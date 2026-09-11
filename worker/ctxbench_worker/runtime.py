"""Clean baseline checkouts and evaluator containers, never solver-visible secrets."""
from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import tarfile
import time
import uuid
import re
import shlex
from pathlib import Path, PurePosixPath

from .datasets import TaskRecord
from .models import ResourcePolicy
from .artifacts import safe_relative_path
from .safe_files import safe_file
from .image_sources import ImageSources
from .diagnostics import step, phase, note, log, docker_event, docker_build


def git(workspace: Path, *arguments: str, data: bytes | None = None) -> bytes:
    note('Git command: ' + ' '.join(arguments) + ' | cwd=' + str(workspace))
    try:
        result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(workspace), *arguments],
                                input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    except subprocess.TimeoutExpired as error:
        if error.stderr:
            log(error.stderr.decode(errors='replace'))
        raise
    # stdout may be an archive, source code or hidden patch. It is not a log.
    if result.stderr:
        log(result.stderr.decode(errors='replace'))
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-3000:])
    return result.stdout


def local_fetch_options(repository: str) -> list[str]:
    """Trust only the operator-selected local source, for this upload-pack process.

    Local Git transports start a separate upload-pack process; the fetch client's
    -c settings alone do not cover ownership checks in that process. Never write
    global configuration or extend this exception to remote/relative addresses.
    """
    candidate = Path(repository)
    if not candidate.is_absolute() or not candidate.is_dir():
        return []
    root = candidate.resolve()
    git_dir = root / '.git'
    if git_dir.is_dir() and not git_dir.is_symlink():
        paths = (root, git_dir)
    elif (root / 'HEAD').is_file() and (root / 'objects').is_dir():
        paths = (root,)  # An explicitly selected bare repository.
    else:
        return []  # Do not follow .git files/symlinks into unrelated directories.
    if any('*' in path.as_posix() for path in paths):
        return []  # safe.directory interprets wildcard suffixes, not literal paths.
    command = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'safe.directory=']
    for path in paths:
        command.extend(['-c', 'safe.directory=' + path.as_posix()])
    command.append('upload-pack')
    return ['--upload-pack=' + shlex.join(command)]


def seal(workspace: Path) -> str:
    git(workspace, "init", "-q")
    git(workspace, "config", "user.name", "CTXBench")
    git(workspace, "config", "user.email", "local@ctxbench.invalid")
    git(workspace, "add", "--all", "--force", "--", ".")
    git(workspace, "commit", "-qm", "Frozen evaluation input", "--allow-empty")
    return git(workspace, "rev-parse", "HEAD").decode().strip()


def extract_baseline(tar: tarfile.TarFile, workspace: Path) -> None:
    """Preserve Git's literal symlinks without ever extracting through one.

    A repository may contain container-specific absolute/dangling symlinks.
    Extract files first and create validated leaf links last. Hard links, special
    files, traversal, duplicate paths and links used as parents are rejected.
    """
    entries = {}
    for member in tar.getmembers():
        path = PurePosixPath(member.name)
        if (path.is_absolute() or '..' in path.parts or not path.parts or
                '.git' in path.parts or '\\' in member.name or ':' in member.name or
                path.as_posix() in entries or not (member.isfile() or member.isdir() or member.issym())):
            raise ValueError(f'Unsafe baseline archive member: {member.name}')
        entries[path.as_posix()] = member
    links = {name for name, member in entries.items() if member.issym()}
    for name in entries:
        if any(parent.as_posix() in links for parent in PurePosixPath(name).parents):
            raise ValueError(f'Baseline archive traverses a symbolic link: {name}')
    tar.extractall(workspace, members=[member for member in entries.values() if not member.issym()], filter='data')
    for name in sorted(links):
        target = workspace.joinpath(*PurePosixPath(name).parts)
        if workspace.resolve() not in target.parent.resolve().parents and target.parent.resolve() != workspace.resolve():
            raise ValueError(f'Baseline link parent escapes workspace: {name}')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(entries[name].linkname)


class Runtime:
    def __init__(self, root: Path, runner):
        self.root, self.runner = root, runner
        self._environment = threading.local()

    @property
    def environment(self):
        return getattr(self._environment, "value", {})

    @contextmanager
    def using_environment(self, value):
        previous = self.environment
        previous_pins = getattr(self._environment, "image_pins", {})
        self._environment.image_pins = {}
        self._environment.value = value.get("document", value) if value else {}
        try:
            yield
        finally:
            self._environment.value = previous
            self._environment.image_pins = previous_pins

    def pin_images(self, pins):
        self._environment.image_pins = dict(pins)

    def require_image_source_harness(self, image):
        if not ImageSources(self.environment).restricted:
            return
        import docker
        client = docker.from_env()
        try:
            if client.images.get(image).labels.get('io.ctxbench.image-sources') != '1':
                raise ValueError('Company image mapping requires an updated official harness image. Rebuild/import the matching application images before starting; no Agent has been called.')
        finally:
            client.close()

    def host_path(self, path: Path) -> str:
        return self.runner._mount_source(path)

    def cancel_grade(self, output: Path) -> None:
        import docker
        client = docker.from_env()
        scope = hashlib.sha256(str(output).encode()).hexdigest()[:20]
        try:
            for container in client.containers.list(all=True, filters={"label": f"io.ctxbench.grade-scope={scope}"}):
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass
        finally:
            client.close()

    def command(self, image: str, command: list[str], *, volumes: dict, output: Path,
                resources: ResourcePolicy, network: str = "none", socket: bool = False, record_logs: bool = True) -> bytes:
        import docker
        client = docker.from_env()
        output.mkdir(parents=True, exist_ok=True)
        if socket:
            volumes["/var/run/docker.sock"] = {"bind": "/var/run/docker.sock", "mode": "rw"}
        container = None
        from .live_logs import ContainerLogs, runtime_secrets
        live_log = None
        log_exit_code = None
        scope = hashlib.sha256(str(output).encode()).hexdigest()[:20]
        self.cancel_grade(output)
        try:
            container = client.containers.run(image, command, detach=True, volumes=volumes,
                environment={"CTXBENCH_GRADER_CPUS": str(resources.cpus), "CTXBENCH_GRADER_MEMORY": f"{resources.memory_gb}g", "CTXBENCH_GRADE_SCOPE": scope,
                             "CTXBENCH_GRADE_IMAGES_PATH": str(output / "child-images.json") if socket else "",
                             "CTXBENCH_LOCAL_IMAGES_ONLY": "1" if ImageSources(self.environment).restricted else "0"},
                network=network, nano_cpus=int(resources.cpus * 1e9), mem_limit=f"{resources.memory_gb}g",
                pids_limit=1024, labels={"io.ctxbench.evaluator": "true", "io.ctxbench.grade-scope": scope},
                **({'log_config': docker.types.LogConfig(type='json-file')} if record_logs else {}),
                **({} if socket else {"cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"]}))
            if record_logs:
                live_log = ContainerLogs(self.root).capture(container, 'evaluator' if socket else 'test',
                    runtime_secrets(getattr(self.runner, 'env_allowlist', ())))
            status = container.wait(timeout=resources.timeout_minutes * 60 + 60)["StatusCode"]
            log_exit_code = status
            log = container.logs()
            if record_logs:
                (output / "evaluator.log").write_bytes(log)
            if status:
                raise RuntimeError(f"Evaluator exited {status}: {log.decode(errors='replace')[-2500:]}")
            return log
        finally:
            if live_log:
                live_log.finish(log_exit_code)
            if container is not None:
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass
            if socket:
                for child in client.containers.list(all=True, filters={"label": f"io.ctxbench.grade-scope={scope}"}):
                    child.remove(force=True)
            client.close()

    @step('Resolve or download Docker image')
    def resolve_image(self, name: str) -> str:
        note('Requested image: ' + name)
        import docker
        sources = ImageSources(self.environment)
        original = name
        name = getattr(self._environment, 'image_pins', {}).get(original, sources.resolve(original))
        client = docker.from_env()
        try:
            try:
                image = client.images.get(name)
            except docker.errors.ImageNotFound:
                # docker load cannot create registry RepoDigests. A verified
                # portable import can bind that immutable reference to a local ID.
                aliases = self.root / "intranet" / "image-references"
                alias_name = hashlib.sha256(name.encode()).hexdigest() + ".json"
                if "@sha256:" in name and (aliases / alias_name).exists():
                    receipt = json.loads(safe_file(aliases, alias_name).read_text(encoding="utf-8"))
                    if receipt.get("reference") != name or not re.fullmatch(r"sha256:[0-9a-f]{64}", receipt.get("id", "")):
                        raise ValueError("Portable image reference receipt is invalid.")
                    image = client.images.get(receipt["id"])
                    image.tag("ctxbench/frozen", image.id.replace(":", "-"))
                    return image.id
                if self.environment.get("offline"):
                    raise ValueError(f"Offline preparation: local image is missing: {name}. Import it first.")
                if name.startswith('sha256:'):
                    raise ValueError('A frozen local image is missing. Restore that exact image; mutable tags will not be downloaded as replacements.')
                sources.require_pull(original)
                with phase('Download Docker image'):
                    for event in client.api.pull(name, stream=True, decode=True):
                        docker_event(event)
                        if event.get('error'):
                            raise RuntimeError(event['error'])
                    image = client.images.get(name)
            # Containerd-backed Docker can discard the last reference when a mutable tag
            # is rebuilt. Keep an explicit immutable tag for every experiment image.
            image.tag("ctxbench/frozen", image.id.replace(":", "-"))
            return image.id
        finally:
            client.close()

    @step('Prepare test image')
    def prepare_test_image(self, task: TaskRecord) -> str:
        """Build once from untouched baseline, never from an agent's candidate patch."""
        if task.image:
            return self.resolve_image(task.image)
        if not task.build:
            raise ValueError("Custom task requires an image or baseline build recipe.")
        if self.environment.get("offline") or ImageSources(self.environment).restricted:
            raise ValueError("Offline preparation requires a prebuilt local test image; adapt the image first.")
        dockerfile = safe_relative_path(str(task.build.get("dockerfile", "Dockerfile")))
        workspace = self.checkout(task, "image-build")
        context_value = str(task.build.get("context", "."))
        context = workspace if context_value == "." else workspace / safe_relative_path(context_value)
        if context.is_symlink() or (context != workspace and workspace not in context.resolve().parents):
            raise ValueError("Build context must remain inside the baseline.")
        source = context / dockerfile
        if source.is_symlink() or not source.is_file() or workspace not in source.resolve().parents:
            raise ValueError("Build Dockerfile must be a regular file inside the baseline repository.")
        import docker
        client = docker.from_env()
        try:
            built = docker_build(client, path=str(context), dockerfile=dockerfile.as_posix(), buildargs=dict(task.build.get("args", {})), rm=True, timeout=3600)
            built.tag("ctxbench/frozen", built.id.replace(":", "-"))
            return built.id
        finally:
            client.close()

    def environment_output(self, task: TaskRecord, dataset_id: str, harness: str, scope: str) -> Path:
        key = hashlib.sha256(f'{dataset_id}:{task.id}:{harness}:{scope}'.encode()).hexdigest()
        return self.root / 'evaluator-environments' / key

    def prepare_agentbench_image(self, task: TaskRecord, dataset: Path, harness: str, resources: ResourcePolicy,
                                *, scope: str = 'standalone') -> str:
        output = self.environment_output(task, dataset.stem, harness, scope)
        source_args = []
        if ImageSources(self.environment).restricted:
            self.require_image_source_harness(harness)
            source_args = ['--source-image', self.resolve_image(task.image)]
        self.command(harness, ['prepare-agentbench', '--dataset', str(dataset), '--instance-id', task.id,
                             '--output', str(output), *source_args],
            volumes={self.host_path(self.root): {'bind': str(self.root), 'mode': 'rw'}},
            output=output, resources=resources, socket=True, network='bridge')
        manifest = json.loads((output / 'environment.json').read_text(encoding='utf-8'))
        if manifest.get('validated') is not True or manifest.get('baseCommit') != task.base_commit or not manifest.get('imageId', '').startswith('sha256:'):
            raise ValueError('Prepared environment does not match the requested baseline.')
        return manifest['imageId']

    @step('Fetch frozen Git baseline')
    def baseline(self, task: TaskRecord) -> tuple[Path, str]:
        note('Repository: ' + task.repository + ' | baseline=' + task.base_commit)
        key = hashlib.sha256(f"{task.repository}@{task.base_commit}".encode()).hexdigest()
        source = self.root / "sources" / key
        source.mkdir(parents=True, exist_ok=True)
        if not (source / ".git").exists():
            git(source, "init", "-q")
            git(source, "remote", "add", "origin", task.repository)
        try:
            git(source, "cat-file", "-e", f"{task.base_commit}^{{commit}}")
        except RuntimeError:
            if self.environment.get("offline"):
                raise ValueError(f"Offline preparation: baseline {task.base_commit} is missing. Import a resource bundle first.")
            mirror = next((item["mirror"] for item in self.environment.get("gitMirrors", []) if item["repository"] == task.repository), "origin")
            local_options = local_fetch_options(task.repository if mirror == 'origin' else mirror)
            git(source, "fetch", "--depth=1", *local_options, mirror, task.base_commit)
        # Portable baselines intentionally omit parent objects. `git show` can
        # traverse parents even with -s; read the commit's own timestamp instead.
        raw_commit = git(source, "cat-file", "-p", task.base_commit)
        committer = next((line for line in raw_commit.split(b"\n\n", 1)[0].splitlines() if line.startswith(b"committer ")), None)
        if committer is None:
            raise ValueError("Baseline commit has no committer timestamp.")
        timestamp, offset = committer.rsplit(b" ", 2)[-2:]
        if not re.fullmatch(rb"[+-][0-9]{4}", offset):
            raise ValueError("Invalid baseline commit timezone.")
        minutes = (int(offset[1:3]) * 60 + int(offset[3:])) * (-1 if offset.startswith(b"-") else 1)
        cutoff = datetime.fromtimestamp(int(timestamp), timezone(timedelta(minutes=minutes))).isoformat()
        return source, cutoff

    @step('Create clean baseline checkout')
    def checkout(self, task: TaskRecord, label: str) -> Path:
        source, _ = self.baseline(task)
        workspace = self.root / "repositories" / f"{label}-{uuid.uuid4().hex[:8]}"
        workspace.mkdir(parents=True)
        archive = workspace.parent / f"{workspace.name}.tar"
        archive.write_bytes(git(source, "archive", "--format=tar", task.base_commit))
        try:
            with tarfile.open(archive) as tar:
                extract_baseline(tar, workspace)
            # No source Git history, remotes, future objects or target PR refs enter an agent mount.
            seal(workspace)
        finally:
            archive.unlink(missing_ok=True)
        return workspace

    def evaluator_workspace(self, label: str, files: dict[str, str]) -> Path:
        workspace = self.root / "repositories" / f"{label}-{uuid.uuid4().hex[:8]}"
        workspace.mkdir(parents=True)
        for name, content in files.items():
            (workspace / name).write_text(content, encoding="utf-8")
        seal(workspace)
        return workspace

    def import_parquet(self, path: Path) -> list[dict]:
        relative = path.resolve().relative_to((self.root / "datasets").resolve())
        output = self.root / "imports" / uuid.uuid4().hex
        try:
            raw = self.command("ctxbench/official-harness:0.1.0", ["catalog", "--dataset", f"/datasets/{relative.as_posix()}"],
                volumes={self.host_path(self.root / "datasets"): {"bind": "/datasets", "mode": "ro"}},
                output=output, resources=ResourcePolicy(timeout_minutes=10), record_logs=False)
            return json.loads(raw)
        finally:
            if output.is_dir() and not any(output.iterdir()):
                output.rmdir()

    def grade(self, task: TaskRecord, dataset_path: Path, patch: Path, output: Path,
              resources: ResourcePolicy, harness_image: str, *, environment_image: str | None = None) -> dict:
        started = time.monotonic()
        if task.ci:
            raise ValueError('CI: remote cases require the dedicated CI grader, not the local test runner.')
        if task.source in {"swebench", "agentbench"}:
            # Legacy experiments may also have digest-pinned original images;
            # only an explicit prepared environment enables the new protocol.
            environment_args = ['--environment-image', environment_image] if environment_image else []
            self.command(harness_image, [f"grade-{task.source}", "--dataset", str(dataset_path),
                "--instance-id", task.id, "--patch", str(patch), "--output", str(output), *environment_args],
                volumes={self.host_path(self.root): {"bind": str(self.root), "mode": "rw"}},
                output=output, resources=resources, socket=True, network="bridge")
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            if not isinstance(summary.get("resolved"), bool):
                raise ValueError("Official harness did not return a boolean resolution.")
            observed = output / "child-images.json"
            if observed.exists():
                summary["graderImageDigests"] = json.loads(observed.read_text())
        else:
            workspace = self.checkout(task, "grader")
            if patch.stat().st_size:
                git(workspace, "apply", "--binary", "--whitespace=nowarn", "-", data=patch.read_bytes())
            if task.hidden_test_patch:
                git(workspace, "apply", "--binary", "--whitespace=nowarn", "-", data=task.hidden_test_patch.encode())
            import docker
            client = docker.from_env()
            container = None
            workspace_owner = None
            from .live_logs import ContainerLogs, runtime_secrets
            live_log = None
            log_exit_code = None
            try:
                image = task.image
                if not image:
                    raise ValueError("Custom test image must be frozen during preparation.")
                self.cancel_grade(output)
                command = list(task.test_command)
                if client.images.get(image).labels.get('io.ctxbench.project-validated') == '1':
                    # Same clean dependency filesystem as the Agent, but no Agent request,
                    # credentials or model invocation. Only initialize dependency links.
                    command = ['/opt/ctxbench-pi/node', '/opt/ctxbench/project-entrypoint.mjs', '--test-command', json.dumps(command)]
                    from .runner import _chown_tree
                    workspace_owner = workspace.stat()
                    _chown_tree(workspace, 10001, 10001)
                container = client.containers.run(image, command, entrypoint="", working_dir="/workspace",
                    detach=True, volumes={self.host_path(workspace): {"bind": "/workspace", "mode": "rw"}},
                    network="none", nano_cpus=int(resources.cpus * 1e9), mem_limit=f"{resources.memory_gb}g",
                    pids_limit=1024, cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
            log_config=docker.types.LogConfig(type='json-file'),
                    labels={"io.ctxbench.evaluator": "true", "io.ctxbench.grade-scope": hashlib.sha256(str(output).encode()).hexdigest()[:20]})
                live_log = ContainerLogs(self.root).capture(container, 'test',
                    runtime_secrets(getattr(self.runner, 'env_allowlist', ())))
                exit_code = container.wait(timeout=resources.timeout_minutes * 60)["StatusCode"]
                log_exit_code = exit_code
                output.mkdir(parents=True, exist_ok=True)
                (output / "evaluator.log").write_bytes(container.logs())
                summary = {"resolved": exit_code == 0, "exitCode": exit_code, "benchmark": "custom", "instanceId": task.id, "graderImageDigests": [image]}
            finally:
                if live_log:
                    live_log.finish(log_exit_code)
                if container is not None:
                    try:
                        container.remove(force=True)
                    except docker.errors.NotFound:
                        pass
                client.close()
                if workspace_owner is not None:
                    _chown_tree(workspace, workspace_owner.st_uid, workspace_owner.st_gid)
        summary["durationSeconds"] = time.monotonic() - started
        (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

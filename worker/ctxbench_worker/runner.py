from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Protocol

from .models import RunResult, RunSpec
from .safe_files import safe_file

ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
DEFAULT_SECRET_ALLOWLIST = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "XIAOMI_TOKEN_PLAN_CN_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "GITHUB_TOKEN",
    }
)


class Runner(Protocol):
    def run(self, spec: RunSpec) -> RunResult: ...


def selected_environment(names: tuple[str, ...], allowlist: frozenset[str]) -> dict[str, str]:
    invalid = [name for name in names if not ENV_NAME.fullmatch(name) or name not in allowlist]
    if invalid:
        raise ValueError(f"Environment variables are not allowlisted: {', '.join(invalid)}")
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise ValueError(f"Configure these runtime variables first: {', '.join(missing)}")
    return {name: os.environ[name] for name in names if name in os.environ}


def _within(root: Path, candidate: str) -> Path:
    resolved = Path(candidate).resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Path escapes configured root: {candidate}")
    return resolved


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    """Set tree ownership without following repository symlinks."""
    if os.name != "posix":
        return
    os.chown(path, uid, gid, follow_symlinks=False)
    for directory, names, files in os.walk(path, followlinks=False):
        current = Path(directory)
        for name in (*names, *files):
            os.chown(current / name, uid, gid, follow_symlinks=False)


class MockRunner:
    """Deterministic adapter used for UI and engine tests without a provider."""

    def run(self, spec: RunSpec) -> RunResult:
        started = time.monotonic()
        output = Path(spec.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(f"{spec.run_id}:{spec.mode}".encode()).digest()
        passed = digest[0] % 5 != 0
        result = {
            "schemaVersion": 1,
            "runId": spec.run_id,
            "mode": spec.mode,
            "mock": True,
            "testsPassed": passed if spec.mode == "grade" else None,
            "inputTokens": 20_000 + int.from_bytes(digest[1:3], "big") % 10_000,
            "outputTokens": 2_000 + int.from_bytes(digest[3:5], "big") % 4_000,
        }
        (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (output / "trajectory.jsonl").write_text(
            json.dumps({"type": "mock_run", "runId": spec.run_id}) + "\n", encoding="utf-8"
        )
        return RunResult(
            run_id=spec.run_id,
            status="completed",
            exit_code=0,
            duration_seconds=time.monotonic() - started,
            output_dir=str(output),
            metadata=result,
        )


class DockerRunner:
    """Container adapter; Docker complexity stays behind the Runner seam."""

    def __init__(
        self,
        repositories_root: str | Path,
        artifacts_root: str | Path,
        request_root: str | Path,
        env_allowlist: frozenset[str] = DEFAULT_SECRET_ALLOWLIST,
        api_network: str = "ctxbench-agent",
        worker_data_root: str | Path | None = None,
        host_data_root: str | None = None,
    ):
        self.repositories_root = Path(repositories_root).resolve()
        self.artifacts_root = Path(artifacts_root).resolve()
        self.request_root = Path(request_root).resolve()
        self.env_allowlist = env_allowlist
        self.api_network = api_network
        self.worker_data_root = Path(worker_data_root).resolve() if worker_data_root else None
        self.host_data_root = (
            PurePosixPath(host_data_root.replace("\\", "/")) if host_data_root else None
        )
        if (self.worker_data_root is None) != (self.host_data_root is None):
            raise ValueError("Worker and host data roots must be configured together.")
        for path in (self.repositories_root, self.artifacts_root, self.request_root):
            path.mkdir(parents=True, exist_ok=True)
        if self.worker_data_root is not None:
            managed_owner = self.worker_data_root.stat()
            for path in (self.repositories_root, self.artifacts_root, self.request_root):
                _within(self.worker_data_root, str(path))
                if os.name == "posix":
                    os.chown(
                        path,
                        managed_owner.st_uid,
                        managed_owner.st_gid,
                        follow_symlinks=False,
                    )

    def _mount_source(self, candidate: Path) -> str:
        """Translate a worker-container path to the Docker host bind source."""
        resolved = candidate.resolve()
        if self.worker_data_root is None or self.host_data_root is None:
            return str(resolved)
        try:
            relative = resolved.relative_to(self.worker_data_root)
        except ValueError as error:
            raise ValueError(f"Docker bind source is outside the shared data root: {candidate}") from error
        return str(self.host_data_root.joinpath(*relative.parts))

    def cancel(self, run_id: str) -> None:
        import docker
        client = docker.from_env()
        try:
            for container in client.containers.list(filters={"label": f"io.ctxbench.run={run_id}"}):
                container.kill()
        finally:
            client.close()

    def run(self, spec: RunSpec) -> RunResult:
        try:
            import docker
            from docker.errors import ContainerError, DockerException
        except ImportError as error:
            raise RuntimeError("Install the pinned Docker SDK to use DockerRunner.") from error

        workspace = _within(self.repositories_root, spec.workspace)
        output = _within(self.artifacts_root, spec.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        request_path = _within(self.request_root, str(self.request_root / f"{spec.run_id}.json"))
        request_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "runId": spec.run_id,
                    "mode": spec.mode,
                    "prompt": spec.prompt,
                    "model": asdict(spec.model),
                    "timeoutSeconds": spec.resources.timeout_minutes * 60,
                    "contextPaths": list(spec.context_paths),
                    "metadata": spec.metadata,
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

        environment = selected_environment(spec.env_names, self.env_allowlist)
        secrets = tuple(environment.values())
        def redact(value: str) -> str:
            for secret in sorted(secrets, key=len, reverse=True):
                value = value.replace(secret, "[REDACTED]")
            return value
        network_mode = (
            "none"
            if spec.resources.network == "offline"
            else self.api_network
            if spec.resources.network == "api-only"
            else "bridge"
        )
        if spec.resources.network == "api-only":
            environment.update(
                {
                    "HTTP_PROXY": "http://ctxbench-egress-proxy:3128",
                    "HTTPS_PROXY": "http://ctxbench-egress-proxy:3128",
                    "NO_PROXY": "localhost,127.0.0.1",
                }
            )
        volumes = {
            self._mount_source(workspace): {"bind": "/workspace", "mode": "rw"},
            self._mount_source(output): {"bind": "/ctxbench/output", "mode": "rw"},
            self._mount_source(request_path): {"bind": "/ctxbench/request.json", "mode": "ro"},
        }
        if spec.skill_path:
            skill = Path(spec.skill_path).resolve()
            if spec.mode != "generate-context":
                raise ValueError("Skills may only be mounted into isolated context-generation runs.")
            volumes[self._mount_source(skill)] = {
                "bind": "/home/ctxbench/.pi/agent/skills/ctxbench-generate-context",
                "mode": "ro",
            }

        started = time.monotonic()
        client = docker.from_env()
        repositories_owner = self.repositories_root.stat()
        artifacts_owner = self.artifacts_root.stat()
        container = None
        workspace_assigned = False
        output_assigned = False
        try:
            _chown_tree(workspace, 10001, 10001)
            workspace_assigned = True
            _chown_tree(output, 10001, 10001)
            output_assigned = True
            container = client.containers.run(
                spec.image,
                detach=True,
                name=f"ctxbench-{spec.run_id[:40]}",
                working_dir="/workspace",
                user="10001:10001",
                environment=environment,
                volumes=volumes,
                network=network_mode,
                nano_cpus=int(spec.resources.cpus * 1_000_000_000),
                mem_limit=f"{spec.resources.memory_gb}g",
                pids_limit=1024,
                security_opt=["no-new-privileges:true"],
                cap_drop=["ALL"],
                labels={"io.ctxbench.run": spec.run_id, "io.ctxbench.mode": spec.mode},
            )
            wait = container.wait(timeout=spec.resources.timeout_minutes * 60 + 30)
            exit_code = int(wait.get("StatusCode", 1))
            logs = redact(container.logs(stdout=True, stderr=True, tail=4000).decode(errors="replace"))
            safe_file(output, "container.log").write_text(logs, encoding="utf-8")
            for artifact in output.rglob("*"):
                if artifact.is_file() and not artifact.is_symlink() and artifact.suffix in {".json", ".jsonl", ".log", ".patch", ".md", ".txt"}:
                    artifact = safe_file(output, artifact.relative_to(output).as_posix())
                    content = artifact.read_text(encoding="utf-8", errors="replace")
                    cleaned = redact(content)
                    if cleaned != content:
                        artifact.write_text(cleaned, encoding="utf-8")
            return RunResult(
                run_id=spec.run_id,
                status="completed" if exit_code == 0 else "failed",
                exit_code=exit_code,
                duration_seconds=time.monotonic() - started,
                output_dir=str(output),
                failure=None if exit_code == 0 else "Agent container exited unsuccessfully; see container.log.",
            )
        except Exception as error:
            if container is not None:
                try:
                    container.kill()
                except DockerException:
                    pass
            return RunResult(
                run_id=spec.run_id,
                status="timed-out" if "timed out" in str(error).lower() else "failed",
                exit_code=124 if "timed out" in str(error).lower() else 1,
                duration_seconds=time.monotonic() - started,
                output_dir=str(output),
                failure=redact(f"{type(error).__name__}: {error}"),
            )
        finally:
            request_path.unlink(missing_ok=True)
            if container is not None:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass
            if workspace_assigned:
                _chown_tree(workspace, repositories_owner.st_uid, repositories_owner.st_gid)
            if output_assigned:
                _chown_tree(output, artifacts_owner.st_uid, artifacts_owner.st_gid)
            client.close()

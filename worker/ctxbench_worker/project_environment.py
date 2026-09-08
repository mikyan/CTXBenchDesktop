"""Task-blind, cached project dependencies for coding and knowledge generation.

Never hand an evaluator image directly to an Agent. Export its merged filesystem,
discard repository trees/history/evaluator scripts/caches, then build FROM scratch.
Only the clean baseline is mounted at execution time. Docker layers, image history,
labels, environment and default entrypoints from the evaluator are not inherited.
"""
from __future__ import annotations

import copy
import hashlib
import json
import posixpath
import re
import shutil
import tarfile
import tempfile
from collections import deque
from pathlib import Path, PurePosixPath

from .environments import public_image_config

VERSION = 1
IMPLEMENTATION = hashlib.sha256((Path(__file__).read_text(encoding='utf-8') + '\n' + Path(__file__).with_name('project_entrypoint.mjs').read_text(encoding='utf-8')).encode()).hexdigest()
DEPENDENCIES = ('.venv', 'venv', 'node_modules')
ENV_KEYS = {'PATH', 'VIRTUAL_ENV', 'PYTHONPATH', 'PYTHONHOME', 'CONDA_PREFIX',
            'CONDA_DEFAULT_ENV', 'UV_PROJECT_ENVIRONMENT', 'JAVA_HOME', 'GOPATH',
            'GOROOT', 'LD_LIBRARY_PATH', 'PKG_CONFIG_PATH', 'RUSTUP_HOME', 'CARGO_HOME'}


def project_root(config):
    root = config.get('WorkingDir', '').rstrip('/') or '/workspace'
    # Do not erase a system directory because an arbitrary image names it as cwd.
    parts = PurePosixPath(root).parts
    if (not root.startswith('/') or '..' in parts or any(c in root for c in '\r\n\0')
            or root.startswith(('/opt/ctxbench', '/home/ctxbench', '/workspace/'))
            or (len(parts) > 1 and parts[1] in {'bin', 'sbin', 'usr', 'lib', 'lib64', 'etc', 'var', 'root', 'tmp', 'proc', 'sys', 'dev', 'run'})
            or root in {'/bin', '/sbin', '/usr', '/usr/local', '/lib', '/lib64', '/etc', '/opt', '/var', '/home', '/root', '/tmp'}):
        raise ValueError('Project image needs a dedicated WORKDIR such as /workspace or /testbed, not a system/adapter directory or a nested /workspace path.')
    return root


def environment_config(config, source_kind='custom'):
    result = {}
    for entry in config.get('Env', []) or []:
        name, _, value = entry.partition('=')
        if name in ENV_KEYS:
            if any(c in value for c in '\0\r\n'):
                raise ValueError('Invalid project runtime environment.')
            result[name] = value
    result.setdefault('PATH', '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin')
    # The official SWE instance images activate testbed from /root/.bashrc.
    # Do not inherit shell startup scripts; preserve that explicit environment
    # through PATH instead. Custom/CTX images retain their recorded activation.
    if source_kind == 'swebench' and '/opt/miniconda3/bin' in result['PATH'].split(':') and not result.get('VIRTUAL_ENV'):
        result.update(CONDA_PREFIX='/opt/miniconda3/envs/testbed', CONDA_DEFAULT_ENV='testbed')
        result['PATH'] = '/opt/miniconda3/envs/testbed/bin:' + result['PATH']
    # Pi uses its own Node binary. Never replace the project's node/python toolchain.
    result['PATH'] = '/opt/ctxbench-pi/bin:' + result['PATH']
    result.update(HOME='/home/ctxbench', PI_NO_UPDATE_NOTIFIER='1', NODE_NO_WARNINGS='1')
    return result


def identity(repository, commit, source, agent, root, environment):
    if not re.fullmatch(r'[0-9a-fA-F]{40}', commit):
        raise ValueError('Project environments require an exact baseline commit.')
    return {'version': VERSION, 'implementation': IMPLEMENTATION, 'repository': repository, 'baseCommit': commit,
            'sourceImage': source, 'agentAdapter': agent, 'projectRoot': root, 'environment': environment}


def _name(member):
    name = member.name.removeprefix('./').rstrip('/')
    if not name or name == '.':
        return ''
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or '\0' in name:
        raise ValueError('Unsafe exported project filesystem path.')
    return name


def sanitize_filesystem(source: Path, destination: Path, root: str, check=lambda: None):
    """Flatten a dependency filesystem, without extracting untrusted paths on host.

    Known dependency folders under the project root are relocated, keeping their
    original absolute paths usable through runtime links. Unknown extra Git trees
    are removed wholesale, rather than merely deleting their .git directories.
    Custom image authors still must keep answers/secrets out of installed packages.
    """
    project = root.lstrip('/')
    roots = {project, 'workspace', 'testbed'}
    with tarfile.open(source) as archive:
        members = archive.getmembers()
        names = {_name(member) for member in members}
        roots.update(name.rsplit('/.git', 1)[0] for name in names if name.endswith('/.git'))
        # Some exports omit the directory entry for .git.
        roots.update(name.split('/.git/', 1)[0] for name in names if '/.git/' in name)
        if any(name in {'', 'usr', 'usr/local', 'opt', 'etc', 'var', 'root', 'home'} for name in roots):
            raise ValueError('Project image contains a Git repository rooted in a system directory; use a dependency-only image.')
        dependencies = [name for name in DEPENDENCIES if f'{project}/{name}' in names]
        dependency_roots = {f'{project}/{name}': f'opt/ctxbench-dependencies/{name}' for name in dependencies}

        def mapped(name):
            parts = PurePosixPath(name).parts
            if (not name or any(part in {'.git', '.hg', '.svn', '.ssh', '.aws', '.azure', '.kube', '.cache', '.docker', '.pi'} for part in parts)
                    or name.startswith(('proc/', 'sys/', 'dev/', 'tmp/', 'run/', 'var/log/', 'var/cache/'))
                    or name in {'proc', 'sys', 'dev', 'tmp', 'run', '.dockerenv', 'etc/hostname', 'etc/hosts', 'etc/resolv.conf'}
                    or name.startswith(('opt/ctxbench', 'home/ctxbench/'))
                    or parts[-1] in {'eval.sh', 'test.patch', 'gold.patch', 'evaluator.json', 'setup_repo.sh', 'setup_env.sh', '.gitconfig', '.netrc', '.npmrc', '.pypirc', '.bash_history', '.env'}
                    or parts[-1].endswith(('.patch', '.diff', '.log'))):
                return None
            # Keep only runtime installations in root's home, not downloads or notebooks.
            if name.startswith('root/') and not name.startswith(('root/.local/bin/', 'root/.local/share/uv/python/')):
                return None
            for old, new in dependency_roots.items():
                if name == old or name.startswith(old + '/'):
                    return new + name[len(old):]
            if any(name == prefix or name.startswith(prefix + '/') for prefix in roots):
                return None
            return name

        written = set()
        with tarfile.open(destination, 'w') as cleaned:
            for index, original in enumerate(members):
                if index % 500 == 0:
                    check()
                name = _name(original)
                target = mapped(name)
                if target is None or not (original.isfile() or original.isdir() or original.issym() or original.islnk()):
                    continue
                if target in written:
                    raise ValueError('Duplicate exported project filesystem entry.')
                member = copy.copy(original)
                member.name = target
                member.pax_headers = {}  # No stale paths, xattrs, capabilities or extended metadata.
                member.mode &= ~0o6000
                if target == 'home/ctxbench' or target.startswith('opt/ctxbench-dependencies/'):
                    member.uid = member.gid = 10001
                if target == 'root':
                    member.mode = 0o755
                if member.islnk():
                    link = mapped(_name(tarfile.TarInfo(member.linkname)))
                    if not link:
                        raise ValueError('Dependency hard link points into removed evaluator material.')
                    member.linkname = link
                elif member.issym():
                    # Relocated venv relative links should keep their original absolute target.
                    resolved = posixpath.normpath(posixpath.join('/' + posixpath.dirname(name), member.linkname))
                    if target != name:
                        member.linkname = resolved
                    if '/.git' in resolved or resolved.startswith(('/proc/', '/sys/')):
                        continue
                cleaned.addfile(member, archive.extractfile(original) if member.isfile() else None)
                written.add(target)
            for directory in ('tmp', 'workspace', 'home/ctxbench', 'opt/ctxbench-dependencies', 'opt/ctxbench-pi/bin'):
                if directory not in written:
                    member = tarfile.TarInfo(directory); member.type = tarfile.DIRTYPE
                    member.mode = 0o1777 if directory == 'tmp' else 0o755
                    member.uid = member.gid = 10001 if directory == 'home/ctxbench' else 0
                    cleaned.addfile(member)
            if root != '/workspace':
                member = tarfile.TarInfo(project); member.type = tarfile.SYMTYPE; member.linkname = '/workspace'; member.mode = 0o777
                cleaned.addfile(member)
    return dependencies


class ProjectEnvironments:
    def __init__(self, runtime, redact=lambda text: text):
        self.runtime, self.redact = runtime, redact

    def _owner(self):
        return hashlib.sha256(self.runtime.host_path(self.runtime.root).encode()).hexdigest()

    def recover_exports(self):
        """Reap only this data directory's stopped export containers after a crash."""
        import docker
        client = docker.from_env()
        try:
            for container in client.containers.list(all=True, filters={'label': 'io.ctxbench.project-owner=' + self._owner()}):
                if container.status in {'created', 'exited', 'dead'}:
                    try:
                        container.remove()
                    except docker.errors.NotFound:
                        pass
        finally:
            client.close()

    def prepare(self, task, source_image, agent_image, *, check=lambda: None, progress=lambda message: None):
        import docker
        client = docker.from_env(timeout=3600)
        container = None
        try:
            source, agent = client.images.get(source_image), client.images.get(agent_image)
            if agent.labels.get('io.ctxbench.agent-kind') != 'pi':
                raise ValueError('Automatic project environments require the current Pi adapter image (agent-kind=pi). Update/import the Agent image under Settings → Application images. For another Agent, provide a ready project-capable adapter and explicitly select as-is mode.')
            for item in (source, agent):
                public_image_config(item.attrs.get('Config', {}), self.redact)
            if source.labels.get('io.ctxbench.project-validated') == '1':
                receipt = json.loads(source.labels.get('io.ctxbench.project-identity', '{}'))
                key = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
                if (receipt.get('version') != VERSION or receipt.get('implementation') != IMPLEMENTATION or receipt.get('repository') != task.repository or receipt.get('baseCommit') != task.base_commit
                        or receipt.get('agentAdapter') != agent.id or source.labels.get('io.ctxbench.project-key') != key):
                    raise ValueError('Imported project environment belongs to another baseline or Agent adapter. Select the original dependency image to prepare a new environment.')
                progress('Reusing the frozen project build environment.')
                return {'imageId': source.id, 'key': key, 'cached': True, 'sourceImage': receipt['sourceImage'], 'projectRoot': receipt['projectRoot']}
            if (source.attrs.get('Os'), source.attrs.get('Architecture')) != (agent.attrs.get('Os'), agent.attrs.get('Architecture')):
                raise ValueError('Project and Agent images must use the same OS and CPU architecture.')
            config = source.attrs.get('Config', {})
            if config.get('Volumes'):
                raise ValueError('Project images with VOLUME declarations cannot be safely flattened. Rebuild a dependency image without VOLUME.')
            root = project_root(config)
            env = environment_config(config, getattr(task, 'source', 'custom'))
            document = identity(task.repository, task.base_commit, source.id, agent.id, root, env)
            key = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
            tag = 'ctxbench/project-agent:' + key
            try:
                cached = client.images.get(tag)
            except docker.errors.ImageNotFound:
                cached = None
            if cached is not None:
                if (cached.labels.get('io.ctxbench.project-key') != key or cached.labels.get('io.ctxbench.project-validated') != '1'
                        or json.loads(cached.labels.get('io.ctxbench.project-identity', '{}')) != document):
                    raise ValueError('Cached Agent environment has an invalid preparation receipt; do not reuse it.')
                progress('Reusing the frozen project build environment.')
                return {'imageId': cached.id, 'key': key, 'cached': True, 'sourceImage': source.id, 'projectRoot': root}
            check()
            stage = self.runtime.root / 'project-environments'
            stage.mkdir(parents=True, exist_ok=True)
            required = (source.attrs.get('Size', 0) + agent.attrs.get('Size', 0)) * 4 + 1024 ** 3
            if shutil.disk_usage(stage).free < required:
                raise ValueError('Insufficient disk space to prepare a project environment. Free space in WSL before retrying; no Agent has started.')
            with tempfile.TemporaryDirectory(prefix='prepare-', dir=stage) as directory:
                folder = Path(directory)
                progress('Exporting the project dependency filesystem; no Agent is running.')
                container = client.containers.create(source.id, entrypoint=['/bin/true'], network_disabled=True,
                    labels={'io.ctxbench.environment-setup': key, 'io.ctxbench.evaluator': 'true', 'io.ctxbench.project-owner': self._owner()})
                with (folder / 'source.tar').open('wb') as stream:
                    for chunk in container.export():
                        check(); stream.write(chunk)
                container.remove(); container = None
                progress('Removing old repositories, history and evaluator material from the Agent environment.')
                dependencies = sanitize_filesystem(folder / 'source.tar', folder / 'rootfs.tar', root, check)
                (folder / 'source.tar').unlink()
                (folder / 'project.json').write_text(json.dumps({'version': VERSION, 'dependencies': dependencies}), encoding='utf-8')
                shutil.copyfile(Path(__file__).with_name('project_entrypoint.mjs'), folder / 'project-entrypoint.mjs')
                # Named local immutable tags avoid registry requests during offline composition.
                donor = 'ctxbench/frozen:' + agent.id.replace(':', '-')
                agent.tag('ctxbench/frozen', agent.id.replace(':', '-'))
                lines = [f'FROM {donor} AS adapter', 'FROM scratch', 'ADD rootfs.tar /',
                    'COPY --from=adapter /usr/local/bin/node /opt/ctxbench-pi/node',
                    'COPY --from=adapter /usr/local/lib/node_modules /opt/ctxbench-pi/lib/node_modules',
                    'COPY --from=adapter /opt/ctxbench /opt/ctxbench',
                    'COPY --from=adapter /usr/bin/rg /usr/bin/rg',
                    'COPY project-entrypoint.mjs /opt/ctxbench/project-entrypoint.mjs',
                    'COPY project.json /opt/ctxbench-project.json',
                    *['ENV ' + name + '=' + json.dumps(value) for name, value in env.items()],
                    'RUN printf \'#!/bin/sh\\nexec /opt/ctxbench-pi/node /opt/ctxbench-pi/lib/node_modules/@earendil-works/pi-coding-agent/dist/cli.js "$@"\\n\' > /opt/ctxbench-pi/bin/pi && chmod 755 /opt/ctxbench-pi/bin/pi',
                    'WORKDIR /workspace', 'USER 10001:10001',
                    *(['RUN test -x /opt/miniconda3/envs/testbed/bin/python'] if env.get('CONDA_PREFIX') == '/opt/miniconda3/envs/testbed' else []),
                    'RUN /opt/ctxbench-pi/node --version && pi --version && git --version && rg --version && /bin/bash -c true && test -w "$HOME"',
                    'LABEL io.ctxbench.workflow="1" io.ctxbench.agent-args="1" io.ctxbench.agent-kind="pi"',
                    'LABEL io.ctxbench.project-validated="1" io.ctxbench.project-key=' + json.dumps(key),
                    'LABEL io.ctxbench.project-identity=' + json.dumps(json.dumps(document, sort_keys=True)),
                    'ENTRYPOINT ["/opt/ctxbench-pi/node", "/opt/ctxbench/project-entrypoint.mjs"]']
                (folder / 'Dockerfile').write_text('\n'.join(lines) + '\n', encoding='utf-8')
                progress('Adding the installed Pi adapter and validating tools offline. First preparation can take several minutes.')
                # Stream the build so cancellation and progress remain observable.
                recent = deque(maxlen=15)
                for event in client.api.build(path=str(folder), tag=tag, rm=True, forcerm=True, pull=False,
                                               network_mode='none', decode=True, timeout=3600):
                    check()
                    if event.get('error'):
                        raise RuntimeError('Project Agent environment build failed: ' + self.redact(event['error'])[-1000:] + '\n' + '\n'.join(recent)[-3000:])
                    line = event.get('stream', '').strip()
                    if line:
                        recent.append(self.redact(line)[-1000:])
                        progress(self.redact(line)[-1000:])
                check()
                built = client.images.get(tag)
                if built.labels.get('io.ctxbench.project-key') != key or built.labels.get('io.ctxbench.project-validated') != '1':
                    raise ValueError('Project Agent environment did not complete validation.')
                return {'imageId': built.id, 'key': key, 'cached': False, 'sourceImage': source.id, 'projectRoot': root}
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass
            client.close()

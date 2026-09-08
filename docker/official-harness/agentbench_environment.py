"""Build evaluator-only dependencies once, before any paid agent work.

Only baseline checkout/setup enters the networked child. Candidate patches, test
runners, gold patches and Provider credentials are never copied into that child.
The resulting image is retained by digest and used by offline test containers.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import uuid
from pathlib import Path

VERSION = 1
ENV_KEYS = ('PATH', 'VIRTUAL_ENV', 'PYTHONPATH', 'PYTHONHOME', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV', 'UV_PROJECT_ENVIRONMENT')
ENV_MARKER = 'CTXBENCH_SETUP_ENV='
# Baseline-specific dependency compatibility, not candidate/test modifications.
# This baseline pins aiohttp 3.9.5 but leaves openai>=1.55.3 unbounded; the 2026
# openai 3.x import crashes against that aiohttp. LiteLLM requires >=1.68.2.
# Record the additional pin in the cache identity and evaluation provenance.
DEPENDENCY_CONSTRAINTS = {
    ('qodo-ai/pr-agent', '7b4c50c717df393a392aec3b7f4146f5fb701503'): ['openai==1.78.1'],
}


def setup_identity(row, source_image):
    commit = row['base_sha']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('AgentBench setup requires an exact baseline commit.')
    commands = row['setup_commands']
    if not isinstance(commands, list) or any(not isinstance(cmd, str) for cmd in commands):
        raise ValueError('AgentBench setup commands must be a list of strings.')
    return {'version': VERSION, 'sourceImage': source_image, 'repository': row['base_repo'],
            'baseCommit': commit, 'setupCommands': commands,
            'dependencyConstraints': DEPENDENCY_CONSTRAINTS.get((row['base_repo'], commit), [])}


def setup_script(identity):
    capture = "import os,json; print(" + repr(ENV_MARKER) + "+json.dumps({k:os.environ[k] for k in " + repr(ENV_KEYS) + " if k in os.environ}))"
    # One shell is essential: a separate `docker exec` for each command loses
    # `source .venv/bin/activate`, `cd`, exports and other setup state.
    constraints = identity.get('dependencyConstraints', [])
    configure = []
    if constraints:
        write = "from pathlib import Path; Path('/tmp/ctxbench-dependencies.txt').write_text(" + repr('\n'.join(constraints) + '\n') + ")"
        configure = ['python -c ' + shlex.quote(write), 'export PIP_CONSTRAINT=/tmp/ctxbench-dependencies.txt']
    return '\n'.join(['set -e', 'cd /testbed',
                      f"git checkout --detach {shlex.quote(identity['baseCommit'])}",
                      f"git reset --hard {shlex.quote(identity['baseCommit'])}",
                      *configure, *identity['setupCommands'], 'python -c ' + shlex.quote(capture)])


def parse_environment(log):
    lines = [line[len(ENV_MARKER):] for line in log.splitlines() if line.startswith(ENV_MARKER)]
    if len(lines) != 1:
        raise RuntimeError('Environment setup did not finish successfully.')
    environment = json.loads(lines[0])
    if not isinstance(environment, dict) or 'PATH' not in environment:
        raise ValueError('Environment setup did not return PATH.')
    if any(key not in ENV_KEYS or not isinstance(value, str) or any(c in value for c in '\n\r\0')
           for key, value in environment.items()):
        raise ValueError('Invalid environment setup result.')
    return environment


def prepare_environment(row, output: Path, source_image=None):
    import docker
    client = docker.from_env()
    container = None
    output.mkdir(parents=True, exist_ok=True)
    try:
        try:
            if source_image and not re.fullmatch(r'sha256:[0-9a-f]{64}', source_image):
                raise ValueError('Prepared source must be a frozen local image ID.')
            source = client.images.get(source_image or row['docker_image'])
        except docker.errors.ImageNotFound:
            if source_image or os.environ.get('CTXBENCH_LOCAL_IMAGES_ONLY') == '1':
                raise ValueError('The frozen source image is missing locally; registry fallback is disabled.') from None
            source = client.images.pull(row['docker_image'])
        source.tag('ctxbench/frozen', source.id.replace(':', '-'))
        identity = setup_identity(row, source.id)
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        tag = 'ctxbench/agentbench-env:' + key
        try:
            prepared = client.images.get(tag)
        except docker.errors.ImageNotFound:
            cpus = float(os.environ.get('CTXBENCH_GRADER_CPUS', '4'))
            memory = os.environ.get('CTXBENCH_GRADER_MEMORY', '8g')
            scope = os.environ.get('CTXBENCH_GRADE_SCOPE', 'standalone')
            # No mounts, socket or injected environment. Baseline setup may fetch
            # dependencies; this is NOT a test execution stage.
            container = client.containers.run(source.id, ['bash', '-lc', setup_script(identity)],
                entrypoint='', working_dir='/testbed', detach=True, network='bridge',
                nano_cpus=int(cpus * 1e9), mem_limit=memory, pids_limit=1024,
                labels={'io.ctxbench.grade-scope': scope, 'io.ctxbench.environment-setup': key})
            try:
                status = container.wait(timeout=1800)['StatusCode']
            finally:
                (output / 'setup.log').write_bytes(container.logs())
            log = (output / 'setup.log').read_text(errors='replace')
            if status:
                raise RuntimeError(f'AgentBench baseline dependency setup exited {status}; no agent was started. ' + log[-4000:])
            environment = parse_environment(log)
            changes = ['ENV ' + name + '=' + json.dumps(value) for name, value in environment.items()]
            prepared = container.commit(repository='ctxbench/agentbench-env', tag=key, changes='\n'.join(changes),
                conf={'Labels': {'io.ctxbench.environment-key': key, 'io.ctxbench.environment-version': str(VERSION),
                                 'io.ctxbench.environment-identity': json.dumps(identity, sort_keys=True)}})
        if prepared.labels.get('io.ctxbench.environment-key') != key:
            raise ValueError('Cached evaluator environment does not match its baseline/setup identity.')
        prepared.tag('ctxbench/frozen', prepared.id.replace(':', '-'))
        manifest = {**identity, 'key': key, 'imageId': prepared.id}
        temporary = output / f'.environment-{uuid.uuid4().hex}.tmp'
        temporary.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        temporary.replace(output / 'environment.json')
        return manifest
    finally:
        if container is not None:
            container.remove(force=True)
        client.close()


def require_prepared_environment(image, row):
    """Refuse arbitrary images or another baseline, including on direct CLI calls."""
    import docker
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise ValueError('AgentBench grading requires a frozen, prepared environment image.')
    client = docker.from_env()
    try:
        prepared = client.images.get(image)
        key = prepared.labels.get('io.ctxbench.environment-key')
        version = prepared.labels.get('io.ctxbench.environment-version')
        receipt = json.loads(prepared.labels.get('io.ctxbench.environment-identity', '{}'))
        if version != str(VERSION) or not receipt:
            raise ValueError('AgentBench evaluator image lacks a valid preparation receipt.')
        expected = setup_identity(row, receipt.get('sourceImage'))
        if receipt != expected or key != hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest():
            raise ValueError('AgentBench evaluator image belongs to another baseline or setup.')
    finally:
        client.close()

"""Real Docker live-console acceptance. No external services or paid model calls.

Run in a worker image with /source read-only, Docker socket and a NEW empty
/tmp/ctxbench-live-* directory mounted at the same host/container path (argv[1]).
Builds only a unique, offline thin Pi overlay; never replaces application tags.
"""
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import time
import socket
import threading
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

sys.path.insert(0, '/source')
import docker
import uvicorn
from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.datasets import TaskRecord
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.history import GitHubClient
from worker.ctxbench_worker.live_logs import ContainerLogs, log_scope
from worker.ctxbench_worker.diagnostics import observed, phase, details, docker_build
from worker.ctxbench_worker.models import ModelConfig, ResourcePolicy, RunSpec
from worker.ctxbench_worker.runner import DockerRunner
from worker.ctxbench_worker.runtime import Runtime, seal, git

root = Path(sys.argv[1]).resolve()
assert root.parent == Path('/tmp') and root.name.startswith('ctxbench-live-') and not list(root.iterdir())
prefix = root.name + '-'
secret = 'synthetic-live-console-credential-not-real'
os.environ['LIVE_FIXTURE_KEY'] = secret
os.environ['CTXBENCH_TEST_DELAY_SECONDS'] = '00003'
runner = DockerRunner(root / 'repositories', root / 'runs', root / 'requests',
    worker_data_root=root, host_data_root=str(root), env_allowlist=frozenset({'LIVE_FIXTURE_KEY', 'CTXBENCH_TEST_DELAY_SECONDS'}))
runtime = Runtime(root, runner)
engine = create_mock_engine(root)
engine.runner = runner
api_socket = socket.socket()
api_socket.bind(('127.0.0.1', 0))
api_server = uvicorn.Server(uvicorn.Config(create_app(engine, GitHubClient(None)), lifespan='off', log_level='error'))
api_thread = threading.Thread(target=lambda: api_server.run(sockets=[api_socket]), daemon=True)
api_thread.start()
while not api_server.started:
    assert api_thread.is_alive()
    time.sleep(.01)

def get(path):
    with urlopen('http://127.0.0.1:' + str(api_socket.getsockname()[1]) + '/v1' + path, timeout=5) as response:
        return json.load(response)
store = ContainerLogs(root)
client = docker.from_env()
resources = ResourcePolicy(cpus=1, memory_gb=1, timeout_minutes=1, network='offline')
model = ModelConfig('mock', 'deterministic', 'off', 5000000)
pool = ThreadPoolExecutor(max_workers=1)
reports = []
pi_image = None


def observe(name, action, marker):
    scope = prefix + name
    def execute():
        with log_scope(operationId=scope, experimentId='live-acceptance', benchmarkRunId=scope):
            return action()
    started = time.monotonic()
    future = pool.submit(execute)
    try:
        while True:
            sessions = get('/container-logs?operationId=' + scope)['sessions']
            if sessions:
                page = get('/container-logs/' + sessions[0]['id'])
                assert secret not in page['content']
                if marker in page['content']:
                    assert not future.done(), f'{name}: output only appeared after task completion'
                    assert page['state'] == 'streaming'
                    assert client.containers.get(page['containerId']).status == 'running', f'{name}: Docker container already exited'
                    latency = time.monotonic() - started
                    break
            assert time.monotonic() - started < 20, name
            if future.done():
                raise AssertionError(f'{name}: task finished without live marker: {future.result()}')
            time.sleep(.05)
    finally:
        result = future.result(timeout=30)
    final = get('/container-logs/' + page['id'])
    assert final['state'] == 'ended', final
    assert secret not in final['content']
    assert final['benchmarkRunId'] == scope and final['experimentId'] == 'live-acceptance'
    reports.append({'case': name, 'visibleWhileRunning': True, 'firstOutputSeconds': round(latency, 2), 'exitCode': final['exitCode']})
    print(json.dumps(reports[-1]), flush=True)
    return result, final


def workspace(name):
    path = root / 'repositories' / name
    path.mkdir()
    (path / 'README.md').write_text('Frozen, task-blind fixture.\n')
    seal(path)
    return path


class PreparationFixture:
    def __init__(self):
        self.root = root

    @observed('Prepare queued operation')
    def run(self, label, action):
        with phase(label):
            return action()


def pre_agent_failure(name, label, action, first, last):
    scope = prefix + name
    try:
        with log_scope(operationId=scope):
            PreparationFixture().run(label, action)
    except Exception as error:
        diagnostic = details(error)
        assert diagnostic and diagnostic['stage'] == label
        assert diagnostic['agentStarted'] is False
    else:
        raise AssertionError('Expected a real preparation failure')
    sessions = get('/container-logs?operationId=' + scope)['sessions']
    assert len(sessions) == 1 and sessions[0]['source'] == 'service'
    chunks, offset = [], 0
    while True:
        page = get('/container-logs/' + sessions[0]['id'] + '?offset=' + str(offset))
        chunks.append(page['content']); offset = page['nextOffset']
        if not page['hasMore']:
            break
    full = ''.join(chunks)
    assert first in full and last in full and 'Traceback' in full
    assert secret not in full and page['state'] == 'ended'
    reports.append({'case': name, 'agentStarted': False, 'failedStep': label, 'completePages': len(chunks), 'originalErrorPreserved': True})
    print(json.dumps(reports[-1]), flush=True)


try:
    # Genuine host-side Git failure, before a coding container can be created.
    git_tree = workspace('bad-commit')
    pre_agent_failure('git-before-agent', 'Fetch frozen Git baseline',
        lambda: git(git_tree, 'cat-file', '-e', 'f' * 40 + '^{commit}'), 'cat-file', 'fatal:')
    # A real failed offline Docker build with more than a page of stdout.
    failed_dockerfile = io.BytesIO(('FROM ctxbench/worker:0.1.0\n'
        'RUN python3 -u -c "print(\'EARLY_BUILD\'); print(\'x\' * 140000); print(\'LAST_BUILD_ERROR\'); raise SystemExit(17)"\n').encode())
    pre_agent_failure('build-before-agent', 'Prepare test image',
        lambda: docker_build(client, fileobj=failed_dockerfile, pull=False, network_mode='none', rm=True, forcerm=True),
        'EARLY_BUILD', 'LAST_BUILD_ERROR')
    # A local-only thin layer exercises exactly the modified Pi entrypoint/runtime.
    files = {}
    for name in ['entrypoint.mjs', 'workflow-runtime.mjs', 'console-stream.mjs', 'agent-args.mjs', 'mock-pi.mjs',
                 'console-stream.integration.mjs', 'workflow-runtime.integration.mjs']:
        files[name] = (Path('/source/docker/agent-pi') / name).read_bytes()
    files['Dockerfile'] = ('FROM ctxbench/agent-pi:0.1.0\n'
        'COPY --chown=10001:10001 *.mjs /opt/ctxbench/\n'
        'LABEL io.ctxbench.workflow="1" io.ctxbench.agent-args="1" io.ctxbench.agent-kind="pi"\n').encode()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name); info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    archive.seek(0)
    tag = 'ctxbench/live-console-test:' + root.name.removeprefix('ctxbench-live-').lower()
    pi_image, _ = client.images.build(fileobj=archive, custom_context=True, tag=tag, pull=False, network_mode='none', rm=True)
    print('Built isolated offline Pi test layer (application image tags unchanged).', flush=True)
    client.containers.run(pi_image.id, ['node', '--test', '/opt/ctxbench/console-stream.integration.mjs', '/opt/ctxbench/workflow-runtime.integration.mjs'],
        entrypoint='', network='none', remove=True)
    print('Pi console and workflow Node integration tests passed.', flush=True)

    source = workspace('custom-source')
    baseline = workspace('grading-source')
    commit = seal(baseline)
    command = ['python3', '-u', '-c', "import os,time; from pathlib import Path; print('CUSTOM_READY 中文',flush=True); s=os.environ['LIVE_FIXTURE_KEY']; print(s[:18],end='',flush=True); time.sleep(.1); print(s[18:],flush=True); time.sleep(3); Path('answer.py').write_text('VALUE=42\\n'); print('CUSTOM_DONE',flush=True)"]
    spec = RunSpec(prefix + 'custom', 'solve', 'ctxbench/worker:0.1.0', str(source), str(root / 'runs/custom'), 'Unchanged prompt', model, resources,
        env_names=('LIVE_FIXTURE_KEY',), metadata={'commandAgent': {'image': 'ctxbench/worker:0.1.0', 'command': command}})
    result, page = observe('custom', lambda: runner.run(spec), 'CUSTOM_READY')
    assert result.status == 'completed' and page['exitCode'] == 0
    assert '[REDACTED]' in page['content']
    assert not client.containers.list(all=True, filters={'name': 'ctxbench-' + spec.run_id[:40]})
    assert store.read(page['id'])['content'], 'Logs must survive automatic container removal'
    assert secret not in (root / 'runs/custom/container.log').read_text()
    assert json.loads((root / 'runs/custom/result.json').read_text())['usageAvailable'] is False

    # Grading gets only its separate candidate checkout. Check true and false verdicts.
    for expected in [42, 99]:
        task = TaskRecord('grade-fixture', str(baseline), commit, 'Unchanged prompt', 'ctxbench/worker:0.1.0', None,
            ('python3', '-u', '-c', f"import time; print('TEST_READY',flush=True); time.sleep(3); from answer import VALUE; assert VALUE == {expected}"))
        result, page = observe('grade-' + str(expected), lambda: runtime.grade(task, root / 'unused.json', root / 'runs/custom/graded.patch', root / ('grading-' + str(expected)), resources, ''), 'TEST_READY')
        assert result['resolved'] is (expected == 42)
        assert page['exitCode'] == (0 if expected == 42 else 1)

    result, page = observe('runtime-command', lambda: runtime.command('ctxbench/worker:0.1.0', ['python3', '-u', '-c', "import time; print('COMMAND_READY',flush=True); time.sleep(3)"],
        volumes={}, output=root / 'command-output', resources=resources), 'COMMAND_READY')
    assert b'COMMAND_READY' in result

    for mode in ['generate-context', 'solve']:
        tree = workspace(mode)
        output = root / 'runs' / mode
        pi_spec = RunSpec(prefix + mode, mode, pi_image.id, str(tree), str(output), 'Synthetic baseline-only prompt', model, resources,
            env_names=('LIVE_FIXTURE_KEY', 'CTXBENCH_TEST_DELAY_SECONDS'),
            workflow={'setupCommands': ['printf "SETUP_READY %s\\n" "$LIVE_FIXTURE_KEY"', 'sleep 3'], 'steps': [{'prompt': None}]})
        result, page = observe(mode, lambda: runner.run(pi_spec), 'SETUP_READY')
        assert result.status == 'completed', result
        assert '[REDACTED]' in page['content'] and 'agent_start' in page['content']
        assert json.loads((output / 'result.json').read_text())['modelInvocations'] == 1
        if mode == 'generate-context':
            assert (output / 'context/files/.ctx/architecture.md').is_file()
        assert secret not in (output / 'container.log').read_text()

    failed_spec = replace(spec, run_id=prefix + 'failure', workspace=str(workspace('failure')), output_dir=str(root / 'runs/failure'),
        metadata={'commandAgent': {'image': 'ctxbench/worker:0.1.0', 'command': ['/bin/sh', '-c', 'printf "FAILURE_READY\\n"; sleep 3; exit 17']}})
    result, page = observe('failure', lambda: runner.run(failed_spec), 'FAILURE_READY')
    assert result.status == 'failed' and result.exit_code == page['exitCode'] == 17
    timed_spec = replace(failed_spec, run_id=prefix + 'timeout', workspace=str(workspace('timeout')), output_dir=str(root / 'runs/timeout'),
        resources=replace(resources, timeout_minutes=.05), metadata={'commandAgent': {'image': 'ctxbench/worker:0.1.0', 'command': ['/bin/sh', '-c', 'printf "TIMEOUT_READY\\n"; sleep 20']}})
    result, page = observe('timeout', lambda: runner.run(timed_spec), 'TIMEOUT_READY')
    assert result.exit_code == page['exitCode'] == 124
    assert secret.encode() not in store.path.read_bytes()
    (root / 'summary.json').write_text(json.dumps({'status': 'passed', 'realDocker': True, 'providerCalls': 0, 'cases': reports}, indent=2))
    print(json.dumps({'status': 'passed', 'cases': len(reports), 'root': str(root), 'providerCalls': 0}), flush=True)
finally:
    pool.shutdown(wait=True)
    api_server.should_exit = True
    api_thread.join(timeout=5)
    api_socket.close()
    if pi_image is not None:
        client.images.remove(tag)
    client.close()

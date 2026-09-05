"""Crash/restore acceptance using a separate Docker Worker, never a real Provider.

Run with the data/socket/source mounts and control network from container-smoke.py.
No production Worker is stopped; only the uniquely labelled acceptance Worker is killed.
"""
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import docker

sys.path.insert(0, '/source/worker')
from ctxbench_worker.runtime import seal

client = docker.from_env()
suffix = uuid.uuid4().hex[:10]
root = Path('/var/lib/ctxbench') / ('acceptance-resilience-' + suffix)
root.mkdir()
source = root / 'fixture'
source.mkdir()
(source / 'README.md').write_text('Isolated crash-recovery acceptance fixture.')
commit = seal(source)
name = 'ctxbench-resilience-' + suffix
worker = None
interrupted_ids = []
profile = {'provider': 'mock', 'model': 'deterministic', 'thinking': 'off', 'maxTokens': 1000}
resources = {'cpus': 1, 'memoryGb': 1, 'timeoutMinutes': 2, 'network': 'offline'}
env_names = ['CTXBENCH_TEST_DELAY_SECONDS']


def request(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    query = urllib.request.Request(f'http://{name}:48173/v1{path}', data=data,
                                   headers={'Content-Type': 'application/json'} if data else {})
    try:
        with urllib.request.urlopen(query, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'{path}: {error.code} {error.read().decode()}') from error


def wait(check, label, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.1)
    diagnostics = worker.logs(tail=30).decode(errors='replace') if worker is not None else ''
    raise AssertionError('Timed out: ' + label + '\n' + diagnostics)


def health():
    try:
        return request('/health')['status'] == 'healthy'
    except (OSError, RuntimeError):
        return False


def stages():
    with sqlite3.connect(f'file:{root}/ctxbench.sqlite3?mode=ro', uri=True) as connection:
        return [json.loads(row[0]) for row in connection.execute("SELECT payload_json FROM documents WHERE kind='stages'")]


def agent_for(experiment):
    snapshot = request('/snapshot?compact=true')
    for run in snapshot['runs']:
        if run['experimentId'] == experiment and run['status'] == 'running' and run.get('solverRunId'):
            if client.containers.list(filters={'label': 'io.ctxbench.run=' + run['solverRunId']}):
                return run
    return None


def finished(experiment):
    snapshot = request('/snapshot')
    record = next(item for item in snapshot['experiments'] if item['id'] == experiment)
    if record['status'] == 'failed':
        raise AssertionError([item for item in snapshot['runs'] if item['experimentId'] == experiment])
    if record['status'] == 'completed':
        runs = [item for item in snapshot['runs'] if item['experimentId'] == experiment]
        assert all(item['testsPassed'] and item['evidenceIntegrity'] == 'verified' for item in runs)
        return runs
    return None


try:
    worker = client.containers.run('ctxbench/worker:0.1.0', name=name, detach=True,
        network='ctxbench_control', labels={'io.ctxbench.acceptance': suffix},
        environment={'CTXBENCH_DATA_DIR': str(root), 'CTXBENCH_HOST_DATA_DIR': str(root), 'CTXBENCH_RUNNER': 'docker',
                     'CTXBENCH_BUNDLED_SKILL_DIR': '/opt/ctxbench/skills/ctxbench-generate-context',
                     'CTXBENCH_EXTRA_ENV_ALLOWLIST': env_names[0],
                     # Long numeric form avoids treating a common digit as a redaction secret.
                     env_names[0]: '00000000000000000000000000000003'},
        volumes={str(root): {'bind': str(root), 'mode': 'rw'},
                 '/var/run/docker.sock': {'bind': '/var/run/docker.sock', 'mode': 'rw'}})
    wait(health, 'isolated Worker health', 30)
    request('/token-budgets', {'id': 'resilience', 'limitTokens': 1000000, 'provider': 'mock', 'model': 'deterministic'})
    dataset = request('/datasets', {'name': 'Crash fixture', 'benchmark': 'custom', 'rows': [{
        'id': 'resilience', 'repository': str(source), 'baseCommit': commit, 'prompt': 'Complete the infrastructure fixture.',
        'image': 'ctxbench/agent-pi:0.1.0',
        'test': {'command': ['python3', '-c', "from pathlib import Path; assert Path('ctxbench_mock_solution.txt').is_file(); assert Path('ctxbench_mock_staged.txt').is_file()"]}}]})
    preparation = request('/prepare/context', {'dataset': dataset['id'], 'taskId': 'resilience', 'model': profile,
        'resources': resources, 'envNames': env_names, 'agentImage': 'ctxbench/agent-pi:0.1.0', 'budgetId': 'resilience'})
    wait(lambda: next((stage for stage in stages() if stage.get('operationId') == preparation['id'] and stage['status'] == 'running'), None), 'builder started')
    request(f"/operations/{preparation['id']}/pause", {})
    request(f"/operations/{preparation['id']}/resume", {})
    wait(lambda: request(f"/operations/{preparation['id']}")['status'] == 'completed', 'builder pause/resume')
    assert len([stage for stage in stages() if stage['id'].startswith('context:')]) == 1

    body = {'name': 'Crash and restore', 'benchmark': 'custom', 'dataset': dataset['id'], 'taskIds': ['resilience'],
            'arms': ['none', 'skill-generated'], 'repeats': 2, 'seed': 42, 'model': profile,
            'profiles': {role: profile for role in ('builder', 'solver', 'constraintMiner', 'constraintJudge')},
            'resources': resources, 'agentImage': 'ctxbench/agent-pi:0.1.0', 'envNames': env_names, 'prepareOnly': True, 'budgetId': 'resilience'}
    preflight = request('/preflight', body)
    assert preflight['runs'] == 4
    experiment = request('/experiments', body)
    wait(lambda: next(item for item in request('/experiments') if item['id'] == experiment['id'])['status'] == 'ready', 'prepare barrier')
    request(f"/experiments/{experiment['id']}/resume", {})
    interrupted = wait(lambda: agent_for(experiment['id']), 'solver container started')
    interrupted_ids.append(interrupted['solverRunId'])
    worker.kill(signal='SIGKILL')
    assert worker.labels['io.ctxbench.acceptance'] == suffix
    worker.start()
    wait(health, 'health after forced restart', 30)
    results = wait(lambda: finished(experiment['id']), 'crash recovery completed')
    recovered = next(item for item in results if item['id'] == interrupted['id'])
    assert recovered['solverRunId'] != interrupted['solverRunId']
    assert not client.containers.list(all=True, filters={'label': 'io.ctxbench.run=' + interrupted['solverRunId']})
    assert len([stage for stage in stages() if stage['id'].startswith('context:')]) == 1

    body.update(name='Immediate cancel/retry', repeats=1, prepareOnly=False)
    retry = request('/experiments', body)
    wait(lambda: agent_for(retry['id']), 'cancel fixture solver started')
    request(f"/experiments/{retry['id']}/cancel", {})
    request(f"/experiments/{retry['id']}/retry", {})
    retry_results = wait(lambda: finished(retry['id']), 'immediate retry completed')
    saved = json.dumps(request('/snapshot'), sort_keys=True)
    worker.restart(timeout=10)
    wait(health, 'final restart health', 30)
    assert saved == json.dumps(request('/snapshot'), sort_keys=True)
    budget = request('/token-budgets/resilience')
    assert budget['reportedTokens'] > 0 and budget['reservedTokens'] == 0
    assert budget['unconfirmedTokens'] >= 1000 and budget['chargedTokens'] >= budget['reportedTokens']
    summary = {'passed': True, 'root': str(root), 'independentPauseResume': True,
               'forcedWorkerKillRecovered': True, 'orphanAgentRemoved': True, 'freshSolverWorkspace': True,
               'generationStages': 1, 'completedRuns': len(results) + len(retry_results),
               'immediateCancelRetry': True, 'evidenceAfterRestartUnchanged': True, 'sharedBudget': budget}
    (root / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
finally:
    if worker is not None:
        if worker.labels.get('io.ctxbench.acceptance') == suffix:
            worker.remove(force=True)
    # Remove only still-running agents named by this fixture's own stage records.
    if (root / 'ctxbench.sqlite3').exists():
        for run_id in set(interrupted_ids + [stage['runId'] for stage in stages()]):
            for container in client.containers.list(all=True, filters={'label': 'io.ctxbench.run=' + run_id}):
                container.remove(force=True)
    client.close()

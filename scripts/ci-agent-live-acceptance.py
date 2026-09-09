"""Explicit paid Pi/Docker -> real GitHub CI acceptance through the worker API.

Project-specific, isolated scratch data and test refs. Does not edit candidate
code, generate context, reset budgets, restart the desktop worker or push master.
Credentials are captured into memory and sent only to loopback API endpoints.
"""
import argparse
import hashlib
import json
import subprocess
import time
import uuid
from pathlib import Path

import requests


BASE = '15676d44d236c2e4b01afb2d2774c4f4446b0585'
IMAGE = 'sha256:d9d1566b02efff953dc8d5489461f111a39a6e3d321c9a3fe73c7b5c5de79992'
KEY_NAME = 'XIAOMI_TOKEN_PLAN_CN_API_KEY'
CAMPAIGN = 'mimo-v25-100m-20260905'
STAGE_LIMIT = 5_000_000
MARGIN = 2_359_296
ENVELOPE = 2 * (STAGE_LIMIT + MARGIN)


def command(argv, *, timeout=60, input=None):
    result = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=timeout, input=input)
    if result.returncode:
        # Never expose captured command output: it may contain a credential.
        raise RuntimeError('Subprocess failed (output withheld): ' + argv[0])
    return result.stdout.strip()


def emit(event, **value):
    print(json.dumps({'event': event, **value}, ensure_ascii=True), flush=True)


def save_text(path, content):
    # Preserve API patch bytes on Windows; CRLF conversion would break receipts.
    path.write_text(content, encoding='utf-8', newline='')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-paid', action='store_true', required=True)
    parser.add_argument('--execute-remote', action='store_true', required=True)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--distro', default='Ubuntu')
    parser.add_argument('--port', default=48174, type=int)
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    secrets = []

    def save(name, value):
        content = json.dumps(value, ensure_ascii=False, indent=2)
        assert not any(secret in content for secret in secrets), 'Credential detected; report not saved.'
        save_text(root / name, content)

    def wsl(*argv, **kwargs):
        return command(['wsl', '-d', args.distro, '--', *argv], **kwargs)

    token = command(['gh', 'auth', 'token', '--hostname', 'github.com'])
    key = wsl('docker', 'exec', 'ctxbench-ctxbench-worker-1', 'python', '-c',
              "import os; print(os.environ.get('" + KEY_NAME + "', ''))")
    assert token and key, 'Existing GitHub and MiMo credentials are required.'
    secrets.extend([token, key])
    identity = command(['gh', 'api', 'user', '--jq', '.login'])
    assert identity == 'mikyan', 'Only the reviewed owner/repository is in scope.'
    before = command(['gh', 'api', 'repos/mikyan/CTXBenchDesktop/git/ref/heads/master', '--jq', '.object.sha'])
    source = wsl('wslpath', '-a', Path(__file__).resolve().parents[1].as_posix())
    scratch = wsl('mktemp', '-d', '/tmp/ctxbench-ci-agent-live-XXXXXXXX')
    assert scratch.startswith('/tmp/ctxbench-ci-agent-live-')
    unique = uuid.uuid4().hex[:12]
    container = 'ctxbench-ci-agent-api-' + unique
    child_budget = 'ci-agent-' + unique
    envelope_id = 'ci-agent-envelope-' + unique
    api = requests.Session()
    api.trust_env = False
    base_url = 'http://127.0.0.1:' + str(args.port)

    def request(method, path, body=None):
        response = api.request(method, base_url + path, json=body, timeout=60)
        if not response.ok:
            detail = response.text
            for secret in secrets:
                detail = detail.replace(secret, '[REDACTED]')
            raise RuntimeError(f'{method} {path}: {response.status_code}: {detail[:1200]}')
        return response.json()

    def production_budget(action, metadata=None):
        code = """
import json, sys
from pathlib import Path
from ctxbench_worker.database import Database
from ctxbench_worker.budgets import TokenBudget
b = TokenBudget(Database(Path('/var/lib/ctxbench/ctxbench.sqlite3')))
p = json.load(sys.stdin)
if p['action'] == 'reserve':
    r = b.reserve(p['campaign'], p['id'], p['limit'], mode='acceptance-envelope', experiment_id=None, output=p['output'])
else:
    r = b.settle(p['id'], p['metadata'])
print(json.dumps({'attempt': r, 'budget': b.snapshot(p['campaign'])}))
"""
        value = {'action': action, 'campaign': CAMPAIGN, 'id': envelope_id,
                 'limit': ENVELOPE - MARGIN, 'output': str(root), 'metadata': metadata}
        return json.loads(wsl('docker', 'exec', '-i', 'ctxbench-ctxbench-worker-1',
                              'python', '-c', code, input=json.dumps(value)))

    evidence = {}

    def capture_containers():
        code = """
import docker, json, sys
root = sys.argv[1]
rows = []
for c in docker.from_env().containers.list(filters={'label':'io.ctxbench.mode=solve'}):
    a = c.attrs
    mounts = a.get('Mounts', [])
    if not any(m.get('Source', '').startswith(root + '/') for m in mounts): continue
    cfg, host = a['Config'], a['HostConfig']
    rows.append({'id':c.id, 'image':a['Image'], 'runId':cfg['Labels']['io.ctxbench.run'],
        'user':cfg['User'], 'network':host['NetworkMode'], 'memory':host['Memory'],
        'nanoCpus':host.get('NanoCpus'), 'cpuQuota':host.get('CpuQuota'), 'cpuPeriod':host.get('CpuPeriod'),
        'capDrop':host.get('CapDrop'), 'mounts':[{k:m.get(k) for k in ('Source','Destination','RW')} for m in mounts],
        'environmentNames':sorted(x.split('=',1)[0] for x in cfg.get('Env',[]))})
print(json.dumps(rows))
"""
        rows = json.loads(wsl('docker', 'exec', container, 'python', '-c', code, scratch))
        for row in rows:
            assert KEY_NAME in row['environmentNames']
            assert not {'GH_TOKEN', 'GITHUB_TOKEN'} & set(row['environmentNames'])
            assert not any(m['Destination'] == '/var/run/docker.sock' for m in row['mounts'])
            if row['id'] not in evidence:
                emit('real-agent-container', **row)
            evidence[row['id']] = row
        save('containers.json', list(evidence.values()))

    started = reserved = settled = False
    experiment = None
    report = {'kind': 'real-agent-docker-github-ci', 'repository': 'mikyan/CTXBenchDesktop',
              'baselineCommit': BASE, 'defaultCommitBefore': before, 'dataRoot': scratch,
              'apiContainer': container, 'apiUrl': base_url, 'provider': 'xiaomi-token-plan-cn',
              'model': 'mimo-v2.5', 'stageTokenLimit': STAGE_LIMIT, 'knowledgeGenerated': False,
              'childBudgetId': child_budget, 'campaignEnvelopeId': envelope_id, 'verified': False}
    save('report.json', report)
    try:
        wsl('docker', 'run', '-d', '--name', container,
            '-p', f'127.0.0.1:{args.port}:48173',
            '-v', source + ':/source:ro', '-v', scratch + ':' + scratch,
            '-v', '/var/run/docker.sock:/var/run/docker.sock',
            '-e', 'CTXBENCH_DATA_DIR=' + scratch, '-e', 'CTXBENCH_HOST_DATA_DIR=' + scratch,
            '-e', 'CTXBENCH_BUNDLED_SKILL_DIR=/source/skills/ctxbench-generate-context',
            '-e', 'CTXBENCH_RUNNER=docker', '-e', 'PYTHONPATH=/source/worker',
            '--workdir', '/source', '--entrypoint', 'python', 'ctxbench/worker:0.1.0',
            '-m', 'uvicorn', 'ctxbench_worker.api:app', '--host', '0.0.0.0', '--port', '48173', '--no-access-log')
        started = True
        deadline = time.monotonic() + 60
        while True:
            try:
                assert request('GET', '/v1/health')['runner'] == 'DockerRunner'
                break
            except requests.ConnectionError:
                if time.monotonic() > deadline: raise
                time.sleep(1)
        connection = request('POST', '/v1/ci/connections', {
            'name': 'Real Pi to GitHub acceptance', 'provider': 'github-actions',
            'apiUrl': 'https://api.github.com', 'repository': 'mikyan/CTXBenchDesktop', 'workflow': 'ci.yml'})
        request('POST', f"/v1/ci/connections/{connection['id']}/credential", {'token': token})
        request('POST', '/v1/runtime/credentials', {'name': KEY_NAME, 'value': key})
        request('POST', '/v1/token-budgets', {'id': child_budget, 'limitTokens': ENVELOPE,
                'provider': 'xiaomi-token-plan-cn', 'model': 'mimo-v2.5'})
        case = request('POST', '/v1/library/cases', {
            'name': 'Real Pi: repair similarity score regression', 'benchmark': 'custom',
            'row': {'id': 'repair-similarity-regression', 'repository': 'https://github.com/mikyan/CTXBenchDesktop.git',
                'baseCommit': BASE, 'image': IMAGE,
                'prompt': 'The SWE-Shield compatible candidate similarity score regressed and no longer responds to its inputs. Restore the documented scoring behavior while preserving the public interface. Do not modify tests or CI/workflow definitions. Verify the fix with the relevant unit tests.',
                'test': {'ci': {'connectionId': connection['id'], 'requiredJobs': ['backend-tests'],
                    'reportArtifact': 'ctxbench-junit', 'minTests': 100, 'timeoutMinutes': 15, 'allowRemoteExecution': True}}}})
        selection = request('GET', '/v1/library/selections/' + case['id'])
        model = {'provider': 'xiaomi-token-plan-cn', 'model': 'mimo-v2.5', 'thinking': 'high', 'maxTokens': STAGE_LIMIT}
        spec = {'name': 'Real Docker Pi + MiMo + GitHub CI acceptance', 'benchmark': 'custom',
            'dataset': case['id'], 'datasetRevision': selection['revision'], 'taskIds': ['repair-similarity-regression'],
            'arms': ['none', 'developer-historical'], 'repeats': 1, 'model': model,
            'profiles': {name: model for name in ('builder', 'solver', 'constraintMiner', 'constraintJudge')},
            'agentImage': IMAGE, 'projectEnvironment': False,
            'resources': {'cpus': 2, 'memoryGb': 4, 'timeoutMinutes': 30, 'network': 'api-only'},
            'seed': 42, 'envNames': [KEY_NAME], 'prepareOnly': False, 'evaluateConstraints': False,
            'budgetId': child_budget}
        save('case.json', case)
        save('experiment-request.json', spec)
        reservation = production_budget('reserve')
        reserved = True
        save('campaign-reservation.json', reservation)
        experiment = request('POST', '/v1/experiments', spec)
        report.update(experimentId=experiment['id'], caseId=case['id'])
        save('report.json', report)
        emit('queued-normal-api', **report)
        deadline = time.monotonic() + 60 * 95
        while time.monotonic() < deadline:
            snapshot = request('GET', '/v1/snapshot?compact=true')
            current = next(e for e in snapshot['experiments'] if e['id'] == experiment['id'])
            runs = [r for r in snapshot['runs'] if r['experimentId'] == experiment['id']]
            capture_containers()
            emit('progress', status=current['status'], runs=[{k:r.get(k) for k in
                ('id', 'arm', 'status', 'solverRunId', 'totalTokens', 'testsPassed', 'failure', 'ci')} for r in runs])
            if current['status'] in {'completed', 'failed', 'cancelled', 'paused'}:
                break
            time.sleep(10)
        else:
            raise TimeoutError('Acceptance deadline exceeded; cancel only this experiment.')
        snapshot = request('GET', '/v1/snapshot')
        save('snapshot.json', snapshot)
        runs = [r for r in snapshot['runs'] if r['experimentId'] == experiment['id']]
        report['runs'] = runs
        outputs = []
        for run in runs:
            run_id = run.get('solverRunId')
            if not run_id: continue
            for name in ['result.json', 'graded.patch', 'trajectory.jsonl', 'container.log', 'agent.stderr.log']:
                content, offset = '', 0
                while True:
                    try:
                        page = request('GET', f'/v1/run-output?runId={run_id}&file={name}&offset={offset}')
                    except RuntimeError as error:
                        if ': 404:' in str(error): break
                        raise
                    content += page['content']
                    if not page['hasMore']: break
                    offset = page['nextOffset']
                if content:
                    assert not any(secret in content for secret in secrets)
                    save_text(root / f'{run_id}-{name}', content)
                if name == 'result.json' and content: outputs.append(json.loads(content))
                if name == 'graded.patch':
                    run['candidatePatchBytes'] = len(content.encode())
                    run['candidatePatchSha256'] = hashlib.sha256(content.encode()).hexdigest()
        child = request('GET', '/v1/token-budgets/' + child_budget)
        report['tokenBudget'] = child
        assert child['reservedTokens'] == 0, 'Paid child stages must settle before the parent envelope.'
        # This is an aggregate budget receipt, not a fabricated Agent result.
        # Confirm only when every child attempt confirmed its own model usage.
        aggregate = {'runId': envelope_id, 'budgetProtocolVersion': 1,
            'status': 'completed' if child['unconfirmedTokens'] == 0 else 'failed',
            'cumulativeTokens': child['reportedTokens'], 'source': 'isolated-child-budget-aggregate'}
        report['campaignSettlement'] = production_budget('settle', aggregate)
        settled = True
        after = command(['gh', 'api', 'repos/mikyan/CTXBenchDesktop/git/ref/heads/master', '--jq', '.object.sha'])
        report.update(defaultCommitAfter=after, defaultUnchanged=after == before,
                      modelInvocations=sum(o.get('modelInvocations', 0) for o in outputs))
        report['verified'] = (len(runs) == len(outputs) == len(evidence) == 2
            and all(r['status'] == 'completed' and r.get('testsPassed') is True and r.get('mock') is False
                    and r.get('candidatePatchBytes', 0) > 0 for r in runs)
            and all(o.get('status') == 'completed' and o.get('modelInvocations', 0) > 0
                    and o.get('cumulativeTokens', 0) > 0 for o in outputs)
            and len({r.get('pairingHash') for r in runs}) == 1
            and report['defaultUnchanged'])
        save('report.json', report)
        emit('finished', verified=report['verified'], modelInvocations=report['modelInvocations'],
             reportedTokens=child['reportedTokens'], report=str(root / 'report.json'))
        return 0 if report['verified'] else 1
    except Exception as error:
        detail = f'{type(error).__name__}: {error}'
        for secret in secrets: detail = detail.replace(secret, '[REDACTED]')
        report['error'] = detail
        save('report.json', report)
        emit('failed', error=detail, report=str(root / 'report.json'))
        raise SystemExit(1) from None
    finally:
        if started:
            if experiment:
                try:
                    request('POST', '/v1/experiments/' + experiment['id'] + '/cancel') if not settled else None
                except Exception:
                    pass
            # Stop only the unique service created above; scratch evidence remains.
            wsl('docker', 'stop', '-t', '15', container)
            wsl('docker', 'rm', container)
        if reserved and not settled:
            # No zero-cost assumption after an interruption; retain full envelope.
            save('campaign-unconfirmed.json', production_budget('settle'))


if __name__ == '__main__':
    raise SystemExit(main())

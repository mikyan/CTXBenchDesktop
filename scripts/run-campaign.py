"""Budget-limited, restartable official-dataset campaign; --execute spends tokens.

The plan is frozen before execution. Only public task metadata determines order.
Each task prepares context once, then runs both arms twice. Existing matching
constraint packages are explicitly recorded; missing history is not a neutral vote.
"""
import argparse
import hashlib
import json
import os
import random
import re
import shutil
import sys
import time
import urllib.request
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))
from ctxbench_worker.checkpoints import atomic_json


@contextmanager
def campaign_lock(root):
    """One coordinator owns a plan; OS locks also release after process death."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'coordinator.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            lock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            unlock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            lock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            unlock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        try:
            lock()
        except OSError as error:
            raise RuntimeError('Campaign is already owned by another coordinator; no requests were sent.') from error
        try:
            yield
        finally:
            unlock()


def request(api, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    query = urllib.request.Request(api + path, data=data, headers={'Content-Type': 'application/json'} if data else {})
    with urllib.request.urlopen(query, timeout=60) as response:
        return json.load(response)


def freeze_plan(api, budget_id, limit, root, agent_image, *, stage_tokens=None, campaign_id=None, source_plan=None):
    if stage_tokens is not None and (type(stage_tokens) is not int or stage_tokens < 1):
        raise ValueError('Stage token allowance must be positive.')
    if campaign_id is not None and not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', campaign_id):
        raise ValueError('Invalid campaign ID.')
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'plan.json'
    if path.exists():
        plan = json.loads(path.read_text())
        if plan['budgetId'] != budget_id or plan['limitTokens'] != limit or plan['agentImage'] != agent_image:
            raise ValueError('Existing campaign authorization cannot be changed.')
        if campaign_id is not None and plan.get('campaignId', plan['budgetId']) != campaign_id:
            raise ValueError('Use a new state directory for a new campaign ID.')
        if stage_tokens is not None and any(plan.get(role, plan['solverTokens']) != stage_tokens for role in ('solverTokens', 'builderTokens', 'minerTokens', 'judgeTokens')):
            raise ValueError('Use a new campaign for changed stage allowances; old results remain frozen.')
        return plan
    if source_plan is not None:
        source = json.loads(source_plan.read_text())
        if source['budgetId'] != budget_id or source['agentImage'] != agent_image:
            raise ValueError('A continuation must retain its shared budget and Agent image.')
        if not campaign_id or campaign_id == source.get('campaignId', source['budgetId']):
            raise ValueError('Changed allowances require a distinct campaign ID.')
        plan = {**source, 'version': 2, 'campaignId': campaign_id, 'limitTokens': limit,
                'sourcePlanHash': hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()}
        plan.update({role: stage_tokens or 5000000 for role in ('solverTokens', 'builderTokens', 'minerTokens', 'judgeTokens')})
        atomic_json(root, 'plan.json', plan)
        return plan
    queues = {}
    packages = request(api, '/constraint-packages')
    for benchmark in ('ctxbench', 'swebench'):
        count = 138 if benchmark == 'ctxbench' else 500
        datasets = [item for item in request(api, '/datasets') if item['benchmark'] == benchmark and item['count'] == count]
        if len(datasets) != 1:
            raise ValueError(f'Expected one frozen {benchmark} dataset with {count} tasks.')
        dataset = datasets[0]
        groups = defaultdict(list)
        for task in request(api, f"/datasets/{dataset['id']}/tasks"):
            matches = [package for package in packages if package['count'] and
                       task['repository'] == f"https://github.com/{package['repository']}.git" and task['baseCommit'] == package['commit']]
            package = sorted(matches, key=lambda item: item['id'])[0] if matches else None
            groups[task['repository']].append({'benchmark': benchmark, 'dataset': dataset['id'], 'taskId': task['id'],
                'repository': task['repository'], 'baseCommit': task['baseCommit'],
                'constraintPackageId': package['id'] if package else None,
                'constraintHistoryVersion': (package.get('historyVersion') or 1) if package else None})
        rng = random.Random(42)
        for group in groups.values():
            group.sort(key=lambda item: item['taskId'])
            rng.shuffle(group)
        repositories = sorted(groups)
        rng.shuffle(repositories)
        ordered = []
        while any(groups.values()):
            for repository in repositories:
                if groups[repository]:
                    ordered.append(groups[repository].pop())
        # These known compatibility cases are a disclosed smoke prefix, not a
        # representative sample selected from candidate outcomes or gold patches.
        smoke = 'opshin_opshin-28' if benchmark == 'ctxbench' else 'pallets__flask-5014'
        ordered.sort(key=lambda item: item['taskId'] != smoke)
        queues[benchmark] = ordered
    tasks = []
    for index in range(max(map(len, queues.values()))):
        for benchmark in ('ctxbench', 'swebench'):
            if index < len(queues[benchmark]):
                tasks.append(queues[benchmark][index])
    plan = {'version': 2, 'campaignId': campaign_id or budget_id, 'budgetId': budget_id, 'limitTokens': limit, 'provider': 'xiaomi-token-plan-cn',
            'model': 'mimo-v2.5', 'seed': 42, 'repeats': 2, 'agentImage': agent_image,
            **{role: stage_tokens or 5000000 for role in ('solverTokens', 'builderTokens', 'minerTokens', 'judgeTokens')},
            'order': 'two disclosed compatibility cases, then seeded repository round-robin, alternating datasets',
            'constraintPolicy': 'explicit matching frozen packages only; new mining is deferred pending GitHub API quota',
            'tasks': tasks}
    atomic_json(root, 'plan.json', plan)
    return plan


def body_for(plan, item, ordinal):
    profile = {'provider': plan['provider'], 'model': plan['model'], 'thinking': 'high', 'maxTokens': plan['solverTokens']}
    package = item['constraintPackageId']
    return {'name': f"{plan.get('campaignId', plan['budgetId'])} [{ordinal + 1:03}] {item['benchmark']} {item['taskId']}",
            'benchmark': item['benchmark'], 'dataset': item['dataset'], 'taskIds': [item['taskId']],
            'arms': ['none', 'skill-generated'], 'repeats': plan['repeats'], 'seed': plan['seed'],
            'model': profile, 'profiles': {'solver': profile, 'builder': {**profile, 'maxTokens': plan['builderTokens']},
                'constraintMiner': {**profile, 'maxTokens': plan.get('minerTokens', plan['solverTokens'])}, 'constraintJudge': {**profile, 'maxTokens': plan['judgeTokens']}},
            'agentImage': plan['agentImage'], 'budgetId': plan['budgetId'],
            'resources': {'cpus': 4, 'memoryGb': 8, 'timeoutMinutes': 45, 'network': 'api-only'},
            'envNames': ['XIAOMI_TOKEN_PLAN_CN_API_KEY'], 'prepareOnly': False,
            'evaluateConstraints': bool(package), 'constraintPackages': {item['taskId']: package} if package else {}}


def execute(api, plan, root, host_volume, stop_after):
    fingerprint = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    state_path = root / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'index': 0, 'results': [], 'planHash': fingerprint}
    if state['planHash'] != fingerprint:
        raise ValueError('Campaign plan changed after execution started.')
    request(api, '/token-budgets', {key: plan[key] for key in ('provider', 'model', 'limitTokens')} | {'id': plan['budgetId']})
    def save(status):
        state.update(status=status, updatedAt=time.time(), budget=request(api, '/token-budgets/' + plan['budgetId']))
        atomic_json(root, 'state.json', state)
    while state['index'] < len(plan['tasks']):
        if stop_after and state['index'] >= stop_after:
            save('smoke_prefix_complete')
            return
        if len(state['results']) >= 3 and all(result['gradedRuns'] == 0 for result in state['results'][-3:]):
            save('infrastructure_failures_paused')
            return
        item = plan['tasks'][state['index']]
        body = body_for(plan, item, state['index'])
        existing = [record for record in request(api, '/experiments') if record['name'] == body['name'] and record.get('budgetId') == plan['budgetId']]
        if len(existing) > 1:
            raise ValueError('Duplicate campaign experiment; human review is required before more spending.')
        budget = request(api, '/token-budgets/' + plan['budgetId'])
        if not existing and budget['remainingTokens'] < plan['builderTokens'] + budget['requestMarginTokens']:
            save('budget_paused')
            return
        if host_volume and shutil.disk_usage(host_volume).free < 25 * 1024**3:
            if existing and existing[0]['status'] in {'preparing', 'running'}:
                request(api, f"/experiments/{existing[0]['id']}/cancel", {})
            save('host_storage_paused')
            return
        experiment = existing[0] if existing else request(api, '/experiments', body)
        state['activeExperimentId'] = experiment['id']
        save('running')
        if experiment['status'] == 'cancelled':
            # A desktop cancellation must not silently start another paid case.
            save('execution_cancelled')
            return
        if experiment['status'] in {'completed', 'failed'}:
            snapshot = request(api, '/snapshot?compact=true')
            runs = [run for run in snapshot['runs'] if run['experimentId'] == experiment['id']]
            state['results'].append({**item, 'experimentId': experiment['id'], 'status': experiment['status'],
                'gradedRuns': sum(isinstance(run.get('testsPassed'), bool) for run in runs),
                'passedRuns': sum(run.get('testsPassed') is True for run in runs),
                'failedRuns': sum(run['status'] == 'failed' for run in runs)})
            state['index'] += 1
            print(json.dumps(state['results'][-1]), flush=True)
            save('running')
        elif experiment['status'] in {'paused', 'ready'}:
            save('execution_paused')
            return
        else:
            time.sleep(5)
    save('completed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:48173/v1')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--budget-id', required=True)
    parser.add_argument('--limit-tokens', type=int, default=1000000000)
    parser.add_argument('--stage-tokens', type=int, help='Cumulative allowance for each role; new plans default to 5,000,000')
    parser.add_argument('--campaign-id', help='Distinct experiment namespace when reusing a shared budget')
    parser.add_argument('--source-plan', type=Path, help='Retain the exact task order in a new campaign; never mixes old results')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--stop-after', type=int, default=0)
    parser.add_argument('--host-volume', type=Path)
    parser.add_argument('--agent-image', required=True, help='A retained immutable sha256 image ID')
    arguments = parser.parse_args()
    if not arguments.agent_image.startswith('sha256:') or len(arguments.agent_image) != 71:
        parser.error('An immutable Agent image ID is required.')
    with campaign_lock(arguments.root):
        frozen = freeze_plan(arguments.api, arguments.budget_id, arguments.limit_tokens, arguments.root, arguments.agent_image,
                             stage_tokens=arguments.stage_tokens, campaign_id=arguments.campaign_id, source_plan=arguments.source_plan)
        print(json.dumps({'plannedTasks': len(frozen['tasks']), 'plannedRuns': len(frozen['tasks']) * 4,
                          'model': frozen['model'], 'budgetId': frozen['budgetId'], 'execute': arguments.execute}), flush=True)
        if arguments.execute:
            execute(arguments.api, frozen, arguments.root, arguments.host_volume, arguments.stop_after)

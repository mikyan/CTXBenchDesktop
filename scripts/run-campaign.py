"""Budget-limited, restartable official-dataset campaign; --execute spends tokens.

The plan is frozen before execution. Only public task metadata determines order.
Each task prepares context once, then runs both arms twice. Existing matching
constraint packages are explicitly recorded; missing history is not a neutral vote.
"""
import argparse
import hashlib
import json
import random
import shutil
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))
from ctxbench_worker.checkpoints import atomic_json


def request(api, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    query = urllib.request.Request(api + path, data=data, headers={'Content-Type': 'application/json'} if data else {})
    with urllib.request.urlopen(query, timeout=60) as response:
        return json.load(response)


def freeze_plan(api, budget_id, limit, root, agent_image):
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'plan.json'
    if path.exists():
        plan = json.loads(path.read_text())
        if plan['budgetId'] != budget_id or plan['limitTokens'] != limit or plan['agentImage'] != agent_image:
            raise ValueError('Existing campaign authorization cannot be changed.')
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
    plan = {'version': 1, 'budgetId': budget_id, 'limitTokens': limit, 'provider': 'xiaomi-token-plan-cn',
            'model': 'mimo-v2.5', 'seed': 42, 'repeats': 2, 'agentImage': agent_image,
            'solverTokens': 300000, 'builderTokens': 800000, 'judgeTokens': 120000,
            'order': 'two disclosed compatibility cases, then seeded repository round-robin, alternating datasets',
            'constraintPolicy': 'explicit matching frozen packages only; new mining is deferred pending GitHub API quota',
            'tasks': tasks}
    atomic_json(root, 'plan.json', plan)
    return plan


def body_for(plan, item, ordinal):
    profile = {'provider': plan['provider'], 'model': plan['model'], 'thinking': 'high', 'maxTokens': plan['solverTokens']}
    package = item['constraintPackageId']
    return {'name': f"{plan['budgetId']} [{ordinal + 1:03}] {item['benchmark']} {item['taskId']}",
            'benchmark': item['benchmark'], 'dataset': item['dataset'], 'taskIds': [item['taskId']],
            'arms': ['none', 'skill-generated'], 'repeats': plan['repeats'], 'seed': plan['seed'],
            'model': profile, 'profiles': {'solver': profile, 'builder': {**profile, 'maxTokens': plan['builderTokens']},
                'constraintMiner': profile, 'constraintJudge': {**profile, 'maxTokens': plan['judgeTokens']}},
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
    parser.add_argument('--limit-tokens', type=int, default=100000000)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--stop-after', type=int, default=0)
    parser.add_argument('--host-volume', type=Path)
    parser.add_argument('--agent-image', required=True, help='A retained immutable sha256 image ID')
    arguments = parser.parse_args()
    if not arguments.agent_image.startswith('sha256:') or len(arguments.agent_image) != 71:
        parser.error('An immutable Agent image ID is required.')
    frozen = freeze_plan(arguments.api, arguments.budget_id, arguments.limit_tokens, arguments.root, arguments.agent_image)
    print(json.dumps({'plannedTasks': len(frozen['tasks']), 'plannedRuns': len(frozen['tasks']) * 4,
                      'model': frozen['model'], 'budgetId': frozen['budgetId'], 'execute': arguments.execute}), flush=True)
    if arguments.execute:
        execute(arguments.api, frozen, arguments.root, arguments.host_volume, arguments.stop_after)

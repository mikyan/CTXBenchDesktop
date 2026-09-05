"""Verify completed real-provider lifecycle evidence; does not create paid runs."""
import argparse
import json
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('experiment', nargs='+')
parser.add_argument('--worker', default='http://127.0.0.1:48173/v1')
parser.add_argument('--output')
args = parser.parse_args()
with urllib.request.urlopen(args.worker + '/snapshot', timeout=30) as response:
    snapshot = json.load(response)
report = []
for experiment_id in args.experiment:
    experiment = next(item for item in snapshot['experiments'] if item['id'] == experiment_id)
    runs = [item for item in snapshot['runs'] if item['experimentId'] == experiment_id]
    assert experiment['status'] == 'completed', (experiment_id, experiment['status'])
    assert len(runs) == experiment['totalRuns']
    assert all(item['status'] == 'completed' and not item.get('mock') and isinstance(item.get('testsPassed'), bool) for item in runs)
    pairs = {}
    for run in runs:
        pairs.setdefault(run['pairId'], []).append(run)
        if run.get('constraintCount', 0):
            assert len(run['judgeRecords']) == 3
            assert len({record['document']['judge'] for record in run['judgeRecords']}) == 3
            assert all(len(record['document']['votes']) == run['constraintCount'] for record in run['judgeRecords'])
    for pair in pairs.values():
        assert len(pair) == len(experiment['arms'])
        assert len({run['pairingHash'] for run in pair}) == 1
        assert len({run['promptHash'] for run in pair}) == 1
        assert len({run['commit'] for run in pair}) == 1
        assert len({run['agentImageDigest'] for run in pair}) == 1
    report.append({'experimentId': experiment_id, 'name': experiment['name'], 'model': experiment['model'],
        'runs': [{key: run.get(key) for key in ('id', 'taskId', 'arm', 'repeat', 'status', 'testsPassed', 'constraintVerdict',
                  'constraintCount', 'constraintQuality', 'contextArtifactId', 'pairingHash', 'promptHash', 'agentImageDigest',
                  'solverRunId', 'inputTokens', 'outputTokens', 'totalTokens', 'constraintPackageId', 'constraintHistoryVersion')}
                 | {'judgeRuns': [record['runId'] for record in run.get('judgeRecords', [])]} for run in runs],
        'completePairs': len(pairs), 'passedTests': sum(run['testsPassed'] for run in runs)})
body = json.dumps({'verified': True, 'experiments': report}, indent=2, ensure_ascii=False)
if args.output:
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
print(body)

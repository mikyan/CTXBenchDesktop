"""Recheck existing real patches with the latest official harness; no Provider calls.

Run with the same /source and data/socket mounts as container-smoke.py.
"""
import argparse
import json
import sys
import urllib.request
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, '/source/worker')
from ctxbench_worker.datasets import import_agentbench, import_swebench
from ctxbench_worker.models import ResourcePolicy
from ctxbench_worker.runtime import Runtime

parser = argparse.ArgumentParser()
parser.add_argument('experiment', nargs='+')
parser.add_argument('--worker', default='http://ctxbench-worker:48173/v1')
parser.add_argument('--expect-error', action='store_true', help='Verify known evaluator exceptions do not become functional failures')
args = parser.parse_args()
with urllib.request.urlopen(args.worker + '/snapshot', timeout=30) as response:
    snapshot = json.load(response)
root = Path('/var/lib/ctxbench')
runtime = Runtime(root, SimpleNamespace(_mount_source=lambda path: str(path)))
harness = runtime.resolve_image('ctxbench/official-harness:0.1.0')
output = root / ('acceptance-regrade-' + uuid.uuid4().hex[:10])
report = []
for experiment_id in args.experiment:
    experiment = next(item for item in snapshot['experiments'] if item['id'] == experiment_id)
    run = next(item for item in snapshot['runs'] if item['experimentId'] == experiment_id
               and item['status'] == 'completed' and (args.expect_error or item['testsPassed']) and not item.get('mock'))
    dataset = root / 'datasets' / (experiment['dataset'] + '.json')
    rows = json.loads(dataset.read_text())
    tasks = import_swebench(rows) if experiment['benchmark'] == 'swebench' else import_agentbench(rows)
    task = next(item for item in tasks if item.id == run['taskId'])
    patch = Path(run['outputDir']) / 'graded.patch'
    assert patch.resolve().is_relative_to(root / 'runs'), 'Patch must be an existing run output'
    try:
        grade = runtime.grade(task, dataset, patch, output / experiment_id,
                              ResourcePolicy(cpus=2, memory_gb=4, timeout_minutes=10, network='offline'), harness)
    except RuntimeError as error:
        if not args.expect_error:
            raise
        assert 'no functional verdict' in str(error), str(error)
        assert not (output / experiment_id / 'summary.json').exists(), 'An evaluator error must not publish a verdict'
        report.append({'experimentId': experiment_id, 'solverRunId': run['solverRunId'],
                       'harnessImage': harness, 'expectedEvaluatorError': True})
        continue
    assert not args.expect_error, 'Expected evaluator failure was not detected'
    assert grade['resolved'] is True, grade
    assert grade.get('graderImageDigests') and all(value.startswith('sha256:') for value in grade['graderImageDigests']), grade
    report.append({'experimentId': experiment_id, 'solverRunId': run['solverRunId'],
                   'harnessImage': harness, 'grade': grade})
body = json.dumps({'verified': True, 'output': str(output), 'results': report}, indent=2)
(output / 'summary.json').write_text(body)
print(body)

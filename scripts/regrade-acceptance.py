"""Recheck existing real patches with the latest official harness; no Provider calls.

Run with the same /source and data/socket mounts as container-smoke.py.
"""
import argparse
import hashlib
import json
import sys
import urllib.request
import uuid
from dataclasses import replace
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
parser.add_argument('--allow-unresolved', action='store_true', help='Regrade retained patches from failed runs; require a real verdict, not a pass')
parser.add_argument('--check-controls', action='store_true', help='Also verify the empty-patch negative and gold-patch positive in evaluator-only containers')
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
               and (item['status'] == 'completed' or args.allow_unresolved and item.get('outputDir'))
               and (args.allow_unresolved or args.expect_error or item.get('testsPassed')) and not item.get('mock'))
    dataset = root / 'datasets' / (experiment['dataset'] + '.json')
    rows = json.loads(dataset.read_text())
    tasks = import_swebench(rows) if experiment['benchmark'] == 'swebench' else import_agentbench(rows)
    task = next(item for item in tasks if item.id == run['taskId'])
    patch = Path(run['outputDir']) / 'graded.patch'
    assert patch.resolve().is_relative_to(root / 'runs'), 'Patch must be an existing run output'
    original_patch_hash = hashlib.sha256(patch.read_bytes()).hexdigest()
    resources = ResourcePolicy(cpus=2, memory_gb=4, timeout_minutes=30, network='offline')
    if task.source == 'agentbench':
        print(json.dumps({'experimentId': experiment_id, 'stage': 'prepare-baseline-environment'}), flush=True)
        task = replace(task, image=runtime.prepare_agentbench_image(task, dataset, harness, resources))
    environment_options = {'environment_image': task.image} if task.source == 'agentbench' else {}
    print(json.dumps({'experimentId': experiment_id, 'stage': 'grade-retained-patch'}), flush=True)
    try:
        grade = runtime.grade(task, dataset, patch, output / experiment_id,
                              resources, harness, **environment_options)
    except RuntimeError as error:
        if not args.expect_error:
            raise
        assert 'no functional verdict' in str(error), str(error)
        assert not (output / experiment_id / 'summary.json').exists(), 'An evaluator error must not publish a verdict'
        report.append({'experimentId': experiment_id, 'solverRunId': run['solverRunId'],
                       'harnessImage': harness, 'expectedEvaluatorError': True})
        continue
    assert not args.expect_error, 'Expected evaluator failure was not detected'
    assert type(grade['resolved']) is bool and (args.allow_unresolved or grade['resolved']), grade
    assert grade.get('graderImageDigests') and all(value.startswith('sha256:') for value in grade['graderImageDigests']), grade
    record = {'experimentId': experiment_id, 'solverRunId': run['solverRunId'],
              'patchHash': original_patch_hash, 'harnessImage': harness, 'grade': grade}
    if args.check_controls:
        controls = {}
        for name, content, expected in [('empty', '', False), ('gold', task.gold_patch, True)]:
            assert content is not None, 'Control requires a retained evaluator-only gold patch'
            control_dir = output / experiment_id / ('control-' + name)
            control_dir.mkdir(parents=True)
            control_patch = control_dir / 'input.patch'
            control_patch.write_text(content, encoding='utf-8')
            print(json.dumps({'experimentId': experiment_id, 'stage': 'control-' + name}), flush=True)
            controls[name] = runtime.grade(task, dataset, control_patch, control_dir, resources, harness, **environment_options)
            assert controls[name]['resolved'] is expected, controls[name]
        record['controls'] = controls
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == original_patch_hash
    report.append(record)
    print(json.dumps(record), flush=True)
body = json.dumps({'verified': True, 'output': str(output), 'results': report}, indent=2)
(output / 'summary.json').write_text(body)
print(body)

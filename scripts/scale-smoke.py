"""Synthetic 638-task/2,552-run storage regression; no Agent or Provider is called.

Runs in a temporary database, which is removed on exit. Timing is observational,
not a machine-independent SLA or evidence of real benchmark performance.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))
from ctxbench_worker.engine import create_mock_engine
from ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from ctxbench_worker.workbench import Workbench


with tempfile.TemporaryDirectory(prefix='ctxbench-scale-') as directory:
    engine = create_mock_engine(directory)
    workbench = Workbench(engine, None)
    dataset = workbench.catalog.register('Synthetic capacity fixture', 'custom', [
        {'id': f'fixture-{index}', 'repository': f'org/repo-{index}', 'baseCommit': 'a' * 40,
         'prompt': 'Synthetic storage fixture; do not execute.', 'image': 'test-only',
         'test': {'command': ['true']}} for index in range(638)])
    spec = ExperimentSpec('Synthetic capacity only', 'custom', dataset['id'], ('none', 'skill-generated'),
                          2, tuple(f'fixture-{index}' for index in range(638)),
                          ModelConfig('mock', 'deterministic', 'off', 1000), 'test-only', ResourcePolicy(), 42)
    started = time.monotonic()
    estimate = workbench.preflight(spec)
    experiment = workbench.create_experiment(spec)
    planned_ms = (time.monotonic() - started) * 1000
    assert estimate['runs'] == 2552
    evidence = {'mock': True, 'testsPassed': True, 'constraintVerdict': 'satisfied',
                'constraintPackageId': 'fixture-package', 'constraintVerdicts': {'c1': 'satisfied'},
                'judgeRecords': [{'judge': str(index), 'evidence': 'synthetic ' * 3000} for index in range(3)],
                'grade': {'resolved': True, 'log': 'synthetic ' * 1000}}
    with engine.database.connect() as connection:
        connection.execute("UPDATE runs SET status='completed', result_json=? WHERE experiment_id=?",
                           (json.dumps(evidence), experiment['id']))
    engine.database.put_document('constraintPackages', 'fixture-package', {
        'id': 'fixture-package', 'repository': 'org/fixture', 'document': {'quality': 'silver', 'constraints': [
            {'id': 'c1', 'problem': 'Synthetic constraint', 'options': [{'rationale': 'Fixture', 'provenance': ['test-only']}]}]}})
    timings, sizes, snapshots = {}, {}, {}
    for compact in (True, False):
        label = 'compact' if compact else 'full'
        started = time.monotonic()
        snapshots[label] = workbench.snapshot(compact=compact)
        encoded = json.dumps(snapshots[label]).encode()
        timings[label] = round((time.monotonic() - started) * 1000, 1)
        sizes[label] = len(encoded)
    assert len(snapshots['compact']['runs']) == 2552
    assert snapshots['compact']['constraints'][0]['satisfied'] == 2552
    assert snapshots['compact']['constraints'] == snapshots['full']['constraints']
    assert all('judgeRecords' not in run and 'grade' not in run for run in snapshots['compact']['runs'])
    assert len(engine.database.get_run(snapshots['compact']['runs'][0]['id'])['judgeRecords']) == 3
    assert sizes['compact'] < sizes['full'] / 10
    assert not engine.database.list_documents('stages'), 'Capacity verification must not invoke an Agent'
    print(json.dumps({'passed': True, 'synthetic': True, 'tasks': 638, 'runs': 2552,
                      'planningMs': round(planned_ms, 1), 'snapshotMs': timings, 'snapshotBytes': sizes,
                      'payloadReductionPercent': round((1 - sizes['compact'] / sizes['full']) * 100, 2)}, indent=2))

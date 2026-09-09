"""Isolated real Docker acceptance: editable sources -> durable frozen execution.

Run in an existing worker image with /source read-only, Docker socket and a new
scratch directory mounted at the SAME absolute path inside/outside the container.
Pass that scratch path as argv[1]. Uses deterministic mock Agent mode, no Provider.
Does not rebuild, retag or remove any pre-existing image or production service.
"""
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, '/source/worker')
from ctxbench_worker.engine import create_engine_from_environment
from ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from ctxbench_worker.runtime import seal
from ctxbench_worker.workbench import Workbench

root = Path(sys.argv[1]).resolve()
assert root.parent == Path('/tmp') and root.name.startswith('ctxbench-case-library-')
assert root.is_dir() and not list(root.iterdir()), 'Use a fresh empty isolated directory'
os.environ['CTXBENCH_HOST_DATA_DIR'] = str(root)
os.environ['CTXBENCH_BUNDLED_SKILL_DIR'] = '/source/skills/ctxbench-generate-context'
engine = create_engine_from_environment(root, 'docker')
wb = Workbench(engine, None)
source = root / 'fixture'
source.mkdir()
(source / 'README.md').write_text('Baseline v1; isolated snapshot acceptance fixture.\n')
commit = seal(source)
image = wb.runtime.resolve_image('ctxbench/agent-pi:0.1.0')
row = {'id': 'snapshot-task', 'repository': str(source), 'baseCommit': commit,
       'prompt': 'Complete the deterministic infrastructure fixture.', 'image': image,
       'test': {'command': ['python3', '-c', "from pathlib import Path; assert Path('ctxbench_mock_solution.txt').is_file(); assert Path('ctxbench_mock_staged.txt').is_file()"]}}
case = wb.library.save_case({'name': 'Standalone case v1', 'benchmark': 'custom', 'row': row})
other = wb.library.save_case({'name': 'Other case', 'benchmark': 'custom', 'row': {**row, 'id': 'other-task'}})
collection = wb.library.save_set({'name': 'Editable suite v1', 'caseIds': [case['id']]})
model = ModelConfig('mock', 'deterministic', 'off', 10000)
resources = ResourcePolicy(cpus=1, memory_gb=1, timeout_minutes=2, network='offline')
operation = wb.enqueue('context', {'dataset': case['id'], 'taskId': row['id'],
    'datasetRevision': wb.library.selection(case['id'])['revision'], 'agentImage': image,
    'model': asdict(model), 'resources': asdict(resources), 'projectEnvironment': False})
spec = ExperimentSpec('Snapshot Docker acceptance', 'custom', collection['id'], ('none', 'skill-generated'),
    2, (row['id'],), model, image, resources, 42, prepare_only=True,
    dataset_revision=wb.library.selection(collection['id'])['revision'])
experiment = wb.create_experiment(spec)
frozen = engine.database.get_spec(experiment['id'])
assert frozen.dataset_snapshot['members'][0]['revision'] == 1

# Edit all executable material and membership BEFORE the scheduler starts.
(source / 'README.md').write_text('Future v2 baseline must not reach queued work.\n')
future_commit = seal(source)
wb.library.save_case({'name': 'Standalone case v2', 'benchmark': 'custom', 'expectedRevision': 1,
    'row': {**row, 'baseCommit': future_commit, 'prompt': 'Different future task.',
            'test': {'command': ['python3', '-c', 'raise AssertionError("Future grader must not run")']}}}, case['id'])
wb.library.save_set({'name': 'Editable suite v2', 'caseIds': [other['id']], 'expectedRevision': 1}, collection['id'])

def wait_until(predicate, label):
    deadline = time.monotonic() + 150
    while not predicate():
        failed = [item for item in engine.database.list_documents('operations') if item['status'] == 'failed']
        assert not failed, [(item['kind'], item.get('failure')) for item in failed]
        assert time.monotonic() < deadline, label + ' timed out'
        time.sleep(.2)

try:
    wb.start()
    wait_until(lambda: engine.database.get_experiment(experiment['id'])['status'] == 'ready', 'Preparation')
    independent = engine.database.get_document('operations', operation['id'])
    assert independent['status'] == 'completed'
    context_id = independent['result']['id']
    assert wb.engine.artifacts.verify(context_id)['identity']['commit'] == commit
    before = len([s for s in engine.database.list_documents('stages') if s['id'].startswith('context:')])
finally:
    wb.stop()

# A service restart and cancellation/retry must reuse both the frozen cases and context.
restored = Workbench(engine, None)
restored.control(experiment['id'], 'cancel')
restored.control(experiment['id'], 'retry')
try:
    restored.start()
    wait_until(lambda: engine.database.get_experiment(experiment['id'])['status'] == 'completed', 'Paired runs')
finally:
    restored.stop()
runs = engine.database.list_runs(experiment['id'])
assert len(runs) == 4 and all(run['status'] == 'completed' and run['testsPassed'] for run in runs), runs
assert len({run['pairingHash'] for run in runs}) == 1
assert len([s for s in engine.database.list_documents('stages') if s['id'].startswith('context:')]) == before
assert restored.catalog.task(frozen.dataset, row['id']).base_commit == commit
assert engine.database.get_spec(experiment['id']).dataset_snapshot == frozen.dataset_snapshot
new_hash, new_receipt = restored.library.freeze(case['id'])
assert new_hash != frozen.dataset and new_receipt['members'][0]['revision'] == 2
assert restored.catalog.task(new_hash, row['id']).base_commit == future_commit
assert restored.library.selection(collection['id'])['tasks'][0]['id'] == 'other-task'

summary = {'status': 'passed', 'root': str(root), 'experimentId': experiment['id'],
    'pairedRuns': 4, 'realDocker': True, 'provider': 'mock', 'independentContextGeneration': True,
    'editedBeforeQueueExecution': True, 'restartCancelRetryKeepsSnapshot': True,
    'generationStages': before, 'contextReused': True, 'futureSnapshotUsesEdits': True}
(root / 'summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2), flush=True)

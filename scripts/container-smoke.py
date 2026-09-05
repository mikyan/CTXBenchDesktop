"""Run inside the worker image with /source and Docker socket mounted; never uses a Provider.

docker run --rm --network ctxbench_control -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/lib/ctxbench:/var/lib/ctxbench -v "$PWD:/source:ro" \
  --entrypoint python ctxbench/worker:0.1.0 /source/scripts/container-smoke.py
"""
import json
import os
import sys
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, '/source/worker')
from ctxbench_worker.engine import create_engine_from_environment
from ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy, RunSpec
from ctxbench_worker.runtime import seal
from ctxbench_worker.workbench import Workbench

root = Path('/var/lib/ctxbench') / f'acceptance-container-{uuid.uuid4().hex[:10]}'
os.environ['CTXBENCH_HOST_DATA_DIR'] = str(root)
os.environ['CTXBENCH_BUNDLED_SKILL_DIR'] = '/source/skills/ctxbench-generate-context'
engine = create_engine_from_environment(root, 'docker')
workbench = Workbench(engine, None)
source = root / 'fixture'
source.mkdir()
agent_image = workbench.runtime.resolve_image('ctxbench/agent-pi:0.1.0')
(source / 'Dockerfile').write_text(f'FROM {agent_image}\nCOPY . /build\nRUN test ! -e /build/ctxbench_mock_solution.txt\n')
(source / 'README.md').write_text('Isolated acceptance fixture, not a benchmark dataset.')
commit = seal(source)
dataset = workbench.catalog.register('Container smoke', 'custom', [{
    'id': 'custom-container-smoke', 'repository': str(source), 'baseCommit': commit,
    'prompt': 'Complete the mock infrastructure fixture.', 'build': {'dockerfile': 'Dockerfile'},
    'test': {'command': ['python3', '-c', "from pathlib import Path; assert Path('ctxbench_mock_solution.txt').is_file(); assert Path('ctxbench_mock_staged.txt').is_file()"]},
}])
manual = workbench.import_context({'dataset': dataset['id'], 'taskId': 'custom-container-smoke',
    'repository': str(source), 'baseCommit': commit, 'files': {'docs/context.txt': 'Frozen manual fixture'}})
profile = ModelConfig('mock', 'deterministic', 'off', 10000)
resources = ResourcePolicy(cpus=1, memory_gb=1, timeout_minutes=2, network='offline')
spec = ExperimentSpec('Container lifecycle acceptance', 'custom', dataset['id'],
    ('none', 'skill-generated', 'manual', 'developer-historical'), 2, ('custom-container-smoke',),
    profile, agent_image, resources, 42, context_artifacts={'custom-container-smoke': manual['id']}, prepare_only=True)
experiment = workbench.create_experiment(spec)
workbench.run_experiment(experiment['id'])
assert engine.database.get_experiment(experiment['id'])['status'] == 'ready'
before = len(engine.database.list_documents('stages'))
workbench.control(experiment['id'], 'resume')
# Reconstruct the coordinator to test persisted preparation/start state.
restored = Workbench(engine, None)
restored.run_experiment(experiment['id'])
runs = engine.database.list_runs(experiment['id'])
assert len(runs) == 8 and all(run['status'] == 'completed' and run['testsPassed'] for run in runs), runs
assert len({run['pairingHash'] for run in runs}) == 1
assert len(engine.database.list_documents('stages')) == before + 8
for run in runs:
    patch = (Path(run['outputDir']) / 'graded.patch').read_text()
    assert 'ctxbench_mock_solution.txt' in patch and 'ctxbench_mock_staged.txt' in patch
assert len([stage for stage in engine.database.list_documents('stages') if stage['id'].startswith('context:')]) == 1
task = restored.catalog.task(dataset['id'], 'custom-container-smoke')
image = engine.database.get_document('prepared', experiment['id'])['graderImages'][task.id]
import docker
pin_client = docker.from_env()
temporary_tag = 'ctxbench/acceptance-mutable:' + root.name
pin_client.images.get(agent_image).tag(temporary_tag)
frozen = restored.runtime.resolve_image(temporary_tag)
pin_client.images.get(image).tag(temporary_tag)
assert pin_client.images.get(frozen).id == agent_image, 'Mutable tag replacement lost the frozen image'
pin_client.images.remove(temporary_tag)
pin_client.close()
bad = root / 'bad.patch'
bad.write_text('')
failed = restored.runtime.grade(replace(task, image=image), Path(engine.database.get_document('datasets', dataset['id'])['path']), bad, root / 'negative-grade', resources, '')
assert failed['resolved'] is False

# Cancellation reaches the running container, not merely its queue record.
os.environ['CTXBENCH_TEST_DELAY_SECONDS'] = '60'
engine.runner.env_allowlist |= {'CTXBENCH_TEST_DELAY_SECONDS'}
run_id = f'cancel-{uuid.uuid4().hex[:12]}'
cancel_spec = RunSpec(run_id, 'solve', agent_image, str(restored.runtime.checkout(task, 'cancel')),
                     str(root / 'runs' / run_id), task.prompt, profile, resources, ('CTXBENCH_TEST_DELAY_SECONDS',))
results = []
thread = threading.Thread(target=lambda: results.append(engine.runner.run(cancel_spec)))
thread.start()
import docker
client = docker.from_env()
deadline = time.monotonic() + 20
while not client.containers.list(filters={'label': f'io.ctxbench.run={run_id}'}):
    assert time.monotonic() < deadline, 'Cancellation fixture failed to start'
    time.sleep(.1)
engine.runner.cancel(run_id)
thread.join(timeout=20)
assert not thread.is_alive() and results[0].status == 'failed'
assert not client.containers.list(all=True, filters={'label': f'io.ctxbench.run={run_id}'})
client.close()
summary = {'status': 'passed', 'root': str(root), 'experimentId': experiment['id'], 'pairedRuns': 8,
           'generationStages': 1, 'manualImport': True, 'baselineImageBuild': True,
           'committedAndStagedPatch': True, 'negativeGrader': True, 'cancelledContainerRemoved': True, 'imagePinSurvivesRetag': True}
(root / 'summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))

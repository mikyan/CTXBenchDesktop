"""Docker workflow acceptance with synthetic prompts and an offline wheel; no Provider calls."""
import json
import os
import sys
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, '/source')
from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy, RunSpec
from worker.ctxbench_worker.runner import DockerRunner
from worker.ctxbench_worker.runtime import seal


root = Path('/var/lib/ctxbench') / f'acceptance-workflow-{uuid.uuid4().hex[:10]}'
runner = DockerRunner(root / 'repositories', root / 'runs', root / 'requests', worker_data_root=root, host_data_root=str(root))
image = os.environ.get('CTXBENCH_WORKFLOW_TEST_IMAGE', 'ctxbench/agent-pi:0.1.0')
setup = ['python3 -m venv "$HOME/bench-env"', 'source "$HOME/bench-env/bin/activate"',
         'python -m pip install --no-index ./ctxbench_fixture_dependency-0.1-py3-none-any.whl']
agent_args = ('--tools', 'read, bash, edit, write', '--verbose')


def prompt(**fixture):
    return 'CTXBENCH_WORKFLOW_TEST:' + json.dumps(fixture)


def run_case(name, mode, workflow=None, max_tokens=10000, args=()):
    workspace = root / 'repositories' / name
    workspace.mkdir()
    (workspace / 'README.md').write_text('Public synthetic baseline.\n')
    wheel = workspace / 'ctxbench_fixture_dependency-0.1-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('ctxbench_fixture_dependency.py', 'VALUE = 42\n')
        archive.writestr('ctxbench_fixture_dependency-0.1.dist-info/METADATA', 'Metadata-Version: 2.1\nName: ctxbench-fixture-dependency\nVersion: 0.1\n')
        archive.writestr('ctxbench_fixture_dependency-0.1.dist-info/WHEEL', 'Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        archive.writestr('ctxbench_fixture_dependency-0.1.dist-info/RECORD', '')
    seal(workspace)
    output = root / 'runs' / name
    result = runner.run(RunSpec(name, mode, image, str(workspace), str(output), 'Default fixture prompt',
        ModelConfig('mock', 'deterministic', 'off', max_tokens), ResourcePolicy(cpus=1, memory_gb=1, timeout_minutes=1, network='offline'),
        workflow=workflow or {}, agent_args=args))
    metadata = json.loads((output / 'result.json').read_text())
    return result, metadata, output


reports = []
for mode in ('generate-context', 'solve'):
    first, second = ('.ctx/step-one.md', '.ctx/step-two.md') if mode == 'generate-context' else ('step-one.txt', 'step-two.txt')
    workflow = {'setupCommands': setup, 'steps': [
        {'name': 'First independent session', 'prompt': prompt(requireDependency=True, writeFile=first, expectedArgs=agent_args)},
        {'name': 'Second independent session', 'prompt': prompt(requireDependency=True, requireFile=first, writeFile=second, expectedArgs=agent_args)},
    ]}
    result, metadata, output = run_case(mode, mode, workflow, args=agent_args)
    assert result.status == 'completed', f'{mode} failed; inspect {output}'
    assert metadata['modelInvocations'] == 2 and metadata['cumulativeTokens'] == 320
    assert all(step['status'] == 'completed' for step in metadata['workflowSteps'])
    from worker.ctxbench_worker.agent_args import verify_agent_args_receipt
    verify_agent_args_receipt(metadata, agent_args)
    records = [json.loads(line) for line in (output / 'trajectory.jsonl').read_text().splitlines() if line]
    assert len({record['sessionPid'] for record in records if record.get('type') == 'agent_start'}) == 2
    assert 'Successfully installed ctxbench-fixture-dependency-0.1' in (output / 'setup.log').read_text()
    if mode == 'generate-context':
        assert (output / 'context' / 'files' / second).is_file()
    else:
        assert first in (output / 'graded.patch').read_text() and second in (output / 'graded.patch').read_text()
    reports.append({'case': mode, 'status': 'passed', 'steps': 2, 'tokens': 320})

result, metadata, output = run_case('setup-failure', 'solve', {'setupCommands': ['false'], 'steps': [{'prompt': None}]})
assert result.status == 'failed' and metadata['modelInvocations'] == 0
reports.append({'case': 'setup-failure-before-model', 'status': 'passed'})
result, metadata, output = run_case('baseline-mutation', 'solve', {'setupCommands': ['printf changed > README.md'], 'steps': [{'prompt': None}]})
assert result.status == 'failed' and metadata['modelInvocations'] == 0
reports.append({'case': 'setup-cannot-change-baseline', 'status': 'passed'})
result, metadata, output = run_case('middle-failure', 'solve', {'steps': [{'prompt': None}, {'prompt': prompt(fail=True)}, {'prompt': prompt(writeFile='must-not-exist.txt')}]})
assert result.status == 'failed' and metadata['modelInvocations'] == 2
assert len(metadata['workflowSteps']) == 2
reports.append({'case': 'failure-stops-later-steps', 'status': 'passed'})
result, metadata, output = run_case('shared-budget', 'solve', {'steps': [{'prompt': None}, {'prompt': None}]}, max_tokens=100)
assert result.status == 'failed' and metadata['modelInvocations'] == 1 and metadata['budgetInterrupted']
reports.append({'case': 'shared-token-budget', 'status': 'passed'})
result, metadata, output = run_case('legacy-single-step', 'solve')
assert result.status == 'completed' and metadata['modelInvocations'] == 1
reports.append({'case': 'default-single-step', 'status': 'passed'})

# Verify orchestration above the adapter: one frozen builder, two repeats, both paired arms.
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.workbench import Workbench
engine = create_mock_engine(root / 'workbench')
engine.runner = DockerRunner(root / 'workbench' / 'repositories', root / 'workbench' / 'runs', root / 'workbench' / 'requests')
workbench = Workbench(engine, None)
source = root / 'paired-source'
source.mkdir()
(source / 'README.md').write_text('Task-blind paired workflow fixture.\n')
commit = seal(source)
dataset = workbench.catalog.register('Paired workflows', 'custom', [{'id': 'workflow-pair', 'repository': str(source),
    'baseCommit': commit, 'prompt': 'Complete the fixture task', 'image': image,
    'test': {'command': ['python3', '-c', "from pathlib import Path; assert Path('solver-two.txt').is_file()"]}}])
builder = {'steps': [{'prompt': prompt(writeFile='.ctx/builder-one.md', expectedArgs=agent_args)}, {'prompt': prompt(requireFile='.ctx/builder-one.md', writeFile='.ctx/builder-two.md', expectedArgs=agent_args)}]}
solver = {'steps': [{'prompt': prompt(writeFile='solver-one.txt', expectedArgs=agent_args)}, {'prompt': prompt(requireFile='solver-one.txt', writeFile='solver-two.txt', expectedArgs=agent_args)}]}
spec = ExperimentSpec('Workflow pairing', 'custom', dataset['id'], ('none', 'skill-generated'), 2, ('workflow-pair',),
    ModelConfig('mock', 'deterministic', 'off', 10000), image, ResourcePolicy(cpus=1, memory_gb=1, timeout_minutes=1, network='offline'),
    42, builder_workflow=builder, solver_workflow=solver, agent_args=agent_args)
experiment = workbench.create_experiment(spec)
workbench.run_experiment(experiment['id'])
runs = engine.database.list_runs(experiment['id'])
assert len(runs) == 4 and all(run['testsPassed'] for run in runs)
assert len({run['pairingHash'] for run in runs}) == 1
assert all(run['agentArgs'] == list(agent_args) for run in runs)
stages = engine.database.list_documents('stages')
assert len([stage for stage in stages if stage['id'].startswith('context:')]) == 1
assert all(stage['metadata']['modelInvocations'] == 2 for stage in stages)
workbench.run_experiment(experiment['id'])
assert len(engine.database.list_documents('stages')) == 5
reports.append({'case': 'paired-workflows-and-frozen-context-reuse', 'status': 'passed', 'gradedRuns': 4})
print(json.dumps({'status': 'passed', 'providerCalls': 0, 'root': str(root), 'cases': reports}))

"""Real Docker pull/build/custom-command/grade acceptance, no Pi or Provider calls.

Run inside the worker image with /source read-only, Docker socket and a fresh WSL
scratch directory mounted at the identical host/container path, supplied as argv[1].
Only a small public image is pulled; existing services/tags are never replaced.
"""
import base64
import json
import os
from pathlib import Path
import sys
import time
from dataclasses import replace

sys.path.insert(0, '/source/worker')
from ctxbench_worker.engine import create_engine_from_environment
from ctxbench_worker.intranet import IntranetWorkbench
from ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy, RunSpec
from ctxbench_worker.runtime import seal
from ctxbench_worker.workbench import Workbench

root = Path(sys.argv[1]).resolve()
assert root.parent == Path('/tmp') and root.name.startswith('ctxbench-command-') and not list(root.iterdir())
os.environ['CTXBENCH_HOST_DATA_DIR'] = str(root)
os.environ['CTXBENCH_BUNDLED_SKILL_DIR'] = '/source/skills/ctxbench-generate-context'
os.environ['PYTHONPATH'] = '/source/worker'
wb = Workbench(create_engine_from_environment(root, 'docker'), None)
service = IntranetWorkbench(wb)


def wait(predicate, label):
    deadline = time.monotonic() + 240
    while not predicate():
        failures = [op for op in wb.db.list_documents('operations') if op['status'] == 'failed']
        assert not failures, [(op['kind'], op.get('failure')) for op in failures]
        assert time.monotonic() < deadline, label
        time.sleep(.3)


fixture_agent = '''import os, shutil, json
from pathlib import Path
assert shutil.which('pi') is None, 'Fixture must not contain Pi'
assert os.environ['FROM_SETUP'] == 'preserved'
assert os.environ['CUSTOM_DEFAULT'] == 'from-image'
assert json.loads(Path('/etc/ctxbench-company-defaults.json').read_text())['mode'] == 'batch'
assert os.environ['CTXBENCH_MODEL'] == 'fixture-cli'
prompt = Path(os.environ['CTXBENCH_PROMPT_FILE']).read_text()
assert 'EVALUATOR_ONLY' not in prompt
if prompt == 'first step':
    Path('answer.py').write_text('VALUE = 42\\n')
    Path('AGENTS.md').write_text('Mutated passive context; never grade this.\\n')
elif prompt == 'second step':
    assert Path('answer.py').read_text() == 'VALUE = 42\\n'
else:
    raise AssertionError('Wrong prompt')
print('Custom command completed without Pi')
'''
try:
    wb.start()
    pull = service.enqueue('image-pull', {'image': 'busybox:1.37.0', 'confirmed': True})
    wait(lambda: service.status(pull['id'])['status'] == 'completed', 'Remote image pull')
    print(json.dumps({'stage': 'pull', 'result': service.status(pull['id'])['result']}), flush=True)
    build = service.enqueue('image-build', {'name': 'Non-Pi fixture with defaults', 'baseImage': 'ctxbench/worker:0.1.0',
        'dockerfile': 'USER root\nRUN mkdir -p /opt/company\nCOPY ["fixture-agent.py", "/opt/fixture-agent.py"]\nCOPY ["settings.json", "/opt/company/settings.json"]\nRUN ' + json.dumps(['/bin/sh', '-eu', '-c', 'cp /opt/company/settings.json /etc/ctxbench-company-defaults.json\nchmod 644 /etc/ctxbench-company-defaults.json']) + '\nENV CUSTOM_DEFAULT="from-image"\nWORKDIR /workspace',
        'network': 'none', 'files': [{'path': 'fixture-agent.py', 'base64': base64.b64encode(fixture_agent.encode()).decode()},
                                   {'path': 'settings.json', 'base64': base64.b64encode(b'{"mode":"batch"}').decode()}]})
    wait(lambda: service.status(build['id'])['status'] == 'completed', 'Custom Agent image build')
    built = service.status(build['id'])['result']
    print(json.dumps({'stage': 'build', 'image': built['tag']}), flush=True)
    source = root / 'fixture'
    source.mkdir()
    (source / 'README.md').write_text('Only the baseline, not hidden tests.\n')
    commit = seal(source)
    command = {'image': built['tag'], 'command': ['python3', '/opt/fixture-agent.py']}
    row = {'id': 'custom-command', 'repository': str(source), 'baseCommit': commit, 'prompt': 'Solve this fixture',
        'image': 'ctxbench/worker:0.1.0', 'agent': command,
        'test': {'command': ['python3', '-c', "from answer import VALUE; assert VALUE == 42; from pathlib import Path; assert not Path('AGENTS.md').exists() # EVALUATOR_ONLY"]}}
    case = wb.library.save_case({'name': 'Non-Pi fixture', 'benchmark': 'custom', 'row': row})
    model = ModelConfig('custom-cli', 'fixture-cli', 'off', 5_000_000)
    # A completely exhausted budget for another model must not gate an
    # unmetered command or turn its missing telemetry into fabricated charges.
    wb.budgets.create('metered-only', 1, 'mock', 'deterministic')
    wb.budgets.reserve('metered-only', 'previous-metered-run', 1, mode='solve', experiment_id=None, output=str(root / 'previous-metered'))
    wb.budgets.settle('previous-metered-run', None)
    initial_budget = wb.budgets.snapshot('metered-only')
    spec = ExperimentSpec('Real non-Pi command acceptance', 'custom', case['id'], ('none', 'developer-historical'), 1,
        ('custom-command',), model, 'intentionally-missing-default-agent:never-pull', ResourcePolicy(cpus=1, memory_gb=1, timeout_minutes=2, network='offline'), 42,
        solver_workflow={'setupCommands': ['export FROM_SETUP=preserved'], 'steps': [{'prompt': 'first step'}, {'prompt': 'second step'}]},
        project_environment=True, prepare_only=True, budget_id='metered-only')
    experiment = wb.create_experiment(spec)
    # The scheduled snapshot must still run v1 after the source command is changed.
    wb.library.save_case({'name': 'Changed future command', 'benchmark': 'custom', 'expectedRevision': 1,
                         'row': {**row, 'agent': {**command, 'command': ['/bin/sh', '-c', 'exit 99']}}}, case['id'])
    wait(lambda: wb.db.get_experiment(experiment['id'])['status'] == 'ready', 'Prepare frozen images')
    wb.control(experiment['id'], 'resume')
    wait(lambda: wb.db.get_experiment(experiment['id'])['status'] in {'completed', 'failed'}, 'Paired custom commands')
    runs = wb.db.list_runs(experiment['id'])
    assert len(runs) == 2 and all(r['status'] == 'completed' and r['testsPassed'] for r in runs), runs
    assert len({r['pairingHash'] for r in runs}) == 1
    assert all(r['totalTokens'] is None and r['contextMutated'] for r in runs)
    for run in runs:
        result = json.loads((Path(run['outputDir']) / 'result.json').read_text())
        assert result['usageAvailable'] is False and len(result['workflowSteps']) == 2
        assert result['commandAgentProtocolVersion'] == 1 and 'cumulativeTokens' not in result
    negative_case = wb.library.save_case({'name': 'Expected failing tests', 'benchmark': 'custom',
        'row': {**row, 'test': {'command': ['python3', '-c', 'raise AssertionError("Expected behavioral failure")']}}})
    negative = wb.create_experiment(replace(spec, dataset=negative_case['id'], prepare_only=False))
    wait(lambda: wb.db.get_experiment(negative['id'])['status'] in {'completed', 'failed'}, 'Negative functional control')
    negative_runs = wb.db.list_runs(negative['id'])
    assert len(negative_runs) == 2 and all(r['status'] == 'completed' and r['testsPassed'] is False and r['totalTokens'] is None for r in negative_runs), negative_runs
    assert wb.budgets.snapshot('metered-only') == initial_budget
    workspace = wb.runtime.checkout(wb.catalog.task(wb.db.get_spec(experiment['id']).dataset, 'custom-command'), 'bad-command')
    failed = wb.engine.runner.run(RunSpec('bad-command-exit', 'solve', built['imageId'], str(workspace), str(root / 'runs/bad-command-exit'),
        'No prompt changes', model, spec.resources, metadata={'commandAgent': {**command, 'command': ['/bin/sh', '-c', 'exit 17']}}))
    assert failed.status == 'failed' and failed.exit_code == 17
    for kind, commands in [('baseline', ['printf changed > README.md']),
                           ('context', ['mkdir -p .ctx', 'printf hidden-context > .ctx/new.md'])]:
        workspace = wb.runtime.checkout(wb.catalog.task(wb.db.get_spec(experiment['id']).dataset, 'custom-command'), 'setup-' + kind)
        blocked_output = root / ('runs/setup-' + kind)
        blocked = wb.engine.runner.run(RunSpec('setup-' + kind, 'solve', built['imageId'], str(workspace), str(blocked_output),
            'Must not reach command', model, spec.resources,
            metadata={'commandAgent': {**command, 'command': ['/bin/sh', '-c', 'touch agent-started.txt']}},
            workflow={'setupCommands': commands, 'steps': [{'prompt': None}]}))
        assert blocked.status == 'failed' and not (workspace / 'agent-started.txt').exists()
        blocked_result = json.loads((blocked_output / 'result.json').read_text())
        assert 'changed the frozen repository' in blocked_result['workflowError'] and not blocked_result['workflowSteps']
    prepared = wb.db.get_document('prepared', experiment['id'])
    prepared['commandAdapterHash'] = '0' * 64
    try:
        wb._run(runs[0], wb.db.get_spec(experiment['id']), prepared)
        raise AssertionError('Changed adapter was accepted')
    except ValueError as error:
        assert 'adapter changed' in str(error)
    report = {'status': 'passed', 'realDocker': True, 'modelCalls': 0, 'piInstalled': False, 'remotePull': service.status(pull['id'])['result'],
        'adaptedImage': built['tag'], 'experimentId': experiment['id'], 'runs': runs,
        'customCommandFailurePreserved': True, 'twoStepsPerRun': True, 'futureEditDidNotChangeSnapshot': True,
        'adapterVersionChangeRejected': True, 'configurationFileInstalled': True, 'startupMutationRejected': True,
        'exhaustedBudgetDoesNotBlockUnknownUsage': True, 'unknownUsagePreservesFailingTests': True, 'negativeExperimentId': negative['id']}
    (root / 'summary.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != 'runs'}), flush=True)
finally:
    wb.stop()

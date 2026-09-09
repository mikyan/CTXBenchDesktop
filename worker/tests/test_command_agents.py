import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from worker.ctxbench_worker.command_agents import command_agent
from worker.ctxbench_worker.datasets import custom_task, task_document
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.intranet import IntranetWorkbench
from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy, RunResult
from worker.ctxbench_worker.runner import DockerRunner
from worker.ctxbench_worker.workbench import Workbench, Interrupted, usage


def row():
    return {'id': 'task', 'repository': 'https://git.example/repo.git', 'baseCommit': 'a' * 40,
        'prompt': 'Fix the task.', 'image': 'team/test:v1', 'test': {'command': ['python3', '-m', 'unittest']}}


def agent():
    return {'image': 'registry.example/team/agent:v1', 'command': ['/bin/sh', '-eu', '-c', 'agent < "$CTXBENCH_PROMPT_FILE"']}


class CommandAgentTests(unittest.TestCase):
    def test_legacy_bytes_and_solver_payload_stay_unchanged(self):
        old = custom_task(row())
        new = custom_task({**row(), 'agent': agent()})
        self.assertNotIn('agent', task_document(old))
        self.assertEqual(old.solver_payload(), new.solver_payload())
        self.assertEqual(task_document(new)['agent'], agent())

    def test_invalid_commands_and_baked_credentials_rejected(self):
        runtime_command = {**agent(), 'command': ['/bin/sh', '-eu', '-c', 'agent --api-key "$COMPANY_API_KEY" < "$CTXBENCH_PROMPT_FILE"']}
        self.assertEqual(command_agent(runtime_command), runtime_command)
        for value in ({}, {**agent(), 'command': []}, {**agent(), 'command': 'agent'},
                      {**agent(), 'command': ['a\0b']}, {**agent(), 'image': 'https://user:pass@registry/image'},
                      {**agent(), 'command': ['agent --token=secret-value-at-least-12']},
                      {**agent(), 'command': ['agent', '--token', 'short']},
                      {**agent(), 'command': ['x' * 20001]}, {**agent(), 'extra': 'no'}):
            with self.subTest(value=value), self.assertRaises(ValueError): command_agent(value)

    def test_edit_preserves_snapshot_and_disallows_false_budget_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            wb = Workbench(create_mock_engine(Path(directory)), None)
            case = wb.library.save_case({'name': 'Command', 'benchmark': 'custom', 'row': {**row(), 'agent': agent()}})
            frozen, receipt = wb.library.freeze(case['id'])
            wb.library.save_case({'name': 'Command v2', 'benchmark': 'custom', 'expectedRevision': 1,
                                 'row': {**row(), 'agent': {**agent(), 'command': ['new-agent']}}}, case['id'])
            self.assertEqual(wb.catalog.task(frozen, 'task').agent, agent())
            self.assertEqual(receipt['members'][0]['revision'], 1)
            self.assertEqual(wb.library.selection(case['id'])['tasks'][0]['customAgentImage'], agent()['image'])
            model = ModelConfig('mock', 'deterministic', 'off', 1000)
            spec = ExperimentSpec('command', 'custom', frozen, ('none', 'developer-historical'), 1,
                                  ('task',), model, 'unused:latest', ResourcePolicy(), 42)
            wb.validate_inputs(spec)
            wb.budgets.create('budget', 10000, 'mock', 'deterministic')
            custom_model = ModelConfig('company', 'unmetered', 'off', 5000000)
            wb.validate_inputs(replace(spec, budget_id='budget', model=custom_model))
            with self.assertRaisesRegex(ValueError, 'global Pi startup arguments'):
                wb.validate_inputs(replace(spec, agent_args=('--verbose',)))
            self.assertIsNone(usage({'usageAvailable': False})['totalTokens'])
            self.assertTrue(all(value is None for value in usage({'usageAvailable': False, 'cumulativeTokens': 0, 'cost': 0}).values()))

    def test_enabled_metered_roles_and_mixed_cases_keep_budget_model_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            wb = Workbench(create_mock_engine(Path(directory)), None)
            dataset = wb.catalog.register('Mixed', 'custom', [{**row(), 'agent': agent()}, {**row(), 'id': 'pi'}])
            wb.budgets.create('budget', 10000, 'mock', 'deterministic')
            custom = ModelConfig('company', 'unmetered', 'off', 5000000)
            metered = ModelConfig('mock', 'deterministic', 'off', 1000)
            spec = ExperimentSpec('command', 'custom', dataset['id'], ('none', 'developer-historical'), 1,
                ('task',), custom, 'unused:latest', ResourcePolicy(), 42, budget_id='budget')
            wb.validate_inputs(spec)
            builder = replace(spec, arms=('none', 'skill-generated'), profiles={'builder': metered})
            wb.validate_inputs(builder)
            with self.assertRaisesRegex(ValueError, 'Every billable role'):
                wb.validate_inputs(replace(builder, profiles={}))
            judged = replace(spec, evaluate_constraints=True, profiles={'constraintMiner': metered, 'constraintJudge': metered})
            wb.validate_inputs(judged)
            with self.assertRaisesRegex(ValueError, 'Every billable role'):
                wb.validate_inputs(replace(judged, judge_profiles=(custom,) * 3))
            with self.assertRaisesRegex(ValueError, 'Every billable role'):
                wb.validate_inputs(replace(spec, task_ids=('task', 'pi')))
            wb.validate_inputs(replace(spec, task_ids=('task', 'pi'), model=metered))

    def test_missing_usage_runs_and_reuses_checkpoint_despite_exhausted_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wb = Workbench(create_mock_engine(root), None)
            wb.budgets.create('budget', 1, 'mock', 'deterministic')
            wb.budgets.reserve('budget', 'previous', 1, mode='solve', experiment_id=None, output='unused')
            wb.budgets.settle('previous', None)
            original_budget = wb.budgets.snapshot('budget')
            model = ModelConfig('company', 'unmetered', 'off', 5000000)
            spec = ExperimentSpec('command', 'custom', 'unused', ('none', 'developer-historical'), 1,
                ('task',), model, 'unused:latest', ResourcePolicy(), 42, budget_id='budget')
            workspace = root / 'workspace'
            workspace.mkdir()
            def run(request):
                output = Path(request.output_dir)
                output.mkdir(parents=True)
                (output / 'result.json').write_text(json.dumps({'schemaVersion': 1, 'runId': request.run_id, 'status': 'completed', 'usageAvailable': False}))
                (output / 'graded.patch').write_text('')
                return RunResult(request.run_id, 'completed', 0, 1, str(output))
            wb.engine.runner = Mock()
            wb.engine.runner.run.side_effect = run
            stage = wb._agent('command', 'solve', lambda: workspace, 'Prompt', model, spec, 'image', command_agent=agent())
            self.assertEqual(stage['status'], 'completed')
            self.assertIsNone(usage(stage['metadata'])['totalTokens'])
            self.assertEqual(wb._agent('command', 'solve', lambda: workspace, 'Prompt', model, spec, 'image', command_agent=agent()), stage)
            self.assertEqual(wb.engine.runner.run.call_count, 1)
            self.assertEqual(wb.budgets.snapshot('budget'), original_budget)
            with self.assertRaises(Interrupted):
                wb._agent('metered', 'solve', lambda: workspace, 'Prompt', ModelConfig('mock', 'deterministic', 'off', 10), spec, 'image')
            self.assertEqual(wb.engine.runner.run.call_count, 1)

    def test_pull_requires_consent_and_never_overwrites_a_cached_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            wb = Workbench(create_mock_engine(Path(directory)), None)
            service = IntranetWorkbench(wb)
            for payload in ({'image': 'team/image:v1'}, {'image': 'docker pull team/image:v1', 'confirmed': True},
                            {'image': 'sha256:' + 'a' * 64, 'confirmed': True}):
                with self.assertRaises(ValueError): service.enqueue('image-pull', payload)
            operation = service.enqueue('image-pull', {'image': 'team/image:v1', 'confirmed': True})
            wb.engine.runner = Mock(spec=DockerRunner)
            store = Mock()
            store.inspect.return_value = {'installed': True, 'compatible': True, 'imageId': 'sha256:' + 'a' * 64, 'sizeBytes': 10}
            with patch('worker.ctxbench_worker.standard_images.DockerImages') as factory:
                factory.return_value.__enter__.return_value = store
                result = service.pull(operation)
            self.assertTrue(result['cached'])
            store.pull.assert_not_called()

    def test_pull_failure_and_wrong_platform_are_not_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            wb = Workbench(create_mock_engine(Path(directory)), None)
            service = IntranetWorkbench(wb)
            operation = service.enqueue('image-pull', {'image': 'team/image:v2', 'confirmed': True})
            wb.engine.runner = Mock(spec=DockerRunner)
            store = Mock()
            store.inspect.return_value = {'installed': False, 'compatible': True}
            store.pull.side_effect = ValueError('download failed')
            with patch('worker.ctxbench_worker.standard_images.DockerImages') as factory:
                factory.return_value.__enter__.return_value = store
                with self.assertRaisesRegex(ValueError, 'download failed'): service.pull(operation)
            store.inspect.return_value = {'installed': True, 'compatible': False}
            store.pull.reset_mock()
            with patch('worker.ctxbench_worker.standard_images.DockerImages') as factory:
                factory.return_value.__enter__.return_value = store
                with self.assertRaisesRegex(ValueError, 'not Linux amd64'): service.pull(operation)
            store.pull.assert_not_called()

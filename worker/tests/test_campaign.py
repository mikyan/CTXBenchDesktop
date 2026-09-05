import json
import runpy
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

campaign = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts' / 'run-campaign.py'))


class CampaignTests(unittest.TestCase):
    def test_coordinator_lock_excludes_duplicates_and_releases_after_failure(self):
        lock = campaign['campaign_lock']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'injected failure'):
                with lock(root):
                    with self.assertRaisesRegex(RuntimeError, 'another coordinator'):
                        with lock(root):
                            self.fail('A duplicate coordinator acquired the same plan')
                    raise ValueError('injected failure')
            with lock(root):
                self.assertTrue((root / 'coordinator.lock').exists())

    def execution_fixture(self):
        plan = {'budgetId': 'budget', 'limitTokens': 100000000, 'provider': 'xiaomi-token-plan-cn',
                'model': 'mimo-v2.5', 'solverTokens': 300000, 'builderTokens': 800000, 'judgeTokens': 120000,
                'repeats': 2, 'seed': 42, 'agentImage': 'sha256:' + 'a' * 64,
                'tasks': [{'benchmark': 'ctxbench', 'dataset': 'ctx', 'taskId': 'case',
                           'constraintPackageId': None}]}
        records, writes = [], []
        budget = {'remainingTokens': 100000000, 'requestMarginTokens': 2359296}
        def fake_request(api, path, body=None):
            if body is not None:
                writes.append((path, body))
            if path.startswith('/token-budgets'):
                return budget
            if path == '/experiments':
                if body is not None:
                    records.append({**body, 'id': 'exp', 'status': 'completed'})
                    return records[-1]
                return records
            if path == '/snapshot?compact=true':
                return {'runs': [{'experimentId': 'exp', 'status': 'completed', 'testsPassed': index != 0}
                                 for index in range(4)]}
            if path == '/experiments/exp/cancel':
                return {}
            self.fail(f'Unexpected request: {path}')
        return plan, records, writes, budget, fake_request

    def test_execute_and_restart_never_repeat_a_finished_task(self):
        execute = campaign['execute']
        plan, records, writes, _, request = self.execution_fixture()
        with tempfile.TemporaryDirectory() as directory, patch.dict(execute.__globals__, request=request):
            root = Path(directory)
            execute('test', plan, root, None, 0)
            execute('test', plan, root, None, 0)
            state = json.loads((root / 'state.json').read_text())
            self.assertEqual(state['status'], 'completed')
            self.assertEqual(state['index'], 1)
            self.assertEqual(state['results'][0]['gradedRuns'], 4)
            self.assertEqual(state['results'][0]['passedRuns'], 3, 'A functional failure remains a benchmark result')
            self.assertEqual(len(records), 1)
            self.assertEqual(sum(path == '/experiments' for path, _ in writes), 1)

    def test_insufficient_budget_does_not_create_an_experiment(self):
        execute = campaign['execute']
        plan, records, writes, budget, request = self.execution_fixture()
        budget['remainingTokens'] = plan['builderTokens'] + budget['requestMarginTokens'] - 1
        with tempfile.TemporaryDirectory() as directory, patch.dict(execute.__globals__, request=request):
            root = Path(directory)
            execute('test', plan, root, None, 0)
            self.assertEqual(json.loads((root / 'state.json').read_text())['status'], 'budget_paused')
            self.assertFalse(records)
            self.assertFalse(any(path == '/experiments' for path, _ in writes))

    def test_user_pause_or_cancel_stops_campaign_without_advancing(self):
        execute = campaign['execute']
        for status in ('paused', 'ready', 'cancelled'):
            with self.subTest(status=status):
                plan, records, writes, _, request = self.execution_fixture()
                records.append({**campaign['body_for'](plan, plan['tasks'][0], 0), 'id': 'exp', 'status': status})
                with tempfile.TemporaryDirectory() as directory, patch.dict(execute.__globals__, request=request):
                    root = Path(directory)
                    execute('test', plan, root, None, 0)
                    state = json.loads((root / 'state.json').read_text())
                    self.assertEqual(state['status'], 'execution_cancelled' if status == 'cancelled' else 'execution_paused')
                    self.assertEqual(state['index'], 0)
                    self.assertFalse(state['results'])
                    self.assertFalse(any(path == '/experiments' for path, _ in writes))

    def test_low_host_disk_cancels_only_the_active_campaign_experiment(self):
        execute = campaign['execute']
        plan, records, writes, _, request = self.execution_fixture()
        records.extend([{'name': 'other-user-experiment', 'id': 'unrelated', 'status': 'running'},
                        {**campaign['body_for'](plan, plan['tasks'][0], 0), 'id': 'exp', 'status': 'running'}])
        disk = SimpleNamespace(disk_usage=lambda path: SimpleNamespace(free=24 * 1024**3))
        with tempfile.TemporaryDirectory() as directory, patch.dict(execute.__globals__, request=request, shutil=disk):
            root = Path(directory)
            execute('test', plan, root, '/host-volume', 0)
            self.assertEqual(json.loads((root / 'state.json').read_text())['status'], 'host_storage_paused')
            self.assertEqual([path for path, _ in writes if path.startswith('/experiments')], ['/experiments/exp/cancel'])

    def test_plan_is_frozen_task_blind_and_contains_every_official_case_once(self):
        def fake_request(api, path, body=None):
            self.assertIsNone(body, 'Planning must not create a budget or execute an experiment')
            if path == '/datasets':
                return [{'id': 'ctx', 'benchmark': 'ctxbench', 'count': 138}, {'id': 'swe', 'benchmark': 'swebench', 'count': 500}]
            if path == '/constraint-packages':
                return []
            prefix, count = ('ctx', 138) if path == '/datasets/ctx/tasks' else ('swe', 500)
            return [{'id': f'{prefix}-{index}', 'repository': f'https://github.com/org/repo{index % 5}.git',
                     'baseCommit': f'{index:040x}', 'prompt': 'DO_NOT_PERSIST_PROMPT'} for index in range(count)]
        freeze = campaign['freeze_plan']
        with tempfile.TemporaryDirectory() as directory, patch.dict(freeze.__globals__, request=fake_request):
            root = Path(directory)
            plan = freeze('test-only', 'budget', 100000000, root, 'sha256:' + 'a' * 64)
            self.assertEqual(len(plan['tasks']), 638)
            self.assertEqual(len({(task['dataset'], task['taskId']) for task in plan['tasks']}), 638)
            self.assertNotIn('DO_NOT_PERSIST_PROMPT', json.dumps(plan))
            self.assertEqual([item['benchmark'] for item in plan['tasks'][:4]], ['ctxbench', 'swebench'] * 2)
            self.assertEqual(freeze('test-only', 'budget', 100000000, root, 'sha256:' + 'a' * 64), plan)
            with self.assertRaises(ValueError):
                freeze('test-only', 'budget', 200000000, root, 'sha256:' + 'a' * 64)
            body = campaign['body_for'](plan, plan['tasks'][0], 0)
            self.assertEqual(body['budgetId'], 'budget')
            self.assertEqual(body['repeats'], 2)
            self.assertEqual({profile['model'] for profile in body['profiles'].values()}, {'mimo-v2.5'})
            self.assertFalse(body['evaluateConstraints'])

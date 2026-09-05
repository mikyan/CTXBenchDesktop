import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

campaign = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts' / 'run-campaign.py'))


class CampaignTests(unittest.TestCase):
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

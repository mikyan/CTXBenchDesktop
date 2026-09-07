import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.history import GitHubClient
from worker.ctxbench_worker.runner import DockerRunner
from worker.ctxbench_worker.catalog import Catalog


def manifest():
    return {"name": "Authoring fixture", "benchmark": "custom", "rows": [{
        "id": "task-1", "repository": "https://gitee.com/example/repo.git",
        "baseCommit": "a" * 40, "prompt": "  Fix behavior.\n", "image": "fixture/tests:baseline",
        "test": {"command": ["/bin/sh", "-eu", "-c", "python -m pytest -q"], "hiddenPatch": "private test patch"},
        "goldPatch": "private reference patch",
    }]}


class DatasetAuthoringTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = create_mock_engine(self.root)
        self.client = TestClient(create_app(self.engine, GitHubClient(None)))
        self.addCleanup(self.client.close)
        self.catalog = Catalog(self.root, self.engine.database)

    def test_validation_is_read_only_and_returns_no_evaluator_inputs(self):
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob('*'))
        with patch.object(self.engine.runner, 'run', side_effect=AssertionError('must not run agents')):
            response = self.client.post('/v1/datasets/validate', json=manifest())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"valid": True, "count": 1, "testsExecuted": False})
        self.assertEqual(self.catalog.list(), [])
        self.assertEqual(before, sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob('*')))

    def test_creates_multiple_tasks_and_keeps_private_inputs_out_of_public_tasks(self):
        body = manifest()
        second = copy.deepcopy(body['rows'][0])
        second.update(id='task-2', repository='https://git.company.example/team/repo.git', baseCommit='b' * 40)
        second.pop('image')
        second['build'] = {'dockerfile': 'Dockerfile', 'context': '.', 'args': {'VERSION': '3.12'}}
        second['test']['command'] = ['python', '-c', 'print("two words")', '']
        body['rows'].append(second)
        response = self.client.post('/v1/datasets', json=body)
        self.assertEqual(response.status_code, 201, response.text)
        key = response.json()['id']
        self.assertEqual(response.json()['count'], 2)
        public = self.client.get(f'/v1/datasets/{key}/tasks')
        self.assertEqual(len(public.json()), 2)
        for private in ['private test patch', 'private reference patch', 'test_command', 'hidden_test_patch', 'gold_patch']:
            self.assertNotIn(private, public.text + response.text)
        task = self.catalog.task(key, 'task-1')
        self.assertEqual(task.prompt, body['rows'][0]['prompt'])
        self.assertEqual(task.hidden_test_patch, 'private test patch')
        self.assertNotIn('private', str(task.solver_payload()))
        self.assertEqual(self.catalog.task(key, 'task-2').test_command, tuple(second['test']['command']))

    def test_registration_and_validation_reject_bad_fields_without_partial_dataset(self):
        invalid = [
            {'baseCommit': 'main'}, {'prompt': ' '}, {'id': 123},
            {'repository': 'https://user:password@git.example/repo.git'},
            {'repository': 'https://git.example/repo.git?token=fixture-only'},
            {'unexpected': 'field'}, {'metadata': []}, {'test': {'command': ['pytest'], 'typo': 'patch'}},
            {'build': {'dockerfile': 'Dockerfile', 'typo': '.'}},
            {'image': 'has whitespace'}, {'test': {'command': []}}, {'test': {'command': ['']}},
            {'test': {'command': ['python', 1]}}, {'test': {'command': 'pytest -q'}},
            {'test': {'command': ['pytest'], 'hiddenPatch': {}}}, {'goldPatch': ['patch']},
            {'build': {'dockerfile': '../Dockerfile'}}, {'build': {'dockerfile': '/Dockerfile'}},
            {'build': {'dockerfile': 'Dockerfile', 'context': '../outside'}},
            {'build': {'dockerfile': 'Dockerfile', 'args': {'X': 42}}}, {'build': {}},
            {'prompt': 'bad\0prompt'},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                body = manifest()
                bad = {**copy.deepcopy(body['rows'][0]), 'id': 'task-2', **changes}
                body['rows'].append(bad)
                for route in ['/v1/datasets/validate', '/v1/datasets']:
                    response = self.client.post(route, json=body)
                    self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.catalog.list(), [])
                self.assertEqual(list((self.root / 'datasets').glob('*.json')), [])

    def test_duplicate_ids_are_rejected(self):
        body = manifest()
        body['rows'] *= 2
        for route in ['/v1/datasets/validate', '/v1/datasets']:
            self.assertEqual(self.client.post(route, json=body).status_code, 422)

    def test_validation_requires_inline_rows_and_does_not_read_paths(self):
        for rows in [None, {}, 'file.json', [1], []]:
            body = {**manifest(), 'rows': rows, 'path': 'not-a-real.parquet'}
            response = self.client.post('/v1/datasets/validate', json=body)
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.catalog.list(), [])

    def test_rejects_configured_credentials_even_in_escaped_nested_strings(self):
        self.engine.runner = DockerRunner(self.root / 'repositories', self.root / 'runs', self.root / 'requests', env_allowlist=frozenset({'FIXTURE_KEY'}))
        secret = 'fixture-only-"quoted"-密钥'
        with patch.dict(os.environ, {'FIXTURE_KEY': secret}):
            for target in ['name', 'prompt', 'hiddenPatch', 'goldPatch', 'buildArg']:
                body = manifest()
                if target == 'name':
                    body['name'] = secret
                elif target == 'hiddenPatch':
                    body['rows'][0]['test']['hiddenPatch'] = secret
                elif target == 'buildArg':
                    body['rows'][0]['build'] = {'dockerfile': 'Dockerfile', 'args': {'TOKEN': secret}}
                else:
                    body['rows'][0][target] = secret
                for route in ['/v1/datasets/validate', '/v1/datasets']:
                    response = self.client.post(route, json=body)
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertNotIn(secret, response.text)
        self.assertEqual(self.catalog.list(), [])

    def test_validation_is_idempotent_and_does_not_modify_frozen_data(self):
        body = manifest()
        registered = self.client.post('/v1/datasets', json=body).json()
        key = registered['id']
        before = (self.root / 'datasets' / f'{key}.json').read_bytes()
        for _ in range(2):
            self.assertEqual(self.client.post('/v1/datasets/validate', json=body).status_code, 200)
        self.assertEqual(self.catalog.list(), [registered])
        self.assertEqual((self.root / 'datasets' / f'{key}.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()

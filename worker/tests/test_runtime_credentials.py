import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.history import GitHubClient
from worker.ctxbench_worker.runner import DockerRunner, selected_environment


class RuntimeCredentialsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = create_mock_engine(self.root)
        self.engine.runner = DockerRunner(self.root / 'repositories', self.root / 'runs', self.root / 'requests')
        self.history = GitHubClient(None)
        self.client = TestClient(create_app(self.engine, self.history))
        self.addCleanup(self.client.close)
        environment = patch.dict(os.environ, {}, clear=False)
        environment.start()
        self.addCleanup(environment.stop)

    def test_saves_multiple_variables_and_returns_names_only(self):
        variables = [
            {'name': 'INTERNAL_AGENT_KEY', 'value': 'fixture-only-secret=value,not-real'},
            {'name': 'INTERNAL_AGENT_URL', 'value': 'https://provider.invalid/v1'},
        ]
        response = self.client.post('/v1/runtime/credentials', json={'variables': variables})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'credentials': [
            {'name': item['name'], 'configured': True} for item in variables
        ]})
        names = tuple(item['name'] for item in variables)
        self.assertEqual(selected_environment(names, self.engine.runner.env_allowlist),
                         {item['name']: item['value'] for item in variables})
        settings = self.client.get('/v1/runtime')
        configured = {item['name']: item['configured'] for item in settings.json()['credentials']}
        self.assertTrue(all(configured[name] for name in names))
        snapshot = self.client.get('/v1/snapshot').text
        for item in variables:
            self.assertNotIn(item['value'], response.text + settings.text + snapshot)

    def test_invalid_batch_does_not_partially_overwrite_or_allowlist(self):
        os.environ['INTERNAL_AGENT_KEY'] = 'old-fixture-value'
        original_allowlist = self.engine.runner.env_allowlist
        response = self.client.post('/v1/runtime/credentials', json={'variables': [
            {'name': 'INTERNAL_AGENT_KEY', 'value': 'replacement-fixture-value'},
            {'name': 'DOCKER_HOST', 'value': 'do-not-change-worker'},
        ]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(os.environ['INTERNAL_AGENT_KEY'], 'old-fixture-value')
        self.assertEqual(self.engine.runner.env_allowlist, original_allowlist)
        self.assertNotIn('replacement-fixture-value', response.text)
        self.assertNotIn('do-not-change-worker', response.text)

    def test_rejects_duplicate_names_and_nul_values_before_writing(self):
        os.environ.pop('INTERNAL_AGENT_KEY', None)
        for second in [
            {'name': 'INTERNAL_AGENT_KEY', 'value': 'fixture-second'},
            {'name': 'INTERNAL_AGENT_URL', 'value': 'fixture\0value'},
        ]:
            response = self.client.post('/v1/runtime/credentials', json={'variables': [
                {'name': 'INTERNAL_AGENT_KEY', 'value': 'fixture-first'}, second,
            ]})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('INTERNAL_AGENT_KEY', os.environ)
            self.assertNotIn('fixture', response.text)

    def test_rejects_malformed_batches_without_echoing_request_values(self):
        for body in [
            {'variables': []}, {'variables': 'fixture-secret'}, ['fixture-secret'],
            {'variables': [{'name': 'INTERNAL_AGENT_KEY', 'value': {'secret': 'fixture-secret'}}]},
            {'variables': [{'name': 'INVALID=fixture-secret', 'value': 'fixture-secret'}]},
            {'variables': [{'name': 'INTERNAL_AGENT_KEY'}]},
            {'variables': [None]}, {'variables': [], 'name': 'fixture-secret'},
            {'variables': [{'name': f'KEY_{index}', 'value': 'fixture-secret'} for index in range(101)]},
        ]:
            with self.subTest(body_type=type(body).__name__):
                response = self.client.post('/v1/runtime/credentials', json=body)
                self.assertEqual(response.status_code, 422)
                self.assertNotIn('fixture-secret', response.text)

    def test_pending_preparation_blocks_the_entire_batch(self):
        os.environ.pop('INTERNAL_AGENT_KEY', None)
        self.engine.database.put_document('operations', 'pending', {'id': 'pending', 'status': 'queued'})
        response = self.client.post('/v1/runtime/credentials', json={'variables': [
            {'name': 'INTERNAL_AGENT_KEY', 'value': 'fixture-secret'},
            {'name': 'INTERNAL_AGENT_URL', 'value': 'https://provider.invalid'},
        ]})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('INTERNAL_AGENT_KEY', os.environ)
        self.assertNotIn('INTERNAL_AGENT_KEY', self.engine.runner.env_allowlist)

    def test_single_variable_api_and_github_client_remain_compatible(self):
        response = self.client.post('/v1/runtime/credentials', json={'name': 'GITHUB_TOKEN', 'value': 'fixture-github-token'})
        self.assertEqual(response.json(), {'name': 'GITHUB_TOKEN', 'configured': True})
        self.assertEqual(self.history.token, 'fixture-github-token')
        response = self.client.post('/v1/runtime/credentials', json={'variables': [
            {'name': 'GITHUB_TOKEN', 'value': ''},
            {'name': 'INTERNAL_AGENT_URL', 'value': 'https://provider.invalid'},
        ]})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.history.token)
        self.assertNotIn('GITHUB_TOKEN', os.environ)


if __name__ == '__main__':
    unittest.main()

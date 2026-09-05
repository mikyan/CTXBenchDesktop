import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.safe_files import safe_file


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = create_mock_engine(self.root)
        # No lifespan here: these are boundary tests, not background job executions.
        self.client = TestClient(create_app(self.engine))

    def test_rejects_browser_cross_origin_writes(self):
        response = self.client.post('/v1/datasets', json={}, headers={'Origin': 'https://evil.invalid'})
        self.assertEqual(response.status_code, 403)

    def test_rejects_traversal_in_raw_runs_and_datasets(self):
        body = {'runId': '../../escape', 'workspace': 'repo', 'prompt': 'test',
                'model': {'provider': 'mock', 'model': 'deterministic'}, 'resources': {}}
        self.assertEqual(self.client.post('/v1/runs', json=body).status_code, 422)
        body.update(runId='safe-id', workspace='../escape')
        self.assertEqual(self.client.post('/v1/runs', json=body).status_code, 422)
        self.assertEqual(self.client.post('/v1/datasets', json={'path': '../ctxbench.sqlite3'}).status_code, 422)

    def test_credential_is_never_returned(self):
        with patch.dict('os.environ', {}, clear=False):
            response = self.client.post('/v1/runtime/credentials', json={'name': 'OPENAI_API_KEY', 'value': 'fake-test-secret-only'})
            self.assertEqual(response.status_code, 200)
            settings = self.client.get('/v1/runtime').text
            self.assertNotIn('fake-test-secret-only', settings)
            self.assertNotIn('fake-test-secret-only', self.client.get('/v1/snapshot').text)
            self.assertEqual(self.client.post('/v1/runtime/credentials', json={'name': 'DOCKER_HOST', 'value': 'x'}).status_code, 422)

    def test_output_size_and_path_boundaries(self):
        with self.assertRaises(ValueError):
            safe_file(self.root, '../outside')
        file = self.root / 'large'
        file.write_bytes(b'12345')
        with self.assertRaises(ValueError):
            safe_file(self.root, 'large', limit=4)
        target = self.root / 'target'
        target.mkdir()
        link = self.root / 'link'
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest('OS does not permit unprivileged symlinks')
        with self.assertRaises(ValueError):
            safe_file(self.root, 'link/output.json')


if __name__ == '__main__':
    unittest.main()

import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.dataset_files import DatasetFiles
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.workbench import Workbench
from worker.tests.test_dataset_authoring import manifest


class DatasetFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = create_mock_engine(self.root)
        self.client = TestClient(create_app(self.engine))
        self.addCleanup(self.client.close)

    def preview(self, data=None, **query):
        return self.client.post('/v1/datasets/files/preview', content=data if data is not None else json.dumps(manifest()).encode(),
            params={"filename": "中文 data.json", "name": "My dataset", "benchmark": "custom", **query}, headers={"Content-Type": "application/octet-stream"})

    def test_preview_then_confirm_is_idempotent_and_keeps_evaluator_data_private(self):
        with patch.object(self.engine.runner, "run", side_effect=AssertionError("Must not run an Agent")):
            result = self.preview()
            self.assertEqual(result.status_code, 200, result.text)
            preview = result.json()
            self.assertEqual(preview['count'], 1)
            self.assertEqual(preview['testsExecuted'], False)
            self.assertEqual(self.client.get('/v1/datasets').json(), [])
            self.assertEqual(list((self.root / 'datasets').iterdir()), [])
            for field in ('private reference patch', 'private test patch', 'goldPatch', 'hiddenPatch'):
                self.assertNotIn(field, result.text)
            for _ in range(2):
                saved = self.client.post(f"/v1/datasets/files/{preview['token']}/confirm")
                self.assertEqual(saved.status_code, 201, saved.text)
                self.assertEqual(saved.json()['count'], 1)
            self.assertEqual(len(self.client.get('/v1/datasets').json()), 1)

    def test_jsonl_bom_and_discard_do_not_register_anything(self):
        data = b'\xef\xbb\xbf' + json.dumps(manifest()['rows'][0]).encode() + b'\n'
        result = self.preview(data, filename='fixture.JSONL')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['sha256'], hashlib.sha256(data).hexdigest())
        token = result.json()['token']
        self.assertEqual(self.client.post(f'/v1/datasets/files/{token}/discard').status_code, 200)
        self.assertEqual(self.client.post(f'/v1/datasets/files/{token}/confirm').status_code, 422)
        self.assertEqual(self.client.get('/v1/datasets').json(), [])

    def test_rejects_invalid_formats_paths_mismatched_sources_and_secrets(self):
        for data, values in [
            (b'', {}), (b'<html>not a download</html>', {'filename': 'data.parquet'}),
            (b'version https://git-lfs.github.com/spec/v1', {'filename': 'data.parquet'}),
            (b'{}', {'filename': '../escape.json'}), (b'{}', {'filename': 'installer.exe'}),
            (b'invalid', {'filename': 'data.jsonl'}),
            (json.dumps(manifest()).encode(), {'benchmark': 'ctxbench'}),
        ]:
            with self.subTest(values=values):
                result = self.preview(data, **values)
                self.assertEqual(result.status_code, 422, result.text)
                self.assertNotIn('do-not-leak', result.text)
        self.assertEqual(list((self.root / 'datasets').iterdir()), [])

    def test_configured_credentials_are_rejected_without_echo_or_persistence(self):
        self.engine.runner.env_allowlist = frozenset({'FIXTURE_KEY'})
        with patch.dict(os.environ, {'FIXTURE_KEY': 'do-not-leak'}):
            for data, query in [
                (json.dumps(manifest()).encode(), {'name': 'do-not-leak'}),
                (json.dumps({**manifest(), 'rows': [{**manifest()['rows'][0], 'goldPatch': 'do-not-leak'}]}).encode(), {}),
            ]:
                response = self.preview(data, **query)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn('do-not-leak', response.text)
        self.assertEqual(list((self.root / 'datasets').iterdir()), [])

    def test_streaming_limit_and_origin_checks_precede_registration(self):
        with patch('worker.ctxbench_worker.api.MAX_DATASET_BYTES', 16):
            self.assertEqual(self.preview(b'a' * 17).status_code, 413)
            response = self.client.post('/v1/datasets/files/preview?filename=a.json&name=A&benchmark=custom', content=iter([b'a' * 10, b'b' * 10]))
            self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.post('/v1/datasets/files/preview', content=b'{}', headers={'Origin': 'https://evil.invalid'}).status_code, 403)

    def test_parquet_conversion_uses_private_temporary_path_and_always_cleans_it(self):
        from worker.ctxbench_worker.runtime import Runtime
        paths = []
        def convert(runtime, path):
            paths.append(path)
            self.assertTrue(path.is_file())
            self.assertTrue(path.is_relative_to(self.root / 'datasets'))
            return manifest()['rows']
        data = b'PAR1fixturePAR1'
        with patch.object(Runtime, 'import_parquet', convert):
            response = self.preview(data, filename='download.parquet')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(all(not path.exists() for path in paths))
        with patch.object(Runtime, 'import_parquet', side_effect=RuntimeError('private reference patch')):
            failed = self.preview(data, filename='download.parquet')
        self.assertEqual(failed.status_code, 422)
        self.assertNotIn('private reference patch', failed.text)
        self.assertEqual(list((self.root / 'datasets').iterdir()), [])

    def test_preview_expiry_and_memory_limit_are_bounded(self):
        workbench = Workbench(self.engine, None)
        service = DatasetFiles(workbench, lambda _: None)
        result = service.preview(json.dumps(manifest()).encode(), 'file.json', 'Name', 'custom')
        service.pending[result['token']]['expires'] = time.monotonic() - 1
        with self.assertRaisesRegex(ValueError, 'expired'):
            service.confirm(result['token'])
        with patch('worker.ctxbench_worker.dataset_files.MAX_CACHE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'too large'):
                service.preview(json.dumps(manifest()).encode(), 'file.json', 'Name', 'custom')


if __name__ == '__main__':
    unittest.main()

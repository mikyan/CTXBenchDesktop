import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.history import GitHubClient
from worker.ctxbench_worker.live_logs import ContainerLogs, log_scope, scoped, runtime_secrets
from worker.ctxbench_worker.command_adapter import RedactedStream
from worker.ctxbench_worker.runner import DockerRunner
from worker.ctxbench_worker.runtime import Runtime
from worker.ctxbench_worker.models import ModelConfig, ResourcePolicy, RunSpec


class RedactionTests(unittest.TestCase):
    def test_all_byte_boundaries_and_json_encodings(self):
        secret = 'fixture-密钥\\"秘密'
        for value in (secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]):
            raw = ('开始🙂 ' + value + ' done\n').encode()
            for index in range(len(raw) + 1):
                redactor = RedactedStream([secret])
                got = redactor.feed(raw[:index]) + redactor.feed(raw[index:]) + redactor.feed(final=True)
                self.assertEqual(got, '开始🙂 [REDACTED] done\n', (value, index))

    def test_prefixes_are_held_even_without_a_newline(self):
        redactor = RedactedStream(['fixture-secret'])
        self.assertEqual(redactor.feed(b'loading fixture-'), 'loading ')
        self.assertEqual(redactor.feed(b'secret ready'), '[REDACTED] ready')
        self.assertEqual(redactor.feed(final=True), '')
        redactor = RedactedStream(['fixture-secret'])
        self.assertEqual(redactor.feed(b'loading fixture-'), 'loading ')
        self.assertEqual(redactor.feed(final=True), '[REDACTED]')

    def test_overlapping_values_and_unescaped_punctuation(self):
        for values in (['aaab', 'ab'], ['abc', 'bcd'], ['x.*[0]'], ['a', 'abcdef']):
            raw = ('before ' + values[0] + ' ' + values[1 if len(values) > 1 else 0] + ' after\n').encode()
            for size in range(1, len(raw) + 1):
                redactor = RedactedStream(values)
                got = ''.join(redactor.feed(raw[i:i + size]) for i in range(0, len(raw), size)) + redactor.feed(final=True)
                for value in values:
                    self.assertNotIn(value, got)


class LiveLogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = ContainerLogs(self.root)

    def test_cursor_is_unicode_based_and_snapshot_has_no_body(self):
        with log_scope(experimentId='experiment-one', operationId='op-one'):
            key = self.store.create('solve', benchmarkRunId='pair-one')
        self.store.append(key, '中文🙂\x00\n')
        page = self.store.read(key)
        self.assertEqual(page['content'], '中文🙂\\0\n')
        self.assertEqual(page['nextOffset'], 6)
        self.store.append(key, 'next')
        self.assertEqual(self.store.read(key, page['nextOffset'])['content'], 'next')
        self.assertEqual(self.store.read(key, 10)['content'], '')
        listed = self.store.list(experimentId='experiment-one')
        self.assertEqual(listed[0]['benchmarkRunId'], 'pair-one')
        self.assertNotIn('content', listed[0])
        self.assertEqual(self.store.list(experimentId='experiment-other'), [])

    def test_complete_archive_pagination_and_old_cursor(self):
        key = self.store.create('solve', runId='run-one')
        self.store.append(key, 'x' * 1_200_000)
        page = self.store.read(key)
        self.assertEqual(len(page['content']), 64_000)
        self.assertFalse(page['truncated'])
        self.assertEqual(page['startOffset'], 0)
        stale = self.store.read(key, 0)
        self.assertFalse(stale['reset'])
        self.assertEqual(stale['nextOffset'], 64_000)
        page = self.store.read(key, page['startOffset'])
        self.assertTrue(page['hasMore'])
        self.assertFalse(page['reset'])
        self.assertTrue(self.store.read(key, 2_000_000)['reset'])
        content, offset = '', 0
        while True:
            page = self.store.read(key, offset)
            content += page['content']; offset = page['nextOffset']
            if not page['hasMore']:
                break
        self.assertEqual(content, 'x' * 1_200_000)

    def test_retention_keeps_running_logs_and_receipts(self):
        active = self.store.create('solve', runId='active')
        self.store.append(active, 'still running')
        old = self.store.create('solve', runId='old')
        self.store.append(old, 'old console')
        self.store.finish(old, 0)
        newer = self.store.create('solve', runId='newer')
        self.store.append(newer, 'recent console')
        self.store.finish(newer, 1)
        for index in range(52):
            self.store.finish(self.store.create('test', runId='extra-' + str(index)))
        self.assertEqual(self.store.read(old)['content'], 'old console')
        self.assertFalse(self.store.read(old)['truncated'])
        self.assertEqual(self.store.read(old)['exitCode'], 0)
        self.assertEqual(self.store.read(active)['content'], 'still running')
        self.assertEqual(self.store.read(newer)['content'], 'recent console')

    def test_restart_marks_observer_interrupted_not_task_failed(self):
        key = self.store.create('solve', runId='run-one')
        with patch('worker.ctxbench_worker.live_logs._owner', 'new-process'):
            self.assertEqual(self.store.read(key)['state'], 'interrupted')
            self.assertIsNone(self.store.read(key)['exitCode'])
        self.store.finish(key, 17)
        self.store.finish(key, error='Late observer shutdown')
        self.assertEqual(self.store.read(key)['exitCode'], 17)

    def test_scope_decorator_propagates_kwargs_and_restores_after_error(self):
        store = self.store
        class Scoped:
            @scoped('operationId', 'id')
            def execute(self, operation):
                store.create('solve', runId='scoped-run')
                raise ValueError('fixture')
        with self.assertRaises(ValueError):
            Scoped().execute(operation={'id': 'op-one'})
        self.assertEqual(len(store.list(operationId='op-one')), 1)
        key = store.create('test', runId='outside')
        self.assertNotIn('operationId', store.read(key))

    def test_capture_visible_before_exit_and_redacted_before_persistence(self):
        proceed = threading.Event()
        def logs(**kwargs):
            yield b'first fixture-'
            yield b'secret line\n'
            proceed.wait(4)
            yield '结束\n'.encode()
        container = MagicMock()
        container.logs.side_effect = logs
        capture = self.store.capture(container, 'solve', ['fixture-secret'], runId='run-one')
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                page = self.store.read(capture.key)
                if '\n' in page['content']:
                    break
                time.sleep(.01)
            self.assertTrue(capture.thread.is_alive())
            self.assertEqual(page['state'], 'streaming')
            self.assertEqual(page['content'], 'first [REDACTED] line\n')
            with self.store.db() as db:
                self.assertNotIn('fixture-secret', str([tuple(row) for row in db.execute('SELECT * FROM chunks')]))
        finally:
            proceed.set()
            capture.finish(17)
        self.assertEqual(self.store.read(capture.key)['exitCode'], 17)
        self.assertTrue(self.store.read(capture.key)['content'].endswith('结束\n'))
        self.assertEqual(self.store.read(capture.key)['state'], 'ended')

    def test_collector_failure_is_generic_and_does_not_fail_runner(self):
        workspace = self.root / 'repositories' / 'fixture'
        workspace.mkdir(parents=True)
        runner = DockerRunner(workspace.parent, self.root / 'runs', self.root / 'requests')
        spec = RunSpec('isolated-run', 'solve', 'fixture', str(workspace), str(self.root / 'runs' / 'isolated-run'),
                       'unchanged prompt', ModelConfig('mock', 'deterministic', 'off', 10), ResourcePolicy(network='offline'))
        with patch('docker.from_env') as factory, patch('worker.ctxbench_worker.runner._chown_tree'):
            container = factory.return_value.containers.run.return_value
            container.wait.return_value = {'StatusCode': 0}
            container.logs.side_effect = lambda **kwargs: (_ for _ in ()).throw(RuntimeError('fixture-secret')) if kwargs.get('stream') else b'final log'
            self.assertEqual(runner.run(spec).status, 'completed')
        session = self.store.list(runId='isolated-run')[0]
        self.assertEqual(session['state'], 'unavailable')
        self.assertEqual(session['exitCode'], 0)
        self.assertNotIn('fixture-secret', session['error'])

    def test_api_empty_live_and_invalid_scopes(self):
        engine = create_mock_engine(self.root)
        with TestClient(create_app(engine, GitHubClient(None))) as client:
            self.assertEqual(client.get('/v1/container-logs?runId=one').json(), {'sessions': [], 'nextBefore': None})
            self.assertEqual(client.get('/v1/container-logs').status_code, 422)
            self.assertEqual(client.get('/v1/container-logs', params={'runId': '../outside'}).status_code, 422)
            key = self.store.create('test', runId='one')
            self.store.append(key, 'live output')
            self.assertEqual(client.get('/v1/container-logs?runId=one').json()['sessions'][0]['id'], key)
            self.assertEqual(client.get('/v1/container-logs/' + key).json()['content'], 'live output')
            for cursor in ['-1', 'invalid', str(2**53)]:
                self.assertEqual(client.get('/v1/container-logs/' + key, params={'offset': cursor}).status_code, 422)
            self.assertEqual(client.get('/v1/container-logs/' + 'f' * 32).status_code, 404)
            self.assertEqual(client.get('/v1/container-logs?runId=one', headers={'Origin': 'https://untrusted.invalid'}).status_code, 403)

    def test_secret_snapshot_does_not_change_forwarded_environment(self):
        with patch.dict('os.environ', {'VISIBLE_CUSTOM': 'synthetic-url', 'INTERNAL_API_KEY': 'synthetic-key', 'NORMAL': 'untouched'}, clear=True):
            self.assertEqual(set(runtime_secrets(['VISIBLE_CUSTOM'])), {'synthetic-url', 'synthetic-key'})

    def test_dataset_transfer_is_not_captured_or_rotated_as_console_output(self):
        runner = DockerRunner(self.root / 'repositories', self.root / 'runs', self.root / 'requests')
        with patch('docker.from_env') as factory:
            container = factory.return_value.containers.run.return_value
            container.wait.return_value = {'StatusCode': 0}
            container.logs.return_value = b'EVALUATOR_ONLY_PARQUET_EXPORT'
            with log_scope(operationId='import'):
                result = Runtime(self.root, runner).command('fixture-harness', ['catalog'], volumes={}, output=self.root / 'import',
                    resources=ResourcePolicy(), record_logs=False)
            self.assertEqual(result, b'EVALUATOR_ONLY_PARQUET_EXPORT')
            self.assertNotIn('log_config', factory.return_value.containers.run.call_args.kwargs)
            container.logs.assert_called_once_with()
            self.assertEqual(self.store.list(operationId='import'), [])
            self.assertFalse((self.root / 'import/evaluator.log').exists())


if __name__ == '__main__':
    unittest.main()

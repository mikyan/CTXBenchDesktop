import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from worker.ctxbench_worker.diagnostics import observed, phase, note, details, docker_event, docker_build
from worker.ctxbench_worker.live_logs import ContainerLogs, log_scope
from worker.ctxbench_worker.runner import DockerRunner
from worker.ctxbench_worker.models import RunSpec, RunResult, ModelConfig, ResourcePolicy, ExperimentSpec
from worker.ctxbench_worker.runtime import Runtime, git
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.workbench import Workbench


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.logs = ContainerLogs(self.root)

    def harness(self):
        root = self.root
        class Harness:
            def __init__(self):
                self.root = root
            @observed('fixture execution')
            def run(self, action):
                return action()
        return Harness()

    def test_pre_agent_error_has_stage_original_chain_and_credential_safe_archive(self):
        def fail():
            with phase('Fetch frozen Git baseline'):
                try:
                    raise OSError('fixture inner cause')
                except OSError as cause:
                    raise ValueError('Cannot fetch https://user:synthetic-url-password@git.invalid/repo with ' + os.environ['FIXTURE_API_KEY']) from cause
        with patch.dict(os.environ, {'FIXTURE_API_KEY': 'synthetic-runtime-credential'}), log_scope(operationId='pre-agent'):
            with self.assertRaises(ValueError) as raised:
                self.harness().run(fail)
        receipt = details(raised.exception)
        self.assertEqual(receipt['stage'], 'Fetch frozen Git baseline')
        self.assertFalse(receipt['agentStarted'])
        page = self.logs.read(receipt['logSessionId'], 0)
        self.assertIn('Traceback', page['content'])
        self.assertIn('fixture inner cause', page['content'])
        self.assertIn('direct cause', page['content'])
        self.assertNotIn('synthetic-runtime-credential', page['content'])
        self.assertNotIn('synthetic-url-password', page['content'])
        self.assertEqual(page['failure']['stage'], receipt['stage'])

    def test_git_full_stderr_survives_the_short_exception_summary(self):
        stderr = b'FIRST_ERROR\n' + b'diagnostic output\n' * 30000 + b'LAST_ERROR\n'
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 128, b'EVALUATOR_STDOUT_MUST_NOT_BE_LOGGED', stderr)), log_scope(operationId='git'):
            with self.assertRaises(RuntimeError):
                self.harness().run(lambda: git(self.root, 'fetch', 'origin', 'a' * 40))
        key = self.logs.list(operationId='git')[0]['id']
        full = self.complete(key)
        self.assertIn('FIRST_ERROR', full)
        self.assertIn('LAST_ERROR', full)
        self.assertNotIn('EVALUATOR_STDOUT_MUST_NOT_BE_LOGGED', full)
        self.assertGreater(len(full), 500000)

    def complete(self, key):
        chunks, offset = [], 0
        while True:
            page = self.logs.read(key, offset)
            chunks.append(page['content']); offset = page['nextOffset']
            if not page['hasMore']:
                return ''.join(chunks)

    def test_docker_create_error_is_recorded_without_a_container(self):
        runner = DockerRunner(self.root / 'repositories', self.root / 'runs', self.root / 'requests')
        tree = self.root / 'repositories/fixture'; tree.mkdir()
        spec = RunSpec('failed-launch', 'solve', 'fixture-image', str(tree), str(self.root / 'runs/failed-launch'),
            'UNCHANGED_PROMPT_DO_NOT_LOG', ModelConfig('mock', 'deterministic', 'off', 10), ResourcePolicy(network='offline'))
        with patch('docker.from_env') as factory, patch('worker.ctxbench_worker.runner._chown_tree'):
            factory.return_value.containers.run.side_effect = RuntimeError('OCI runtime create failed: permission denied on mount')
            result = runner.run(spec)
        self.assertEqual(result.status, 'failed')
        session = self.logs.list(runId='failed-launch')[0]
        self.assertEqual(session['failure']['stage'], 'Create and start Agent container')
        self.assertFalse(session['failure']['agentStarted'])
        self.assertNotIn('UNCHANGED_PROMPT_DO_NOT_LOG', self.complete(session['id']))
        self.assertIn('OCI runtime', self.complete(session['id']))

    def test_build_events_saved_from_start_and_failure_not_retried(self):
        import docker
        client = MagicMock()
        client.api.build.return_value = iter([{'stream': 'EARLY_BUILD\n'}, {'stream': 'x' * 1_200_000 + '\n'}, {'error': 'Missing package fixture'}])
        with log_scope(operationId='build'):
            with self.assertRaises(docker.errors.BuildError):
                self.harness().run(lambda: docker_build(client, path='/fixture', rm=True))
        key = self.logs.list(operationId='build')[0]['id']
        full = self.complete(key)
        self.assertTrue('EARLY_BUILD' in full and 'Missing package fixture' in full)
        self.assertGreater(len(full), 1_200_000)
        client.api.build.assert_called_once_with(decode=True, path='/fixture', rm=True)

    def test_workbench_does_not_replace_launch_error_with_missing_agent_result(self):
        wb = Workbench(create_mock_engine(self.root), None)
        model = ModelConfig('mock', 'deterministic', 'off', 100)
        spec = ExperimentSpec('Fixture', 'custom', 'fixture', ('none', 'developer-historical'), 1, ('one',), model, 'fixture', ResourcePolicy(), 1)
        failed = RunResult('fixture', 'failed', 1, 0, str(self.root), failure='OCI runtime create failed: permission denied on fixture mount')
        with patch.object(wb.engine.runner, 'run', return_value=failed), log_scope(operationId='agent-start-failed'):
            with self.assertRaisesRegex(RuntimeError, 'OCI runtime create failed') as raised:
                self.harness().run(lambda: wb._agent('fixture', 'solve', lambda: self.root, 'UNCHANGED_PRIVATE_PROMPT', model, spec, 'fixture'))
        self.assertNotIn('result contract invalid', str(raised.exception))
        full = self.complete(self.logs.list(operationId='agent-start-failed')[0]['id'])
        self.assertIn('OCI runtime create failed', full)
        self.assertNotIn('UNCHANGED_PRIVATE_PROMPT', full)

    def test_split_credentials_do_not_leak_in_build_fragments(self):
        def action():
            docker_event({'stream': 'step secret-prefix-'})
            docker_event({'stream': 'tail\n'})
        with patch.dict(os.environ, {'FIXTURE_API_KEY': 'secret-prefix-tail'}), log_scope(operationId='split'):
            self.harness().run(action)
        full = self.complete(self.logs.list(operationId='split')[0]['id'])
        self.assertNotIn('secret-prefix-', full)
        self.assertIn('[REDACTED]', full)

    def test_log_storage_failure_does_not_change_work(self):
        with patch.object(ContainerLogs, 'append', side_effect=OSError('disk full')):
            self.assertEqual(self.harness().run(lambda: (note('hello'), 42)[1]), 42)
        with self.logs.db() as db:
            self.assertEqual(db.execute('SELECT state FROM sessions').fetchone()[0], 'unavailable')

    def test_queue_persists_preparation_failure_and_retry_clears_only_current_receipt(self):
        wb = Workbench(create_mock_engine(self.root), None)
        def fail(_):
            with phase('Fetch frozen Git baseline'):
                raise OSError('fixture baseline unavailable')
        wb.operation_handlers['diagnostic-fixture'] = fail
        operation = wb.enqueue('diagnostic-fixture', {})
        wb.start()
        try:
            deadline = time.monotonic() + 5
            while True:
                current = wb.db.get_document('operations', operation['id'])
                if current['status'] == 'failed': break
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
        finally:
            wb.stop()
        self.assertEqual(current['diagnostic']['stage'], 'Fetch frozen Git baseline')
        self.assertFalse(current['diagnostic']['agentStarted'])
        key = current['diagnostic']['logSessionId']
        self.assertIn('fixture baseline unavailable', self.complete(key))
        wb.control_operation(operation['id'], 'retry')
        retry = wb.db.get_document('operations', operation['id'])
        self.assertNotIn('diagnostic', retry)
        self.assertNotIn('failure', retry)
        self.assertIn('fixture baseline unavailable', self.complete(key))

    def test_new_attempt_does_not_overwrite_old_failure(self):
        with log_scope(operationId='retry'):
            with self.assertRaises(ValueError):
                self.harness().run(lambda: (_ for _ in ()).throw(ValueError('first attempt')))
            self.harness().run(lambda: note('second attempt'))
        sessions = self.logs.list(operationId='retry')
        self.assertNotIn('failure', sessions[0])
        self.assertIn('first attempt', sessions[1]['failure']['summary'])

    def test_operation_failure_is_visible_in_experiment_snapshot(self):
        wb = Workbench(create_mock_engine(self.root), None)
        # Minimal experiment fixture does not need Docker or a real provider.
        model = ModelConfig('mock', 'deterministic', 'off', 100)
        spec = ExperimentSpec('Fixture', 'custom', 'fixture', ('none', 'developer-historical'), 1, ('one',), model, 'fixture', ResourcePolicy(), 1)
        experiment = wb.engine.create_experiment(spec)
        wb.db.set_experiment_status(experiment['id'], 'failed')
        wb.db.put_document('operations', 'op-failed', {'id': 'op-failed', 'kind': 'experiment', 'status': 'failed',
            'createdAt': '2026-09-09', 'updatedAt': '2026-09-09', 'payload': {'experimentId': experiment['id']},
            'failure': 'Image preparation failed', 'diagnostic': {'stage': 'Prepare test image'}})
        value = wb.snapshot(compact=True)['experiments'][0]
        self.assertEqual(value['failure'], 'Image preparation failed')
        self.assertEqual(value['diagnostic']['stage'], 'Prepare test image')

    def test_inventory_pagination_and_legacy_missing_head_are_explicit(self):
        for index in range(205):
            self.logs.finish(self.logs.create('preparation', operationId='long-operation'))
        first = self.logs.list(operationId='long-operation')
        second = self.logs.list(operationId='long-operation', before=first[-1]['sequence'])
        self.assertEqual(len(first), 200)
        self.assertEqual(len(second), 5)
        self.assertFalse({item['id'] for item in first} & {item['id'] for item in second})
        key = second[0]['id']
        with self.logs.db() as db:
            db.execute('UPDATE sessions SET start=100,end=100 WHERE id=?', (key,))
        self.assertTrue(self.logs.read(key, 0)['truncated'])


if __name__ == '__main__':
    unittest.main()

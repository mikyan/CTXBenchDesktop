import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from worker.ctxbench_worker.agent_args import normalize_agent_args, validate_pi_args, agent_args_hash, verify_agent_args_receipt
from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.jobs import run_spec_from_dict
from worker.ctxbench_worker.models import ModelConfig, ResourcePolicy, RunSpec
from worker.ctxbench_worker.runner import DockerRunner


class AgentArgsTests(unittest.TestCase):
    def test_literal_arguments_and_job_roundtrip(self):
        args = ['--config', '/opt/company agent/config.json', '', '中文', '$(echo literal); $HOME']
        self.assertEqual(normalize_agent_args(args), tuple(args))
        spec = RunSpec('run', 'solve', 'fixture', '/repo', '/output', 'prompt', ModelConfig('mock', 'm', 'off', 1), ResourcePolicy(), agent_args=tuple(args))
        self.assertEqual(run_spec_from_dict(asdict(spec)).agent_args, tuple(args))
        legacy = asdict(spec)
        legacy.pop('agent_args')
        self.assertEqual(run_spec_from_dict(legacy).agent_args, ())
        self.assertEqual(normalize_agent_args(None), ())

    def test_rejects_bad_shapes_controls_and_credentials_without_echo(self):
        for args in ('fixture-private', {'x': 'fixture-private'}, [False], ['a'] * 129, ['a' * 4097], ['a' * 4096] * 9,
                     ['\0'], ['\n'], ['\ud800'], ['--api-key=fixture-private'], ['--token', 'fixture-private']):
            with self.subTest(kind=type(args).__name__), self.assertRaises(ValueError) as error:
                normalize_agent_args(args)
            self.assertNotIn('fixture-private', str(error.exception))

    def test_pi_protects_benchmark_controls_and_requires_values(self):
        args = ['--tools', 'read, bash', '-xt', '工具', '--verbose', '-nt', '-nbt', '--no-themes', '-nc']
        self.assertEqual(validate_pi_args(args), tuple(args))
        for args in (['--tools'], ['--tools', '--model'], ['--mode=rpc'], ['--model', 'x'], ['-p', 'read AGENTS.md'],
                     ['--', 'prompt'], ['@AGENTS.md'], ['--system-prompt', 'x'], ['--append-system-prompt', 'x'],
                     ['--extension', 'x'], ['--skill', 'x'], ['--resume'], ['--api-key', 'private'], ['--unknown']):
            with self.subTest(args=args), self.assertRaises(ValueError):
                validate_pi_args(args)

    def test_receipt_is_order_and_boundary_sensitive(self):
        args = ['--tools', 'read, bash', '--verbose']
        self.assertNotEqual(agent_args_hash(args), agent_args_hash(list(reversed(args))))
        self.assertNotEqual(agent_args_hash(['a b']), agent_args_hash(['a', 'b']))
        verify_agent_args_receipt({'agentArgsProtocolVersion': 1, 'agentArgsHash': agent_args_hash(args)}, args)
        verify_agent_args_receipt({}, [])
        for metadata in ({}, {'agentArgsProtocolVersion': 1}, {'agentArgsProtocolVersion': 1, 'agentArgsHash': agent_args_hash([])}):
            with self.assertRaisesRegex(ValueError, 'did not confirm'):
                verify_agent_args_receipt(metadata, args)


class AgentArgsBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = create_mock_engine(self.root)
        self.client = TestClient(create_app(self.engine))  # No lifespan; no background runs.
        self.addCleanup(self.client.close)
        self.model = {'provider': 'mock', 'model': 'deterministic', 'thinking': 'off', 'maxTokens': 1000}
        self.dataset = self.client.post('/v1/datasets', json={'name': 'fixture', 'benchmark': 'custom', 'rows': [{
            'id': 'task', 'repository': 'https://git.internal.invalid/org/repo.git', 'baseCommit': 'a' * 40,
            'prompt': 'Public task', 'image': 'fixture', 'test': {'command': ['true']}}]}).json()['id']
        self.args = ['--config', '/opt/company agent/config.json', '中文', '$(echo literal)']

    def body(self):
        return {'name': 'Args', 'benchmark': 'custom', 'dataset': self.dataset, 'taskIds': ['task'], 'arms': ['none', 'skill-generated'],
                'repeats': 1, 'seed': 42, 'model': self.model, 'resources': {}, 'agentImage': 'fixture',
                'profiles': {role: self.model for role in ('solver', 'builder', 'constraintMiner', 'constraintJudge')}, 'agentArgs': self.args}

    def test_experiment_preflight_preparation_and_raw_run_preserve_arguments(self):
        self.assertEqual(self.client.post('/v1/preflight', json=self.body()).status_code, 200)
        response = self.client.post('/v1/experiments', json=self.body())
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['agentArgs'], self.args)
        self.assertEqual(self.engine.database.get_spec(response.json()['id']).agent_args, tuple(self.args))
        from worker.ctxbench_worker.workbench import Workbench
        for kind in ('context', 'constraints'):
            response = self.client.post('/v1/prepare/' + kind, json={'dataset': self.dataset, 'taskId': 'task', 'model': self.model, 'resources': {}, 'agentArgs': self.args})
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(response.json()['payload']['agentArgs'], self.args)
            self.assertEqual(Workbench._preparation_spec(response.json()['payload']).agent_args, tuple(self.args))
        response = self.client.post('/v1/runs', json={'runId': 'args-test', 'workspace': 'fixture', 'prompt': 'task', 'model': self.model, 'resources': {}, 'agentArgs': self.args})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()['payload']['agent_args'], self.args)

    def test_credentials_and_malformed_input_are_not_echoed_or_persisted(self):
        with patch.object(self.engine.runner, 'env_allowlist', {'FIXTURE_KEY'}, create=True), patch.dict(os.environ, {'FIXTURE_KEY': 'fixture-private'}):
            for args in (['--config', 'fixture-private'], ['--api-key', 'fixture-private'], {'bad': 'fixture-private'}, [123, 'fixture-private']):
                for path, body in [('/v1/experiments', self.body()), ('/v1/prepare/context', {'dataset': self.dataset, 'taskId': 'task', 'model': self.model, 'resources': {}}),
                                   ('/v1/runs', {'runId': 'rejected', 'workspace': 'fixture', 'prompt': 'task', 'model': self.model, 'resources': {}})]:
                    response = self.client.post(path, json={**body, 'agentArgs': args})
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertNotIn('fixture-private', response.text)
        self.assertFalse(self.engine.database.list_experiments())
        self.assertFalse(self.engine.database.list_documents('operations'))

    def test_old_pi_images_fail_before_request_persistence(self):
        runner = DockerRunner(self.root / 'repositories', self.root / 'runs', self.root / 'requests')
        with patch('docker.from_env') as factory:
            factory.return_value.images.get.return_value.labels = {}
            with self.assertRaisesRegex(ValueError, 'does not support startup arguments'):
                runner.validate_agent_args_image('old-image', ['--verbose'])
            factory.return_value.images.get.return_value.labels = {'io.ctxbench.agent-args': '1', 'io.ctxbench.agent-kind': 'pi'}
            with self.assertRaisesRegex(ValueError, 'Unsupported Pi'):
                runner.validate_agent_args_image('new-pi', ['--model', 'other'])
            runner.validate_agent_args_image('new-pi', ['--verbose'])
            factory.return_value.images.get.return_value.labels = {'io.ctxbench.agent-args': '1'}
            runner.validate_agent_args_image('custom', self.args)
            factory.return_value.containers.run.assert_not_called()

    def test_runner_passes_literal_argv_and_requires_adapter_confirmation(self):
        runner = DockerRunner(self.root / 'repositories', self.root / 'runs', self.root / 'requests')
        workspace = self.root / 'repositories' / 'fixture'
        workspace.mkdir()
        for confirm in (False, True):
            name = f'args-{confirm}'
            output = self.root / 'runs' / name
            spec = RunSpec(name, 'solve', 'fixture', str(workspace), str(output), 'unchanged prompt',
                           ModelConfig('mock', 'm', 'off', 1), ResourcePolicy(network='offline'), agent_args=tuple(self.args))
            with patch('docker.from_env') as factory, patch('worker.ctxbench_worker.runner._chown_tree'):
                client = factory.return_value
                client.images.get.return_value.labels = {'io.ctxbench.agent-args': '1'}
                container = client.containers.run.return_value
                container.logs.return_value = b'fixture'
                def finish(**kwargs):
                    request = json.loads((self.root / 'requests' / f'{name}.json').read_text(encoding='utf-8'))
                    self.assertEqual(request['agentArgs'], self.args)
                    self.assertEqual(request['prompt'], 'unchanged prompt')
                    metadata = {'agentArgsProtocolVersion': 1, 'agentArgsHash': agent_args_hash(self.args)} if confirm else {}
                    (output / 'result.json').write_text(json.dumps(metadata))
                    return {'StatusCode': 0}
                container.wait.side_effect = finish
                result = runner.run(spec)
                self.assertEqual(result.status, 'completed' if confirm else 'failed')
                self.assertNotIn('command', client.containers.run.call_args.kwargs)
                self.assertFalse((self.root / 'requests' / f'{name}.json').exists())


if __name__ == '__main__':
    unittest.main()

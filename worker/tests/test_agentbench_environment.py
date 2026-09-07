import json
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from worker.ctxbench_worker.datasets import TaskRecord
from worker.ctxbench_worker.models import ResourcePolicy
from worker.ctxbench_worker.runtime import Runtime

environment = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'docker/official-harness/agentbench_environment.py'))


class AgentbenchEnvironmentTests(unittest.TestCase):
    def test_legacy_digest_image_does_not_enable_the_new_harness_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = Runtime(root, SimpleNamespace(_mount_source=str))
            task = TaskRecord('case', 'https://github.com/org/repo.git', 'a' * 40, 'task', 'sha256:' + 'b' * 64, None, (), source='agentbench')
            commands = []
            def command(image, arguments, **kwargs):
                commands.append(arguments)
                kwargs['output'].mkdir(parents=True, exist_ok=True)
                (kwargs['output'] / 'summary.json').write_text('{"resolved":true}')
            runtime.command = command
            runtime.grade(task, root / 'dataset.json', root / 'patch', root / 'legacy', ResourcePolicy(), 'legacy-harness')
            runtime.grade(task, root / 'dataset.json', root / 'patch', root / 'new', ResourcePolicy(), 'new-harness', environment_image=task.image)
            self.assertNotIn('--environment-image', commands[0])
            self.assertEqual(commands[1][-2:], ['--environment-image', task.image])

    def test_setup_child_has_no_mounts_or_credentials_and_failed_setup_is_not_cached(self):
        class MissingImage(Exception):
            pass
        for status in (0, 1):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                source = SimpleNamespace(id='sha256:' + 'b' * 64, tag=Mock())
                container = Mock()
                container.wait.return_value = {'StatusCode': status}
                container.logs.return_value = b'CTXBENCH_SETUP_ENV={"PATH":"/testbed/.venv/bin:/bin","VIRTUAL_ENV":"/testbed/.venv"}\n'
                def commit(**kwargs):
                    return SimpleNamespace(id='sha256:' + 'c' * 64, labels=kwargs['conf']['Labels'], tag=Mock())
                container.commit.side_effect = commit
                client = Mock()
                client.images.get.side_effect = [source, MissingImage()]
                client.containers.run.return_value = container
                docker = SimpleNamespace(from_env=lambda: client, errors=SimpleNamespace(ImageNotFound=MissingImage))
                with patch.dict('sys.modules', docker=docker), patch.dict('os.environ', {'OPENAI_API_KEY': 'PRIVATE_CREDENTIAL'}):
                    row = {**self.row(), 'docker_image': 'fixture:1'}
                    if status:
                        with self.assertRaisesRegex(RuntimeError, 'no agent was started'):
                            environment['prepare_environment'](row, Path(directory))
                        container.commit.assert_not_called()
                        self.assertFalse((Path(directory) / 'environment.json').exists())
                    else:
                        result = environment['prepare_environment'](row, Path(directory))
                        self.assertEqual(result['imageId'], 'sha256:' + 'c' * 64)
                        self.assertNotIn('PRIVATE_', json.dumps(result))
                kwargs = client.containers.run.call_args.kwargs
                self.assertEqual(kwargs['network'], 'bridge')
                self.assertNotIn('volumes', kwargs)
                self.assertNotIn('environment', kwargs)
                self.assertNotIn('PRIVATE_', str(client.containers.run.call_args))
                container.remove.assert_called_once_with(force=True)

    def test_dependency_compatibility_is_explicit_and_baseline_scoped(self):
        row = {**self.row(), 'base_repo': 'qodo-ai/pr-agent', 'base_sha': '7b4c50c717df393a392aec3b7f4146f5fb701503'}
        identity = environment['setup_identity'](row, 'sha256:' + 'b' * 64)
        self.assertEqual(identity['dependencyConstraints'], ['openai==1.78.1'])
        self.assertIn('export PIP_CONSTRAINT=', environment['setup_script'](identity))
        self.assertEqual(environment['setup_identity']({**row, 'base_sha': 'a' * 40}, 'image')['dependencyConstraints'], [])

    def row(self):
        return {'base_repo': 'org/repo', 'base_sha': 'a' * 40, 'setup_commands': ['python -m venv .venv', 'source .venv/bin/activate', 'pip install pytest'],
                'clean_pr_patch': 'PRIVATE_GOLD', 'test_file_contents': ['PRIVATE_TEST'], 'problem_description': 'PRIVATE_TASK'}

    def test_setup_identity_is_task_blind_and_script_preserves_activation(self):
        identity = environment['setup_identity'](self.row(), 'sha256:' + 'b' * 64)
        script = environment['setup_script'](identity)
        self.assertTrue(script.startswith('set -e\n'))
        self.assertIn('source .venv/bin/activate\npip install pytest', script)
        self.assertNotIn('PRIVATE_', json.dumps(identity) + script)
        changed = {**self.row(), 'clean_pr_patch': 'OTHER_ANSWER', 'problem_description': 'OTHER_TASK'}
        self.assertEqual(identity, environment['setup_identity'](changed, 'sha256:' + 'b' * 64))
        with self.assertRaises(ValueError):
            environment['setup_identity']({**changed, 'base_sha': 'main; echo bad'}, 'image')

    def test_only_explicit_environment_state_can_be_committed(self):
        parse = environment['parse_environment']
        self.assertEqual(parse('log\nCTXBENCH_SETUP_ENV={"PATH":"/testbed/.venv/bin:/usr/bin","VIRTUAL_ENV":"/testbed/.venv"}\n')['VIRTUAL_ENV'], '/testbed/.venv')
        for log in ('', 'CTXBENCH_SETUP_ENV={}', 'CTXBENCH_SETUP_ENV={"PATH":"/bin","API_KEY":"secret"}',
                    'CTXBENCH_SETUP_ENV={"PATH":"a\\nb"}', 'CTXBENCH_SETUP_ENV={"PATH":42}'):
            with self.subTest(log=log), self.assertRaises((ValueError, RuntimeError)):
                parse(log)

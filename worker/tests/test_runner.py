import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from worker.ctxbench_worker.runner import DockerRunner, selected_environment
from worker.ctxbench_worker.models import ModelConfig, ResourcePolicy, RunSpec


class RunnerSecurityTests(unittest.TestCase):
    def test_old_images_cannot_silently_ignore_a_workflow(self):
        with tempfile.TemporaryDirectory() as directory, patch('docker.from_env') as factory:
            root = Path(directory)
            runner = DockerRunner(root / 'repositories', root / 'runs', root / 'requests')
            factory.return_value.images.get.return_value.labels = {}
            with self.assertRaisesRegex(ValueError, 'does not support workflow'):
                runner.validate_workflow_image('legacy-image')
            factory.return_value.containers.run.assert_not_called()
            factory.return_value.close.assert_called_once()

    def test_cancel_reaps_exited_containers_after_worker_crash(self) -> None:
        import docker
        with tempfile.TemporaryDirectory() as directory, patch('docker.from_env') as factory:
            root = Path(directory)
            runner = DockerRunner(root / 'repositories', root / 'runs', root / 'requests')
            container = MagicMock()
            factory.return_value.containers.list.return_value = [container]
            runner.cancel('isolated-run')
            factory.return_value.containers.list.assert_called_once_with(all=True, filters={'label': 'io.ctxbench.run=isolated-run'})
            container.remove.assert_called_once_with(force=True)
            container.remove.side_effect = docker.errors.NotFound('already removed')
            runner.cancel('isolated-run')
            self.assertEqual(factory.return_value.close.call_count, 2)

    def test_only_allowlisted_names_are_copied(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "UNSAFE": "nope"}, clear=False):
            self.assertEqual(
                selected_environment(("OPENAI_API_KEY",), frozenset({"OPENAI_API_KEY"})),
                {"OPENAI_API_KEY": "secret"},
            )
            with self.assertRaises(ValueError):
                selected_environment(("UNSAFE",), frozenset({"OPENAI_API_KEY"}))

    def test_multiple_variables_reach_container_and_are_redacted_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch('docker.from_env') as factory, patch('worker.ctxbench_worker.runner._chown_tree'):
            root = Path(directory)
            variables = {'INTERNAL_AGENT_KEY': 'fixture-key-not-real', 'INTERNAL_AGENT_URL': 'https://provider.invalid/v1'}
            runner = DockerRunner(root / 'repositories', root / 'runs', root / 'requests', env_allowlist=frozenset(variables))
            workspace = root / 'repositories' / 'fixture'
            workspace.mkdir()
            container = factory.return_value.containers.run.return_value
            container.wait.return_value = {'StatusCode': 0}
            container.logs.return_value = ' '.join(variables.values()).encode()
            spec = RunSpec('multi-env', 'solve', 'fixture-image', str(workspace), str(root / 'runs' / 'multi-env'),
                           'Fixture prompt', ModelConfig('mock', 'deterministic', 'off', 10),
                           ResourcePolicy(network='offline'), env_names=tuple(variables))
            with patch.dict(os.environ, {**variables, 'UNSELECTED_FIXTURE': 'must-not-leak'}, clear=False):
                result = runner.run(spec)
            self.assertEqual(result.status, 'completed')
            passed = factory.return_value.containers.run.call_args.kwargs['environment']
            self.assertEqual(passed, variables)
            self.assertNotIn('UNSELECTED_FIXTURE', passed)
            logs = (Path(result.output_dir) / 'container.log').read_text()
            self.assertEqual(logs, '[REDACTED] [REDACTED]')
            self.assertFalse((root / 'requests' / 'multi-env.json').exists())

    def test_worker_paths_are_translated_to_docker_host_bind_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = DockerRunner(
                repositories_root=root / "repositories",
                artifacts_root=root / "runs",
                request_root=root / "requests",
                worker_data_root=root,
                host_data_root="/var/lib/ctxbench",
            )
            workspace = root / "repositories" / "task"
            workspace.mkdir()
            self.assertEqual(
                runner._mount_source(workspace),
                "/var/lib/ctxbench/repositories/task",
            )

    def test_host_translation_rejects_sources_outside_shared_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            runner = DockerRunner(
                repositories_root=root / "repositories",
                artifacts_root=root / "runs",
                request_root=root / "requests",
                worker_data_root=root,
                host_data_root="/var/lib/ctxbench",
            )
            with self.assertRaises(ValueError):
                runner._mount_source(Path(outside))


if __name__ == "__main__":
    unittest.main()

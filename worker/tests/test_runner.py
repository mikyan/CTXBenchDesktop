import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.ctxbench_worker.runner import DockerRunner, selected_environment


class RunnerSecurityTests(unittest.TestCase):
    def test_only_allowlisted_names_are_copied(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "UNSAFE": "nope"}, clear=False):
            self.assertEqual(
                selected_environment(("OPENAI_API_KEY",), frozenset({"OPENAI_API_KEY"})),
                {"OPENAI_API_KEY": "secret"},
            )
            with self.assertRaises(ValueError):
                selected_environment(("UNSAFE",), frozenset({"OPENAI_API_KEY"}))

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

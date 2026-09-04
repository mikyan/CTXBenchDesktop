import unittest

from worker.ctxbench_worker.datasets import custom_task


class DatasetTests(unittest.TestCase):
    def test_solver_payload_excludes_evaluator_only_material(self) -> None:
        task = custom_task(
            {
                "id": "task-1",
                "repository": "https://github.com/org/repo.git",
                "baseCommit": "abc123",
                "prompt": "Fix the behavior.",
                "image": "repo:task-1",
                "test": {"command": ["pytest", "-q"], "hiddenPatch": "secret tests"},
                "goldPatch": "gold",
            }
        )
        payload = task.solver_payload()
        self.assertEqual(set(payload), {"id", "repository", "baseCommit", "prompt"})
        self.assertNotIn("secret tests", str(payload))
        self.assertNotIn("gold", str(payload))

    def test_custom_task_requires_explicit_environment(self) -> None:
        with self.assertRaisesRegex(ValueError, "image or an explicit build recipe"):
            custom_task(
                {
                    "id": "task-1",
                    "repository": "org/repo",
                    "baseCommit": "abc123",
                    "prompt": "Fix it",
                    "test": {"command": ["pytest"]},
                }
            )


if __name__ == "__main__":
    unittest.main()

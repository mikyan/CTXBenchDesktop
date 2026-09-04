import tempfile
import unittest
from pathlib import Path

from worker.ctxbench_worker.workspace import prepare_context


class WorkspaceTests(unittest.TestCase):
    def test_generated_arm_removes_historical_context_then_overlays_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "repo"
            artifact = root / "artifact"
            workspace.mkdir()
            artifact.mkdir()
            (workspace / "AGENTS.md").write_text("historical", encoding="utf-8")
            (workspace / "source.py").write_text("unchanged", encoding="utf-8")
            (artifact / ".ctx").mkdir()
            (artifact / "AGENTS.md").write_text("generated", encoding="utf-8")
            (artifact / ".ctx" / "architecture.md").write_text("map", encoding="utf-8")

            changes = prepare_context(workspace, "skill-generated", artifact)
            self.assertEqual((workspace / "AGENTS.md").read_text(encoding="utf-8"), "generated")
            self.assertEqual((workspace / "source.py").read_text(encoding="utf-8"), "unchanged")
            self.assertEqual([change.operation for change in changes], ["remove", "overlay", "overlay"])

    def test_none_removes_nested_context_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "package").mkdir()
            (workspace / "package" / "AGENTS.md").write_text("nested", encoding="utf-8")
            prepare_context(workspace, "none")
            self.assertFalse((workspace / "package" / "AGENTS.md").exists())

    def test_artifact_cannot_modify_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, artifact = root / "repo", root / "artifact"
            workspace.mkdir()
            (artifact / "src").mkdir(parents=True)
            (artifact / "src" / "core.py").write_text("bad", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-context"):
                prepare_context(workspace, "manual", artifact)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from worker.ctxbench_worker.artifacts import ArtifactStore, ContextIdentity, is_context_owned
from worker.ctxbench_worker.models import ModelConfig


class ArtifactTests(unittest.TestCase):
    def identity(self) -> ContextIdentity:
        return ContextIdentity(
            repository="org/repo",
            commit="abc123",
            capability="tree-only",
            skill_version="1.0.0",
            generation_prompt_hash="prompt-sha",
            builder=ModelConfig("mock", "builder", "high", 8192),
        )

    def test_identity_is_stable(self) -> None:
        self.assertEqual(self.identity().key(), self.identity().key())
        self.assertEqual(len(self.identity().key()), 64)

    def test_only_context_owned_files_can_be_published(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            target = store.publish(
                self.identity(),
                {"AGENTS.md": b"context", ".ctx/architecture.md": b"architecture"},
                {"targetTaskSeen": False},
            )
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(set(manifest["files"]), {"AGENTS.md", ".ctx/architecture.md"})
            self.assertTrue(store.contains(self.identity().key()))

            with self.assertRaisesRegex(ValueError, "non-context files"):
                store.publish(
                    ContextIdentity(**{**self.identity().__dict__, "commit": "different"}),
                    {"src/core.py": b"confound"},
                    {},
                )

    def test_paths_cannot_escape_artifact_root(self) -> None:
        self.assertFalse(is_context_owned("docs/guide.md"))
        with self.assertRaises(ValueError):
            is_context_owned("../AGENTS.md")


if __name__ == "__main__":
    unittest.main()

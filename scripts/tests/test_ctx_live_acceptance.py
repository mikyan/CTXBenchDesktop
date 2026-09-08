import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


module_spec = importlib.util.spec_from_file_location(
    "ctx_live_acceptance", Path(__file__).resolve().parents[1] / "ctx-live-acceptance.py")
acceptance = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(acceptance)


@dataclass(frozen=True)
class ControlTask:
    image: str = "unpinned"
    gold_patch: str = "synthetic evaluator-only reference"


class GraderControlTests(unittest.TestCase):
    def run_controls(self, verdict):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            calls = []

            def grade(task, dataset, patch, folder, resources, harness, **options):
                self.assertTrue(folder.resolve().is_relative_to(output.resolve()))
                self.assertEqual(resources.network, "offline")
                self.assertEqual(harness, "sha256:harness")
                self.assertEqual(task.image, "sha256:environment")
                self.assertEqual(options["environment_image"], task.image)
                content = patch.read_text(encoding="utf-8")
                calls.append(content)
                return {"resolved": verdict(content)}

            # There is deliberately no Agent runner or credential interface.
            wb = SimpleNamespace(
                catalog=SimpleNamespace(verify=lambda _: {"path": temporary}, task=lambda *_: ControlTask()),
                runtime=SimpleNamespace(grade=grade))
            spec = SimpleNamespace(dataset="frozen-dataset", task_ids=("normal", "../../unsafe/task"))
            prepared = {"graderImages": {task: "sha256:environment" for task in spec.task_ids}, "harnessImage": "sha256:harness"}
            result = acceptance.grade_controls(wb, spec, prepared, output, lambda *_, **__: None)
            return result, calls

    def test_offline_controls_use_pinned_images_and_safe_paths_without_an_agent(self):
        result, calls = self.run_controls(bool)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result, {task: {"empty": False, "gold": True} for task in ("normal", "../../unsafe/task")})

    def test_accepting_empty_patch_fails_the_control(self):
        with self.assertRaisesRegex(AssertionError, "empty control failed"):
            self.run_controls(lambda _: True)

    def test_rejecting_reference_patch_fails_the_control(self):
        with self.assertRaisesRegex(AssertionError, "gold control failed"):
            self.run_controls(lambda _: False)


if __name__ == "__main__":
    unittest.main()

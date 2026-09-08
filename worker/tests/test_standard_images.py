import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.intranet import IntranetWorkbench
from worker.ctxbench_worker.standard_images import DockerImages, StandardImages, project_image, swe_image
from worker.ctxbench_worker.workbench import Interrupted, Workbench


def rows():
    return [{"instance_id": f"repo-{i}", "base_repo": "org/repo", "base_sha": "a" * 40,
             "docker_image": "org/project:v1", "problem_description": "TASK_PROMPT_NOT_FOR_INSTALLER",
             "clean_pr_patch": "EVALUATOR_GOLD", "test_patch": "HIDDEN_TEST", "setup_commands": ["DO_NOT_EXECUTE"]}
            for i in range(3)]


class Store:
    def __init__(self):
        self.images = {}; self.pulls = []; self.fail = False; self.after_event = lambda: None
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def inspect(self, ref):
        return {"installed": ref in self.images, "compatible": self.images.get(ref) != "arm64",
                "imageId": self.images.get(ref), "sizeBytes": 123 if ref in self.images else None}
    def pull(self, ref, check, progress):
        self.pulls.append(ref)
        progress("layer Downloading 5kB/10kB")
        self.after_event(); check()
        if self.fail: raise ValueError("REGISTRY_UNAVAILABLE")
        self.images[ref] = "sha256:" + "b" * 64


class StandardImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_mock_engine(Path(self.tmp.name))
        self.wb = Workbench(self.engine, None)
        self.op = IntranetWorkbench(self.wb)
        self.store = Store()
        self.service = StandardImages(self.op, lambda: self.store)
        self.op.standard_images = self.service
        self.dataset = self.wb.catalog.register("CTX fixture", "ctxbench", rows())["id"]
        self.payload = {"dataset": self.dataset, "taskIds": ["repo-0", "repo-1"], "confirmed": True}

    def tearDown(self): self.tmp.cleanup()

    def test_plan_is_read_only_deduplicated_and_evaluator_blind(self):
        plan = self.service.plan(self.dataset)
        self.assertEqual(len(plan["images"]), 1)
        self.assertEqual(plan["images"][0]["taskIds"], ["repo-0", "repo-1", "repo-2"])
        for sentinel in ("EVALUATOR_GOLD", "HIDDEN_TEST", "TASK_PROMPT_NOT_FOR_INSTALLER", "DO_NOT_EXECUTE"):
            self.assertNotIn(sentinel, json.dumps(plan))
        self.assertEqual(self.store.pulls, [])
        self.assertEqual(self.engine.database.list_documents("operations"), [])

    def test_install_uses_one_image_then_reuses_cache_without_model(self):
        operation = self.op.enqueue("standard-images", self.payload)
        self.wb.runtime.checkout = Mock(side_effect=AssertionError("no clone"))
        self.wb._agent = Mock(side_effect=AssertionError("no Agent"))
        result = self.op.execute(operation)
        self.assertEqual(self.store.pulls, ["org/project:v1"])
        self.assertEqual(result["modelCalls"], 0)
        self.assertEqual(result["taskCount"], 2)
        self.assertFalse(result["images"][0]["cached"])
        self.assertEqual(self.op.status(operation["id"])["progress"]["percent"], 100)
        result = self.service.install(operation)
        self.assertTrue(result["images"][0]["cached"])
        self.assertEqual(len(self.store.pulls), 1)
        self.assertFalse(list((self.op.root / "jobs").iterdir()))

    def test_selection_consent_custom_and_duplicate_jobs_are_rejected(self):
        for changes in [{"taskIds": []}, {"taskIds": ["missing"]}, {"taskIds": ["repo-0", "repo-0"]},
                        {"taskIds": "repo-0"}, {"confirmed": False}, {"confirmed": 1}, {"images": ["arbitrary/image"]}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.op.enqueue("standard-images", {**self.payload, **changes})
        self.op.enqueue("standard-images", self.payload)
        with self.assertRaisesRegex(ValueError, "already"):
            self.op.enqueue("standard-images", self.payload)

    def test_frozen_dataset_tampering_stops_install_before_pull(self):
        (self.wb.root / "datasets" / f"{self.dataset}.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.service.plan(self.dataset)
        self.assertEqual(self.store.pulls, [])

    def test_swe_names_include_solver_variant_and_official_grader(self):
        record = self.wb.catalog.register("SWE", "swebench", [{"instance_id": "matplotlib__matplotlib-1", "repo": "matplotlib/matplotlib",
                    "base_commit": "a" * 40, "problem_statement": "Fix"}])
        plan = self.service.plan(record["id"])
        self.assertEqual([image["reference"] for image in plan["images"]], [swe_image("matplotlib__matplotlib-1", solver=True), swe_image("matplotlib__matplotlib-1")])
        task = self.wb.catalog.task(record["id"], "matplotlib__matplotlib-1")
        self.assertEqual(project_image(task), plan["images"][0]["reference"])
        self.assertEqual(project_image(replace(task, image="company/project:v2")), "company/project:v2")

    def test_custom_dataset_is_not_mistaken_for_an_official_download(self):
        record = self.wb.catalog.register("Custom", "custom", [{"id": "custom", "repository": "https://git.example/org/repo", "baseCommit": "a" * 40,
                        "prompt": "Fix", "image": "org/tests:v1", "test": {"command": ["pytest"]}}])
        with self.assertRaisesRegex(ValueError, "CTXBench or SWE-bench"):
            self.service.plan(record["id"])
        self.assertEqual(self.store.pulls, [])

    def test_company_check_is_metadata_only_profile_scoped_and_keeps_missing_tasks(self):
        from worker.tests.test_intranet import profile
        record = self.op.profiles.save({**profile(), 'offline': False,
            'imageMappings': [{'source': 'org/project:', 'target': 'registry.example/ctx/project:'}]})
        self.store.availability = Mock(return_value='not-found')
        payload = {**self.payload, 'profileId': record['id']}
        operation = self.op.enqueue('image-check', payload)
        result = self.op.execute(operation)
        self.assertEqual(result['modelCalls'], 0)
        self.store.availability.assert_called_once_with('registry.example/ctx/project:v1')
        self.assertEqual(self.store.pulls, [])
        with self.wb.runtime.using_environment(record):
            plan = self.service.plan(self.dataset)
        self.assertEqual(len(plan['tasks']), 3)
        self.assertEqual(plan['images'][0]['reference'], 'registry.example/ctx/project:v1')
        self.assertEqual(plan['images'][0]['remote']['status'], 'not-found')
        self.assertEqual(plan['images'][0]['originals'], ['org/project:v1'])
        self.assertEqual(self.service.plan(self.dataset)['images'][0]['remote']['status'], 'unchecked')
        # Completing the metadata check does not change the original dataset.
        self.assertEqual(self.wb.catalog.task(self.dataset, 'repo-0').image, 'org/project:v1')

    def test_company_installer_uses_frozen_profile_and_no_unmapped_pull(self):
        from worker.tests.test_intranet import profile
        saved = self.op.profiles.save({**profile(), 'offline': False,
            'imageMappings': [{'source': 'org/project:', 'target': 'registry.example/ctx/project:'}]})
        operation = self.op.enqueue('standard-images', {**self.payload, 'profileId': saved['id']})
        self.op.execute(operation)
        self.assertEqual(self.store.pulls, ['registry.example/ctx/project:v1'])
        self.assertEqual(operation['payload']['environment'], saved)
        self.store.pulls.clear()
        with self.wb.runtime.using_environment({'imageMappings': [{'source': 'other/', 'target': 'registry.example/other/'}]}):
            with self.assertRaisesRegex(ValueError, 'No permitted registry mapping'):
                self.service.install(operation)
        self.assertEqual(self.store.pulls, [])

    def test_company_check_can_cancel_before_next_registry_call(self):
        self.store.availability = Mock(side_effect=lambda ref: self.wb.control_operation(operation['id'], 'cancel'))
        operation = self.op.enqueue('image-check', self.payload)
        self.wb._scope.operation_id = operation['id']
        with self.assertRaises(Interrupted):
            self.op.execute(operation)
        self.assertFalse(self.wb.db.list_documents('imageAvailability'))

    def test_wrong_architecture_does_not_overwrite_local_image(self):
        self.store.images["org/project:v1"] = "arm64"
        operation = self.op.enqueue("standard-images", self.payload)
        with self.assertRaisesRegex(ValueError, "wrong platform"):
            self.service.install(operation)
        self.assertEqual(self.store.pulls, [])

    def test_failure_and_cancellation_do_not_report_success(self):
        operation = self.op.enqueue("standard-images", self.payload)
        self.store.fail = True
        with self.assertRaisesRegex(ValueError, "REGISTRY_UNAVAILABLE"):
            self.service.install(operation)
        self.assertLess(self.op.status(operation["id"])["progress"]["percent"], 100)
        self.store.fail = False
        self.wb._scope.operation_id = operation["id"]
        self.store.after_event = lambda: self.wb.control_operation(operation["id"], "cancel")
        with self.assertRaises(Interrupted):
            self.service.install(operation)
        self.assertEqual(self.store.images, {})
        self.assertEqual(self.wb.db.get_document("operations", operation["id"])["status"], "cancelled")

    def test_cancel_kills_sdk_process_even_when_no_pull_event_arrives(self):
        process = Mock()
        process.stdout = iter([])
        process.poll.return_value = None
        process.wait.return_value = 0
        # A stopped reader is sufficient: the controller must not depend on an event.
        with patch.dict("os.environ", {"TEAM_API_KEY": "private-fixture"}), patch("subprocess.Popen", return_value=process) as start, patch("threading.Thread"):
            with self.assertRaises(Interrupted):
                DockerImages().pull("org/project:v1", Mock(side_effect=Interrupted("cancelled")), Mock())
        self.assertNotIn("TEAM_API_KEY", start.call_args.kwargs["env"])
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=3)

    def test_routes_only_expose_image_metadata_and_old_worker_does_not_fake_readiness(self):
        with TestClient(create_app(self.engine)) as client, patch("worker.ctxbench_worker.standard_images.DockerImages.__enter__", return_value=self.store), patch("worker.ctxbench_worker.standard_images.DockerImages.__exit__"):
            response = client.get(f"/v1/datasets/{self.dataset}/project-images")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn("EVALUATOR_GOLD", response.text)
            self.assertEqual(response.json()["images"][0]["installed"], False)
            bad = client.post("/v1/intranet/operations/standard-images", json={**self.payload, "confirmed": False})
            self.assertEqual(bad.status_code, 422)

    def test_swe_harness_pin_matches_legacy_snapshot_and_preserves_images(self):
        root = Path(__file__).resolve().parents[2]
        dockerfile = (root / "docker/official-harness/Dockerfile").read_text()
        self.assertIn("SWEBENCH_COMMIT=726c5461e2ef52d83cf1ea2107870a8bb3328d57", dockerfile)
        source = (root / "docker/official-harness/harness.py").read_text()
        self.assertIn('namespace=namespace', source)
        self.assertIn('cache_level="instance"', source)

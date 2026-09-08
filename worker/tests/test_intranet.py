import base64
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.catalog import fingerprint
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.environments import validate_profile, public_image_config
from worker.ctxbench_worker.intranet import IntranetWorkbench
from worker.ctxbench_worker.portable import PortableResources, source_key
from worker.ctxbench_worker.runner import DockerRunner
from worker.ctxbench_worker.workbench import Workbench


def profile():
    return {"format": "ctxbench-company-profile", "version": 1, "name": "Internal", "agentImage": "company/agent:v1",
            "harnessImage": "company/harness:v1", "provider": "private", "model": "model-v1", "envNames": ["TEAM_API_KEY", "TEAM_BASE_URL"],
            "agentArgs": ["--config", "/opt/team/settings.json"], "offline": True,
            "gitMirrors": [{"repository": "https://git.example/team/repo.git", "mirror": "https://gitee.example/team/repo.git"}],
            "providerDomains": ["api.company.example"]}


def row():
    return {"id": "task-1", "repository": "https://git.example/team/repo.git", "baseCommit": "a" * 40,
            "prompt": "Repair addition.", "image": "team/tests:v1", "test": {"command": ["python", "-m", "unittest"], "hiddenPatch": "HIDDEN_FIXTURE"}, "goldPatch": "PRIVATE_REFERENCE"}


class IntranetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = create_mock_engine(self.root)
        self.wb = Workbench(self.engine, None)
        self.service = IntranetWorkbench(self.wb)
        self.client = TestClient(create_app(self.engine))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_profiles_are_content_addressed_and_do_not_apply_globally(self):
        first = self.service.profiles.save(profile())
        second = self.service.profiles.save({**profile(), "model": "model-v2"})
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.service.profiles.get(first["id"])["document"]["model"], "model-v1")
        self.assertEqual(self.wb.runtime.environment, {})
        self.assertEqual(self.service.profiles.save(profile()), first)

    def test_profiles_validate_secret_free_urls_names_and_domain_rules(self):
        bad = [
            {**profile(), "envNames": [{"name": "KEY", "value": "private"}]},
            {**profile(), "envNames": ["TEAM_API_KEY", "TEAM_API_KEY"]},
            {**profile(), "apiKey": "private"},
            {**profile(), "providerDomains": ["api.example\nhttp_access allow all"]},
            {**profile(), "gitMirrors": [{"repository": "https://example/repo", "mirror": "https://user:pass@example/repo"}]},
            {**profile(), "gitMirrors": [{"repository": "https://example/repo", "mirror": "relative/path"}]},
            {**profile(), "offline": "true"},
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_profile(value)
        validate_profile({**profile(), "gitMirrors": [{"repository": "https://example/repo", "mirror": "ssh://git@internal/repo"}]})

    def test_profile_tampering_is_rejected(self):
        saved = self.service.profiles.save(profile())
        saved["document"]["model"] = "tampered"
        self.engine.database.put_document("companyProfiles", saved["id"], saved)
        with self.assertRaisesRegex(ValueError, "modified"):
            self.service.profiles.get(saved["id"])

    def test_experiment_freezes_profile_and_does_not_follow_new_versions(self):
        dataset = self.wb.catalog.register("set", "custom", [row()])
        saved = self.service.profiles.save({**profile(), "agentArgs": []})
        model = {"provider": "mock", "model": "explicit-model", "thinking": "off", "maxTokens": 100}
        request = {"name": "Frozen company settings", "benchmark": "custom", "dataset": dataset["id"], "arms": ["none", "skill-generated"],
                   "repeats": 1, "taskIds": [row()["id"]], "model": model, "profiles": {role: model for role in ["builder", "solver", "constraintMiner", "constraintJudge"]},
                   "agentImage": "mock-image", "resources": {"cpus": 1, "memoryGb": 1, "timeoutMinutes": 1, "network": "offline"},
                   "seed": 1, "companyProfileId": saved["id"]}
        response = self.client.post("/v1/experiments", json=request)
        self.assertEqual(response.status_code, 201, response.text)
        key = response.json()["id"]
        self.service.profiles.save({**profile(), "model": "new-company-default"})
        spec = self.db_spec(key)
        self.assertEqual(spec.company_environment["id"], saved["id"])
        self.assertEqual(spec.company_environment["document"]["model"], "model-v1")
        self.assertEqual(spec.model.model, "explicit-model")

    def db_spec(self, key):
        return self.engine.database.get_spec(key)

    def test_reregistering_same_dataset_does_not_rename_or_change_frozen_metadata(self):
        first = self.wb.catalog.register("Original", "custom", [row()])
        self.assertEqual(self.wb.catalog.register("Another name", "custom", [row()]), first)
        changed = self.wb.catalog.register("New version", "custom", [{**row(), "prompt": "Changed requirement"}])
        self.assertNotEqual(changed["id"], first["id"])

    def test_build_files_are_scanned_after_decoding_before_queue_persistence(self):
        token = "FAKE_ONLY_TEST_CREDENTIAL"
        self.wb.redact = lambda text: text.replace(token, "[REDACTED]")
        recipe = {"name": "Test", "baseImage": "team/base:v1", "dockerfile": "COPY data.bin /opt/data.bin", "network": "none",
                  "files": [{"path": "data.bin", "base64": base64.b64encode(token.encode()).decode()}]}
        with self.assertRaises(ValueError):
            self.service.enqueue("image-build", recipe)
        self.assertEqual(self.engine.database.list_documents("operations"), [])
        recipe["files"][0]["base64"] = base64.b64encode(b"\0\x01binary-installer\0").decode()
        self.service.enqueue("image-build", recipe)

    def test_digest_receipt_resolves_without_pull_after_portable_import(self):
        import docker
        reference = "internal.example/team/image@sha256:" + "d" * 64
        key = "sha256:" + "e" * 64
        aliases = self.root / "intranet" / "image-references"
        aliases.mkdir()
        (aliases / (hashlib.sha256(reference.encode()).hexdigest() + ".json")).write_text(json.dumps({"reference": reference, "id": key}))
        image = Mock(id=key)
        client = Mock()
        client.images.get.side_effect = [docker.errors.ImageNotFound("missing registry reference"), image]
        with patch("docker.from_env", return_value=client), self.wb.runtime.using_environment({"offline": True}):
            self.assertEqual(self.wb.runtime.resolve_image(reference), key)
        client.images.pull.assert_not_called()

    def test_proxy_export_does_not_touch_active_proxy(self):
        saved = self.service.profiles.save(profile())
        config = self.service.profiles.proxy_config(saved["id"])
        self.assertIn("dstdomain api.company.example", config)
        self.assertIn("http_access deny all", config)
        self.assertNotIn("http_access allow all", config)

    def test_short_image_credentials_are_rejected(self):
        for env in ["API_KEY=x", "TEAM_TOKEN=123", "AWS_SECRET_ACCESS_KEY=x", "PASSWORD=x"]:
            with self.assertRaises(ValueError):
                public_image_config({"Env": [env]}, lambda text: text)
        public_image_config({"Env": ["PATH=/bin", "API_KEY="]}, lambda text: text)

    def test_runtime_environment_scope_restores_and_does_not_pull_offline(self):
        import docker
        client = Mock()
        client.images.get.side_effect = docker.errors.ImageNotFound("missing")
        with patch("docker.from_env", return_value=client):
            with self.wb.runtime.using_environment({"document": profile()}):
                with self.assertRaisesRegex(ValueError, "Offline preparation"):
                    self.wb.runtime.resolve_image("team/missing:v1")
                with self.wb.runtime.using_environment({"offline": False}):
                    self.assertFalse(self.wb.runtime.environment["offline"])
                self.assertTrue(self.wb.runtime.environment["offline"])
            self.assertEqual(self.wb.runtime.environment, {})
        client.images.pull.assert_not_called()

    def test_mirror_fetch_keeps_original_task_identity_and_exact_commit(self):
        task = self.wb.catalog.validate("dataset", "custom", [row()])[0]
        calls = []
        def fake_git(source, *args, **kwargs):
            calls.append(args)
            if args[:2] == ("cat-file", "-e"):
                raise RuntimeError("not present")
            if args[:2] == ("cat-file", "-p"):
                return b"tree aaaa\ncommitter Test <test@example.invalid> 1767225600 +0000\n\nFrozen baseline"
            return b"2026-01-01T00:00:00Z"
        with patch("worker.ctxbench_worker.runtime.git", side_effect=fake_git), self.wb.runtime.using_environment({**profile(), "offline": False}):
            self.wb.runtime.baseline(task)
        self.assertIn(("fetch", "--depth=1", "https://gitee.example/team/repo.git", "a" * 40), calls)
        self.assertEqual(task.repository, row()["repository"])

    def test_draft_versions_keep_evaluator_data_out_of_dashboard(self):
        draft = {"format": "ctxbench-dataset-draft", "version": 1, "name": "Draft", "tasks": [{"goldPatch": "PRIVATE_REFERENCE"}]}
        result = self.client.post("/v1/intranet/drafts", json=draft)
        self.assertEqual(result.status_code, 200)
        key = result.json()["id"]
        self.assertEqual(self.client.get(f"/v1/intranet/drafts/{key}").json()["document"], draft)
        self.assertNotIn("PRIVATE_REFERENCE", self.client.get("/v1/snapshot").text)
        self.assertNotIn("PRIVATE_REFERENCE", self.client.get("/v1/intranet").text)

    def test_recipe_rejects_unsafe_context_and_unpinned_from(self):
        recipe = {"name": "Test", "baseImage": "team/base:v1", "dockerfile": "RUN true", "network": "none", "files": []}
        for instruction in ["FROM team/other", "ARG TOKEN", "# syntax=remote/frontend\nRUN true"]:
            with self.assertRaises(ValueError):
                self.service.recipe({**recipe, "dockerfile": instruction})
        for name in ["../escape", "/absolute", ".env", "Dockerfile", "auth.json", "files/../../escape"]:
            with self.assertRaises(ValueError):
                self.service.recipe({**recipe, "files": [{"path": name, "base64": base64.b64encode(b"fixture").decode()}]})
        self.assertEqual(self.service.recipe(recipe), recipe)

    def test_probe_requires_reference_and_does_not_call_mock_agent(self):
        value = {"name": "set", "rows": [{**row(), "goldPatch": ""}]}
        with self.assertRaisesRegex(ValueError, "reference fix"):
            self.service.enqueue("probe", value)
        op = self.service.enqueue("probe", {"name": "set", "rows": [row()]})
        with self.assertRaisesRegex(ValueError, "Docker worker"):
            self.service.execute(op)
        self.assertEqual(list((self.service.root / "jobs").iterdir()), [])
        self.assertNotIn("PRIVATE_REFERENCE", json.dumps(self.service.status(op["id"])))

    def test_probe_checks_both_existing_tests_and_the_same_hidden_tests(self):
        runner = DockerRunner(self.root / "repositories", self.root / "artifacts", self.root / "requests")
        self.engine.runner = runner
        self.service.runtime.prepare_test_image = Mock(return_value="sha256:" + "b" * 64)
        seen = []
        def grade(task, dataset, patch_file, output, resources, harness):
            seen.append((task.hidden_test_patch, patch_file.read_text(), resources.network))
            exit_code = 1 if task.hidden_test_patch and not patch_file.read_text() else 0
            (output / "evaluator.log").write_text("AssertionError" if exit_code else "OK")
            return {"exitCode": exit_code, "resolved": exit_code == 0}
        self.service.runtime.grade = grade
        op = self.service.enqueue("probe", {"name": "set", "rows": [row()]})
        result = self.service.execute(op)
        self.assertEqual(result["agentInvocations"], 0)
        self.assertTrue(result["reports"][0]["candidateReady"])
        self.assertEqual(seen, [(None, "", "offline"), (None, "PRIVATE_REFERENCE", "offline"), ("HIDDEN_FIXTURE", "", "offline"), ("HIDDEN_FIXTURE", "PRIVATE_REFERENCE", "offline")])

    def test_probe_does_not_treat_import_errors_as_valid_regressions(self):
        self.engine.runner = DockerRunner(self.root / "repositories", self.root / "artifacts", self.root / "requests")
        self.service.runtime.prepare_test_image = Mock(return_value="sha256:" + "b" * 64)
        def grade(task, dataset, patch_file, output, resources, harness):
            (output / "evaluator.log").write_text("ModuleNotFoundError: missing_package")
            return {"exitCode": 1 if not patch_file.read_text() else 0, "resolved": bool(patch_file.read_text())}
        self.service.runtime.grade = grade
        result = self.service.execute(self.service.enqueue("probe", {"name": "set", "rows": [row()]}))
        self.assertFalse(result["reports"][0]["candidateReady"])

    def bundle(self, change=None):
        resource = PortableResources(self.service)
        dataset = {"id": fingerprint({"benchmark": "custom", "rows": [row()]}), "name": "set", "benchmark": "custom", "path": "evaluator/dataset.json"}
        pack = f"baselines/{source_key(row()['repository'], row()['baseCommit'])}.pack"
        image = "images/" + "b" * 64 + ".tar"
        payloads = {dataset["path"]: json.dumps([row()]).encode(), pack: b"PACK", image: b"IMAGE"}
        manifest = {"format": "ctxbench-resources", "version": 1, "dataset": dataset,
                    "sources": [{"repository": row()["repository"], "commit": "a" * 40, "path": pack}],
                    "images": [{"id": "sha256:" + "b" * 64, "references": [row()["image"]], "path": image}],
                    "profiles": [], "contexts": [], "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in payloads.items()}}
        if change:
            change(manifest, payloads)
        path = resource.root / "fixture.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name, data in payloads.items():
                archive.writestr(name, data)
        return resource, path

    def test_bundle_manifest_hashes_and_dependency_closure(self):
        resource, path = self.bundle()
        self.assertEqual(resource.validate_archive(path)[0]["dataset"]["name"], "set")
        for mutate in [lambda m, p: p.update({"evaluator/dataset.json": b"tamper"}),
                       lambda m, p: m.update(images=[]), lambda m, p: m.update(sources=[]),
                       lambda m, p: p.update({"../escape": b"unsafe"}),
                       lambda m, p: m.update(version=2)]:
            resource, path = self.bundle(mutate)
            with self.assertRaises(ValueError):
                resource.validate_archive(path)

    def test_export_includes_matching_project_environment_and_its_pi_adapter(self):
        dataset = self.wb.catalog.register('set', 'custom', [row()])
        self.wb.db.put_document('projectEnvironments', 'd'*64, {'key':'d'*64, 'repository':row()['repository'],
            'baseCommit':row()['baseCommit'], 'agentAdapter':'sha256:'+'e'*64})
        self.wb.db.put_document('projectEnvironments', 'f'*64, {'key':'f'*64, 'repository':'unrelated',
            'baseCommit':row()['baseCommit'], 'agentAdapter':'unrelated/agent'})
        resource = PortableResources(self.service)
        operation = self.service.enqueue('bundle-export', {'dataset':dataset['id']})
        attempt = self.root / 'export-attempt'; attempt.mkdir()
        client = Mock()
        def image(ref):
            return SimpleNamespace(id=ref if ref.startswith('sha256:') else 'sha256:'+hashlib.sha256(ref.encode()).hexdigest(), attrs={'Config':{}, 'Size':1}, save=lambda **kwargs: [b'IMAGE'])
        client.images.get.side_effect = image
        with patch('docker.from_env', return_value=client), patch.object(self.wb.runtime, 'baseline', return_value=(self.root, 'cutoff')), \
             patch.object(resource, 'check_source'), patch('worker.ctxbench_worker.portable.write_pack', side_effect=lambda source, commit, target:target.write_bytes(b'PACK')):
            result = resource.export(operation, attempt)
        with zipfile.ZipFile(result['path']) as archive:
            manifest = json.loads(archive.read('manifest.json'))
        refs = {ref for image in manifest['images'] for ref in image['references']}
        self.assertEqual(refs, {row()['image'], 'ctxbench/project-agent:'+'d'*64, 'sha256:'+'e'*64})
        client.images.pull.assert_not_called()

    def test_bundle_import_requires_trust_before_docker_or_writes(self):
        resource, _ = self.bundle()
        with patch("docker.from_env") as docker_client, self.assertRaisesRegex(ValueError, "trusted source"):
            resource.import_bundle({"payload": {"filename": "fixture.zip"}}, self.root / "not-created")
        docker_client.assert_not_called()

    def test_transfer_paths_cannot_escape_worker_directory(self):
        resource = PortableResources(self.service)
        for path in ["../secrets.zip", "/tmp/file.zip", "C:\\file.zip", "-filename.zip", "example.zip/other"]:
            with self.assertRaises(ValueError):
                resource.path(path)

    def test_image_conflicts_are_reported_without_mutation(self):
        resource, path = self.bundle()
        client = Mock()
        client.images.get.return_value = SimpleNamespace(id="sha256:" + "c" * 64)
        with patch("docker.from_env", return_value=client):
            result = resource.inspect(path.name)
        self.assertFalse(result["ready"])
        self.assertEqual(result["conflicts"], [row()["image"]])
        client.images.load.assert_not_called()


if __name__ == "__main__":
    unittest.main()

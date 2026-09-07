import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

from test_images_release import release, SaveProcess, fixture_config


class LocalExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ctxbench-local-export-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.args = argparse.Namespace(root=self.root, version="v0.1.3", output=self.root / "custom 离线 images.zip",
            image=[f"{role}=registry.internal:5000/company/{role}:custom" for role in release.ROLES], progress_json=True)
        self.calls = []
        self.env = ["PATH=/usr/bin", "API_KEY="]
        self.architecture = "amd64"

    def docker(self, *args, **kwargs):
        self.calls.append(args)
        if args[1] == "info": return json.dumps({"OSType": "linux", "Architecture": "amd64"})
        if args[1:3] == ("image", "inspect"):
            role = next(role for role in release.ROLES if f"/{role}:" in args[3])
            return json.dumps([{"Id": "sha256:" + str(release.ROLES.index(role) + 1) * 64, "Os": "linux", "Architecture": self.architecture,
                "Size": 1024, "Config": {"Env": self.env}, "History": "not package metadata"}])
        return ""

    def export(self, config=None, process=None):
        with patch.object(release, "source_state", side_effect=AssertionError("Installed exports must not use Git")), \
                patch.object(release, "compose_config", return_value=config or fixture_config()), \
                patch.object(release, "command", side_effect=self.docker), \
                patch.object(release.subprocess, "Popen", return_value=process or SaveProcess()) as start:
            path = release.export_local(self.args)
        return path, start.call_args.args[0]

    def test_custom_export_is_offline_pinned_and_importable_without_git(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output): path, save_args = self.export()
        manifest = release.verify(path, expected_version="0.1.3")
        self.assertEqual(manifest["source"], {"commit": None, "dirty": None})
        self.assertEqual(manifest["buildMode"], "existing-local-images")
        self.assertEqual({i["runtimeReference"] for i in manifest["images"]}, set(release.RUNTIME_IMAGES.values()))
        self.assertNotIn("registry.internal", json.dumps(manifest))
        self.assertNotIn("Config", json.dumps(manifest))
        self.assertNotIn("History", json.dumps(manifest))
        self.assertEqual(save_args, ["docker", "image", "save", *[i["archiveReference"] for i in manifest["images"]]])
        tagged = [call for call in self.calls if call[1:3] == ("image", "tag")]
        removed = [call[3] for call in self.calls if call[1:3] == ("image", "rm")]
        self.assertEqual(len(tagged), 4)
        self.assertEqual(set(removed), {i["archiveReference"] for i in manifest["images"]})
        self.assertTrue(all(call[3].startswith("sha256:") and ":local-export-" in call[4] for call in tagged))
        self.assertFalse(any(any(word in call for word in ("git", "build", "pull", "commit", "stop", "up", "prune")) for call in self.calls))
        self.assertFalse(list(self.root.glob(".ctxbench-export-*")))
        events = [json.loads(line.removeprefix("CTXBENCH_EXPORT_PROGRESS ")) for line in output.getvalue().splitlines() if line.startswith("CTXBENCH_EXPORT_PROGRESS ")]
        self.assertEqual({event["phase"] for event in events}, {"inspect", "save", "package", "verify", "complete"})
        self.assertTrue(any(event["phase"] == "save" and event["total"] == 0 and event["completed"] > 0 for event in events))

    def test_credentials_and_wrong_platform_are_rejected_before_tagging_or_saving(self):
        for environment, arch in [(["MIMO_API_KEY=sensitive-fixture"], "amd64"), (["HTTP_PROXY=http://user:pass@proxy"], "amd64"), ([], "arm64")]:
            self.env, self.architecture = environment, arch
            self.calls.clear()
            with self.subTest(env=environment, arch=arch), self.assertRaisesRegex(ValueError, "credentials detected|platform mismatch") as error:
                self.export()
            self.assertNotIn("sensitive-fixture", str(error.exception))
            self.assertTrue(all(call[1] == "info" or call[1:3] == ("image", "inspect") for call in self.calls))
            self.assertFalse(self.args.output.exists())

    def test_plaintext_compose_credentials_are_not_exported_but_empty_placeholders_work(self):
        release.check_image_credentials({"Config": None})
        config = fixture_config()
        config["services"]["ctxbench-worker"]["environment"] = {"OPENAI_API_KEY": "private-fixture"}
        with self.assertRaisesRegex(ValueError, "credentials detected") as error: self.export(config)
        self.assertNotIn("private-fixture", str(error.exception))
        self.assertFalse(any(call[1] == "image" for call in self.calls))
        self.assertFalse(self.args.output.exists())
        for value in ("", "${OPENAI_API_KEY}", "${OPENAI_API_KEY:-}"):
            release.check_image_credentials({"Config": {"Env": ["OPENAI_API_KEY=" + value]}}, allow_placeholders=True)
        with self.assertRaises(ValueError):
            release.check_image_credentials({"Config": {"Env": ["OPENAI_API_KEY=${OPENAI_API_KEY:-private-fixture}"]}}, allow_placeholders=True)

    def test_existing_or_partial_output_is_never_overwritten(self):
        for path in (self.args.output, self.args.output.with_name(self.args.output.name + ".incomplete")):
            path.write_bytes(b"keep me")
            with self.assertRaisesRegex(ValueError, "already exists"): self.export()
            self.assertEqual(path.read_bytes(), b"keep me")
            self.assertEqual(self.calls, [])
            path.unlink()  # This test's explicitly created sentinel only.

    def test_invalid_selections_and_missing_parent_fail_without_docker(self):
        for images in (["ctxbench-worker=--help"], ["ctxbench-worker=x;touch /tmp/file"], self.args.image[:3], self.args.image + self.args.image[:1]):
            with self.subTest(images=images), self.assertRaisesRegex(ValueError, "selection"):
                release.image_selections(images)
        self.args.output = self.root / "missing-parent" / "images.zip"
        with self.assertRaisesRegex(ValueError, "export path"): self.export()
        self.assertEqual(self.calls, [])

    def test_failed_save_removes_only_temporary_tags_and_leaves_no_final_zip(self):
        with self.assertRaisesRegex(ValueError, "save failed"): self.export(process=SaveProcess(status=1))
        self.assertFalse(self.args.output.exists())
        removed = [call[3] for call in self.calls if call[1:3] == ("image", "rm")]
        self.assertEqual(len(removed), 4)
        self.assertTrue(all(":local-export-" in ref for ref in removed))
        self.assertFalse(list(self.root.glob(".ctxbench-export-*")))

    def test_zip_write_failure_is_not_reported_as_success_and_cleans_temporary_tags(self):
        with patch.object(release, "create_single_file", side_effect=OSError("No space left on device")):
            with self.assertRaises(OSError): self.export()
        self.assertFalse(self.args.output.exists())
        self.assertEqual(len([call for call in self.calls if call[1:3] == ("image", "rm")]), 4)

    def test_local_zip_bypasses_only_the_github_wrapper_size_limit(self):
        # Exercise the same branch as a >2 GiB ZIP without allocating gigabytes.
        with patch.object(release, "ASSET_LIMIT", 100_000): path, _ = self.export()
        self.assertTrue(path.is_file())
        release.verify(path)

    def test_custom_images_cannot_be_published_as_an_official_release(self):
        path, _ = self.export()
        with patch.object(release, "command") as github:
            with self.assertRaisesRegex(ValueError, "clean source-built"):
                release.publish(path, "owner/repo", "v0.1.3", single_file=True)
            github.assert_not_called()


@unittest.skipUnless(os.environ.get("CTXBENCH_IMAGE_RELEASE_DOCKER_TEST") == "1", "Requires explicit Docker integration opt-in in WSL/Linux.")
class CustomizedImageRoundtrip(unittest.TestCase):
    def test_runtime_aliases_match_installed_compose_contract(self):
        root = Path(__file__).resolve().parents[2]
        config = release.compose_config(root)
        self.assertEqual({role: config["services"][role]["image"] for role in release.ROLES}, release.RUNTIME_IMAGES)

    def test_customized_layer_survives_export_and_import_without_changing_source_tags(self):
        token = uuid.uuid4().hex[:12]
        sources = {role: f"company.example/export-test/{role}:{token}" for role in release.ROLES}
        runtimes = {role: f"ctxbench/export-test-{role}:{token}" for role in release.ROLES}
        baseline = f"ctxbench/export-test-baseline:{token}"
        container = f"ctxbench-export-test-{token}"
        archives = []
        with tempfile.TemporaryDirectory(prefix="ctxbench-custom-roundtrip-") as temporary:
            root = Path(temporary)
            (root / "baseline.txt").write_text("baseline")
            (root / "Dockerfile").write_text("FROM scratch\nCOPY baseline.txt /baseline.txt\n")
            try:
                release.command("docker", "build", "--network", "none", "--platform", "linux/amd64", "-t", baseline, str(root))
                (root / "company-dependency.txt").write_text("custom software payload v2")
                (root / "Dockerfile").write_text(f"FROM {baseline}\nCOPY company-dependency.txt /company-dependency.txt\n")
                first = sources[release.ROLES[0]]
                release.command("docker", "build", "--network", "none", "--pull=false", "-t", first, str(root))
                for ref in list(sources.values())[1:]: release.command("docker", "image", "tag", first, ref)
                image_id = release.command("docker", "image", "inspect", "--format", "{{.Id}}", first, capture=True).strip()
                args = argparse.Namespace(root=root, version="v0.1.3", output=root / "internal-custom.zip",
                    image=[f"{role}={ref}" for role, ref in sources.items()], progress_json=True)
                with patch.object(release, "compose_config", return_value=fixture_config()), patch.object(release, "RUNTIME_IMAGES", runtimes):
                    release.export_local(args)
                manifest = release.verify(args.output)
                archives = [item["archiveReference"] for item in manifest["images"]]
                for ref in sources.values():
                    self.assertEqual(release.command("docker", "image", "inspect", "--format", "{{.Id}}", ref, capture=True).strip(), image_id)
                release.import_bundle(args.output, expected_version="0.1.3")
                release.command("docker", "create", "--name", container, "--network", "none", runtimes[release.ROLES[2]], "/not-executed")
                release.command("docker", "cp", f"{container}:/company-dependency.txt", str(root / "restored.txt"))
                self.assertEqual((root / "restored.txt").read_text(), "custom software payload v2")
            finally:
                subprocess.run(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                subprocess.run(["docker", "image", "rm", baseline, *sources.values(), *runtimes.values(), *archives], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


if __name__ == "__main__": unittest.main()

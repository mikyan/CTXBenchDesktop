"""Packaging regressions are independent of the worker and require only stdlib."""
import argparse
import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile
import stat
import contextlib

SCRIPT = Path(__file__).resolve().parents[1] / "images-release.py"
spec = importlib.util.spec_from_file_location("images_release", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def fixture_config():
    names = ("worker", "egress-proxy", "agent-pi", "official-harness")
    services = {role: {"image": f"ctxbench/{name}:0.1.0", "build": {"context": "/private/source"}}
                for role, name in zip(release.ROLES, names)}
    services["ctxbench-worker"]["environment"] = {"OPENAI_API_KEY": "${OPENAI_API_KEY:-}"}
    return {"services": services, "networks": {"agent": {"internal": True}}}


class SaveProcess:
    def __init__(self, data=b"synthetic Docker archive" * 100, status=0):
        self.stdout = io.BytesIO(data)
        self.status = status

    def wait(self):
        return self.status

    def poll(self):
        return self.status


class LoadInput(io.BytesIO):
    def close(self):
        self.saved = self.getvalue()


class LoadProcess:
    def __init__(self):
        self.stdin = LoadInput()

    def wait(self):
        return 0

    def poll(self):
        return 0


class BundleTests(unittest.TestCase):
    def test_single_zip_contains_everything_and_never_extracts_or_executes_helper(self):
        manifest = self.make_bundle()
        archive = self.folder / release.single_file_name(manifest["version"])
        with zipfile.ZipFile(archive) as zipped:
            self.assertEqual(set(zipped.namelist()), set(release.bundle_files(manifest)))
            self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in zipped.infolist()))
        moved = self.root / "Chinese 离线 bundle.zip"
        archive.rename(moved)
        with patch.object(release, "command") as command:
            self.assertEqual(release.verify(moved), manifest)
            command.assert_not_called()
        self.assertEqual(release.verify(self.folder / release.MANIFEST), manifest)
        self.assertFalse((self.root / release.HELPER).exists())

    def test_zip_rejects_unsafe_entries_and_bombs_before_docker(self):
        manifest = self.make_bundle()
        valid = self.folder / release.single_file_name(manifest["version"])
        for kind in ("path", "duplicate", "symlink", "compressed", "unexpected", "missing"):
            path = self.root / f"{kind}.zip"
            with zipfile.ZipFile(valid) as original, zipfile.ZipFile(path, "w") as corrupt:
                for name in original.namelist():
                    if kind == "missing" and name == manifest["parts"][0]["name"]:
                        continue
                    corrupt.writestr(name, original.read(name))
                entry = zipfile.ZipInfo("extra.txt")
                if kind == "path": entry.filename = "../escape.py"
                if kind == "duplicate": entry.filename = release.MANIFEST
                if kind == "symlink": entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                if kind == "compressed": entry.compress_type = zipfile.ZIP_DEFLATED
                if kind != "missing": corrupt.writestr(entry, b"ignored")
            with self.subTest(kind=kind), patch.object(release, "command") as docker:
                with self.assertRaises(ValueError): release.import_bundle(path)
                docker.assert_not_called()

    def test_zip_corruption_version_mismatch_and_oversized_metadata_precede_mutation(self):
        manifest = self.make_bundle()
        archive = self.folder / release.single_file_name(manifest["version"])
        with patch.object(release, "command") as docker:
            with self.assertRaisesRegex(ValueError, "Version mismatch"):
                release.import_bundle(archive, expected_version="v0.2.0")
            docker.assert_not_called()
        damaged = self.root / "damaged.zip"
        with zipfile.ZipFile(archive) as original, zipfile.ZipFile(damaged, "w") as changed:
            for name in original.namelist():
                data = original.read(name)
                if name == manifest["parts"][0]["name"]: data = data[:-1] + bytes([data[-1] ^ 1])
                changed.writestr(name, data)
        with patch.object(release, "command") as docker:
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                release.import_bundle(damaged)
            docker.assert_not_called()
        (self.folder / release.MANIFEST).write_bytes(b"x" * (release.MAX_METADATA + 1))
        with self.assertRaisesRegex(ValueError, "metadata is too large"):
            release.verify(self.folder)

    def test_single_file_zip_limit_and_exclusive_creation(self):
        manifest = self.make_bundle()
        archive = self.folder / release.single_file_name(manifest["version"])
        with self.assertRaises(FileExistsError): release.create_single_file(self.folder)
        original_verify = release.verify
        with patch.object(release, "verify", return_value=original_verify(self.folder)), patch.object(release, "ASSET_LIMIT", 1024):
            with self.assertRaisesRegex(ValueError, "2 GiB"):
                release.create_single_file(self.folder, self.root / "too-large.zip")
        self.assertTrue(archive.is_file())

    def test_running_worker_blocks_zip_import_before_tag_or_load(self):
        manifest = self.make_bundle()
        for running in (["running-worker"], ["", "running-agent"], ["", "", "running-grader"]):
            with self.subTest(running=running), patch.object(release, "command", side_effect=[json.dumps({"OSType": "linux", "Architecture": "amd64"}), *running]) as command, patch.object(release.subprocess, "Popen") as start:
                with self.assertRaisesRegex(ValueError, "Active CTXBench"):
                    release.import_bundle(self.folder / release.single_file_name(manifest["version"]), require_stopped=True)
                self.assertTrue(all(call.args[1] in ("info", "ps") for call in command.call_args_list))
                start.assert_not_called()

    def test_activity_is_rechecked_after_verification_and_queries_only_running_labels(self):
        manifest = self.make_bundle()
        verified = False
        original = release._verify
        def verify(*args):
            nonlocal verified
            value = original(*args)
            verified = True
            return value
        def docker(*args, **kwargs):
            if args[1] == "info": return json.dumps({"OSType": "linux", "Architecture": "amd64"})
            self.assertTrue(verified)
            self.assertEqual(args[1:3], ("ps", "--filter"))
            self.assertNotIn("-a", args)
            return "grading-started-during-verification" if args[3] == "label=io.ctxbench.evaluator" else ""
        with patch.object(release, "_verify", side_effect=verify), patch.object(release, "command", side_effect=docker), patch.object(release.subprocess, "Popen") as start:
            with self.assertRaisesRegex(ValueError, "Active CTXBench"):
                release.import_bundle(self.folder / release.single_file_name(manifest["version"]), require_stopped=True)
            start.assert_not_called()

    def test_zip_import_streams_bytes_and_stage_progress(self):
        manifest = self.make_bundle()
        def docker(*args, **kwargs):
            if args[1] == "info": return json.dumps({"OSType": "linux", "Architecture": "amd64"})
            return ""
        process = LoadProcess()
        output = io.StringIO()
        with patch.object(release, "command", side_effect=docker), patch.object(release.subprocess, "Popen", return_value=process), contextlib.redirect_stdout(output):
            release.import_bundle(self.folder / release.single_file_name(manifest["version"]), release.Progress(True), "0.1.0", require_stopped=True)
        self.assertEqual(process.stdin.saved, b"".join((self.folder / part["name"]).read_bytes() for part in manifest["parts"]))
        events = [json.loads(line[len(release.PROGRESS_PREFIX):]) for line in output.getvalue().splitlines() if line.startswith(release.PROGRESS_PREFIX)]
        self.assertEqual(set(event["phase"] for event in events), {"verify", "load", "unpack", "register", "complete"})
        self.assertEqual(events[-1], {"phase": "complete", "completed": 4, "total": 4})

    def test_publish_single_zip_only_and_reject_stale_wrapper(self):
        self.publishable()
        archive = self.folder / release.single_file_name("v0.1.0")
        calls = []
        def gh(*args, **kwargs):
            calls.append(args)
            return json.dumps({"assets": []} if "/releases/" in args[2] else {"sha": self.source["commit"]}) if args[1] == "api" else ""
        with patch.object(release, "command", side_effect=gh):
            with self.assertRaisesRegex(ValueError, "manifests differ"):
                release.publish(self.folder, "owner/repo", "v0.1.0", single_file=True)
        # Only the generated fixture wrapper is replaced, not a published artifact.
        archive.unlink()
        release.create_single_file(self.folder)
        calls.clear()
        with patch.object(release, "command", side_effect=gh):
            release.publish(self.folder, "owner/repo", "v0.1.0", single_file=True)
        uploads = [call for call in calls if call[1:3] == ("release", "upload")]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(Path(uploads[0][4]), archive)

    def test_single_zip_publication_resumes_identical_asset_without_overwrite(self):
        self.publishable()
        archive = self.folder / release.single_file_name("v0.1.0")
        archive.unlink()
        release.create_single_file(self.folder)
        for checksum in (release.digest(archive), "bad"):
            asset = {"name": archive.name, "digest": "sha256:" + checksum, "size": archive.stat().st_size}
            with self.subTest(checksum=checksum), patch.object(release, "command", side_effect=[json.dumps({"assets": [asset]}), json.dumps({"sha": self.source["commit"]})]) as command:
                if checksum == "bad":
                    with self.assertRaisesRegex(ValueError, "not overwritten"):
                        release.publish(self.folder, "owner/repo", "v0.1.0", single_file=True)
                else:
                    release.publish(self.folder, "owner/repo", "v0.1.0", single_file=True)
                self.assertEqual(command.call_count, 2)

    def test_publish_original_zip_from_actions_without_extracting_it(self):
        self.publishable()
        archive = self.folder / release.single_file_name("v0.1.0")
        archive.unlink()
        release.create_single_file(self.folder)
        moved = self.root / archive.name
        archive.rename(moved)
        def gh(*args, **kwargs):
            return json.dumps({"assets": []} if "/releases/" in args[2] else {"sha": self.source["commit"]}) if args[1] == "api" else ""
        with patch.object(release, "command", side_effect=gh) as command:
            release.publish(moved, "owner/repo", "v0.1.0")
        uploads = [call for call in command.call_args_list if call.args[1:3] == ("release", "upload")]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(Path(uploads[0].args[4]), moved)

    def test_publication_falls_back_to_parts_when_no_single_zip_exists(self):
        self.publishable()
        (self.folder / release.single_file_name("v0.1.0")).unlink()
        def gh(*args, **kwargs):
            return json.dumps({"assets": []} if "/releases/" in args[2] else {"sha": self.source["commit"]}) if args[1] == "api" else ""
        with patch.object(release, "command", side_effect=gh) as command:
            release.publish(self.folder, "owner/repo", "v0.1.0", single_file=True)
        uploads = [call for call in command.call_args_list if call.args[1:3] == ("release", "upload")]
        self.assertEqual(len(uploads), 6)
        self.assertFalse(any("--clobber" in call.args for call in uploads))

    def test_compose_config_keeps_host_paths_and_credentials_unresolved(self):
        with patch.object(release, "command", return_value=json.dumps(fixture_config())) as run:
            config = release.compose_config(Path("/source checkout"))
        args = run.call_args.args
        for option in ("--no-interpolate", "--no-path-resolution", "--no-env-resolution"):
            self.assertIn(option, args)
        self.assertEqual(config["services"]["ctxbench-worker"]["environment"]["OPENAI_API_KEY"], "${OPENAI_API_KEY:-}")

    def test_offline_mounts_remain_portable_across_build_hosts(self):
        config = fixture_config()
        source = "${CTXBENCH_HOST_DATA_DIR:-/var/lib/ctxbench}"
        config["services"]["ctxbench-worker"]["volumes"] = [{"type": "bind", "source": source, "target": "/var/lib/ctxbench"}]
        offline = release.offline_compose(config)
        self.assertEqual(offline["services"]["ctxbench-worker"]["volumes"][0]["source"], source)
        self.assertNotIn("/home/runner", json.dumps(offline))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ctxbench-bundle-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / "bundle"
        self.source = {"commit": "a" * 40, "dirty": False}
        self.args = argparse.Namespace(root=self.root, output=self.folder, version="v0.1.0",
                                       part_size_mib=1, skip_build=True, allow_dirty=False)

    def make_bundle(self, **overrides):
        for key, value in overrides.items():
            setattr(self.args, key, value)
        def inspect(*args, **kwargs):
            self.assertEqual(args[:3], ("docker", "image", "inspect"))
            return json.dumps([{"Id": "sha256:" + "b" * 64, "Os": "linux", "Architecture": "amd64",
                                "Size": 123, "Config": {"Env": ["SECRET=must-never-leak"]}}])
        with patch.object(release, "source_state", return_value=self.source), \
                patch.object(release, "compose_config", return_value=fixture_config()), \
                patch.object(release, "command", side_effect=inspect), \
                patch.object(release.subprocess, "Popen", return_value=SaveProcess()):
            release.pack(self.args)
        return release.verify(self.folder)

    def change_manifest(self, update):
        path = self.folder / release.MANIFEST
        manifest = json.loads(path.read_text(encoding="utf-8"))
        update(manifest)
        release.write_json(path, manifest)
        sums = self.folder / release.CHECKSUMS
        lines = sums.read_text().splitlines()
        sums.write_text("\n".join(f"{release.digest(path)}  {release.MANIFEST}" if line.endswith("  " + release.MANIFEST)
                                  else line for line in lines) + "\n")

    def test_pack_verify_and_portable_paths(self):
        manifest = self.make_bundle()
        self.assertEqual(manifest["buildMode"], "existing-local-images")
        for name in (release.MANIFEST, release.CHECKSUMS, release.COMPOSE):
            text = (self.folder / name).read_text()
            self.assertNotIn("must-never-leak", text)
            self.assertNotIn("/private/source", text)
        moved = self.root / "moved bundle"
        self.folder.rename(moved)
        release.verify(moved)
        compose = json.loads((moved / release.COMPOSE).read_text())
        self.assertEqual(len(compose["services"]), 2)
        for service in compose["services"].values():
            self.assertNotIn("build", service)
            self.assertEqual(service["pull_policy"], "never")
        self.assertEqual(compose["services"]["ctxbench-worker"]["environment"]["OPENAI_API_KEY"], "${OPENAI_API_KEY:-}")

    def test_gzip_multiple_parts_roundtrip(self):
        self.folder.mkdir()
        original = bytes(range(256)) * 20
        with patch.object(release.subprocess, "Popen", return_value=SaveProcess(original)):
            parts = release.export_stream(["ctxbench/test:1"], self.folder, "sample.tar.gz", 100)
        self.assertGreater(len(parts), 1)
        combined = b"".join((self.folder / part["name"]).read_bytes() for part in parts)
        self.assertEqual(gzip.decompress(combined), original)
        self.assertTrue(all(0 < item["bytes"] <= 100 for item in parts))

    def test_export_failure_is_not_valid(self):
        with patch.object(release, "source_state", return_value=self.source), \
                patch.object(release, "compose_config", return_value=fixture_config()), \
                patch.object(release, "command", return_value=json.dumps([{"Os": "linux", "Architecture": "amd64", "Id": "x", "Size": 1}])), \
                patch.object(release.subprocess, "Popen", return_value=SaveProcess(status=1)):
            with self.assertRaisesRegex(ValueError, "save failed"):
                release.pack(self.args)
        self.assertTrue((self.folder / release.INCOMPLETE).exists())
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            release.verify(self.folder)

    def test_existing_output_not_overwritten(self):
        self.make_bundle()
        original = (self.folder / release.MANIFEST).read_bytes()
        with self.assertRaises(FileExistsError):
            self.make_bundle()
        self.assertEqual((self.folder / release.MANIFEST).read_bytes(), original)

    def test_dirty_checkout_requires_explicit_flag(self):
        self.source["dirty"] = True
        with self.assertRaisesRegex(ValueError, "Commit source changes"):
            self.make_bundle()
        manifest = self.make_bundle(allow_dirty=True)
        self.assertTrue(manifest["source"]["dirty"])

    def test_missing_part_rejected_before_docker(self):
        manifest = self.make_bundle()
        (self.folder / manifest["parts"][0]["name"]).unlink()
        with patch.object(release, "command") as docker:
            with self.assertRaisesRegex(ValueError, "Missing"):
                release.import_bundle(self.folder)
            docker.assert_not_called()

    def test_corrupt_part_rejected_before_docker(self):
        manifest = self.make_bundle()
        part = self.folder / manifest["parts"][0]["name"]
        data = bytearray(part.read_bytes())
        data[-1] ^= 1
        part.write_bytes(data)
        with patch.object(release, "command") as docker:
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                release.import_bundle(self.folder)
            docker.assert_not_called()

    def test_manifest_tampering_rejected(self):
        self.make_bundle()
        with (self.folder / release.MANIFEST).open("a") as stream:
            stream.write(" ")
        with self.assertRaisesRegex(ValueError, "Manifest checksum"):
            release.verify(self.folder)

    def test_path_traversal_and_part_order_rejected(self):
        self.make_bundle()
        self.change_manifest(lambda m: m["parts"][0].update(name="../private.env"))
        with self.assertRaisesRegex(ValueError, "ordered"):
            release.verify(self.folder)
        for name in ("../secret", "/tmp/key", "C:\\secret", "--flag", ".env"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                release.local_file(self.folder, name)

    def test_missing_support_and_injected_checksum_rejected(self):
        self.make_bundle()
        with (self.folder / release.CHECKSUMS).open("a") as stream:
            stream.write("0" * 64 + "  private.env\n")
        with self.assertRaisesRegex(ValueError, "inventory"):
            release.verify(self.folder)

    def test_image_inventory_validation(self):
        self.make_bundle()
        self.change_manifest(lambda m: m["images"].pop())
        with self.assertRaisesRegex(ValueError, "four application"):
            release.verify(self.folder)

    def test_size_and_platform_validation(self):
        for size in (0, 1901):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "Part size"):
                self.make_bundle(part_size_mib=size)
        self.make_bundle(part_size_mib=1)
        self.change_manifest(lambda m: m.update(platform="linux/arm64"))
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            release.verify(self.folder)

    def test_unsafe_version_rejected(self):
        for version in ("../x", "--help", "x; touch file", "", "x" * 81):
            with self.subTest(version=version), self.assertRaises(ValueError):
                release.version_name(version)

    def test_import_stream_and_alias_backups(self):
        manifest = self.make_bundle()
        calls = []
        def docker(*args, **kwargs):
            calls.append(args)
            if args[1] == "info":
                return json.dumps({"OSType": "linux", "Architecture": "x86_64"})
            if args[1:3] == ("image", "ls"):
                return "sha256:" + "c" * 64
            return ""
        process = LoadProcess()
        with patch.object(release, "command", side_effect=docker), \
                patch.object(release.subprocess, "Popen", return_value=process) as start:
            release.import_bundle(self.folder)
        self.assertEqual(start.call_args.args[0], ["docker", "image", "load"])
        self.assertEqual(process.stdin.saved, b"".join((self.folder / part["name"]).read_bytes() for part in manifest["parts"]))
        self.assertEqual(len([call for call in calls if call[1:3] == ("image", "tag")]), 8)
        self.assertFalse(any("pull" in call or "up" in call or "build" in call for call in calls))

    def test_wrong_daemon_does_not_load(self):
        self.make_bundle()
        with patch.object(release, "command", return_value=json.dumps({"OSType": "windows", "Architecture": "amd64"})), \
                patch.object(release.subprocess, "Popen") as start:
            with self.assertRaisesRegex(ValueError, "Linux amd64"):
                release.import_bundle(self.folder)
            start.assert_not_called()

    def publishable(self):
        self.make_bundle()
        self.change_manifest(lambda m: m.update(buildMode="source-build"))

    def test_publish_requires_clean_source_build(self):
        self.make_bundle()
        with patch.object(release, "command") as gh:
            with self.assertRaisesRegex(ValueError, "clean source-built"):
                release.publish(self.folder, "owner/repo", "v0.1.0")
            gh.assert_not_called()

    def test_publish_only_inventory_and_never_overwrites(self):
        self.publishable()
        (self.folder / "unrelated-secret.env").write_text("do not upload")
        calls = []
        def gh(*args, **kwargs):
            calls.append(args)
            if args[1] == "api":
                return json.dumps({"assets": []} if "/releases/" in args[2] else {"sha": self.source["commit"]})
            return ""
        with patch.object(release, "command", side_effect=gh):
            release.publish(self.folder, "owner/repo", "v0.1.0")
        uploads = [call for call in calls if call[1:3] == ("release", "upload")]
        self.assertEqual(len(uploads), 6)
        self.assertFalse(any("--clobber" in call or "secret.env" in " ".join(call) for call in uploads))

    def test_publish_commit_mismatch_or_conflicting_asset(self):
        self.publishable()
        for wrong_commit in (True, False):
            calls = []
            def gh(*args, **kwargs):
                calls.append(args)
                if "/releases/" in args[2]:
                    return json.dumps({"assets": [{"name": release.MANIFEST, "size": 1, "digest": "sha256:bad"}]})
                return json.dumps({"sha": "bad" if wrong_commit else self.source["commit"]})
            with self.subTest(wrong_commit=wrong_commit), patch.object(release, "command", side_effect=gh):
                with self.assertRaises(ValueError):
                    release.publish(self.folder, "owner/repo", "v0.1.0")
            self.assertFalse(any(call[1:3] == ("release", "upload") for call in calls))

    def test_publish_resume_skips_matching_assets(self):
        self.publishable()
        manifest = release.verify(self.folder)
        names = [release.MANIFEST, release.CHECKSUMS, *(i["name"] for i in manifest["supportFiles"]),
                 *(i["name"] for i in manifest["parts"])]
        assets = [{"name": name, "size": (self.folder / name).stat().st_size,
                   "digest": "sha256:" + release.digest(self.folder / name)} for name in names]
        calls = []
        def gh(*args, **kwargs):
            calls.append(args)
            return json.dumps({"assets": assets} if "/releases/" in args[2] else {"sha": self.source["commit"]})
        with patch.object(release, "command", side_effect=gh):
            release.publish(self.folder, "owner/repo", "v0.1.0")
        self.assertEqual(len(calls), 2)

    def test_build_uses_isolated_tags(self):
        calls, overrides = [], []
        def docker(*args, **kwargs):
            calls.append(args)
            if args[1] == "compose":
                override = Path(args[args.index("--profile") - 1])
                overrides.append(json.loads(override.read_text()))
                return ""
            return json.dumps([{"Os": "linux", "Architecture": "amd64", "Id": "sha256:" + "d" * 64, "Size": 10}])
        self.args.skip_build = False
        with patch.object(release, "source_state", return_value=self.source), \
                patch.object(release, "compose_config", return_value=fixture_config()), \
                patch.object(release, "command", side_effect=docker), \
                patch.object(release.subprocess, "Popen", return_value=SaveProcess()):
            release.pack(self.args)
        manifest = release.verify(self.folder)
        self.assertEqual(manifest["buildMode"], "source-build")
        self.assertTrue(all("bundle-v0.1.0-" in item["archiveReference"] for item in manifest["images"]))
        self.assertTrue(all(item["runtimeReference"].endswith(":0.1.0") for item in manifest["images"]))
        self.assertTrue(all(s["platform"] == "linux/amd64" for s in overrides[0]["services"].values()))


@unittest.skipUnless(os.environ.get("CTXBENCH_IMAGE_RELEASE_DOCKER_TEST") == "1", "Set CTXBENCH_IMAGE_RELEASE_DOCKER_TEST=1 in WSL/Linux for real Docker roundtrip.")
class DockerRoundtrip(unittest.TestCase):
    def test_real_compose_export_does_not_embed_build_host_paths(self):
        root = SCRIPT.parents[1]
        config = release.compose_config(root)
        offline = release.offline_compose(config)
        volumes = offline["services"]["ctxbench-worker"]["volumes"]
        data = next(volume for volume in volumes if volume["target"] == "/var/lib/ctxbench")
        self.assertEqual(data["source"], "${CTXBENCH_HOST_DATA_DIR:-/var/lib/ctxbench}")
        self.assertNotIn(str(root), json.dumps(offline))
        self.assertEqual(offline["services"]["ctxbench-worker"]["environment"]["OPENAI_API_KEY"], "${OPENAI_API_KEY:-}")

    def test_real_docker_save_verify_load(self):
        token = uuid.uuid4().hex[:12]
        config = fixture_config()
        refs = []
        for role, service in config["services"].items():
            service["image"] = f"ctxbench/release-test-{role}:{token}"
            refs.append(service["image"])
        with tempfile.TemporaryDirectory(prefix="ctxbench-release-roundtrip-") as temporary:
            root = Path(temporary)
            (root / "Dockerfile").write_text("FROM scratch\nCOPY fixture /fixture\n")
            (root / "fixture").write_bytes(os.urandom(2 * release.MIB))
            try:
                release.command("docker", "build", "--platform", "linux/amd64", "-t", refs[0], str(root))
                for ref in refs[1:]:
                    release.command("docker", "image", "tag", refs[0], ref)
                args = argparse.Namespace(root=root, output=root / "bundle", version="test-roundtrip", part_size_mib=1,
                                          skip_build=True, allow_dirty=False)
                with patch.object(release, "source_state", return_value={"commit": "a" * 40, "dirty": False}), \
                        patch.object(release, "compose_config", return_value=config):
                    release.pack(args)
                manifest = release.verify(args.output)
                self.assertGreaterEqual(len(manifest["parts"]), 3)
                # Only this test's randomly named tags are removed, never production images.
                release.command("docker", "image", "rm", *refs)
                release.import_bundle(args.output / release.single_file_name("test-roundtrip"), release.Progress(True), "test-roundtrip")
                for ref in refs:
                    release.command("docker", "image", "inspect", "--format", "{{.Id}}", ref, capture=True)
            finally:
                subprocess.run(["docker", "image", "rm", *refs], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()

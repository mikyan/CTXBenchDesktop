"""Verified benchmark bundles; evaluator documents never enter baseline repositories.

Portable v1 closes the dependency set for custom datasets with prebuilt test images.
Official harness datasets are rejected until their dynamic dependency graph can be
proven complete, rather than advertising a misleading 'offline-ready' archive.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

from .artifacts import ArtifactStore, safe_relative_path
from .catalog import Catalog, fingerprint
from .database import utc_now
from .environments import image_reference, validate_profile, public_image_config
from .runtime import git
from .safe_files import safe_file


def digest_file(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_key(repository, commit):
    return hashlib.sha256(f"{repository}@{commit}".encode()).hexdigest()


def safe_member(name):
    normalized = safe_relative_path(name).as_posix()
    if normalized != name or "\\" in name or any(part.endswith((".", " ")) for part in name.split("/")):
        raise ValueError("Resource bundle contains an unsafe path.")
    return normalized


def source_objects(source, commit):
    entries = git(source, "ls-tree", "-r", "-t", "-z", commit).split(b"\0")
    objects = {commit, git(source, "rev-parse", commit + "^{tree}").decode().strip()}
    for entry in filter(None, entries):
        meta, _ = entry.split(b"\t", 1)
        _, kind, oid = meta.split()
        if kind == b"commit":
            raise ValueError("Baseline contains submodules. Vendor their pinned contents in a reviewed dataset baseline before portable v1 export.")
        objects.add(oid.decode())
    return objects


def write_pack(source, commit, destination):
    objects = source_objects(source, commit)
    with destination.open("wb") as stream:
        result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(source), "pack-objects", "--stdout"],
                                input=("\n".join(sorted(objects)) + "\n").encode(), stdout=stream, stderr=subprocess.PIPE, timeout=600)
    if result.returncode:
        raise ValueError("Could not package pinned baseline objects.")


def read_pack(source, pack):
    source.mkdir(parents=True, exist_ok=True)
    if not (source / ".git").exists():
        git(source, "init", "-q")
    with pack.open("rb") as stream:
        result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(source), "index-pack", "--stdin"],
                                stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    if result.returncode:
        raise ValueError("Invalid portable baseline pack.")


class PortableResources:
    def __init__(self, service):
        self.service, self.wb = service, service.wb
        self.root = service.root / "transfers"
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, filename):
        if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.zip", filename):
            raise ValueError("Choose a .zip filename inside the Worker intranet/transfers directory, not a Windows path.")
        return safe_file(self.root, filename, limit=200 * 1024**3)

    def check_source(self, source, commit):
        source_objects(source, commit)
        # Check precisely the exported tree, never a working directory or its future history.
        with tarfile.open(fileobj=io.BytesIO(git(source, "archive", "--format=tar", commit))) as archive:
            for member in archive.getmembers():
                safe_member(member.name.rstrip("/"))
                if member.isfile():
                    data = archive.extractfile(member).read()
                    if data.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
                        raise ValueError("Baseline contains unresolved Git LFS pointers. Materialize and pin the files before portable v1 export.")
                    # Known active credentials and private keys cannot leave this Worker.
                    text = data.decode("utf-8", errors="replace")
                    if self.wb.redact(text) != text or "PRIVATE KEY-----" in text:
                        raise ValueError("Baseline contains a configured credential or private key; resource export refused.")

    def export(self, operation, attempt):
        import docker
        value = operation["payload"]
        dataset = self.wb.catalog.verify(value.get("dataset", ""))
        if dataset["benchmark"] != "custom":
            raise ValueError("Portable v1 supports custom datasets with prebuilt images. Official SWE/CTX harness datasets have dynamic dependencies; use the standard dataset and Docker image transfer guides, not an incomplete resource bundle.")
        tasks = self.wb.catalog.index(dataset["id"])
        if any(not task.image for task in tasks.values()):
            raise ValueError("Build-only tasks cannot be marked offline-ready. Create a new dataset version using prebuilt test image references first.")
        manifest = {"format": "ctxbench-resources", "version": 1, "createdAt": utc_now(), "dataset": {
            "id": dataset["id"], "name": dataset["name"], "benchmark": "custom", "path": "evaluator/dataset.json"},
            "sources": [], "images": [], "contexts": [], "profiles": [], "files": {}, "agentCredentialsIncluded": False}
        content = attempt / "content"
        content.mkdir()

        def put(name, data):
            target = content / safe_member(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return target

        self.service.material(json.loads(Path(dataset["path"]).read_text(encoding="utf-8")))
        put("evaluator/dataset.json", Path(dataset["path"]).read_bytes())
        sources = set()
        for task in tasks.values():
            self.wb._check(None)
            key = source_key(task.repository, task.base_commit)
            if key in sources:
                continue
            self.service.progress(operation, f"Packaging exact baseline: {task.repository} @ {task.base_commit}", 10)
            source, _ = self.wb.runtime.baseline(task)
            self.check_source(source, task.base_commit)
            target = put(f"baselines/{key}.pack", b"")
            write_pack(source, task.base_commit, target)
            manifest["sources"].append({"repository": task.repository, "commit": task.base_commit, "path": f"baselines/{key}.pack"})
            sources.add(key)
        for profile_id in value.get("profileIds", []):
            profile = self.service.profiles.get(profile_id)
            path = f"profiles/{profile_id}.json"
            put(path, json.dumps(profile["document"]).encode())
            manifest["profiles"].append({"id": profile_id, "path": path})
        baseline_ids = {(t.repository, t.base_commit) for t in tasks.values()}
        for key in value.get("contextIds", []):
            store = self.wb.engine.artifacts
            context = store.verify(key)
            if (context["identity"]["repository"], context["identity"]["commit"]) not in baseline_ids:
                raise ValueError("A selected context does not match a dataset baseline.")
            directory = store.path_for(key)
            self.service.material(context)
            put(f"contexts/{key}/manifest.json", (directory / "manifest.json").read_bytes())
            for name in context["files"]:
                data = (directory / "files" / name).read_bytes()
                self.service.material(data.decode("utf-8", errors="replace"))
                put(f"contexts/{key}/files/{name}", data)
            manifest["contexts"].append(key)
        refs = {task.image for task in tasks.values()}
        extra = value.get("images", [])
        if not isinstance(extra, list) or len(extra) > 100:
            raise ValueError("Select at most 100 additional local images.")
        refs.update(image_reference(ref) for ref in extra)
        for profile_id in value.get("profileIds", []):
            refs.add(self.service.profiles.get(profile_id)["document"]["agentImage"])
        client = docker.from_env(timeout=3600)
        try:
            selected = {}
            for ref in sorted(refs):
                image = client.images.get(ref)  # No automatic network pull.
                public_image_config(image.attrs.get("Config", {}), self.wb.redact)
                selected.setdefault(image.id, {"image": image, "references": []})["references"].append(ref)
            required = sum(item["image"].attrs.get("Size", 0) for item in selected.values()) * 3 + 512 * 1024**2
            if shutil.disk_usage(content).free < required:
                raise ValueError("Insufficient disk space for image staging and the resource ZIP.")
            for index, (key, item) in enumerate(selected.items()):
                self.wb._check(None)
                self.service.progress(operation, f"Saving local image {index + 1}/{len(selected)}: {key}", 20 + int(index / len(selected) * 60))
                name = f"images/{key.removeprefix('sha256:')}.tar"
                target = put(name, b"")
                with target.open("wb") as stream:
                    for chunk in item["image"].save(named=False):
                        stream.write(chunk)
                manifest["images"].append({"id": key, "references": item["references"], "path": name})
        finally:
            client.close()
        self.service.progress(operation, "Hashing and writing the portable resource ZIP.", 85)
        for path in content.rglob("*"):
            if path.is_file():
                manifest["files"][path.relative_to(content).as_posix()] = {"sha256": digest_file(path), "bytes": path.stat().st_size}
        filename = "ctxbench-resources-" + operation["id"] + "-" + attempt.name.split("-")[-1] + ".zip"
        partial = self.root / (filename + ".incomplete")
        with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            for name in manifest["files"]:
                archive.write(content / name, name)
        # Verify the complete byte inventory before exposing the final filename.
        self.validate_archive(partial)
        final = self.root / filename
        if final.exists():
            raise ValueError("Resource bundle output already exists; no file was replaced.")
        partial.rename(final)
        return {"filename": filename, "path": str(final), "sha256": digest_file(final), "bytes": final.stat().st_size,
                "datasets": 1, "baselines": len(sources), "images": len(manifest["images"]), "contexts": len(manifest["contexts"]),
                "note": "Runtime installation and API credentials are separate. Review custom tests and image layers before sharing."}

    def validate_archive(self, path, progress=None):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) > 100000 or len(set(names)) != len(names) or "manifest.json" not in names:
                raise ValueError("Duplicate members or invalid resource bundle inventory.")
            if archive.getinfo("manifest.json").file_size > 10 * 1024**2:
                raise ValueError("Resource bundle manifest is oversized.")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != "ctxbench-resources" or manifest.get("version") != 1 or not isinstance(manifest.get("files"), dict):
                raise ValueError("Unsupported resource bundle version.")
            if set(names) != {"manifest.json", *manifest["files"]}:
                raise ValueError("Resource bundle inventory differs from its manifest.")
            total = sum(info.file_size for info in archive.infolist())
            if total > 200 * 1024**3:
                raise ValueError("Resource bundle exceeds the 200 GiB safety limit.")
            processed = 0
            for name, expected in manifest["files"].items():
                safe_member(name)
                info = archive.getinfo(name)
                if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000 or info.file_size != expected["bytes"]:
                    raise ValueError("Resource bundle contains unsafe or incorrectly sized members.")
                with archive.open(name) as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != expected["sha256"]:
                        raise ValueError("Resource bundle checksum mismatch. No resources were imported.")
                processed += info.file_size
                if progress:
                    progress(f"Verified {name}: {processed}/{total} bytes.", 5 + int(processed / max(total, 1) * 75))
            self.service.material(manifest)
            dataset = manifest["dataset"]
            if dataset.get("path") != "evaluator/dataset.json":
                raise ValueError("Invalid evaluator definition location.")
            rows = json.loads(archive.read(dataset["path"]))
            self.service.material(rows)
            tasks = Catalog.validate(dataset["name"], dataset["benchmark"], rows)
            if dataset["benchmark"] != "custom" or fingerprint({"benchmark": "custom", "rows": rows}) != dataset["id"] or any(not t.image for t in tasks):
                raise ValueError("Dataset identity or portable version is invalid.")
            expected_sources = {(task.repository, task.base_commit) for task in tasks}
            actual_sources = {(s["repository"], s["commit"]) for s in manifest["sources"]}
            if expected_sources != actual_sources or len(actual_sources) != len(manifest["sources"]):
                raise ValueError("Resource bundle baseline dependency closure is incomplete.")
            for source in manifest["sources"]:
                expected_path = f"baselines/{source_key(source['repository'], source['commit'])}.pack"
                if source["path"] != expected_path or source["path"] not in manifest["files"]:
                    raise ValueError("Invalid baseline resource path.")
            references = set()
            image_ids = set()
            for image in manifest["images"]:
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", image["id"]) or image["id"] in image_ids or image["path"] != f"images/{image['id'][7:]}.tar" or image["path"] not in manifest["files"]:
                    raise ValueError("Invalid image dependency identity.")
                image_ids.add(image["id"])
                for reference in image["references"]:
                    image_reference(reference)
                    if reference in references or (reference.startswith("sha256:") and reference != image["id"]):
                        raise ValueError("Duplicate or inconsistent image reference.")
                    references.add(reference)
            if not {t.image for t in tasks}.issubset(references):
                raise ValueError("Resource bundle is missing task images.")
            for profile in manifest["profiles"]:
                document = validate_profile(json.loads(archive.read(profile["path"])), self.wb.redact)
                if fingerprint(document) != profile["id"] or profile["path"] != f"profiles/{profile['id']}.json" or document["agentImage"] not in references:
                    raise ValueError("Profile identity or Agent image dependency is invalid.")
            for key in manifest["contexts"]:
                if not re.fullmatch(r"[0-9a-f]{64}", key):
                    raise ValueError("Invalid context identity.")
                context = json.loads(archive.read(f"contexts/{key}/manifest.json"))
                if context.get("key") != key or fingerprint(context.get("identity")) != key or not context.get("files"):
                    raise ValueError("Frozen context identity is invalid.")
                if (context["identity"]["repository"], context["identity"]["commit"]) not in expected_sources:
                    raise ValueError("Frozen context belongs to a different baseline.")
                self.service.material(context)
                expected_paths = {f"contexts/{key}/manifest.json"}
                for name, digest in context["files"].items():
                    safe_member(name)
                    context_path = f"contexts/{key}/files/{name}"
                    if manifest["files"].get(context_path, {}).get("sha256") != digest:
                        raise ValueError("Frozen context file checksum differs from its manifest.")
                    expected_paths.add(context_path)
                if expected_paths != {name for name in manifest["files"] if name.startswith(f"contexts/{key}/")}:
                    raise ValueError("Frozen context inventory is inconsistent.")
            expected_paths = {dataset["path"], *[s["path"] for s in manifest["sources"]], *[i["path"] for i in manifest["images"]], *[p["path"] for p in manifest["profiles"]]}
            expected_paths.update(name for name in manifest["files"] if any(name.startswith(f"contexts/{key}/") for key in manifest["contexts"]))
            if expected_paths != set(manifest["files"]):
                raise ValueError("Bundle contains undeclared resource classes.")
            return manifest, total

    def conflicts(self, manifest):
        import docker
        client = docker.from_env()
        conflicts = []
        try:
            for image in manifest["images"]:
                for ref in image["references"]:
                    if "@sha256:" in ref:
                        aliases = self.service.root / "image-references"
                        alias_name = hashlib.sha256(ref.encode()).hexdigest() + ".json"
                        if (aliases / alias_name).exists():
                            receipt = json.loads(safe_file(aliases, alias_name).read_text(encoding="utf-8"))
                            if receipt != {"reference": ref, "id": image["id"]}:
                                conflicts.append(ref)
                    try:
                        if client.images.get(ref).id != image["id"]:
                            conflicts.append(ref)
                    except docker.errors.ImageNotFound:
                        pass
        finally:
            client.close()
        return conflicts

    def inspect(self, filename, progress=None):
        path = self.path(filename)
        manifest, size = self.validate_archive(path, progress)
        if progress:
            progress("Checking existing resource conflicts and free space.", 85)
        conflicts = self.conflicts(manifest)
        with zipfile.ZipFile(path) as archive:
            for key in manifest["contexts"]:
                if self.wb.engine.artifacts.contains(key) and self.wb.engine.artifacts.verify(key) != json.loads(archive.read(f"contexts/{key}/manifest.json")):
                    conflicts.append("context:" + key)
        required = size * 3 + 512 * 1024**2
        free = shutil.disk_usage(self.root).free
        return {"filename": filename, "sha256": digest_file(path), "dataset": manifest["dataset"]["name"],
                "datasetId": manifest["dataset"]["id"], "images": len(manifest["images"]), "baselines": len(manifest["sources"]),
                "contexts": len(manifest["contexts"]), "conflicts": conflicts, "requiredBytes": required, "freeBytes": free,
                "ready": not conflicts and free >= required,
                "warning": "Import only trusted bundles: tests and images contain executable code. Hashes detect corruption, not trust."}

    def sanitized_image(self, source, destination, expected_id):
        # Rebuild a single-image legacy archive. OCI annotations and embedded tags
        # cannot silently replace existing application images during docker load.
        with tarfile.open(source) as tar:
            members = tar.getmembers()
            if len({m.name for m in members}) != len(members):
                raise ValueError("Duplicate Docker archive members.")
            # Containerd-backed engines identify an image by an OCI index/manifest
            # digest rather than the legacy config digest. Preserve the complete
            # verified descriptor graph, but remove import-time naming annotations.
            if any(m.name == "index.json" for m in members):
                self.sanitized_oci(tar, destination, expected_id)
                return
            info = tar.getmember("manifest.json")
            if not info.isfile() or info.size > 2 * 1024**2:
                raise ValueError("Invalid Docker image manifest.")
            manifest = json.load(tar.extractfile(info))
            if not isinstance(manifest, list) or len(manifest) != 1:
                raise ValueError("Each resource image must contain exactly one Docker image.")
            record = manifest[0]
            config_info = tar.getmember(safe_member(record["Config"]))
            if not config_info.isfile() or config_info.size > 10 * 1024**2:
                raise ValueError("Invalid image configuration.")
            config = tar.extractfile(config_info).read()
            if "sha256:" + hashlib.sha256(config).hexdigest() != expected_id:
                raise ValueError("Docker image ID does not match its resource manifest.")
            parsed_config = json.loads(config)
            self.service.material(parsed_config)
            public_image_config(parsed_config.get("config", {}), self.wb.redact)
            selected = [record["Config"], *record["Layers"]]
            if len(selected) != len(set(selected)) or "manifest.json" in selected:
                raise ValueError("Invalid Docker image member inventory.")
            with tarfile.open(destination, "w") as clean:
                data = json.dumps([{**record, "RepoTags": None}]).encode()
                header = tarfile.TarInfo("manifest.json")
                header.size = len(data)
                clean.addfile(header, io.BytesIO(data))
                for name in selected:
                    safe_member(name)
                    member = tar.getmember(name)
                    if not member.isfile():
                        raise ValueError("Docker image members must be regular files.")
                    clean.addfile(member, tar.extractfile(member))

    def sanitized_oci(self, tar, destination, expected_id):
        def metadata(name):
            member = tar.getmember(safe_member(name))
            if not member.isfile() or member.size > 10 * 1024**2:
                raise ValueError("Invalid OCI metadata member.")
            return json.load(tar.extractfile(member))

        index = metadata("index.json")
        roots = index.get("manifests", [])
        root = next((d for d in roots if d.get("digest") == expected_id), None)
        if root is None:
            raise ValueError("OCI archive does not contain the expected image identity.")
        selected = set()

        def visit(descriptor):
            digest = descriptor.get("digest", "")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or descriptor.get("urls"):
                raise ValueError("OCI resources must use local SHA-256 blobs, not external URLs.")
            name = "blobs/sha256/" + digest[7:]
            if name in selected:
                return
            selected.add(name)
            member = tar.getmember(name)
            if not member.isfile() or member.size != descriptor.get("size"):
                raise ValueError("Invalid OCI resource size or type.")
            with tar.extractfile(member) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest[7:]:
                    raise ValueError("OCI resource digest mismatch.")
            media = descriptor.get("mediaType", "")
            if "image.index" in media or "manifest.list" in media or "image.manifest" in media or "manifest.v2" in media:
                document = metadata(name)
                if any(k in document.get("annotations", {}) for k in ("io.containerd.image.name", "org.opencontainers.image.ref.name")):
                    raise ValueError("Nested OCI naming annotations are not supported in portable resources.")
                if "manifests" in document:
                    for child in document["manifests"]:
                        if child.get("annotations", {}).get("io.containerd.image.name") or child.get("annotations", {}).get("org.opencontainers.image.ref.name"):
                            raise ValueError("Nested OCI image aliases are not allowed.")
                        visit(child)
                else:
                    visit(document["config"])
                    for child in document["layers"]:
                        visit(child)
            elif "image.config" in media or "container.image" in media:
                config = metadata(name)
                self.service.material(config)
                public_image_config(config.get("config", {}), self.wb.redact)
            elif "layer" not in media and "rootfs" not in media and "in-toto" not in media:
                raise ValueError("Unsupported OCI resource media type.")

        visit(root)
        clean_index = {"schemaVersion": 2, "manifests": [{k: v for k, v in root.items() if k != "annotations"}]}
        with tarfile.open(destination, "w") as clean:
            for name, document in [("index.json", clean_index), ("oci-layout", {"imageLayoutVersion": "1.0.0"})]:
                data = json.dumps(document).encode()
                member = tarfile.TarInfo(name)
                member.size = len(data)
                clean.addfile(member, io.BytesIO(data))
            for name in sorted(selected):
                clean.addfile(tar.getmember(name), tar.extractfile(name))

    def import_bundle(self, operation, attempt):
        import docker
        value = operation["payload"]
        if value.get("trusted") is not True:
            raise ValueError("Confirm that this resource bundle comes from a trusted source.")
        path = self.path(value.get("filename", ""))
        report = self.inspect(value["filename"])
        if not report["ready"] or report["sha256"] != value.get("expectedSha256"):
            raise ValueError("Bundle changed, image tags conflict, or space is insufficient. Inspect again before importing.")
        # Work on a private snapshot so the operator cannot replace a transfer mid-import.
        snapshot = attempt / "bundle.zip"
        shutil.copyfile(path, snapshot)
        if digest_file(snapshot) != report["sha256"]:
            raise ValueError("Bundle changed while copying; nothing was imported.")
        manifest, _ = self.validate_archive(snapshot)
        content = attempt / "verified"
        content.mkdir()
        with zipfile.ZipFile(snapshot) as archive:
            for name in manifest["files"]:
                target = content / safe_member(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
        self.service.progress(operation, "Verifying baseline objects, frozen contexts and Docker image contents before importing.", 20)
        for source in manifest["sources"]:
            key = source_key(source["repository"], source["commit"])
            staging = attempt / "sources" / key
            read_pack(staging, content / source["path"])
            self.check_source(staging, source["commit"])
            actual = set(git(staging, "cat-file", "--batch-all-objects", "--batch-check=%(objectname)").decode().splitlines())
            if actual != source_objects(staging, source["commit"]):
                raise ValueError("Baseline pack contains objects outside its exact commit tree; history is not imported.")
        store = ArtifactStore(attempt / "artifacts")
        for key in manifest["contexts"]:
            shutil.copytree(content / "contexts" / key, store.path_for(key))
            context = store.verify(key)
            if (context["identity"]["repository"], context["identity"]["commit"]) not in {(s["repository"], s["commit"]) for s in manifest["sources"]}:
                raise ValueError("Context does not match a portable baseline.")
            for name in context["files"]:
                self.service.material((store.path_for(key) / "files" / name).read_text(encoding="utf-8"))
        for image in manifest["images"]:
            self.sanitized_image(content / image["path"], attempt / (image["id"][7:] + ".tar"), image["id"])
        if self.conflicts(manifest):
            raise ValueError("Image tags changed during validation. Inspect again; no image was loaded.")
        client = docker.from_env(timeout=3600)
        try:
            for index, image in enumerate(manifest["images"]):
                self.wb._check(None)
                self.service.progress(operation, f"Importing image {index + 1}/{len(manifest['images'])} by ID only.", 40 + int(index / len(manifest["images"]) * 40))
                try:
                    client.images.get(image["id"])
                except docker.errors.ImageNotFound:
                    with (attempt / (image["id"][7:] + ".tar")).open("rb") as stream:
                        client.images.load(stream)
                loaded = client.images.get(image["id"])
                for ref in image["references"]:
                    if "@sha256:" in ref:
                        aliases = self.service.root / "image-references"
                        aliases.mkdir(parents=True, exist_ok=True)
                        path = aliases / (hashlib.sha256(ref.encode()).hexdigest() + ".json")
                        receipt = {"reference": ref, "id": image["id"]}
                        try:
                            with path.open("x", encoding="utf-8") as stream:
                                json.dump(receipt, stream)
                        except FileExistsError:
                            if json.loads(safe_file(aliases, path.name).read_text(encoding="utf-8")) != receipt:
                                raise ValueError("Portable digest reference conflicts; existing mapping was not overwritten.")
                        continue
                    if ref.startswith("sha256:"):
                        continue
                    try:
                        if client.images.get(ref).id != loaded.id:
                            raise ValueError("Image tag changed concurrently. No existing tag was intentionally replaced.")
                    except docker.errors.ImageNotFound:
                        loaded.tag(ref)
        finally:
            client.close()
        for source in manifest["sources"]:
            key = source_key(source["repository"], source["commit"])
            target = self.wb.root / "sources" / key
            if target.is_symlink() or (target / ".git").is_symlink():
                raise ValueError("Source cache must not be a symbolic link.")
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(attempt / "sources" / key, target)
                git(target, "remote", "add", "origin", source["repository"])
            else:
                read_pack(target, content / source["path"])
        for key in manifest["contexts"]:
            target = self.wb.engine.artifacts.path_for(key)
            if self.wb.engine.artifacts.contains(key):
                existing = self.wb.engine.artifacts.verify(key)
                if existing != store.verify(key):
                    raise ValueError("Existing frozen context conflicts with bundle; not overwritten.")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.rename(store.path_for(key), target)
        for profile in manifest["profiles"]:
            self.service.profiles.save(json.loads((content / profile["path"]).read_text(encoding="utf-8")))
        dataset = manifest["dataset"]
        rows = json.loads((content / dataset["path"]).read_text(encoding="utf-8"))
        try:
            self.wb.catalog.verify(dataset["id"])
        except KeyError:
            self.wb.catalog.register(dataset["name"], "custom", rows)
        return {"datasetId": dataset["id"], "images": len(manifest["images"]), "contexts": len(manifest["contexts"]),
                "note": "Resources imported. Configure credentials separately and self-test before running an experiment."}

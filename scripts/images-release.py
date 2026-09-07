#!/usr/bin/env python3
"""Build, verify, import and publish offline application images (Python 3.10+, stdlib only)."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
import stat
from contextlib import contextmanager
from types import SimpleNamespace

MIB = 1024 * 1024
ASSET_LIMIT = 2 * 1024 * MIB
ROLES = ("ctxbench-worker", "ctxbench-egress-proxy", "agent-pi-image", "official-harness-image")
RUNTIME_IMAGES = dict(zip(ROLES, ("ctxbench/worker:0.1.0", "ctxbench/egress-proxy:0.1.0", "ctxbench/agent-pi:0.1.0", "ctxbench/official-harness:0.1.0")))
HELPER = "ctxbench-images.py"
COMPOSE = "ctxbench-images-compose.json"
GUIDE = "ctxbench-images-README.txt"
CHECKSUMS = "ctxbench-images-SHA256SUMS"
MANIFEST = "ctxbench-images-manifest.json"
INCOMPLETE = ".incomplete"
MAX_METADATA = MIB
PROGRESS_PREFIX = "CTXBENCH_IMPORT_PROGRESS "


class Progress:
    def __init__(self, enabled=False, prefix=PROGRESS_PREFIX):
        self.enabled, self.last, self.phase = enabled, 0.0, ""
        self.prefix = prefix

    def emit(self, phase, completed=0, total=0, force=False):
        now = time.monotonic()
        if self.enabled and (force or phase != self.phase or now - self.last >= .25 or completed == total):
            print(self.prefix + json.dumps({"phase": phase, "completed": completed, "total": total}), flush=True)
            self.last, self.phase = now, phase


class ZipMember:
    """Read-only, flat ZIP entries. Nothing is extracted or executed."""
    def __init__(self, bundle, name):
        self.bundle, self.name = bundle, name

    def exists(self):
        return self.name in self.bundle.entries

    def is_file(self):
        return self.exists()

    def is_symlink(self):
        return False  # Rejected when the ZIP directory is opened.

    def stat(self):
        return SimpleNamespace(st_size=self.bundle.entries[self.name].file_size)

    def open(self, mode="rb"):
        if mode != "rb":
            raise ValueError("Offline packages are read-only.")
        return self.bundle.archive.open(self.name)

    def read_text(self, encoding="utf-8"):
        if self.stat().st_size > MAX_METADATA:
            raise ValueError("Bundle metadata is too large.")
        with self.open() as stream:
            return stream.read(MAX_METADATA + 1).decode(encoding)


class ZipBundle:
    def __init__(self, archive):
        self.archive = archive
        infos = archive.infolist()
        if not 6 <= len(infos) <= 905:
            raise ValueError("Invalid ZIP file count; select the CTXBench offline images ZIP, not source code.")
        self.entries = {}
        for item in infos:
            mode = item.external_attr >> 16
            if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", item.filename)
                    or item.filename in self.entries or item.is_dir()
                    or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or item.flag_bits & 1 or item.compress_type != zipfile.ZIP_STORED
                    or item.file_size != item.compress_size or not 0 < item.file_size < ASSET_LIMIT):
                raise ValueError("Unsafe, duplicate, encrypted or compressed ZIP entry; use the original offline images ZIP.")
            self.entries[item.filename] = item

    def __truediv__(self, name):
        return ZipMember(self, name)


@contextmanager
def bundle_reader(source):
    if isinstance(source, ZipBundle):
        yield source
    elif source.is_file() and source.name == MANIFEST:
        yield source.parent  # Legacy split bundles: select the manifest file.
    elif source.is_dir():
        yield source
    else:
        with zipfile.ZipFile(source) as archive:
            yield ZipBundle(archive)


def metadata(path):
    if path.stat().st_size > MAX_METADATA:
        raise ValueError("Bundle metadata is too large.")
    return path.read_text(encoding="utf-8")


def single_file_name(version):
    return f"ctxbench-images-{version_name(version)}-linux-amd64.zip"


def bundle_files(manifest):
    return [MANIFEST, CHECKSUMS, *(i["name"] for i in manifest["supportFiles"]), *(i["name"] for i in manifest["parts"])]


def create_single_file(folder: Path, output: Path | None = None, *, github_limit=True, progress=None):
    progress = progress or Progress()
    manifest = verify(folder, progress)
    output = output or folder / single_file_name(manifest["version"])
    names = bundle_files(manifest)
    # ZIP_STORED avoids recompressing gzip data. Leave room for ZIP64 headers.
    total = sum(local_file(folder, name).stat().st_size for name in names)
    if github_limit and total + MIB >= ASSET_LIMIT:
        raise ValueError("Single ZIP exceeds GitHub's 2 GiB limit; use the verified legacy split bundle.")
    if output.exists():
        raise FileExistsError(output)
    temporary = output.with_name(output.name + ".incomplete")
    completed = 0
    progress.emit("package", 0, total, force=True)
    with temporary.open("xb") as sink, zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for name in names:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.file_size = local_file(folder, name).stat().st_size
            with local_file(folder, name).open("rb") as source, archive.open(info, "w", force_zip64=True) as target:
                for chunk in iter(lambda: source.read(MIB), b""):
                    target.write(chunk)
                    completed += len(chunk)
                    progress.emit("package", completed, total)
    # Verify the completed temporary ZIP before giving it the final filename.
    verify(temporary, progress)
    if output.exists():
        raise FileExistsError(output)
    temporary.rename(output)
    print(f"Single-file offline package: {output}")
    return output


def command(*args: str, capture: bool = False, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else ""


def version_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
        raise ValueError("Version must be 1-80 ASCII letters, digits, dots, underscores or hyphens.")
    return value


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else stream_digest(stream)


def stream_digest(stream) -> str:
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(MIB), b""):
        result.update(chunk)
    return result.hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def local_file(folder: Path, name: str) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("Bundle contains an unsafe filename.")
    path = folder / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or non-regular bundle file: {name}")
    return path


class SplitWriter:
    """Bounded-memory gzip sink; no intermediate uncompressed or combined archive."""

    def __init__(self, folder: Path, prefix: str, limit: int):
        self.folder, self.prefix, self.limit = folder, prefix, limit
        self.stream = None
        self.parts: list[dict] = []
        self.size = 0
        self.hasher = hashlib.sha256()

    def write(self, data: bytes) -> int:
        original = len(data)
        view = memoryview(data)
        while view:
            if self.stream is None:
                name = f"{self.prefix}.part{len(self.parts) + 1:04d}"
                if len(self.parts) >= 900:
                    raise ValueError("Bundle exceeds the supported part count.")
                self.stream = (self.folder / name).open("xb")
                self.size, self.hasher = 0, hashlib.sha256()
            count = min(len(view), self.limit - self.size)
            self.stream.write(view[:count])
            self.hasher.update(view[:count])
            self.size += count
            view = view[count:]
            if self.size == self.limit:
                self.close_part()
        return original

    def close_part(self) -> None:
        if self.stream is not None:
            self.stream.close()
            self.parts.append({"name": Path(self.stream.name).name, "bytes": self.size,
                               "sha256": self.hasher.hexdigest()})
            self.stream = None


def export_stream(references: list[str], folder: Path, prefix: str, limit: int, progress=None) -> list[dict]:
    progress = progress or Progress()
    sink = SplitWriter(folder, prefix, limit)
    process = subprocess.Popen(["docker", "image", "save", *references], stdout=subprocess.PIPE)
    try:
        completed = 0
        progress.emit("save", force=True)
        with gzip.GzipFile(filename="", mode="wb", fileobj=sink, compresslevel=6, mtime=0) as compressed:
            for chunk in iter(lambda: process.stdout.read(MIB), b""):
                compressed.write(chunk)
                completed += len(chunk)
                progress.emit("save", completed, 0)
        progress.emit("save", completed, 0, force=True)
        process.stdout.close()
        if process.wait() != 0:
            raise ValueError("Docker image save failed; partial output must not be published.")
        sink.close_part()
        return sink.parts
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        sink.close_part()


def source_state(root: Path) -> dict:
    revision = command("git", "rev-parse", "HEAD", cwd=root, capture=True).strip()
    dirty = bool(command("git", "status", "--porcelain", "--untracked-files=normal", cwd=root, capture=True).strip())
    return {"commit": revision, "dirty": dirty}


def compose_config(root: Path) -> dict:
    # Never serialize expanded credential values or a user's local .env file.
    return json.loads(command("docker", "compose", "--env-file", os.devnull,
                              "-f", str(root / "docker/compose.yaml"), "--profile", "build-only",
                              "config", "--no-interpolate", "--no-path-resolution", "--no-env-resolution",
                              "--format", "json", capture=True))


def offline_compose(config: dict) -> dict:
    services = {}
    for name in ROLES[:2]:
        service = config["services"][name]
        services[name] = {key: service[key] for key in
                          ("image", "restart", "environment", "ports", "depends_on", "volumes", "networks")
                          if key in service}
        services[name]["pull_policy"] = "never"
    return {"name": "ctxbench", "services": services, "networks": config["networks"]}


def pack(args) -> Path:
    root = args.root.resolve()
    version = version_name(args.version)
    if not 1 <= args.part_size_mib <= 1900:
        raise ValueError("Part size must be between 1 and 1900 MiB (below GitHub's 2 GiB asset limit).")
    source = source_state(root)
    if source["dirty"] and not args.allow_dirty:
        raise ValueError("Commit source changes first, or use --allow-dirty for a local, non-publishable test bundle.")
    config = compose_config(root)
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    (folder / INCOMPLETE).touch()
    references = {role: config["services"][role]["image"] for role in ROLES}
    export_refs = dict(references)
    if not args.skip_build:
        # Isolated tags: building a release must not replace tags used by the local desktop.
        suffix = f"bundle-{version.lower()}-{uuid.uuid4().hex[:12]}"
        export_refs = {role: ref.rsplit(":", 1)[0] + ":" + suffix for role, ref in references.items()}
        with tempfile.TemporaryDirectory(prefix="ctxbench-image-build-") as temporary:
            override = Path(temporary) / "compose.json"
            write_json(override, {"services": {role: {"image": ref, "platform": "linux/amd64"}
                                               for role, ref in export_refs.items()}})
            command("docker", "compose", "--env-file", os.devnull, "-f", str(root / "docker/compose.yaml"),
                    "-f", str(override), "--profile", "build-only", "build", *ROLES)
        if source_state(root) != source:
            raise ValueError("Source changed during build; retry from a stable checkout.")
    images = []
    for role in ROLES:
        ref = export_refs[role]
        inspected = json.loads(command("docker", "image", "inspect", ref, capture=True))[0]
        if (inspected["Os"], inspected["Architecture"]) != ("linux", "amd64"):
            raise ValueError(f"Expected linux/amd64 image for {role}.")
        images.append({"service": role, "archiveReference": ref, "runtimeReference": references[role],
                       "id": inspected["Id"], "sizeBytes": inspected["Size"]})
    parts = export_stream(list(export_refs.values()), folder,
                          f"ctxbench-images-{version}-linux-amd64.tar.gz", args.part_size_mib * MIB)
    write_bundle_metadata(folder, version, source, config, images, parts,
                          "existing-local-images" if args.skip_build else "source-build")
    print(f"Packed {len(images)} images, {len(parts)} part(s): {folder}")
    if sum(item["bytes"] for item in parts) + 2 * MIB < ASSET_LIMIT:
        create_single_file(folder)
    else:
        print("Single ZIP exceeds GitHub's limit; publishing will retain legacy split files.")
    return folder


def write_bundle_metadata(folder, version, source, config, images, parts, build_mode):
    shutil.copyfile(Path(__file__), folder / HELPER)
    write_json(folder / COMPOSE, offline_compose(config))
    (folder / GUIDE).write_text(
        "CTXBench offline application images / 离线应用镜像\n\n"
        "Recommended: select the ONE offline images ZIP in Desktop > Infrastructure > Offline installation.\n"
        "推荐：在桌面软件的“基础设施 → 离线安装”中选择一个镜像 ZIP，软件会自动校验、导入，无需解压。\n"
        "Use the matching desktop version. Older split bundles: select ctxbench-images-manifest.json.\n"
        "桌面与镜像版本须一致。旧分片包放齐全部文件，改选 ctxbench-images-manifest.json。\n"
        "Pause experiments and stop the worker first. Import never starts services automatically.\n"
        "先暂停实验并停止工作节点。导入不会自动启动服务。\n\n"
        "Advanced manual import from a trusted, extracted legacy folder:\n"
        "高级用法：在来源可信、文件齐全的旧包目录中手动导入：\n"
        "Keep ALL files together. Requires Python 3.10+ and Docker Engine + Compose in the selected WSL.\n"
        "所有附件放在同一目录；在桌面选定的 WSL 发行版中运行，需要 Python 3.10+、Docker 和 Compose。\n\n"
        f"sha256sum --check {CHECKSUMS}\n"
        f"python3 {HELPER} verify .\n"
        f"python3 {HELPER} import . --require-stopped\n"
        f"docker compose -f {COMPOSE} up -d --no-build --pull never ctxbench-worker\n\n"
        "Import does NOT start/restart services. Stop active experiments before changing runtime images.\n"
        "导入不会自动重启服务。切换运行镜像前，请先停止实验。\n"
        "Existing runtime tags are backed up under ctxbench/backup before replacement.\n"
        "已有运行标签会备份为 ctxbench/backup 标签；导入失败可重试，不自动清理镜像。\n"
        "Application images ONLY: task/evaluator images, datasets and repositories are NOT included.\n"
        "仅含四个应用镜像，不含用例/评分环境镜像、数据集、代码仓、运行结果或凭据。\n"
        "Checksums detect corruption, not publisher authenticity. Download from a trusted Release.\n"
        "校验用于发现损坏，不代替来源认证。API 域名/公司 CA/环境变量仍需按内网配置。\n",
        encoding="utf-8")
    if build_mode == "existing-local-images":
        with (folder / GUIDE).open("a", encoding="utf-8") as guide:
            guide.write("\nCUSTOM LOCAL IMAGES: not an official source-built release. Verify software compatibility and image contents before sharing.\n"
                        "本地自定义镜像：不是官方源码构建产物。分享前请确认软件兼容性并检查镜像层中的凭据、代码和数据。\n")
    manifest = {"schemaVersion": 1, "version": version, "platform": "linux/amd64", "source": source,
                "buildMode": build_mode,
                "archiveFormat": "docker-save+gzip", "images": images, "parts": parts,
                "supportFiles": [{"name": name, "bytes": (folder / name).stat().st_size,
                                  "sha256": digest(folder / name)} for name in (HELPER, COMPOSE, GUIDE)]}
    write_json(folder / MANIFEST, manifest)
    names = [MANIFEST, HELPER, COMPOSE, GUIDE, *(part["name"] for part in parts)]
    (folder / CHECKSUMS).write_text("".join(f"{digest(folder / name)}  {name}\n" for name in names), encoding="utf-8")
    (folder / INCOMPLETE).unlink()


def image_selections(values):
    selections = {}
    for value in values:
        role, separator, reference = value.partition("=")
        if not separator or role not in ROLES or role in selections or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}", reference):
            raise ValueError("Invalid export image selection; provide exactly one local image reference for each role.")
        selections[role] = reference
    if set(selections) != set(ROLES):
        raise ValueError("Invalid export image selection; all four application roles are required.")
    return selections


def check_image_credentials(inspected, *, allow_placeholders=False):
    for variable in (inspected.get("Config") or {}).get("Env", []) or []:
        key, _, value = variable.partition("=")
        if allow_placeholders and re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::[-?])?\}", value):
            continue
        sensitive_key = re.search(r"(?:^|_)(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE_KEY|AUTHORIZATION|CREDENTIALS?)$", key, re.I)
        credential_url = re.search(r"https?://[^/@\s]+:[^/@\s]+@", value)
        if value.strip() and (sensitive_key or credential_url):
            # Never print the key/value or include Config/Env/history in the manifest.
            raise ValueError("Image credentials detected. Rebuild without embedded credentials before exporting.")


def export_local(args):
    """Export customized images from an installed desktop; no Git checkout or network required."""
    version = version_name(args.version)
    selected = image_selections(args.image)
    output = args.output.absolute()
    temporary_zip = output.with_name(output.name + ".incomplete")
    if output.suffix.lower() != ".zip" or not output.parent.is_dir():
        raise ValueError("Invalid export path; choose a ZIP file in an existing directory.")
    if output.exists() or output.is_symlink() or temporary_zip.exists() or temporary_zip.is_symlink():
        raise ValueError("Export destination already exists. Choose a new filename; existing files are never overwritten.")
    progress = Progress(args.progress_json, "CTXBENCH_EXPORT_PROGRESS ")
    daemon = json.loads(command("docker", "info", "--format", "{{json .}}", capture=True))
    if daemon.get("OSType") != "linux" or daemon.get("Architecture") not in ("x86_64", "amd64"):
        raise ValueError("Image platform mismatch: a Linux amd64 Docker daemon is required.")
    config = compose_config(args.root.resolve())
    for service in offline_compose(config)["services"].values():
        environment = service.get("environment", {})
        variables = [f"{key}={value or ''}" for key, value in environment.items()] if isinstance(environment, dict) else environment
        check_image_credentials({"Config": {"Env": variables}}, allow_placeholders=True)
    for role in ROLES:
        config["services"][role]["image"] = RUNTIME_IMAGES[role]
    images = []
    suffix = "local-export-" + uuid.uuid4().hex
    progress.emit("inspect", 0, 4, force=True)
    for index, role in enumerate(ROLES, 1):
        inspected = json.loads(command("docker", "image", "inspect", selected[role], capture=True))[0]
        if (inspected.get("Os"), inspected.get("Architecture")) != ("linux", "amd64"):
            raise ValueError(f"Image platform mismatch for {role}: Linux amd64 is required.")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", inspected.get("Id", "")):
            raise ValueError("Invalid local image identity.")
        check_image_credentials(inspected)
        images.append({"service": role, "archiveReference": f"ctxbench/{role}:{suffix}",
                       "runtimeReference": RUNTIME_IMAGES[role], "id": inspected["Id"], "sizeBytes": inspected["Size"]})
        progress.emit("inspect", index, 4, force=True)
    tagged = []
    try:
        # Pin the inspected IDs, not mutable input tags. Production aliases are never changed.
        for item in images:
            command("docker", "image", "tag", item["id"], item["archiveReference"])
            tagged.append(item["archiveReference"])
        # TemporaryDirectory owns only this unique staging directory, not its parent.
        with tempfile.TemporaryDirectory(prefix=".ctxbench-export-", dir=output.parent) as staging:
            folder = Path(staging)
            (folder / INCOMPLETE).touch()
            parts = export_stream(tagged, folder, f"ctxbench-images-{version}-linux-amd64.tar.gz", 1900 * MIB, progress)
            write_bundle_metadata(folder, version, {"commit": None, "dirty": None}, config, images, parts, "existing-local-images")
            create_single_file(folder, output, github_limit=False, progress=progress)
    finally:
        for reference in tagged:
            try:
                command("docker", "image", "rm", reference, capture=True)
            except (OSError, subprocess.CalledProcessError):
                print(f"Temporary export tag retained: {reference}", flush=True)
    progress.emit("complete", 4, 4, force=True)
    print(f"Custom image ZIP exported: {output}", flush=True)
    return output


def verify(source: Path, progress=None, expected_version=None) -> dict:
    with bundle_reader(source) as folder:
        return _verify(folder, progress or Progress(), expected_version)


def _verify(folder, progress, expected_version=None) -> dict:
    if (folder / INCOMPLETE).exists():
        raise ValueError("Incomplete bundle; packing did not finish successfully.")
    manifest_path = local_file(folder, MANIFEST)
    checks = {}
    for line in metadata(local_file(folder, CHECKSUMS)).splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if not match or match[2] in checks:
            raise ValueError("Invalid or duplicate checksum entry.")
        checks[match[2]] = match[1]
    manifest_text = metadata(manifest_path)
    if checks.get(MANIFEST) != digest(manifest_path):
        raise ValueError("Manifest checksum mismatch.")
    manifest = json.loads(manifest_text)
    if not isinstance(manifest, dict):
        raise ValueError("Invalid bundle manifest: expected an object.")
    if manifest.get("schemaVersion") != 1 or manifest.get("platform") != "linux/amd64" or manifest.get("archiveFormat") != "docker-save+gzip":
        raise ValueError("Unsupported bundle version, platform or format.")
    version = version_name(manifest["version"])
    if expected_version and version.removeprefix("v") != expected_version.removeprefix("v"):
        raise ValueError(f"Version mismatch: package {version}; desktop {expected_version}. Download the matching offline package.")
    images = manifest["images"]
    if len(images) != 4 or {item["service"] for item in images} != set(ROLES):
        raise ValueError("Expected exactly the four application images.")
    for item in images:
        for field in ("archiveReference", "runtimeReference"):
            if not re.fullmatch(r"ctxbench/[a-z0-9-]+:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", item[field]):
                raise ValueError("Invalid application image reference.")
    parts = manifest["parts"]
    if not 1 <= len(parts) <= 900:
        raise ValueError("Invalid archive part count.")
    for index, part in enumerate(parts, 1):
        if part["name"] != f"ctxbench-images-{version}-linux-amd64.tar.gz.part{index:04d}":
            raise ValueError("Archive parts must be complete and ordered.")
    support = manifest["supportFiles"]
    if len(support) != 3 or {item["name"] for item in support} != {HELPER, COMPOSE, GUIDE}:
        raise ValueError("Missing or duplicate support file.")
    entries = [*parts, *support]
    if set(checks) != {MANIFEST, *(item["name"] for item in entries)}:
        raise ValueError("Checksum inventory does not match bundle inventory.")
    if isinstance(folder, ZipBundle) and set(folder.entries) != {CHECKSUMS, *checks}:
        raise ValueError("ZIP inventory does not match bundle inventory.")
    for item in entries:
        if type(item["bytes"]) is not int or not 0 < item["bytes"] < ASSET_LIMIT:
            raise ValueError("Invalid bundle file size.")
    total = sum(item["bytes"] for item in entries)
    completed = 0
    progress.emit("verify", 0, total, force=True)
    for item in entries:
        path = local_file(folder, item["name"])
        if not 0 < item["bytes"] < ASSET_LIMIT or path.stat().st_size != item["bytes"]:
            raise ValueError(f"Size mismatch or oversized asset: {path.name}")
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for data in iter(lambda: stream.read(MIB), b""):
                hasher.update(data)
                completed += len(data)
                progress.emit("verify", completed, total)
        if checks[path.name] != item["sha256"] or hasher.hexdigest() != item["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {path.name}")
    print(f"Verified {version}: {len(parts)} part(s), four application images.")
    return manifest


def import_bundle(source: Path, progress=None, expected_version=None, require_stopped=False) -> None:
    progress = progress or Progress()
    with bundle_reader(source) as folder:
        _import_bundle(folder, progress, expected_version, require_stopped)


def _import_bundle(folder, progress, expected_version, require_stopped):
    manifest = _verify(folder, progress, expected_version)  # All files verified before any Docker mutation.
    daemon = json.loads(command("docker", "info", "--format", "{{json .}}", capture=True))
    if daemon.get("OSType") != "linux" or daemon.get("Architecture") not in ("x86_64", "amd64"):
        raise ValueError("This bundle requires a Linux amd64 Docker daemon (the selected WSL distribution).")
    if require_stopped:
        for label in ("com.docker.compose.service=ctxbench-worker", "io.ctxbench.run"):
            if command("docker", "ps", "--filter", f"label={label}", "--format", "{{.ID}}", capture=True).strip():
                raise ValueError("Active CTXBench containers detected. Pause experiments and stop the worker before importing.")
    for item in manifest["images"]:
        # Back up aliases even for --skip-build archives, whose load itself may replace them.
        present = command("docker", "image", "ls", "--no-trunc", "-q",
                          item["runtimeReference"], capture=True).strip()
        if present:
            backup = "ctxbench/backup:" + present.replace(":", "-")
            command("docker", "image", "tag", item["runtimeReference"], backup)
            print(f"Preserved {item['runtimeReference']} as {backup}")
    process = subprocess.Popen(["docker", "image", "load"], stdin=subprocess.PIPE)
    try:
        total = sum(part["bytes"] for part in manifest["parts"])
        completed = 0
        progress.emit("load", 0, total, force=True)
        for part in manifest["parts"]:
            with (folder / part["name"]).open("rb") as stream:
                for data in iter(lambda: stream.read(MIB), b""):
                    process.stdin.write(data)
                    completed += len(data)
                    progress.emit("load", completed, total)
        process.stdin.close()
        progress.emit("unpack", force=True)
        if process.wait() != 0:
            raise ValueError("Docker load failed; services were not restarted. Fix the error and retry import.")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdin.close()
    # Image IDs can differ between classic and containerd image stores; archive hashes
    # are the portable integrity check. Resolve the loaded reference on this daemon.
    progress.emit("register", 0, 4, force=True)
    for item in manifest["images"]:
        command("docker", "image", "inspect", "--format", "{{.Id}}", item["archiveReference"], capture=True)
    for index, item in enumerate(manifest["images"], 1):
        command("docker", "image", "tag", item["archiveReference"], item["runtimeReference"])
        progress.emit("register", index, 4, force=True)
    progress.emit("complete", 4, 4, force=True)
    print("Imported. No containers were started/restarted; use the bundled offline Compose file when ready.")


def publish(folder: Path, repository: str, tag: str, single_file=False) -> None:
    zipped_source = folder.is_file()
    if zipped_source and folder.suffix.lower() != ".zip":
        raise ValueError("Publish requires a bundle folder or its single ZIP.")
    manifest = verify(folder)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repository must be OWNER/REPO.")
    if version_name(tag) != manifest["version"]:
        raise ValueError("Release tag must match the bundle version.")
    if manifest["source"]["dirty"] or manifest["buildMode"] != "source-build":
        raise ValueError("Only clean source-built bundles may be published; commit changes and rebuild first.")
    release = json.loads(command("gh", "api", f"repos/{repository}/releases/tags/{tag}", capture=True))
    commit = json.loads(command("gh", "api", f"repos/{repository}/commits/{tag}", capture=True))["sha"]
    if commit != manifest["source"]["commit"]:
        raise ValueError("Release tag commit differs from the bundle source commit.")
    if zipped_source:
        if folder.name != single_file_name(tag):
            raise ValueError("Restore the original versioned ZIP filename before publishing.")
        paths = [local_file(folder.parent, folder.name)]
    else:
        names = bundle_files(manifest)
        archive = folder / single_file_name(tag)
        if single_file and archive.is_file():
            if verify(archive) != manifest:
                raise ValueError("ZIP and folder manifests differ; rebuild the package.")
            names = [archive.name]
        paths = [local_file(folder, name) for name in names]
    existing = {asset["name"]: asset for asset in release["assets"]}
    pending = []
    for path in paths:
        name = path.name
        asset = existing.get(name)
        if asset:
            if asset.get("digest") != "sha256:" + digest(path) or asset["size"] != path.stat().st_size:
                raise ValueError(f"Release asset already exists with different/unverifiable content: {name}; not overwritten.")
        else:
            pending.append(path)
    for path in pending:
        command("gh", "release", "upload", tag, str(path), "--repo", repository)
    print(f"Published/verified {len(paths)} independent image assets on {repository} release {tag}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    packing = commands.add_parser("pack", help="Build four app images, gzip/split them and add offline tools.")
    packing.add_argument("--version", required=True)
    packing.add_argument("--output", type=Path, required=True, help="A new directory; existing directories are never overwritten.")
    packing.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    packing.add_argument("--part-size-mib", type=int, default=1900)
    packing.add_argument("--skip-build", action="store_true", help="Export existing Compose image tags; not publishable.")
    packing.add_argument("--allow-dirty", action="store_true", help="Allow a local test bundle; not publishable.")
    exporting = commands.add_parser("export-local", help="Export four customized local images to one ZIP without building or Git.")
    exporting.add_argument("--version", required=True, help="Matching desktop version, not an official release claim.")
    exporting.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    exporting.add_argument("--output", type=Path, required=True, help="A new ZIP path; never overwritten.")
    exporting.add_argument("--image", action="append", required=True, help="ROLE=LOCAL_IMAGE; specify each of the four roles once.")
    exporting.add_argument("--progress-json", action="store_true")
    wrapping = commands.add_parser("bundle", help="Wrap a verified legacy folder in one self-contained ZIP.")
    wrapping.add_argument("folder", type=Path)
    wrapping.add_argument("--output", type=Path)
    for name in ("verify", "import", "publish"):
        sub = commands.add_parser(name)
        sub.add_argument("folder", type=Path)
        if name == "publish":
            sub.add_argument("--repo", required=True, help="OWNER/REPO; existing Release required.")
            sub.add_argument("--tag", required=True)
            sub.add_argument("--single-file", action="store_true", help="Prefer one ZIP; fall back to split files above GitHub's limit.")
        if name == "import":
            sub.add_argument("--progress-json", action="store_true")
            sub.add_argument("--expected-version")
            sub.add_argument("--require-stopped", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "pack":
            pack(args)
        elif args.action == "export-local":
            export_local(args)
        elif args.action == "verify":
            verify(args.folder)
        elif args.action == "import":
            import_bundle(args.folder, Progress(args.progress_json), args.expected_version, args.require_stopped)
        elif args.action == "bundle":
            create_single_file(args.folder, args.output)
        else:
            publish(args.folder, args.repo, args.tag, args.single_file)
        return 0
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        print(f"Image bundle error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

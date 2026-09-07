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
import uuid

MIB = 1024 * 1024
ASSET_LIMIT = 2 * 1024 * MIB
ROLES = ("ctxbench-worker", "ctxbench-egress-proxy", "agent-pi-image", "official-harness-image")
HELPER = "ctxbench-images.py"
COMPOSE = "ctxbench-images-compose.json"
GUIDE = "ctxbench-images-README.txt"
CHECKSUMS = "ctxbench-images-SHA256SUMS"
MANIFEST = "ctxbench-images-manifest.json"
INCOMPLETE = ".incomplete"


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


def export_stream(references: list[str], folder: Path, prefix: str, limit: int) -> list[dict]:
    sink = SplitWriter(folder, prefix, limit)
    process = subprocess.Popen(["docker", "image", "save", *references], stdout=subprocess.PIPE)
    try:
        with gzip.GzipFile(filename="", mode="wb", fileobj=sink, compresslevel=6, mtime=0) as compressed:
            shutil.copyfileobj(process.stdout, compressed, length=MIB)
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
    shutil.copyfile(Path(__file__), folder / HELPER)
    write_json(folder / COMPOSE, offline_compose(config))
    (folder / GUIDE).write_text(
        "CTXBench offline application images / 离线应用镜像\n\n"
        "Keep ALL files together. Requires Python 3.10+ and Docker Engine + Compose in the selected WSL.\n"
        "所有附件放在同一目录；在桌面选定的 WSL 发行版中运行，需要 Python 3.10+、Docker 和 Compose。\n\n"
        f"sha256sum --check {CHECKSUMS}\n"
        f"python3 {HELPER} verify .\n"
        f"python3 {HELPER} import .\n"
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
    manifest = {"schemaVersion": 1, "version": version, "platform": "linux/amd64", "source": source,
                "buildMode": "existing-local-images" if args.skip_build else "source-build",
                "archiveFormat": "docker-save+gzip", "images": images, "parts": parts,
                "supportFiles": [{"name": name, "bytes": (folder / name).stat().st_size,
                                  "sha256": digest(folder / name)} for name in (HELPER, COMPOSE, GUIDE)]}
    write_json(folder / MANIFEST, manifest)
    names = [MANIFEST, HELPER, COMPOSE, GUIDE, *(part["name"] for part in parts)]
    (folder / CHECKSUMS).write_text("".join(f"{digest(folder / name)}  {name}\n" for name in names), encoding="utf-8")
    (folder / INCOMPLETE).unlink()
    print(f"Packed {len(images)} images, {len(parts)} part(s): {folder}")
    return folder


def verify(folder: Path) -> dict:
    if (folder / INCOMPLETE).exists():
        raise ValueError("Incomplete bundle; packing did not finish successfully.")
    manifest_path = local_file(folder, MANIFEST)
    checks = {}
    for line in local_file(folder, CHECKSUMS).read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if not match or match[2] in checks:
            raise ValueError("Invalid or duplicate checksum entry.")
        checks[match[2]] = match[1]
    if checks.get(MANIFEST) != digest(manifest_path):
        raise ValueError("Manifest checksum mismatch.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1 or manifest.get("platform") != "linux/amd64" or manifest.get("archiveFormat") != "docker-save+gzip":
        raise ValueError("Unsupported bundle version, platform or format.")
    version = version_name(manifest["version"])
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
    for item in entries:
        path = local_file(folder, item["name"])
        if not 0 < item["bytes"] < ASSET_LIMIT or path.stat().st_size != item["bytes"]:
            raise ValueError(f"Size mismatch or oversized asset: {path.name}")
        if checks[path.name] != item["sha256"] or digest(path) != item["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {path.name}")
    print(f"Verified {version}: {len(parts)} part(s), four application images.")
    return manifest


def import_bundle(folder: Path) -> None:
    manifest = verify(folder)  # All files verified before any Docker mutation.
    daemon = json.loads(command("docker", "info", "--format", "{{json .}}", capture=True))
    if daemon.get("OSType") != "linux" or daemon.get("Architecture") not in ("x86_64", "amd64"):
        raise ValueError("This bundle requires a Linux amd64 Docker daemon (the selected WSL distribution).")
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
        for part in manifest["parts"]:
            with (folder / part["name"]).open("rb") as stream:
                shutil.copyfileobj(stream, process.stdin, length=MIB)
        process.stdin.close()
        if process.wait() != 0:
            raise ValueError("Docker load failed; services were not restarted. Fix the error and retry import.")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdin.close()
    # Image IDs can differ between classic and containerd image stores; archive hashes
    # are the portable integrity check. Resolve the loaded reference on this daemon.
    for item in manifest["images"]:
        command("docker", "image", "inspect", "--format", "{{.Id}}", item["archiveReference"], capture=True)
    for item in manifest["images"]:
        command("docker", "image", "tag", item["archiveReference"], item["runtimeReference"])
    print("Imported. No containers were started/restarted; use the bundled offline Compose file when ready.")


def publish(folder: Path, repository: str, tag: str) -> None:
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
    names = [MANIFEST, CHECKSUMS, *(item["name"] for item in manifest["supportFiles"]),
             *(item["name"] for item in manifest["parts"])]
    existing = {asset["name"]: asset for asset in release["assets"]}
    pending = []
    for name in names:
        path = local_file(folder, name)
        asset = existing.get(name)
        if asset:
            if asset.get("digest") != "sha256:" + digest(path) or asset["size"] != path.stat().st_size:
                raise ValueError(f"Release asset already exists with different/unverifiable content: {name}; not overwritten.")
        else:
            pending.append(path)
    for path in pending:
        command("gh", "release", "upload", tag, str(path), "--repo", repository)
    print(f"Published/verified {len(names)} independent image assets on {repository} release {tag}.")


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
    for name in ("verify", "import", "publish"):
        sub = commands.add_parser(name)
        sub.add_argument("folder", type=Path)
        if name == "publish":
            sub.add_argument("--repo", required=True, help="OWNER/REPO; existing Release required.")
            sub.add_argument("--tag", required=True)
    args = parser.parse_args()
    try:
        if args.action == "pack":
            pack(args)
        elif args.action == "verify":
            verify(args.folder)
        elif args.action == "import":
            import_bundle(args.folder)
        else:
            publish(args.folder, args.repo, args.tag)
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Image bundle error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

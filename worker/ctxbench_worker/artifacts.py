from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from .models import ModelConfig
from .safe_files import safe_file


@dataclass(frozen=True)
class ContextIdentity:
    repository: str
    commit: str
    capability: str
    skill_version: str
    generation_prompt_hash: str
    builder: ModelConfig

    def key(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def safe_relative_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or not path.parts or ":" in normalized or any(part.lower() == ".git" for part in path.parts):
        raise ValueError(f"Unsafe artifact path: {value}")
    return path


def is_context_owned(path_value: str, declared_paths: tuple[str, ...] = ()) -> bool:
    path = safe_relative_path(path_value)
    lowered = path.as_posix().lower()
    name = path.name.lower()
    conventional = (
        name in {"agents.md", "claude.md"}
        or lowered == ".github/copilot-instructions.md"
        or lowered.startswith(".ctx/")
    )
    declared = any(path.as_posix() == safe_relative_path(item).as_posix() for item in declared_paths)
    return conventional or declared


class ArtifactStore:
    """Content-addressed context storage with atomic publication."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise ValueError("Artifact keys must be lowercase SHA-256 values.")
        target = self.root / key[:2] / key
        if target.is_symlink() or target.parent.is_symlink():
            raise ValueError("Artifact directories must not be symbolic links.")
        return target

    def contains(self, key: str) -> bool:
        target = self.path_for(key)
        return target.is_dir() and (target / "manifest.json").is_file()

    def publish(
        self,
        identity: ContextIdentity,
        files: Mapping[str, bytes],
        provenance: Mapping[str, object],
        declared_paths: tuple[str, ...] = (),
    ) -> Path:
        key = identity.key()
        target = self.path_for(key)
        if self.contains(key):
            self.verify(key)
            return target

        if not files:
            raise ValueError("Context package must contain at least one file.")

        invalid = [path for path in files if not is_context_owned(path, declared_paths)]
        if invalid:
            raise ValueError(f"Context package attempted to own non-context files: {', '.join(invalid)}")

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{key}.", dir=target.parent))
        try:
            payload = staging / "files"
            hashes: dict[str, str] = {}
            for name, content in sorted(files.items()):
                relative = safe_relative_path(name)
                destination = payload.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                hashes[relative.as_posix()] = hashlib.sha256(content).hexdigest()

            manifest = {
                "schemaVersion": 1,
                "key": key,
                "identity": asdict(identity),
                "files": hashes,
                "provenance": dict(provenance),
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
            try:
                os.replace(staging, target)
            except FileExistsError:
                shutil.rmtree(staging)
            return target
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def verify(self, key: str) -> dict[str, object]:
        target = self.path_for(key)
        manifest = json.loads(safe_file(target, 'manifest.json', limit=2 * 1024 * 1024).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("key") != key or not isinstance(manifest.get("files"), dict) or not manifest["files"] or not isinstance(manifest.get("identity"), dict):
            raise ValueError("Invalid context manifest.")
        identity_hash = hashlib.sha256(json.dumps(manifest["identity"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if identity_hash != key:
            raise ValueError("Context identity was modified.")
        actual = {path.relative_to(target / 'files').as_posix() for path in (target / 'files').rglob('*') if path.is_file() or path.is_symlink()}
        if actual != set(manifest['files']):
            raise ValueError('Context file inventory was modified.')
        for name, digest in manifest["files"].items():
            path = safe_file(target, 'files/' + safe_relative_path(name).as_posix(), limit=20 * 1024 * 1024)
            if path.is_symlink() or not path.is_file() or target not in path.resolve().parents:
                raise ValueError(f"Missing or unsafe context file: {name}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Context artifact was modified: {name}")
        return manifest

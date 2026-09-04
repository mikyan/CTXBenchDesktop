from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .artifacts import is_context_owned, safe_relative_path

ContextArm = Literal["none", "skill-generated", "manual", "developer-historical"]


@dataclass(frozen=True)
class Transformation:
    operation: Literal["remove", "overlay", "retain"]
    path: str


def _contained(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Workspace path escapes root: {candidate}")
    return resolved


def discover_context_files(workspace: str | Path) -> list[Path]:
    root = Path(workspace).resolve()
    result = [
        path
        for name in ("AGENTS.md", "CLAUDE.md")
        for path in root.rglob(name)
        if path.is_file() or path.is_symlink()
    ]
    copilot = root / ".github" / "copilot-instructions.md"
    if copilot.exists() or copilot.is_symlink():
        result.append(copilot)
    context_folder = root / ".ctx"
    if context_folder.exists():
        result.extend(path for path in context_folder.rglob("*") if path.is_file() or path.is_symlink())
    return sorted(set(result))


def prepare_context(
    workspace: str | Path,
    arm: ContextArm,
    artifact_files: str | Path | None = None,
    declared_paths: tuple[str, ...] = (),
) -> list[Transformation]:
    """Prepare one arm while keeping all task and solver inputs outside this interface."""
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise ValueError("Workspace must be an existing directory.")
    if arm == "developer-historical" and artifact_files is not None:
        raise ValueError("Developer-historical uses only context already present at the baseline commit.")
    if arm in {"skill-generated", "manual"} and artifact_files is None:
        raise ValueError(f"{arm} requires a frozen context artifact.")

    transformations: list[Transformation] = []
    existing = discover_context_files(root)
    if arm == "developer-historical":
        return [Transformation("retain", path.relative_to(root).as_posix()) for path in existing]

    for path in existing:
        target = _contained(root, path)
        relative = target.relative_to(root).as_posix()
        target.unlink(missing_ok=True)
        transformations.append(Transformation("remove", relative))
    context_folder = root / ".ctx"
    if context_folder.exists() and not any(context_folder.iterdir()):
        context_folder.rmdir()

    if artifact_files is None:
        return transformations

    source_root = Path(artifact_files).resolve()
    if not source_root.is_dir():
        raise ValueError("Artifact files directory does not exist.")
    for source in sorted(path for path in source_root.rglob("*") if path.is_file() or path.is_symlink()):
        if source.is_symlink():
            raise ValueError(f"Context artifacts cannot contain symbolic links: {source}")
        relative = source.relative_to(source_root).as_posix()
        if not is_context_owned(relative, declared_paths):
            raise ValueError(f"Artifact owns a non-context file: {relative}")
        safe = safe_relative_path(relative)
        target = _contained(root, root.joinpath(*safe.parts))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        transformations.append(Transformation("overlay", relative))
    return transformations

"""Boundary checks before the privileged worker reads agent-owned files."""
from pathlib import Path


def safe_file(root: Path, relative: str, *, limit: int = 64 * 1024 * 1024) -> Path:
    root = root.absolute()
    candidate = root / relative
    try:
        parts = candidate.relative_to(root).parts
    except ValueError as error:
        raise ValueError("Output path escapes its run directory.") from error
    if not parts or any(part in {"..", "."} for part in parts):
        raise ValueError("Unsafe output path.")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Agent output must not contain symbolic links.")
    if root.resolve() not in candidate.resolve().parents:
        raise ValueError("Output path escapes its run directory.")
    if candidate.exists() and (not candidate.is_file() or candidate.stat().st_size > limit):
        raise ValueError("Agent output is not a regular file or exceeds the size limit.")
    return candidate

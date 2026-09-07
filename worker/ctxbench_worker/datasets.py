from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from .artifacts import safe_relative_path


@dataclass(frozen=True)
class TaskRecord:
    id: str
    repository: str
    base_commit: str
    prompt: str
    image: str | None
    build: Mapping[str, Any] | None
    test_command: tuple[str, ...]
    hidden_test_patch: str | None = None
    gold_patch: str | None = None
    source: str = "custom"

    def solver_payload(self) -> dict[str, object]:
        """Return the complete solver-visible task. Evaluator-only fields stay absent by construction."""
        return {
            "id": self.id,
            "repository": self.repository,
            "baseCommit": self.base_commit,
            "prompt": self.prompt,
        }


def _repository(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.scheme not in {"https", "ssh", "git"} and not Path(value).is_absolute():
        raise ValueError(f"Unsupported repository URL scheme: {parsed.scheme}")
    if not value.strip():
        raise ValueError("Repository is required.")
    return value


def custom_task(value: Mapping[str, Any]) -> TaskRecord:
    if set(value) - {"id", "repository", "baseCommit", "prompt", "test", "image", "build", "goldPatch", "metadata"}:
        raise ValueError("Custom task contains unsupported fields; follow the custom task schema.")
    if "metadata" in value and not isinstance(value["metadata"], Mapping):
        raise ValueError("Custom task metadata must be an object.")
    required = ("id", "repository", "baseCommit", "prompt", "test")
    missing = [key for key in required if not value.get(key)]
    if missing:
        raise ValueError(f"Custom task is missing required fields: {', '.join(missing)}")
    for key in ("id", "repository", "baseCommit", "prompt"):
        if not isinstance(value[key], str) or not value[key].strip() or "\0" in value[key]:
            raise ValueError(f"Custom task {key} must be nonempty text without NUL characters.")
    test = value["test"]
    if not isinstance(test, Mapping) or not isinstance(test.get("command"), list):
        raise ValueError("Custom task test.command must be an argument array.")
    if set(test) - {"command", "hiddenPatch"}:
        raise ValueError("Custom task test contains unsupported fields.")
    command = test["command"]
    if not command or not all(isinstance(arg, str) and "\0" not in arg for arg in command) or not command[0].strip():
        raise ValueError("Custom task test.command must be a nonempty string argument array without NUL characters.")
    for patch in (test.get("hiddenPatch"), value.get("goldPatch")):
        if patch is not None and (not isinstance(patch, str) or "\0" in patch):
            raise ValueError("Evaluator patches must be text without NUL characters.")
    if not value.get("image") and not value.get("build"):
        raise ValueError("Custom tasks require image or an explicit build recipe.")
    if "image" in value and (not isinstance(value["image"], str) or not value["image"].strip() or any(c.isspace() or c == "\0" for c in value["image"])):
        raise ValueError("Provide a test image reference without whitespace.")
    if "build" in value:
        build = value["build"]
        if not isinstance(build, Mapping) or not isinstance(build.get("dockerfile"), str) or build["dockerfile"].strip() in {"", "."}:
            raise ValueError("Custom task build requires a relative Dockerfile path.")
        if set(build) - {"dockerfile", "context", "args"}:
            raise ValueError("Custom task build contains unsupported fields.")
        for path in (build["dockerfile"], build.get("context", ".")):
            if not isinstance(path, str) or "\0" in path or "\\" in path or not path:
                raise ValueError("Build paths must stay inside the baseline repository; use Linux relative paths.")
            if path != ".":
                safe_relative_path(path)
        args = build.get("args", {})
        if not isinstance(args, Mapping) or not all(isinstance(k, str) and isinstance(v, str) and "\0" not in k + v for k, v in args.items()):
            raise ValueError("Build arguments must be a JSON object with string values.")
    return TaskRecord(
        id=str(value["id"]),
        repository=_repository(str(value["repository"])),
        base_commit=str(value["baseCommit"]),
        prompt=str(value["prompt"]),
        image=str(value["image"]) if value.get("image") else None,
        build=value.get("build"),
        test_command=tuple(str(item) for item in test["command"]),
        hidden_test_patch=test.get("hiddenPatch"),
        gold_patch=value.get("goldPatch"),
    )


def load_jsonl(path: str | Path) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON on line {number}: {error.msg}") from error
        if not isinstance(value, dict):
            raise ValueError(f"Task on line {number} must be an object.")
        result.append(value)
    return result


def load_custom_manifest(path: str | Path) -> list[TaskRecord]:
    return [custom_task(value) for value in load_jsonl(path)]


def import_swebench(rows: Iterable[Mapping[str, Any]]) -> list[TaskRecord]:
    result: list[TaskRecord] = []
    for row in rows:
        repository = str(row["repo"])
        result.append(
            TaskRecord(
                id=str(row["instance_id"]),
                repository=f"https://github.com/{repository}.git",
                base_commit=str(row["base_commit"]),
                prompt=str(row["problem_statement"]),
                image=str(row["image_name"]) if row.get("image_name") else None,
                build=None,
                test_command=("python", "-m", "swebench.harness.run_evaluation"),
                hidden_test_patch=str(row["test_patch"]) if row.get("test_patch") else None,
                gold_patch=str(row["patch"]) if row.get("patch") else None,
                source="swebench",
            )
        )
    return result


def import_agentbench(rows: Iterable[Mapping[str, Any]]) -> list[TaskRecord]:
    result: list[TaskRecord] = []
    for row in rows:
        repository = str(row.get("base_repo") or row.get("repo") or row.get("repository"))
        task_id = str(row.get("instance_id") or row.get("id"))
        result.append(
            TaskRecord(
                id=task_id,
                repository=f"https://github.com/{repository}.git" if "://" not in repository else repository,
                base_commit=str(row.get("base_sha") or row.get("base_commit") or row.get("baseCommit")),
                prompt=str(row.get("problem_description") or row.get("problem_statement") or row.get("task")),
                image=str(row.get("docker_image") or row.get("image")) if row.get("docker_image") or row.get("image") else None,
                build=row.get("build"),
                test_command=tuple(row.get("test_command") or ("pytest", "-q")),
                hidden_test_patch=str(row["test_patch"]) if row.get("test_patch") else None,
                gold_patch=str(row.get("clean_pr_patch") or row.get("patch")) if row.get("clean_pr_patch") or row.get("patch") else None,
                source="agentbench",
            )
        )
    return result

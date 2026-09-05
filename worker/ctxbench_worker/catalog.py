"""Dataset registration freezes source bytes and separates public task metadata."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

from .database import Database, utc_now
from .datasets import TaskRecord, custom_task, import_agentbench, import_swebench


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Catalog:
    def __init__(self, root: Path, database: Database):
        self.root, self.database = root, database
        (root / "datasets").mkdir(parents=True, exist_ok=True)

    def register(self, name: str, benchmark: str, rows: list[dict]) -> dict:
        if benchmark not in {"custom", "swebench", "ctxbench"} or not name.strip() or not rows:
            raise ValueError("A dataset name, benchmark kind, and nonempty task set are required.")
        if len(rows) > 10000:
            raise ValueError("Import at most 10,000 tasks per dataset.")
        tasks = ([custom_task(row) for row in rows] if benchmark == "custom" else
                 import_swebench(rows) if benchmark == "swebench" else import_agentbench(rows))
        if len({task.id for task in tasks}) != len(tasks):
            raise ValueError("Dataset task IDs must be unique.")
        for task in tasks:
            if not task.id or task.id == "None" or not task.prompt or task.prompt == "None":
                raise ValueError("Every task must have an ID and prompt.")
            if not re.fullmatch(r"[0-9a-fA-F]{40}", task.base_commit):
                raise ValueError(f"Task {task.id} must pin a full 40-character commit.")
            parsed = urlparse(task.repository)
            if parsed.username or parsed.password:
                raise ValueError("Repository URLs must not embed credentials.")
            if task.source == "custom" and not task.test_command:
                raise ValueError("Custom tasks need a nonempty test command.")
        key = fingerprint({"benchmark": benchmark, "rows": rows})
        path = self.root / "datasets" / f"{key}.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        record = {"id": key, "name": name, "benchmark": benchmark, "count": len(tasks),
                  "createdAt": utc_now(), "path": str(path), "tasks": [asdict(task) for task in tasks]}
        self.database.put_document("datasets", key, record)
        return self.public(record)

    @staticmethod
    def public(record: dict) -> dict:
        return {key: record[key] for key in ("id", "name", "benchmark", "count", "createdAt")}

    def list(self) -> list[dict]:
        return [self.public(item) for item in self.database.list_documents("datasets")]

    def tasks(self, dataset: str) -> list[dict]:
        return [{"id": task["id"], "repository": task["repository"], "baseCommit": task["base_commit"],
                 "prompt": task["prompt"], "image": task["image"]}
                for task in self.database.get_document("datasets", dataset)["tasks"]]

    def task(self, dataset: str, task_id: str) -> TaskRecord:
        for task in self.database.get_document("datasets", dataset)["tasks"]:
            if task["id"] == task_id:
                return TaskRecord(**{**task, "test_command": tuple(task["test_command"])})
        raise ValueError(f"Task is not in the imported dataset: {task_id}")

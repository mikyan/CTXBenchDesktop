"""Dataset registration freezes source bytes and separates public task metadata."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

from .database import Database, utc_now
from .datasets import TaskRecord, custom_task, import_agentbench, import_swebench, task_document
from .safe_files import safe_file


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Catalog:
    def __init__(self, root: Path, database: Database):
        self.root, self.database = root, database
        (root / "datasets").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate(name: str, benchmark: str, rows: list[dict]) -> list[TaskRecord]:
        """Validate exactly as registration does, without writes or runtime I/O."""
        if not isinstance(name, str) or not isinstance(benchmark, str) or benchmark not in {"custom", "swebench", "ctxbench"} or not name.strip() or not rows:
            raise ValueError("A dataset name, benchmark kind, and nonempty task set are required.")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Dataset rows must be an array of task records.")
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
            if task.source == "custom" and parsed.scheme and (parsed.query or parsed.fragment):
                raise ValueError("Repository URLs must not contain query strings or fragments.")
            if task.source == "custom" and not task.test_command and not task.ci:
                raise ValueError("Custom tasks need a nonempty test command.")
        return tasks

    def register(self, name: str, benchmark: str, rows: list[dict], *, internal: bool = False) -> dict:
        tasks = self.validate(name, benchmark, rows)
        key = fingerprint({"benchmark": benchmark, "rows": rows})
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            existing = connection.execute("SELECT 1 FROM documents WHERE kind='datasets' AND id=?", (key,)).fetchone()
            if existing:
                record = self.verify(key)
                if not internal:
                    connection.execute("DELETE FROM documents WHERE kind='deletedLibrarySources' AND id=?", ('set-' + key,))
                if not internal and record.pop('internalSnapshot', False):
                    connection.execute("UPDATE documents SET payload_json=? WHERE kind='datasets' AND id=?", (json.dumps(record), key))
                return self.public(record)
            path = self.root / 'datasets' / f'{key}.json'
            temporary = None
            try:
                with NamedTemporaryFile(mode='w', encoding='utf-8', prefix='snapshot-', suffix='.tmp', dir=path.parent, delete=False) as output:
                    temporary = Path(output.name)
                    json.dump(rows, output)
                temporary.replace(path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            record = {'id': key, 'name': name, 'benchmark': benchmark, 'count': len(tasks),
                      'createdAt': utc_now(), 'path': str(path), 'tasks': [task_document(task) for task in tasks]}
            if internal:
                record['internalSnapshot'] = True
            connection.execute('INSERT INTO documents VALUES (?, ?, ?)', ('datasets', key, json.dumps(record)))
        return self.public(record)

    @staticmethod
    def public(record: dict) -> dict:
        return {key: record[key] for key in ("id", "name", "benchmark", "count", "createdAt")}

    def list(self) -> list[dict]:
        records = self.database.list_document_summaries('datasets', ('id', 'name', 'benchmark', 'count', 'createdAt', 'internalSnapshot'))
        deleted = {item['id'] for item in self.database.list_documents('deletedLibrarySources')}
        return [{k: v for k, v in record.items() if k != 'internalSnapshot'} for record in records if not record['internalSnapshot'] and 'set-' + record['id'] not in deleted]

    def tasks(self, dataset: str) -> list[dict]:
        return [{"id": task["id"], "repository": task["repository"], "baseCommit": task["base_commit"],
                 "prompt": task["prompt"], "image": task["image"],
                 **({'customAgentImage': task['agent']['image']} if task.get('agent') else {})}
                for task in self.verify(dataset)["tasks"]]

    def verify(self, dataset: str) -> dict:
        record = self.database.get_document('datasets', dataset)
        path = safe_file(self.root / 'datasets', f'{dataset}.json')
        rows = json.loads(path.read_text(encoding='utf-8'))
        if fingerprint({'benchmark': record['benchmark'], 'rows': rows}) != dataset:
            raise ValueError('Frozen dataset contents have changed; import as a new dataset instead.')
        expected_tasks = json.loads(json.dumps([task_document(task) for task in self.validate(record['name'], record['benchmark'], rows)]))
        if record['tasks'] != expected_tasks or record['id'] != dataset or record['count'] != len(expected_tasks) or Path(record['path']).resolve() != path.resolve():
            raise ValueError('Frozen dataset metadata has changed; restore the original snapshot before running.')
        return record

    def task(self, dataset: str, task_id: str) -> TaskRecord:
        try:
            return self.index(dataset)[task_id]
        except KeyError as error:
            raise ValueError(f"Task is not in the imported dataset: {task_id}") from error

    def index(self, dataset: str) -> dict[str, TaskRecord]:
        return {task['id']: TaskRecord(**{**task, 'test_command': tuple(task['test_command'])}) for task in self.verify(dataset)['tasks']}

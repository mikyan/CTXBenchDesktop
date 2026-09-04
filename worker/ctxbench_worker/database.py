from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .models import ExperimentSpec, PlannedRun

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    dataset TEXT NOT NULL,
    status TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    completed_runs INTEGER NOT NULL DEFAULT 0,
    total_runs INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    pair_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    repeat INTEGER NOT NULL,
    arm TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_queue ON runs(status, ordinal);
CREATE INDEX IF NOT EXISTS runs_pair ON runs(pair_id);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """Durable worker state; callers only see transactional operations."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    def create_experiment(
        self, experiment_id: str, spec: ExperimentSpec, runs: list[PlannedRun]
    ) -> dict[str, object]:
        timestamp = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO experiments
                   (id, name, benchmark, dataset, status, spec_json, total_runs, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'preparing', ?, ?, ?, ?)""",
                (
                    experiment_id,
                    spec.name,
                    spec.benchmark,
                    spec.dataset,
                    json.dumps(asdict(spec), separators=(",", ":")),
                    len(runs),
                    timestamp,
                    timestamp,
                ),
            )
            connection.executemany(
                """INSERT INTO runs
                   (id, experiment_id, pair_id, task_id, repeat, arm, ordinal, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run.id,
                        run.experiment_id,
                        run.pair_id,
                        run.task_id,
                        run.repeat,
                        run.arm,
                        run.ordinal,
                        run.status,
                        timestamp,
                    )
                    for run in runs
                ],
            )
        return self.get_experiment(experiment_id)

    def get_experiment(self, experiment_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        return self._experiment_record(row)

    def list_experiments(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM experiments ORDER BY created_at DESC").fetchall()
        return [self._experiment_record(row) for row in rows]

    def recover_interrupted_jobs(self) -> int:
        """Return in-flight jobs to the durable queue after a worker restart."""
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status = 'queued', updated_at = ? WHERE status = 'running'",
                (utc_now(),),
            )
            return cursor.rowcount

    def enqueue_job(self, kind: str, payload: dict[str, object]) -> dict[str, object]:
        job_id = f"job-{uuid.uuid4().hex[:16]}"
        timestamp = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO jobs (id, kind, status, payload_json, created_at, updated_at)
                   VALUES (?, ?, 'queued', ?, ?, ?)""",
                (job_id, kind, json.dumps(payload, separators=(",", ":")), timestamp, timestamp),
            )
        return self.get_job(job_id)

    def claim_job(self) -> dict[str, object] | None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            timestamp = utc_now()
            connection.execute(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?",
                (timestamp, row["id"]),
            )
            value = dict(row)
            value["status"] = "running"
            value["attempts"] += 1
            value["updated_at"] = timestamp
            return self._job_record(value)

    def finish_job(self, job_id: str, status: str, result: dict[str, object]) -> dict[str, object]:
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("Invalid terminal job status.")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                (status, json.dumps(result, separators=(",", ":")), utc_now(), job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._job_record(dict(row))

    @staticmethod
    def _job_record(row: dict[str, object]) -> dict[str, object]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "status": row["status"],
            "payload": json.loads(str(row["payload_json"])),
            "result": json.loads(str(row["result_json"])) if row.get("result_json") else None,
            "attempts": row["attempts"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _experiment_record(row: sqlite3.Row) -> dict[str, object]:
        spec = json.loads(row["spec_json"])
        return {
            "id": row["id"],
            "name": row["name"],
            "benchmark": row["benchmark"],
            "dataset": row["dataset"],
            "status": row["status"],
            "arms": spec["arms"],
            "repeats": spec["repeats"],
            "tasks": len(spec["task_ids"]),
            "completedRuns": row["completed_runs"],
            "totalRuns": row["total_runs"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "model": {
                "provider": spec["model"]["provider"],
                "model": spec["model"]["model"],
                "thinking": spec["model"]["thinking"],
                "maxTokens": spec["model"]["max_tokens"],
                **({"temperature": spec["model"]["temperature"]} if spec["model"].get("temperature") is not None else {}),
            },
            "profiles": {
                role: {
                    "provider": profile["provider"],
                    "model": profile["model"],
                    "thinking": profile["thinking"],
                    "maxTokens": profile["max_tokens"],
                    **({"temperature": profile["temperature"]} if profile.get("temperature") is not None else {}),
                }
                for role, profile in spec.get("profiles", {}).items()
            },
            "agentImage": spec["agent_image"],
            "resources": {
                "cpus": spec["resources"]["cpus"],
                "memoryGb": spec["resources"]["memory_gb"],
                "timeoutMinutes": spec["resources"]["timeout_minutes"],
                "network": spec["resources"]["network"],
            },
            "seed": spec["seed"],
        }

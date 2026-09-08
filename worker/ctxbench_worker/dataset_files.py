"""Bounded local-file preview/confirmation; source rows never enter public previews."""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

MAX_DATASET_BYTES = 32 * 1024 * 1024
MAX_CACHE_BYTES = 128 * 1024 * 1024


class DatasetFiles:
    def __init__(self, workbench, protect):
        self.workbench, self.protect = workbench, protect
        self.pending = {}
        self.lock = threading.RLock()

    def expire(self):
        for key in list(self.pending):
            if self.pending[key]["expires"] < time.monotonic():
                del self.pending[key]

    def preview(self, data: bytes, filename: str, name: str, benchmark: str):
        if not 0 < len(data) <= MAX_DATASET_BYTES:
            raise ValueError("Choose a nonempty dataset file no larger than 32 MiB.")
        # The filename is display-only, never a destination path or a command argument.
        if not filename or len(filename) > 255 or any(char in filename for char in ("/", "\\", "\x00", "\r", "\n")):
            raise ValueError("Choose a local dataset file, not a directory or server path.")
        self.protect({"name": name, "filename": filename, "benchmark": benchmark})
        suffix = Path(filename).suffix.lower()
        if suffix not in {".parquet", ".json", ".jsonl"}:
            raise ValueError("Select a Parquet, JSON or JSONL dataset file; ZIP and EXE files are not datasets.")
        if benchmark not in {"swebench", "ctxbench", "custom"}:
            raise ValueError("Select the matching dataset source.")
        if suffix == ".parquet":
            if len(data) < 12 or data[:4] != b"PAR1" or data[-4:] != b"PAR1":
                raise ValueError("This is not a complete Parquet file. Download the actual file, not a web page or Git LFS pointer.")
            with TemporaryDirectory(prefix="upload-", dir=self.workbench.root / "datasets") as folder:
                source = Path(folder) / "source.parquet"
                source.write_bytes(data)
                try:
                    rows = self.workbench.runtime.import_parquet(source)
                except Exception as error:
                    # Container logs may contain source rows; never echo them as upload errors.
                    raise ValueError("Parquet could not be read. Check that the local evaluation service has the official harness image, then retry with an intact file.") from error
        else:
            try:
                text = data.decode("utf-8-sig")
                rows = json.loads(text) if suffix == ".json" else [json.loads(line) for line in text.splitlines() if line.strip()]
            except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
                raise ValueError("The file is not valid UTF-8 JSON / JSONL. Changing a file extension does not convert its format.") from error
            if isinstance(rows, dict) and isinstance(rows.get("rows"), list):
                if rows.get("benchmark", benchmark) != benchmark:
                    raise ValueError("Select the matching dataset source.")
                rows = rows["rows"]
        self.protect({"rows": rows})
        try:
            tasks = self.workbench.catalog.validate(name, benchmark, rows)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("The file does not match this dataset source or contains invalid tasks. Check the source, task IDs and pinned baseline commits.") from error
        encoded = json.dumps(rows).encode()
        if len(encoded) > MAX_CACHE_BYTES:
            raise ValueError("The expanded dataset is too large. Split it into smaller datasets.")
        with self.lock:
            self.expire()
            if len(self.pending) >= 16 or sum(item["bytes"] for item in self.pending.values()) + len(encoded) > MAX_CACHE_BYTES:
                raise ValueError("Too many dataset previews are open. Cancel an earlier preview or restart the local evaluation service when it is idle.")
            token = uuid.uuid4().hex
            self.pending[token] = {"rows": rows, "bytes": len(encoded), "name": name, "benchmark": benchmark, "expires": time.monotonic() + 3600, "result": None}
        return {"token": token, "filename": filename, "name": name, "benchmark": benchmark, "count": len(tasks),
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "samples": [{"id": task.id, "repository": task.repository, "baseCommit": task.base_commit} for task in tasks[:5]],
                "testsExecuted": False}

    def confirm(self, token: str):
        with self.lock:
            self.expire()
            item = self.pending.get(token)
            if not item:
                raise ValueError("The dataset preview expired or the service restarted. Select the file and check it again.")
            if item["result"] is None:
                # Retry after a lost response returns the same immutable registration.
                item["result"] = self.workbench.catalog.register(item["name"], item["benchmark"], item["rows"])
                item["rows"], item["bytes"] = None, 0
            return item["result"]

    def discard(self, token: str):
        with self.lock:
            self.expire()
            self.pending.pop(token, None)
        return {"discarded": True}

"""Read-only Docker observation, isolated from candidate trees and grading.

Persist only redacted text, serve the complete archive in bounded pages, and
never make the outcome of a benchmark depend on the availability of its logs.
Offsets count Unicode characters, not encoded bytes or Docker timestamps.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import inspect
import os
from pathlib import Path
import re
import sqlite3
import threading
import uuid

from .database import utc_now
from .command_adapter import RedactedStream

_scope = ContextVar('container_log_scope', default={})
_owner = uuid.uuid4().hex
SCOPES = {'experimentId', 'operationId', 'benchmarkRunId', 'runId'}
PAGE = 64_000


@contextmanager
def log_scope(**values):
    token = _scope.set({**_scope.get(), **{key: value for key, value in values.items() if value}})
    try:
        yield
    finally:
        _scope.reset(token)


def scoped(key, field=None):
    """Attach operator provenance without putting it into the Agent request."""
    def decorate(function):
        argument = tuple(inspect.signature(function).parameters)[1]
        @wraps(function)
        def call(self, *args, **kwargs):
            value = args[0] if args else kwargs[argument]
            with log_scope(**{key: (value[field] if isinstance(value, dict) else getattr(value, field)) if field else value}):
                return function(self, *args, **kwargs)
        return call
    return decorate


class ContainerLogs:
    def __init__(self, root):
        # Host-side operator data, never mounted into a coding/builder container.
        self.root = Path(root) / 'container-logs'
        self.path = self.root / 'logs.sqlite3'

    def connect(self):
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, metadata TEXT, owner TEXT, state TEXT, exit_code INTEGER, error TEXT, start INTEGER, end INTEGER, updated TEXT)')
        connection.execute('CREATE TABLE IF NOT EXISTS chunks (session TEXT, offset INTEGER, content TEXT, PRIMARY KEY(session, offset))')
        for key in sorted(SCOPES):
            connection.execute(f"CREATE INDEX IF NOT EXISTS scope_{key} ON sessions(json_extract(metadata, '$.{key}'))")
        return connection

    @contextmanager
    def db(self):
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, mode, **scope):
        key = uuid.uuid4().hex
        metadata = {**_scope.get(), **scope, 'id': key, 'mode': mode, 'archiveVersion': 1, 'startedAt': utc_now()}
        with self.db() as db:
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)',
                       (key, json.dumps(metadata), _owner, 'streaming', None, None, 0, 0, utc_now()))
        return key

    def append(self, key, text):
        text = text.replace('\x00', '\\0')
        if not text:
            return
        # Bound SQLite row size, without discarding the beginning of the archive.
        for index in range(0, len(text), 16_000):
            chunk = text[index:index + 16_000]
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM sessions WHERE id=?', (key,)).fetchone()
                if row is None or row['state'] != 'streaming':
                    return
                end = row['end'] + len(chunk)
                db.execute('INSERT INTO chunks VALUES (?,?,?)', (key, row['end'], chunk))
                start = db.execute('SELECT min(offset) FROM chunks WHERE session=?', (key,)).fetchone()[0]
                db.execute('UPDATE sessions SET start=?, end=?, updated=? WHERE id=?', (start, end, utc_now(), key))

    def finish(self, key, code=None, error=None):
        with self.db() as db:
            db.execute('UPDATE sessions SET state=?, exit_code=COALESCE(?,exit_code), error=?, updated=? WHERE id=?',
                       ('unavailable' if error else 'ended', code, error, utc_now(), key))

    def metadata(self, key, **values):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT metadata FROM sessions WHERE id=?', (key,)).fetchone()
            if row:
                db.execute('UPDATE sessions SET metadata=? WHERE id=?', (json.dumps({**json.loads(row[0]), **values}), key))

    @staticmethod
    def public(row):
        return {**json.loads(row['metadata']), 'state': 'interrupted' if row['state'] == 'streaming' and row['owner'] != _owner else row['state'],
                'exitCode': row['exit_code'], 'error': row['error'], 'startOffset': row['start'],
                'endOffset': row['end'], 'updatedAt': row['updated'], 'truncated': row['start'] > 0}

    def list(self, *, before=None, **scope):
        if not scope or set(scope) - SCOPES or any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value) for value in scope.values()):
            raise ValueError('Select a valid experiment, preparation or run to view container logs.')
        if before is not None and (type(before) is not int or before < 1 or before > 2**53 - 1):
            raise ValueError('Invalid log inventory cursor.')
        if not self.path.exists():
            return []
        with self.db() as db:
            # Query metadata only: log bodies never enter dashboard snapshots.
            conditions = ' AND '.join(f"json_extract(metadata, '$.{key}') = ?" for key in scope)
            rows = db.execute(f'SELECT rowid AS sequence, * FROM sessions WHERE {conditions}' + (' AND rowid < ?' if before else '') + ' ORDER BY rowid DESC LIMIT 200',
                              (*scope.values(), before) if before else tuple(scope.values())).fetchall()
            return [{**self.public(row), 'sequence': row['sequence']} for row in rows]

    def read(self, key, offset=None):
        if not re.fullmatch(r'[a-f0-9]{32}', key) or (offset is not None and (type(offset) is not int or offset < 0 or offset > 2**53 - 1)):
            raise ValueError('Invalid container log cursor.')
        if not self.path.exists():
            raise KeyError('Container log session')
        with self.db() as db:
            db.execute('BEGIN')
            row = db.execute('SELECT * FROM sessions WHERE id=?', (key,)).fetchone()
            if row is None:
                raise KeyError('Container log session')
            start = max(row['start'], row['end'] - PAGE) if offset is None else max(row['start'], min(offset, row['end']))
            reset = offset is not None and (offset < row['start'] or offset > row['end'])
            if reset:
                start = max(row['start'], row['end'] - PAGE)
            anchor = db.execute('SELECT offset FROM chunks WHERE session=? AND offset<=? ORDER BY offset DESC LIMIT 1', (key, start)).fetchone()
            chunks = db.execute('SELECT offset, content FROM chunks WHERE session=? AND offset>=? AND offset<? ORDER BY offset',
                                (key, anchor[0] if anchor else start, start + PAGE)).fetchall()
            content = ''.join(chunk['content'][max(0, start - chunk['offset']):max(0, start + PAGE - chunk['offset'])] for chunk in chunks)
            return {**self.public(row), 'content': content, 'pageOffset': start, 'nextOffset': start + len(content),
                    'hasMore': start + len(content) < row['end'], 'reset': reset}

    def capture(self, container, mode, secrets=(), **scope):
        # A failed observer must not fail/retry a model invocation or change grades.
        try:
            identity = {key: value for key, value in {'containerId': getattr(container, 'id', None),
                        'containerName': getattr(container, 'name', None)}.items() if isinstance(value, str)}
            return Capture(self, container, self.create(mode, **scope, **identity), secrets)
        except Exception:
            return NullCapture()


class NullCapture:
    def finish(self, code=None):
        pass


class Capture:
    def __init__(self, store, container, key, secrets):
        self.store, self.container, self.key = store, container, key
        self.redactor = RedactedStream(secrets)
        self.stream = None
        self.error = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.consume, name='ctxbench-container-log', daemon=True)
        self.thread.start()

    def consume(self):
        try:
            self.stream = self.container.logs(stream=True, follow=True, stdout=True, stderr=True)
            chunks = [self.stream] if isinstance(self.stream, bytes) else self.stream
            for chunk in chunks:
                if self.stop.is_set():
                    break
                if isinstance(chunk, bytes):
                    self.store.append(self.key, self.redactor.feed(chunk))
            self.store.append(self.key, self.redactor.feed(final=True))
        except Exception:
            self.error = 'Container log collection stopped. The task may still be running; inspect its status separately.'
            try:
                self.store.finish(self.key, error=self.error)
            except Exception:
                pass

    def finish(self, code=None):
        try:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                self.stop.set()
                self.error = self.error or 'Container log collection ended before all output was received.'
                if hasattr(self.stream, 'close'):
                    self.stream.close()
        except Exception:
            pass
        finally:
            try:
                self.store.finish(self.key, code, self.error)
            except Exception:
                pass


def runtime_secrets(names=()):
    return tuple(value for key, value in os.environ.items() if value and (key in names or re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', key, re.I)))

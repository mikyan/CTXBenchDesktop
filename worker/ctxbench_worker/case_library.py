"""Editable cases/sets; execution crosses this seam once into the frozen catalog.

Rows (including evaluator-only material) never leave operator detail endpoints.
All membership/version reads use one SQLite transaction. Optimistic revisions stop
stale editors and stale run previews, including edits made through another set.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from .catalog import fingerprint
from .database import utc_now
from .environments import public_material


class LibraryConflict(ValueError):
    pass


CASE_FIELDS = ('id', 'name', 'benchmark', 'revision', 'taskId', 'repository', 'baseCommit',
               'prompt', 'image', 'createdAt', 'updatedAt', 'originDataset', 'modified')


class CaseLibrary:
    def __init__(self, catalog, redact):
        self.catalog, self.db, self.redact = catalog, catalog.database, redact

    @staticmethod
    def editable(key):
        return isinstance(key, str) and key.startswith(('case-', 'set-'))

    @staticmethod
    def _get(connection, kind, key):
        row = connection.execute('SELECT payload_json FROM documents WHERE kind = ? AND id = ?', (kind, key)).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    @staticmethod
    def _put(connection, kind, record):
        connection.execute('INSERT INTO documents VALUES (?, ?, ?) ON CONFLICT(kind,id) DO UPDATE SET payload_json=excluded.payload_json',
                           (kind, record['id'], json.dumps(record)))

    @staticmethod
    def _revision(record, expected):
        if type(expected) is not int or expected != record['revision']:
            raise LibraryConflict('This item was edited elsewhere. Reload it before saving; your changes were not overwritten.')

    @staticmethod
    def _name(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 160 or '\0' in value:
            raise ValueError('Enter a name between 1 and 160 characters.')
        return value.strip()

    def _case(self, key, name, benchmark, row, previous=None):
        if len(json.dumps(row)) > 10_000_000:
            raise ValueError('A case definition must not exceed 10 MB.')
        task = self.catalog.validate(name, benchmark, [row])[0]
        now = utc_now()
        return {'id': key, 'name': name, 'benchmark': benchmark, 'row': row,
                'revision': previous['revision'] + 1 if previous else 1,
                'taskId': task.id, 'repository': task.repository, 'baseCommit': task.base_commit,
                'prompt': task.prompt, 'image': task.image,
                'createdAt': previous['createdAt'] if previous else now, 'updatedAt': now,
                'originDataset': previous.get('originDataset') if previous else None,
                'modified': bool(previous and previous.get('originDataset'))}

    def save_case(self, value, key=None):
        if not isinstance(value, dict) or set(value) - {'name', 'benchmark', 'row', 'expectedRevision'}:
            raise ValueError('Unsupported case fields.')
        public_material(value, self.redact)
        name = self._name(value.get('name'))
        with self.db.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            old = self._get(connection, 'libraryCases', key) if key else None
            if old:
                self._revision(old, value.get('expectedRevision'))
                if old['benchmark'] != value.get('benchmark'):
                    raise ValueError('The grading protocol cannot change for an existing case. Create another case instead.')
            record = self._case(key or 'case-' + uuid.uuid4().hex, name, value.get('benchmark'), value.get('row'), old)
            # A renamed task ID must not introduce duplicates into any referencing set.
            for row in connection.execute("SELECT payload_json FROM documents WHERE kind = 'librarySets'").fetchall():
                collection = json.loads(row[0])
                if record['id'] in collection['caseIds']:
                    others = [self._get(connection, 'libraryCases', item) for item in collection['caseIds'] if item != record['id']]
                    if any(item['taskId'] == record['taskId'] for item in others):
                        raise ValueError('This task ID is already used by another case in a referencing dataset.')
            self._put(connection, 'libraryCases', record)
        return self.public_case(record)

    @staticmethod
    def public_case(record):
        return {key: record.get(key) for key in CASE_FIELDS}

    def cases(self):
        return self.db.list_document_summaries('libraryCases', CASE_FIELDS)

    def case(self, key):
        with self.db.connect() as connection:
            connection.execute('BEGIN')
            record = self._get(connection, 'libraryCases', key)
            used = [json.loads(row[0]) for row in connection.execute("SELECT payload_json FROM documents WHERE kind='librarySets'").fetchall()]
            return {**record, 'usedBy': [{'id': item['id'], 'name': item['name']} for item in used if key in item['caseIds']]}

    def _selection(self, connection, key):
        if key.startswith('case-'):
            case = self._get(connection, 'libraryCases', key)
            collection = {k: case[k] for k in ('id', 'name', 'benchmark', 'revision', 'createdAt', 'updatedAt')}
            collection['caseIds'] = [key]
        else:
            collection = self._get(connection, 'librarySets', key)
        cases = [self._get(connection, 'libraryCases', item) for item in collection['caseIds']]
        rows = [item['row'] for item in cases]
        members = [{'caseId': item['id'], 'revision': item['revision'], 'taskId': item['taskId'],
                    'rowHash': fingerprint(item['row']), 'modified': item['modified']} for item in cases]
        revision = fingerprint({'id': key, 'revision': collection['revision'], 'members': members})
        return collection, cases, rows, members, revision

    def selection(self, key):
        """One coherent read, with no snapshots, model calls or execution side effects."""
        if not self.editable(key):
            record = self.catalog.verify(key)
            return {'dataset': self.catalog.public(record), 'tasks': self.catalog.tasks(key), 'revision': key}
        with self.db.connect() as connection:
            connection.execute('BEGIN')
            collection, cases, _, _, revision = self._selection(connection, key)
            return {'dataset': {**collection, 'count': len(cases), 'contentRevision': revision},
                    'tasks': [{'id': item['taskId'], **{k: item[k] for k in ('repository', 'baseCommit', 'prompt', 'image')},
                               **({'customAgentImage': item['row']['agent']['image']} if item['benchmark'] == 'custom' and item['row'].get('agent') else {}),
                               'caseId': item['id'], 'caseRevision': item['revision']} for item in cases], 'revision': revision}

    def definition(self, key):
        """Operator-only live source; callers must freeze it before queuing work."""
        if not self.editable(key):
            record = self.catalog.verify(key)
            return {**record, 'rows': json.loads(Path(record['path']).read_text(encoding='utf-8'))}
        with self.db.connect() as connection:
            connection.execute('BEGIN')
            collection, _, rows, members, revision = self._selection(connection, key)
            tasks = self.catalog.validate(collection['name'], collection['benchmark'], rows)
            return {**collection, 'rows': rows, 'members': members, 'contentRevision': revision,
                    'count': len(tasks), 'tasks': [asdict(task) for task in tasks]}

    def save_set(self, value, key=None):
        if not isinstance(value, dict) or set(value) - {'name', 'caseIds', 'expectedRevision'}:
            raise ValueError('Unsupported dataset fields.')
        public_material(value, self.redact)
        name, ids = self._name(value.get('name')), value.get('caseIds')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 10000 or not all(isinstance(item, str) for item in ids) or len(ids) != len(set(ids)):
            raise ValueError('Select between 1 and 10,000 unique existing cases.')
        with self.db.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            old = self._get(connection, 'librarySets', key) if key else None
            if old:
                self._revision(old, value.get('expectedRevision'))
            cases = [self._get(connection, 'libraryCases', item) for item in ids]
            if len({item['benchmark'] for item in cases}) != 1:
                raise ValueError('Combine cases using the same grading protocol. SWE-bench, CTXBench and custom tests use different graders.')
            if len({item['taskId'] for item in cases}) != len(cases):
                raise ValueError('Task IDs must be unique within this dataset. Edit the conflicting case ID first.')
            now = utc_now()
            record = {'id': key or 'set-' + uuid.uuid4().hex, 'name': name, 'caseIds': ids,
                      'benchmark': cases[0]['benchmark'], 'count': len(ids),
                      'revision': old['revision'] + 1 if old else 1,
                      'createdAt': old['createdAt'] if old else now, 'updatedAt': now}
            if old and old.get('originDataset'):
                record['originDataset'] = old['originDataset']
            self._put(connection, 'librarySets', record)
        return record

    def sets(self):
        # Idempotent lazy migration also discovers datasets imported by old CLIs.
        # Immutable source records and files are never edited or removed.
        for record in self.catalog.list():
            self.adopt(record['id'])
        return self.db.list_documents('librarySets')

    def adopt(self, dataset):
        key = 'set-' + dataset
        try:
            return self.db.get_document('librarySets', key)
        except KeyError:
            pass
        source = self.catalog.verify(dataset)
        rows = json.loads(Path(source['path']).read_text(encoding='utf-8'))
        with self.db.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            try:
                return self._get(connection, 'librarySets', key)
            except KeyError:
                pass
            ids = []
            for index, row in enumerate(rows):
                case_id = 'case-' + fingerprint({'dataset': dataset, 'index': index})
                task = source['tasks'][index]
                record = self._case(case_id, task['id'], source['benchmark'], row)
                record['originDataset'] = dataset
                self._put(connection, 'libraryCases', record)
                ids.append(case_id)
            record = {'id': key, 'name': source['name'], 'benchmark': source['benchmark'], 'caseIds': ids,
                      'count': len(ids), 'revision': 1, 'originDataset': dataset,
                      'createdAt': source['createdAt'], 'updatedAt': utc_now()}
            self._put(connection, 'librarySets', record)
            return record

    def freeze(self, key, task_ids=None, expected_revision=None):
        if not self.editable(key):
            self.catalog.verify(key)
            return key, {}
        record = self.definition(key)
        if expected_revision and record['contentRevision'] != expected_revision:
            raise LibraryConflict('The selected cases or dataset changed. Reload the selection and review it before starting.')
        requested = list(task_ids) if task_ids is not None else [item['taskId'] for item in record['members']]
        if not requested or len(requested) != len(set(requested)) or any(item not in {m['taskId'] for m in record['members']} for item in requested):
            raise ValueError('Select unique tasks from the current dataset or case.')
        by_id = {member['taskId']: (row, member) for row, member in zip(record['rows'], record['members'])}
        rows = [by_id[item][0] for item in requested]
        frozen = self.catalog.register(record['name'], record['benchmark'], rows, internal=True)
        receipt = {'id': 'snapshot-' + uuid.uuid4().hex, 'sourceId': key, 'name': record['name'],
                   'sourceRevision': record['revision'], 'contentRevision': record['contentRevision'],
                   'dataset': frozen['id'], 'benchmark': record['benchmark'], 'createdAt': utc_now(),
                   'members': [by_id[item][1] for item in requested]}
        self.db.put_document('datasetSnapshots', receipt['id'], receipt)
        return frozen['id'], receipt

    def snapshots(self, source=None):
        records = self.db.list_documents('datasetSnapshots')
        return [item for item in records if not source or item['sourceId'] == source or any(m['caseId'] == source for m in item['members'])]

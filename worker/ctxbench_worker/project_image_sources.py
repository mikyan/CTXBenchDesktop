"""Remember exact official-image addresses; capture them once before execution.

Settings are shared by official image identity within the selected company profile
(or the default scope), not written into datasets, image tags, or model settings.
Only explicit saves mutate settings. Every execution receives a frozen copy.
"""
import json

from .case_library import LibraryConflict
from .catalog import fingerprint
from .database import utc_now
from .environments import public_material
from .image_sources import normalize_pull_reference, validate_overrides


class ProjectImageSources:
    def __init__(self, workbench):
        self.wb, self.db = workbench, workbench.db

    @staticmethod
    def scope(environment):
        return environment.get('companyProfileId', environment.get('id', '')) if environment else ''

    def references(self, dataset, task_ids=None):
        from .datasets import TaskRecord
        from .standard_images import project_image, swe_image
        record = self.wb.library.definition(dataset)
        if record['benchmark'] not in {'swebench', 'ctxbench'}:
            return set()
        tasks = record['tasks']
        if task_ids is not None:
            ids = set(task_ids)
            if not ids or not ids <= {task['id'] for task in tasks}:
                raise ValueError('Select tasks belonging to this official dataset.')
            tasks = [task for task in tasks if task['id'] in ids]
        refs = set()
        for value in tasks:
            task = TaskRecord(**value)
            refs.add(project_image(task))
            if task.source == 'swebench':
                refs.add(swe_image(task.id))
        return refs

    def _get(self, scope, connection=None):
        key = fingerprint({'profileId': scope})
        if connection is not None:
            row = connection.execute("SELECT payload_json FROM documents WHERE kind='projectImageSources' AND id=?", (key,)).fetchone()
            value = json.loads(row[0]) if row else None
        else:
            try:
                value = self.db.get_document('projectImageSources', key)
            except KeyError:
                value = None
        if value is None:
            return {'id': key, 'profileId': scope, 'revision': 0, 'overrides': []}
        public_material(value, self.wb.redact)
        validate_overrides(value['overrides'])
        return value

    def view(self, dataset, environment=None):
        refs = self.references(dataset)
        value = self._get(self.scope(environment))
        return {**value, 'overrides': [row for row in value['overrides'] if row['source'] in refs]}

    def save(self, dataset, value, environment=None):
        if not isinstance(value, dict) or set(value) - {'overrides', 'expectedRevision', 'datasetRevision', 'profileId'}:
            raise ValueError('Unsupported project image address settings.')
        public_material(value, self.wb.redact)
        selection = self.wb.library.selection(dataset)
        if value.get('datasetRevision') and selection['revision'] != value['datasetRevision']:
            raise LibraryConflict('The selected cases or dataset changed. Reload the selection and review it before starting.')
        refs = self.references(dataset)
        if not refs:
            raise ValueError('Exact project image addresses are available for official SWE-bench and CTXBench cases only.')
        updates = value.get('overrides')
        if not isinstance(updates, list) or not 1 <= len(updates) <= 10000:
            raise ValueError('Provide between 1 and 10,000 image address changes.')
        normalized = {}
        for row in updates:
            if not isinstance(row, dict) or set(row) != {'source', 'target'} or not isinstance(row.get('source'), str) or row['source'] not in refs or row['source'] in normalized:
                raise ValueError('Choose each official image from this dataset at most once.')
            if not isinstance(row['target'], str):
                raise ValueError('An image address must be text; leave it empty to restore the default.')
            normalized[row['source']] = normalize_pull_reference(row['target']) if row['target'].strip() else None
        with self.db.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current = self._get(self.scope(environment), connection)
            if type(value.get('expectedRevision')) is not int or value['expectedRevision'] != current['revision']:
                raise LibraryConflict('Image addresses changed elsewhere. Refresh image status before saving or installing.')
            addresses = {row['source']: row['target'] for row in current['overrides']}
            for source, target in normalized.items():
                if target is None:
                    addresses.pop(source, None)
                else:
                    addresses[source] = target
            record = {**current, 'revision': current['revision'] + 1, 'updatedAt': utc_now(),
                      'overrides': [{'source': source, 'target': target} for source, target in sorted(addresses.items())]}
            validate_overrides(record['overrides'])
            connection.execute('INSERT INTO documents VALUES (?, ?, ?) ON CONFLICT(kind,id) DO UPDATE SET payload_json=excluded.payload_json',
                               ('projectImageSources', record['id'], json.dumps(record)))
        return {**record, 'overrides': [row for row in record['overrides'] if row['source'] in refs]}

    def freeze(self, dataset, task_ids=None, environment=None, expected_revision=None):
        environment = environment or {}
        if 'projectImageSources' in environment:
            return environment  # A retry or an already captured operator job.
        refs = self.references(dataset, task_ids)
        if not refs:
            return environment
        current = self._get(self.scope(environment))
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision != current['revision']):
            raise LibraryConflict('Image addresses changed elsewhere. Refresh image status before saving or installing.')
        rows = [row for row in current['overrides'] if row['source'] in refs]
        if not rows:
            return environment
        document = {**environment.get('document', environment), 'imageOverrides': rows}
        receipt = {'scope': current['profileId'], 'revision': current['revision'], 'overrides': rows}
        return {'id': fingerprint({'document': document, 'projectImageSources': receipt}),
                'companyProfileId': self.scope(environment), 'document': document, 'projectImageSources': receipt}

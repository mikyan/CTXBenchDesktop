"""Confirmed, transactional record deletion. Never touches files or external services.

Execution snapshots, shared artifacts, budget accounting and CI receipts outlive
editable sources/results. A result is deleted as its entire paired repeat block.
"""
import json
import uuid

from .case_library import LibraryConflict
from .catalog import fingerprint
from .database import utc_now

TERMINAL = {'completed', 'failed', 'cancelled'}


class DataDeletions:
    def __init__(self, workbench):
        self.wb, self.db = workbench, workbench.db

    @staticmethod
    def target(value, *, confirmed=False):
        fields = {'kind', 'id', 'token'} if confirmed else {'kind', 'id'}
        if (not isinstance(value, dict) or set(value) != fields or
                not isinstance(value.get('kind'), str) or
                value.get('kind') not in {'case', 'set', 'experiment', 'result'} or
                not isinstance(value.get('id'), str) or not 1 <= len(value['id']) <= 4096 or
                (confirmed and (not isinstance(value.get('token'), str) or len(value['token']) != 64))):
            raise ValueError('Invalid deletion request. Open the confirmation dialog again.')

    def _plan(self, connection, kind, key):
        plan = {'kind': kind, 'id': key, 'affectedSets': [], 'runCount': 0, 'blockers': []}
        identity = {}
        if kind in {'case', 'set'}:
            record = self.wb.library._get(connection, 'libraryCases' if kind == 'case' else 'librarySets', key)
            plan.update(name=record['name'], caseCount=1 if kind == 'case' else record['count'])
            identity['revision'] = record['revision']
            identity['updatedAt'] = record['updatedAt']
            if kind == 'case':
                for row in connection.execute("SELECT payload_json FROM documents WHERE kind='librarySets' ORDER BY id"):
                    collection = json.loads(row[0])
                    if key in collection['caseIds']:
                        plan['affectedSets'].append({'id': collection['id'], 'name': collection['name'],
                            'revision': collection['revision'], 'remainingCount': len(collection['caseIds']) - 1})
        else:
            if kind == 'result':
                run = connection.execute('SELECT experiment_id,pair_id,task_id,repeat FROM runs WHERE id=?', (key,)).fetchone()
                if run is None:
                    raise KeyError(key)
                experiment_id, pair_id = run['experiment_id'], run['pair_id']
                plan.update(taskId=run['task_id'], repeat=run['repeat'])
            else:
                experiment_id, pair_id = key, None
            experiment = connection.execute('SELECT * FROM experiments WHERE id=?', (experiment_id,)).fetchone()
            if experiment is None:
                raise KeyError(experiment_id)
            runs = connection.execute('SELECT id,pair_id,arm,status,updated_at FROM runs WHERE experiment_id=?' +
                (' AND pair_id=?' if pair_id else '') + ' ORDER BY id', (experiment_id, pair_id) if pair_id else (experiment_id,)).fetchall()
            plan.update(name=experiment['name'], experimentId=experiment_id, runCount=len(runs),
                        pairId=pair_id, arms=[row['arm'] for row in runs] if pair_id else [])
            identity.update(experimentUpdated=experiment['updated_at'], runs=[dict(row) for row in runs])
            operations = [json.loads(row[0]) for row in connection.execute("SELECT payload_json FROM documents WHERE kind='operations'")]
            operations = [op for op in operations if op['kind'] == 'experiment' and op['payload'].get('experimentId') == experiment_id]
            if (experiment['status'] not in TERMINAL or experiment_id in self.wb._active or
                    any(op['status'] in {'queued', 'running'} or op['id'] == self.wb._executing_operation for op in operations)):
                plan['blockers'].append('Finish or cancel this experiment and wait for its current operation to exit before deleting results.')
        # The token binds the exact displayed impact and revisions, not a stale UI snapshot.
        plan['token'] = fingerprint({'plan': plan, 'identity': identity})
        return plan

    def preview(self, value):
        self.target(value)
        with self.wb._lock, self.db.connect() as connection:
            connection.execute('BEGIN')
            return self._plan(connection, value['kind'], value['id'])

    def delete(self, value):
        self.target(value, confirmed=True)
        kind, key = value['kind'], value['id']
        with self.wb._lock, self.db.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            plan = self._plan(connection, kind, key)
            if plan['blockers']:
                raise LibraryConflict(plan['blockers'][0])
            if plan['token'] != value['token']:
                raise LibraryConflict('The deletion scope changed. Reload the preview and confirm the updated impact; nothing was deleted.')
            if kind == 'case':
                for item in plan['affectedSets']:
                    collection = self.wb.library._get(connection, 'librarySets', item['id'])
                    collection.update(caseIds=[member for member in collection['caseIds'] if member != key],
                        count=item['remainingCount'], revision=collection['revision'] + 1, updatedAt=utc_now())
                    self.wb.library._put(connection, 'librarySets', collection)
                connection.execute("DELETE FROM documents WHERE kind='libraryCases' AND id=?", (key,))
            elif kind == 'set':
                # Suppress the automatic legacy-import adoption, not immutable source access.
                self.wb.library._put(connection, 'deletedLibrarySources', {'id': key, 'deletedAt': utc_now()})
                connection.execute("DELETE FROM documents WHERE kind='librarySets' AND id=?", (key,))
            else:
                experiment_id = plan['experimentId']
                if kind == 'experiment':
                    connection.execute('DELETE FROM experiments WHERE id=?', (experiment_id,))
                    connection.execute("DELETE FROM documents WHERE kind IN ('prepared','executionRequests','environmentProgress') AND id=?", (experiment_id,))
                    connection.execute("DELETE FROM documents WHERE kind='operations' AND json_extract(payload_json,'$.kind')='experiment' AND json_extract(payload_json,'$.payload.experimentId')=?", (experiment_id,))
                else:
                    connection.execute('DELETE FROM runs WHERE experiment_id=? AND pair_id=?', (experiment_id, plan['pairId']))
                    connection.execute("UPDATE experiments SET total_runs=(SELECT count(*) FROM runs WHERE experiment_id=?), completed_runs=(SELECT count(*) FROM runs WHERE experiment_id=? AND status IN ('completed','failed','cancelled')),updated_at=? WHERE id=?",
                        (experiment_id, experiment_id, utc_now(), experiment_id))
            receipt = {k: plan[k] for k in ('kind', 'id', 'name', 'runCount')}
            receipt.update(id='deletion-' + uuid.uuid4().hex, targetId=key, deletedAt=utc_now(),
                **({'experimentId': plan['experimentId'], 'pairId': plan['pairId']} if kind == 'result' else {}))
            self.wb.library._put(connection, 'deletionEvents', receipt)
        return {'deleted': True, 'kind': kind, 'id': key, 'runCount': plan['runCount'],
                'affectedSetCount': len(plan['affectedSets']), 'filesRetained': True}

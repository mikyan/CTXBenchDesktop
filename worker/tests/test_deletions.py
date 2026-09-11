"""Record deletion uses disposable databases only; never runs agents or removes files."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.case_library import LibraryConflict
from worker.ctxbench_worker.deletions import DataDeletions
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.history import GitHubClient
from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from worker.ctxbench_worker.workbench import Workbench
from worker.tests.test_dataset_authoring import manifest


class DeletionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = create_mock_engine(self.root)
        self.wb = Workbench(self.engine, GitHubClient(None))
        self.db, self.library = self.engine.database, self.wb.library
        self.deletions = DataDeletions(self.wb)
        self.client = TestClient(create_app(self.engine, GitHubClient(None)))
        self.addCleanup(self.client.close)

    def case(self, id='task-1'):
        return self.library.save_case({'name': 'Case ' + id, 'benchmark': 'custom',
            'row': {**manifest()['rows'][0], 'id': id}})

    def collection(self, *cases):
        return self.library.save_set({'name': 'Suite', 'caseIds': [case['id'] for case in cases]})

    def confirm(self, plan):
        return {key: plan[key] for key in ('kind', 'id', 'token')}

    def remove(self, kind, id):
        return self.deletions.delete(self.confirm(self.deletions.preview({'kind': kind, 'id': id})))

    def experiment(self, status='completed'):
        case = self.case()
        dataset, receipt = self.library.freeze(case['id'])
        spec = ExperimentSpec('Deletion fixture', 'custom', dataset, ('none', 'manual', 'skill-generated'),
            2, ('task-1',), ModelConfig('mock', 'deterministic', 'off', 4096), 'fixture/agent', ResourcePolicy(), 42,
            dataset_snapshot=receipt)
        experiment = self.engine.create_experiment(spec)
        for run in self.db.list_runs(experiment['id']):
            self.db.update_run(run['id'], 'completed', {'testsPassed': True, 'tokenUsage': {'total': 7}})
        self.db.set_experiment_status(experiment['id'], status)
        return experiment, spec

    def test_case_detaches_all_sets_atomically_and_preserves_frozen_data(self):
        one, two = self.case(), self.case('task-2')
        a, b = self.collection(one), self.collection(one, two)
        frozen, receipt = self.library.freeze(a['id'])
        path = self.root / 'datasets' / (frozen + '.json')
        contents = path.read_bytes()
        plan = self.deletions.preview({'kind': 'case', 'id': one['id']})
        self.assertEqual(sorted(item['remainingCount'] for item in plan['affectedSets']), [0, 1])
        self.assertNotIn('private test patch', json.dumps(plan))
        self.assertNotIn('private reference patch', json.dumps(plan))
        self.assertEqual(len(self.library.cases()), 2)  # Preview is read-only.
        result = self.deletions.delete(self.confirm(plan))
        self.assertEqual(result['affectedSetCount'], 2)
        self.assertEqual(self.library.cases(), [two])
        for collection, members in ((a, []), (b, [two['id']])):
            current = self.db.get_document('librarySets', collection['id'])
            self.assertEqual(current['caseIds'], members)
            self.assertEqual(current['count'], len(members))
            self.assertEqual(current['revision'], 2)
        self.assertEqual(path.read_bytes(), contents)
        self.assertEqual(self.library.snapshots()[0], receipt)
        self.assertEqual(self.wb.catalog.task(frozen, 'task-1').gold_patch, 'private reference patch')
        with self.assertRaises(ValueError):
            self.library.freeze(a['id'])
        self.library.save_set({'name': 'Refilled', 'caseIds': [two['id']], 'expectedRevision': 2}, a['id'])
        self.library.freeze(a['id'])

    def test_case_edit_and_reference_changes_invalidate_confirmation(self):
        case = self.case()
        first = self.deletions.preview({'kind': 'case', 'id': case['id']})
        self.collection(case)
        with self.assertRaisesRegex(LibraryConflict, 'scope changed'):
            self.deletions.delete(self.confirm(first))
        second = self.deletions.preview({'kind': 'case', 'id': case['id']})
        self.library.save_case({'name': 'Renamed', 'benchmark': 'custom', 'row': manifest()['rows'][0], 'expectedRevision': 1}, case['id'])
        with self.assertRaisesRegex(LibraryConflict, 'scope changed'):
            self.deletions.delete(self.confirm(second))
        self.assertEqual(len(self.library.cases()), 1)
        self.assertEqual(self.db.list_documents('deletionEvents'), [])

    def test_set_deletion_keeps_shared_cases_and_other_sets(self):
        case = self.case()
        a, b = self.collection(case), self.collection(case)
        self.remove('set', a['id'])
        self.assertEqual(self.library.sets(), [b])
        self.assertEqual(self.library.cases(), [case])

    def test_set_edit_invalidates_confirmation(self):
        case = self.case()
        collection = self.collection(case)
        plan = self.deletions.preview({'kind': 'set', 'id': collection['id']})
        self.library.save_set({'name': 'New name', 'caseIds': [case['id']], 'expectedRevision': 1}, collection['id'])
        with self.assertRaises(LibraryConflict):
            self.deletions.delete(self.confirm(plan))

    def test_delete_rolls_back_all_set_updates_if_a_write_fails(self):
        case = self.case()
        self.collection(case)
        self.collection(case)
        before = self.library.sets()
        original = self.library._put
        calls = []
        def fail_second(connection, kind, record):
            calls.append(kind)
            if len(calls) == 2:
                raise OSError('fixture disk failure')
            return original(connection, kind, record)
        with patch.object(self.library, '_put', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.remove('case', case['id'])
        self.assertEqual(self.library.sets(), before)
        self.assertEqual(self.library.cases(), [case])
        self.assertEqual(self.db.list_documents('deletionEvents'), [])

    def test_deleted_import_does_not_resurrect_after_refresh_or_restart(self):
        body = manifest()
        imported = self.wb.catalog.register(body['name'], body['benchmark'], body['rows'])
        collection = self.library.sets()[0]
        self.remove('set', collection['id'])
        restarted = Workbench(create_mock_engine(self.root), GitHubClient(None))
        self.assertEqual(restarted.library.inventory()['sets'], [])
        self.assertEqual(restarted.catalog.list(), [])
        self.assertEqual(len(restarted.library.cases()), 1)
        restarted.catalog.verify(imported['id'])
        with self.assertRaises(LibraryConflict):
            restarted.library.adopt(imported['id'])
        # Freezing the same rows internally must not clear the tombstone.
        restarted.catalog.register(body['name'], body['benchmark'], body['rows'], internal=True)
        self.assertEqual(restarted.library.sets(), [])

    def test_explicit_reimport_does_not_overwrite_retained_edited_cases(self):
        body = manifest()
        imported = self.wb.catalog.register(body['name'], body['benchmark'], body['rows'])
        collection = self.library.sets()[0]
        case = self.library.cases()[0]
        self.library.save_case({'name': 'Local variant', 'benchmark': 'custom', 'expectedRevision': 1,
            'row': {**body['rows'][0], 'prompt': 'Edited local requirement'}}, case['id'])
        shared = self.collection(case)
        self.remove('set', collection['id'])
        self.wb.catalog.register(body['name'], body['benchmark'], body['rows'])
        restored = self.library.adopt(imported['id'])
        self.assertNotEqual(restored['caseIds'], collection['caseIds'])
        self.assertEqual(self.library.selection(restored['id'])['tasks'][0]['prompt'], body['rows'][0]['prompt'])
        self.assertEqual(self.library.selection(shared['id'])['tasks'][0]['prompt'], 'Edited local requirement')

    def test_reimport_reuses_unchanged_cases_and_restores_deleted_cases(self):
        body = manifest()
        imported = self.wb.catalog.register(body['name'], body['benchmark'], body['rows'])
        collection = self.library.sets()[0]
        self.remove('set', collection['id'])
        self.wb.catalog.register(body['name'], body['benchmark'], body['rows'])
        self.assertEqual(self.library.adopt(imported['id'])['caseIds'], collection['caseIds'])
        self.assertEqual(len(self.library.cases()), 1)
        self.remove('case', collection['caseIds'][0])
        self.assertEqual(self.library.sets()[0]['count'], 0)  # No automatic case resurrection.
        self.remove('set', collection['id'])
        self.wb.catalog.register(body['name'], body['benchmark'], body['rows'])
        self.assertEqual(self.library.adopt(imported['id'])['count'], 1)

    def test_import_adoption_rechecks_tombstone_inside_transaction(self):
        body = manifest()
        imported = self.wb.catalog.register(body['name'], body['benchmark'], body['rows'])
        original = self.wb.catalog.verify
        def deleted_during_verification(key):
            source = original(key)
            self.db.put_document('deletedLibrarySources', 'set-' + key, {'id': 'set-' + key})
            return source
        with patch.object(self.wb.catalog, 'verify', side_effect=deleted_during_verification):
            with self.assertRaises(LibraryConflict):
                self.library.adopt(imported['id'])
        self.assertEqual(self.library.cases(), [])
        self.assertEqual(self.library.sets(), [])

    def test_result_deletes_all_arms_of_one_repeat_and_updates_counts(self):
        experiment, spec = self.experiment()
        runs = self.db.list_runs(experiment['id'])
        target = next(run for run in runs if run['arm'] == 'manual')
        plan = self.deletions.preview({'kind': 'result', 'id': target['id']})
        self.assertEqual(plan['runCount'], 3)
        self.assertEqual(set(plan['arms']), {'none', 'manual', 'skill-generated'})
        self.deletions.delete(self.confirm(plan))
        remaining = self.db.list_runs(experiment['id'])
        self.assertEqual(len(remaining), 3)
        self.assertNotIn(target['pairId'], {run['pairId'] for run in remaining})
        self.assertEqual(self.db.get_experiment(experiment['id'])['totalRuns'], 3)
        self.assertEqual(self.db.get_experiment(experiment['id'])['completedRuns'], 3)
        self.assertEqual(self.db.get_spec(experiment['id']), spec)
        self.assertEqual(self.wb.snapshot()['experiments'][0]['deletedResultGroups'], 1)
        self.remove('result', remaining[0]['id'])
        self.assertEqual(self.db.get_experiment(experiment['id'])['totalRuns'], 0)
        snapshot = self.wb.snapshot(compact=True)
        self.assertEqual(snapshot['runs'], [])
        self.assertEqual(snapshot['experiments'][0]['deletedResultRuns'], 6)

    def test_active_and_unwinding_operations_block_both_result_and_experiment_deletion(self):
        experiment, _ = self.experiment()
        run = self.db.list_runs(experiment['id'])[0]
        for status in ('running', 'preparing', 'ready', 'paused'):
            self.db.set_experiment_status(experiment['id'], status)
            for kind, key in (('experiment', experiment['id']), ('result', run['id'])):
                with self.subTest(status=status, kind=kind):
                    plan = self.deletions.preview({'kind': kind, 'id': key})
                    self.assertTrue(plan['blockers'])
                    with self.assertRaises(LibraryConflict):
                        self.deletions.delete(self.confirm(plan))
        self.db.set_experiment_status(experiment['id'], 'cancelled')
        operation = self.wb.enqueue('experiment', {'experimentId': experiment['id']})
        with self.assertRaises(LibraryConflict):
            self.remove('experiment', experiment['id'])
        operation['status'] = 'cancelled'
        self.db.put_document('operations', operation['id'], operation)
        self.wb._executing_operation = operation['id']  # Cancel acknowledged, but handler has not exited.
        with self.assertRaises(LibraryConflict):
            self.remove('experiment', experiment['id'])
        self.wb._executing_operation = None
        self.wb._active[experiment['id']] = run['id']
        with self.assertRaises(LibraryConflict):
            self.remove('result', run['id'])
        self.wb._active.clear()
        self.remove('experiment', experiment['id'])

    def test_restarting_and_changed_run_invalidate_old_preview(self):
        experiment, _ = self.experiment()
        plan = self.deletions.preview({'kind': 'experiment', 'id': experiment['id']})
        self.db.set_experiment_status(experiment['id'], 'running')
        with self.assertRaises(LibraryConflict):
            self.deletions.delete(self.confirm(plan))
        self.db.set_experiment_status(experiment['id'], 'completed')
        run = self.db.list_runs(experiment['id'])[0]
        self.db.update_run(run['id'], 'completed', {'failure': 'Changed evidence'})
        with self.assertRaises(LibraryConflict):
            self.deletions.delete(self.confirm(plan))

    def test_whole_experiment_deletion_keeps_snapshots_shared_records_files_and_other_experiments(self):
        experiment, spec = self.experiment('failed')
        other = self.engine.create_experiment(replace(spec, name='Keep this'))
        path = self.root / 'saved-log.txt'
        path.write_text('retain log', encoding='utf-8')
        for kind in ('prepared', 'executionRequests', 'environmentProgress'):
            self.db.put_document(kind, experiment['id'], {'id': experiment['id']})
        for kind in ('tokenUsage', 'ciEvaluations', 'stages'):
            self.db.put_document(kind, 'retain', {'id': 'retain', 'value': 123})
        operation = self.wb.enqueue('experiment', {'experimentId': experiment['id']})
        operation['status'] = 'failed'
        self.db.put_document('operations', operation['id'], operation)
        other_op = self.wb.enqueue('experiment', {'experimentId': other['id']})
        before = self.library.snapshots()
        self.remove('experiment', experiment['id'])
        self.assertEqual(self.db.list_runs(experiment['id']), [])
        self.assertEqual(len(self.db.list_runs(other['id'])), 6)
        self.assertEqual(self.library.snapshots(), before)
        self.wb.catalog.verify(spec.dataset)
        self.assertEqual(path.read_text(encoding='utf-8'), 'retain log')
        self.assertEqual(self.db.list_documents('operations'), [other_op])
        for kind in ('prepared', 'executionRequests', 'environmentProgress'):
            self.assertEqual(self.db.list_documents(kind), [])
        for kind in ('tokenUsage', 'ciEvaluations', 'stages'):
            self.assertEqual(self.db.get_document(kind, 'retain')['value'], 123)
        with self.assertRaises(KeyError):
            self.db.get_experiment(experiment['id'])

    def test_concurrent_deletes_have_one_winner_across_services(self):
        case = self.case()
        self.collection(case)
        plan = self.deletions.preview({'kind': 'case', 'id': case['id']})
        def remove(_):
            other = DataDeletions(Workbench(create_mock_engine(self.root), GitHubClient(None)))
            try:
                other.delete(self.confirm(plan))
                return True
            except KeyError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(remove, [1, 2])), [False, True])
        self.assertEqual(self.library.sets()[0]['count'], 0)
        self.assertEqual(len(self.db.list_documents('deletionEvents')), 1)

    def test_deletion_never_refunds_reserved_or_settled_tokens(self):
        experiment, _ = self.experiment()
        run = self.db.list_runs(experiment['id'])[0]
        budget = self.wb.budgets
        budget.create('deletion-budget', 1000, 'mock', 'deterministic')
        budget.reserve('deletion-budget', run['id'], 100, mode='solve', experiment_id=experiment['id'], output='fixture')
        budget.settle(run['id'], {'runId': run['id'], 'budgetProtocolVersion': 1, 'cumulativeTokens': 70, 'status': 'completed'})
        budget.reserve('deletion-budget', 'uncertain-stage', 100, mode='solve', experiment_id=experiment['id'], output='fixture')
        before = budget.snapshot('deletion-budget')
        self.assertEqual(before['remainingTokens'], 830)
        self.remove('result', run['id'])
        self.assertEqual(budget.snapshot('deletion-budget'), before)
        self.remove('experiment', experiment['id'])
        self.assertEqual(budget.snapshot('deletion-budget'), before)

    def test_http_preview_confirm_invalid_missing_and_stale_requests(self):
        case = self.case()
        base = '/v1/data-deletions'
        for invalid in ({}, {'kind': [], 'id': case['id']}, {'kind': 'case', 'id': ''},
                        {'kind': 'case', 'id': case['id'], 'extra': True}, {'kind': 'bogus', 'id': case['id']}):
            self.assertEqual(self.client.post(base + '/preview', json=invalid).status_code, 422)
        body = {'kind': 'case', 'id': case['id']}
        self.assertEqual(self.client.post(base, json=body).status_code, 422)
        plan = self.client.post(base + '/preview', json=body).json()
        self.assertEqual(self.client.post(base, json={**body, 'token': '0' * 64}).status_code, 409)
        self.assertEqual(self.client.post(base, json=self.confirm(plan)).status_code, 200)
        self.assertEqual(self.client.post(base, json=self.confirm(plan)).status_code, 404)
        self.assertEqual(self.client.post(base + '/preview', json=body).status_code, 404)
        self.assertEqual(self.client.get('/v1/library').json()['cases'], [])

    def test_http_experiment_deletion_removes_snapshot_rows_and_detail_access(self):
        experiment, _ = self.experiment()
        run = self.db.list_runs(experiment['id'])[0]
        base = '/v1/data-deletions'
        plan = self.client.post(base + '/preview', json={'kind': 'experiment', 'id': experiment['id']}).json()
        self.assertEqual(self.client.post(base, json=self.confirm(plan)).status_code, 200)
        self.assertEqual(self.client.get('/v1/snapshot').json()['runs'], [])
        self.assertEqual(self.client.get('/v1/experiments').json(), [])
        self.assertEqual(self.client.get('/v1/run-record', params={'id': run['id']}).status_code, 404)

    def test_untrusted_web_origin_cannot_confirm_deletion(self):
        case = self.case()
        plan = self.deletions.preview({'kind': 'case', 'id': case['id']})
        response = self.client.post('/v1/data-deletions', json=self.confirm(plan), headers={'Origin': 'https://evil.example'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(self.library.cases()), 1)


if __name__ == '__main__':
    unittest.main()

import copy
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.case_library import CaseLibrary, LibraryConflict
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.history import GitHubClient
from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from worker.ctxbench_worker.workbench import Workbench
from worker.tests.test_dataset_authoring import manifest


class CaseLibraryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = create_mock_engine(self.root)
        self.wb = Workbench(self.engine, GitHubClient(None))
        self.library = self.wb.library
        self.client = TestClient(create_app(self.engine, GitHubClient(None)))
        self.addCleanup(self.client.close)
        self.model = ModelConfig('mock', 'deterministic', 'off', 4096)

    def case(self, id='task-1'):
        return self.library.save_case({'name': 'Case ' + id, 'benchmark': 'custom', 'row': {**manifest()['rows'][0], 'id': id}})

    def edit(self, case, **changes):
        record = self.library.case(case['id'])
        return self.library.save_case({'name': record['name'], 'benchmark': record['benchmark'],
                                       'row': {**record['row'], **changes}, 'expectedRevision': case['revision']}, case['id'])

    def collection(self, *cases, name='Suite'):
        return self.library.save_set({'name': name, 'caseIds': [item['id'] for item in cases]})

    def spec(self, source, task_ids=('task-1',), revision=''):
        return ExperimentSpec('Library run', 'custom', source, ('none', 'skill-generated'), 2, task_ids,
                              self.model, 'fixture/agent', ResourcePolicy(), 42, dataset_revision=revision)

    def test_independent_case_needs_no_dataset_or_snapshot(self):
        case = self.case()
        self.assertEqual(self.library.cases(), [case])
        self.assertEqual(self.library.sets(), [])
        self.assertEqual(self.wb.catalog.list(), [])
        self.assertEqual(self.library.snapshots(), [])
        self.assertEqual(self.library.selection(case['id'])['tasks'][0]['id'], 'task-1')

    def test_shared_case_edits_update_future_sets_but_not_frozen_material(self):
        case = self.case()
        a, b = self.collection(case, name='A'), self.collection(case, name='B')
        before = self.library.selection(a['id'])
        frozen, receipt = self.library.freeze(a['id'], expected_revision=before['revision'])
        source = (self.root / 'datasets' / f'{frozen}.json').read_bytes()
        self.edit(case, prompt='New requirement', baseCommit='b' * 40,
                  test={'command': ['python3', '-m', 'unittest'], 'hiddenPatch': 'new private tests'}, goldPatch='new answer')
        for collection in (a, b):
            current = self.library.selection(collection['id'])
            self.assertEqual(current['tasks'][0]['prompt'], 'New requirement')
            self.assertEqual(current['tasks'][0]['caseRevision'], 2)
        self.assertNotEqual(self.library.selection(a['id'])['revision'], before['revision'])
        task = self.wb.catalog.task(frozen, 'task-1')
        self.assertEqual(task.prompt, manifest()['rows'][0]['prompt'])
        self.assertEqual(task.gold_patch, 'private reference patch')
        self.assertEqual((self.root / 'datasets' / f'{frozen}.json').read_bytes(), source)
        newer, next_receipt = self.library.freeze(a['id'])
        self.assertNotEqual(newer, frozen)
        self.assertEqual(receipt['members'][0]['revision'], 1)
        self.assertEqual(next_receipt['members'][0]['revision'], 2)
        self.assertEqual(self.wb.catalog.list(), [])  # Internal run snapshots do not pollute the imported library.

    def test_edit_composition_keeps_removed_cases_and_old_membership(self):
        one, two = self.case(), self.case('task-2')
        collection = self.collection(one, two)
        frozen, receipt = self.library.freeze(collection['id'])
        self.library.save_set({'name': 'Renamed', 'caseIds': [two['id']], 'expectedRevision': 1}, collection['id'])
        self.assertEqual(len(self.library.cases()), 2)
        self.assertEqual([item['id'] for item in self.wb.catalog.tasks(frozen)], ['task-1', 'task-2'])
        self.assertEqual(receipt['name'], 'Suite')
        self.assertEqual(self.library.selection(collection['id'])['dataset']['name'], 'Renamed')

    def test_concurrent_snapshots_share_content_without_partial_files(self):
        case = self.case()
        with ThreadPoolExecutor(max_workers=3) as executor:
            snapshots = list(executor.map(lambda _: self.library.freeze(case['id']), range(3)))
        self.assertEqual(len({key for key, _ in snapshots}), 1)
        self.assertEqual(len({receipt['id'] for _, receipt in snapshots}), 3)
        self.wb.catalog.verify(snapshots[0][0])
        self.assertEqual(len(list((self.root / 'datasets').iterdir())), 1)

    def test_frozen_normalized_metadata_cannot_diverge_from_snapshot_rows(self):
        case = self.case()
        key, _ = self.library.freeze(case['id'])
        record = self.engine.database.get_document('datasets', key)
        record['tasks'][0]['prompt'] = 'Tampered normalized prompt'
        self.engine.database.put_document('datasets', key, record)
        with self.assertRaisesRegex(ValueError, 'metadata has changed'):
            self.wb.catalog.task(key, 'task-1')

    def test_public_import_can_adopt_internal_snapshot_without_overwriting_source(self):
        case = self.case()
        key, _ = self.library.freeze(case['id'])
        raw = self.library.case(case['id'])['row']
        self.wb.catalog.register('Public import', 'custom', [raw])
        self.assertEqual(self.wb.catalog.list()[0]['id'], key)
        collection = self.library.sets()[0]
        self.assertEqual(collection['originDataset'], key)
        self.edit(case, prompt='Unrelated source edits')
        self.assertEqual(self.library.selection(collection['id'])['tasks'][0]['prompt'], raw['prompt'])

    def test_conflicting_edit_is_409_and_does_not_overwrite(self):
        case = self.case()
        self.edit(case, prompt='Winner')
        response = self.client.put('/v1/library/cases/' + case['id'], json={
            'name': 'Loser', 'benchmark': 'custom', 'expectedRevision': 1, 'row': manifest()['rows'][0]})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.library.case(case['id'])['prompt'], 'Winner')
        collection = self.collection(case)
        body = {'name': 'Update', 'caseIds': [case['id']], 'expectedRevision': 1}
        self.assertEqual(self.client.put('/v1/library/sets/' + collection['id'], json=body).status_code, 200)
        self.assertEqual(self.client.put('/v1/library/sets/' + collection['id'], json=body).status_code, 409)

    def test_concurrent_edit_has_exactly_one_winner_across_module_instances(self):
        case = self.case()
        def save(name):
            library = CaseLibrary(self.wb.catalog, self.wb.redact)
            try:
                library.save_case({'name': name, 'benchmark': 'custom', 'row': manifest()['rows'][0], 'expectedRevision': 1}, case['id'])
                return True
            except LibraryConflict:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(save, ['A', 'B'])), [False, True])
        self.assertEqual(self.library.case(case['id'])['revision'], 2)

    def test_duplicate_references_ids_and_cross_protocol_members_are_rejected_atomically(self):
        one, two = self.case(), self.case('task-2')
        collection = self.collection(one, two)
        with self.assertRaises(ValueError):
            self.collection(one, one)
        with self.assertRaises(ValueError):
            self.edit(two, id='task-1')
        self.assertEqual(self.library.case(two['id'])['taskId'], 'task-2')
        official = self.library.save_case({'name': 'Official', 'benchmark': 'swebench', 'row': {
            'instance_id': 'org__project-1', 'repo': 'org/project', 'base_commit': 'a' * 40, 'problem_statement': 'Task'}})
        with self.assertRaises(ValueError):
            self.collection(one, official)
        with self.assertRaises(KeyError):
            self.library.save_set({'name': 'bad', 'caseIds': [one['id'], 'case-missing'], 'expectedRevision': 1}, collection['id'])
        self.assertEqual(self.library.selection(collection['id'])['dataset']['revision'], 1)

    def test_public_inventory_and_snapshot_never_leak_evaluator_material(self):
        case = self.case()
        _, receipt = self.library.freeze(case['id'])
        for path in ('/v1/library', '/v1/library/selections/' + case['id'], '/v1/library/snapshots', '/v1/library/snapshots/' + receipt['id']):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            for secret in ('private test patch', 'private reference patch', 'hiddenPatch', 'goldPatch'):
                self.assertNotIn(secret, response.text)
        operator = self.client.get('/v1/library/cases/' + case['id']).json()
        self.assertEqual(operator['row']['goldPatch'], 'private reference patch')

    def test_legacy_import_migrates_idempotently_without_overwriting_edits(self):
        body = manifest()
        imported = self.wb.catalog.register(body['name'], body['benchmark'], body['rows'])
        path = self.root / 'datasets' / (imported['id'] + '.json')
        before = path.read_bytes()
        first = self.library.sets()
        case = self.library.cases()[0]
        self.edit(case, prompt='Local variant')
        self.assertEqual(self.library.sets(), first)
        self.assertEqual(len(self.library.cases()), 1)
        self.assertEqual(self.library.selection(first[0]['id'])['tasks'][0]['prompt'], 'Local variant')
        self.assertEqual(self.wb.catalog.task(imported['id'], 'task-1').prompt, body['rows'][0]['prompt'])
        self.assertEqual(path.read_bytes(), before)
        restarted = Workbench(self.engine, GitHubClient(None))
        self.assertEqual(restarted.library.sets(), first)

    def test_preflight_does_not_write_and_experiment_captures_before_queueing(self):
        case = self.case()
        collection = self.collection(case)
        selection = self.library.selection(collection['id'])
        spec = self.spec(collection['id'], revision=selection['revision'])
        before = sorted(path.name for path in (self.root / 'datasets').iterdir())
        report = self.wb.preflight(spec)
        self.assertEqual(report['datasetRevision'], selection['revision'])
        self.assertEqual(self.library.snapshots(), [])
        self.assertEqual(before, sorted(path.name for path in (self.root / 'datasets').iterdir()))
        experiment = self.wb.create_experiment(spec)
        frozen_spec = self.engine.database.get_spec(experiment['id'])
        self.assertFalse(self.library.editable(frozen_spec.dataset))
        self.assertEqual(frozen_spec.dataset_snapshot['members'][0]['revision'], 1)
        self.edit(case, prompt='New source')
        self.assertNotEqual(self.library.selection(collection['id'])['revision'], selection['revision'])
        self.assertEqual(self.wb.catalog.task(frozen_spec.dataset, 'task-1').prompt, manifest()['rows'][0]['prompt'])
        self.assertEqual(experiment['datasetSnapshot']['id'], frozen_spec.dataset_snapshot['id'])
        with self.assertRaises(LibraryConflict):
            self.wb.create_experiment(spec)
        self.assertEqual(len(self.engine.database.list_experiments()), 1)

    def test_standalone_generation_freezes_even_before_scheduler_executes(self):
        case = self.case()
        selection = self.library.selection(case['id'])
        body = {'dataset': case['id'], 'datasetRevision': selection['revision'], 'taskId': 'task-1',
                'model': {'provider': 'mock', 'model': 'deterministic', 'maxTokens': 4096},
                'resources': {'network': 'offline'}, 'projectEnvironment': False}
        response = self.client.post('/v1/prepare/context', json=body)
        self.assertEqual(response.status_code, 202, response.text)
        payload = self.engine.database.get_document('operations', response.json()['id'])['payload']
        self.edit(case, prompt='Edited while queued')
        self.assertEqual(payload['datasetSnapshot']['sourceId'], case['id'])
        self.assertEqual(self.wb.catalog.task(payload['dataset'], 'task-1').base_commit, 'a' * 40)
        self.assertEqual(self.client.post('/v1/prepare/context', json=body).status_code, 409)
        self.assertEqual(len(self.engine.database.list_documents('operations')), 1)

    def test_snapshot_only_contains_selected_cases_and_preserves_native_official_row(self):
        row = {'instance_id': 'org__repo-1', 'repo': 'org/repo', 'base_commit': 'a' * 40,
               'problem_statement': 'Repair it', 'patch': 'PRIVATE_ANSWER', 'test_patch': 'PRIVATE_TESTS',
               'FAIL_TO_PASS': '["test"]', 'version': '1.0', 'custom_upstream': {'retain': True}}
        case = self.library.save_case({'name': 'Official case', 'benchmark': 'swebench', 'row': row})
        other = self.library.save_case({'name': 'Other', 'benchmark': 'swebench', 'row': {**row, 'instance_id': 'org__repo-2'}})
        collection = self.collection(case, other)
        key, receipt = self.library.freeze(collection['id'], [case['taskId']])
        self.assertEqual(json.loads((self.root / 'datasets' / f'{key}.json').read_text()), [row])
        self.assertEqual(len(receipt['members']), 1)

    def test_invalid_or_secret_definition_does_not_persist(self):
        for row in (None, [], {}, {**manifest()['rows'][0], 'baseCommit': 'main'}):
            response = self.client.post('/v1/library/cases', json={'name': 'Bad', 'benchmark': 'custom', 'row': row})
            self.assertEqual(response.status_code, 422, response.text)
        secret = 'fixture-only-runtime-private-value'
        with patch.object(self.library, 'redact', side_effect=lambda value: value.replace(secret, '[REDACTED]')):
            for field in ('prompt', 'goldPatch'):
                with self.assertRaises(ValueError):
                    self.library.save_case({'name': 'Secret', 'benchmark': 'custom', 'row': {**manifest()['rows'][0], field: secret}})
        self.assertEqual(self.library.cases(), [])


if __name__ == '__main__':
    unittest.main()

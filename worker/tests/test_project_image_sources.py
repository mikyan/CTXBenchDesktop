import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import docker
from fastapi.testclient import TestClient

from worker.ctxbench_worker.api import create_app
from worker.ctxbench_worker.case_library import LibraryConflict
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.image_sources import ImageSources, normalize_pull_reference
from worker.ctxbench_worker.intranet import IntranetWorkbench
from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from worker.ctxbench_worker.standard_images import StandardImages, swe_image
from worker.ctxbench_worker.workbench import Workbench
from worker.tests.test_intranet import profile
from worker.tests.test_standard_images import Store, rows


TARGET = 'registry.company.example:5000/mirrors/planbenchx86:Company-v2'


class ProjectImageSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = create_mock_engine(self.root)
        self.wb = Workbench(self.engine, None)
        self.op = IntranetWorkbench(self.wb)
        self.store = Store()
        self.store.availability = Mock(return_value='available')
        self.op.standard_images = StandardImages(self.op, lambda: self.store)
        self.dataset = self.wb.catalog.register('CTX', 'ctxbench', rows())['id']
        self.sources = self.wb.image_sources

    def save(self, target=TARGET, revision=0, dataset=None, environment=None, source='org/project:v1'):
        return self.sources.save(dataset or self.dataset, {'expectedRevision': revision,
            'overrides': [{'source': source, 'target': target}]}, environment)

    def test_accepts_literal_pull_and_digest_without_interpreting_shell(self):
        self.assertEqual(normalize_pull_reference('  docker pull ' + TARGET + '\n'), TARGET)
        digest = 'registry.company.example/team/image@sha256:' + 'd' * 64
        self.assertEqual(normalize_pull_reference(digest), digest)
        for bad in ['docker pull --platform linux/amd64 ' + TARGET, 'docker login registry.company.example',
                    TARGET + ';id', TARGET + ' && echo ok', 'docker pull a\ndocker pull b',
                    'https://' + TARGET, 'user:password@' + TARGET, 'namespace/image:v1',
                    '${REGISTRY}/image:v1', 'registry.company.example/../x', 'registry.company.example/image@token',
                    TARGET + ' | cat', '$(id)/repo:v1']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_pull_reference(bad)

    def test_save_is_no_io_and_leaves_dataset_and_company_defaults_unchanged(self):
        before = self.wb.catalog.verify(self.dataset)
        with patch('docker.from_env', side_effect=AssertionError('Saving must not contact Docker')):
            saved = self.save('docker pull ' + TARGET)
        self.assertEqual(saved['overrides'][0]['target'], TARGET)
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(self.wb.catalog.verify(self.dataset), before)
        self.assertEqual(self.engine.database.list_documents('operations'), [])
        self.assertEqual(self.engine.database.list_documents('companyProfiles'), [])

    def test_exact_address_priority_and_scope_isolated_from_other_profiles(self):
        company = self.op.profiles.save({**profile(), 'offline': False,
            'imageMappings': [{'source': 'org/', 'target': 'registry.example/prefix/'}]})
        self.save(environment=company)
        other = self.op.profiles.save({**company['document'], 'name': 'Other'})
        self.assertEqual(self.sources.view(self.dataset)['overrides'], [])
        self.assertEqual(self.sources.view(self.dataset, other)['overrides'], [])
        plan = self.op.standard_images.plan(self.dataset, company)
        self.assertEqual(plan['images'][0]['reference'], TARGET)
        self.assertEqual(plan['imageSources']['profileId'], company['id'])
        self.assertEqual(self.op.profiles.get(company['id']), company)
        self.save('', 1, environment=company)
        self.assertEqual(self.op.standard_images.plan(self.dataset, company)['images'][0]['reference'], 'registry.example/prefix/project:v1')

    def test_download_and_check_freeze_only_selected_addresses_before_mutation(self):
        self.save()
        collection = self.wb.library.adopt(self.dataset)
        plan = self.op.standard_images.plan(collection['id'])
        payload = {'dataset': collection['id'], 'datasetRevision': plan['datasetRevision'],
            'taskIds': ['repo-0', 'repo-1'], 'imageSourcesRevision': 1, 'confirmed': True}
        operation = self.op.enqueue('standard-images', payload)
        self.save('registry.company.example/future:v3', 1)
        result = self.op.execute(operation)
        self.assertEqual(self.store.pulls, [TARGET])
        self.assertEqual(result['images'][0]['reference'], TARGET)
        self.assertEqual(result['taskCount'], 2)
        operation['status'] = 'completed'
        self.wb.db.put_document('operations', operation['id'], operation)
        with self.assertRaises(LibraryConflict):
            self.op.enqueue('image-check', payload)
        payload['imageSourcesRevision'] = 2
        check = self.op.enqueue('image-check', payload)
        self.save('', 2)
        self.op.execute(check)
        self.store.availability.assert_called_once_with('registry.company.example/future:v3')
        self.assertEqual(self.sources.view(self.dataset)['overrides'], [])

    def test_failed_mirror_never_falls_back_or_overwrites_installed_official_tag(self):
        self.save()
        self.store.images['org/project:v1'] = 'sha256:' + 'c' * 64
        self.store.fail = True
        operation = self.op.enqueue('standard-images', {'dataset': self.dataset, 'taskIds': ['repo-0'], 'confirmed': True})
        with self.assertRaisesRegex(ValueError, 'REGISTRY_UNAVAILABLE'):
            self.op.execute(operation)
        self.assertEqual(self.store.pulls, [TARGET])
        self.assertEqual(self.store.images['org/project:v1'], 'sha256:' + 'c' * 64)

    def test_exact_addresses_respect_offline_and_disable_implicit_unmapped_pulls(self):
        self.save()
        frozen = self.sources.freeze(self.dataset)
        sources = ImageSources(frozen['document'])
        self.assertTrue(sources.may_pull('org/project:v1'))
        self.assertFalse(sources.may_pull('unmapped/project:v1'))
        self.assertFalse(sources.may_pull('sha256:' + 'c' * 64))
        offline = ImageSources({**frozen['document'], 'offline': True})
        self.assertEqual(offline.resolve('org/project:v1'), TARGET)
        self.assertFalse(offline.may_pull('org/project:v1'))

    def test_jobs_created_before_any_override_keep_original_sources(self):
        spec = ExperimentSpec('Original source', 'ctxbench', self.dataset, ('none', 'skill-generated'), 1,
            ('repo-0',), ModelConfig('mock', 'chosen-by-user', 'off', 4096),
            'ctxbench/agent-pi:0.1.0', ResourcePolicy(), 42)
        exp = self.wb.create_experiment(spec)
        prep = self.wb.enqueue('context', {'dataset': self.dataset, 'taskId': 'repo-0'})
        operation = self.op.enqueue('standard-images', {'dataset': self.dataset,
            'taskIds': ['repo-0'], 'confirmed': True, 'imageSourcesRevision': 0})
        self.save()
        self.op.execute(operation)
        self.assertEqual(self.store.pulls, ['org/project:v1'])
        self.assertEqual(prep['payload'].get('environment', {}), {})
        self.wb.control(exp['id'], 'cancel'); self.wb.control(exp['id'], 'retry')
        self.assertEqual(self.wb.db.get_spec(exp['id']).company_environment, {})

    def test_new_experiments_and_independent_context_inherit_but_old_jobs_do_not_follow_edits(self):
        self.save()
        model = ModelConfig('mock', 'chosen-by-user', 'off', 4096)
        spec = ExperimentSpec('Image capture', 'ctxbench', self.dataset, ('none', 'skill-generated'), 1,
            ('repo-0',), model, 'ctxbench/agent-pi:0.1.0', ResourcePolicy(), 42)
        exp = self.wb.create_experiment(spec)
        frozen = self.wb.db.get_spec(exp['id'])
        self.assertEqual(frozen.model, model)
        self.assertEqual(frozen.agent_image, spec.agent_image)
        self.assertEqual(ImageSources(frozen.company_environment['document']).resolve('org/project:v1'), TARGET)
        prep = self.wb.enqueue('context', {'dataset': self.dataset, 'taskId': 'repo-0'})
        self.save('registry.company.example/future:v3', 1)
        self.wb.control(exp['id'], 'cancel'); self.wb.control(exp['id'], 'retry')
        restarted = Workbench(self.engine, None)
        self.assertEqual(restarted.db.get_spec(exp['id']).company_environment, frozen.company_environment)
        self.assertEqual(prep['payload']['environment'], frozen.company_environment)
        future = restarted.create_experiment(spec)
        self.assertEqual(restarted.db.get_spec(future['id']).company_environment['document']['imageOverrides'][0]['target'], 'registry.company.example/future:v3')

    def test_swe_solver_and_grader_can_use_two_different_full_addresses(self):
        dataset = self.wb.catalog.register('SWE', 'swebench', [{'instance_id': 'matplotlib__matplotlib-1', 'repo': 'matplotlib/matplotlib', 'base_commit': 'a' * 40, 'problem_statement': 'Fix'}])['id']
        solver = swe_image('matplotlib__matplotlib-1', solver=True)
        grader = swe_image('matplotlib__matplotlib-1')
        self.save(dataset=dataset, source=solver)
        self.save('registry.company.example/grade@sha256:' + 'd' * 64, 1, dataset, source=grader)
        plan = self.op.standard_images.plan(dataset)
        self.assertEqual(len(plan['images']), 2)
        self.assertEqual(plan['images'][0]['reference'], TARGET)
        self.assertEqual(plan['images'][1]['reference'], 'registry.company.example/grade@sha256:' + 'd' * 64)
        self.assertEqual(self.wb.catalog.tasks(dataset)[0]['image'], None)

    def test_shared_image_survives_recomposition_but_custom_cases_are_unaffected(self):
        self.save()
        collection = self.wb.library.adopt(self.dataset)
        single = collection['caseIds'][0]
        other = self.wb.library.save_set({'name': 'Subset', 'caseIds': [single]})
        self.assertEqual(self.op.standard_images.plan(other['id'])['images'][0]['reference'], TARGET)
        custom = self.wb.catalog.register('Custom', 'custom', [{'id': 'x', 'repository': '/repo', 'baseCommit': 'a' * 40, 'prompt': 'Fix', 'image': 'org/project:v1', 'test': {'command': ['true']}}])['id']
        self.assertEqual(self.sources.freeze(custom), {})
        with self.assertRaises(ValueError): self.save(dataset=custom)

    def test_api_validation_conflicts_and_secrets_do_not_persist(self):
        with TestClient(create_app(self.engine)) as client:
            path = f'/v1/datasets/{self.dataset}/project-image-sources'
            body = {'overrides': [{'source': 'org/project:v1', 'target': 'docker pull ' + TARGET}], 'expectedRevision': 0}
            self.assertEqual(client.put(path, json=body).status_code, 200)
            self.assertEqual(client.put(path, json=body).status_code, 409)
            for changes in [{'overrides': [{'source': 'other/image:v1', 'target': TARGET}]},
                            {'overrides': [{'source': 'org/project:v1', 'target': 'https://user:SECRET@registry.example/image'}]},
                            {'datasetRevision': 'stale'}, {'overrides': None}]:
                response = client.put(path, json={**body, 'expectedRevision': 1, **changes})
                self.assertIn(response.status_code, [409, 422])
                self.assertNotIn('SECRET', response.text)
            self.assertEqual(client.get(path).json()['revision'], 1)


if __name__ == '__main__': unittest.main()

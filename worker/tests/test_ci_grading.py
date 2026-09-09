import copy
import io
import json
import os
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from worker.ctxbench_worker.ci_config import ci_connection, ci_test
from worker.ctxbench_worker.ci_grading import CIGrading, gate_result
from worker.ctxbench_worker.ci_protocol import CIError, ExplicitAuth, Transport
from worker.ctxbench_worker.ci_reports import junit_counts
from worker.ctxbench_worker.datasets import custom_task, task_document
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.intranet import IntranetWorkbench
from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from worker.ctxbench_worker.runtime import git, seal
from worker.ctxbench_worker.workbench import Workbench, Interrupted
from worker.tests.test_workbench import cleanup_fixture, FixtureRunner


CONNECTION = {'name': 'Personal CI', 'provider': 'github-actions', 'apiUrl': 'https://api.github.com', 'repository': 'team/backend', 'workflow': 'ci.yml'}
POLICY = {'connectionId': 'a' * 64, 'requiredJobs': ['build', 'test'], 'reportArtifact': '', 'minTests': 1, 'timeoutMinutes': 1, 'allowRemoteExecution': True}
STATE = {'status': 'completed', 'conclusion': 'success', 'jobs': [{'name': n, 'status': 'completed', 'conclusion': 'success'} for n in ['build', 'test']]}


def archive(xml):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as bundle: bundle.writestr('results.xml', xml)
    return output.getvalue()


class CIPolicyTests(unittest.TestCase):
    def test_grading_requires_successful_complete_gates_not_just_workflow_badge(self):
        self.assertTrue(gate_result(POLICY, STATE)['resolved'])
        self.assertIsNone(gate_result(POLICY, STATE)['testCounts'])
        self.assertFalse(gate_result(POLICY, {**STATE, 'conclusion': 'failure'})['resolved'])
        failed = copy.deepcopy(STATE); failed['jobs'][1]['conclusion'] = 'failure'
        self.assertFalse(gate_result(POLICY, failed)['resolved'])
        for status in ['cancelled', 'skipped', 'timed_out', 'neutral', None]:
            with self.subTest(status=status), self.assertRaises(CIError): gate_result(POLICY, {**STATE, 'conclusion': status})
        for jobs in [[], STATE['jobs'] * 2, [{**job, 'conclusion': 'skipped'} for job in STATE['jobs']]]:
            with self.assertRaises(CIError): gate_result(POLICY, {**STATE, 'jobs': jobs})

    def test_junit_leaf_counts_include_errors_and_skips_without_double_counting_suites(self):
        counts = junit_counts(archive('<testsuites tests="999"><testsuite tests="999"><testcase/><testcase><failure/></testcase><testcase><error/></testcase><testcase><skipped/></testcase></testsuite></testsuites>'))
        self.assertEqual(counts, {'total': 4, 'passed': 1, 'failures': 1, 'errors': 1, 'skipped': 1})
        self.assertFalse(gate_result({**POLICY, 'reportArtifact': 'reports'}, STATE, counts)['resolved'])
        with self.assertRaises(CIError): gate_result({**POLICY, 'reportArtifact': 'reports', 'minTests': 4}, STATE, counts)

    def test_empty_invalid_entities_and_utf16_dtd_reports_are_not_passes(self):
        for payload in [b'not-a-zip', archive('<testsuite tests="5"/>'), archive('<testsuite>'),
                        archive('<!DOCTYPE x [<!ENTITY test "test">]><testsuite><testcase name="&test;"/></testsuite>'),
                        archive('<!DOCTYPE x [<!ENTITY test "test">]><testsuite><testcase name="&test;"/></testsuite>'.encode('utf-16'))]:
            with self.assertRaises(CIError): junit_counts(payload)
        counts = junit_counts(archive('<testsuite><testcase><skipped/></testcase></testsuite>'))
        with self.assertRaises(CIError): gate_result({**POLICY, 'reportArtifact': 'reports'}, STATE, counts)

    def test_configuration_rejects_secrets_and_requires_explicit_remote_consent(self):
        self.assertEqual(ci_connection(CONNECTION), CONNECTION)
        for url in ['http://platform.example', 'https://user:pass@platform.example', 'https://platform.example?token=value']:
            with self.assertRaises(ValueError): ci_connection({**CONNECTION, 'apiUrl': url})
        for changes in [{'allowRemoteExecution': False}, {'requiredJobs': ['test', 'test']}, {'timeoutMinutes': True}, {'token': 'secret'}]:
            with self.assertRaises(ValueError): ci_test({**POLICY, **changes})


class CIIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(cleanup_fixture, directory)
        self.root = Path(directory.name)
        self.wb = Workbench(create_mock_engine(self.root / 'worker'), None)
        self.ci = self.wb.ci
        self.connection = self.ci.save_connection(CONNECTION)
        self.ci.set_credential(self.connection['id'], {'token': 'CI_ONLY_SYNTHETIC_CREDENTIAL'})
        self.policy = {**POLICY, 'connectionId': self.connection['id']}
        self.repo = self.root / 'repo'; self.repo.mkdir()
        (self.repo / 'app.py').write_text('value = 1\n')
        workflow = self.repo / '.github' / 'workflows'; workflow.mkdir(parents=True)
        (workflow / 'ci.yml').write_text('on: workflow_dispatch\n')
        self.base = seal(self.repo)
        self.base_tree = git(self.repo, 'rev-parse', 'HEAD^{tree}').decode().strip()
        self.row = {'id': 'backend-1', 'repository': 'https://github.com/team/backend.git', 'baseCommit': self.base,
            'prompt': 'Fix the calculation.', 'image': 'test/image:v1', 'test': {'ci': self.policy}}
        self.task = custom_task(self.row)
        self.wb.runtime.baseline = Mock(return_value=(self.repo, '2020-01-01T00:00:00Z'))
        (self.repo / 'app.py').write_text('value = 2\n')
        self.patch = self.root / 'candidate.patch'; self.patch.write_bytes(git(self.repo, 'diff', '--binary', 'HEAD'))
        (self.repo / 'app.py').write_text('value = 1\n')
        self.platform = Mock()
        self.target = {'repository': CONNECTION['repository'], 'baseCommit': self.base, 'baseTree': self.base_tree,
                       'workflowBlob': 'f' * 40, 'protectedPaths': ['.github/']}
        self.platform.prepare.return_value = self.target
        self.platform.poll.return_value = copy.deepcopy(STATE)
        self.platform.submit.side_effect = lambda target, candidate, receipt, save: (receipt.update(remoteId='remote-1', commit='b' * 40), save())
        self.ci.adapters = {'github-actions': lambda *_: self.platform}

    def experiment(self):
        dataset = self.wb.catalog.register('CI case', 'custom', [self.row])['id']
        spec = ExperimentSpec('CI', 'custom', dataset, ('none', 'skill-generated'), 1, (self.task.id,),
            ModelConfig('fixture', 'test', 'off', 1000), 'agent:v1', ResourcePolicy(), 1)
        exp = self.wb.create_experiment(spec)
        return spec, self.wb.db.list_runs(exp['id'])[0]

    def test_real_git_candidate_is_baseline_plus_patch_and_ci_stays_evaluator_only(self):
        frozen = self.ci.prepare(self.task)
        candidate = self.ci.candidate(self.task, self.patch, self.target)
        self.assertEqual(len(candidate['files']), 1)
        self.assertEqual(candidate['files'][0]['path'], 'app.py')
        self.assertNotIn('ci', self.task.solver_payload())
        _, run = self.experiment()
        grade = self.ci.grade(self.task, self.patch, run, frozen, lambda: None, poll_seconds=0)
        self.assertTrue(grade['resolved'])
        self.assertEqual(grade['gradingMode'], 'ci')
        self.assertNotIn('CI_ONLY_SYNTHETIC_CREDENTIAL', json.dumps(self.wb.db.list_documents('ciEvaluations')))
        self.assertFalse('CI_ONLY_SYNTHETIC_CREDENTIAL' in str(getattr(self.wb.engine.runner, 'env_allowlist', ())))
        self.assertNotIn('CI_ONLY_SYNTHETIC_CREDENTIAL', os.environ.values())

    def test_ci_configuration_edits_do_not_change_frozen_case_snapshots(self):
        case = self.wb.library.save_case({'name': 'CI', 'benchmark': 'custom', 'row': self.row})
        frozen, _ = self.wb.library.freeze(case['id'])
        changed = {**self.row, 'test': {'ci': {**self.policy, 'requiredJobs': ['different']}}}
        self.wb.library.save_case({'name': 'CI', 'benchmark': 'custom', 'row': changed, 'expectedRevision': 1}, case['id'])
        self.assertEqual(self.wb.catalog.task(frozen, self.task.id).ci['requiredJobs'], ['build', 'test'])

    def test_legacy_catalog_and_checkpoint_documents_do_not_gain_new_null_fields(self):
        old = custom_task({**self.row, 'test': {'command': ['true']}})
        self.assertNotIn('ci', task_document(old))
        dataset = self.wb.catalog.register('Old', 'custom', [{**self.row, 'test': {'command': ['true']}}])
        self.assertNotIn('ci', self.wb.catalog.verify(dataset['id'])['tasks'][0])

    def test_protected_workflow_patch_is_rejected_before_remote_submission(self):
        path = self.repo / '.github/workflows/ci.yml'
        path.write_text('on: push\n')
        self.patch.write_bytes(git(self.repo, 'diff', '--binary', 'HEAD'))
        path.write_text('on: workflow_dispatch\n')
        with self.assertRaisesRegex(CIError, 'protected'): self.ci.candidate(self.task, self.patch, self.target)
        self.platform.submit.assert_not_called()

    def test_hidden_reference_material_and_local_self_test_never_upload(self):
        for row in [{**self.row, 'goldPatch': 'HIDDEN'}, {**self.row, 'goldPatch': ''},
                    {**self.row, 'test': {**self.row['test'], 'hiddenPatch': 'HIDDEN'}}]:
            with self.assertRaises(ValueError): custom_task(row)
        operator = IntranetWorkbench(self.wb)
        with self.assertRaisesRegex(ValueError, 'local self-test'):
            operator.enqueue('probe', {'name': 'CI', 'benchmark': 'custom', 'rows': [self.row]})
        self.platform.submit.assert_not_called()

    def test_platform_failure_remains_retryable_infrastructure_error(self):
        _, run = self.experiment(); frozen = self.ci.prepare(self.task)
        self.platform.poll.return_value = {**STATE, 'conclusion': 'cancelled'}
        with self.assertRaises(CIError): self.ci.grade(self.task, self.patch, run, frozen, lambda: None, poll_seconds=0)
        self.assertNotIn('testsPassed', self.wb.db.get_run(run['id']))

    def test_reports_record_content_hash_without_persisting_raw_report_material(self):
        _, run = self.experiment()
        task = replace(self.task, ci={**self.policy, 'reportArtifact': 'reports'})
        report = archive('<testsuite><testcase name="PRIVATE_TEST_NAME"/></testsuite>')
        self.platform.report.return_value = report
        result = self.ci.grade(task, self.patch, run, self.ci.prepare(task), lambda: None, poll_seconds=0)
        self.assertEqual(result['testCounts']['total'], 1)
        self.assertEqual(len(result['report']['sha256']), 64)
        self.assertNotIn('PRIVATE_TEST_NAME', json.dumps(result))

    def test_full_prepare_solve_ci_grade_pair_uses_one_frozen_target_and_context(self):
        runner = FixtureRunner(); original = runner.run
        def run(spec):
            result = original(spec)
            if spec.mode == 'solve': (Path(spec.output_dir) / 'graded.patch').write_bytes(self.patch.read_bytes())
            return result
        runner.run = run; self.wb.engine.runner = runner
        spec, first = self.experiment()
        with patch('worker.ctxbench_worker.workbench.DockerRunner', FixtureRunner), \
             patch.object(self.wb.runtime, 'resolve_image', return_value='sha256:' + 'a' * 64), \
             patch.object(self.wb.runtime, 'prepare_test_image', return_value='sha256:' + 'b' * 64):
            result = self.wb.run_experiment(first['experimentId'])
            self.assertEqual(result['status'], 'completed')
            self.wb.run_experiment(first['experimentId'])
        self.assertEqual(self.platform.prepare.call_count, 1)
        self.assertEqual(len([call for call in runner.calls if call.mode == 'generate-context']), 1)
        solves = [call for call in runner.calls if call.mode == 'solve']
        self.assertEqual(len(solves), 2)
        self.assertEqual(solves[0].prompt, solves[1].prompt)
        self.assertEqual(solves[0].model, solves[1].model)
        self.assertEqual(solves[0].env_names, solves[1].env_names)
        runs = self.wb.db.list_runs(first['experimentId'])
        self.assertTrue(all(run['testsPassed'] for run in runs))
        self.assertEqual(len({run['pairingHash'] for run in runs}), 1)
        self.assertEqual(len({row['id'] for row in self.wb.db.list_documents('ciEvaluations')}), 2)

    def test_platform_preparation_failure_happens_before_any_paid_stage(self):
        self.wb.engine.runner = FixtureRunner()
        _, first = self.experiment()
        self.platform.prepare.side_effect = CIError('platform unavailable')
        with patch('worker.ctxbench_worker.workbench.DockerRunner', FixtureRunner), \
             patch.object(self.wb.runtime, 'resolve_image', return_value='image'):
            with self.assertRaises(CIError): self.wb.run_experiment(first['experimentId'])
        self.assertEqual(self.wb.engine.runner.calls, [])

    def test_restored_experiment_requires_session_token_before_paid_stages(self):
        self.wb.engine.runner = FixtureRunner()
        _, first = self.experiment()
        frozen = self.ci.prepare(self.task)
        self.wb.db.put_document('prepared', first['experimentId'], {'id': first['experimentId'], 'ciTargets': {self.task.id: frozen}})
        self.ci.credentials.clear()
        with patch('worker.ctxbench_worker.workbench.DockerRunner', FixtureRunner):
            with self.assertRaisesRegex(CIError, 'token first'): self.wb.run_experiment(first['experimentId'])
        self.assertEqual(self.wb.engine.runner.calls, [])

    def test_gateway_target_requires_repository_and_immutable_workflow_revision(self):
        for changes in [{'repository': 'other/repo'}, {'workflowBlob': ''}]:
            self.platform.prepare.return_value = {**self.target, **changes}
            with self.assertRaises(CIError): self.ci.prepare(self.task)

    def test_interruption_stops_before_submission(self):
        _, run = self.experiment(); frozen = self.ci.prepare(self.task)
        with self.assertRaises(Interrupted):
            self.ci.grade(self.task, self.patch, run, frozen, Mock(side_effect=Interrupted('pause')))
        self.platform.submit.assert_not_called()

    def test_cancel_after_local_timeout_still_cancels_owned_remote_evaluation(self):
        _, run = self.experiment()
        self.wb.db.put_document('ciEvaluations', 'pending-evaluation', {'id': 'pending-evaluation', 'runId': run['id'],
            'connectionId': self.connection['id'], 'dispatchIntent': True})
        self.wb.db.update_run(run['id'], 'failed', {'failure': 'CI: waiting timed out.'})
        self.wb.db.set_experiment_status(run['experimentId'], 'failed')
        self.wb.control(run['experimentId'], 'cancel')
        self.assertEqual(self.platform.cancel.call_count, 1)

    def test_credentials_and_connection_api_never_return_token_or_allow_endpoint_reuse(self):
        from fastapi.testclient import TestClient
        from worker.ctxbench_worker.api import create_app
        client = TestClient(create_app(self.wb.engine))
        self.addCleanup(client.close)
        response = client.post('/v1/ci/connections', json=CONNECTION)
        key = response.json()['id']
        token = 'DO_NOT_PERSIST_THIS_SYNTHETIC_TOKEN'
        response = client.post(f'/v1/ci/connections/{key}/credential', json={'token': token})
        self.assertEqual(response.json(), {'credentialConfigured': True})
        self.assertNotIn(token, client.get('/v1/ci/connections').text)
        changed = client.post('/v1/ci/connections', json={**CONNECTION, 'apiUrl': 'https://company.example/api/v3'}).json()
        self.assertNotEqual(changed['id'], key)
        self.assertFalse(changed['credentialConfigured'])
        self.assertNotIn(token, self.wb.db.path.read_bytes().decode(errors='replace'))


class TransportTests(unittest.TestCase):
    def response(self, code, content=b'{}', headers=None):
        response = Mock(status_code=code, headers=headers or {})
        response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [content]
        return response

    def test_authenticated_requests_do_not_follow_redirects_and_errors_do_not_echo(self):
        http = Transport('https://api.github.com', 'SYNTHETIC_TOKEN')
        with patch('requests.request', return_value=self.response(401, b'SYNTHETIC_TOKEN SERVER_SECRET')) as request:
            with self.assertRaises(CIError) as error: http.request('GET', '/repos/team/backend')
            self.assertNotIn('SYNTHETIC_TOKEN', str(error.exception))
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
        with patch('requests.request', return_value=self.response(302, headers={'Location': 'https://elsewhere.example'})):
            with self.assertRaises(CIError): http.request('GET', '/repos/team/backend')

    def test_report_redirects_drop_platform_authorization(self):
        http = Transport('https://api.github.com', 'SYNTHETIC_TOKEN')
        with patch('requests.request', return_value=self.response(302, headers={'Location': 'https://artifacts.example/signed'})), \
             patch('requests.get', return_value=self.response(200, b'zip')) as get:
            self.assertEqual(http.request('GET', '/artifact/zip', allowed=(302,), binary=True), b'zip')
            self.assertNotIn('headers', get.call_args.kwargs)
            self.assertIsInstance(get.call_args.kwargs['auth'], ExplicitAuth)

    def test_explicit_auth_never_uses_netrc_or_forwards_api_token_to_reports(self):
        import requests
        with patch('requests.sessions.get_netrc_auth', side_effect=AssertionError('netrc must not be consulted')):
            with requests.Session() as session:
                api = session.prepare_request(requests.Request('GET', 'https://api.github.com',
                    headers={'Authorization': 'Bearer SYNTHETIC_TOKEN'}, auth=ExplicitAuth()))
                report = session.prepare_request(requests.Request('GET', 'https://artifacts.example/signed', auth=ExplicitAuth()))
        self.assertEqual(api.headers['Authorization'], 'Bearer SYNTHETIC_TOKEN')
        self.assertNotIn('Authorization', report.headers)


if __name__ == '__main__': unittest.main()

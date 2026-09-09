import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from worker.ctxbench_worker.ci_github import GitHubActions
from worker.ctxbench_worker.ci_http import HttpCI
from worker.ctxbench_worker.ci_protocol import CIError
from worker.tests.test_ci_grading import CONNECTION


class GitHubAdapterTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.commit = 'b' * 40
        self.tree = 'c' * 40
        self.target = {'baseCommit': 'a' * 40, 'baseTree': 'd' * 40, 'workflowId': 123}
        self.receipt = {'id': 'e' * 64, 'branch': 'ctxbench-eval/' + 'e' * 32, 'target': self.target}
        self.candidate = {'treeSha': self.tree, 'files': [{'path': 'app.py', 'mode': '100644', 'base64': 'dmFsdWUgPSAyCg=='}]}
        self.run = {'id': 456, 'head_sha': self.commit, 'head_branch': self.receipt['branch'], 'workflow_id': 123,
            'event': 'workflow_dispatch', 'repository': {'full_name': 'team/backend'}, 'run_attempt': 1,
            'status': 'completed', 'conclusion': 'success'}
        self.branch_sha = None
        self.dispatch_failure = None
        self.jobs = [{'name': 'test', 'status': 'completed', 'conclusion': 'success', 'head_sha': self.commit, 'run_id': 456}]
        self.http = Mock()
        self.http.request.side_effect = self.request
        self.adapter = GitHubActions(CONNECTION, self.http)

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, copy.deepcopy(kwargs)))
        if path.endswith('/git/commits/' + 'a' * 40): return {'sha': 'a' * 40, 'tree': {'sha': 'd' * 40}}
        if path.endswith('/actions/workflows/ci.yml'): return {'state': 'active', 'path': '.github/workflows/ci.yml', 'id': 123}
        if '/contents/' in path: return {'type': 'file', 'sha': 'f' * 40}
        if method == 'POST' and path.endswith('/git/blobs'): return {'sha': 'f' * 40}
        if path.endswith('/git/trees'): return {'sha': self.tree}
        if path.endswith('/git/commits'): return {'sha': self.commit}
        if '/git/ref/heads/' in path: return {'object': {'sha': self.branch_sha}} if self.branch_sha else {'message': 'Not Found'}
        if path.endswith('/git/refs'):
            self.branch_sha = kwargs['body']['sha']; return {'object': {'sha': self.branch_sha}}
        if path.endswith('/dispatches'):
            if self.dispatch_failure: raise self.dispatch_failure
            return {}  # API versions returning 204 must also work.
        if path.endswith('/actions/workflows/123/runs'): return {'total_count': 1, 'workflow_runs': [self.run]}
        if path.endswith('/actions/runs/456'): return self.run
        if path.endswith('/attempts/1/jobs'):
            page = kwargs['query']['page']; return {'total_count': len(self.jobs), 'jobs': self.jobs[(page-1)*100:page*100]}
        if path.endswith('/actions/runs/456/artifacts'): return {'total_count': 1, 'artifacts': [{'name': 'reports', 'id': 789, 'expired': False, 'workflow_run': {'head_sha': self.commit}}]}
        if path.endswith('/artifacts/789/zip'): return b'zip'
        if path.endswith('/cancel'): return {}
        raise AssertionError((method, path, kwargs))

    def test_preparation_reads_baseline_workflow_without_creating_remote_objects(self):
        target = self.adapter.prepare(SimpleNamespace(repository='https://github.com/team/backend.git', base_commit='a' * 40))
        self.assertEqual(target['workflowBlob'], 'f' * 40)
        self.assertTrue(all(method == 'GET' for method, _, _ in self.calls))
        with self.assertRaises(CIError): self.adapter.prepare(SimpleNamespace(repository='https://github.com/other/backend.git', base_commit='a' * 40))

    def test_submission_uploads_only_changed_blobs_and_never_force_pushes(self):
        snapshots = []
        self.adapter.submit(self.target, self.candidate, self.receipt, lambda: snapshots.append(copy.deepcopy(self.receipt)))
        self.assertTrue(self.receipt['dispatchIntent'])
        refs = [body['body'] for _, path, body in self.calls if path.endswith('/git/refs')]
        self.assertEqual(refs, [{'ref': 'refs/heads/' + self.receipt['branch'], 'sha': self.commit}])
        self.assertFalse(any(method in {'PATCH', 'DELETE'} for method, _, _ in self.calls))
        before = len(self.calls)
        self.adapter.submit(self.target, self.candidate, self.receipt, lambda: None)
        self.assertEqual(len(self.calls), before)

    def test_ambiguous_dispatch_error_preserves_intent_and_retry_does_not_dispatch_twice(self):
        self.dispatch_failure = CIError('uncertain network failure')
        with self.assertRaises(CIError): self.adapter.submit(self.target, self.candidate, self.receipt, lambda: None)
        self.assertTrue(self.receipt['dispatchIntent'])
        self.dispatch_failure = None
        self.adapter.submit(self.target, self.candidate, self.receipt, lambda: None)
        self.assertEqual(len([1 for _, path, _ in self.calls if path.endswith('/dispatches')]), 1)
        result = self.adapter.poll(self.receipt)
        self.assertEqual(self.receipt['remoteId'], 456)
        self.assertEqual(result['conclusion'], 'success')

    def test_definite_permission_denial_can_retry_after_operator_updates_token(self):
        self.dispatch_failure = CIError('denied', 403)
        with self.assertRaises(CIError): self.adapter.submit(self.target, self.candidate, self.receipt, lambda: None)
        self.assertFalse(self.receipt['dispatchIntent'])
        self.dispatch_failure = None
        self.adapter.submit(self.target, self.candidate, self.receipt, lambda: None)
        self.assertTrue(self.receipt['dispatchIntent'])

    def test_existing_branch_collision_is_never_overwritten(self):
        self.branch_sha = '9' * 40
        with self.assertRaisesRegex(CIError, 'collision'): self.adapter.submit(self.target, self.candidate, self.receipt, lambda: None)
        self.assertFalse(any(path.endswith('/git/refs') or path.endswith('/dispatches') for _, path, _ in self.calls))

    def test_run_sha_workflow_event_repository_branch_and_attempt_are_bound(self):
        self.receipt.update(commit=self.commit, remoteId=456, attempt=1)
        for change in [{'head_sha': '9' * 40}, {'head_branch': 'main'}, {'workflow_id': 999}, {'event': 'push'}, {'repository': {'full_name': 'elsewhere/repo'}}, {'run_attempt': 2}]:
            original = self.run
            self.run = {**original, **change}
            with self.subTest(change=change), self.assertRaises(CIError): self.adapter.poll(self.receipt)
            self.run = original
        self.assertEqual(self.adapter.poll(self.receipt)['url'], 'https://github.com/team/backend/actions/runs/456')

    def test_more_than_one_page_of_jobs_and_artifact_identity(self):
        self.receipt.update(commit=self.commit, remoteId=456)
        self.jobs = [{**self.jobs[0], 'name': str(index)} for index in range(101)]
        self.assertEqual(len(self.adapter.poll(self.receipt)['jobs']), 101)
        self.assertEqual(self.adapter.report(self.receipt, 'reports'), b'zip')
        with self.assertRaises(CIError): self.adapter.report(self.receipt, 'missing')

    def test_cancel_validates_ownership_and_does_not_delete_branch(self):
        self.receipt.update(commit=self.commit, remoteId=456)
        self.run['status'] = 'in_progress'
        self.adapter.cancel(self.receipt)
        self.assertTrue(any(path.endswith('/cancel') for _, path, _ in self.calls))
        self.calls.clear(); self.run['head_sha'] = '9' * 40
        with self.assertRaises(CIError): self.adapter.cancel(self.receipt)
        self.assertFalse(any(method != 'GET' for method, _, _ in self.calls))


class CompanyAdapterTests(unittest.TestCase):
    def test_uncertain_submission_keeps_identity_for_retry_and_cancel(self):
        http = Mock(); adapter = HttpCI(CONNECTION, http)
        receipt = {'id': 'a' * 64, 'treeSha': 'b' * 40}
        http.request.side_effect = CIError('timeout')
        saved = []
        with self.assertRaises(CIError): adapter.submit({}, {}, receipt, lambda: saved.append(copy.deepcopy(receipt)))
        self.assertTrue(saved[0]['dispatchIntent'])
        http.request.side_effect = None
        adapter.cancel(receipt)
        self.assertEqual(http.request.call_args.args, ('POST', '/v1/evaluations/' + receipt['id'] + '/cancel'))

    def test_company_gateway_uses_idempotent_evaluation_id_and_checks_tree_binding(self):
        http = Mock(); adapter = HttpCI(CONNECTION, http)
        receipt = {'id': 'a' * 64, 'treeSha': 'b' * 40}
        http.request.return_value = {'evaluationId': receipt['id'], 'treeSha': receipt['treeSha'], 'commit': 'c' * 40}
        adapter.submit({'baseCommit': 'd' * 40}, {'treeSha': receipt['treeSha'], 'files': []}, receipt, lambda: None)
        self.assertEqual(http.request.call_args.args[0], 'PUT')
        adapter.poll(receipt)
        http.request.return_value = {'evaluationId': receipt['id'], 'treeSha': '0' * 40}
        with self.assertRaises(CIError): adapter.poll(receipt)


if __name__ == '__main__': unittest.main()

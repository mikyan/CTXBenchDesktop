"""GitHub Actions adapter. Git objects/Actions endpoints stay out of the grader."""
from urllib.parse import quote, urlsplit
from .ci_protocol import CIError


class GitHubActions:
    def __init__(self, config, transport):
        self.config, self.http = config, transport
        self.repo = '/repos/' + config['repository']

    def prepare(self, task):
        source = urlsplit(task.repository)
        api = urlsplit(self.config['apiUrl'])
        host = 'github.com' if api.hostname == 'api.github.com' else api.hostname
        if source.hostname != host or source.path.strip('/').removesuffix('.git').lower() != self.config['repository'].lower():
            raise CIError('CI: GitHub target must be the same repository as the task baseline. Use a dedicated evaluation repository as the task source.')
        commit = self.http.request('GET', self.repo + '/git/commits/' + task.base_commit)
        if commit['sha'].lower() != task.base_commit.lower(): raise CIError('CI: remote baseline commit mismatch.')
        workflow = self.http.request('GET', self.repo + '/actions/workflows/' + quote(self.config['workflow'], safe=''))
        path = workflow.get('path')
        if workflow.get('state') != 'active' or not isinstance(path, str) or not path.startswith('.github/workflows/'):
            raise CIError('CI: select an active workflow under .github/workflows, supporting workflow_dispatch.')
        content = self.http.request('GET', self.repo + '/contents/' + quote(path, safe='/'), query={'ref': task.base_commit})
        if content.get('type') != 'file': raise CIError('CI: the selected workflow is missing from the baseline commit.')
        return {'repository': self.config['repository'], 'baseCommit': task.base_commit, 'baseTree': commit['tree']['sha'],
                'workflowId': workflow['id'], 'workflowPath': path, 'workflowBlob': content['sha'],
                'protectedPaths': ['.github/']}

    def submit(self, target, candidate, receipt, save):
        if not receipt.get('commit'):
            tree = []
            for file in candidate['files']:
                blob = self.http.request('POST', self.repo + '/git/blobs', body={'content': file['base64'], 'encoding': 'base64'})['sha'] if file['mode'] != '000000' else None
                tree.append({'path': file['path'], 'mode': file['mode'] if blob else '100644', 'type': 'blob', 'sha': blob})
            tree_sha = self.http.request('POST', self.repo + '/git/trees', body={'base_tree': target['baseTree'], 'tree': tree})['sha'] if tree else target['baseTree']
            if tree_sha != candidate['treeSha']: raise CIError('CI: uploaded Git tree does not match the graded candidate.')
            # Fixed author/time makes commit creation deterministic after a crash.
            who = {'name': 'CTXBench evaluation', 'email': 'evaluation@ctxbench.invalid', 'date': '2000-01-01T00:00:00Z'}
            commit = self.http.request('POST', self.repo + '/git/commits', body={'message': 'CTXBench evaluation ' + receipt['id'],
                'tree': tree_sha, 'parents': [target['baseCommit']], 'author': who, 'committer': who})['sha']
            receipt.update(commit=commit); save()
        if not receipt.get('branchCreated'):
            path = self.repo + '/git/ref/heads/' + quote(receipt['branch'], safe='/')
            existing = self.http.request('GET', path, allowed=(200, 404))
            if existing.get('object'):
                if existing['object']['sha'] != receipt['commit']: raise CIError('CI: evaluation branch collision; existing branch was not overwritten.')
            else:
                self.http.request('POST', self.repo + '/git/refs', body={'ref': 'refs/heads/' + receipt['branch'], 'sha': receipt['commit']})
            receipt.update(branchCreated=True); save()
        if not receipt.get('dispatchIntent'):
            # Persist intent BEFORE dispatch: ambiguous HTTP failure must never
            # silently trigger duplicate pipelines on retry.
            receipt.update(dispatchIntent=True); save()
            try:
                result = self.http.request('POST', self.repo + f"/actions/workflows/{target['workflowId']}/dispatches", body={'ref': receipt['branch']})
            except CIError as error:
                if error.status in {400, 401, 403, 404, 422}:
                    receipt['dispatchIntent'] = False; save()
                raise
            if result.get('workflow_run_id'): receipt['remoteId'] = result['workflow_run_id']
            save()

    def _run(self, receipt):
        if not receipt.get('remoteId'):
            result = self.http.request('GET', self.repo + f"/actions/workflows/{receipt['target']['workflowId']}/runs",
                query={'branch': receipt['branch'], 'head_sha': receipt['commit'], 'event': 'workflow_dispatch', 'per_page': 100})
            if result.get('total_count', 0) > 100: raise CIError('CI: too many matching workflow runs; refusing ambiguous results.')
            runs = [run for run in result['workflow_runs'] if run.get('head_sha') == receipt['commit'] and run.get('head_branch') == receipt['branch']]
            if len(runs) > 1: raise CIError('CI: more than one matching workflow run; refusing an ambiguous grade.')
            if not runs: return None
            receipt['remoteId'] = runs[0]['id']
        run = self.http.request('GET', self.repo + f"/actions/runs/{receipt['remoteId']}")
        if (run.get('head_sha') != receipt['commit'] or run.get('head_branch') != receipt['branch']
                or run.get('workflow_id') != receipt['target']['workflowId'] or run.get('event') != 'workflow_dispatch'
                or run.get('repository', {}).get('full_name', '').lower() != self.config['repository'].lower()):
            raise CIError('CI: workflow identity does not match this candidate; no result was accepted.')
        attempt = run.get('run_attempt', 1)
        if receipt.get('attempt', attempt) != attempt: raise CIError('CI: workflow attempt changed; create a new evaluation instead of mixing attempts.')
        receipt['attempt'] = attempt
        return run

    def poll(self, receipt):
        run = self._run(receipt)
        if run is None: return {'status': 'waiting-for-workflow', 'conclusion': None, 'jobs': []}
        # Construct a safe navigation URL rather than trusting a response URL.
        api = urlsplit(self.config['apiUrl'])
        web = 'https://github.com' if api.hostname == 'api.github.com' else f'{api.scheme}://{api.netloc}'
        result = {'status': run['status'], 'conclusion': run.get('conclusion'), 'jobs': [],
                  'url': f"{web}/{self.config['repository']}/actions/runs/{receipt['remoteId']}", 'attempt': receipt['attempt']}
        if run['status'] != 'completed': return result
        for page in range(1, 21):
            data = self.http.request('GET', self.repo + f"/actions/runs/{receipt['remoteId']}/attempts/{receipt['attempt']}/jobs", query={'per_page': 100, 'page': page})
            for job in data['jobs']:
                if job.get('head_sha') != receipt['commit'] or job.get('run_id') != receipt['remoteId']:
                    raise CIError('CI: job identity mismatch.')
                result['jobs'].append({key: job.get(key) for key in ('name', 'status', 'conclusion')})
            if len(result['jobs']) >= data['total_count']: return result
        raise CIError('CI: workflow job pagination exceeded the safety limit.')

    def report(self, receipt, name):
        self._run(receipt)
        if receipt.get('attempt') != 1:
            raise CIError('CI: report artifacts cannot be reliably assigned across reruns; start a new evaluation.')
        matches = []
        for page in range(1, 21):
            data = self.http.request('GET', self.repo + f"/actions/runs/{receipt['remoteId']}/artifacts", query={'per_page': 100, 'page': page})
            matches += [item for item in data['artifacts'] if item['name'] == name]
            if page * 100 >= data['total_count']: break
        else: raise CIError('CI: too many report artifacts.')
        if len(matches) != 1 or matches[0].get('expired'):
            raise CIError('CI: the configured JUnit artifact is missing, expired or ambiguous.')
        artifact = matches[0]
        if artifact.get('workflow_run', {}).get('head_sha') != receipt['commit']:
            raise CIError('CI: report artifact does not belong to this candidate commit.')
        content = self.http.request('GET', self.repo + f"/actions/artifacts/{artifact['id']}/zip", allowed=(200, 302), binary=True)
        self._run(receipt)
        receipt['reportArtifactId'] = artifact['id']
        return content

    def cancel(self, receipt):
        run = self._run(receipt)
        if run is None: raise CIError('CI: the remote run is not visible yet; cancellation could not be confirmed.')
        if run and run['status'] != 'completed':
            self.http.request('POST', self.repo + f"/actions/runs/{receipt['remoteId']}/cancel", allowed=(202, 409))

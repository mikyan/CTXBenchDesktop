"""CI grading policy and durable receipts, independent of the selected platform."""
import base64
import hashlib
import re
import time
from .catalog import fingerprint
from .ci_config import ci_connection, ci_test
from .ci_protocol import CIError, Transport
from .ci_github import GitHubActions
from .ci_http import HttpCI
from .ci_reports import junit_counts
from .database import utc_now
from .environments import public_material
from .runtime import git


# Company ports usually only change this registry or add one adapter module.
ADAPTERS = {'github-actions': GitHubActions, 'http-ci': HttpCI}


def gate_result(config, state, counts=None):
    if state.get('status') != 'completed': raise CIError('CI: workflow has not completed.')
    if state.get('conclusion') not in {'success', 'failure'}:
        raise CIError('CI: workflow was cancelled, timed out, skipped or blocked; this is an infrastructure failure, not a test FAIL.')
    jobs = state.get('jobs')
    if not isinstance(jobs, list): raise CIError('CI: invalid gate results.')
    required = []
    for name in config['requiredJobs']:
        matches = [job for job in jobs if isinstance(job, dict) and job.get('name') == name]
        if len(matches) != 1: raise CIError('CI: a required gate is missing or duplicated. Check exact job names, including matrix suffixes.')
        job = matches[0]
        if job.get('status') != 'completed' or job.get('conclusion') not in {'success', 'failure'}:
            raise CIError('CI: a required gate was skipped, cancelled or did not finish; no passing result was accepted.')
        required.append({'name': name, 'conclusion': job['conclusion']})
    passed = state['conclusion'] == 'success' and all(j['conclusion'] == 'success' for j in required)
    if config.get('reportArtifact'):
        if counts is None: raise CIError('CI: required test counts are missing.')
        executed = counts['total'] - counts['skipped']
        if executed < config['minTests']: raise CIError('CI: fewer tests executed than the configured minimum; no passing result was accepted.')
        passed = passed and counts['failures'] == 0 and counts['errors'] == 0
    return {'resolved': passed, 'requiredJobs': required, 'testCounts': counts}


class CIGrading:
    def __init__(self, workbench, adapters=None, transport=Transport):
        self.wb, self.db = workbench, workbench.db
        self.adapters, self.transport = adapters or ADAPTERS, transport
        self.credentials = {}  # Memory only; not os.environ, SQLite, agent allowlists or snapshots.

    def save_connection(self, value):
        public_material(value, self.wb.redact)
        config = ci_connection(value)
        record = {'id': fingerprint(config), 'document': config, 'createdAt': utc_now()}
        self.db.put_document('ciConnections', record['id'], record)
        return self.public_connection(record)

    def connection(self, key):
        record = self.db.get_document('ciConnections', key)
        if fingerprint(ci_connection(record['document'])) != key: raise CIError('CI: saved connection changed; restore it or create a new version.')
        return record

    def public_connection(self, record):
        return {**record, 'credentialConfigured': bool(self.credentials.get(record['id']))}

    def set_credential(self, key, value):
        self.connection(key)
        if not isinstance(value, dict) or set(value) != {'token'} or not isinstance(value['token'], str) or len(value['token']) > 4096 or any(c.isspace() for c in value['token']):
            raise CIError('CI: invalid platform token.')
        if self.wb._active or any(o['status'] in {'queued', 'running'} for o in self.db.list_documents('operations')):
            raise CIError('CI: finish or pause active work before changing platform credentials.')
        if value['token']: self.credentials[key] = value['token']
        else: self.credentials.pop(key, None)
        return {'credentialConfigured': bool(value['token'])}

    def adapter(self, config):
        key = fingerprint(config)
        if not self.credentials.get(key): raise CIError('CI: configure this connection token first. Tokens must be re-entered after the evaluation service restarts.')
        return self.adapters[config['provider']](config, self.transport(config['apiUrl'], self.credentials[key]))

    def prepare(self, task):
        config = ci_test(task.ci)
        connection = self.connection(config['connectionId'])
        target = self.adapter(connection['document']).prepare(task)
        if not isinstance(target, dict) or set(target) - {'repository', 'baseCommit', 'baseTree', 'workflowId', 'workflowPath', 'workflowBlob', 'protectedPaths'}:
            raise CIError('CI: platform target contains unsupported fields.')
        public_material(target, self.wb.redact)
        if target.get('baseCommit') != task.base_commit or not re.fullmatch(r'[a-f0-9]{40}', str(target.get('baseTree', ''))):
            raise CIError('CI: platform must resolve the exact baseline commit and Git tree.')
        if target.get('repository') != connection['document']['repository'] or not isinstance(target.get('workflowBlob'), str) or not target['workflowBlob'].strip():
            raise CIError('CI: platform must bind the target repository and an immutable workflow revision.')
        paths = target.get('protectedPaths', [])
        if not isinstance(paths, list) or any(not isinstance(p, str) or not p or p.startswith('/') or '..' in p for p in paths):
            raise CIError('CI: invalid platform grading-file protection rules.')
        return {'connection': connection, 'target': target, 'policy': config}

    def candidate(self, task, patch, target):
        if task.hidden_test_patch:
            raise CIError('CI: local hidden-test patches must not be uploaded. Keep hidden tests in the trusted CI evaluator instead.')
        workspace = self.wb.runtime.checkout(task, 'ci-candidate')
        if git(workspace, 'rev-parse', 'HEAD^{tree}').decode().strip() != target['baseTree']:
            raise CIError('CI: local baseline tree differs from the platform baseline.')
        if patch.stat().st_size:
            git(workspace, 'apply', '--binary', '--whitespace=nowarn', '-', data=patch.read_bytes())
        git(workspace, 'add', '--all', '--force', '--', '.')
        raw = git(workspace, 'diff', '--cached', '--raw', '--no-renames', '--no-abbrev', '-z', 'HEAD').split(b'\0')
        files, size = [], 0
        for index in range(0, len(raw) - 1, 2):
            info, path = raw[index].decode().split(), raw[index + 1].decode('utf-8')
            if any(path == prefix.rstrip('/') or path.startswith(prefix.rstrip('/') + '/') for prefix in ['.github/', '.git/', *target.get('protectedPaths', [])]):
                raise CIError('CI: candidate changes a protected workflow definition. It was not submitted.')
            mode, blob = info[1], info[3]
            if mode not in {'000000', '100644', '100755', '120000'}:
                raise CIError('CI: this candidate contains an unsupported Git entry type.')
            content = git(workspace, 'cat-file', 'blob', blob) if mode != '000000' else b''
            size += len(content)
            if size > 10 * 1024 * 1024 or len(files) >= 500: raise CIError('CI: candidate exceeds 500 changed files or 10 MiB.')
            # Never forward any known Agent/platform credentials in candidate files.
            public_material(content.decode('utf-8', errors='replace').replace('\0', ''), self.wb.redact)
            files.append({'path': path, 'mode': mode, 'base64': base64.b64encode(content).decode()})
        return {'baseCommit': task.base_commit, 'treeSha': git(workspace, 'write-tree').decode().strip(),
                'patchSha256': hashlib.sha256(patch.read_bytes()).hexdigest(), 'files': files}

    def grade(self, task, patch, run, frozen, check, *, poll_seconds=5):
        started = time.monotonic()
        if not frozen: raise CIError('CI: the frozen platform target is missing; prepare the experiment first.')
        connection, policy = frozen['connection']['document'], frozen['policy']
        if fingerprint(connection) != task.ci['connectionId'] or policy != ci_test(task.ci):
            raise CIError('CI: grading configuration changed after the experiment was frozen.')
        adapter = self.adapter(connection)
        if hasattr(adapter, 'http'):
            adapter.http.check = check
        candidate = self.candidate(task, patch, frozen['target'])
        key = fingerprint({'run': run['id'], 'candidate': candidate['treeSha'], 'frozen': frozen})
        try: receipt = self.db.get_document('ciEvaluations', key)
        except KeyError:
            receipt = {'id': key, 'runId': run['id'], 'experimentId': run['experimentId'], 'connectionId': task.ci['connectionId'],
                'branch': 'ctxbench-eval/' + key[:32], 'treeSha': candidate['treeSha'], 'target': frozen['target'], 'createdAt': utc_now()}
        def save(): self.db.put_document('ciEvaluations', key, receipt)
        def progress(state):
            # Store a small, sanitized receipt, never HTTP bodies, tokens, signed URLs or logs.
            visible = {'evaluationId': key, 'provider': connection['provider'], 'repository': connection['repository'],
                'branch': receipt['branch'], 'commit': receipt.get('commit'), 'remoteId': receipt.get('remoteId'),
                'status': state['status'], 'url': state.get('url'), 'attempt': state.get('attempt')}
            public_material(visible, self.wb.redact)
            self.db.update_run(run['id'], 'grading', {'ci': visible})
            return visible
        check(); save(); progress({'status': 'preparing-ci'})
        adapter.submit(frozen['target'], candidate, receipt, save)
        deadline = time.monotonic() + policy['timeoutMinutes'] * 60
        while True:
            check()
            state = adapter.poll(receipt)
            save(); check(); visible = progress(state)
            if state.get('status') == 'completed':
                # Check gate shape before fetching any report; failure itself is
                # still a valid grade once the required evidence is complete.
                gate_result({**policy, 'reportArtifact': ''}, state)
                report = adapter.report(receipt, policy['reportArtifact']) if policy['reportArtifact'] else None
                counts = junit_counts(report) if report is not None else None
                check(); save()
                result = gate_result(policy, state, counts)
                return {**result, 'benchmark': 'custom', 'instanceId': task.id, 'gradingMode': 'ci',
                        'durationSeconds': time.monotonic() - started,
                        'report': {'sha256': hashlib.sha256(report).hexdigest(), 'artifactName': policy['reportArtifact'],
                                   'artifactId': receipt.get('reportArtifactId')} if report is not None else None,
                        'ci': {**visible, 'conclusion': state['conclusion']}, 'graderImageDigests': []}
            if time.monotonic() >= deadline:
                raise CIError('CI: waiting timed out. The remote workflow may still be running; retry resumes observation without resubmitting code.')
            until = time.monotonic() + poll_seconds
            while time.monotonic() < until:
                check(); time.sleep(min(.25, max(0, until - time.monotonic())))

    def cancel(self, run_id):
        for receipt in self.db.list_documents('ciEvaluations'):
            if receipt.get('runId') == run_id and (receipt.get('remoteId') or receipt.get('dispatchIntent')):
                try:
                    self.adapter(self.connection(receipt['connectionId'])['document']).cancel(receipt)
                except CIError:
                    self.db.update_run(run_id, 'cancelled', {'failure': 'CI: remote cancellation could not be confirmed. Check the recorded platform run; it may still be running.'})


def register_ci_routes(app, service):
    @app.get('/v1/ci/selection/{dataset}')
    def selection(dataset: str):
        record = service.wb.library.definition(dataset)
        result = []
        for task in record['tasks']:
            if task.get('ci'):
                connection = service.public_connection(service.connection(task['ci']['connectionId']))
                result.append({'taskId': task['id'], 'connectionName': connection['document']['name'],
                    'repository': connection['document']['repository'], 'provider': connection['document']['provider'],
                    'credentialConfigured': connection['credentialConfigured']})
        return result

    @app.get('/v1/ci/connections')
    def connections():
        return [service.public_connection(service.connection(row['id'])) for row in service.db.list_documents('ciConnections')]

    @app.post('/v1/ci/connections', status_code=201)
    def save_connection(value: dict): return service.save_connection(value)

    @app.post('/v1/ci/connections/{key}/credential')
    def credential(key: str, value: dict): return service.set_credential(key, value)

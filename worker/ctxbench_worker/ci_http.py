"""Company gateway reference adapter. Implement this small protocol on any CI.

The gateway owns platform-specific auth, submission and test-report conversion.
Its evaluation endpoint MUST implement durable idempotency by evaluation ID.
"""
from .ci_protocol import CIError


class HttpCI:
    def __init__(self, config, transport):
        self.config, self.http = config, transport

    def prepare(self, task):
        return self.http.request('POST', '/v1/targets/resolve', body={'repository': self.config['repository'],
            'workflow': self.config['workflow'], 'sourceRepository': task.repository, 'baseCommit': task.base_commit})

    def submit(self, target, candidate, receipt, save):
        if receipt.get('remoteId'): return
        # A timed-out PUT may already have launched work. Persist its identity
        # first so cancellation can still target it without a response receipt.
        receipt['dispatchIntent'] = True; save()
        value = self.http.request('PUT', '/v1/evaluations/' + receipt['id'], body={'target': target,
            'candidate': candidate, 'evaluationId': receipt['id']})
        if value.get('evaluationId') != receipt['id'] or value.get('treeSha') != candidate['treeSha']:
            raise CIError('CI: company gateway submission identity mismatch.')
        receipt.update(remoteId=receipt['id'], commit=value.get('commit')); save()

    def poll(self, receipt):
        value = self.http.request('GET', '/v1/evaluations/' + receipt['id'])
        if value.get('evaluationId') != receipt['id'] or value.get('treeSha') != receipt['treeSha']:
            raise CIError('CI: company gateway result identity mismatch.')
        return value

    def report(self, receipt, name):
        return self.http.request('GET', '/v1/evaluations/' + receipt['id'] + '/junit', query={'artifact': name}, binary=True)

    def cancel(self, receipt):
        self.http.request('POST', '/v1/evaluations/' + receipt['id'] + '/cancel')

"""Operator-only execution diagnostics, including work before Docker exists.

Never log prompts, request bodies, repository file contents or process env dumps.
Only explicitly instrumented command diagnostics and exception chains are saved.
No diagnostics object is passed to an Agent or included in experiment identity.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import re
import time
import traceback

from .live_logs import ContainerLogs, runtime_secrets
from .command_adapter import RedactedStream
from .database import utc_now

_active = ContextVar('execution_diagnostics', default=())


def clean(text, redact=lambda text: text):
    stream = RedactedStream(runtime_secrets())
    text = stream.feed(str(text).encode('utf-8', errors='replace'), final=True)
    text = redact(text)
    # Catch common URL/HTTP credentials not registered as an Agent env variable.
    text = re.sub(r'(?i)(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', text)
    text = re.sub(r'(?i)(\b(?:authorization|api[-_]?key|access[-_]?token|password|secret)\b["\x27]?\s*[:=]\s*["\x27]?)(?:bearer\s+)?[^\s,"\x27]+', r'\1[REDACTED]', text)
    return text


def advice(stage, text):
    lower = text.lower()
    if any(word in lower for word in ('no space left', 'disk space', 'disk full')):
        return 'storage', 'Free space on the Windows disk and WSL disk, then retry explicitly.'
    if 'dubious ownership' in lower:
        return 'repository', 'Git rejected a local repository owned by another user. This is not a write-permission error. Update the evaluation service for command-scoped trust of the selected local repository; do not change its ownership or globally trust every repository.'
    if any(word in lower for word in ('permission denied', 'access is denied', 'read-only file')):
        return 'permission', 'Check WSL directory ownership, UID 10001 access and whether the mounted directory is writable.'
    if any(word in lower for word in ('unauthorized', 'authentication', 'access denied', '401', '403')):
        return 'authentication', 'Check access to the Git or image registry and runtime credentials. Do not paste credentials into commands.'
    if any(word in lower for word in ('timed out', 'timeout', 'connection', 'resolve host', 'certificate', 'deadline exceeded')):
        return 'connection', 'Check Docker, network, proxy and company certificate settings; consult the original error below.'
    if 'image' in stage.lower():
        return 'image', 'Check the exact image address, local installation, platform and required tools; review the complete build output.'
    if any(word in stage.lower() for word in ('git', 'baseline', 'checkout')):
        return 'repository', 'Check repository access, the frozen baseline commit and the working directory permissions.'
    return 'execution', 'Review the failed step and complete log before retrying; retry does not repair configuration automatically.'


class Trace:
    def __init__(self, root, label, redact, secrets=()):
        self.store, self.redact = ContainerLogs(root), redact
        self.key = self.store.create('preparation', source='service', label=label)
        self.stage = label
        self.started = False
        self.failure = None
        self.lost = False
        self.stream = RedactedStream(secrets)

    def write(self, text):
        try:
            self.store.append(self.key, clean(self.stream.feed(str(text).encode('utf-8', errors='replace')), self.redact))
        except Exception:
            self.lost = True

    def fail(self, error):
        if self.failure is None:
            message = clean(f'{type(error).__name__}: {error}', self.redact)
            category, hint = advice(self.stage, message)
            self.failure = {'logSessionId': self.key, 'failedAt': utc_now(), 'stage': self.stage, 'category': category,
                            'hint': hint, 'agentStarted': self.started, 'summary': message[:1200]}
            self.write(f'\n[{utc_now()}] FAILED: {self.stage}\n')
            self.write(''.join(traceback.TracebackException.from_exception(error, capture_locals=False).format()))
            try:
                self.store.metadata(self.key, failure=self.failure)
            except Exception:
                self.lost = True
        return self.failure


def log(text):
    for trace in _active.get():
        trace.write(text)


def note(message):
    log(f'[{utc_now()}] {message}\n')


def call(label, function, *args, **kwargs):
    with phase(label):
        return function(*args, **kwargs)


def agent_started():
    for trace in _active.get():
        trace.started = True
    note('Agent container started. Model invocation is determined by the Agent execution record.')


def failure(error):
    receipt = getattr(error, '_ctxbench_diagnostic', None)
    newest = None
    for trace in _active.get():
        try:
            newest = trace.fail(error)
        except Exception:
            trace.lost = True
    # An outer phase must not replace a more specific, inner error receipt.
    receipt = receipt or newest
    if receipt:
        try:
            error._ctxbench_diagnostic = receipt
        except Exception:
            pass
    return receipt


def details(error):
    return getattr(error, '_ctxbench_diagnostic', None)


@contextmanager
def phase(label):
    traces = _active.get()
    previous = [trace.stage for trace in traces]
    started = time.monotonic()
    for trace in traces:
        trace.stage = label
    note('START: ' + label)
    try:
        yield
    except Exception as error:
        failure(error)
        raise
    else:
        note(f'OK: {label} ({time.monotonic() - started:.2f}s)')
    finally:
        for trace, old in zip(traces, previous):
            trace.stage = old


def step(label):
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            with phase(label):
                return function(*args, **kwargs)
        return call
    return decorate


def observed(label):
    """Start a distinct retained diagnostic attempt, with current provenance."""
    def decorate(function):
        @wraps(function)
        def call(self, *args, **kwargs):
            trace = None
            try:
                root = getattr(self, 'root', None) or self.artifacts_root.parent
                redact = getattr(self, 'redact', lambda value: value)
                runner = getattr(getattr(self, 'engine', None), 'runner', self)
                secrets = (*runtime_secrets(getattr(runner, 'env_allowlist', ())),
                           *getattr(getattr(self, 'ci', None), 'credentials', {}).values())
                trace = Trace(root, label, redact, secrets)
            except Exception:
                pass  # Observation failures do not change execution or grading.
            token = _active.set((*_active.get(), trace)) if trace else None
            try:
                with phase(label):
                    return function(self, *args, **kwargs)
            finally:
                if trace:
                    _active.reset(token)
                    try:
                        trace.store.append(trace.key, clean(trace.stream.feed(final=True), trace.redact))
                    except Exception:
                        trace.lost = True
                    try:
                        trace.store.finish(trace.key, error='Diagnostic log could not be completely saved. Check available disk space.' if trace.lost else None)
                    except Exception:
                        pass
        return call
    return decorate


def docker_event(event):
    # Build/pull event fields only; never inspect images' Config.Env or request bodies.
    if isinstance(event, dict):
        for key in ('stream', 'status', 'progress', 'error'):
            if event.get(key):
                log(str(event[key]) if key == 'stream' else str(event[key]) + '\n')


def docker_build(client, **kwargs):
    """Drain low-level build events as they arrive and keep original image semantics."""
    import docker
    image_id = None
    for event in client.api.build(decode=True, **kwargs):
        docker_event(event)
        if event.get('error'):
            raise docker.errors.BuildError(event['error'], [])
        if event.get('aux', {}).get('ID'):
            image_id = event['aux']['ID']
        match = re.search(r'Successfully built ([0-9a-f]+)', event.get('stream', ''))
        if match:
            image_id = match.group(1)
    if not image_id:
        raise RuntimeError('Docker build did not return an image identity; inspect the full build log.')
    return client.images.get(image_id)

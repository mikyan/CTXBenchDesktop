"""Standalone stdlib container adapter. Requires python3, git and /bin/sh.

No Pi dependency. Never receives grading inputs. Token usage is unknown, not zero.
This file is copied into a read-only per-run mount, not imported from a task repo.
"""
import hashlib
import codecs
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import re
import time


class RedactedStream:
    """Shared by this standalone adapter and the host's private log collector."""
    def __init__(self, secrets=()):
        values = {value for value in secrets if value}
        values |= {json.dumps(value, ensure_ascii=ascii_only)[1:-1] for value in values for ascii_only in (False, True)}
        self.values = sorted(values, key=len, reverse=True)
        self.pattern = re.compile('|'.join(map(re.escape, self.values))) if values else None
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.pending = ''

    def feed(self, chunk=b'', *, final=False):
        text = self.pending + self.decoder.decode(chunk, final=final)
        cut = len(text)
        for secret in self.values:
            for size in range(min(len(text), len(secret) - 1), 0, -1):
                if text.endswith(secret[:size]):
                    cut = min(cut, len(text) - size)
                    break
        if self.pattern:
            for match in self.pattern.finditer(text):
                if match.start() < cut < match.end():
                    cut = match.start()
                    break
        self.pending = text[cut:]
        result = self.pattern.sub('[REDACTED]', text[:cut]) if self.pattern else text[:cut]
        if final and self.pending:
            result += '[REDACTED]'
            self.pending = ''
        return result


def main():
    request = json.loads(Path('/ctxbench/request.json').read_text())
    output = Path('/ctxbench/output')
    secrets = [value for name, value in os.environ.items() if value and
               (name in request['envNames'] or re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', name, re.I))]

    def redact(text):
        for secret in sorted(secrets, key=len, reverse=True):
            text = text.replace(secret, '[REDACTED]')
        return text

    def write(name, content):
        path = output / name
        if path.is_symlink() or output not in path.resolve().parents:
            raise ValueError('Unsafe Agent output path.')
        path.write_text(redact(content), encoding='utf-8')

    def git(*args):
        return subprocess.check_output(['git', '-c', 'safe.directory=/workspace',
            '-c', 'core.hooksPath=/dev/null', '-c', 'core.quotePath=false', *args], cwd='/workspace').decode('utf-8')

    initial = git('rev-parse', 'HEAD').strip()
    declared = set(request.get('contextPaths', []))

    def context(name):
        lower = name.lower()
        return (name in declared or lower.split('/')[-1] in {'agents.md', 'claude.md'}
                or lower == '.github/copilot-instructions.md' or lower.startswith('.ctx/'))

    environment = dict(os.environ)
    if not os.access(environment.get('HOME', '/root'), os.W_OK):
        environment['HOME'] = tempfile.mkdtemp(prefix='ctxbench-home-')
    for key in ('provider', 'model', 'thinking', 'max_tokens'):
        environment['CTXBENCH_' + key.upper()] = str(request['model'].get(key, ''))
    deadline = time.monotonic() + request['timeoutSeconds']
    workflow = request.get('workflow') or {'setupCommands': [], 'steps': [{'name': '', 'prompt': request['prompt']}]}
    steps = []
    setup_status = 'skipped'
    code, failure = 0, None
    scratch = Path(tempfile.mkdtemp(prefix='ctxbench-command-'))

    def execute(argv, logfile, env):
        if time.monotonic() >= deadline:
            return 124
        previous = output / logfile
        if previous.is_symlink():
            raise ValueError('Unsafe Agent log path.')
        child = subprocess.Popen(argv, cwd='/workspace', env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        def pump():
            stream = RedactedStream([*secrets, *(value for name, value in env.items() if value and re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', name, re.I))])
            try:
                written = previous.stat().st_size if previous.exists() else 0
            except OSError:
                written = 8 * 1024 * 1024
            def emit(content):
                nonlocal written
                if not content:
                    return
                try:
                    print(content, end='', flush=True)
                except (OSError, ValueError):
                    pass
                # Keep artifact growth bounded; the host retains a rolling console.
                data = content.encode('utf-8')
                try:
                    if written + len(data) <= 8 * 1024 * 1024 and not previous.is_symlink():
                        with previous.open('ab') as log:
                            log.write(data)
                except OSError:
                    # Keep draining the pipe even when the artifact disk is full.
                    pass
                written += len(data)
            while chunk := child.stdout.read1(8192):
                emit(stream.feed(chunk))
            emit(stream.feed(final=True))
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        try:
            result = child.wait(timeout=max(.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            result = 124
        finally:
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait()
            reader.join(timeout=2)
            if not reader.is_alive():
                child.stdout.close()
        return result

    try:
        if workflow['setupCommands']:
            setup_status = 'running'
            # All setup lines share a shell; exported variables carry into steps.
            envfile = scratch / 'environment.json'
            setup = '\n'.join(workflow['setupCommands']) + '\npython3 -c ' + "'import os,json; json.dump(dict(os.environ),open(\"" + str(envfile) + "\",\"w\"))'"
            code = execute(['/bin/sh', '-eu', '-c', setup], 'setup.log', environment)
            if code: raise RuntimeError('Custom Agent startup commands failed.')
            environment = json.loads(envfile.read_text())
            secrets.extend(value for name, value in environment.items() if value and re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', name, re.I))
            envfile.unlink()
            if (git('rev-parse', 'HEAD').strip() != initial
                    or git('status', '--porcelain', '--untracked-files=all').strip()
                    or any(context(name) for name in git('ls-files', '--others', '--ignored', '--exclude-standard', '-z').split('\0') if name)):
                raise RuntimeError('Startup commands changed the frozen repository. Install dependencies outside the checkout or in ignored environment directories.')
            setup_status = 'completed'
        for index, step in enumerate(workflow['steps']):
            prompt = scratch / f'prompt-{index}.txt'
            prompt.write_text(step['prompt'], encoding='utf-8')
            prompt.chmod(0o444)
            env = {**environment, 'CTXBENCH_PROMPT_FILE': str(prompt)}
            code = execute(request['metadata']['commandAgent']['command'], 'agent.stderr.log', env)
            steps.append({'index': index + 1, 'name': step['name'],
                'promptHash': hashlib.sha256(step['prompt'].encode()).hexdigest(),
                'status': 'completed' if code == 0 else 'failed', 'exitCode': code})
            write('trajectory.jsonl', ''.join(json.dumps({'type': 'command_step', **item}) + '\n' for item in steps))
            if code: raise RuntimeError('Custom Agent command failed; inspect agent.stderr.log.')
        # Include staged, committed and new files relative to the frozen start.
        git('add', '-A', '--', '.')
        changed = git('diff', initial, '--name-only', '-z').split('\0')
        changed = [name for name in changed if name]
        context_paths = [name for name in changed if context(name)]
        write('raw_agent.patch', git('diff', initial, '--binary', '--no-ext-diff', '--', '.'))
        write('graded.patch', git('diff', initial, '--binary', '--no-ext-diff', '--', '.',
                                 *[':(exclude,literal)' + name for name in context_paths]))
        write('context_mutation.patch', git('diff', initial, '--binary', '--no-ext-diff', '--',
              *[':(literal)' + name for name in context_paths]) if context_paths else '')
    except Exception as error:
        failure = redact(str(error))
        code = code or 1
        if setup_status == 'running':
            setup_status = 'timed-out' if code == 124 else 'failed'
    write('workflow.json', json.dumps({'version': 1, 'setup': {'status': setup_status},
        'steps': steps, 'plannedSteps': len(workflow['steps']), 'error': failure, 'usageAvailable': False}, indent=2))
    result = {'schemaVersion': 1, 'runId': request['runId'], 'status': 'completed' if code == 0 else 'timed-out' if code == 124 else 'failed',
        'exitCode': code, 'commandAgentProtocolVersion': 1, 'usageAvailable': False,
        'commandAgentHash': hashlib.sha256(json.dumps(request['metadata']['commandAgent'], sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'workflowProtocolVersion': 1, 'workflowSteps': steps, 'workflowError': failure}
    write('result.json', json.dumps(result, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())

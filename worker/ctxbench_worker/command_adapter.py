"""Standalone stdlib container adapter. Requires python3, git and /bin/sh.

No Pi dependency. Never receives grading inputs. Token usage is unknown, not zero.
This file is copied into a read-only per-run mount, not imported from a task repo.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


def main():
    request = json.loads(Path('/ctxbench/request.json').read_text())
    output = Path('/ctxbench/output')
    secrets = [os.environ[name] for name in request['envNames'] if os.environ.get(name)]

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
        # Temp logs are outside the candidate tree. No credential-bearing raw logs
        # are persisted to the mounted output; export only after redaction.
        with tempfile.TemporaryFile() as log:
            child = subprocess.Popen(argv, cwd='/workspace', env=env, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            try:
                result = child.wait(timeout=max(.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                result = 124
            finally:
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait()
            log.seek(0)
            content = log.read().decode('utf-8', errors='replace')
            previous = output / logfile
            if previous.is_symlink():
                raise ValueError('Unsafe Agent log path.')
            write(logfile, (previous.read_text(encoding='utf-8') if previous.exists() else '') + content)
            print(redact(content[-8000:]), flush=True)
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

"""Explicit, remote CI acceptance controls; never a model/knowledge benchmark.

Preparation publishes ONLY the reviewed workflow on a new codex/ branch based
on an explicit existing commit. Grading exercises the shipped CIGrading through
real GitHub Actions for original and deliberately defective candidates. No Agent
runs. State is kept in a separate acceptance directory, never the desktop DB.
"""
import argparse
import base64
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker.ctxbench_worker.ci_protocol import Transport
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from worker.ctxbench_worker.runtime import git
from worker.ctxbench_worker.workbench import Workbench


def gh_token():
    result = subprocess.run(['gh', 'auth', 'token', '--hostname', 'github.com'], capture_output=True, text=True, timeout=30)
    if result.returncode or not result.stdout.strip():
        raise ValueError('Log in to GitHub CLI first; no token is printed or persisted.')
    return result.stdout.strip()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'grade'])
    parser.add_argument('--execute-remote', action='store_true', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--base')
    parser.add_argument('--branch')
    parser.add_argument('--verify-resume', action='store_true', help='Re-enter the real grader with persisted receipts; must reuse the same remote execution.')
    args = parser.parse_args()
    root = args.root.resolve(); root.mkdir(parents=True, exist_ok=True)
    token = gh_token()
    http = Transport('https://api.github.com', token)
    identity = http.request('GET', '/user')['login']
    if args.repo != identity + '/CTXBenchDesktop':
        raise ValueError('This project-specific control only targets the authenticated owner/CTXBenchDesktop repository.')
    repo_path = '/repos/' + args.repo
    metadata = http.request('GET', repo_path)
    if metadata.get('visibility') != 'public' or not metadata.get('permissions', {}).get('push'):
        raise ValueError('This acceptance requires the reviewed, public, writable project repository.')
    default = metadata['default_branch']
    original = http.request('GET', repo_path + '/git/ref/heads/' + default)['object']['sha']
    receipt_path = root / 'baseline.json'
    if args.action == 'prepare':
        if receipt_path.exists(): raise ValueError('Baseline receipt exists; reuse it with grade, never overwrite it.')
        if not args.base or original != args.base or not args.branch or not args.branch.startswith('codex/ci-live-'):
            raise ValueError('Supply the current reviewed default commit and a fresh codex/ci-live- branch.')
        present = http.request('GET', repo_path + '/git/ref/heads/' + args.branch, allowed=(200, 404))
        if present.get('object'): raise ValueError('Test branch already exists; it was not changed.')
        workflow = (Path(__file__).resolve().parents[1] / 'examples/ci/github-python-acceptance.yml').read_bytes()
        blob = http.request('POST', repo_path + '/git/blobs', body={'encoding': 'base64', 'content': base64.b64encode(workflow).decode()})['sha']
        parent = http.request('GET', repo_path + '/git/commits/' + args.base)
        tree = http.request('POST', repo_path + '/git/trees', body={'base_tree': parent['tree']['sha'],
            'tree': [{'path': '.github/workflows/ci.yml', 'mode': '100644', 'type': 'blob', 'sha': blob}]})['sha']
        commit = http.request('POST', repo_path + '/git/commits', body={'message': 'Prepare isolated CTXBench CI grading acceptance',
            'tree': tree, 'parents': [args.base]})['sha']
        receipt = {'repository': args.repo, 'defaultBranch': default, 'defaultCommitBefore': original,
            'baselineCommit': commit, 'baselineBranch': args.branch, 'workflowBlob': blob, 'workflow': 'ci.yml'}
        # Keep a receipt even if ref creation returns an uncertain network error.
        save(receipt_path, receipt)
        http.request('POST', repo_path + '/git/refs', body={'ref': 'refs/heads/' + args.branch, 'sha': commit})
        print(json.dumps(receipt), flush=True)
        return 0

    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt['repository'] != args.repo: raise ValueError('Receipt repository mismatch.')
    wb = Workbench(create_mock_engine(root / 'state'), None)
    connection = wb.ci.save_connection({'name': 'GitHub live acceptance (no Agent)', 'provider': 'github-actions',
        'apiUrl': 'https://api.github.com', 'repository': args.repo, 'workflow': receipt['workflow']})
    wb.ci.set_credential(connection['id'], {'token': token})
    result_path = root / 'results.json'
    if result_path.exists():
        report = json.loads(result_path.read_text(encoding='utf-8'))
    else:
        policy = {'connectionId': connection['id'], 'requiredJobs': ['backend-tests'], 'reportArtifact': 'ctxbench-junit',
                  'minTests': 100, 'timeoutMinutes': 15, 'allowRemoteExecution': True}
        row = {'id': 'ci-backend-control', 'repository': 'https://github.com/' + args.repo + '.git',
            'baseCommit': receipt['baselineCommit'], 'prompt': 'CI transport acceptance control; no Agent execution.',
            'image': 'ctxbench/agent-pi:0.1.0', 'test': {'ci': policy}}
        dataset = wb.catalog.register('Live CI acceptance controls (not model results)', 'custom', [row])['id']
        task = wb.catalog.task(dataset, row['id'])
        frozen = wb.ci.prepare(task)
        # The two controls are independent experiments; no context comparison is
        # claimed. Only each none run is used; unused context plans are cancelled.
        report = {'kind': 'ci-transport-acceptance', 'repository': args.repo, 'dataset': dataset,
                  'baseline': receipt, 'frozen': frozen, 'agentCalls': 0, 'modelTokens': 0, 'controls': {}}
        for label in ['original', 'defective']:
            spec = ExperimentSpec('CI control: ' + label + ' (no Agent)', 'custom', dataset, ('none', 'skill-generated'), 1,
                (task.id,), ModelConfig('mock', 'not-executed', 'off', 1), 'ctxbench/agent-pi:0.1.0', ResourcePolicy(), 1)
            experiment = wb.engine.create_experiment(spec)
            for run in wb.db.list_runs(experiment['id']):
                if run['arm'] == 'none':
                    report['controls'][label] = {'runId': run['id'], 'experimentId': experiment['id']}
                else: wb.db.update_run(run['id'], 'cancelled', {'mock': True, 'failure': 'Unused control plan; not a context comparison.'})
            patch = root / (label + '.patch')
            if label == 'original': patch.write_bytes(b'')
            else:
                checkout = wb.runtime.checkout(task, 'acceptance-control')
                source = checkout / 'worker/ctxbench_worker/constraints.py'
                text = source.read_text(encoding='utf-8')
                before = 'return 0.8 * semantic + 0.2 * structure'
                if text.count(before) != 1: raise ValueError('Defect control no longer matches the reviewed baseline.')
                source.write_text(text.replace(before, 'return 0.0  # Deliberate CI acceptance defect'), encoding='utf-8')
                patch.write_bytes(git(checkout, 'diff', '--binary', 'HEAD'))
        save(result_path, report)
    task = wb.catalog.task(report['dataset'], 'ci-backend-control')
    if report['baseline'] != receipt: raise ValueError('Acceptance baseline receipt changed.')

    def grade(label):
        value = report['controls'][label]
        run = wb.db.get_run(value['runId'])
        previous = value.get('grade')
        if previous and not args.verify_resume: return value
        try:
            result = wb.ci.grade(task, root / (label + '.patch'), run, report['frozen'], lambda: None, poll_seconds=10)
            if previous:
                assert result['ci']['remoteId'] == previous['ci']['remoteId'], 'Resume must not trigger a new workflow.'
                assert result['report']['sha256'] == previous['report']['sha256'], 'Resume must read the same report.'
                assert result['testCounts'] == previous['testCounts'], 'Resume must preserve reported counts.'
                value['resumeVerified'] = True
            value.pop('error', None)
            value['grade'] = result
            wb.db.update_run(run['id'], 'completed', {'grade': result, 'mock': True, 'acceptanceControl': label})
        except Exception as error:
            value['error'] = wb.redact(f'{type(error).__name__}: {error}')
            wb.db.update_run(run['id'], 'failed', {'failure': value['error'], 'mock': True})
        wb.db.set_experiment_status(value['experimentId'], 'failed' if value.get('error') else 'completed')
        return value

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(grade, label): label for label in report['controls']}
        while futures:
            done, _ = concurrent.futures.wait(futures, timeout=30, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                label = futures.pop(future); report['controls'][label] = future.result()
                save(result_path, report)
            states = {label: wb.db.get_run(value['runId']).get('ci', {}) for label, value in report['controls'].items()}
            print(json.dumps({'stage': 'observe-real-github', 'controls': states}), flush=True)
    after = http.request('GET', repo_path + '/git/ref/heads/' + default)['object']['sha']
    report['defaultCommitAfter'] = after
    report['defaultUnchanged'] = after == receipt['defaultCommitBefore']
    grades = [report['controls'][label].get('grade', {}) for label in ['original', 'defective']]
    report['verified'] = (not any(value.get('error') for value in report['controls'].values())
        and grades[0].get('resolved') is True and grades[1].get('resolved') is False
        and grades[0].get('testCounts', {}).get('total') == grades[1].get('testCounts', {}).get('total')
        and report['defaultUnchanged'])
    save(result_path, report)
    print(json.dumps({'verified': report['verified'], 'report': str(result_path), 'controls': report['controls']}), flush=True)
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    try: sys.exit(main())
    except Exception as error:
        # Transport errors are already sanitized. Never print an HTTP body or
        # subprocess stderr that could include credentials.
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        sys.exit(1)

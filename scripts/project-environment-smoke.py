"""Isolated Docker project-environment acceptance. No Provider, production writes or downloads.

Mount this repo read-only at /source and one new /tmp/ctxbench-project-test-* folder
at the same container path, plus the Docker socket. Uses existing application images.
"""
import argparse
import io
import json
import os
import shutil
import tarfile
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, '/source/worker')
from ctxbench_worker.engine import create_engine_from_environment
from ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from ctxbench_worker.runtime import git, seal, extract_baseline
from ctxbench_worker.workbench import Workbench


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--official-image')
    parser.add_argument('--compile-path', default='.')
    parser.add_argument('--test-command-json', default='["python", "-m", "pytest", "--version"]')
    args = parser.parse_args()
    root = args.root.resolve()
    assert root.parent == Path('/tmp') and root.name.startswith('ctxbench-project-test-')
    os.environ.setdefault('CTXBENCH_HOST_DATA_DIR', str(root))
    os.environ['CTXBENCH_BUNDLED_SKILL_DIR'] = '/source/skills/ctxbench-generate-context'
    engine = create_engine_from_environment(root, 'docker')
    wb = Workbench(engine, None)
    save_document = wb.db.put_document
    def save_with_progress(kind, key, document):
        if kind == 'environmentProgress': print(document['message'], flush=True)
        return save_document(kind, key, document)
    wb.db.put_document = save_with_progress
    import docker
    client = docker.from_env(timeout=3600)
    installed = client.images.get('ctxbench/agent-pi:0.1.0').id
    # Exercise current adapter sources without rebuilding/downloading Pi or retagging
    # the installed application image used by the production service.
    adapter = root / 'adapter'; adapter.mkdir()
    for name in ('entrypoint.mjs', 'mock-pi.mjs', 'workflow-runtime.mjs', 'agent-args.mjs'):
        shutil.copyfile(Path('/source/docker/agent-pi') / name, adapter / name)
    (adapter / 'Dockerfile').write_text(f'FROM {installed}\nCOPY *.mjs /opt/ctxbench/\nLABEL io.ctxbench.workflow="1" io.ctxbench.agent-args="1" io.ctxbench.agent-kind="pi"\n')
    donor = client.images.build(path=str(adapter), rm=True, pull=False, network_mode='none')[0].id
    source = None
    try:
        if args.official_image:
            from ctxbench_worker.datasets import TaskRecord
            from ctxbench_worker.project_environment import ProjectEnvironments
            # Probe the image's real baseline source, never a gold/hidden patch.
            original = client.images.get(args.official_image)
            receipt = json.loads(original.labels.get('io.ctxbench.environment-identity', '{}'))
            def source_git(*arguments):
                return client.containers.run(original.id, ['-c', 'safe.directory=/testbed', '-C', '/testbed', *arguments],
                    entrypoint='git', user='root', network='none', remove=True, labels={'io.ctxbench.evaluator':'true'})
            commit = receipt.get('baseCommit') or source_git('rev-parse', 'HEAD').decode().strip()
            repository = 'https://github.com/' + receipt['repository'] + '.git' if receipt.get('repository') else 'https://example.invalid/probe.git'
            workspace = root / 'repositories' / 'official-probe'; workspace.mkdir()
            # Docker logs are not a binary artifact transport: large archives may
            # be truncated by the log driver. Copy the archive through Docker API.
            exporter = client.containers.run(original.id, ['-c', 'safe.directory=/testbed', '-C', '/testbed', 'archive', '--format=tar', '--output=/tmp/ctxbench-baseline.tar', commit],
                entrypoint='git', user='root', network='none', detach=True, labels={'io.ctxbench.evaluator':'true'})
            try:
                assert exporter.wait(timeout=120)['StatusCode'] == 0
                stream, _ = exporter.get_archive('/tmp/ctxbench-baseline.tar')
                with tarfile.open(fileobj=io.BytesIO(b''.join(stream))) as outer:
                    with tarfile.open(fileobj=io.BytesIO(outer.extractfile('ctxbench-baseline.tar').read())) as archive:
                        extract_baseline(archive, workspace)
            finally:
                exporter.remove(force=True)
            assert (workspace / args.compile_path).exists(), 'Compilation target must really exist at baseline'
            baseline = seal(workspace)
            task = TaskRecord('environment-probe', repository, commit, '', args.official_image, None, (), source='swebench' if '/sweb.eval.' in args.official_image else 'agentbench')
            result = ProjectEnvironments(wb.runtime).prepare(task, args.official_image, donor, progress=lambda message: print(message, flush=True))
            frozen_task = task
            task = replace(task, repository=str(workspace), base_commit=baseline, image=result['imageId'], source='custom', test_command=('python', '-m', 'compileall', '-q', args.compile_path))
            empty = root / 'empty.patch'; empty.write_text('')
            grade = wb.runtime.grade(task, root / 'unused', empty, root / 'official-grade', ResourcePolicy(timeout_minutes=3), 'custom')
            assert grade['resolved'], 'Prepared official project cannot execute Python build commands'
            command = json.loads(args.test_command_json)
            assert isinstance(command, list) and command and all(isinstance(arg, str) for arg in command)
            grade = wb.runtime.grade(replace(task, test_command=tuple(command)), root / 'unused', empty, root / 'official-dependency-test', ResourcePolicy(timeout_minutes=3), 'custom')
            assert grade['resolved'], 'Prepared project must retain its runtime/test dependencies'
            again = ProjectEnvironments(wb.runtime).prepare(frozen_task, args.official_image, donor)
            assert again['cached'] and again['imageId'] == result['imageId']
            print(json.dumps({'officialImage':args.official_image,'baselineCommit':commit,'environment':result['imageId'],'baselineCompilationPassed':True,'dependencyTestPassed':True,'cacheReused':True,'providerCalls':0}), flush=True)
            return
        fixture = root / 'fixture'; fixture.mkdir()
        (fixture / '.gitignore').write_text('__pycache__/\n*.pyc\n')
        (fixture / 'app.py').write_text('def add(a, b):\n    return a - b\n')
        (fixture / 'tests').mkdir()
        (fixture / 'tests/test_add.py').write_text('import unittest\nimport fixture_dependency\nfrom app import add\nclass Addition(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2,3), fixture_dependency.EXPECTED)\n')
        baseline = seal(fixture)
        dependency = "import pathlib,sysconfig; p=pathlib.Path(sysconfig.get_paths()['purelib'])/'fixture_dependency.py'; p.write_text('EXPECTED=5\\n')"
        recipe = f'''FROM {donor}
USER root
WORKDIR /testbed
RUN python3 -m venv --without-pip /testbed/.venv
RUN /testbed/.venv/bin/python -c {json.dumps(dependency)}
RUN mkdir -p /testbed/.git/objects /root/.cache && printf FUTURE_SENTINEL > /testbed/.git/objects/future && printf OLD_SOURCE > /testbed/old.py && printf HIDDEN_SENTINEL > /eval.sh && printf CACHE_SENTINEL > /root/.cache/leak
ENV PATH=/testbed/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ENV VIRTUAL_ENV=/testbed/.venv
'''
        source, _ = client.images.build(fileobj=io.BytesIO(recipe.encode()), rm=True, pull=False, network_mode='none')
        dataset = wb.catalog.register('Isolated project environment fixture','custom',[{'id':'addition','repository':str(fixture),'baseCommit':baseline,'prompt':'Fix addition.','image':source.id,'test':{'command':['python','-m','unittest','discover','-s','tests','-v']}}])
        model = ModelConfig('mock','deterministic','off',10000)
        workflow = {'setupCommands':["python -m compileall -q app.py", "python -c 'import fixture_dependency; assert fixture_dependency.EXPECTED == 5'", "test ! -e /testbed/old.py && test ! -e /eval.sh && test ! -e /root/.cache/leak", "test $(git rev-list --all --count) -le 2 && test -z \"$(git remote)\""], 'steps':[{'name':'','prompt':None}]}
        spec = ExperimentSpec('Project image acceptance','custom',dataset['id'],('none','skill-generated'),2,('addition',),model,donor,ResourcePolicy(cpus=1,memory_gb=2,timeout_minutes=3,network='offline'),42,prepare_only=True,project_environment=True,builder_workflow=workflow,solver_workflow=workflow)
        experiment = wb.create_experiment(spec)
        wb.run_experiment(experiment['id'])
        prepared = wb.db.get_document('prepared',experiment['id'])
        assert wb.db.get_experiment(experiment['id'])['status'] == 'ready'
        assert len(wb.db.list_documents('stages')) == 1
        assert all(run['status']=='queued' for run in wb.db.list_runs(experiment['id']))
        assert prepared['agentImages']['addition'] == prepared['graderImages']['addition']
        restored = Workbench(engine, None)
        restored.run_experiment(experiment['id'], start=True)
        runs = wb.db.list_runs(experiment['id'])
        assert len(runs)==4 and all(run['status']=='completed' and run['testsPassed'] is False for run in runs), runs
        assert len({run['pairingHash'] for run in runs}) == 1
        assert len({run['agentImageDigest'] for run in runs}) == 1
        assert len(wb.db.list_documents('stages')) == 5
        task = replace(wb.catalog.task(dataset['id'],'addition'),image=prepared['agentImages']['addition'])
        (fixture/'app.py').write_text('def add(a, b):\n    return a + b\n')
        fix = root/'reference.patch'; fix.write_bytes(git(fixture,'diff','--binary'))
        result = wb.runtime.grade(task,root/'unused',fix,root/'reference-grade',spec.resources,'custom')
        assert result['resolved'], 'Reference fix must pass with the same dependency environment'
        cached = wb.prepare_project_agent(task,spec,donor,source.id)
        assert cached['cached'] and cached['imageId']==task.image
        print(json.dumps({'experimentId':experiment['id'],'runs':4,'builderInvocations':1,'sourceDependenciesAvailable':True,'historyAndEvaluatorMaterialRemoved':True,'baselineFailed':True,'referencePassed':True,'cacheReused':True,'providerCalls':0,'root':str(root)}),flush=True)
    finally:
        # Retain the derived environment and evidence for inspection; never touch existing images.
        client.close()


if __name__ == '__main__': main()

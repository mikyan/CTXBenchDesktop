import io
import json
import tarfile
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from worker.ctxbench_worker.project_environment import ProjectEnvironments, environment_config, identity, project_root, sanitize_filesystem
from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from worker.ctxbench_worker.api import ExperimentInput, _spec


class ProjectEnvironmentTests(unittest.TestCase):
    def test_filesystem_removes_history_old_checkouts_caches_and_evaluator_material(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = {'testbed/app.py': 'OLD_REPOSITORY', 'testbed/.git/objects/future': 'FUTURE_HISTORY',
                       'extra/repo/.git/objects/future': 'HISTORY', 'extra/repo/answer.py': 'OTHER_CHECKOUT',
                       'eval.sh': 'HIDDEN_TEST', 'tmp/gold.patch': 'GOLD', 'root/.cache/object': 'CACHE',
                       'root/.ssh/id_rsa': 'PRIVATE_KEY', 'testbed/.venv/lib/site-packages/dep.py': 'DEPENDENCY',
                       'usr/bin/gcc': 'COMPILER', 'usr/local/bin/python': 'PYTHON', 'home/user/.env': 'CREDENTIAL'}
            with tarfile.open(root / 'source.tar', 'w') as archive:
                for name in ('testbed', 'testbed/.venv', 'testbed/.venv/lib', 'root'):
                    member = tarfile.TarInfo(name); member.type = tarfile.DIRTYPE; archive.addfile(member)
                for name, text in content.items():
                    member = tarfile.TarInfo(name); data = text.encode(); member.size = len(data); member.mode = 0o6755
                    archive.addfile(member, io.BytesIO(data))
                link = tarfile.TarInfo('testbed/.venv/lib64'); link.type = tarfile.SYMTYPE; link.linkname = 'lib'; archive.addfile(link)
            dependencies = sanitize_filesystem(root / 'source.tar', root / 'clean.tar', '/testbed')
            self.assertEqual(dependencies, ['.venv'])
            with tarfile.open(root / 'clean.tar') as archive:
                names = archive.getnames()
                self.assertIn('opt/ctxbench-dependencies/.venv/lib/site-packages/dep.py', names)
                self.assertEqual(archive.getmember('testbed').linkname, '/workspace')
                self.assertEqual(archive.getmember('opt/ctxbench-dependencies/.venv/lib64').linkname, '/testbed/.venv/lib')
                self.assertFalse(archive.getmember('usr/bin/gcc').mode & 0o6000)
                text = '\n'.join(archive.extractfile(m).read().decode() for m in archive if m.isfile())
                for sentinel in ('OLD_REPOSITORY', 'FUTURE_HISTORY', 'OTHER_CHECKOUT', 'HIDDEN_TEST', 'GOLD', 'CACHE', 'PRIVATE_KEY', 'CREDENTIAL'):
                    self.assertNotIn(sentinel, text)
                self.assertIn('DEPENDENCY', text)

    def test_rejects_unsafe_paths_before_host_extraction(self):
        for name in ('../../outside', '/etc/outside', 'x\\bad'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with tarfile.open(root / 'source.tar', 'w') as archive:
                    archive.addfile(tarfile.TarInfo(name))
                with self.assertRaises(ValueError):
                    sanitize_filesystem(root / 'source.tar', root / 'clean.tar', '/testbed')

    def test_task_blind_identity_preserves_project_runtime_not_donor_environment(self):
        env = environment_config({'Env': ['PATH=/opt/venv/bin:/bin', 'VIRTUAL_ENV=/opt/venv', 'OPENAI_API_KEY=NEVER_COPY', 'OTHER=NO']})
        self.assertEqual(env['VIRTUAL_ENV'], '/opt/venv')
        self.assertEqual(env['PATH'], '/opt/ctxbench-pi/bin:/opt/venv/bin:/bin')
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('OTHER', env)
        self.assertNotIn('NEVER_COPY', json.dumps(identity('repo', 'a'*40, 'source', 'adapter', '/testbed', env)))
        for path in ('/usr', '/usr/local/bin', '/root', '/root/repo', '/tmp', '/tmp/repo', '../testbed', '/x/../etc', '/opt/ctxbench', '/home/ctxbench', '/workspace/nested'):
            with self.assertRaises(ValueError): project_root({'WorkingDir': path})
        self.assertEqual(project_root({'WorkingDir': '/testbed/'}), '/testbed')

    def test_swe_environment_activation_does_not_run_evaluator_shell_scripts(self):
        config = {'Env':['PATH=/opt/miniconda3/bin:/bin']}
        env = environment_config(config, 'swebench')
        self.assertEqual(env['CONDA_PREFIX'], '/opt/miniconda3/envs/testbed')
        self.assertIn('/opt/miniconda3/envs/testbed/bin:', env['PATH'])
        self.assertNotIn('CONDA_PREFIX', environment_config(config, 'custom'))
        active = environment_config({'Env':config['Env']+['VIRTUAL_ENV=/opt/custom-venv']}, 'swebench')
        self.assertNotIn('CONDA_PREFIX', active)

    def test_cached_image_must_have_valid_receipt_and_does_not_export_or_run(self):
        import hashlib
        source = SimpleNamespace(id='sha256:source', attrs={'Os':'linux','Architecture':'amd64','Config':{'WorkingDir':'/testbed'}}, labels={})
        agent = SimpleNamespace(id='sha256:agent', attrs={'Os':'linux','Architecture':'amd64','Config':{}}, labels={'io.ctxbench.agent-kind':'pi'})
        task = SimpleNamespace(repository='repo', base_commit='a'*40, prompt='PRIVATE_PROMPT', gold_patch='PRIVATE_GOLD')
        receipt = identity('repo', 'a'*40, source.id, agent.id, '/testbed', environment_config(source.attrs['Config']))
        key = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
        client = Mock()
        cached = SimpleNamespace(id='cached', labels={'io.ctxbench.project-key':key,'io.ctxbench.project-validated':'1', 'io.ctxbench.project-identity':json.dumps(receipt)})
        client.images.get.side_effect = [source, agent, cached]
        with patch.dict('sys.modules', docker=SimpleNamespace(from_env=lambda **kwargs:client, errors=SimpleNamespace(ImageNotFound=KeyError))):
            result = ProjectEnvironments(SimpleNamespace()).prepare(task, source.id, agent.id)
        self.assertTrue(result['cached']); client.containers.create.assert_not_called(); client.api.build.assert_not_called()
        client.close.assert_called_once()
        cached.labels['io.ctxbench.project-key'] = 'wrong'
        client.images.get.side_effect = [source, agent, cached]
        with patch.dict('sys.modules', docker=SimpleNamespace(from_env=lambda **kwargs:client, errors=SimpleNamespace(ImageNotFound=KeyError))):
            with self.assertRaisesRegex(ValueError, 'invalid preparation receipt'):
                ProjectEnvironments(SimpleNamespace()).prepare(task, source.id, agent.id)

    def test_new_requests_enable_preparation_but_legacy_specs_keep_original_behavior(self):
        model = ModelConfig('mock', 'deterministic', 'off', 100)
        legacy = ExperimentSpec('legacy','custom','dataset',('none','skill-generated'),1,('task',),model,'image',ResourcePolicy(),42)
        self.assertFalse(legacy.project_environment)
        value = dict(name='new', benchmark='custom',dataset='dataset',arms=['none','skill-generated'],repeats=1,taskIds=['task'],
                     model=dict(provider='mock',model='deterministic'), profiles={role:dict(provider='mock',model='deterministic') for role in ('builder','solver','constraintMiner','constraintJudge')},resources={},seed=42)
        self.assertTrue(_spec(ExperimentInput.model_validate(value)).project_environment)
        self.assertFalse(_spec(ExperimentInput.model_validate({**value, 'projectEnvironment':False})).project_environment)

    def test_recovery_only_reaps_stopped_exports_owned_by_this_data_directory(self):
        client = Mock()
        stopped, active = Mock(status='created'), Mock(status='running')
        client.containers.list.return_value = [stopped, active]
        runtime = SimpleNamespace(root=Path('/data'), host_path=lambda path: '/home/user/ctxbench-data')
        with patch('docker.from_env', return_value=client):
            ProjectEnvironments(runtime).recover_exports()
        filters = client.containers.list.call_args.kwargs['filters']
        self.assertTrue(filters['label'].startswith('io.ctxbench.project-owner='))
        self.assertNotIn('/data', filters['label'])
        stopped.remove.assert_called_once_with(); active.remove.assert_not_called()

    def test_imported_prepared_image_requires_same_baseline_adapter_and_implementation(self):
        import hashlib
        source_config = {'WorkingDir':'/testbed'}
        receipt = identity('repo', 'a'*40, 'source', 'adapter', '/testbed', environment_config(source_config))
        source = SimpleNamespace(id='prepared', attrs={'Config':{}}, labels={'io.ctxbench.project-validated':'1',
            'io.ctxbench.project-identity':json.dumps(receipt), 'io.ctxbench.project-key':hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()})
        agent = SimpleNamespace(id='adapter', attrs={'Config':{}}, labels={'io.ctxbench.agent-kind':'pi'})
        client = Mock()
        for commit, expected in [('a'*40, True), ('b'*40, False)]:
            client.images.get.side_effect = [source, agent]
            with patch('docker.from_env', return_value=client):
                module = ProjectEnvironments(SimpleNamespace())
                task = SimpleNamespace(repository='repo', base_commit=commit)
                if expected:
                    self.assertEqual(module.prepare(task, 'source', 'adapter')['imageId'], 'prepared')
                else:
                    with self.assertRaisesRegex(ValueError, 'another baseline'):
                        module.prepare(task, 'source', 'adapter')
        client.api.build.assert_not_called()

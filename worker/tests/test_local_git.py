import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.ctxbench_worker.runtime import Runtime, git, local_fetch_options, seal
from worker.ctxbench_worker.datasets import custom_task


class LocalGitTests(unittest.TestCase):
    def setUp(self):
        # Do not let developer-global Git hooks or trace consumers act on these
        # disposable repositories (including after the Git process has exited).
        environment = patch.dict(os.environ, {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
        environment.start()
        self.addCleanup(environment.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "selected repo ' with spaces"
        self.repo.mkdir()
        (self.repo / 'baseline.txt').write_text('baseline only', encoding='utf-8')
        self.commit = seal(self.repo)
        self.before = (self.repo / '.git/config').read_bytes()

    def test_local_transport_only_trusts_exact_paths_and_quotes_shell_metacharacters(self):
        option, = local_fetch_options(str(self.repo))
        argv = shlex.split(option.split('=', 1)[1])
        self.assertEqual(argv, ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'safe.directory=',
                               '-c', 'safe.directory=' + self.repo.as_posix(),
                               '-c', 'safe.directory=' + (self.repo / '.git').as_posix(), 'upload-pack'])
        self.assertNotIn('safe.directory=*', option)
        for remote in ('https://git.example/team/repo.git', 'ssh://git.example/repo', 'git@git.example:repo',
                       'file:///tmp/repo', 'origin', '../repo', str(self.root / 'missing'), str(self.root)):
            self.assertEqual(local_fetch_options(remote), [], remote)

    def test_foreign_owned_source_fetch_is_command_scoped_and_preserves_pinned_commit(self):
        destination = self.root / 'destination'; destination.mkdir(); git(destination, 'init', '-q')
        # Exercise ownership without chown, sudo or host-global trust. New Git
        # upload-pack accepts foreign owners (ENTER_REPO_ANY_OWNER_OK), whereas
        # repository discovery still checks ownership. Probe that independently
        # so both transport policies verify our command-scoped compatibility.
        environment = {**os.environ, 'GIT_TEST_ASSUME_DIFFERENT_OWNER': '1',
                       'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
        base = ['git', '-c', 'maintenance.auto=false', '-c', 'gc.auto=0',
                '-c', 'safe.directory=', '-c', 'safe.directory=' + destination.as_posix(), '-C', str(destination)]
        ownership_probe = ['git', '-c', 'safe.directory=', '-C', str(self.repo), 'rev-parse', 'HEAD']
        untrusted = subprocess.run(ownership_probe, env=environment, capture_output=True)
        self.assertNotEqual(untrusted.returncode, 0)
        self.assertIn(b'dubious ownership', untrusted.stderr)
        failed = subprocess.run([*base, 'fetch', '--depth=1', str(self.repo), self.commit], env=environment, capture_output=True)
        if failed.returncode != 0:
            self.assertIn(b'dubious ownership', failed.stderr)
        fixed = subprocess.run([*base, 'fetch', '--depth=1', *local_fetch_options(str(self.repo)), str(self.repo), self.commit], env=environment, capture_output=True)
        self.assertEqual(fixed.returncode, 0, fixed.stderr.decode(errors='replace'))
        self.assertEqual(git(destination, 'rev-parse', 'FETCH_HEAD').decode().strip(), self.commit)
        self.assertEqual((self.repo / '.git/config').read_bytes(), self.before)
        self.assertEqual((self.repo / 'baseline.txt').read_text(encoding='utf-8'), 'baseline only')
        again = subprocess.run([*base, 'fetch', '--depth=1', str(self.repo), self.commit], env=environment, capture_output=True)
        self.assertEqual(again.returncode, failed.returncode, 'Scoped fetch must not change the unscoped transport policy')
        still_untrusted = subprocess.run(ownership_probe, env=environment, capture_output=True)
        self.assertNotEqual(still_untrusted.returncode, 0, 'Trust must not persist after the scoped fetch')
        self.assertIn(b'dubious ownership', still_untrusted.stderr)

    def test_baseline_uses_selected_source_or_configured_local_mirror_without_identity_change(self):
        task = custom_task({'id': 'fixture', 'repository': 'https://git.example/original', 'baseCommit': self.commit,
                            'prompt': 'Keep fixed', 'image': 'fixture:v1', 'test': {'command': ['true']}})
        runtime = Runtime(self.root / 'runtime', None)
        with runtime.using_environment({'gitMirrors': [{'repository': task.repository, 'mirror': str(self.repo)}]}):
            source, _ = runtime.baseline(task)
        self.assertEqual(git(source, 'rev-parse', 'FETCH_HEAD').decode().strip(), self.commit)
        self.assertEqual(git(source, 'remote', 'get-url', 'origin').decode().strip(), task.repository)
        self.assertEqual((self.repo / '.git/config').read_bytes(), self.before)

    def test_bare_source_and_non_repository_boundaries(self):
        bare = self.root / 'selected-bare.git'
        subprocess.run(['git', 'clone', '--bare', str(self.repo), str(bare)], check=True, capture_output=True)
        argv = shlex.split(local_fetch_options(str(bare))[0].split('=', 1)[1])
        self.assertEqual([item for item in argv if item.startswith('safe.directory=')], ['safe.directory=', 'safe.directory=' + bare.as_posix()])
        linked = self.root / 'linked'; linked.mkdir()
        (linked / '.git').write_text('gitdir: ' + str(self.repo / '.git'), encoding='utf-8')
        self.assertEqual(local_fetch_options(str(linked)), [])


if __name__ == '__main__':
    unittest.main()

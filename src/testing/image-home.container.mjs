/** Generic image HOME regression: disposable offline containers, no mounts or credentials.
 * Run with Node 24 (type stripping), WSL Docker and the already-installed bundled Pi base.
 * This does not install an Agent, build a user image, run a benchmark or mutate a base image.
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { guidedDockerfile } from '../lib/image-recipes.ts';

const recipe = guidedDockerfile('', 'HOME=/home/ctxbench', []);
const commands = recipe.split('\n').filter(line => line.startsWith('RUN ')).map(line => line.slice(4));
assert.equal(commands.length, 3, 'Expected initial safety, post-install ownership, and UID probe');
assert(recipe.includes('USER 10001:10001\nRUN '), 'Build-time probe must use the actual runtime UID');
const script = `
import json, os, pathlib, subprocess, sys
commands = json.load(sys.stdin)
home = pathlib.Path('/home/ctxbench')
outside = pathlib.Path('/tmp/ctxbench-home-test-outside')
outside.mkdir(mode=0o700)
mode = sys.argv[1]
fixture_parent = pathlib.Path('/tmp/ctxbench-home-test-parent')
fixture_parent.mkdir()
fixture_home = fixture_parent / 'home'
guard_fixture = commands[0].replace('/home', str(fixture_home))
if mode == 'root-symlink':
    fixture_home.mkdir()
    (fixture_home / 'ctxbench').symlink_to(outside, target_is_directory=True)
    result = subprocess.run(['/bin/sh', '-eu', '-c', guard_fixture], capture_output=True)
    assert result.returncode != 0, 'Refuse symlink HOME before any chown'
    assert outside.stat().st_uid == 0, 'Never chown the symlink target'
elif mode == 'parent-symlink':
    fixture_home.symlink_to(outside, target_is_directory=True)
    result = subprocess.run(['/bin/sh', '-eu', '-c', guard_fixture], capture_output=True)
    assert result.returncode != 0, 'Refuse symlink /home before any chown'
    assert outside.stat().st_uid == 0
else:
    subprocess.run(['/bin/sh', '-eu', '-c', commands[0]], check=True)
    nested = home / '.local/share/fixture-agent/log'
    nested.mkdir(parents=True, mode=0o700)
    assert nested.stat().st_uid == 0, 'Fixture simulates a root installation or version check'
    (home / 'outside-link').symlink_to(outside, target_is_directory=True)
    subprocess.run(['/bin/sh', '-eu', '-c', commands[1]], check=True)
    assert nested.stat().st_uid == 10001
    assert outside.stat().st_uid == 0, 'Recursive repair must not follow child symlinks'
    def runtime_user(): os.setgroups([]); os.setgid(10001); os.setuid(10001)
    subprocess.run(['/bin/sh', '-eu', '-c', commands[2]], check=True, preexec_fn=runtime_user)
    subprocess.run(['/bin/sh', '-eu', '-c', 'printf fixture > /home/ctxbench/.local/share/fixture-agent/log/output.log'], check=True, preexec_fn=runtime_user)
print(json.dumps({'scenario': mode, 'passed': True, 'runtimeUid': 10001, 'baseImageUnchanged': True}))
`;
const distribution = process.env.CTXBENCH_TEST_DISTRIBUTION || 'Ubuntu';
const base = 'ctxbench/agent-pi:0.1.0';
for (const scenario of ['root-install-cache', 'root-symlink', 'parent-symlink']) {
  const result = execFileSync('wsl', ['-d', distribution, '--', 'docker', 'run', '--rm', '-i', '--network', 'none', '--user', '0:0',
    '--label', 'io.ctxbench.test=home-permissions', '--entrypoint', 'python3', base, '-c', script, scenario],
    { input: JSON.stringify(commands), encoding: 'utf8', timeout: 30000, windowsHide: true });
  console.log(result.trim());
}

// Restore dependency locations without restoring any baked repository or Git history.
import { readFile, lstat, symlink, appendFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
const config = JSON.parse(await readFile('/opt/ctxbench-project.json', 'utf8'));
const grading = process.argv[2] === '--test-command';
if (config.version !== 1 || !Array.isArray(config.dependencies) || config.dependencies.some(name => !['.venv', 'venv', 'node_modules'].includes(name))) throw Error('Invalid project environment receipt.');
for (const name of config.dependencies) {
  const target = `/workspace/${name}`;
  try { await lstat(target); throw Error(`Baseline conflicts with prepared dependency folder: ${name}`); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  await symlink(`/opt/ctxbench-dependencies/${name}`, target);
  await appendFile('/workspace/.git/info/exclude', `\n/${name}\n`);
}
// The adapter and Pi need Node 22; project build commands retain their own runtime.
process.env.CTXBENCH_PI_NODE = process.execPath;
const git = spawnSync('git', ['-c', 'safe.directory=/workspace', 'status', '--porcelain'], {cwd:'/workspace', encoding:'utf8'});
if (git.status !== 0 || (!grading && git.stdout.trim())) throw Error('Prepared dependencies changed the frozen baseline.');
if (grading) {
  const command = JSON.parse(process.argv[3]);
  if (!Array.isArray(command) || !command.length || command.some(arg => typeof arg !== 'string' || arg.includes('\0'))) throw Error('Invalid test command.');
  const result = spawnSync(command[0], command.slice(1), {cwd:'/workspace', env:process.env, stdio:'inherit'});
  if (result.error) { console.error(result.error.message); process.exit(127); }
  process.exit(result.status ?? 1);
} else await import('./entrypoint.mjs');

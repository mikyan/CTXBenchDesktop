export type RecipeFile = { path: string; base64: string };
export type GuidedRecipe = { name: string; baseImage: string; dockerfile: string; files: RecipeFile[]; network: 'none' | 'bridge' };
export const dependencyTemplates = {
  python: 'python3 -m venv /opt/venv\n/opt/venv/bin/pip install --no-cache-dir pytest',
  node: 'npm install --global YOUR_AGENT_PACKAGE',
  java: 'apt-get update\napt-get install -y --no-install-recommends openjdk-17-jdk-headless maven\nrm -rf /var/lib/apt/lists/*',
  adapter: 'apt-get update\napt-get install -y --no-install-recommends python3 git ca-certificates\nrm -rf /var/lib/apt/lists/*',
};
export function guidedDockerfile(commands: string, defaults: string, files: RecipeFile[]): string {
  const lines = ['USER root', 'RUN mkdir -p /opt/company /home/ctxbench && chown 10001:10001 /home/ctxbench'];
  for (const file of files) {
    if (!/^[\w./-]+$/.test(file.path) || file.path.startsWith('/') || file.path.split('/').some((part) => ['..', '.', ''].includes(part))) throw Error('Use relative build paths without traversal.');
    lines.push(`COPY ${JSON.stringify([file.path, '/opt/company/' + file.path])}`);
  }
  if (commands.trim()) lines.push('RUN ' + JSON.stringify(['/bin/sh', '-eu', '-c', commands]));
  const recipe = lines.join('\n');
  const env = defaults.split(/\r?\n/).filter((line) => line.trim());
  const seen = new Set<string>();
  for (const line of env) {
    const match = /^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/.exec(line);
    if (!match || /(?:TOKEN|PASSWORD|SECRET|API_KEY|PRIVATE_KEY|ACCESS_KEY)/i.test(match[1]) || seen.has(match[1])) throw Error('Use unique NAME=value defaults without credentials.');
    seen.add(match[1]);
  }
  return recipe + '\n' + env.map((line) => {
    const split = line.indexOf('=');
    return 'ENV ' + line.slice(0, split) + '=' + JSON.stringify(line.slice(split + 1)).replaceAll('$', '\\$');
  }).join('\n') + '\nWORKDIR /workspace\n';
}

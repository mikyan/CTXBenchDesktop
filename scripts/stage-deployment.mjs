import { copyFileSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const destination = path.join(root, ".desktop-deployment");
if (path.dirname(destination) !== root || path.basename(destination) !== ".desktop-deployment") throw new Error("Invalid staging directory");
if (existsSync(destination)) rmSync(destination, { recursive: true });
const files = ["docker/compose.yaml", "worker/requirements.txt", "README.md", "docs/architecture.md", "docs/evaluation.md", "docs/agent-adapters.md", "docs/reassessment.md", "scripts/images-export.sh", "scripts/images-import.sh", "scripts/wsl/install-docker.sh", "scripts/container-smoke.py", "scripts/container-resilience.py", "scripts/scale-smoke.py", "scripts/verify-live-experiment.py", "scripts/regrade-acceptance.py"];
files.push('scripts/run-campaign.py', 'README.zh-CN.md');
files.push('scripts/container-environment-smoke.py', 'scripts/container-workflow-smoke.py');
files.push('scripts/images-release.py', 'docs/offline-images.md');
files.push('docs/custom-datasets.md');
files.push('docs/desktop-setup.md');
files.push('docs/standard-datasets.md');
files.push('docs/intranet-workbench.md', 'scripts/container-intranet-smoke.py');
for (const folder of ["docker/agent-pi", "docker/official-harness", "docker/worker", "docker/egress-proxy", "worker/ctxbench_worker", "skills/ctxbench-generate-context", "schemas"]) {
  for (const entry of readdirSync(path.join(root, folder), { withFileTypes: true })) {
    if (entry.isFile() && !entry.name.startsWith(".") && !entry.name.endsWith(".pyc")) files.push(`${folder}/${entry.name}`);
  }
}
for (const relative of files) {
  if (relative.includes(".env")) throw new Error("Credentials may not enter a deployment bundle");
  const target = path.join(destination, relative);
  mkdirSync(path.dirname(target), { recursive: true });
  copyFileSync(path.join(root, relative), target);
}
console.log(`Staged ${files.length} deployment files without runtime credentials.`);

// Hints describe the bundled recipes, not compatibility guarantees for arbitrary retagged images.
export function bundledImageRole(reference: string): "agent" | "harness" | "worker" | "proxy" | undefined {
  const repository = reference.split("@")[0].replace(/:[^/:]+$/, "");
  const roles: Record<string, "agent" | "harness" | "worker" | "proxy"> = { "ctxbench/agent-pi": "agent", "ctxbench/official-harness": "harness", "ctxbench/worker": "worker", "ctxbench/egress-proxy": "proxy" };
  return Object.hasOwn(roles, repository) ? roles[repository] : undefined;
}
export const imageRoleHints = {
  agent: "Pi image: Node.js/npm and Python 3 are included. Standard-library tests can reuse it; pytest and project dependencies are not preinstalled. Use python3, not python.",
  harness: "Official harness image: imports and grades official datasets. It is not the per-repository test environment; official tasks still need their own dependencies and images.",
  worker: "Service image: runs the local API and scheduler. Its dependencies are for CTXBench itself, not your project; it is not recommended as a project test image.",
  proxy: "Proxy image: controls network access. It is not intended to run project tests.",
};

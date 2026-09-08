export type WorkerAction = "start" | "stop" | "build" | "logs";
export interface BuildProgressEvent {
  phase: "checking" | "building";
  lines: string[];
  elapsedMs: number;
  lastOutputMs: number | null;
}
export interface WorkerActionResult { ok: boolean; code: string; detail: string; command?: string | null }
export interface ExportImageSelection { role: string; reference: string }
export interface LocalImageInventory { images: string[]; error: WorkerActionResult | null }
export interface ActiveContainer { id: string; name: string; status: string; role: "worker" | "agent" | "grader" }
export interface DeploymentInfo {
  distribution: string;
  composePath: string;
  wslComposePath: string | null;
  dataDirectory: string | null;
  checks: { id: string; ok: boolean; detail: string }[];
  missingImages: string[];
  containers: string[];
  activeContainers?: ActiveContainer[];
  activityError?: string | null;
}

export function activityState(info?: DeploymentInfo) {
  const known = Boolean(info && Array.isArray(info.activeContainers) && info.activityError === null);
  const containers = info?.activeContainers ?? [];
  return { known, containers, tasks: containers.filter((item) => item.role !== "worker"), canReplace: known && containers.length === 0 };
}

export type RecoveryAction = "check" | "logs" | "runtime" | "images" | "offline" | "downloads" | "credentials";
export const recoveryLabels: Record<RecoveryAction, string> = {
  check: "Recheck status", logs: "Read container logs", runtime: "Go to runtime controls", images: "Prepare application images",
  offline: "Switch to offline installation", downloads: "Open release downloads", credentials: "Configure runtime credentials",
};
export function recoveryActions(code: string): RecoveryAction[] {
  switch (code) {
    case "worker_running": case "active_runs": case "activity_unknown": return ["check", "runtime"];
    case "worker_health": case "port_in_use": case "timeout": return ["check", "logs", "runtime"];
    case "network": return ["offline", "check"];
    case "bundle_invalid": case "bundle_version": case "offline_tool": case "compose_file": return ["downloads", "check"];
    case "images": return ["images", "check"];
    case "images_import": case "build": return ["runtime"];
    case "start": return ["credentials"];
    case "stop": return ["images", "check"];
    case "logs": case "images_export": return [];
    default: return ["check"];
  }
}

export const setupMessages: Record<string, { title: string; help: string }> = {
  images_export: { title: "Custom image ZIP exported", help: "Copy this ZIP to another computer running the same desktop version and select it in Offline installation. Existing images and running containers were not changed. This is a customized local bundle, not an official source-built release." },
  export_exists: { title: "The export filename is already in use", help: "Choose a new ZIP filename. Existing files and .incomplete files are never overwritten; inspect any partial output before removing it manually." },
  export_path: { title: "The export destination is unavailable", help: "Choose a new ZIP file in an existing writable folder accessible from the selected WSL. Reserve space for temporary compressed parts and the final ZIP on that drive." },
  export_credentials: { title: "The image or deployment configuration contains credential settings", help: "Rebuild without embedded credentials and remove plaintext credentials from deployment configuration. Runtime API keys must be supplied separately. Export cannot remove secrets from existing image layers or automatically audit all files in them." },
  export_platform: { title: "The image platform is incompatible", help: "Select locally installed Linux amd64 images for all four roles and use a Linux amd64 Docker Engine in WSL." },
  export_selection: { title: "Choose one image for each application role", help: "Provide all four image references without duplicates in the role mapping. Use a local tag or digest, not a container name, URL or shell command." },
  images_import: { title: "Offline images imported", help: "Next, click Start worker. No images were downloaded or built, and no containers were started. Existing image tags were preserved as backups." },
  bundle_invalid: { title: "The offline package is invalid or incomplete", help: "Choose the original offline images ZIP from the matching release, not the Windows installer or source-code ZIP. For legacy bundles, keep all parts together and select ctxbench-images-manifest.json. Redownload damaged or missing files." },
  bundle_version: { title: "The offline package version does not match", help: "Use a desktop installer and offline images package from the same release. Do not mix versions; download the matching package and retry." },
  python: { title: "Python is unavailable in the selected WSL", help: "Install Python 3.10 or later in this WSL distribution using your organization's approved source. No pip packages are needed for offline import." },
  offline_tool: { title: "The packaged offline importer is missing", help: "Reinstall the complete desktop application. The trusted importer must be present at deployment/scripts/images-release.py; scripts inside the downloaded package are never executed." },
  worker_running: { title: "Running CTXBench containers block image replacement", help: "This is an image preparation safeguard, not a new image startup failure. Pause experiments, wait for generation and grading to finish, then use the Stop worker control on this page. Closing the desktop does not stop the worker. No images were replaced by this blocked attempt." },
  active_runs: { title: "Benchmark containers are still active", help: "Pause experiment scheduling and wait for active Agent, knowledge generation and grading work to finish. Refresh the container list before stopping, starting or replacing the worker. Do not delete containers or volumes to bypass this safeguard." },
  activity_unknown: { title: "Container activity could not be verified", help: "An unavailable status is not an idle system. Check the selected WSL and Docker access, then recheck. Mutating operations will verify activity again; logs and diagnostics remain available." },
  busy: { title: "Another infrastructure operation is in progress", help: "Wait for the current import, export, build or worker operation to finish. Do not launch a second copy. If an operation timed out, inspect Docker before retrying." },
  offline_platform: { title: "The offline image platform is incompatible", help: "This package requires a Linux amd64 Docker Engine in the selected WSL distribution. It cannot be loaded into Windows containers or an ARM64 daemon." },
  compose_file: { title: "Deployment file not found", help: "The installer must include deployment/docker/compose.yaml next to the application. Reinstall the complete desktop package; do not move only the executable. The filename ends in .yaml, not .yml." },
  wsl_path: { title: "WSL cannot access the deployment file", help: "Check that the selected distribution can access the Windows installation drive. Use the absolute path shown below; a relative docker/compose.yaml path only works from the deployment directory." },
  compose: { title: "Docker Compose is unavailable", help: "Docker Engine and Docker Compose are separate checks. Install the Compose plugin inside the selected WSL distribution using your organization's approved package source, then check again." },
  compose_config: { title: "Deployment configuration could not be read", help: "Check the deployment file and its environment-variable settings. Do not share .env files or credential values; use the redacted details below." },
  docker: { title: "Docker Engine is unavailable", help: "Start Docker Engine inside the selected WSL distribution and make sure your WSL user can access it. Docker in a different distribution does not count." },
  images: { title: "Required application images are missing", help: "The Windows installer does not include Docker images. Offline: import all image files from the matching release into this WSL distribution. Online: build images first. Starting the worker never downloads or builds images." },
  data_directory: { title: "The WSL data directory is unavailable", help: "Create the data directory shown below inside the selected WSL distribution, or fix its bind-mount setting. Keep the host data path and worker mount consistent; do not delete an existing experiment directory." },
  permission: { title: "Permission denied", help: "Check access to the Docker socket and deployment/data directories in WSL. Ask your administrator for the required access; do not disable security controls or use chmod 777." },
  port_in_use: { title: "Port 48173 is already in use", help: "Check which process or container owns port 48173. Do not stop an unrelated service. CTXBench currently requires this local port." },
  disk_space: { title: "Insufficient disk space", help: "Check both free space inside WSL and on the Windows drive holding its virtual disk. Image builds and benchmark data consume space; do not delete experiment evidence blindly." },
  timeout: { title: "The operation timed out", help: "WSL startup or image building took too long. Check container status and logs before retrying; a timed-out command does not guarantee Docker stopped its background work." },
  network: { title: "A network or certificate check failed", help: "For an internal network, import offline images or configure approved internal registries and CA certificates. Do not disable TLS verification." },
  worker_health: { title: "Containers were started, but the worker is not reachable", help: "Read container logs below. If the worker is running, check Windows-to-WSL localhost forwarding and port 48173. Local worker requests bypass HTTP proxies; do not expose the worker to the public network." },
  action: { title: "The operation could not be completed", help: "Read the redacted technical details, check deployment prerequisites, and retry after correcting the cause. Copy the diagnostic report if you need help." },
  start: { title: "Worker started and health check passed", help: "You can now configure Agent environment variables and import a dataset. Starting the worker does not launch a benchmark or call a Provider." },
  stop: { title: "Worker stop command completed", help: "Only this deployment's worker was targeted; data and other deployments were not deleted. Recheck for remaining containers before importing images. After restarting, re-enter any credentials supplied through the runtime-only settings." },
  build: { title: "Application images built", help: "Next, start the worker. Building images does not import datasets or run benchmarks." },
  logs: { title: "Recent container logs", help: "Logs are redacted before display and limited to the latest 80 lines per service. An empty result may mean the containers have not been created." },
};

export const prerequisiteLabels: Record<string, string> = {
  compose_file: "Packaged deployment file",
  wsl_path: "WSL deployment file access",
  compose: "Docker Compose plugin",
  compose_config: "Deployment configuration",
  docker: "Docker Engine",
  images: "Four application images",
  data_directory: "WSL data directory",
};

export function setupMessage(code: string) { return setupMessages[code] ?? setupMessages.action; }
export function quoteShell(value: string, shell: "wsl" | "powershell"): string {
  return `'${value.replaceAll("'", shell === "wsl" ? `'"'"'` : "''")}'`;
}
export function setupCommands(info: DeploymentInfo, shell: "wsl" | "powershell"): Record<string, string> {
  if (!info.wslComposePath) return {};
  const quote = (value: string) => quoteShell(value, shell);
  const prefix = shell === "powershell" ? `wsl.exe --distribution ${quote(info.distribution)} --exec ` : "";
  const compose = `${prefix}docker compose -f ${quote(info.wslComposePath)}`;
  return {
    start: `${compose} up -d --no-build --pull never ctxbench-worker`,
    status: `${compose} ps -a`,
    stop: `${compose} stop ctxbench-worker`,
    activity: ["com.docker.compose.service=ctxbench-worker", "io.ctxbench.run", "io.ctxbench.evaluator"].map((label) => `${prefix}docker ps --filter ${quote(`label=${label}`)} --format ${quote("table {{.ID}}\\t{{.Names}}\\t{{.Status}}")}`).join("\n"),
    space: `${prefix}df -h /`,
    port: `${prefix}docker ps --filter ${quote("publish=48173")} --format ${quote("table {{.ID}}\\t{{.Names}}\\t{{.Ports}}")}`,
    build: `${compose} --profile build-only build`,
    ...(info.dataDirectory?.startsWith("/") ? { directory: `${prefix}sudo mkdir -p -- ${quote(info.dataDirectory)}` } : {}),
  };
}

export function diagnosticReport(info: DeploymentInfo | undefined, result: WorkerActionResult | undefined): string {
  return ["CTXBench deployment diagnostics", ...(info ? [
    `Distribution: ${info.distribution}`, `Windows Compose: ${info.composePath}`, `WSL Compose: ${info.wslComposePath ?? "unavailable"}`,
    ...info.checks.map((check) => `${check.id}: ${check.ok ? "OK" : "FAILED"}\n${check.detail}`), ...info.containers,
    `Container activity: ${activityState(info).known ? "checked" : "unknown"}`,
    ...(info.activityError ? [info.activityError] : []),
    ...(info.activeContainers ?? []).map((item) => `${item.id} · ${item.name} · ${item.role} · ${item.status}`),
  ] : []), ...(result ? [`Operation: ${result.code} (${result.ok ? "OK" : "FAILED"})`, result.detail] : [])].join("\n\n");
}

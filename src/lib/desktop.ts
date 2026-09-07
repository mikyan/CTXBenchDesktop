import { Channel, invoke } from "@tauri-apps/api/core";
import { createDemoSnapshot } from "../data/demo";
import { planExperimentRuns } from "../domain/planner";
import { renderSnapshotHtml } from "../domain/report";
import { aggregateArms, aggregateDashboard } from "../domain/metrics";
import { savedDistribution, type WslInventory } from "./wsl";
import type { BuildProgressEvent, DeploymentInfo, WorkerAction, WorkerActionResult } from "./infrastructure";
import type {
  CreateExperimentRequest,
  DashboardSnapshot,
  DiagnosticItem,
  Experiment,
} from "../domain/types";

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

const pause = (milliseconds: number): Promise<void> =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export async function loadSnapshot(): Promise<DashboardSnapshot> {
  if (new URLSearchParams(window.location.search).get("demo") === "1") return createDemoSnapshot();
  const snapshot = await workerRequest<DashboardSnapshot>("/snapshot?compact=true");
  const realRuns = snapshot.runs.filter((run) => !run.mock);
  return { ...snapshot, metrics: aggregateDashboard(realRuns), armMetrics: aggregateArms(realRuns) };
}

export async function workerRequest<T>(path: string, method: "GET" | "POST" = "GET", body?: unknown): Promise<T> {
  if (isTauri()) return invoke<T>("worker_request", { method, path, body: body ?? null });
  const response = await fetch(`/worker${path}`, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  let payload;
  try { payload = await response.json(); } catch { throw new Error("The WSL worker is unavailable. Start it from Infrastructure and retry."); }
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail ?? payload));
  return payload as T;
}

export async function listWslDistributions(): Promise<WslInventory> {
  if (!isTauri()) throw new Error("WSL detection requires the desktop application.");
  return invoke<WslInventory>("list_wsl_distributions");
}

export async function getDeploymentInfo(distribution: string): Promise<DeploymentInfo> {
  if (!isTauri()) throw new Error("Deployment checks require the desktop application.");
  return invoke<DeploymentInfo>("get_deployment_info", { distribution: distribution.trim() });
}

export async function controlWorker(action: WorkerAction, distribution = savedDistribution(), onProgress?: (event: BuildProgressEvent) => void): Promise<WorkerActionResult> {
  if (!isTauri()) throw new Error("Worker controls require the desktop application.");
  if (!distribution.trim()) throw new Error("Select an installed WSL distribution first.");
  return invoke<WorkerActionResult>("worker_control", { action, distribution: distribution.trim(), ...(onProgress ? { onProgress: new Channel<BuildProgressEvent>(onProgress) } : {}) });
}

export async function diagnoseEnvironment(distribution = savedDistribution()): Promise<DiagnosticItem[]> {
  if (isTauri()) return invoke<DiagnosticItem[]>("diagnose_environment", { distribution: distribution.trim() || null });
  const health = await workerRequest<{ version: string; runner: string }>("/health");
  return [{ id: "worker", label: "CTXBench worker", status: "healthy", detail: `${health.version} · ${health.runner}` }];
}

export async function createExperiment(request: CreateExperimentRequest): Promise<Experiment> {
  if (new URLSearchParams(window.location.search).get("demo") !== "1") return workerRequest<Experiment>("/experiments", "POST", request);
  await pause(500);
  const id = `exp-${crypto.randomUUID().slice(0, 8)}`;
  const runs = planExperimentRuns(id, request);
  const timestamp = new Date().toISOString();
  return {
    id,
    name: request.name,
    benchmark: request.benchmark,
    dataset: request.dataset,
    status: "preparing",
    arms: request.arms,
    repeats: request.repeats,
    tasks: request.taskIds.length,
    completedRuns: 0,
    totalRuns: runs.length,
    createdAt: timestamp,
    updatedAt: timestamp,
    model: request.model,
    profiles: request.profiles,
    agentImage: request.agentImage,
    agentArgs: request.agentArgs ?? [],
    resources: request.resources,
    seed: request.seed,
  };
}

export async function exportSnapshot(snapshot: DashboardSnapshot, format: "json" | "csv" | "html"): Promise<void> {
  let body: string;
  let mediaType: string;
  if (format === "json") {
    const full = snapshot.runtime === "mock" ? snapshot : { ...snapshot, ...await workerRequest<DashboardSnapshot>("/snapshot") };
    body = JSON.stringify(full, null, 2);
    mediaType = "application/json";
  } else if (format === "csv") {
    const header = "run_id,experiment_id,task_id,repeat,pair_id,arm,status,mock,tests_passed,constraint_verdict,cost_usd,pairing_hash,context_artifact_id,failure";
    const rows = snapshot.runs.map((run) =>
      [
        run.id,
        run.experimentId,
        run.taskId,
        run.repeat,
        run.pairId,
        run.arm,
        run.status,
        run.mock ?? false,
        run.testsPassed ?? "",
        run.constraintVerdict ?? "",
        run.costUsd ?? "",
        run.pairingHash ?? "",
        run.contextArtifactId ?? "",
        run.failure ?? "",
      ]
        .map((value) => `"${String(value).replace(/^[=+@\-\t\r]/, "'$&").replaceAll('"', '""')}"`)
        .join(","),
    );
    body = [header, ...rows].join("\n");
    mediaType = "text/csv";
  } else {
    body = renderSnapshotHtml(snapshot);
    mediaType = "text/html";
  }

  await saveText(`ctxbench-export-${new Date().toISOString().slice(0, 10)}.${format}`, body, mediaType);
}

export async function saveText(filename: string, body: string, mediaType = "application/json"): Promise<void> {
  if (isTauri()) { await invoke("save_export", { filename, content: body }); return; }
  const url = URL.createObjectURL(new Blob([body], { type: mediaType }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // WebViews may start the download asynchronously after the click returns.
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

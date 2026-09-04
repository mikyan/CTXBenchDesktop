import { invoke } from "@tauri-apps/api/core";
import { createDemoSnapshot } from "../data/demo";
import { planExperimentRuns } from "../domain/planner";
import { renderSnapshotHtml } from "../domain/report";
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
  if (isTauri()) return invoke<DashboardSnapshot>("bootstrap");
  await pause(240);
  return createDemoSnapshot();
}

export async function diagnoseEnvironment(): Promise<DiagnosticItem[]> {
  if (isTauri()) return invoke<DiagnosticItem[]>("diagnose_environment");
  await pause(850);
  return createDemoSnapshot().diagnostics;
}

export async function createExperiment(request: CreateExperimentRequest): Promise<Experiment> {
  if (isTauri()) return invoke<Experiment>("create_experiment", { request });
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
    resources: request.resources,
    seed: request.seed,
  };
}

export function exportSnapshot(snapshot: DashboardSnapshot, format: "json" | "csv" | "html"): void {
  let body: string;
  let mediaType: string;
  if (format === "json") {
    body = JSON.stringify(snapshot, null, 2);
    mediaType = "application/json";
  } else if (format === "csv") {
    const header = "run_id,experiment_id,task_id,arm,status,tests_passed,constraint_verdict,cost_usd";
    const rows = snapshot.runs.map((run) =>
      [
        run.id,
        run.experimentId,
        run.taskId,
        run.arm,
        run.status,
        run.testsPassed ?? "",
        run.constraintVerdict ?? "",
        run.costUsd ?? "",
      ]
        .map((value) => `"${String(value).replaceAll('"', '""')}"`)
        .join(","),
    );
    body = [header, ...rows].join("\n");
    mediaType = "text/csv";
  } else {
    body = renderSnapshotHtml(snapshot);
    mediaType = "text/html";
  }

  const url = URL.createObjectURL(new Blob([body], { type: mediaType }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `ctxbench-export-${new Date().toISOString().slice(0, 10)}.${format}`;
  anchor.click();
  URL.revokeObjectURL(url);
}

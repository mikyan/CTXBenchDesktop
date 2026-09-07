import { controlWorker } from "./desktop";
import type { BuildProgressEvent, WorkerActionResult } from "./infrastructure";

export interface BuildStep { id: string; label: string; status: "running" | "done" | "failed" | "canceled" }
export interface ImageBuild {
  id: number;
  distribution: string;
  status: "running" | "completed" | "failed";
  phase: "checking" | "building" | "pulling" | "installing" | "exporting";
  startedAt: number;
  endedAt?: number;
  eventAt: number;
  elapsedMs: number;
  lastOutputMs: number | null;
  lines: string[];
  omitted: number;
  steps: Record<string, BuildStep>;
  current?: string;
  transfer?: { step: string; layer: string; downloaded: number; total: number; label: string };
  result?: WorkerActionResult;
}

export function newImageBuild(distribution: string, id = 0, now = Date.now()): ImageBuild {
  return { id, distribution, status: "running", phase: "checking", startedAt: now, eventAt: now, elapsedMs: 0, lastOutputMs: null, lines: [], omitted: 0, steps: {} };
}

function bytes(value: string, unit: string): number {
  const index = ["B", "KB", "MB", "GB", "TB"].indexOf(unit.toUpperCase().replace("I", ""));
  return Number(value) * (unit.toLowerCase().includes("i") ? 1024 : 1000) ** index;
}

// BuildKit vertices run in parallel and are discovered incrementally. This is
// completed/observed work, NEVER an estimate of total duration or a frozen total.
export function receiveBuildProgress(build: ImageBuild, event: BuildProgressEvent, now = Date.now()): ImageBuild {
  if (build.status !== "running") return build;
  const next = { ...build, eventAt: now, elapsedMs: event.elapsedMs, lastOutputMs: event.lastOutputMs };
  if (event.phase === "building" && next.phase === "checking") next.phase = "building";
  if (!event.lines.length) return next;
  next.steps = { ...build.steps };
  for (const line of event.lines) {
    const match = line.match(/^#(\d+)\s+(.+)/);
    if (!match) continue;
    const [, id, text] = match;
    const old = next.steps[id];
    if (!old && Object.keys(next.steps).length >= 4096) continue;
    const terminal = text.match(/^(DONE|CACHED|ERROR|CANCELED)\b/);
    next.steps[id] = { id, label: old?.label ?? `#${id}`, status: old?.status ?? "running" };
    if (terminal) {
      next.steps[id].status = terminal[1] === "ERROR" ? "failed" : terminal[1] === "CANCELED" ? "canceled" : "done";
      if (next.transfer?.step === id) next.transfer = undefined;
    } else if (/^(\[|exporting|importing|resolving)/.test(text)) {
      next.steps[id].label = line;
      next.current = line;
      next.phase = /exporting|naming to|unpacking to/.test(text) ? "exporting"
        : /load metadata|\bFROM\b|pulling/.test(text) ? "pulling"
        : /\bRUN\b.*\b(apt|apt-get|apk|pip\d?|npm|pnpm|yarn|uv|poetry|curl|wget)\b/.test(text) ? "installing" : "building";
    }
    const transfer = text.match(/^(sha256:[a-f\d]+)\s+([\d.]+)([KMGT]?i?B)\s*\/\s*([\d.]+)([KMGT]?i?B)\b/i);
    if (transfer && next.steps[id].status === "running") {
      const downloaded = bytes(transfer[2], transfer[3]);
      const total = bytes(transfer[4], transfer[5]);
      if (Number.isFinite(downloaded) && Number.isFinite(total) && total > 0 && downloaded >= 0 && downloaded <= total) {
        next.transfer = { step: id, layer: transfer[1], downloaded, total, label: transfer[0] };
      }
    }
  }
  next.lines = [...build.lines, ...event.lines];
  let size = next.lines.reduce((sum, line) => sum + line.length, 0);
  let removed = 0;
  while (next.lines.length - removed > 500 || size > 100_000) { size -= next.lines[removed++].length; }
  next.lines = next.lines.slice(removed);
  next.omitted += removed;
  return next;
}

export function buildTiming(build: ImageBuild, now: number) {
  const at = build.endedAt ?? now;
  return { elapsed: Math.max(0, at - build.startedAt), silent: Math.max(0, build.elapsedMs - (build.lastOutputMs ?? 0) + at - build.eventAt) };
}

type Listener = () => void;
type Runner = typeof controlWorker;
export function createImageBuildStore(run: Runner = controlWorker) {
  let snapshot: ImageBuild | undefined;
  let sequence = 0;
  let pending: Promise<WorkerActionResult> | undefined;
  const listeners = new Set<Listener>();
  const publish = (value: ImageBuild) => { snapshot = value; listeners.forEach((listener) => listener()); };
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: Listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    start(distribution: string): Promise<WorkerActionResult> {
      if (pending) return pending;
      const id = ++sequence;
      // Defer the invoke so the promise guard is installed before listeners run.
      pending = Promise.resolve().then(() => run("build", distribution, (event) => {
        if (snapshot?.id === id) publish(receiveBuildProgress(snapshot, event));
      })).catch((): WorkerActionResult => ({ ok: false, code: "action", detail: "Build connection lost. Check Docker status before retrying; background work may still be running." }))
        .then((result) => {
          if (snapshot?.id === id) publish({ ...snapshot, status: result.ok ? "completed" : "failed", endedAt: Date.now(), result });
          return result;
        }).finally(() => { pending = undefined; });
      publish(newImageBuild(distribution, id));
      return pending;
    },
  };
}

// In-memory only: keeps a build visible across page navigation, not app restarts.
export const imageBuildStore = createImageBuildStore();

import { importOfflineImages } from "./desktop";
import { newImageBuild, receiveBuildProgress, type ImageBuild } from "./image-build";
import type { BuildProgressEvent, WorkerActionResult } from "./infrastructure";

export const importPhaseLabels = { checking: "Checking offline import prerequisites", verify: "Verifying package checksums", load: "Transferring images to Docker", unpack: "Docker is unpacking images", register: "Verifying and registering four images", complete: "Confirming import completion" };
export interface OfflineImport extends ImageBuild {
  packagePath: string;
  importPhase: keyof typeof importPhaseLabels;
  completed: number;
  total: number;
}
export function receiveImportProgress(state: OfflineImport, event: BuildProgressEvent): OfflineImport {
  if (state.status !== "running") return state;
  let next = { ...state };
  const lines: string[] = [];
  for (const line of event.lines) {
    if (!line.startsWith("CTXBENCH_IMPORT_PROGRESS ")) { lines.push(line); continue; }
    try {
      const value = JSON.parse(line.slice("CTXBENCH_IMPORT_PROGRESS ".length));
      if (Object.hasOwn(importPhaseLabels, value.phase) && Number.isSafeInteger(value.completed) && Number.isSafeInteger(value.total) && value.completed >= 0 && value.total >= value.completed) {
        next = { ...next, importPhase: value.phase, completed: value.completed, total: value.total };
      }
    } catch { /* Ignore malformed progress controls, never interpret arbitrary output as code. */ }
  }
  return { ...next, ...receiveBuildProgress(next, { ...event, lines }) };
}

export function createOfflineImportStore(run = importOfflineImages) {
  let snapshot: OfflineImport | undefined;
  let sequence = 0;
  let pending: Promise<WorkerActionResult> | undefined;
  const listeners = new Set<() => void>();
  const publish = (value: OfflineImport) => { snapshot = value; listeners.forEach((listener) => listener()); };
  return {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    start(distribution: string, packagePath: string) {
      if (pending) return pending;
      const id = ++sequence;
      pending = Promise.resolve().then(() => run(distribution, packagePath, (event) => {
        if (snapshot?.id === id) publish(receiveImportProgress(snapshot, event));
      })).catch((): WorkerActionResult => ({ ok: false, code: "action", detail: "Offline import connection lost; check Docker before retrying." }))
        .then((result) => {
          if (snapshot?.id === id) publish({ ...snapshot, status: result.ok ? "completed" : "failed", endedAt: Date.now(), result });
          return result;
        }).finally(() => { pending = undefined; });
      publish({ ...newImageBuild(distribution, id), packagePath, importPhase: "checking", completed: 0, total: 0 });
      return pending;
    },
  };
}
export const offlineImportStore = createOfflineImportStore();

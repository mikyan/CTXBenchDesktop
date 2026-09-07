import { exportOfflineImages } from "./desktop";
import { newImageBuild, receiveBuildProgress, type ImageBuild } from "./image-build";
import type { BuildProgressEvent, ExportImageSelection, WorkerActionResult } from "./infrastructure";

export const defaultExportImages = [
  { role: "ctxbench-worker", label: "Worker image", reference: "ctxbench/worker:0.1.0" },
  { role: "ctxbench-egress-proxy", label: "Egress proxy image", reference: "ctxbench/egress-proxy:0.1.0" },
  { role: "agent-pi-image", label: "Pi Agent image", reference: "ctxbench/agent-pi:0.1.0" },
  { role: "official-harness-image", label: "Official harness image", reference: "ctxbench/official-harness:0.1.0" },
];
export const exportPhaseLabels = { checking: "Checking image export prerequisites", inspect: "Inspecting and pinning selected images", save: "Exporting and compressing images", package: "Writing the single ZIP", verify: "Verifying the exported package", complete: "Confirming export completion" };
export interface OfflineExport extends ImageBuild {
  packagePath: string;
  images: ExportImageSelection[];
  exportPhase: keyof typeof exportPhaseLabels;
  completed: number;
  total: number;
}
export function validExportImages(images: ExportImageSelection[]) {
  return images.length === 4 && defaultExportImages.every(({ role }) => images.filter((image) => image.role === role).length === 1)
    && images.every(({ reference }) => /^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}$/.test(reference));
}
export function receiveExportProgress(state: OfflineExport, event: BuildProgressEvent): OfflineExport {
  if (state.status !== "running") return state;
  let next = { ...state };
  const lines: string[] = [];
  for (const line of event.lines) {
    if (!line.startsWith("CTXBENCH_EXPORT_PROGRESS ")) { lines.push(line); continue; }
    try {
      const value = JSON.parse(line.slice("CTXBENCH_EXPORT_PROGRESS ".length));
      if (Object.hasOwn(exportPhaseLabels, value.phase) && Number.isSafeInteger(value.completed) && Number.isSafeInteger(value.total) && value.completed >= 0
        && (value.total >= value.completed || (value.phase === "save" && value.total === 0))) {
        next = { ...next, exportPhase: value.phase, completed: value.completed, total: value.total };
      }
    } catch { /* Progress controls are data, never code. */ }
  }
  return { ...next, ...receiveBuildProgress(next, { ...event, lines }) };
}

export function createOfflineExportStore(run = exportOfflineImages) {
  let snapshot: OfflineExport | undefined;
  let sequence = 0;
  let pending: Promise<WorkerActionResult> | undefined;
  const listeners = new Set<() => void>();
  const publish = (value: OfflineExport) => { snapshot = value; listeners.forEach((listener) => listener()); };
  return {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    start(distribution: string, packagePath: string, images: ExportImageSelection[]) {
      if (pending) return pending;
      const id = ++sequence;
      const frozenImages = images.map(({ role, reference }) => ({ role, reference }));
      pending = Promise.resolve().then(() => run(distribution, packagePath, frozenImages, (event) => {
        if (snapshot?.id === id) publish(receiveExportProgress(snapshot, event));
      })).catch((): WorkerActionResult => ({ ok: false, code: "action", detail: "Image export connection lost. Check the output before retrying." }))
        .then((result) => {
          if (snapshot?.id === id) publish({ ...snapshot, status: result.ok ? "completed" : "failed", endedAt: Date.now(), result });
          return result;
        }).finally(() => { pending = undefined; });
      publish({ ...newImageBuild(distribution, id), packagePath, images: frozenImages, exportPhase: "checking", completed: 0, total: 0 });
      return pending;
    },
  };
}
export const offlineExportStore = createOfflineExportStore();

import { invoke } from "@tauri-apps/api/core";
import standardDatasets from "../data/standard-datasets.json";
import type { BenchmarkKind } from "../domain/types";

export const maxDatasetBytes = 32 * 1024 * 1024;
export interface DatasetFilePreview {
  token: string; filename: string; name: string; benchmark: BenchmarkKind; count: number; bytes: number; sha256: string;
  samples: { id: string; repository: string; baseCommit: string }[]; testsExecuted: false;
}
export function datasetFileError(file: Pick<File, "name" | "size">): string | undefined {
  if (!file.size || file.size > maxDatasetBytes) return "Choose a nonempty dataset file no larger than 32 MiB.";
  if (!/\.(parquet|json|jsonl)$/i.test(file.name)) return "Select a Parquet, JSON or JSONL dataset file; ZIP and EXE files are not datasets.";
}
export function officialSnapshot(hash: string) { return standardDatasets.find((item) => item.sha256 === hash); }
export async function previewDatasetFile(file: File, name: string, benchmark: BenchmarkKind): Promise<DatasetFilePreview> {
  const error = datasetFileError(file); if (error) throw new Error(error);
  const bytes = new Uint8Array(await file.arrayBuffer());
  if ("__TAURI_INTERNALS__" in window) return invoke("preview_dataset_file", { filename: file.name, bytes: Array.from(bytes), name, benchmark });
  const query = new URLSearchParams({ filename: file.name, name, benchmark });
  const response = await fetch(`/worker/datasets/files/preview?${query}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: bytes });
  if ([404, 405].includes(response.status)) throw new Error("Local file import requires the matching new evaluation service image. Update it in Settings; no manual file copy is needed.");
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Dataset file check failed. Check the file and local evaluation service.");
  return payload;
}

import type { BenchmarkKind, DatasetRecord } from "../domain/types";
import type { Translate } from "../i18n";

export const CTXBENCH_LABEL = "CTXBench (formerly AGENTBench)";

export function benchmarkLabel(kind: BenchmarkKind, t: Translate): string {
  return t({ ctxbench: CTXBENCH_LABEL, swebench: "SWE-bench", custom: "Custom" }[kind]);
}

export function datasetLabel(dataset: Pick<DatasetRecord, "name" | "benchmark" | "count">, t: Translate): string {
  // Presentation only: keep frozen IDs, original records and custom names intact.
  if (dataset.benchmark === "ctxbench" && (
    dataset.name === CTXBENCH_LABEL ||
    dataset.name === `AGENTBench official ${dataset.count}`
  )) return benchmarkLabel("ctxbench", t);
  return dataset.name;
}

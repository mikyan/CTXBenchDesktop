import { useEffect, useId, useState } from "react";
import standardDatasets from "../data/standard-datasets.json";
import type { BenchmarkKind, RuntimeSettings } from "../domain/types";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import { ExternalLink } from "./ExternalLink";

export function StandardDatasetDownloads({ benchmark, onSelect, disabled = false }: { benchmark: BenchmarkKind; onSelect: (value: "ctxbench" | "swebench") => void; disabled?: boolean }) {
  const { t } = useI18n();
  const heading = useId();
  const [directory, setDirectory] = useState<string>();
  useEffect(() => {
    let alive = true;
    void workerRequest<RuntimeSettings>("/runtime").then((runtime) => {
      if (alive && runtime.dataDirectory.startsWith("/")) setDirectory(`${runtime.dataDirectory.replace(/\/+$/, "")}/datasets`);
    }).catch(() => {});
    return () => { alive = false; };
  }, []);
  return <section className="standard-datasets" aria-labelledby={heading}>
    <h3 id={heading}>{t("Download standard datasets")}</h3>
    <p>{t("Download on a connected computer, then copy the file to your internal environment. These links point to pinned official snapshots, not demo tasks or our Docker image ZIP.")}</p>
    <div className="standard-dataset-cards">{standardDatasets.map((dataset) => {
      const kind = dataset.id as "ctxbench" | "swebench";
      return <article key={kind} className={benchmark === kind ? "selected" : ""}>
        <h4>{t(dataset.name)}</h4><p>{t("{count} tasks · split: {split} · {size}", { count: dataset.tasks, split: dataset.split, size: dataset.size })}</p>
        <div className="toolbar">
          <ExternalLink destination={kind === "ctxbench" ? "ctxbenchDataset" : "swebenchDataset"}>{t("Official dataset page")}</ExternalLink>
          <ExternalLink destination={kind === "ctxbench" ? "ctxbenchDownload" : "swebenchDownload"}>{t("Download pinned Parquet")}</ExternalLink>
        </div>
        <p>{t("Downloaded filename")}: <code>{dataset.filename}</code></p>
        <button type="button" className="button secondary" disabled={disabled} aria-pressed={benchmark === kind} onClick={() => onSelect(kind)}>{t("Use this dataset source")}</button>
        <details><summary>{t("Snapshot and checksum")}</summary><p>{t("Source")}: {dataset.repository}</p><p>{t("Checked on {date}; task counts refer to this snapshot only.", { date: dataset.checkedAt })}</p><p>Revision: <code>{dataset.revision}</code></p><p>SHA-256: <code>{dataset.sha256}</code></p></details>
      </article>;
    })}</div>
    <details className="standard-dataset-import"><summary>{t("How to import the downloaded file offline")}</summary>
      <ol>
        <li>{t("Keep the downloaded Parquet intact. Copy it into the running Worker's datasets directory; a Windows Downloads path is not visible inside the Worker.")}</li>
        <li>{t("Select the matching benchmark source above. In File in worker datasets directory, enter the downloaded filename, or rename it to the suggested name before copying.")}</li>
        <li>{t("Click Import dataset. Parquet import needs the local official-harness image. JSON / JSONL can instead be uploaded directly below; renaming Parquet to JSON does not convert it.")}</li>
      </ol>
      <p>{t("Worker datasets directory")}: <code>{directory ?? t("Unavailable until the Worker is connected")}</code></p>
      <p>{t("Standard deployment: copy into the selected WSL data mount's datasets folder (default /var/lib/ctxbench/datasets). For a custom mount, use its actual host path; the container path above may differ.")}</p>
      <p>{t("Suggested filenames: agentbench.parquet for CTXBench; swebench-verified.parquet for SWE-bench Verified.")}</p>
    </details>
    <p className="standard-dataset-warning">{t("Dataset files include evaluator-only reference patches and test material. Never provide the full dataset to the coding agent or knowledge builder. Baseline repositories, task images and prepared grading images still need separate preparation.")}</p>
    <p>{t("Our Release does not currently mirror these datasets. Public download availability is not a blanket redistribution license; follow upstream and repository-specific terms.")}</p>
  </section>;
}

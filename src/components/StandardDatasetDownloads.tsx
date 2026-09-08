import { useId } from "react";
import standardDatasets from "../data/standard-datasets.json";
import type { BenchmarkKind } from "../domain/types";
import { useI18n } from "../i18n";
import { ExternalLink } from "./ExternalLink";

export function StandardDatasetDownloads({ benchmark, onSelect, disabled = false }: { benchmark: BenchmarkKind; onSelect: (value: "ctxbench" | "swebench") => void; disabled?: boolean }) {
  const { t } = useI18n();
  const heading = useId();
  return <section className="standard-datasets" aria-labelledby={heading}>
    <h3 id={heading}>{t("Download standard datasets")}</h3>
    <p>{t("Download the dataset to any folder on your computer. For an internal network, transfer it to that computer's Downloads folder or another ordinary folder, then select it in the app.")}</p>
    <div className="standard-dataset-cards">{standardDatasets.map((dataset) => {
      const kind = dataset.id as "ctxbench" | "swebench";
      return <article key={kind} className={benchmark === kind ? "selected" : ""}>
        <h4>{t(dataset.name)}</h4><p>{t("{count} tasks · split: {split} · {size}", { count: dataset.tasks, split: dataset.split, size: dataset.size })}</p>
        <div className="toolbar">
          <ExternalLink destination={kind === "ctxbench" ? "ctxbenchDataset" : "swebenchDataset"}>{t("Official dataset page")}</ExternalLink>
          <ExternalLink destination={kind === "ctxbench" ? "ctxbenchDownload" : "swebenchDownload"}>{t("Download pinned Parquet")}</ExternalLink>
        </div>
        <p>{t("Downloaded filename")}: <code>{dataset.filename}</code></p>
        <p>{t(kind === "ctxbench" ? "Project images: upstream supplies Docker Hub image references in each task's docker_image field. Baseline-specific setup is still required after download." : "Project images: SWE-bench supplies per-task Docker Hub images, not one universal image. The app lists the exact images for the tasks you select.")}</p>
        <ExternalLink destination={kind === "ctxbench" ? "ctxbenchImages" : "swebenchImages"}>{t("Upstream image instructions")}</ExternalLink>
        <button type="button" className="button secondary" disabled={disabled} aria-pressed={benchmark === kind} onClick={() => onSelect(kind)}>{t("Use this dataset source")}</button>
        <details><summary>{t("Snapshot and checksum")}</summary><p>{t("Source")}: {dataset.repository}</p><p>{t("Checked on {date}; task counts refer to this snapshot only.", { date: dataset.checkedAt })}</p><p>Revision: <code>{dataset.revision}</code></p><p>SHA-256: <code>{dataset.sha256}</code></p></details>
      </article>;
    })}</div>
    <div className="standard-dataset-import"><h4>{t("How to import the downloaded file offline")}</h4>
      <ol>
        <li>{t("Download the Parquet file above and keep its original extension. No extraction or renaming is needed.")}</li>
        <li>{t("Open Import dataset, choose the matching source, then select the downloaded file from your computer.")}</li>
        <li>{t("Click Check selected file. When the task count appears, click Confirm dataset import. The app handles file transfer; no Docker or WSL copy is needed.")}</li>
        <li>{t("In Registered datasets, click Install project images on the imported dataset card. Select a few tasks, review missing images and confirm installation. No image names need to be typed.")}</li>
      </ol>
      <p>{t("The local evaluation service must be running. For Parquet, install the matching application images in Settings first. No Provider key is needed to import a dataset.")}</p>
    </div>
    <details><summary>{t("What this download includes (not an error)")}</summary><p>{t("Reference fixes and test material are normal contents of an official dataset, not an import error. They are kept on the grading side and are not given to the coding Agent or knowledge builder.")}</p><p>{t("Next, select this dataset when creating an experiment. Repositories, dependencies and test environments are prepared separately; importing this file does not run an Agent or call a model.")}</p></details>
    <p>{t("Our Release does not currently mirror these datasets. Public download availability is not a blanket redistribution license; follow upstream and repository-specific terms.")}</p>
  </section>;
}

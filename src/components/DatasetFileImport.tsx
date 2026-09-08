import { useEffect, useRef, useState } from "react";
import type { BenchmarkKind, DatasetRecord } from "../domain/types";
import { useI18n } from "../i18n";
import { benchmarkLabel } from "../lib/benchmark-labels";
import { datasetFileError, officialSnapshot, previewDatasetFile, type DatasetFilePreview } from "../lib/dataset-import";
import { workerRequest } from "../lib/desktop";
import { StandardDatasetDownloads } from "./StandardDatasetDownloads";

export function DatasetFileImport({ initialBenchmark, onComplete, onBusy, onClose, onSettings }: {
  initialBenchmark: BenchmarkKind; onComplete: () => void; onBusy: (busy: boolean) => void; onClose: () => void;
  onSettings?: (section: "runtime" | "images") => void;
}) {
  const { t } = useI18n();
  const [benchmark, setBenchmark] = useState(initialBenchmark);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File>();
  const [preview, setPreview] = useState<DatasetFilePreview>();
  const [record, setRecord] = useState<DatasetRecord>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const errorRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (error) { errorRef.current?.focus(); errorRef.current?.scrollIntoView({ block: "nearest" }); } }, [error]);
  const token = useRef<string | undefined>(undefined);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => {
    alive.current = false;
    if (token.current) void workerRequest(`/datasets/files/${token.current}/discard`, "POST").catch(() => {});
  }; }, []);
  const clearPreview = () => {
    if (token.current) void workerRequest(`/datasets/files/${token.current}/discard`, "POST").catch(() => {});
    token.current = undefined; setPreview(undefined); setError("");
  };
  const check = async () => {
    if (!file || busy) return;
    setBusy(true); onBusy(true); setError("");
    try {
      const result = await previewDatasetFile(file, name.trim() || file.name.replace(/\.(parquet|jsonl?)$/i, ""), benchmark);
      if (!alive.current) { void workerRequest(`/datasets/files/${result.token}/discard`, "POST").catch(() => {}); return; }
      token.current = result.token; setPreview(result);
    } catch (cause) { if (alive.current) setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { if (alive.current) { setBusy(false); onBusy(false); } }
  };
  const confirm = async () => {
    if (!preview || busy) return;
    setBusy(true); onBusy(true); setError("");
    try {
      const result = await workerRequest<DatasetRecord>(`/datasets/files/${preview.token}/confirm`, "POST");
      if (alive.current) { token.current = undefined; setRecord(result); onComplete(); }
      void workerRequest(`/datasets/files/${preview.token}/discard`, "POST").catch(() => {});
    } catch (cause) { if (alive.current) setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { if (alive.current) { setBusy(false); onBusy(false); } }
  };
  if (record) return <div className="dataset-import-result" role="status"><h3>{t("Dataset imported successfully")}</h3><p>{t("{count} tasks are now in your dataset library.", { count: record.count })}</p><p>{t("Next, select this dataset when creating an experiment. Repositories, dependencies and test environments are prepared separately; importing this file does not run an Agent or call a model.")}</p><button className="button primary" onClick={onClose}>{t("Done")}</button></div>;
  const official = preview && officialSnapshot(preview.sha256);
  return <>
    <p className="info-note">{t("Choose the downloaded file on this computer. The app transfers it to the local evaluation service automatically. No Docker copy, WSL path or sudo command is needed.")}</p>
    <details><summary>{t("Need to download an official dataset?")}</summary><StandardDatasetDownloads benchmark={benchmark} onSelect={(value) => { clearPreview(); setBenchmark(value); }} disabled={busy} /></details>
    <ol className="dataset-import-stages" aria-label={t("Dataset import steps")}><li aria-current={!preview ? "step" : undefined}>{t("1. Select a local file")}</li><li aria-current={preview ? "step" : undefined}>{t("2. Check and confirm")}</li><li>{t("3. Ready in the library")}</li></ol>
    <label>{t("Benchmark source")}<select value={benchmark} disabled={busy} onChange={(event) => { clearPreview(); setBenchmark(event.target.value as BenchmarkKind); }}>{(["ctxbench", "swebench", "custom"] as const).map((kind) => <option key={kind} value={kind}>{benchmarkLabel(kind, t)}</option>)}</select></label>
    <label>{t("Select downloaded dataset file")}<input type="file" accept=".parquet,.json,.jsonl" disabled={busy} onChange={(event) => {
      clearPreview(); const selected = event.target.files?.[0]; setFile(selected);
      if (selected) { const failure = datasetFileError(selected); if (failure) setError(failure); }
    }} /></label>
    <p>{t("Parquet, JSON and JSONL are supported, up to 32 MiB. Keep the original filename and extension; do not extract or convert the official Parquet download.")}</p>
    {file && <p>{file.name} · {(file.size / 1024 / 1024).toFixed(2)} MiB</p>}
    <label>{t("Dataset name (optional)")}<input value={name} disabled={busy} placeholder={file?.name ?? benchmarkLabel(benchmark, t)} onChange={(event) => { clearPreview(); setName(event.target.value); }} /></label>
    {busy && <p role="status">{t(preview ? "Saving the checked dataset…" : "Transferring and checking the file locally… Parquet parsing can take a few minutes. No model is being called.")}</p>}
    {preview && <section className="dataset-import-preview" aria-label={t("Dataset check result")}><h3>{t("File checked — ready to import")}</h3><p>{t("{count} valid tasks · no tests executed", { count: preview.count })}</p>
      <p>{t(official ? "File checksum matches the pinned official snapshot." : "This is not one of the pinned official downloads. Its task format is valid, but its source has not been verified.")}</p>
      <details><summary>{t("Check details and sample task IDs")}</summary><p>SHA-256: <code>{preview.sha256}</code></p><ul>{preview.samples.map((task) => <li key={task.id}>{task.id} · {task.repository} · {task.baseCommit.slice(0, 12)}</li>)}</ul></details>
      <button className="button primary" disabled={busy} onClick={() => void confirm()}>{t("Confirm dataset import")}</button>
    </section>}
    {error && <div ref={errorRef} tabIndex={-1} className="form-error" role="alert"><strong>{t("Dataset import needs attention")}</strong><p>{t(error)}</p><p>{t("Your original file was not changed. Correct the issue, then check it again. If the service image is old, update it in Settings → Application images first.")}</p>
      {onSettings && /service|harness/.test(error) && <div className="toolbar"><button className="button secondary" disabled={busy} onClick={() => onSettings("runtime")}>{t("Go to runtime controls")}</button><button className="button secondary" disabled={busy} onClick={() => onSettings("images")}>{t("Prepare application images")}</button></div>}
    </div>}
    {!preview && <button className="button primary" disabled={busy || !file || Boolean(file && datasetFileError(file))} onClick={() => void check()}>{t("Check selected file")}</button>}
    {preview && <button className="button secondary" disabled={busy} onClick={clearPreview}>{t("Choose or check again")}</button>}
    <details><summary>{t("About local storage and evaluation-only data")}</summary><p>{t("The local evaluation service is the background part of this app that stores datasets and runs isolated tests. It is sometimes called Worker in technical logs. You do not need to manage its files manually.")}</p><p>{t("Reference fixes and test material are normal contents of an official dataset, not an import error. They are kept on the grading side and are not given to the coding Agent or knowledge builder.")}</p></details>
  </>;
}

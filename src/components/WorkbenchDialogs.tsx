import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import type { BenchmarkKind, BenchmarkRun, DatasetRecord, FrozenModelConfig, TaskSummary } from "../domain/types";
import { useI18n } from "../i18n";
import { saveText, workerRequest } from "../lib/desktop";

export function defaultProfile(): FrozenModelConfig { return { provider: "mock", model: "deterministic", thinking: "high", maxTokens: 300000 }; }
export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const { t } = useI18n(); const ref = useRef<HTMLDialogElement>(null); const titleId = useId();
  useEffect(() => { const dialog = ref.current!; dialog.showModal(); return () => dialog.close(); }, []);
  return <dialog ref={ref} aria-labelledby={titleId} className="workbench-dialog" onCancel={onClose}><header><h2 id={titleId}>{title}</h2><button className="icon-button" aria-label={t("Close")} onClick={onClose}><X size={18} /></button></header><div className="workbench-form">{children}</div></dialog>;
}
export function ProfileEditor({ title, value, onChange }: { title: string; value: FrozenModelConfig; onChange: (profile: FrozenModelConfig) => void }) {
  const { t } = useI18n();
  return <fieldset><legend>{title}</legend><div className="form-grid two"><label>{t("Provider")}<input value={value.provider} onChange={(e) => onChange({ ...value, provider: e.target.value })} /></label><label>{t("Model")}<input value={value.model} onChange={(e) => onChange({ ...value, model: e.target.value })} /></label><label>{t("Thinking")}<select value={value.thinking} onChange={(e) => onChange({ ...value, thinking: e.target.value as FrozenModelConfig["thinking"] })}>{["off", "minimal", "low", "medium", "high", "xhigh", "max"].map((item) => <option key={item}>{item}</option>)}</select></label><label>{t("Cumulative token budget")}<input type="number" min={1} value={value.maxTokens} onChange={(e) => onChange({ ...value, maxTokens: Number(e.target.value) })} /></label></div></fieldset>;
}
export function DatasetDialog({ onClose, onComplete }: { onClose: () => void; onComplete: () => void }) {
  const { t } = useI18n();
  const [name, setName] = useState(""); const [benchmark, setBenchmark] = useState<BenchmarkKind>("ctxbench");
  const [path, setPath] = useState("agentbench.parquet"); const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const submit = async () => { setBusy(true); setError(""); try {
    const rows = content.trim() ? (content.trim().startsWith("[") ? JSON.parse(content) : content.split(/\r?\n/).filter((line) => line.trim()).map((line) => JSON.parse(line))) : undefined;
    await workerRequest("/datasets", "POST", { name: name || path, benchmark, path, rows }); onComplete(); onClose();
  } catch (error) { setError(String(error)); } finally { setBusy(false); } };
  return <Modal title={t("Import dataset")} onClose={onClose}>
    <label>{t("Name")}<input value={name} onChange={(e) => setName(e.target.value)} /></label>
    <label>{t("Benchmark source")}<select value={benchmark} onChange={(e) => { const value = e.target.value as BenchmarkKind; setBenchmark(value); setPath(value === "ctxbench" ? "agentbench.parquet" : value === "swebench" ? "swebench-verified.parquet" : ""); }}><option value="ctxbench">CTXBench / AGENTBench</option><option value="swebench">SWE-bench</option><option value="custom">{t("Custom")}</option></select></label>
    <label>{t("File in worker datasets directory")}<input value={path} onChange={(e) => setPath(e.target.value)} /></label>
    <label>{t("Or upload JSON / JSONL")}<input type="file" accept=".json,.jsonl" onChange={(e) => { const file = e.target.files?.[0]; if (file) void file.text().then(setContent); }} /></label>
    {content && <p>{content.length.toLocaleString()} {t("bytes loaded")}</p>}
    <p>{t("Source rows are frozen by hash. Gold patches and hidden tests stay evaluator-only.")}</p>
    {error && <p className="form-error" role="alert">{error}</p>}<button className="button primary" disabled={busy} onClick={() => void submit()}>{busy ? t("Importing…") : t("Import dataset")}</button>
  </Modal>;
}
export function PreparationDialog({ kind, onClose, onComplete }: { kind: "context" | "constraints" | "manual"; onClose: () => void; onComplete: () => void }) {
  const { t } = useI18n();
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]); const [dataset, setDataset] = useState("");
  const [tasks, setTasks] = useState<TaskSummary[]>([]); const [taskId, setTaskId] = useState("");
  const [profile, setProfile] = useState(defaultProfile()); const [env, setEnv] = useState("");
  const [files, setFiles] = useState<Record<string, string>>({}); const [packageCommit, setPackageCommit] = useState("");
  const [image, setImage] = useState("ctxbench/agent-pi:0.1.0"); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  useEffect(() => { workerRequest<DatasetRecord[]>("/datasets").then(setDatasets).catch((error) => setError(String(error))); }, []);
  useEffect(() => { let active = true; setTasks([]); setTaskId(""); if (dataset) workerRequest<TaskSummary[]>(`/datasets/${dataset}/tasks`).then((value) => { if (active) setTasks(value); }).catch((error) => { if (active) setError(String(error)); }); return () => { active = false; }; }, [dataset]);
  const submit = async () => { setBusy(true); setError(""); try {
    const task = tasks.find((task) => task.id === taskId)!;
    if (kind === "manual") await workerRequest("/context/import", "POST", { dataset, taskId, baseCommit: packageCommit, repository: task.repository, files, contextPaths: Object.keys(files) });
    else await workerRequest(`/prepare/${kind}`, "POST", { dataset, taskId, model: profile, envNames: env.split(/[\s,]+/).filter(Boolean), agentImage: image, resources: { cpus: 4, memoryGb: 8, timeoutMinutes: 60, network: "api-only" } });
    onComplete(); onClose();
  } catch (error) { setError(String(error)); } finally { setBusy(false); } };
  return <Modal title={t(kind === "manual" ? "Import package" : kind === "context" ? "Generate context" : "Mine constraints")} onClose={onClose}>
    <label>{t("Dataset or manifest")}<select value={dataset} onChange={(e) => setDataset(e.target.value)}><option value="">{t("Select an imported dataset")}</option>{datasets.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
    <label>{t("Task")}<select value={taskId} onChange={(e) => setTaskId(e.target.value)}><option value="">{t("Select task")}</option>{tasks.map((task) => <option key={task.id}>{task.id}</option>)}</select></label>
    {kind === "manual" && <label>{t("Or select a documentation folder")}<input type="file" multiple {...{ webkitdirectory: "" }} onChange={(event) => {
      const selected = Array.from(event.target.files ?? []).filter((file) => /\.(md|txt|rst)$/i.test(file.name));
      if (selected.reduce((total, file) => total + file.size, 0) > 20 * 1024 * 1024) { setError("Context packages are limited to 20 MiB."); return; }
      void Promise.all(selected.map(async (file) => [file.webkitRelativePath.split("/").slice(1).join("/") || file.name, await file.text()] as const)).then((entries) => setFiles(Object.fromEntries(entries))).catch((error) => setError(String(error)));
    }} /></label>}
    {kind === "manual" ? <><label>{t("Package baseline commit")}<input value={packageCommit} onChange={(e) => setPackageCommit(e.target.value)} /></label><label>{t("Package JSON: relative paths mapped to text")}<input type="file" accept=".json" onChange={(e) => { const file = e.target.files?.[0]; if (file) void file.text().then((text) => { const parsed = JSON.parse(text); setFiles(parsed.files ?? parsed); if (parsed.baseCommit) setPackageCommit(parsed.baseCommit); }).catch((error) => setError(String(error))); }} /></label><pre>{JSON.stringify(Object.keys(files), null, 2)}</pre><p>{t("Use AGENTS.md or documentation folders. The package must match the selected baseline commit.")}</p></> : <><ProfileEditor title={t(kind === "context" ? "Knowledge builder" : "Constraint miner")} value={profile} onChange={setProfile} /><label>{t("Environment variable names")}<input value={env} onChange={(e) => setEnv(e.target.value)} /></label><label>{t("Agent image")}<input value={image} onChange={(e) => setImage(e.target.value)} /></label></>}
    {error && <p className="form-error" role="alert">{error}</p>}<button className="button primary" disabled={busy || !taskId} onClick={() => void submit()}>{busy ? t("Working…") : t("Submit")}</button>
  </Modal>;
}
export function RunDialog({ run, onClose }: { run: BenchmarkRun; onClose: () => void }) {
  const { t } = useI18n(); const [file, setFile] = useState("graded.patch"); const [content, setContent] = useState("");
  const [next, setNext] = useState(0); const [more, setMore] = useState(false); const [error, setError] = useState("");
  const [record, setRecord] = useState<BenchmarkRun>();
  const [recordError, setRecordError] = useState("");
  const readVersion = useRef(0);
  useEffect(() => {
    let active = true;
    void workerRequest<BenchmarkRun>(`/run-record?id=${encodeURIComponent(run.id)}`).then((value) => { if (active) { setRecord(value); setRecordError(""); } }).catch((error) => { if (active) setRecordError(String(error)); });
    return () => { active = false; };
  }, [run.id, run.updatedAt]);
  const full = record?.id === run.id ? { ...record, ...run } : run;
  const read = async (offset = 0) => { const version = ++readVersion.current; try { setError(""); const result = await workerRequest<{ content: string; nextOffset: number; hasMore: boolean }>(`/run-output?runId=${encodeURIComponent(run.solverRunId ?? "")}&file=${encodeURIComponent(file)}&offset=${offset}`); if (version !== readVersion.current) return; setContent((old) => offset ? old + result.content : result.content); setNext(result.nextOffset); setMore(result.hasMore); } catch (error) { if (version === readVersion.current) setError(String(error)); } };
  useEffect(() => { setContent(""); setMore(false); if (run.solverRunId) void read(); return () => { readVersion.current++; }; }, [run.solverRunId, file]);
  return <Modal title={`${run.taskId} · ${run.arm}`} onClose={onClose}>
    {run.mock && <p className="form-error">{t("Mock provider — infrastructure verification only")}</p>}
    <pre>{JSON.stringify({ ...full, judgeRecords: undefined }, null, 2)}</pre>
    {recordError && <p className="form-error" role="alert">{recordError}</p>}
    <select value={file} onChange={(e) => setFile(e.target.value)}>{["graded.patch", "raw_agent.patch", "context_mutation.patch", "trajectory.live.jsonl", "trajectory.jsonl", "result.json", "container.log", "grading/evaluator.log"].map((item) => <option key={item}>{item}</option>)}</select>
    <button className="button secondary" onClick={() => void read()}>{t("Refresh")}</button>
    {error && <p className="form-error">{error}</p>}<pre className="log-view">{content}</pre>{more && <button className="button secondary" onClick={() => void read(next)}>{t("Load more")}</button>}
    <details><summary>{t("Judge evidence")}</summary><pre>{recordError ? t("Evidence unavailable") : !record ? t("Loading…") : JSON.stringify(full.judgeRecords ?? [], null, 2)}</pre></details>
    <button className="button secondary" disabled={record?.id !== run.id || !!recordError} onClick={() => void saveText(`${run.solverRunId ?? "run"}.json`, JSON.stringify(full, null, 2)).catch((error) => setError(String(error)))}>{t("Export run record")}</button>
  </Modal>;
}

export function PackageDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useI18n();
  const [value, setValue] = useState<{ manifest: { identity: { repository: string; commit: string } }; files: Record<string, string> }>();
  const [error, setError] = useState("");
  useEffect(() => { let active = true; void workerRequest<NonNullable<typeof value>>(`/context/${id}`).then((value) => { if (active) setValue(value); }).catch((error) => { if (active) setError(String(error)); }); return () => { active = false; }; }, [id]);
  return <Modal title={t("View package")} onClose={onClose}>
    <code>{id}</code>{error && <p role="alert" className="form-error">{error}</p>}
    {value && <><pre>{JSON.stringify(value.manifest, null, 2)}</pre>{Object.entries(value.files).map(([name, content]) => <details key={name}><summary>{name}</summary><pre className="log-view">{content}</pre></details>)}
    <button className="button secondary" onClick={() => void saveText(`context-${id.slice(0, 12)}.json`, JSON.stringify({ repository: value.manifest.identity.repository, baseCommit: value.manifest.identity.commit, files: value.files, manifest: value.manifest }, null, 2)).catch((error) => setError(String(error)))}>{t("Export package")}</button></>}
  </Modal>;
}

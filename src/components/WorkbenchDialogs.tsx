import { useEffect, useRef, useState } from "react";
import { CIGradingResult } from './CIGradingResult';
import { ContainerLogViewer } from './ContainerLogs';
import { FailureDetails } from './FailureDetails';
import { DataDeleteDialog } from './DataDeleteDialog';
import type { BenchmarkKind, BenchmarkRun, DatasetRecord, FrozenModelConfig, RuntimeSettings, TaskSummary } from "../domain/types";
import { useI18n } from "../i18n";
import { saveText, workerRequest } from "../lib/desktop";
import { EnvironmentNamesField } from "./EnvironmentNamesField";
import { environmentNamesError, parseEnvironmentNames } from "../lib/environment";
import { WorkflowEditor } from "./WorkflowEditor";
import { defaultWorkflow, workflowError } from "../lib/workflow";
import { datasetLabel } from "../lib/benchmark-labels";
import { AgentArgsField } from "./AgentArgsField";
import { agentArgsError } from "../lib/agent-args";
import { DatasetFileImport } from "./DatasetFileImport";
import { titleCase } from "../lib/format";
import { Modal, FormError } from "./Dialogs";
import { ProjectEnvironmentField, requireProjectEnvironment } from "./ProjectEnvironmentField";
import { CompanyProfilePicker } from "./CompanyProfilePicker";
import { libraryError, librarySources, loadLibrary, type LibrarySelection } from '../lib/case-library';
import { LibrarySourcePicker } from './LibrarySourcePicker';
import { ProjectImageSourceNotice } from './ProjectImageSourceNotice';
export { Modal } from "./Dialogs";

export function defaultProfile(): FrozenModelConfig { return { provider: "mock", model: "deterministic", thinking: "high", maxTokens: 5000000 }; }
export function ProfileEditor({ title, value, onChange }: { title: string; value: FrozenModelConfig; onChange: (profile: FrozenModelConfig) => void }) {
  const { t } = useI18n();
  return <fieldset><legend>{title}</legend><div className="form-grid two"><label>{t("Provider")}<input value={value.provider} onChange={(e) => onChange({ ...value, provider: e.target.value })} /></label><label>{t("Model")}<input value={value.model} onChange={(e) => onChange({ ...value, model: e.target.value })} /></label><label>{t("Thinking")}<select value={value.thinking} onChange={(e) => onChange({ ...value, thinking: e.target.value as FrozenModelConfig["thinking"] })}>{["off", "minimal", "low", "medium", "high", "xhigh", "max"].map((item) => <option key={item}>{item}</option>)}</select></label><label>{t("Cumulative token budget")}<input type="number" min={1} value={value.maxTokens} onChange={(e) => onChange({ ...value, maxTokens: Number(e.target.value) })} /></label></div></fieldset>;
}
export function DatasetDialog({ onClose, onComplete, initialBenchmark = "ctxbench", onSettings }: { onClose: () => void; onComplete: () => void; initialBenchmark?: BenchmarkKind; onSettings?: (section: "runtime" | "images") => void }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  return <Modal title={t("Import dataset")} busy={busy} onClose={onClose}><DatasetFileImport initialBenchmark={initialBenchmark} onComplete={onComplete} onClose={onClose} onBusy={setBusy} onSettings={onSettings} /></Modal>;
}
export function PreparationDialog({ kind, onClose, onComplete, initialSource = '' }: { kind: "context" | "constraints" | "manual"; onClose: () => void; onComplete: () => void; initialSource?: string }) {
  const { t } = useI18n();
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]); const [dataset, setDataset] = useState(initialSource);
  const [datasetRevision, setDatasetRevision] = useState(''); const [selectionReload, setSelectionReload] = useState(0);
  const [tasks, setTasks] = useState<TaskSummary[]>([]); const [taskId, setTaskId] = useState("");
  const [profile, setProfile] = useState(defaultProfile()); const [env, setEnv] = useState("");
  const [companyProfileId, setCompanyProfileId] = useState("");
  const [workflow, setWorkflow] = useState(defaultWorkflow);
  const [agentArgs, setAgentArgs] = useState<string[]>([]);
  const [generationPrompt, setGenerationPrompt] = useState<string>();
  const [projectEnvironment, setProjectEnvironment] = useState(true);
  const [network, setNetwork] = useState("api-only");
  useEffect(() => { void workerRequest<RuntimeSettings>("/runtime").then((settings) => {
    setGenerationPrompt(settings.defaultPrompts?.builder);
    if (settings.credentials.some((item) => item.name === 'XIAOMI_TOKEN_PLAN_CN_API_KEY' && item.configured)) {
      setProfile((current) => current.provider === 'mock' ? { ...current, provider: 'xiaomi-token-plan-cn', model: 'mimo-v2.5' } : current);
      setEnv((current) => current || 'XIAOMI_TOKEN_PLAN_CN_API_KEY');
    }
  }).catch(() => {}); }, []);
  const [files, setFiles] = useState<Record<string, string>>({}); const [packageCommit, setPackageCommit] = useState("");
  const [image, setImage] = useState("ctxbench/agent-pi:0.1.0"); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  useEffect(() => { let active = true; void loadLibrary().then((value) => { if (active) setDatasets(librarySources(value)); }).catch((error) => { if (active) setError(libraryError(error)); }); return () => { active = false; }; }, []);
  useEffect(() => { let active = true; setTasks([]); setTaskId(''); setDatasetRevision('');
    if (dataset) void workerRequest<LibrarySelection>(`/library/selections/${dataset}`).then((value) => { if (active) { setTasks(value.tasks); setDatasetRevision(value.revision); if (value.tasks.length === 1) setTaskId(value.tasks[0].id); } }).catch((error) => { if (active) setError(libraryError(error)); });
    return () => { active = false; };
  }, [dataset, selectionReload]);
  const submit = async () => { setBusy(true); setError(""); try {
    const task = tasks.find((task) => task.id === taskId)!;
    const envError = kind === "manual" ? undefined : agentArgsError(agentArgs) ?? environmentNamesError(env) ?? (kind === "context" ? workflowError(workflow) : undefined);
    if (envError) throw new Error(t(envError));
    if (kind === 'context') await requireProjectEnvironment(projectEnvironment, t);
    if (kind === "manual") await workerRequest("/context/import", "POST", { dataset, datasetRevision, taskId, baseCommit: packageCommit, repository: task.repository, files, contextPaths: Object.keys(files) });
    else await workerRequest(`/prepare/${kind}`, "POST", { dataset, datasetRevision, taskId, model: profile, envNames: parseEnvironmentNames(env), agentImage: image, agentArgs, companyProfileId, resources: { cpus: 4, memoryGb: 8, timeoutMinutes: 60, network }, ...(kind === "context" ? { workflow, projectEnvironment } : {}) });
    onComplete(); onClose();
  } catch (error) { setError(libraryError(error)); } finally { setBusy(false); } };
  return <Modal title={t(kind === "manual" ? "Import package" : kind === "context" ? "Generate context" : "Mine constraints")} busy={busy} warnOnClose onClose={onClose}>
    <LibrarySourcePicker value={dataset} onChange={setDataset} sources={datasets} onReload={() => { setError(''); setSelectionReload((value) => value + 1); }} />
    {kind === 'context' && <ProjectImageSourceNotice key={selectionReload} dataset={dataset} profileId={companyProfileId} />}
    <label>{t("Task")}<select value={taskId} onChange={(e) => setTaskId(e.target.value)}><option value="">{t("Select task")}</option>{tasks.map((task) => <option key={task.id}>{task.id}</option>)}</select></label>
    {kind !== 'manual' && <CompanyProfilePicker value={companyProfileId} onChange={(record) => { setCompanyProfileId(record?.id ?? ''); if (record) { const p = record.document; setProfile({ ...profile, provider: p.provider, model: p.model }); setEnv(p.envNames.join('\n')); setImage(p.agentImage); setAgentArgs(p.agentArgs); } }} />}
    {kind === "manual" && <label>{t("Or select a documentation folder")}<input type="file" multiple {...{ webkitdirectory: "" }} onChange={(event) => {
      const selected = Array.from(event.target.files ?? []).filter((file) => /\.(md|txt|rst)$/i.test(file.name));
      if (selected.reduce((total, file) => total + file.size, 0) > 20 * 1024 * 1024) { setError("Context packages are limited to 20 MiB."); return; }
      void Promise.all(selected.map(async (file) => [file.webkitRelativePath.split("/").slice(1).join("/") || file.name, await file.text()] as const)).then((entries) => setFiles(Object.fromEntries(entries))).catch((error) => setError(libraryError(error)));
    }} /></label>}
    {kind === "manual" ? <><label>{t("Package baseline commit")}<input value={packageCommit} onChange={(e) => setPackageCommit(e.target.value)} /></label><label>{t("Package JSON: relative paths mapped to text")}<input type="file" accept=".json" onChange={(e) => { const file = e.target.files?.[0]; if (file) void file.text().then((text) => { const parsed = JSON.parse(text); setFiles(parsed.files ?? parsed); if (parsed.baseCommit) setPackageCommit(parsed.baseCommit); }).catch((error) => setError(libraryError(error))); }} /></label><pre>{JSON.stringify(Object.keys(files), null, 2)}</pre><p>{t("Use AGENTS.md or documentation folders. The package must match the selected baseline commit.")}</p></> : <><ProfileEditor title={t(kind === "context" ? "Knowledge builder" : "Constraint miner")} value={profile} onChange={setProfile} /><EnvironmentNamesField value={env} onChange={setEnv} /></>}
    {kind !== "manual" && <details className="advanced-form"><summary>{t("Runtime and budgets")}</summary><label>{t("Agent image")}<input value={image} onChange={(e) => setImage(e.target.value)} /></label><AgentArgsField value={agentArgs} onChange={setAgentArgs} /></details>}
    {kind === 'context' && <ProjectEnvironmentField value={projectEnvironment} onChange={setProjectEnvironment} />}
    {kind === "context" && <details className="advanced-form"><summary>{t("Advanced workflows")}</summary><p>{t("Defaults use one Agent step. Expand only to add startup commands or separate prompts.")}</p><WorkflowEditor title={t("Knowledge generation workflow")} value={workflow} onChange={setWorkflow} defaultPrompt={generationPrompt} />
      <label>{t("Network")}<select value={network} onChange={(event) => setNetwork(event.target.value)}>{["api-only", "offline", "unrestricted"].map((item) => <option key={item}>{item}</option>)}</select></label></details>}
    {error && <FormError>{t(error)}</FormError>}<button className="button primary" disabled={busy || !taskId} onClick={() => void submit()}>{busy ? t("Working…") : t("Submit")}</button>
  </Modal>;
}
export function RunDialog({ run, onClose, onDeleted }: { run: BenchmarkRun; onClose: () => void; onDeleted?: () => void }) {
  const [deleting, setDeleting] = useState(false);
  const { t } = useI18n(); const [file, setFile] = useState(""); const [content, setContent] = useState("");
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
  const read = async (offset = 0) => { const version = ++readVersion.current; try { setError(""); const result = await workerRequest<{ content: string; nextOffset: number; hasMore: boolean }>(`/run-output?runId=${encodeURIComponent(run.solverRunId ?? "")}&file=${encodeURIComponent(file)}&offset=${offset}`); if (version !== readVersion.current) return; setContent((old) => offset ? old + result.content : result.content); setNext(result.nextOffset); setMore(result.hasMore); } catch (error) { if (version === readVersion.current) setError(libraryError(error)); } };
  useEffect(() => { setContent(""); setMore(false); setError(''); if (run.solverRunId && file) void read(); return () => { readVersion.current++; }; }, [run.solverRunId, file]);
  return <Modal title={`${run.taskId} · ${run.arm}`} onClose={onClose}>
    {run.mock && <p className="form-error">{t("Mock provider — infrastructure verification only")}</p>}
    <dl className="review-grid"><div><dt>{t("Status")}</dt><dd>{t(titleCase(run.status))}</dd></div><div><dt>{t("Tests")}</dt><dd>{typeof run.testsPassed === "boolean" ? t(run.testsPassed ? "PASS" : "FAIL") : t("Not graded")}</dd></div><div><dt>{t("Arm")}</dt><dd>{t(titleCase(run.arm))} · {run.repeat}</dd></div><div><dt>{t("Constraint")}</dt><dd>{run.constraintVerdict ? t(titleCase(run.constraintVerdict)) : t("Not judged")}</dd></div></dl>
    {full.failure && <FailureDetails message={t(full.failure.replace(/^CIError: /, ''))} diagnostic={full.diagnostic} />}
    <CIGradingResult run={full} />
    <details><summary>{t("Frozen metadata and hashes")}</summary><pre>{JSON.stringify({ ...full, judgeRecords: undefined }, null, 2)}</pre></details>
    {recordError && <FormError>{recordError}</FormError>}
    <ContainerLogViewer scope={{ benchmarkRunId: run.id }} />
    <label>{t("Evidence file")}<select value={file} onChange={(e) => setFile(e.target.value)}><option value="">{t('Select saved evidence (optional)')}</option>{["graded.patch", "raw_agent.patch", "context_mutation.patch", "workflow.json", "setup.log", "trajectory.live.jsonl", "trajectory.jsonl", "result.json", "container.log", "grading/evaluator.log"].map((item) => <option key={item}>{item}</option>)}</select></label>
    {file && <button className="button secondary" disabled={!run.solverRunId} onClick={() => void read()}>{t("Refresh")}</button>}
    {error && <FormError>{t(error)}</FormError>}{file && <pre className="log-view run-evidence-output" role="region" aria-label={t('Saved evidence contents')} tabIndex={0}>{content}</pre>}{more && <button className="button secondary" onClick={() => void read(next)}>{t("Load more")}</button>}
    <details><summary>{t("Judge evidence")}</summary><pre>{recordError ? t("Evidence unavailable") : !record ? t("Loading…") : JSON.stringify(full.judgeRecords ?? [], null, 2)}</pre></details>
    <button className="button secondary" disabled={record?.id !== run.id || !!recordError} onClick={() => void saveText(`${run.solverRunId ?? "run"}.json`, JSON.stringify(full, null, 2)).catch((error) => setError(libraryError(error)))}>{t("Export run record")}</button>
    <button type="button" className="button tertiary danger-text" onClick={() => setDeleting(true)}>{t('Delete comparison group')}</button>
    {deleting && <DataDeleteDialog target={{ kind: 'result', id: run.id }} onClose={() => setDeleting(false)} onDeleted={() => { onDeleted?.(); onClose(); }} />}
  </Modal>;
}

export function PackageDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useI18n();
  const [value, setValue] = useState<{ manifest: { identity: { repository: string; commit: string } }; files: Record<string, string> }>();
  const [error, setError] = useState("");
  useEffect(() => { let active = true; void workerRequest<NonNullable<typeof value>>(`/context/${id}`).then((value) => { if (active) setValue(value); }).catch((error) => { if (active) setError(libraryError(error)); }); return () => { active = false; }; }, [id]);
  return <Modal title={t("View package")} onClose={onClose}>
    <code>{id}</code>{error && <FormError>{t(error)}</FormError>}
    {value && <><pre>{JSON.stringify(value.manifest, null, 2)}</pre>{Object.entries(value.files).map(([name, content]) => <details key={name}><summary>{name}</summary><pre className="log-view">{content}</pre></details>)}
    <button className="button secondary" onClick={() => void saveText(`context-${id.slice(0, 12)}.json`, JSON.stringify({ repository: value.manifest.identity.repository, baseCommit: value.manifest.identity.commit, files: value.files, manifest: value.manifest }, null, 2)).catch((error) => setError(libraryError(error)))}>{t("Export package")}</button></>}
  </Modal>;
}

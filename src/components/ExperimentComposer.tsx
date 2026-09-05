import { useEffect, useState } from "react";
import type { ContextArm, CreateExperimentRequest, DatasetRecord, FrozenModelConfig, KnowledgeArtifact, RuntimeSettings, TaskSummary } from "../domain/types";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import { Modal, ProfileEditor, defaultProfile } from "./WorkbenchDialogs";

export function ExperimentComposer({ creating, onClose, onCreate, artifacts }: {
  creating: boolean; onClose: () => void; onCreate: (request: CreateExperimentRequest) => Promise<void>; artifacts: KnowledgeArtifact[];
}) {
  const { t } = useI18n();
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]); const [dataset, setDataset] = useState("");
  const [tasks, setTasks] = useState<TaskSummary[]>([]); const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState(""); const [name, setName] = useState("");
  const [arm, setArm] = useState<Exclude<ContextArm, "none">>("skill-generated");
  const [repeats, setRepeats] = useState(1); const [seed, setSeed] = useState(42);
  const [profiles, setProfiles] = useState({ builder: defaultProfile(), solver: defaultProfile(), constraintMiner: defaultProfile(), constraintJudge: defaultProfile() });
  const [judges, setJudges] = useState<FrozenModelConfig[]>([]);
  const [image, setImage] = useState("ctxbench/agent-pi:0.1.0"); const [env, setEnv] = useState("");
  const [cpu, setCpu] = useState(4); const [memory, setMemory] = useState(8); const [timeout, setTimeoutMinutes] = useState(45);
  const [network, setNetwork] = useState<CreateExperimentRequest["resources"]["network"]>("api-only");
  const [prepareOnly, setPrepareOnly] = useState(false); const [constraints, setConstraints] = useState(false);
  const [packages, setPackages] = useState<Record<string, string>>({}); const [error, setError] = useState("");
  const [constraintPackages, setConstraintPackages] = useState<Record<string, string>>({});
  const [availableConstraints, setAvailableConstraints] = useState<{ id: string; repository: string; commit: string; count: number; historyVersion?: number }[]>([]);
  useEffect(() => {
    workerRequest<DatasetRecord[]>("/datasets").then(setDatasets).catch((error) => setError(String(error)));
    workerRequest<typeof availableConstraints>("/constraint-packages").then(setAvailableConstraints).catch(() => {});
    workerRequest<RuntimeSettings>("/runtime").then((settings) => {
      const mimo = settings.credentials.find((item) => item.name === "XIAOMI_TOKEN_PLAN_CN_API_KEY" && item.configured);
      if (mimo) { setEnv(mimo.name); const profile = { ...defaultProfile(), provider: "xiaomi-token-plan-cn", model: "mimo-v2.5-pro" }; setProfiles({ solver: profile, builder: { ...profile, maxTokens: 800000 }, constraintMiner: profile, constraintJudge: profile }); }
    }).catch(() => {});
  }, []);
  useEffect(() => { let current = true; setTasks([]); setSelected([]); setPackages({}); if (dataset) workerRequest<TaskSummary[]>(`/datasets/${dataset}/tasks`).then((tasks) => { if (current) setTasks(tasks); }).catch((error) => setError(String(error))); return () => { current = false; }; }, [dataset]);
  const visible = tasks.filter((task) => `${task.id} ${task.repository}`.toLowerCase().includes(query.toLowerCase()));
  const submit = async () => {
    if (!dataset || !selected.length || !name.trim()) { setError(t("Choose a dataset, tasks, and experiment name.")); return; }
    setError("");
    const selectedPackages = (values: Record<string, string>) => Object.fromEntries(selected.filter((id) => values[id]).map((id) => [id, values[id]]));
    try { await onCreate({ name, benchmark: datasets.find((item) => item.id === dataset)!.benchmark, dataset, taskIds: selected, arms: ["none", arm], repeats, seed, profiles, model: profiles.solver,
      agentImage: image, resources: { cpus: cpu, memoryGb: memory, timeoutMinutes: timeout, network }, envNames: env.split(/[\s,]+/).filter(Boolean), prepareOnly, evaluateConstraints: constraints, contextArtifacts: selectedPackages(packages), constraintPackages: selectedPackages(constraintPackages), judgeProfiles: judges }); } catch (error) { setError(String(error)); }
  };
  return <Modal title={t("New experiment")} onClose={onClose}>
    <label>{t("Experiment name")}<input value={name} onChange={(e) => setName(e.target.value)} /></label>
    <label>{t("Dataset or manifest")}<select value={dataset} onChange={(e) => setDataset(e.target.value)}><option value="">{t("Select an imported dataset")}</option>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.count}</option>)}</select></label>
    {!datasets.length && <p>{t("Import a dataset from the experiments page first.")}</p>}
    <label>{t("Filter tasks")}<input value={query} onChange={(e) => setQuery(e.target.value)} /></label>
    <div className="task-picker"><button className="text-button" onClick={() => setSelected(visible.map((task) => task.id))}>{t("Select filtered tasks")}</button><button className="text-button" onClick={() => setSelected([])}>{t("Clear")}</button>
      {visible.map((task) => <label className="check-line" key={task.id}><input type="checkbox" checked={selected.includes(task.id)} onChange={(e) => setSelected((current) => e.target.checked ? [...current, task.id] : current.filter((id) => id !== task.id))} /><span>{task.id}<small>{task.repository} · {task.baseCommit.slice(0, 12)}</small></span></label>)}
    </div>
    <label>{t("Context comparison")}<select value={arm} onChange={(e) => setArm(e.target.value as typeof arm)}><option value="skill-generated">{t("Skill generated")}</option><option value="manual">{t("Frozen package (generated or manual)")}</option><option value="developer-historical">{t("Developer historical")}</option></select></label>
    {arm === "manual" && selected.map((id) => { const task = tasks.find((task) => task.id === id)!; return <label key={id}>{id}<select value={packages[id] ?? ""} onChange={(e) => setPackages({ ...packages, [id]: e.target.value })}><option value="">{t("Select matching package")}</option>{artifacts.filter((item) => item.repository === task.repository && item.commit === task.baseCommit && item.status === "ready").map((item) => <option key={item.id} value={item.id}>{item.source} · {item.id.slice(0, 16)} · {item.files} {t("files")}</option>)}</select></label>; })}
    <div className="form-grid two"><label>{t("Repeats")}<input type="number" min={1} max={50} value={repeats} onChange={(e) => setRepeats(Number(e.target.value))} /></label><label>{t("Random seed")}<input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></label></div>
    {(Object.keys(profiles) as (keyof typeof profiles)[]).filter((role) => constraints || !role.startsWith("constraint")).map((role) => <ProfileEditor key={role} title={t(role)} value={profiles[role]} onChange={(value) => setProfiles({ ...profiles, [role]: value })} />)}
    <label className="check-line"><input type="checkbox" checked={constraints} onChange={(e) => setConstraints(e.target.checked)} />{t("Mine historical constraints and run three independent judges")}</label>
    {constraints && selected.map((id) => { const task = tasks.find((task) => task.id === id)!; return <label key={`constraints-${id}`}>{t("Frozen constraints")} · {id}<select value={constraintPackages[id] ?? ""} onChange={(event) => setConstraintPackages({ ...constraintPackages, [id]: event.target.value })}><option value="">{t("Mine or reuse matching miner cache")}</option>{availableConstraints.filter((item) => `https://github.com/${item.repository}.git` === task.repository && item.commit === task.baseCommit).map((item) => <option key={item.id} value={item.id}>{item.id.slice(0, 12)} · {item.count} · history v{item.historyVersion ?? 1}</option>)}</select></label>; })}
    {constraints && <><label className="check-line"><input type="checkbox" checked={judges.length === 3} onChange={(e) => setJudges(e.target.checked ? Array.from({ length: 3 }, () => ({ ...profiles.constraintJudge })) : [])} />{t("Configure each judge separately")}</label>{judges.map((judge, index) => <ProfileEditor key={index} title={`${t("Constraint judge")} ${index + 1}`} value={judge} onChange={(value) => setJudges(judges.map((item, i) => i === index ? value : item))} />)}<p>{t("Automatic mining is silver quality. Empty or inapplicable constraints are reported as neutral.")}</p></>}
    <details><summary>{t("Runtime and budgets")}</summary><label>{t("Agent image")}<input value={image} onChange={(e) => setImage(e.target.value)} /></label><label>{t("Environment variable names")}<input value={env} onChange={(e) => setEnv(e.target.value)} placeholder="OPENAI_API_KEY" /></label>
      <div className="form-grid two"><label>CPU<input type="number" min={1} value={cpu} onChange={(e) => setCpu(Number(e.target.value))} /></label><label>{t("Memory (GiB)")}<input type="number" min={1} value={memory} onChange={(e) => setMemory(Number(e.target.value))} /></label><label>{t("Timeout (minutes)")}<input type="number" min={1} value={timeout} onChange={(e) => setTimeoutMinutes(Number(e.target.value))} /></label><label>{t("Network")}<select value={network} onChange={(e) => setNetwork(e.target.value as typeof network)}>{["api-only", "offline", "unrestricted"].map((item) => <option key={item}>{item}</option>)}</select></label></div></details>
    <label className="check-line"><input type="checkbox" checked={prepareOnly} onChange={(e) => setPrepareOnly(e.target.checked)} />{t("Prepare all context first; start solver runs later")}</label>
    <p>{t("{runs} runs · {keys} context keys", { runs: selected.length * repeats * 2, keys: new Set(tasks.filter((task) => selected.includes(task.id)).map((task) => `${task.repository}@${task.baseCommit}`)).size })}</p>
    {error && <p className="form-error" role="alert">{error}</p>}<button className="button primary" disabled={creating || !selected.length} onClick={() => void submit()}>{creating ? t("Creating plan…") : t("Create & prepare")}</button>
  </Modal>;
}

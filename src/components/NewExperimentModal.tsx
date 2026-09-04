import { Check, ChevronDown, FlaskConical, Info, ShieldCheck, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { BenchmarkKind, ContextArm, CreateExperimentRequest } from "../domain/types";
import { validateExperimentRequest } from "../domain/planner";
import { titleCase } from "../lib/format";

const presets: Record<BenchmarkKind, { dataset: string; tasks: string[] }> = {
  ctxbench: {
    dataset: "eth-sri/agentbench@138",
    tasks: ["astropy__astropy-14369", "django__django-14915", "pytest-dev__pytest-7432", "pallets__flask-4045", "sympy__sympy-20590"],
  },
  swebench: {
    dataset: "princeton-nlp/SWE-bench_Verified",
    tasks: ["django__django-11099", "sympy__sympy-12419", "pytest-dev__pytest-5221", "pallets__flask-5014", "sphinx-doc__sphinx-11445"],
  },
  custom: {
    dataset: "./benchmarks/custom-manifest.jsonl",
    tasks: ["custom/task-001", "custom/task-002", "custom/task-003"],
  },
};

export function NewExperimentModal({
  open,
  creating,
  onClose,
  onCreate,
}: {
  open: boolean;
  creating: boolean;
  onClose: () => void;
  onCreate: (request: CreateExperimentRequest) => Promise<void>;
}) {
  const [benchmark, setBenchmark] = useState<BenchmarkKind>("ctxbench");
  const [name, setName] = useState("AGENTBench · generated context");
  const [dataset, setDataset] = useState(presets.ctxbench.dataset);
  const [contextArm, setContextArm] = useState<Exclude<ContextArm, "none">>("skill-generated");
  const [repeats, setRepeats] = useState(5);
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("gpt-5.4");
  const [builderProvider, setBuilderProvider] = useState("openai");
  const [builderModel, setBuilderModel] = useState("gpt-5.4-mini");
  const [minerProvider, setMinerProvider] = useState("openai");
  const [minerModel, setMinerModel] = useState("gpt-5.4-mini");
  const [judgeProvider, setJudgeProvider] = useState("openai");
  const [judgeModel, setJudgeModel] = useState("gpt-5.4");
  const [thinking, setThinking] = useState<CreateExperimentRequest["model"]["thinking"]>("high");
  const [agentImage, setAgentImage] = useState("ctxbench/agent-pi:0.1.0");
  const [error, setError] = useState<string>();

  const taskIds = useMemo(() => presets[benchmark].tasks, [benchmark]);
  if (!open) return null;

  const updateBenchmark = (value: BenchmarkKind) => {
    setBenchmark(value);
    setDataset(presets[value].dataset);
    setName(value === "ctxbench" ? "AGENTBench · generated context" : value === "swebench" ? "SWE-bench Verified · context study" : "Custom repository · paired context");
  };

  const submit = async () => {
    const request: CreateExperimentRequest = {
      name,
      benchmark,
      dataset,
      arms: ["none", contextArm],
      repeats,
      taskIds,
      model: { provider, model, thinking, maxTokens: 32_768 },
      profiles: {
        builder: { provider: builderProvider, model: builderModel, thinking: "high", maxTokens: 24_576 },
        solver: { provider, model, thinking, maxTokens: 32_768 },
        constraintMiner: { provider: minerProvider, model: minerModel, thinking: "medium", maxTokens: 16_384 },
        constraintJudge: { provider: judgeProvider, model: judgeModel, thinking: "high", maxTokens: 16_384 },
      },
      agentImage,
      resources: { cpus: 4, memoryGb: 8, timeoutMinutes: 45, network: "api-only" },
      seed: Math.floor(Math.random() * 100_000),
    };
    const errors = validateExperimentRequest(request);
    if (errors.length > 0) {
      setError(errors[0]);
      return;
    }
    setError(undefined);
    await onCreate(request);
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="new-experiment-title">
        <header className="modal-header">
          <div className="modal-title-icon"><FlaskConical size={20} /></div>
          <div><span>PAIRED BENCHMARK</span><h2 id="new-experiment-title">New experiment</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </header>

        <div className="modal-body">
          <div className="form-section">
            <div className="form-section-title"><span>1</span><div><strong>Benchmark source</strong><small>Choose a task set and frozen baseline.</small></div></div>
            <div className="segmented benchmark-options">
              {(["ctxbench", "swebench", "custom"] as const).map((value) => (
                <button key={value} className={benchmark === value ? "selected" : ""} onClick={() => updateBenchmark(value)}>
                  {value === "ctxbench" ? "CTXBench" : value === "swebench" ? "SWE-bench" : "Custom"}
                  {benchmark === value && <Check size={14} />}
                </button>
              ))}
            </div>
            <div className="form-grid two">
              <label><span>Experiment name</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>
              <label><span>Dataset or manifest</span><div className="select-wrap"><input value={dataset} onChange={(event) => setDataset(event.target.value)} /><ChevronDown size={14} /></div></label>
            </div>
            <div className="dataset-summary"><Info size={15} /><span><strong>{taskIds.length} preview tasks</strong> selected for this run. Full dataset filtering is available after import.</span></div>
          </div>

          <div className="form-section">
            <div className="form-section-title"><span>2</span><div><strong>Context comparison</strong><small>The no-context baseline is mandatory and frozen.</small></div></div>
            <div className="arm-comparison">
              <div className="arm-choice fixed"><span className="radio checked" /><div><strong>No context</strong><small>Original context files removed</small></div><em>BASELINE</em></div>
              <div className="versus">VS</div>
              <div className="arm-select">
                {(["skill-generated", "manual", "developer-historical"] as const).map((arm) => (
                  <button className={contextArm === arm ? "selected" : ""} onClick={() => setContextArm(arm)} key={arm}>
                    <span className={`radio ${contextArm === arm ? "checked" : ""}`} />
                    <div><strong>{titleCase(arm)}</strong><small>{arm === "skill-generated" ? "Generated once in isolated Pi session" : arm === "manual" ? "Human-authored frozen package" : "Original repository context at base commit"}</small></div>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="form-section">
            <div className="form-section-title"><span>3</span><div><strong>Frozen solver configuration</strong><small>Both arms receive exactly the same model and budget.</small></div></div>
            <div className="profile-editor">
              <div className="profile-head"><span>Role</span><span>Provider</span><span>Model</span><span>Thinking</span></div>
              <ProfileRow role="Knowledge builder" provider={builderProvider} model={builderModel} thinking="high" onProvider={setBuilderProvider} onModel={setBuilderModel} />
              <ProfileRow role="Coding agent" provider={provider} model={model} thinking={thinking} onProvider={setProvider} onModel={setModel} onThinking={setThinking} />
              <ProfileRow role="Constraint miner" provider={minerProvider} model={minerModel} thinking="medium" onProvider={setMinerProvider} onModel={setMinerModel} />
              <ProfileRow role="Constraint judge" provider={judgeProvider} model={judgeModel} thinking="high" onProvider={setJudgeProvider} onModel={setJudgeModel} />
            </div>
            <label className="repeat-field"><span>Agent image</span><input value={agentImage} onChange={(event) => setAgentImage(event.target.value)} /></label>
            <label className="repeat-field"><span>Repeat profile</span><select value={repeats} onChange={(event) => setRepeats(Number(event.target.value))}><option value={1}>1 · Smoke</option><option value={5}>5 · Standard</option><option value={10}>10 · Research</option></select></label>
            <div className="integrity-note"><ShieldCheck size={16} /><span>Strict pairing locks prompt, commit, image, CPU, memory, timeout, network, and agent version.</span></div>
          </div>

          {error && <div className="form-error">{error}</div>}
        </div>

        <footer className="modal-footer">
          <div><span>Planned workload</span><strong>{taskIds.length * repeats * 2} runs · {taskIds.length} context keys</strong></div>
          <button className="button secondary" onClick={onClose} disabled={creating}>Cancel</button>
          <button className="button primary" onClick={submit} disabled={creating}>{creating ? "Creating plan…" : "Create & prepare"}</button>
        </footer>
      </div>
    </div>
  );
}

function ProfileRow({ role, provider, model, thinking, onProvider, onModel, onThinking }: {
  role: string;
  provider: string;
  model: string;
  thinking: CreateExperimentRequest["model"]["thinking"];
  onProvider: (value: string) => void;
  onModel: (value: string) => void;
  onThinking?: (value: CreateExperimentRequest["model"]["thinking"]) => void;
}) {
  return (
    <div className="profile-row">
      <strong>{role}</strong>
      <input aria-label={`${role} provider`} value={provider} onChange={(event) => onProvider(event.target.value)} />
      <input aria-label={`${role} model`} value={model} onChange={(event) => onModel(event.target.value)} />
      {onThinking ? (
        <select aria-label={`${role} thinking`} value={thinking} onChange={(event) => onThinking(event.target.value as typeof thinking)}><option>off</option><option>low</option><option>medium</option><option>high</option><option>xhigh</option><option>max</option></select>
      ) : <span className="thinking-lock">{thinking}</span>}
    </div>
  );
}

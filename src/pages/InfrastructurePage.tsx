import { Box, Check, Clipboard, Container, Copy, HardDrive, KeyRound, Network, RefreshCw, ServerCog, TerminalSquare } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { DiagnosticIcon, PageTitle, StatusBadge } from "../components/shared";
import type { DiagnosticItem, RuntimeSettings } from "../domain/types";
import { useI18n } from "../i18n";
import { controlWorker, workerRequest } from "../lib/desktop";
import { runtimeVariablesPayload, type RuntimeVariable } from "../lib/environment";

export function InfrastructurePage({ diagnostics, onDiagnose, diagnosing }: { diagnostics: DiagnosticItem[]; onDiagnose: (distribution?: string) => void; diagnosing: boolean }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const [settings, setSettings] = useState<RuntimeSettings>();
  const [variables, setVariables] = useState<(RuntimeVariable & { id: number })[]>([{ id: 0, name: "XIAOMI_TOKEN_PLAN_CN_API_KEY", value: "" }]);
  const nextVariableId = useRef(1);
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const [credentialMessage, setCredentialMessage] = useState("");
  const [distribution, setDistribution] = useState(() => localStorage.getItem("ctxbench-distribution") || "Ubuntu");
  const refresh = () => workerRequest<RuntimeSettings>("/runtime").then(setSettings).catch(() => {});
  useEffect(() => { void refresh(); }, []);
  const action = async (value: "start" | "stop" | "build") => { setBusy(true); setMessage(""); try { setMessage(await controlWorker(value, distribution)); await refresh(); onDiagnose(); } catch (error) { setMessage(String(error)); } finally { setBusy(false); } };
  const save = async () => {
    setBusy(true); setCredentialMessage("");
    try {
      await workerRequest("/runtime/credentials", "POST", runtimeVariablesPayload(variables));
      setVariables([{ id: nextVariableId.current++, name: "", value: "" }]);
      setCredentialMessage("Environment variables saved in worker memory until restart.");
      await refresh();
    } catch (error) { setCredentialMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  const updateVariable = (id: number, changes: Partial<RuntimeVariable>) => setVariables((rows) => rows.map((row) => row.id === id ? { ...row, ...changes } : row));
  const command = "docker compose -f docker/compose.yaml up -d --build ctxbench-worker";
  const copyCommand = async () => {
    await navigator.clipboard.writeText(command);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="page">
      <PageTitle
        eyebrow={t("LOCAL INFRASTRUCTURE")}
        title={t("WSL & container runtime")}
        description={t("Everything runs locally. The desktop app controls an isolated worker inside WSL2.")}
        actions={<button className="button primary" onClick={() => onDiagnose(distribution)} disabled={diagnosing}><RefreshCw size={16} className={diagnosing ? "spin" : ""} /> {diagnosing ? t("Checking…") : t("Run diagnostics")}</button>}
      />

      <section className="infra-layout">
        <div className="panel diagnostics-panel">
          <div className="panel-header"><div><span className="panel-kicker">{t("READINESS")}</span><h2>{t("System checks")}</h2></div><StatusBadge status={diagnostics.length > 0 && diagnostics.every((item) => item.status === "healthy") ? "healthy" : "warning"} label={diagnostics.length > 0 && diagnostics.every((item) => item.status === "healthy") ? t("Ready") : t("Action needed")} /></div>
          <div className="diagnostic-list">
            {diagnostics.map((item) => (
              <div className="diagnostic-row" key={item.id}>
                <DiagnosticIcon status={item.status} />
                <div><strong>{t(item.label)}</strong><span>{t(item.detail)}</span>{item.fix && <small>{t(item.fix)}</small>}</div>
                <StatusBadge status={item.status} />
              </div>
            ))}
          </div>
        </div>

        <div className="panel topology-panel">
          <div className="panel-header"><div><span className="panel-kicker">{t("EXECUTION PATH")}</span><h2>{t("Local topology")}</h2></div><ServerCog size={19} /></div>
          <div className="topology">
            <TopologyNode icon={<TerminalSquare size={20} />} title={t("Desktop")} sub={t("Tauri control layer")} active />
            <div className="topology-link"><span>{t("HTTP :48173")}</span></div>
            <TopologyNode icon={<Container size={20} />} title={t("WSL worker")} sub={t("Persistent queue + SQLite")} />
            <div className="topology-link"><span>{t("Docker socket")}</span></div>
            <div className="topology-split">
              <TopologyNode icon={<Box size={19} />} title={t("Pi agent")} sub={t("API-only network")} />
              <TopologyNode icon={<HardDrive size={19} />} title={t("Grader")} sub={t("Offline + clean base")} />
            </div>
          </div>
        </div>

        <div className="panel setup-panel">
          <div className="panel-header"><div><span className="panel-kicker">{t("NEXT ACTION")}</span><h2>{t("Start the worker")}</h2></div><Clipboard size={18} /></div>
          <p>{t("Build the bundled images once, then start the worker. Existing experiments remain stored in WSL.")}</p>
          <label>{t("Distribution")}<input value={distribution} onChange={(e) => { setDistribution(e.target.value); localStorage.setItem("ctxbench-distribution", e.target.value); }} /></label>
          <div className="toolbar"><button className="button secondary" disabled={busy} onClick={() => void action("build")}>{t("Build images")}</button><button className="button primary" disabled={busy} onClick={() => void action("start")}>{t("Start worker")}</button><button className="button secondary" disabled={busy} onClick={() => void action("stop")}>{t("Stop worker")}</button></div>
          {busy && <p>{t("Working…")}</p>}{message && <p role="status">{t(message)}</p>}
          <div className="code-command"><code>{command}</code><button onClick={copyCommand} title={t("Copy command")}>{copied ? <Check size={15} /> : <Copy size={15} />}</button></div>
          <div className="setup-notes">
            <span><Check size={14} /> {t("Binds to localhost only")}</span>
            <span><Check size={14} /> {t("Resumes queued work after restart")}</span>
            <span><Check size={14} /> {t("Images export for air-gapped use")}</span>
          </div>
        </div>

        <div className="panel policy-panel">
          <div className="panel-header"><div><span className="panel-kicker">{t("SECURITY POLICY")}</span><h2>{t("Runtime boundaries")}</h2></div><KeyRound size={18} /></div>
          <Policy icon={<Network size={16} />} title={t("Agent network")} value={t("API-only")} detail={t("Provider endpoints from allowlist")} />
          <Policy icon={<HardDrive size={16} />} title={t("Grader network")} value={t("Offline")} detail={t("Clean base + graded patch only")} />
          <Policy icon={<KeyRound size={16} />} title={t("Credentials")} value={t("Runtime-only")} detail={t("Values redacted from all artifacts")} />
          <div className="workbench-form"><h3>{t("Agent environment")}</h3>
            <p>{settings?.runner} · {settings?.dataDirectory}</p>
            {settings?.credentials.map((item) => <small key={item.name}>{item.name} · {t(item.configured ? "Configured" : "Not configured")}</small>)}
            <p>{t("Add multiple name/value rows and save them together. Values are hidden and are never returned by the worker.")}</p>
            {variables.map((row, index) => <fieldset key={row.id} disabled={busy}>
              <legend>{t("Variable {index}", { index: index + 1 })}</legend>
              <div className="runtime-variable-fields">
                <label>{t("Environment variable name")}<input value={row.name} autoComplete="off" spellCheck={false} placeholder="OPENAI_API_KEY" onChange={(event) => updateVariable(row.id, { name: event.target.value })} /></label>
                <label>{t("Environment variable value")}<input type="password" autoComplete="new-password" value={row.value} onChange={(event) => updateVariable(row.id, { value: event.target.value })} /></label>
                <button type="button" className="button tertiary" disabled={variables.length === 1} aria-label={t("Remove variable {index}", { index: index + 1 })} onClick={() => setVariables((rows) => rows.filter((item) => item.id !== row.id))}>{t("Remove variable")}</button>
              </div>
            </fieldset>)}
            <div className="toolbar">
              <button type="button" className="button secondary" disabled={busy || variables.length >= 100} onClick={() => setVariables([...variables, { id: nextVariableId.current++, name: "", value: "" }])}>{t("Add variable")}</button>
              <button type="button" className="button primary" disabled={busy || !variables.some((row) => row.value)} onClick={() => void save()}>{t("Save environment variables")}</button>
            </div>
            {credentialMessage && <p role="status">{t(credentialMessage)}</p>}
            <p>{t("Values stay in worker memory. Restart clears values entered here; deployment environment variables remain available.")}</p>
          </div>
        </div>
      </section>
    </div>
  );
}

function TopologyNode({ icon, title, sub, active = false }: { icon: React.ReactNode; title: string; sub: string; active?: boolean }) {
  return <div className={`topology-node ${active ? "active" : ""}`}><span>{icon}</span><div><strong>{title}</strong><small>{sub}</small></div></div>;
}

function Policy({ icon, title, value, detail }: { icon: React.ReactNode; title: string; value: string; detail: string }) {
  return <div className="policy-row"><span className="policy-icon">{icon}</span><div><strong>{title}</strong><small>{detail}</small></div><em>{value}</em></div>;
}

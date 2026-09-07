import { Box, Container, HardDrive, KeyRound, Network, RefreshCw, ServerCog, TerminalSquare } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { DiagnosticIcon, PageTitle, StatusBadge } from "../components/shared";
import { InfrastructureSetup } from "../components/InfrastructureSetup";
import type { DiagnosticItem, RuntimeSettings } from "../domain/types";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import { runtimeVariablesPayload, type RuntimeVariable } from "../lib/environment";
import { savedDistribution, saveDistribution } from "../lib/wsl";

export function InfrastructurePage({ diagnostics, onDiagnose, diagnosing }: { diagnostics: DiagnosticItem[]; onDiagnose: (distribution?: string) => void; diagnosing: boolean }) {
  const { t } = useI18n();
  const [settings, setSettings] = useState<RuntimeSettings>();
  const [variables, setVariables] = useState<(RuntimeVariable & { id: number })[]>([{ id: 0, name: "XIAOMI_TOKEN_PLAN_CN_API_KEY", value: "" }]);
  const nextVariableId = useRef(1);
  const [credentialBusy, setCredentialBusy] = useState(false);
  const [deploymentBusy, setDeploymentBusy] = useState(false);
  const busy = credentialBusy || deploymentBusy;
  const [credentialMessage, setCredentialMessage] = useState("");
  const [credentialError, setCredentialError] = useState(false);
  const [distribution, setDistribution] = useState(savedDistribution);
  const changeDistribution = (name: string) => { setDistribution(name); saveDistribution(name); };
  const refresh = () => workerRequest<RuntimeSettings>("/runtime").then(setSettings).catch(() => setSettings(undefined));
  useEffect(() => { void refresh(); }, []);
  const save = async () => {
    setCredentialBusy(true); setCredentialMessage(""); setCredentialError(false);
    try {
      await workerRequest("/runtime/credentials", "POST", runtimeVariablesPayload(variables));
      setVariables([{ id: nextVariableId.current++, name: "", value: "" }]);
      setCredentialMessage("Environment variables saved in worker memory until restart.");
      await refresh();
    } catch (error) { setCredentialError(true); setCredentialMessage(error instanceof Error ? error.message : String(error)); }
    finally { setCredentialBusy(false); }
  };
  const updateVariable = (id: number, changes: Partial<RuntimeVariable>) => setVariables((rows) => rows.map((row) => row.id === id ? { ...row, ...changes } : row));

  return (
    <div className="page">
      <PageTitle
        eyebrow={t("LOCAL INFRASTRUCTURE")}
        title={t("WSL & container runtime")}
        description={t("Everything runs locally. The desktop app controls an isolated worker inside WSL2.")}
        actions={<><button className="button secondary" onClick={() => { const heading = document.getElementById("setup-heading"); heading?.focus({ preventScroll: true }); heading?.scrollIntoView({ block: "start" }); }}>{t("Open setup guide")}</button><button className="button primary" onClick={() => onDiagnose(distribution)} disabled={diagnosing || busy}><RefreshCw size={16} className={diagnosing ? "spin" : ""} /> {diagnosing ? t("Checking…") : t("Run diagnostics")}</button></>}
      />

      <section className="infra-layout">
        <div className="panel diagnostics-panel">
          <div className="panel-header"><div><span className="panel-kicker">{t("READINESS")}</span><h2>{t("System checks")}</h2></div><StatusBadge status={diagnostics.length > 0 && diagnostics.every((item) => item.status === "healthy") ? "healthy" : "warning"} label={diagnostics.length > 0 && diagnostics.every((item) => item.status === "healthy") ? t("Ready") : t("Action needed")} /></div>
          <div className="diagnostic-list">
            {diagnostics.length === 0 && <p>{t("Run diagnostics to check WSL, Docker and the worker connection.")}</p>}
            {diagnostics.map((item) => {
              const values = item.detailValues && Object.fromEntries(Object.entries(item.detailValues).map(([key, value]) => [key, typeof value === "string" ? t(value) : value]));
              return (
              <div className="diagnostic-row" key={item.id}>
                <DiagnosticIcon status={item.status} />
                <div><strong>{t(item.label)}</strong>{item.status === "healthy" ? <details><summary>{t("Show diagnostic details")}</summary><pre>{t(item.detail, values)}</pre></details> : <span>{t(item.detail, values)}</span>}{item.fix && <small>{t(item.fix)}</small>}</div>
                <StatusBadge status={item.status} />
              </div>
              );
            })}
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

        <InfrastructureSetup distribution={distribution} onDistribution={changeDistribution} diagnosing={diagnosing || credentialBusy} onBusy={setDeploymentBusy} onDiagnose={(name) => { onDiagnose(name); void refresh(); }} />

        <div className="panel policy-panel">
          <div className="panel-header"><div><span className="panel-kicker">{t("SECURITY POLICY")}</span><h2>{t("Runtime boundaries")}</h2></div><KeyRound size={18} /></div>
          <Policy icon={<Network size={16} />} title={t("Agent network")} value={t("API-only")} detail={t("Provider endpoints from allowlist")} />
          <Policy icon={<HardDrive size={16} />} title={t("Grader network")} value={t("Offline")} detail={t("Clean base + graded patch only")} />
          <Policy icon={<KeyRound size={16} />} title={t("Credentials")} value={t("Runtime-only")} detail={t("Values redacted from all artifacts")} />
          <div className="workbench-form"><h3>{t("Agent environment")}</h3>
            {settings ? <p>{settings.runner} · {settings.dataDirectory}</p> : <p className="setup-callout">{t("Start the worker successfully before configuring Agent environment variables. No API key is needed to install or start the worker.")}</p>}
            {settings?.credentials.map((item) => <small key={item.name}>{item.name} · {t(item.configured ? "Configured" : "Not configured")}</small>)}
            <p>{t("Add multiple name/value rows and save them together. Values are hidden and are never returned by the worker.")}</p>
            {variables.map((row, index) => <fieldset key={row.id} disabled={busy || !settings}>
              <legend>{t("Variable {index}", { index: index + 1 })}</legend>
              <div className="runtime-variable-fields">
                <label>{t("Environment variable name")}<input value={row.name} autoComplete="off" spellCheck={false} placeholder="OPENAI_API_KEY" onChange={(event) => updateVariable(row.id, { name: event.target.value })} /></label>
                <label>{t("Environment variable value")}<input type="password" autoComplete="new-password" value={row.value} onChange={(event) => updateVariable(row.id, { value: event.target.value })} /></label>
                <button type="button" className="button tertiary" disabled={variables.length === 1} aria-label={t("Remove variable {index}", { index: index + 1 })} onClick={() => setVariables((rows) => rows.filter((item) => item.id !== row.id))}>{t("Remove variable")}</button>
              </div>
            </fieldset>)}
            <div className="toolbar">
              <button type="button" className="button secondary" disabled={busy || !settings || variables.length >= 100} onClick={() => setVariables([...variables, { id: nextVariableId.current++, name: "", value: "" }])}>{t("Add variable")}</button>
              <button type="button" className="button primary" disabled={busy || !settings || !variables.some((row) => row.value)} onClick={() => void save()}>{t("Save environment variables")}</button>
            </div>
            {credentialMessage && <p className={credentialError ? "form-error" : "credential-success"} role={credentialError ? "alert" : "status"}>{t(credentialMessage)}</p>}
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

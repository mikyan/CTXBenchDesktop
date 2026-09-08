import { useEffect, useRef, useState } from "react";
import { KeyRound, Plus, RefreshCw } from "lucide-react";
import type { RuntimeSettings } from "../domain/types";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import { runtimeVariablesPayload, type RuntimeVariable } from "../lib/environment";

export function RuntimeCredentials({ disabled, refreshKey, onBusy, onRuntime }: { disabled: boolean; refreshKey: number; onBusy: (value: boolean) => void; onRuntime: () => void }) {
  const { t } = useI18n();
  const [settings, setSettings] = useState<RuntimeSettings>();
  const [variables, setVariables] = useState<(RuntimeVariable & { id: number })[]>([{ id: 0, name: "", value: "" }]);
  const nextId = useRef(1);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(""); const [error, setError] = useState(false);
  const refresh = () => workerRequest<RuntimeSettings>("/runtime").then(setSettings).catch(() => setSettings(undefined));
  useEffect(() => { let alive = true; void workerRequest<RuntimeSettings>("/runtime").then((value) => { if (alive) setSettings(value); }).catch(() => { if (alive) setSettings(undefined); }); return () => { alive = false; }; }, [refreshKey]);
  const save = async () => {
    setBusy(true); onBusy(true); setMessage(""); setError(false);
    try {
      await workerRequest("/runtime/credentials", "POST", runtimeVariablesPayload(variables));
      setVariables([{ id: nextId.current++, name: "", value: "" }]);
      setMessage("Environment variables saved in worker memory until restart."); await refresh();
    } catch (cause) { setError(true); setMessage(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); onBusy(false); }
  };
  return <section className="panel settings-form" aria-label={t("Model credentials")}>
    <div className="panel-header"><h2>{t("Agent environment")}</h2><KeyRound size={20} /></div>
    <div className="settings-form-body workbench-form">
      <div className="info-note"><strong>{t("Model choices are per experiment")}</strong><p>{t("Save credentials here, then choose Provider, model and allowed variable names in New experiment. Saving a key does not start an Agent.")}</p></div>
      {!settings && <div className="setup-callout"><div><p>{t("Start the worker successfully before configuring Agent environment variables. No API key is needed to install or start the worker.")}</p><button className="button secondary" onClick={onRuntime}>{t("Back to runtime")}</button></div></div>}
      <div className="setup-check-header"><h3>{t("Configured variable names")}</h3><button className="button secondary" disabled={disabled || busy} onClick={() => void refresh()}><RefreshCw size={16} />{t("Refresh connection")}</button></div>
      <div className="credential-inventory">{settings?.credentials.some((item) => item.configured) ? settings.credentials.filter((item) => item.configured).map((item) => <span key={item.name}><code>{item.name}</code><small>{t("Configured")}</small></span>) : <p>{t("No configured variables")}</p>}</div>
      {!!settings?.credentials.some((item) => !item.configured) && <details><summary>{t("Other supported variable names")}</summary><div className="credential-inventory">{settings.credentials.filter((item) => !item.configured).map((item) => <span key={item.name}><code>{item.name}</code><small>{t("Not configured")}</small></span>)}</div></details>}
      <p>{t("Add multiple name/value rows and save them together. Values are hidden and are never returned by the worker.")}</p>
      {variables.map((row, index) => <fieldset key={row.id} disabled={disabled || busy || !settings}>
        <legend>{t("Variable {index}", { index: index + 1 })}</legend><div className="runtime-variable-fields">
          <label>{t("Environment variable name")}<input value={row.name} autoComplete="off" spellCheck={false} placeholder="OPENAI_API_KEY" onChange={(e) => setVariables((rows) => rows.map((r) => r.id === row.id ? { ...r, name: e.target.value } : r))} /></label>
          <label>{t("Environment variable value")}<input type="password" autoComplete="new-password" value={row.value} onChange={(e) => setVariables((rows) => rows.map((r) => r.id === row.id ? { ...r, value: e.target.value } : r))} /></label>
          <button type="button" className="button tertiary" disabled={variables.length === 1} aria-label={t("Remove variable {index}", { index: index + 1 })} onClick={() => setVariables((rows) => rows.filter((r) => r.id !== row.id))}>{t("Remove variable")}</button>
        </div>
      </fieldset>)}
      <div className="form-actions"><button className="button secondary" disabled={disabled || busy || !settings || variables.length >= 100} onClick={() => setVariables((rows) => [...rows, { id: nextId.current++, name: "", value: "" }])}><Plus size={16} />{t("Add variable")}</button><button className="button primary" disabled={disabled || busy || !settings || !variables.some((row) => row.value)} onClick={() => void save()}>{t(busy ? "Saving…" : "Save environment variables")}</button></div>
      {message && <p className={error ? "form-error" : "credential-success"} role={error ? "alert" : "status"}>{t(message)}</p>}
      <p>{t("Values stay in worker memory. Restart clears values entered here; deployment environment variables remain available.")}</p>
      {settings && <details><summary>{t("Environment details")}</summary><p>{settings.runner} · <code>{settings.dataDirectory}</code></p></details>}
    </div>
  </section>;
}

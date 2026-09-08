import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import { activityState, type DeploymentInfo } from "../lib/infrastructure";
import { ConfirmDialog } from "./Dialogs";

export function RuntimeSafety({ info, distribution, disabled, checking, onCheck, onStop, onExperiments, onKnowledge }: {
  info?: DeploymentInfo; distribution: string; disabled: boolean; checking: boolean; onCheck: () => void; onStop: () => void;
  onExperiments?: () => void; onKnowledge?: () => void;
}) {
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  useEffect(() => { setConfirming(false); setAcknowledged(false); }, [distribution]);
  const state = activityState(info);
  const canStop = state.known && !state.tasks.length && !disabled;
  const title = checking ? "Checking container activity…" : !state.known ? "Container activity is unknown" : state.tasks.length ? "Wait for active tasks before maintenance" : state.containers.length ? "Stop the old worker before replacing images" : "No active CTXBench containers detected";
  return <section className="runtime-safety" aria-label={t("Image update safety check")}>
    <header><div><h3>{t("Image update safety check")}</h3><span>{distribution || t("Select an installed WSL distribution first.")}</span></div><button className="button secondary" disabled={disabled} onClick={onCheck}>{t("Recheck status")}</button></header>
    <p className="safety-status" role="status">{t(title)}</p>
    <p>{t("Pause experiments → wait for current tasks → stop worker → import or build images → start worker. Closing the desktop does not stop Docker containers.")}</p>
    <p>{t("This list covers CTXBench containers across the selected Docker daemon, including other deployments. Stopped containers and the egress proxy alone do not block import. Refresh to check again; this is not live monitoring.")}</p>
    {state.containers.length > 0 && <ul className="active-container-list">{state.containers.map((item) => <li key={item.id}>
      <strong>{item.name}</strong><span>{t(item.role === "worker" ? "Worker" : item.role === "grader" ? "Grading container" : "Agent / knowledge generation container")}</span><code>{item.id} · {item.status}</code>
    </li>)}</ul>}
    {info?.activityError && <details><summary>{t("Technical details (redacted)")}</summary><pre>{t(info.activityError)}</pre></details>}
    <div className="toolbar">
      {onExperiments && <button className="button secondary" disabled={disabled} onClick={onExperiments}>{t("View experiments and pause scheduling")}</button>}
      {onKnowledge && <button className="button secondary" disabled={disabled} onClick={onKnowledge}>{t("View knowledge generation")}</button>}
      <button className="button secondary" disabled={!canStop} onClick={() => { setAcknowledged(false); setConfirming(true); }}>{t("Stop worker…")}</button>
    </div>
    {state.tasks.length > 0 && <p>{t("Pause stops new scheduling, not the current task. Wait for these containers to exit. If the worker is unreachable or containers remain unexpectedly, copy the diagnostic report for investigation; do not force-remove them.")}</p>}
    {confirming && <ConfirmDialog title={t("Confirm worker stop")} description={t("This stops only the worker managed by the detected Compose file. It does not stop other deployments or delete datasets, results, images or volumes. Runtime-only credentials must be entered again after restart.")}
      confirmLabel={t("Confirm and stop worker")} disabled={!acknowledged || !canStop} onCancel={() => { setConfirming(false); setAcknowledged(false); }} onConfirm={() => { setConfirming(false); setAcknowledged(false); onStop(); }}>
      <label className="offline-confirm"><input type="checkbox" checked={acknowledged} disabled={!canStop} onChange={(event) => setAcknowledged(event.target.checked)} />{t("I have paused experiment scheduling and waited for all generation, preparation and evaluation jobs to finish.")}</label>
      {!canStop && <p role="alert">{t("Container activity changed. Cancel and recheck before stopping.")}</p>}
    </ConfirmDialog>}
  </section>;
}

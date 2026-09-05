import { useState } from "react";
import type { OperationRecord } from "../domain/types";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import { relativeTime } from "../lib/format";
import { StatusBadge } from "./shared";

export function PreparationQueue({ operations, kind }: { operations: OperationRecord[]; kind: "context" | "constraints" }) {
  const { t, locale } = useI18n();
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);
  const selected = operations.filter((item) => item.kind === kind).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  const act = async (id: string, action: string) => {
    setBusy(id); setError("");
    try { await workerRequest(`/operations/${id}/${action}`, "POST"); }
    catch (error) { setError(String(error)); }
    finally { setBusy(undefined); }
  };
  if (!selected.length) return null;
  return <section className="panel preparation-queue">
    <div className="panel-header"><h2>{t("Independent preparation tasks")}</h2><span>{selected.length}</span></div>
    <p className="panel-note">{t("Pause takes effect at a stage boundary. Cancel stops the active agent; completed stages and frozen packages remain reusable.")}</p>
    {error && <p role="alert" className="form-error">{error}</p>}
    <div className="compact-table-wrap"><table className="data-table"><thead><tr><th>{t("Task")}</th><th>{t("Status")}</th><th>{t("Updated")}</th><th>{t("Actions")}</th></tr></thead><tbody>
      {(showAll ? selected : selected.slice(0, 8)).map((item) => <tr key={item.id}>
        <td><strong>{item.taskId ?? item.id}</strong><small className="muted">{item.id}</small>{item.failure && <p className="form-error">{item.failure}</p>}</td>
        <td><StatusBadge status={item.status} /></td><td>{relativeTime(item.updatedAt, locale)}</td>
        <td><div className="toolbar">
          {["queued", "running"].includes(item.status) && <button className="button secondary" disabled={busy === item.id} onClick={() => void act(item.id, "pause")}>{t("Pause")}</button>}
          {item.status === "paused" && <button className="button secondary" disabled={busy === item.id} onClick={() => void act(item.id, "resume")}>{t("Resume")}</button>}
          {["failed", "cancelled"].includes(item.status) && <button className="button secondary" disabled={busy === item.id} onClick={() => void act(item.id, "retry")}>{t("Retry")}</button>}
          {["queued", "running", "paused"].includes(item.status) && <button className="button secondary" disabled={busy === item.id} onClick={() => void act(item.id, "cancel")}>{t("Cancel")}</button>}
        </div></td>
      </tr>)}
    </tbody></table></div>
    {selected.length > 8 && <button className="text-button" onClick={() => setShowAll(!showAll)}>{t(showAll ? "Show less" : "Show all")}</button>}
  </section>;
}

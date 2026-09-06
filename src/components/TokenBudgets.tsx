import { useState } from "react";
import type { TokenBudgetRecord } from "../domain/types";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";

function BudgetIncrease({ budget }: { budget: TokenBudgetRecord }) {
  const { t } = useI18n(); const [limit, setLimit] = useState(budget.limitTokens);
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const increase = async () => { setBusy(true); setError(""); try {
    await workerRequest(`/token-budgets/${budget.id}/increase`, "POST", { expectedLimitTokens: budget.limitTokens, limitTokens: limit, reason: "User approved higher total allowance in desktop" });
  } catch (error) { setError(String(error)); } finally { setBusy(false); } };
  return <details><summary>{t("Increase total allowance")}</summary><p>{t("Existing usage and reservations are retained. The increase is recorded for audit.")}</p>
    <label>{t("New total allowance")}<input type="number" min={budget.limitTokens + 1} value={limit} onChange={(e) => setLimit(Number(e.target.value))} /></label>
    <button className="button secondary" disabled={busy || !Number.isSafeInteger(limit) || limit <= budget.limitTokens} onClick={() => void increase()}>{t("Authorize increase")}</button>
    {budget.limitChanges?.map((change, index) => <p key={index}>{change.fromTokens.toLocaleString()} → {change.toTokens.toLocaleString()} · {change.createdAt}</p>)}
    {error && <p className="form-error" role="alert">{error}</p>}</details>;
}

export function TokenBudgets({ budgets }: { budgets: TokenBudgetRecord[] }) {
  const { t } = useI18n();
  const [id, setId] = useState(""); const [limit, setLimit] = useState(1000000000);
  const [model, setModel] = useState("mimo-v2.5"); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const create = async () => { setBusy(true); setError(""); try { await workerRequest("/token-budgets", "POST", { id, limitTokens: limit, provider: "xiaomi-token-plan-cn", model }); setId(""); } catch (error) { setError(String(error)); } finally { setBusy(false); } };
  return <section className="panel workbench-results"><h2>{t("Shared token budget")}</h2>
    <p>{t("All attached experiments and roles share this allowance. Increases require explicit authorization. Failed or interrupted attempts retain a conservative charge. This is not the Provider bill.")}</p>
    {budgets.map((budget) => <article key={budget.id}><h3>{budget.id} · {budget.model}</h3><p>{t("Reported / charged / reserved / remaining")}: {budget.reportedTokens.toLocaleString()} / {budget.chargedTokens.toLocaleString()} / {budget.reservedTokens.toLocaleString()} / {budget.remainingTokens.toLocaleString()}</p><small>{t("Unconfirmed allowance")}: {budget.unconfirmedTokens.toLocaleString()} · {t("Total allowance")}: {budget.limitTokens.toLocaleString()}</small><BudgetIncrease budget={budget} /></article>)}
    <details><summary>{t("Create shared budget")}</summary><div className="form-grid two"><label>{t("Budget ID")}<input value={id} onChange={(e) => setId(e.target.value)} /></label><label>{t("Total allowance")}<input type="number" min={1} value={limit} onChange={(e) => setLimit(Number(e.target.value))} /></label><label>{t("Model")}<select value={model} onChange={(e) => setModel(e.target.value)}><option>mimo-v2.5</option><option>mimo-v2.5-pro</option></select></label></div><button className="button secondary" disabled={busy || !id || limit < 1} onClick={() => void create()}>{t("Create shared budget")}</button></details>
    {error && <p className="form-error" role="alert">{error}</p>}
  </section>;
}

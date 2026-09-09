import { useState } from "react";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import type { OperatorJob } from "../lib/intranet";
import { OperatorJobPanel } from "./OperatorJobPanel";
import { CompanyProfilePicker } from "./CompanyProfilePicker";

export function DatasetSelfTest({ payload, disabled = false }: { payload: string; disabled?: boolean }) {
  const { t } = useI18n();
  const [job, setJob] = useState<{ payload: string; value: OperatorJob }>();
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const [profileId, setProfileId] = useState(""); const [trusted, setTrusted] = useState(false);
  const run = async () => {
    setBusy(true); setError("");
    try { const value = await workerRequest<OperatorJob>("/intranet/operations/probe", "POST", { ...JSON.parse(payload), profileId }); setJob({ payload, value }); }
    catch (cause) { setError(String(cause)); } finally { setBusy(false); }
  };
  let hasCI = false;
  try { hasCI = Boolean(payload && JSON.parse(payload).rows?.some((row: { test?: { ci?: unknown } }) => row.test?.ci)); } catch { /* Incomplete form. */ }
  if (hasCI) return <p className="wizard-notice">{t('CI: the local self-test never uploads code. Run CI cases through an explicitly configured experiment.')}</p>;
  return <section className="dataset-self-test"><h4>{t("Run baseline / reference self-test")}</h4>
    <p>{t("Runs actual test containers without an Agent: original tests (if hidden tests exist), baseline with hidden tests, and the same tests with the reference fix. A reference patch is required. Each phase is offline, 2 CPU / 4 GiB / 10 minutes.")}</p>
    <CompanyProfilePicker value={profileId} onChange={(record) => setProfileId(record?.id ?? "")} preparationOnly />
    <label className="check-line"><input type="checkbox" checked={trusted} onChange={(e) => setTrusted(e.target.checked)} />{t("I trust these test commands and images and want to execute them locally.")}</label>
    <button className="button secondary" disabled={disabled || busy || !payload || !trusted} onClick={() => void run()}>{t(busy ? "Queueing…" : "Run self-test (no model tokens)")}</button>
    {error && <p className="form-error" role="alert">{error}</p>}
    {job && <>{job.payload !== payload && <p role="alert">{t("The definition has changed. This result belongs to the previous definition; run self-test again.")}</p>}<OperatorJobPanel initial={job.value} /></>}
  </section>;
}

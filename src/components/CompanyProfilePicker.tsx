import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import { workerRequest } from "../lib/desktop";
import type { CompanyProfileRecord } from "../lib/intranet";

export function CompanyProfilePicker({ value, onChange, preparationOnly = false }: { value: string; onChange: (profile: CompanyProfileRecord | undefined) => void; preparationOnly?: boolean }) {
  const { t } = useI18n();
  const [profiles, setProfiles] = useState<CompanyProfileRecord[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { let alive = true; void workerRequest<CompanyProfileRecord[]>("/intranet/profiles").then((rows) => { if (alive) setProfiles(rows); }).catch((cause) => { if (alive) setError(String(cause)); }); return () => { alive = false; }; }, []);
  return <div className="company-profile-picker"><label>{t("Company environment profile")}<select value={value} onChange={(e) => onChange(profiles.find((p) => p.id === e.target.value))}>
    <option value="">{t("No company profile")}</option>{profiles.map((p) => <option key={p.id} value={p.id}>{p.document.name} · {p.id.slice(0, 8)}</option>)}
  </select></label><small>{t(preparationOnly ? "Only Git mirror and offline preparation settings apply here. No model or Agent is used; test images remain those defined by the dataset." : "Selecting a profile fills model, image and Agent defaults. Its preparation policy is frozen for this new experiment; existing experiments are unchanged.")}</small>
    {error && <p className="form-error">{error}</p>}
  </div>;
}

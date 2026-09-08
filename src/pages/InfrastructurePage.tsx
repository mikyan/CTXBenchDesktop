import { RefreshCw, ShieldCheck } from "lucide-react";
import { useCallback, useState } from "react";
import { DiagnosticIcon, PageTitle, StatusBadge } from "../components/shared";
import { InfrastructureSetup } from "../components/InfrastructureSetup";
import { IntranetWorkbench } from "../components/IntranetWorkbench";
import { SectionNav } from "../components/SectionNav";
import { RuntimeCredentials } from "../components/RuntimeCredentials";
import type { DiagnosticItem } from "../domain/types";
import { useI18n } from "../i18n";
import { savedDistribution, saveDistribution } from "../lib/wsl";
import { settingsSections, type SettingsSection } from "../lib/navigation";

export function InfrastructurePage({ diagnostics, onDiagnose, diagnosing, initialSection = "runtime" }: { diagnostics: DiagnosticItem[]; onDiagnose: (distribution?: string) => void; diagnosing: boolean; initialSection?: SettingsSection }) {
  const { t } = useI18n();
  const [section, setSection] = useState<SettingsSection>(initialSection);
  const [credentialBusy, setCredentialBusy] = useState(false); const [deploymentBusy, setDeploymentBusy] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [distribution, setDistribution] = useState(savedDistribution);
  const changeDistribution = (name: string) => { setDistribution(name); saveDistribution(name); };
  const diagnose = useCallback((name?: string) => { onDiagnose(name); setRefreshKey((key) => key + 1); }, [onDiagnose]);
  const selected = settingsSections.find((item) => item.id === section)!;
  const companySection = section === "profiles" ? "Company profiles" : section === "adaptation" ? "Image adaptation" : "Portable resources";
  const ready = diagnostics.length > 0 && diagnostics.every((item) => item.status === "healthy");
  return <div className="page settings-page">
    <PageTitle eyebrow={t("System settings")} title={t("Settings")} description={t("Configure one area at a time. Experiment-specific models and budgets belong in New experiment.")} />
    <div className="settings-layout">
      <SectionNav label="Settings sections" items={settingsSections} value={section} onChange={setSection} vertical />
      <div className="settings-main">
        <header className="section-heading"><h2>{t(selected.label)}</h2><p>{t(selected.description)}</p></header>
        <div hidden={section !== "runtime"} className="settings-stack">
          <section className="panel diagnostics-panel" aria-label={t("System checks")}>
            <div className="panel-header"><div><h2>{t("System checks")}</h2><StatusBadge status={diagnosing ? "checking" : ready ? "healthy" : "warning"} label={t(diagnosing ? "Checking…" : ready ? "Ready" : "Action needed")} /></div><button className="button secondary" onClick={() => diagnose(distribution)} disabled={diagnosing || credentialBusy || deploymentBusy}><RefreshCw size={16} className={diagnosing ? "spin" : ""} />{t("Run diagnostics")}</button></div>
            <div className={`diagnostic-list ${ready ? "all-healthy" : ""}`}>
              {!diagnostics.length && <p>{t("Run diagnostics to check WSL, Docker and the worker connection.")}</p>}
              {diagnostics.map((item) => {
                const values = item.detailValues && Object.fromEntries(Object.entries(item.detailValues).map(([key, value]) => [key, typeof value === "string" ? t(value) : value]));
                return <div className="diagnostic-row" key={item.id}><DiagnosticIcon status={diagnosing ? "checking" : item.status} /><div><strong>{t(item.label)}</strong>{item.status === "healthy" ? <details><summary>{t("Show diagnostic details")}</summary><pre>{t(item.detail, values)}</pre></details> : <span>{t(item.detail, values)}</span>}{item.fix && item.status !== "healthy" && <small>{t(item.fix)}</small>}</div><StatusBadge status={diagnosing ? "checking" : item.status} /></div>;
              })}
            </div>
          </section>
        </div>
        <div hidden={section !== "runtime" && section !== "images"}>
          <InfrastructureSetup view={section === "images" ? "images" : "runtime"} distribution={distribution} onDistribution={changeDistribution} diagnosing={diagnosing || credentialBusy} onBusy={setDeploymentBusy} onDiagnose={diagnose} />
        </div>
        <div hidden={section !== "credentials"}><RuntimeCredentials disabled={deploymentBusy} refreshKey={refreshKey} onBusy={setCredentialBusy} onRuntime={() => setSection("runtime")} /></div>
        <div hidden={!["profiles", "adaptation", "resources"].includes(section)}><IntranetWorkbench distribution={distribution} section={companySection} /></div>
        {section === "runtime" && <details className="panel secondary-disclosure"><summary><ShieldCheck size={17} />{t("Security and execution model")}</summary><p>{t("Everything runs locally. The desktop app controls an isolated worker inside WSL2.")}</p><ul><li>{t("Agent network")}: {t("Provider endpoints from allowlist")}</li><li>{t("Grader network")}: {t("Offline")} · {t("Clean base + graded patch only")}</li><li>{t("Credentials")}: {t("Runtime-only")} · {t("Values redacted from all artifacts")}</li></ul></details>}
      </div>
    </div>
  </div>;
}

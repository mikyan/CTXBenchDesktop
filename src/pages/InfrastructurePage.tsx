import { Box, Check, Clipboard, Container, Copy, HardDrive, KeyRound, Network, RefreshCw, ServerCog, TerminalSquare } from "lucide-react";
import { useState } from "react";
import { DiagnosticIcon, PageTitle, StatusBadge } from "../components/shared";
import type { DiagnosticItem } from "../domain/types";
import { useI18n } from "../i18n";

export function InfrastructurePage({ diagnostics, onDiagnose, diagnosing }: { diagnostics: DiagnosticItem[]; onDiagnose: () => void; diagnosing: boolean }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
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
        actions={<button className="button primary" onClick={onDiagnose} disabled={diagnosing}><RefreshCw size={16} className={diagnosing ? "spin" : ""} /> {diagnosing ? t("Checking…") : t("Run diagnostics")}</button>}
      />

      <section className="infra-layout">
        <div className="panel diagnostics-panel">
          <div className="panel-header"><div><span className="panel-kicker">{t("READINESS")}</span><h2>{t("System checks")}</h2></div><StatusBadge status={diagnostics.every((item) => item.status === "healthy") ? "healthy" : "warning"} label={diagnostics.every((item) => item.status === "healthy") ? t("Ready") : t("Action needed")} /></div>
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
          <p>{t("Docker Engine is not available in the selected Ubuntu distribution. Install it explicitly, start the daemon, then run:")}</p>
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

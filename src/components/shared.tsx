import type { ReactNode } from "react";
import { CheckCircle2, CircleAlert, CircleDashed, CircleX, LoaderCircle } from "lucide-react";
import type { DiagnosticItem, ExperimentStatus, RunStatus } from "../domain/types";
import { useI18n } from "../i18n";
import { titleCase } from "../lib/format";

type StatusValue = ExperimentStatus | RunStatus | DiagnosticItem["status"] | "ready" | "generating" | "invalid" | "gold" | "silver";

const toneForStatus = (status: StatusValue): string => {
  if (["completed", "healthy", "ready", "gold"].includes(status)) return "success";
  if (["running", "preparing", "grading", "checking", "generating"].includes(status)) return "active";
  if (["failed", "missing", "invalid", "cancelled"].includes(status)) return "danger";
  if (["paused", "warning", "silver"].includes(status)) return "warning";
  return "neutral";
};

export function StatusBadge({ status, label }: { status: StatusValue; label?: string }) {
  const { t } = useI18n();
  const tone = toneForStatus(status);
  return (
    <span className={`status-badge ${tone}`}>
      <span className="status-dot" />
      {label ?? t(titleCase(status))}
    </span>
  );
}

export function DiagnosticIcon({ status }: { status: DiagnosticItem["status"] }) {
  if (status === "healthy") return <CheckCircle2 size={18} className="icon-success" />;
  if (status === "missing") return <CircleX size={18} className="icon-danger" />;
  if (status === "warning") return <CircleAlert size={18} className="icon-warning" />;
  return <LoaderCircle size={18} className="icon-active spin" />;
}

export function PageTitle({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-title">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function ProgressBar({ value, tone = "cyan" }: { value: number; tone?: "cyan" | "violet" | "green" | "red" }) {
  const { t } = useI18n();
  const bounded = Math.max(0, Math.min(1, value));
  return (
    <div className="progress-track" aria-label={t("{percent} percent", { percent: Math.round(bounded * 100) })}>
      <div className={`progress-fill ${tone}`} style={{ width: `${bounded * 100}%` }} />
    </div>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <CircleDashed size={28} />
      <strong>{title}</strong>
      <span>{body}</span>
    </div>
  );
}

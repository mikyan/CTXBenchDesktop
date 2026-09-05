import { BookOpenCheck, ChevronDown, Filter, GitPullRequestArrow, Search, ShieldCheck, ShieldX, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { PageTitle, StatusBadge } from "../components/shared";
import type { DashboardSnapshot } from "../domain/types";
import { useI18n } from "../i18n";
import { percent } from "../lib/format";

export function ConstraintsPage({ snapshot }: { snapshot: DashboardSnapshot }) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const constraints = useMemo(
    () => snapshot.constraints.filter((constraint) => `${constraint.repository} ${constraint.title}`.toLowerCase().includes(query.toLowerCase())),
    [query, snapshot.constraints],
  );
  const totalSatisfied = snapshot.constraints.reduce((sum, item) => sum + item.satisfied, 0);
  const totalViolated = snapshot.constraints.reduce((sum, item) => sum + item.violated, 0);

  return (
    <div className="page">
      <PageTitle
        eyebrow={t("SWE-SHIELD COMPATIBLE")}
        title={t("Design constraint compliance")}
        description={t("Mine decisions from review history, associate them with tasks, and judge patches independently from tests.")}
        actions={<button className="button primary"><Sparkles size={16} /> {t("Mine constraints")}</button>}
      />

      <section className="constraint-metrics">
        <div className="constraint-metric"><span className="round-icon green"><ShieldCheck size={18} /></span><div><span>{t("Design satisfaction")}</span><strong>{percent(snapshot.metrics.dsr)}</strong><small>{t("DSR · all judged issues")}</small></div></div>
        <div className="constraint-metric"><span className="round-icon red"><ShieldX size={18} /></span><div><span>{t("Design violation")}</span><strong>{percent(snapshot.metrics.dvr)}</strong><small>{t("DVR · all judged issues")}</small></div></div>
        <div className="constraint-metric"><span className="round-icon violet"><BookOpenCheck size={18} /></span><div><span>{t("Curated constraints")}</span><strong>{snapshot.constraints.length}</strong><small>{t("{gold} gold · {silver} silver", { gold: snapshot.constraints.filter((item) => item.quality === "gold").length, silver: snapshot.constraints.filter((item) => item.quality === "silver").length })}</small></div></div>
        <div className="constraint-metric"><span className="round-icon orange"><GitPullRequestArrow size={18} /></span><div><span>{t("Judged decisions")}</span><strong>{totalSatisfied + totalViolated}</strong><small>{t("3-vote research mode")}</small></div></div>
      </section>

      <section className="panel methodology-strip">
        <div><span>1</span><strong>{t("Mine")}</strong><small>{t("Review windows + adoption")}</small></div><i />
        <div><span>2</span><strong>{t("Cluster")}</strong><small>{t("Semantic + provenance")}</small></div><i />
        <div><span>3</span><strong>{t("Associate")}</strong><small>{t("Traceability + patch intent")}</small></div><i />
        <div><span>4</span><strong>{t("Judge")}</strong><small>{t("Applicability, then verdict")}</small></div>
      </section>

      <div className="toolbar">
        <label className="table-search"><Search size={15} /><input aria-label={t("Search constraints")} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search constraints")} /></label>
        <button className="button tertiary"><Filter size={15} /> {t("Repository")}</button>
        <button className="button tertiary">{t("All quality")} <ChevronDown size={14} /></button>
        <div className="toolbar-spacer" />
        <span className="result-count">{t("{count} constraints", { count: constraints.length })}</span>
      </div>

      <section className="panel constraints-table-panel">
        <table className="data-table constraints-table">
          <thead><tr><th>{t("Constraint")}</th><th>{t("Quality")}</th><th>{t("Applicable")}</th><th>{t("Satisfied")}</th><th>{t("Violated")}</th><th>{t("Provenance")}</th></tr></thead>
          <tbody>
            {constraints.map((constraint) => (
              <tr key={constraint.id}>
                <td><div className="constraint-title"><strong>{constraint.title}</strong><span>{constraint.repository}</span><p>{constraint.rationale}</p></div></td>
                <td><StatusBadge status={constraint.quality} /></td>
                <td className="mono">{constraint.applicableRuns}</td>
                <td><span className="score-cell green">{constraint.satisfied}</span></td>
                <td><span className="score-cell red">{constraint.violated}</span></td>
                <td><span className="provenance"><GitPullRequestArrow size={14} />{constraint.provenance}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

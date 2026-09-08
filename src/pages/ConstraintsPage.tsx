import { BookOpenCheck, ChevronDown, Filter, GitPullRequestArrow, Search, ShieldCheck, ShieldX, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { PageTitle, StatusBadge } from "../components/shared";
import type { DashboardSnapshot } from "../domain/types";
import { useI18n } from "../i18n";
import { percent } from "../lib/format";
import { PreparationQueue } from "../components/PreparationQueue";
import { SectionNav } from "../components/SectionNav";

export function ConstraintsPage({ snapshot, onMine }: { snapshot: DashboardSnapshot; onMine: () => void }) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"library" | "queue">("library");
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
        actions={<button className="button primary" onClick={onMine}><Sparkles size={16} /> {t("Mine constraints")}</button>}
      />

      <section className="constraint-metrics">
        <div className="constraint-metric"><span className="round-icon green"><ShieldCheck size={18} /></span><div><span>{t("Design satisfaction")}</span><strong>{snapshot.metrics.judgedRuns ? percent(snapshot.metrics.dsr) : "—"}</strong><small>{t("DSR · all judged issues")}</small></div></div>
        <div className="constraint-metric"><span className="round-icon red"><ShieldX size={18} /></span><div><span>{t("Design violation")}</span><strong>{snapshot.metrics.judgedRuns ? percent(snapshot.metrics.dvr) : "—"}</strong><small>{t("DVR · all judged issues")}</small></div></div>
        <div className="constraint-metric"><span className="round-icon violet"><BookOpenCheck size={18} /></span><div><span>{t("Curated constraints")}</span><strong>{snapshot.constraints.length}</strong><small>{t("{gold} gold · {silver} silver", { gold: snapshot.constraints.filter((item) => item.quality === "gold").length, silver: snapshot.constraints.filter((item) => item.quality === "silver").length })}</small></div></div>
        <div className="constraint-metric"><span className="round-icon orange"><GitPullRequestArrow size={18} /></span><div><span>{t("Judged decisions")}</span><strong>{totalSatisfied + totalViolated}</strong><small>{t("3-vote research mode")}</small></div></div>
      </section>
      <SectionNav label="Constraint views" items={[{ id: "library", label: "Constraint library" }, { id: "queue", label: "Mining queue" }]} value={view} onChange={setView} />
      <div hidden={view !== "queue"}><PreparationQueue operations={snapshot.operations ?? []} kind="constraints" /></div>
      <div hidden={view !== "library"}>

      <details className="secondary-disclosure"><summary>{t("Methodology and limitations")}</summary><section className="panel methodology-strip">
        <div><span>1</span><strong>{t("Mine")}</strong><small>{t("Review evidence + adoption")}</small></div><i />
        <div><span>2</span><strong>{t("Extract")}</strong><small>{t("Review evidence + adoption")}</small></div><i />
        <div><span>3</span><strong>{t("Freeze")}</strong><small>{t("Silver constraint package")}</small></div><i />
        <div><span>4</span><strong>{t("Judge")}</strong><small>{t("Applicability, then verdict")}</small></div>
      </section></details>

      <div className="toolbar">
        <label className="table-search"><Search size={15} /><input aria-label={t("Search constraints")} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search constraints")} /></label>
        <div className="toolbar-spacer" />
        <span className="result-count">{t("{count} constraints", { count: constraints.length })}</span>
      </div>

      <section className="panel constraints-table-panel">
        <div className="table-scroll"><table className="data-table constraints-table">
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
        </table></div>
        {!constraints.length && <p className="empty-state">{t("No matching constraints")}</p>}
      </section></div>
    </div>
  );
}

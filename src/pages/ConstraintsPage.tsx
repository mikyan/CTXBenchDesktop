import { BookOpenCheck, ChevronDown, Filter, GitPullRequestArrow, Search, ShieldCheck, ShieldX, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { PageTitle, StatusBadge } from "../components/shared";
import type { DashboardSnapshot } from "../domain/types";
import { percent } from "../lib/format";

export function ConstraintsPage({ snapshot }: { snapshot: DashboardSnapshot }) {
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
        eyebrow="SWE-SHIELD COMPATIBLE"
        title="Design constraint compliance"
        description="Mine decisions from review history, associate them with tasks, and judge patches independently from tests."
        actions={<button className="button primary"><Sparkles size={16} /> Mine constraints</button>}
      />

      <section className="constraint-metrics">
        <div className="constraint-metric"><span className="round-icon green"><ShieldCheck size={18} /></span><div><span>Design satisfaction</span><strong>{percent(snapshot.metrics.dsr)}</strong><small>DSR · all judged issues</small></div></div>
        <div className="constraint-metric"><span className="round-icon red"><ShieldX size={18} /></span><div><span>Design violation</span><strong>{percent(snapshot.metrics.dvr)}</strong><small>DVR · all judged issues</small></div></div>
        <div className="constraint-metric"><span className="round-icon violet"><BookOpenCheck size={18} /></span><div><span>Curated constraints</span><strong>{snapshot.constraints.length}</strong><small>{snapshot.constraints.filter((item) => item.quality === "gold").length} gold · {snapshot.constraints.filter((item) => item.quality === "silver").length} silver</small></div></div>
        <div className="constraint-metric"><span className="round-icon orange"><GitPullRequestArrow size={18} /></span><div><span>Judged decisions</span><strong>{totalSatisfied + totalViolated}</strong><small>3-vote research mode</small></div></div>
      </section>

      <section className="panel methodology-strip">
        <div><span>1</span><strong>Mine</strong><small>Review windows + adoption</small></div><i />
        <div><span>2</span><strong>Cluster</strong><small>Semantic + provenance</small></div><i />
        <div><span>3</span><strong>Associate</strong><small>Traceability + patch intent</small></div><i />
        <div><span>4</span><strong>Judge</strong><small>Applicability, then verdict</small></div>
      </section>

      <div className="toolbar">
        <label className="table-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search constraints" /></label>
        <button className="button tertiary"><Filter size={15} /> Repository</button>
        <button className="button tertiary">All quality <ChevronDown size={14} /></button>
        <div className="toolbar-spacer" />
        <span className="result-count">{constraints.length} constraints</span>
      </div>

      <section className="panel constraints-table-panel">
        <table className="data-table constraints-table">
          <thead><tr><th>Constraint</th><th>Quality</th><th>Applicable</th><th>Satisfied</th><th>Violated</th><th>Provenance</th></tr></thead>
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

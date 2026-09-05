import { Download, Filter, FlaskConical, MoreHorizontal, Pause, Play, Search, SquareStack, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { PageTitle, ProgressBar, StatusBadge } from "../components/shared";
import type { BenchmarkRun, DashboardSnapshot } from "../domain/types";
import { pairedComparisons } from "../domain/metrics";
import { signedPercent } from "../lib/format";
import { useI18n } from "../i18n";
import { relativeTime, titleCase } from "../lib/format";

export function ExperimentsPage({ snapshot, onNewExperiment, onExport, onImport, onAction, onRun }: { snapshot: DashboardSnapshot; onNewExperiment: () => void; onExport: (format: "json" | "csv" | "html") => void; onImport: () => void; onAction: (id: string, action: string) => void; onRun: (run: BenchmarkRun) => void }) {
  const { locale, t } = useI18n();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("");
  const selectedRuns = snapshot.runs.filter((run) => !selected || run.experimentId === selected);
  const filtered = useMemo(
    () => snapshot.experiments.filter((experiment) => `${experiment.name} ${experiment.dataset}`.toLowerCase().includes(query.toLowerCase())),
    [query, snapshot.experiments],
  );

  return (
    <div className="page">
      <PageTitle
        eyebrow={t("EXPERIMENTS")}
        title={t("Runs and comparisons")}
        description={t("Every context arm is paired against a frozen no-context baseline.")}
        actions={<><button className="button secondary" onClick={onImport}>{t("Import dataset")}</button><button type="button" className="button primary" onClick={onNewExperiment}><FlaskConical size={16} /> {t("New experiment")}</button></>}
      />

      <section className="subnav-stats">
        <div><span>{t("Active")}</span><strong>{snapshot.experiments.filter((item) => item.status === "running").length}</strong></div>
        <div><span>{t("Queued runs")}</span><strong>{snapshot.runs.filter((run) => run.status === "queued").length}</strong></div>
        <div><span>{t("Completed")}</span><strong>{snapshot.experiments.filter((item) => item.status === "completed").length}</strong></div>
        <div><span>{t("Imported datasets")}</span><strong>{snapshot.datasets?.length ?? 0}</strong></div>
      </section>

      <div className="toolbar">
        <label className="table-search"><Search size={15} /><input aria-label={t("Filter experiments")} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Filter experiments")} /></label>
        <div className="toolbar-spacer" />
        <button className="button tertiary" onClick={() => onExport("json")}><Download size={14} /> JSON</button>
        <button className="button tertiary" onClick={() => onExport("csv")}><Download size={14} /> CSV</button>
        <button className="button tertiary" onClick={() => onExport("html")}><Download size={14} /> {t("Report")}</button>
        <span className="result-count">{t("{count} experiments", { count: filtered.length })}</span>
      </div>

      <section className="experiment-list">
        {filtered.map((experiment) => {
          const progress = experiment.totalRuns === 0 ? 0 : experiment.completedRuns / experiment.totalRuns;
          return (
            <article className="experiment-row" key={experiment.id}>
              <div className={`benchmark-symbol ${experiment.benchmark}`}>
                {experiment.benchmark === "swebench" ? "SW" : experiment.benchmark === "ctxbench" ? "CX" : "CU"}
              </div>
              <div className="experiment-main">
                <div className="experiment-heading"><h3>{experiment.name}</h3><StatusBadge status={experiment.status} /></div>
                <div className="experiment-meta">
                  <span>{t(titleCase(experiment.benchmark))}</span><i />
                  <span>{experiment.model.provider}/{experiment.model.model}</span><i />
                  <span>{t("{tasks} tasks × {repeats}", { tasks: experiment.tasks, repeats: experiment.repeats })}</span><i />
                  <span>{t("seed {seed}", { seed: experiment.seed })}</span>
                </div>
                <div className="arm-list">
                  {experiment.arms.map((arm) => <span key={arm} className={arm === "none" ? "arm-tag none" : "arm-tag context"}>{t(titleCase(arm))}</span>)}
                </div>
              </div>
              <div className="experiment-progress-cell">
                <div><span>{t("{completed} / {total} runs", { completed: experiment.completedRuns, total: experiment.totalRuns })}</span><strong>{Math.round(progress * 100)}%</strong></div>
                <ProgressBar value={progress} tone={experiment.status === "paused" ? "violet" : "cyan"} />
                <small>{t("Updated {time}", { time: relativeTime(experiment.updatedAt, locale) })}</small>
              </div>
              <div className="experiment-actions">
                {["running", "preparing"].includes(experiment.status) ? <button className="icon-button" title={t("Pause after current stage")} onClick={() => onAction(experiment.id, "pause")}><Pause size={16} /></button> : ["ready", "paused"].includes(experiment.status) ? <button className="icon-button" title={t("Resume")} onClick={() => onAction(experiment.id, "resume")}><Play size={16} /></button> : ["failed", "cancelled"].includes(experiment.status) ? <button className="button tertiary" onClick={() => onAction(experiment.id, "retry")}>{t("Retry failed runs")}</button> : null}
                {["running", "preparing", "paused", "ready"].includes(experiment.status) && <button className="button tertiary" onClick={() => onAction(experiment.id, "cancel")}>{t("Cancel")}</button>}
                <button className="button tertiary" onClick={() => setSelected(experiment.id)}>{t("Results")}</button>
              </div>
            </article>
          );
        })}
      </section>

      {!filtered.length && <p className="empty-state">{t("No experiments yet. Import tasks, then create a paired experiment.")}</p>}
      <section className="panel workbench-results"><h2>{t("Run results and evidence")}</h2>
        <select value={selected} onChange={(e) => setSelected(e.target.value)}><option value="">{t("All experiments")}</option>{snapshot.experiments.map((experiment) => <option key={experiment.id} value={experiment.id}>{experiment.name}</option>)}</select>
        <p>{t("Real runs only; mock results are excluded.")}</p>
        {pairedComparisons(selectedRuns.filter((run) => !run.mock)).map((block) => <p key={`${block.experimentId}:${block.arm}`}>{snapshot.experiments.find((experiment) => experiment.id === block.experimentId)?.name} · {t(titleCase(block.arm))} · {block.pairs} {t("pairs")} / {block.taskCount} {t("Tasks")} · {t("Knowledge lift")} {signedPercent(block.lift)} · 95% CI {block.ci95 ? block.ci95.map((value) => signedPercent(value)).join(" … ") : t("More tasks needed")} · {t("Repeat variance")} {block.repeatVariance.toFixed(3)}</p>)}
        <div className="table-scroll"><table className="data-table"><thead><tr>{["Task", "Arm", "Status", "Tests", "Constraint", "Evidence"].map((label) => <th key={label}>{t(label)}</th>)}</tr></thead><tbody>{selectedRuns.map((run) => <tr key={run.id}><td>{run.taskId}{run.mock && <small> · MOCK</small>}</td><td>{t(titleCase(run.arm))} · {run.repeat}</td><td><StatusBadge status={run.status} /></td><td>{run.testsPassed === undefined ? "—" : run.testsPassed ? t("PASS") : t("FAIL")}</td><td>{run.constraintVerdict ? t(titleCase(run.constraintVerdict)) : t("Not judged")}</td><td><button className="text-button" onClick={() => onRun(run)}>{t("Details")}</button></td></tr>)}</tbody></table></div>
      </section>
      <section className="panel workbench-results"><h2>{t("Preparation queue")}</h2>{snapshot.operations?.map((operation) => <p key={operation.id}><code>{operation.id}</code> · {t(operation.kind)} · {t(titleCase(operation.status))}{operation.failure && <span className="form-error"> {operation.failure}</span>}</p>)}</section>

      <div className="integrity-strip">
        <SquareStack size={17} />
        <div><strong>{t("Pair integrity is enforced")}</strong><span>{t("Changing model, budget, image, prompt, network, or resources creates a new experiment block.")}</span></div>
        <TriangleAlert size={16} />
        <span>{t("Task-cluster bootstrap; repeated runs are not independent tasks.")}</span>
      </div>
    </div>
  );
}

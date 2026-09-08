import { Download, Filter, FlaskConical, MoreHorizontal, Pause, Play, Search, SquareStack, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { PageTitle, ProgressBar, StatusBadge } from "../components/shared";
import type { BenchmarkKind, BenchmarkRun, DashboardSnapshot } from "../domain/types";
import { pairedComparisons } from "../domain/metrics";
import { signedPercent } from "../lib/format";
import { useI18n } from "../i18n";
import { relativeTime, titleCase } from "../lib/format";
import { Pagination } from "../components/Pagination";
import { pageWindow } from "../domain/pagination";
import { TokenBudgets } from "../components/TokenBudgets";
import { benchmarkLabel } from "../lib/benchmark-labels";
import { SectionNav } from "../components/SectionNav";
import { experimentViews } from "../lib/navigation";

export function ExperimentsPage({ snapshot, onNewExperiment, onExport, onDatasets, onAction, onRun, initialBenchmark = "" }: { snapshot: DashboardSnapshot; onNewExperiment: () => void; onExport: (format: "json" | "csv" | "html") => void; onDatasets: () => void; initialBenchmark?: BenchmarkKind | ""; onAction: (id: string, action: string) => void; onRun: (run: BenchmarkRun) => void }) {
  const { locale, t } = useI18n();
  const [query, setQuery] = useState("");
  const [view, setView] = useState<typeof experimentViews[number]["id"]>(initialBenchmark ? "results" : "plans");
  const [benchmark, setBenchmark] = useState<BenchmarkKind | "">(initialBenchmark);
  const [exportFormat, setExportFormat] = useState<"json" | "csv" | "html">("html");
  const benchmarkExperiments = snapshot.experiments.filter((item) => !benchmark || item.benchmark === benchmark);
  const [selected, setSelected] = useState("");
  const [runQuery, setRunQuery] = useState("");
  const [runStatus, setRunStatus] = useState("");
  const [resultPage, setResultPage] = useState(0);
  const selectedRuns = snapshot.runs.filter((run) => (!selected || run.experimentId === selected) && benchmarkExperiments.some((item) => item.id === run.experimentId));
  const visibleRuns = selectedRuns.filter((run) => (!runStatus || run.status === runStatus) && `${run.taskId} ${run.repository}`.toLowerCase().includes(runQuery.toLowerCase()));
  const resultsWindow = pageWindow(visibleRuns.length, resultPage);
  const filtered = useMemo(
    () => snapshot.experiments.filter((experiment) => (!benchmark || experiment.benchmark === benchmark) && `${experiment.name} ${experiment.dataset}`.toLowerCase().includes(query.toLowerCase())),
    [query, snapshot.experiments, benchmark],
  );

  return (
    <div className="page">
      <PageTitle
        eyebrow={t("EXPERIMENTS")}
        title={t("Runs and comparisons")}
        description={t("Every context arm is paired against a frozen no-context baseline.")}
        actions={<><button className="button secondary" onClick={onDatasets}>{t("Manage datasets")}</button><button type="button" className="button primary" onClick={onNewExperiment}><FlaskConical size={16} /> {t("New experiment")}</button></>}
      />

      <section className="subnav-stats">
        <div><span>{t("Active")}</span><strong>{snapshot.experiments.filter((item) => item.status === "running").length}</strong></div>
        <div><span>{t("Queued runs")}</span><strong>{snapshot.runs.filter((run) => run.status === "queued").length}</strong></div>
        <div><span>{t("Completed")}</span><strong>{snapshot.experiments.filter((item) => item.status === "completed").length}</strong></div>
        <div><span>{t("Imported datasets")}</span><strong>{snapshot.datasets?.length ?? 0}</strong></div>
      </section>
      <SectionNav label="Experiment views" items={experimentViews} value={view} onChange={setView} />
      <div hidden={view === "budgets"} className="filter-bar"><label>{t("Benchmark filter")}<select value={benchmark} onChange={(e) => { setBenchmark(e.target.value as BenchmarkKind | ""); setSelected(""); setResultPage(0); }}><option value="">{t("All benchmarks")}</option>{(["ctxbench", "swebench", "custom"] as const).map((kind) => <option value={kind} key={kind}>{benchmarkLabel(kind, t)}</option>)}</select></label></div>
      <div hidden={view !== "budgets"}><TokenBudgets budgets={snapshot.tokenBudgets ?? []} /></div>
      <div hidden={view !== "plans"}>

      <div className="toolbar">
        <label className="table-search"><Search size={15} /><input aria-label={t("Filter experiments")} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Filter experiments")} /></label>
        <div className="toolbar-spacer" />
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
                  <span>{benchmarkLabel(experiment.benchmark, t)}</span><i />
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
                <button className="button tertiary" onClick={() => { setSelected(experiment.id); setResultPage(0); setView("results"); }}>{t("Results")}</button>
              </div>
            </article>
          );
        })}
      </section>

      {!filtered.length && <p className="empty-state">{t(snapshot.experiments.length ? "No matches. Change the search or benchmark filter." : "No experiments yet. Create or import a dataset, then create a paired experiment.")}</p>}
      </div><div hidden={view !== "results"}>
      <section className="panel workbench-results"><h2>{t("Run results and evidence")}</h2>
        <select aria-label={t("Select experiment")} value={selected} onChange={(e) => { setSelected(e.target.value); setResultPage(0); }}><option value="">{t("All experiments")}</option>{benchmarkExperiments.map((experiment) => <option key={experiment.id} value={experiment.id}>{experiment.name}</option>)}</select>
        <div className="toolbar"><label>{t("Filter runs")}<input value={runQuery} onChange={(e) => { setRunQuery(e.target.value); setResultPage(0); }} /></label><label>{t("Status")}<select value={runStatus} onChange={(e) => { setRunStatus(e.target.value); setResultPage(0); }}><option value="">{t("All statuses")}</option>{["queued", "running", "grading", "completed", "failed", "cancelled"].map((status) => <option key={status} value={status}>{t(titleCase(status))}</option>)}</select></label></div>
        <p>{t("Comparison statistics exclude mock runs; the table labels them explicitly.")}</p>
        <details className="comparison-details"><summary>{t("Knowledge impact")}</summary>
        {pairedComparisons(selectedRuns.filter((run) => !run.mock)).map((block) => <p key={`${block.experimentId}:${block.arm}`}>{snapshot.experiments.find((experiment) => experiment.id === block.experimentId)?.name} · {t(titleCase(block.arm))} · {block.pairs} {t("pairs")} / {block.taskCount} {t("Tasks")} · {t("Knowledge lift")} {signedPercent(block.lift, 1, locale)} · 95% CI {block.ci95 ? block.ci95.map((value) => signedPercent(value, 1, locale)).join(" … ") : t("More tasks needed")} · {t("Repeat variance")} {block.repeatVariance.toFixed(3)}</p>)}
        </details><div className="table-scroll"><table className="data-table"><thead><tr>{["Task", "Arm", "Status", "Tests", "Constraint", "Evidence"].map((label) => <th key={label}>{t(label)}</th>)}</tr></thead><tbody>{visibleRuns.slice(resultsWindow.start, resultsWindow.end).map((run) => <tr key={run.id}><td>{run.taskId}{run.mock && <small> · MOCK</small>}</td><td>{t(titleCase(run.arm))} · {run.repeat}</td><td><StatusBadge status={run.status} /></td><td>{run.testsPassed === undefined ? "—" : run.testsPassed ? t("PASS") : t("FAIL")}</td><td>{run.constraintVerdict ? t(titleCase(run.constraintVerdict)) : t("Not judged")}</td><td><button className="text-button" onClick={() => onRun(run)}>{t("Details")}</button></td></tr>)}</tbody></table></div>
        {!visibleRuns.length && <p className="empty-state">{t("No matching runs")}</p>}
        <Pagination total={visibleRuns.length} page={resultPage} onChange={setResultPage} />
      </section>
<div className="export-bar"><label>{t("Export all results")}<select value={exportFormat} onChange={(e) => setExportFormat(e.target.value as typeof exportFormat)}><option value="html">HTML</option><option value="csv">CSV</option><option value="json">JSON</option></select></label><button className="button secondary" onClick={() => onExport(exportFormat)}><Download size={16} />{t("Export all results")}</button><small>{t("Results are filtered below; exports include the entire workspace.")}</small></div>
      </div>

      <details className="secondary-disclosure"><summary>{t("Pair integrity is enforced")}</summary><div className="integrity-strip">
        <SquareStack size={17} />
        <div><strong>{t("Pair integrity is enforced")}</strong><span>{t("Changing model, budget, image, prompt, network, or resources creates a new experiment block.")}</span></div>
        <TriangleAlert size={16} />
        <span>{t("Task-cluster bootstrap; repeated runs are not independent tasks.")}</span>
      </div></details>
    </div>
  );
}

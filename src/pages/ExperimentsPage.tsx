import { Download, Filter, FlaskConical, MoreHorizontal, Pause, Play, Search, SquareStack, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { PageTitle, ProgressBar, StatusBadge } from "../components/shared";
import type { DashboardSnapshot } from "../domain/types";
import { useI18n } from "../i18n";
import { relativeTime, titleCase } from "../lib/format";

export function ExperimentsPage({ snapshot, onNewExperiment, onExport }: { snapshot: DashboardSnapshot; onNewExperiment: () => void; onExport: (format: "json" | "csv" | "html") => void }) {
  const { locale, t } = useI18n();
  const [query, setQuery] = useState("");
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
        actions={<button type="button" className="button primary" onClick={onNewExperiment}><FlaskConical size={16} /> {t("New experiment")}</button>}
      />

      <section className="subnav-stats">
        <div><span>{t("Active")}</span><strong>{snapshot.experiments.filter((item) => item.status === "running").length}</strong></div>
        <div><span>{t("Queued runs")}</span><strong>56</strong></div>
        <div><span>{t("Completed")}</span><strong>{snapshot.experiments.filter((item) => item.status === "completed").length}</strong></div>
        <div><span>{t("Paired coverage")}</span><strong>100%</strong></div>
      </section>

      <div className="toolbar">
        <label className="table-search"><Search size={15} /><input aria-label={t("Filter experiments")} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Filter experiments")} /></label>
        <button className="button tertiary"><Filter size={15} /> {t("Filter")}</button>
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
                {experiment.status === "running" ? <button className="icon-button" title={t("Pause")}><Pause size={16} /></button> : <button className="icon-button" title={t("Resume")}><Play size={16} /></button>}
                <button className="icon-button"><MoreHorizontal size={17} /></button>
              </div>
            </article>
          );
        })}
      </section>

      <div className="integrity-strip">
        <SquareStack size={17} />
        <div><strong>{t("Pair integrity is enforced")}</strong><span>{t("Changing model, budget, image, prompt, network, or resources creates a new experiment block.")}</span></div>
        <TriangleAlert size={16} />
        <span>{t("{count} confounded pairs", { count: 0 })}</span>
      </div>
    </div>
  );
}

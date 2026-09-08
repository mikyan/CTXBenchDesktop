import {
  ArrowUpRight,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  DatabaseZap,
  FlaskConical,
  MoreHorizontal,
  Play,
  ShieldAlert,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import type { BenchmarkKind, BenchmarkRun, DashboardSnapshot } from "../domain/types";
import { useState } from "react";
import { aggregateArms, aggregateDashboard } from "../domain/metrics";
import { useI18n } from "../i18n";
import { duration, money, percent, relativeTime, signedPercent, titleCase } from "../lib/format";
import { PageTitle, ProgressBar, StatusBadge } from "../components/shared";
import { benchmarkLabel } from "../lib/benchmark-labels";

export function DashboardPage({
  snapshot,
  onNewExperiment,
  onOpenExperiments,
  onRun,
}: {
  snapshot: DashboardSnapshot;
  onNewExperiment: () => void;
  onOpenExperiments: (benchmark?: BenchmarkKind) => void;
  onRun: (run: BenchmarkRun) => void;
}) {
  const { locale, t } = useI18n();
  const [block, setBlock] = useState("");
  const [chosenArm, setChosenArm] = useState("");
  const blockRuns = snapshot.runs.filter((run) => !run.mock && (!block || run.experimentId === block));
  const contextArms = [...new Set(blockRuns.filter((run) => run.arm !== "none").map((run) => run.arm))];
  const selectedArm = contextArms.find((arm) => arm === chosenArm) ?? contextArms[0];
  const eligibleExperiments = new Set(blockRuns.filter((run) => run.arm === selectedArm).map((run) => run.experimentId));
  const runs = selectedArm ? blockRuns.filter((run) => eligibleExperiments.has(run.experimentId) && (run.arm === "none" || run.arm === selectedArm)) : blockRuns;
  const metrics = aggregateDashboard(runs);
  const armMetrics = aggregateArms(runs);
  const pairCount = metrics.pairedWins + metrics.pairedLosses + metrics.pairedTies;
  const active = snapshot.experiments.find((experiment) => ["preparing", "running"].includes(experiment.status));
  const baseline = armMetrics.find((item) => item.arm === "none");
  const context = armMetrics.find((item) => item.arm !== "none");
  const live = snapshot.runs.find((run) => run.experimentId === active?.id && ["running", "grading", "preparing"].includes(run.status));
  const armRate = (arm: string, passing: boolean) => {
    const judged = runs.filter((run) => run.arm === arm && run.status === "completed" && run.constraintVerdict !== undefined);
    return judged.length ? judged.filter((run) => run.constraintVerdict === "satisfied" && (!passing || run.testsPassed)).length / judged.length : undefined;
  };

  return (
    <div className="page dashboard-page">
      <PageTitle
        eyebrow={t("BENCHMARK LAB")}
        title={t("Experiment overview")}
        description={t("Paired coding-agent evaluation, from frozen context to constraint-aware verdicts.")}
        actions={
          <>
            <button type="button" className="button secondary" onClick={() => onOpenExperiments()}>{t("View all runs")}</button>
            <button type="button" className="button primary" onClick={onNewExperiment}>
              <FlaskConical size={16} /> {t("New experiment")}
            </button>
          </>
        }
      />

      <section className="coverage-grid" aria-label={t("Benchmark coverage")}>{(["ctxbench", "swebench", "custom"] as const).map((kind) => {
        const ids = new Set(snapshot.experiments.filter((item) => item.benchmark === kind).map((item) => item.id));
        const graded = snapshot.runs.filter((run) => ids.has(run.experimentId) && !run.mock && run.status === "completed" && typeof run.testsPassed === "boolean");
        return <button key={kind} className="coverage-card" onClick={() => onOpenExperiments(kind)}><span>{benchmarkLabel(kind, t)}</span><strong>{graded.length}</strong><small>{t(graded.length ? "Real graded runs" : "No real grades yet")}</small><ArrowUpRight size={17} /></button>;
      })}</section><p className="coverage-note">{t("Coverage counts completed non-mock grades, not full-suite certification.")}</p>
      <div className="dashboard-filters">
      <div className="toolbar"><label>{t("Comparison block")} <select value={block} onChange={(event) => setBlock(event.target.value)}><option value="">{t("All real experiments")}</option>{snapshot.experiments.filter((item) => item.model.provider !== "mock").map((item) => <option value={item.id} key={item.id}>{item.name} · {item.model.model}</option>)}</select></label><span className="muted">{t("Real runs only; mock results are excluded.")}</span></div>
      {contextArms.length > 0 && <div className="toolbar"><label>{t("Comparison arm")} <select value={selectedArm} onChange={(event) => setChosenArm(event.target.value)}>{contextArms.map((arm) => <option key={arm} value={arm}>{t(titleCase(arm))}</option>)}</select></label></div>}
      </div>
      <section className="metric-grid" aria-label={t("Benchmark summary")}>
        <MetricCard
          label={t("Functional pass rate")}
          value={metrics.totalRuns ? percent(metrics.passRate) : "—"}
          detail={t("{count} graded runs", { count: metrics.totalRuns })}
          trend=""
          icon={<CheckCircle2 size={17} />}
          tone="green"
          spark={[]}
        />
        <MetricCard
          label={t("Knowledge lift")}
          value={pairCount ? signedPercent(metrics.knowledgeLift, 1, locale) : "—"}
          detail={t("context vs none")}
          trend={`${metrics.pairedWins}W / ${metrics.pairedLosses}L`}
          icon={<TrendingUp size={17} />}
          tone="cyan"
          spark={[]}
        />
        <MetricCard
          label={t("Pass-patch violations")}
          value={metrics.passingApplicable ? percent(metrics.passPatchViolationRate) : "—"}
          detail={t("PPVR · applicable runs")}
          trend=""
          icon={<ShieldAlert size={17} />}
          tone="orange"
          spark={[]}
        />
        <MetricCard
          label={t("Average run cost")}
          value={runs.some((run) => run.status === "completed" && typeof run.costUsd === "number") ? money(metrics.avgCostUsd, locale) : "—"}
          detail={t("Provider-reported · solver only")}
          trend=""
          icon={<CircleDollarSign size={17} />}
          tone="violet"
          spark={[]}
        />
      </section>

      <section className="dashboard-grid">
        <div className="panel impact-panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">{t("PAIRED EFFECT")}</span>
              <h2>{t("Knowledge impact")}</h2>
            </div>
            <div className="legend">
              <span><i className="legend-dot baseline" />{t("No context")}</span>
              <span><i className="legend-dot context" />{selectedArm ? t(titleCase(selectedArm)) : t("Context")}</span>
            </div>
          </div>
          <div className="impact-summary">
            <div>
              <strong>{pairCount ? signedPercent(metrics.knowledgeLift, 1, locale) : "—"}</strong>
              <span>{t("absolute pass-rate lift")}</span>
            </div>
            <div className="win-chip"><Sparkles size={14} /> {t("Context wins {wins} of {pairs} pairs", { wins: metrics.pairedWins, pairs: metrics.pairedWins + metrics.pairedLosses + metrics.pairedTies })}</div>
          </div>
          <div className="bar-chart">
            <BarGroup label={t("Tests passed")} first={baseline?.passRate} second={context?.passRate} />
            <BarGroup label={t("Constraints satisfied")} first={armRate("none", false)} second={armRate(context?.arm ?? "skill-generated", false)} />
            <BarGroup label={t("Pass & satisfied")} first={armRate("none", true)} second={armRate(context?.arm ?? "skill-generated", true)} />
          </div>
          <div className="chart-axis"><span>0</span><span>25</span><span>50</span><span>75</span><span>100%</span></div>
        </div>

        <div className="panel active-panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">{t("ACTIVE EXPERIMENT")}</span>
              <h2>{active?.name ?? t("No active experiment")}</h2>
            </div>
            {active && <StatusBadge status={active.status} />}
          </div>
          {active && (
            <>
              <div className="experiment-progress">
                <div className="progress-copy">
                  <strong>{active.completedRuns} <span>/ {active.totalRuns}</span></strong>
                  <em>{active.totalRuns ? Math.round((active.completedRuns / active.totalRuns) * 100) : 0}%</em>
                </div>
                <ProgressBar value={active.totalRuns ? active.completedRuns / active.totalRuns : 0} />
              </div>
              <div className="run-stage-grid">
                <Stage value={String(active.tasks)} label={t("Tasks")} />
                <Stage value={`${active.repeats}×`} label={t("Repeats")} />
                <Stage value={String(active.arms.length)} label={t("Arms")} />
                <Stage value="—" label={t("ETA")} />
              </div>
              <div className="live-run">
                <div className="live-icon"><Play size={14} fill="currentColor" /></div>
                <div>
                  <strong>{live?.taskId ?? t("Preparing")}</strong>
                  <span>{live ? `${t(titleCase(live.arm))} · ${t(titleCase(live.status))}` : "—"}</span>
                </div>
                <Clock3 size={15} />
                <time>{duration(live?.durationSeconds, locale)}</time>
              </div>
              <button type="button" className="button panel-button" onClick={() => onOpenExperiments()}>
                {t("Open experiment")} <ArrowUpRight size={15} />
              </button>
            </>
          )}
        </div>

        <div className="panel results-panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">{t("LATEST VERDICTS")}</span>
              <h2>{t("Recent runs")}</h2>
            </div>
            <button type="button" className="text-button" onClick={() => onOpenExperiments()}>{t("All results")} <ArrowUpRight size={14} /></button>
          </div>
          <div className="compact-table-wrap">
            <table className="data-table compact">
              <thead>
                <tr><th>{t("Task")}</th><th>{t("Arm")}</th><th>{t("Tests")}</th><th>{t("Constraint")}</th><th>{t("Time")}</th><th /></tr>
              </thead>
              <tbody>
                {[...runs].filter((run) => run.status !== "queued").sort((a, b) => (b.updatedAt ?? "").localeCompare(a.updatedAt ?? "")).slice(0, 6).map((run) => (
                  <tr key={run.id}>
                    <td>
                      <div className="primary-cell"><strong>{run.taskId.split("__").at(-1)}</strong><span>{run.repository}</span></div>
                    </td>
                    <td><span className={`arm-tag ${run.arm === "none" ? "none" : "context"}`}>{t(run.arm === "none" ? "None" : "Context")}</span></td>
                    <td><span className={`result-mark ${run.testsPassed === undefined ? "" : run.testsPassed ? "pass" : "fail"}`}>{run.testsPassed === undefined ? "—" : t(run.testsPassed ? "PASS" : "FAIL")}</span></td>
                    <td><span className={`verdict ${run.constraintVerdict}`}>{run.constraintVerdict ? t(titleCase(run.constraintVerdict)) : t("Not judged")}</span></td>
                    <td className="mono muted">{duration(run.durationSeconds, locale)}</td>
                    <td><button className="row-menu" aria-label={t("Run actions")} onClick={() => onRun(run)}><MoreHorizontal size={16} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel shield-panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">{t("SWE-SHIELD LAYER")}</span>
              <h2>{t("Design compliance")}</h2>
            </div>
            <ShieldAlert size={19} className="icon-orange" />
          </div>
          <div className="shield-body">
            <div className="donut" style={{ "--satisfied": `${metrics.dsr * 100}%`, "--violated": `${(metrics.dsr + metrics.dvr) * 100}%` } as React.CSSProperties}>
              <div><strong>{metrics.judgedRuns ? percent(metrics.dsr, 0) : "—"}</strong><span>DSR</span></div>
            </div>
            <div className="shield-stats">
              <ShieldStat color="green" label={t("Satisfied")} value={metrics.judgedRuns ? metrics.dsr : undefined} />
              <ShieldStat color="red" label={t("Violated")} value={metrics.judgedRuns ? metrics.dvr : undefined} />
              <ShieldStat color="slate" label={t("Neutral")} value={metrics.judgedRuns ? metrics.dnr : undefined} />
            </div>
          </div>
          <p className="panel-note">{t("Three-judge majority on applicable design constraints. Functional tests remain a separate axis.")}</p>
        </div>

        <div className="panel activity-panel">
          <div className="panel-header">
            <div><span className="panel-kicker">{t("WORKER STREAM")}</span><h2>{t("Activity")}</h2></div>
            <span className="live-label"><i /> {t("LIVE")}</span>
          </div>
          <div className="activity-list">
            {snapshot.activity.slice(0, 4).map((item) => (
              <div className="activity-row" key={item.id}>
                <div className={`activity-icon ${item.kind}`}>
                  {item.kind === "artifact" ? <DatabaseZap size={14} /> : item.kind === "constraint" ? <ShieldAlert size={14} /> : <CheckCircle2 size={14} />}
                </div>
                <div><strong>{t(item.message)}</strong><span>{t(item.detail)}</span></div>
                <time>{relativeTime(item.timestamp, locale)}</time>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

function MetricCard({ label, value, detail, trend, icon, tone, spark }: {
  label: string; value: string; detail: string; trend: string; icon: React.ReactNode; tone: string; spark: number[];
}) {
  const points = spark.map((value, index) => `${index * 18},${54 - value}`).join(" ");
  return (
    <div className={`metric-card ${tone}`}>
      <div className="metric-label"><span className="metric-icon">{icon}</span>{label}</div>
      <div className="metric-content"><strong>{value}</strong>{spark.length > 1 && <Sparkline points={points} />}</div>
      <div className="metric-footer"><span>{detail}</span><em>{trend}</em></div>
    </div>
  );
}

function Sparkline({ points }: { points: string }) {
  const { t } = useI18n();
  return (
    <svg className="sparkline" viewBox="0 0 110 46" role="img" aria-label={t("Trend")}>
      <defs><linearGradient id="sparkFade" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="currentColor" stopOpacity=".28"/><stop offset="100%" stopColor="currentColor" stopOpacity="0"/></linearGradient></defs>
      <polyline points={`${points} 108,46 0,46`} fill="url(#sparkFade)" stroke="none" />
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function BarGroup({ label, first, second }: { label: string; first?: number; second?: number }) {
  return (
    <div className="bar-group">
      <span>{label}</span>
      <div className="bars">
        <div className="bar baseline" style={{ width: `${(first ?? 0) * 100}%` }}><em>{first === undefined ? "—" : percent(first, 0)}</em></div>
        <div className="bar context" style={{ width: `${(second ?? 0) * 100}%` }}><em>{second === undefined ? "—" : percent(second, 0)}</em></div>
      </div>
    </div>
  );
}

function Stage({ value, label }: { value: string; label: string }) {
  return <div><strong>{value}</strong><span>{label}</span></div>;
}

function ShieldStat({ color, label, value }: { color: string; label: string; value?: number }) {
  return <div><i className={color} /><span>{label}</span><strong>{value === undefined ? "—" : percent(value, 0)}</strong></div>;
}

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
import type { DashboardSnapshot } from "../domain/types";
import { duration, money, percent, relativeTime, signedPercent, titleCase } from "../lib/format";
import { PageTitle, ProgressBar, StatusBadge } from "../components/shared";

export function DashboardPage({
  snapshot,
  onNewExperiment,
  onOpenExperiments,
}: {
  snapshot: DashboardSnapshot;
  onNewExperiment: () => void;
  onOpenExperiments: () => void;
}) {
  const { metrics } = snapshot;
  const active = snapshot.experiments.find((experiment) => experiment.status === "running");
  const baseline = snapshot.armMetrics.find((item) => item.arm === "none");
  const context = snapshot.armMetrics.find((item) => item.arm === "skill-generated");

  return (
    <div className="page dashboard-page">
      <PageTitle
        eyebrow="BENCHMARK LAB"
        title="Experiment overview"
        description="Paired coding-agent evaluation, from frozen context to constraint-aware verdicts."
        actions={
          <>
            <button type="button" className="button secondary" onClick={onOpenExperiments}>View all runs</button>
            <button type="button" className="button primary" onClick={onNewExperiment}>
              <FlaskConical size={16} /> New experiment
            </button>
          </>
        }
      />

      <section className="metric-grid" aria-label="Benchmark summary">
        <MetricCard
          label="Functional pass rate"
          value={percent(metrics.passRate)}
          detail={`${metrics.totalRuns} graded runs`}
          trend="+4.8 pp"
          icon={<CheckCircle2 size={17} />}
          tone="green"
          spark={[42, 47, 45, 53, 58, 61, 63]}
        />
        <MetricCard
          label="Knowledge lift"
          value={signedPercent(metrics.knowledgeLift)}
          detail="context vs none"
          trend={`${metrics.pairedWins}W / ${metrics.pairedLosses}L`}
          icon={<TrendingUp size={17} />}
          tone="cyan"
          spark={[12, 18, 15, 24, 31, 28, 38]}
        />
        <MetricCard
          label="Pass-patch violations"
          value={percent(metrics.passPatchViolationRate)}
          detail="PPVR · applicable runs"
          trend="−2.1 pp"
          icon={<ShieldAlert size={17} />}
          tone="orange"
          spark={[40, 37, 42, 33, 31, 29, 26]}
        />
        <MetricCard
          label="Average run cost"
          value={money(metrics.avgCostUsd)}
          detail="solver only"
          trend="−$0.07"
          icon={<CircleDollarSign size={17} />}
          tone="violet"
          spark={[50, 49, 44, 46, 39, 38, 36]}
        />
      </section>

      <section className="dashboard-grid">
        <div className="panel impact-panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">PAIRED EFFECT</span>
              <h2>Knowledge impact</h2>
            </div>
            <div className="legend">
              <span><i className="legend-dot baseline" />No context</span>
              <span><i className="legend-dot context" />Generated</span>
            </div>
          </div>
          <div className="impact-summary">
            <div>
              <strong>{signedPercent(metrics.knowledgeLift)}</strong>
              <span>absolute pass-rate lift</span>
            </div>
            <div className="win-chip"><Sparkles size={14} /> Context wins {metrics.pairedWins} of {metrics.pairedWins + metrics.pairedLosses + metrics.pairedTies} pairs</div>
          </div>
          <div className="bar-chart">
            <BarGroup label="Tests passed" first={baseline?.passRate ?? 0} second={context?.passRate ?? 0} />
            <BarGroup label="Constraints satisfied" first={0.69} second={0.82} />
            <BarGroup label="Patch accepted" first={0.44} second={0.63} />
          </div>
          <div className="chart-axis"><span>0</span><span>25</span><span>50</span><span>75</span><span>100%</span></div>
        </div>

        <div className="panel active-panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">ACTIVE EXPERIMENT</span>
              <h2>{active?.name ?? "No active experiment"}</h2>
            </div>
            {active && <StatusBadge status={active.status} />}
          </div>
          {active && (
            <>
              <div className="experiment-progress">
                <div className="progress-copy">
                  <strong>{active.completedRuns} <span>/ {active.totalRuns}</span></strong>
                  <em>{Math.round((active.completedRuns / active.totalRuns) * 100)}%</em>
                </div>
                <ProgressBar value={active.completedRuns / active.totalRuns} />
              </div>
              <div className="run-stage-grid">
                <Stage value="24" label="Tasks" />
                <Stage value={`${active.repeats}×`} label="Repeats" />
                <Stage value="2" label="Arms" />
                <Stage value="~38m" label="ETA" />
              </div>
              <div className="live-run">
                <div className="live-icon"><Play size={14} fill="currentColor" /></div>
                <div>
                  <strong>sympy__sympy-20590</strong>
                  <span>skill-generated · grading patch offline</span>
                </div>
                <Clock3 size={15} />
                <time>08:41</time>
              </div>
              <button type="button" className="button panel-button" onClick={onOpenExperiments}>
                Open experiment <ArrowUpRight size={15} />
              </button>
            </>
          )}
        </div>

        <div className="panel results-panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">LATEST VERDICTS</span>
              <h2>Recent runs</h2>
            </div>
            <button type="button" className="text-button" onClick={onOpenExperiments}>All results <ArrowUpRight size={14} /></button>
          </div>
          <div className="compact-table-wrap">
            <table className="data-table compact">
              <thead>
                <tr><th>Task</th><th>Arm</th><th>Tests</th><th>Constraint</th><th>Time</th><th /></tr>
              </thead>
              <tbody>
                {[...snapshot.runs].reverse().slice(0, 6).map((run) => (
                  <tr key={run.id}>
                    <td>
                      <div className="primary-cell"><strong>{run.taskId.split("__").at(-1)}</strong><span>{run.repository}</span></div>
                    </td>
                    <td><span className={`arm-tag ${run.arm === "none" ? "none" : "context"}`}>{run.arm === "none" ? "None" : "Context"}</span></td>
                    <td><span className={`result-mark ${run.testsPassed ? "pass" : "fail"}`}>{run.testsPassed ? "PASS" : "FAIL"}</span></td>
                    <td><span className={`verdict ${run.constraintVerdict}`}>{titleCase(run.constraintVerdict ?? "neutral")}</span></td>
                    <td className="mono muted">{duration(run.durationSeconds)}</td>
                    <td><button className="row-menu" aria-label="Run actions"><MoreHorizontal size={16} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel shield-panel">
          <div className="panel-header">
            <div>
              <span className="panel-kicker">SWE-SHIELD LAYER</span>
              <h2>Design compliance</h2>
            </div>
            <ShieldAlert size={19} className="icon-orange" />
          </div>
          <div className="shield-body">
            <div className="donut" style={{ "--satisfied": `${metrics.dsr * 100}%`, "--violated": `${(metrics.dsr + metrics.dvr) * 100}%` } as React.CSSProperties}>
              <div><strong>{percent(metrics.dsr, 0)}</strong><span>DSR</span></div>
            </div>
            <div className="shield-stats">
              <ShieldStat color="green" label="Satisfied" value={metrics.dsr} />
              <ShieldStat color="red" label="Violated" value={metrics.dvr} />
              <ShieldStat color="slate" label="Neutral" value={metrics.dnr} />
            </div>
          </div>
          <p className="panel-note">Three-judge majority on applicable design constraints. Functional tests remain a separate axis.</p>
        </div>

        <div className="panel activity-panel">
          <div className="panel-header">
            <div><span className="panel-kicker">WORKER STREAM</span><h2>Activity</h2></div>
            <span className="live-label"><i /> LIVE</span>
          </div>
          <div className="activity-list">
            {snapshot.activity.slice(0, 4).map((item) => (
              <div className="activity-row" key={item.id}>
                <div className={`activity-icon ${item.kind}`}>
                  {item.kind === "artifact" ? <DatabaseZap size={14} /> : item.kind === "constraint" ? <ShieldAlert size={14} /> : <CheckCircle2 size={14} />}
                </div>
                <div><strong>{item.message}</strong><span>{item.detail}</span></div>
                <time>{relativeTime(item.timestamp)}</time>
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
      <div className="metric-content"><strong>{value}</strong><Sparkline points={points} /></div>
      <div className="metric-footer"><span>{detail}</span><em>{trend}</em></div>
    </div>
  );
}

function Sparkline({ points }: { points: string }) {
  return (
    <svg className="sparkline" viewBox="0 0 110 46" role="img" aria-label="Trend">
      <defs><linearGradient id="sparkFade" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="currentColor" stopOpacity=".28"/><stop offset="100%" stopColor="currentColor" stopOpacity="0"/></linearGradient></defs>
      <polyline points={`${points} 108,46 0,46`} fill="url(#sparkFade)" stroke="none" />
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function BarGroup({ label, first, second }: { label: string; first: number; second: number }) {
  return (
    <div className="bar-group">
      <span>{label}</span>
      <div className="bars">
        <div className="bar baseline" style={{ width: `${first * 100}%` }}><em>{percent(first, 0)}</em></div>
        <div className="bar context" style={{ width: `${second * 100}%` }}><em>{percent(second, 0)}</em></div>
      </div>
    </div>
  );
}

function Stage({ value, label }: { value: string; label: string }) {
  return <div><strong>{value}</strong><span>{label}</span></div>;
}

function ShieldStat({ color, label, value }: { color: string; label: string; value: number }) {
  return <div><i className={color} /><span>{label}</span><strong>{percent(value, 0)}</strong></div>;
}

import type {
  ArmMetric,
  BenchmarkRun,
  ConstraintVerdict,
  ContextArm,
  DashboardMetrics,
} from "./types";

const rate = (value: number, total: number): number => (total === 0 ? 0 : value / total);
const average = (values: number[]): number =>
  values.length === 0 ? 0 : values.reduce((sum, value) => sum + value, 0) / values.length;

export function aggregateArms(runs: BenchmarkRun[]): ArmMetric[] {
  const completed = runs.filter((run) => run.status === "completed");
  const arms = Array.from(new Set(completed.map((run) => run.arm)));
  return arms.map((arm) => {
    const selected = completed.filter((run) => run.arm === arm);
    const applicable = selected.filter((run) => run.constraintVerdict !== "neutral");
    return {
      arm,
      runs: selected.length,
      passRate: rate(selected.filter((run) => run.testsPassed).length, selected.length),
      passCount: selected.filter((run) => run.testsPassed).length,
      violationRate: rate(
        applicable.filter((run) => run.constraintVerdict === "violated").length,
        applicable.length,
      ),
      avgDurationSeconds: average(selected.flatMap((run) => run.durationSeconds ?? [])),
      avgCostUsd: average(selected.flatMap((run) => run.costUsd ?? [])),
    };
  });
}

function pairedOutcome(runs: BenchmarkRun[]): Pick<DashboardMetrics, "pairedWins" | "pairedLosses" | "pairedTies"> {
  const groups = new Map<string, BenchmarkRun[]>();
  for (const run of runs.filter((item) => item.status === "completed")) {
    groups.set(run.pairId, [...(groups.get(run.pairId) ?? []), run]);
  }

  let pairedWins = 0;
  let pairedLosses = 0;
  let pairedTies = 0;
  for (const group of groups.values()) {
    const baseline = group.find((run) => run.arm === "none");
    if (!baseline) continue;
    for (const context of group.filter((run) => run.arm !== "none")) {
      if (context.testsPassed === baseline.testsPassed) pairedTies += 1;
      else if (context.testsPassed) pairedWins += 1;
      else pairedLosses += 1;
    }
  }
  return { pairedWins, pairedLosses, pairedTies };
}

function verdictCount(runs: BenchmarkRun[], verdict: ConstraintVerdict): number {
  return runs.filter((run) => run.constraintVerdict === verdict).length;
}

export function aggregateDashboard(runs: BenchmarkRun[]): DashboardMetrics {
  const completed = runs.filter((run) => run.status === "completed");
  const baseline = completed.filter((run) => run.arm === "none");
  const context = completed.filter((run) => run.arm !== "none");
  const applicablePassing = completed.filter(
    (run) => run.testsPassed && run.constraintVerdict !== "neutral",
  );
  const armMetrics = aggregateArms(completed);
  const baselinePass = rate(baseline.filter((run) => run.testsPassed).length, baseline.length);
  const contextPass = rate(context.filter((run) => run.testsPassed).length, context.length);

  return {
    totalRuns: completed.length,
    passRate: rate(completed.filter((run) => run.testsPassed).length, completed.length),
    knowledgeLift: contextPass - baselinePass,
    passPatchViolationRate: rate(
      applicablePassing.filter((run) => run.constraintVerdict === "violated").length,
      applicablePassing.length,
    ),
    avgCostUsd: average(completed.flatMap((run) => run.costUsd ?? [])),
    ...pairedOutcome(completed),
    dsr: rate(verdictCount(completed, "satisfied"), completed.length),
    dvr: rate(verdictCount(completed, "violated"), completed.length),
    dnr: rate(verdictCount(completed, "neutral"), completed.length),
  };
}

export function metricForArm(metrics: ArmMetric[], arm: ContextArm): ArmMetric | undefined {
  return metrics.find((metric) => metric.arm === arm);
}

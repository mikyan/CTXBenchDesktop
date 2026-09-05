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
  const completed = runs.filter((run) => typeof run.testsPassed === "boolean");
  const arms = Array.from(new Set(completed.map((run) => run.arm)));
  return arms.map((arm) => {
    const selected = completed.filter((run) => run.arm === arm);
    const applicable = selected.filter((run) => run.constraintVerdict === "satisfied" || run.constraintVerdict === "violated");
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
  for (const run of runs.filter((item) => typeof item.testsPassed === "boolean")) {
    const key = `${run.experimentId}:${run.pairId}`;
    groups.set(key, [...(groups.get(key) ?? []), run]);
  }

  let pairedWins = 0;
  let pairedLosses = 0;
  let pairedTies = 0;
  for (const group of groups.values()) {
    const baseline = group.find((run) => run.arm === "none");
    if (!baseline) continue;
    for (const context of group.filter((run) => run.arm !== "none")) {
      if (!baseline.pairingHash || context.pairingHash !== baseline.pairingHash || context.mock !== baseline.mock) continue;
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
  const completed = runs.filter((run) => typeof run.testsPassed === "boolean");
  const applicablePassing = completed.filter(
    (run) => run.testsPassed && (run.constraintVerdict === "satisfied" || run.constraintVerdict === "violated"),
  );
  const judged = completed.filter((run) => run.constraintVerdict !== undefined);
  const paired = pairedOutcome(completed);

  return {
    totalRuns: completed.length,
    passRate: rate(completed.filter((run) => run.testsPassed).length, completed.length),
    knowledgeLift: rate(paired.pairedWins - paired.pairedLosses, paired.pairedWins + paired.pairedLosses + paired.pairedTies),
    passPatchViolationRate: rate(
      applicablePassing.filter((run) => run.constraintVerdict === "violated").length,
      applicablePassing.length,
    ),
    avgCostUsd: average(completed.flatMap((run) => run.costUsd ?? [])),
    ...paired,
    dsr: rate(verdictCount(judged, "satisfied"), judged.length),
    dvr: rate(verdictCount(judged, "violated"), judged.length),
    dnr: rate(verdictCount(judged, "neutral"), judged.length),
    judgedRuns: judged.length, passingApplicable: applicablePassing.length,
    failedRuns: runs.filter((run) => run.status === "failed").length,
  };
}

export function pairedComparisons(runs: BenchmarkRun[]) {
  const blocks = new Map<string, { experimentId: string; arm: ContextArm; values: Map<string, number[]>; wins: number; losses: number; ties: number }>();
  const baselines = new Map(runs.filter((run) => run.arm === "none" && typeof run.testsPassed === "boolean").map((run) => [`${run.experimentId}:${run.pairId}`, run]));
  for (const context of runs.filter((run) => run.arm !== "none" && typeof run.testsPassed === "boolean")) {
    const baseline = baselines.get(`${context.experimentId}:${context.pairId}`);
    if (!baseline?.pairingHash || baseline.pairingHash !== context.pairingHash || baseline.mock !== context.mock) continue;
    const key = `${context.experimentId}:${context.arm}`;
    const block = blocks.get(key) ?? { experimentId: context.experimentId, arm: context.arm, values: new Map<string, number[]>(), wins: 0, losses: 0, ties: 0 };
    const delta = Number(context.testsPassed) - Number(baseline.testsPassed);
    block.values.set(context.taskId, [...(block.values.get(context.taskId) ?? []), delta]);
    if (delta > 0) block.wins++; else if (delta < 0) block.losses++; else block.ties++;
    blocks.set(key, block);
  }
  return [...blocks.values()].map((block) => {
    const means = [...block.values.values()].map(average);
    let state = 42;
    const random = () => { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state / 4294967296; };
    const bootstrap = means.length < 2 ? [] : Array.from({ length: 2000 }, () => average(means.map(() => means[Math.floor(random() * means.length)]))).sort((a, b) => a - b);
    const repeatVariance = average([...block.values.values()].map((values) => values.length < 2 ? 0 : values.reduce((sum, value) => sum + (value - average(values)) ** 2, 0) / (values.length - 1)));
    return { experimentId: block.experimentId, arm: block.arm, taskCount: means.length, pairs: block.wins + block.losses + block.ties,
      wins: block.wins, losses: block.losses, ties: block.ties, lift: average(means), repeatVariance,
      ci95: bootstrap.length ? [bootstrap[49], bootstrap[1949]] as [number, number] : null };
  });
}

export function metricForArm(metrics: ArmMetric[], arm: ContextArm): ArmMetric | undefined {
  return metrics.find((metric) => metric.arm === arm);
}

import { describe, expect, it } from "vitest";
import { aggregateDashboard, pairedComparisons } from "./metrics";
import type { BenchmarkRun } from "./types";

const run = (
  id: string,
  pairId: string,
  arm: BenchmarkRun["arm"],
  testsPassed: boolean,
  constraintVerdict: BenchmarkRun["constraintVerdict"],
): BenchmarkRun => ({
  id,
  pairId,
  arm,
  taskId: pairId,
  repeat: 1,
  ordinal: 0,
  experimentId: "exp",
  repository: "org/repo",
  commit: "abc",
  pairingHash: "fixture-inputs",
  status: "completed",
  testsPassed,
  constraintVerdict,
  costUsd: 1,
});

describe("aggregateDashboard", () => {
  it("retains functional grades when a later independent judge fails", () => {
    const metrics = aggregateDashboard([{ ...run('1', 'a', 'none', true, undefined), status: 'failed' }]);
    expect(metrics.totalRuns).toBe(1);
    expect(metrics.passRate).toBe(1);
    expect(metrics.judgedRuns).toBe(0);
    expect(metrics.failedRuns).toBe(1);
  });
  it("excludes unjudged outcomes from compliance denominators and incomplete pairs from lift", () => {
    const metrics = aggregateDashboard([
      run("1", "a", "none", true, undefined), run("2", "b", "none", true, "violated"),
      run("3", "b", "manual", false, "neutral"),
    ]);
    expect(metrics.passPatchViolationRate).toBe(1);
    expect(metrics.dvr).toBe(.5);
    expect(metrics.knowledgeLift).toBe(-1);
    expect(metrics.pairedTies).toBe(0);
  });
  it("does not combine mismatched inputs or mock and real pairs", () => {
    const runs = [run("1", "a", "none", false, undefined), { ...run("2", "a", "manual", true, undefined), pairingHash: "different" }];
    expect(pairedComparisons(runs)).toEqual([]);
    expect(aggregateDashboard(runs).pairedWins).toBe(0);
    expect(pairedComparisons(runs.map((item) => ({ ...item, pairingHash: undefined })))).toEqual([]);
  });
  it("reports uncertainty at task level and does not invent a one-task confidence interval", () => {
    const runs = [run("1", "a", "none", false, undefined), run("2", "a", "manual", true, undefined)];
    expect(pairedComparisons(runs)[0].ci95).toBeNull();
    const blocks = pairedComparisons([...runs, run("3", "b", "none", true, undefined), run("4", "b", "manual", false, undefined)]);
    expect(blocks[0].lift).toBe(0);
    expect(blocks[0].ci95).toEqual([-1, 1]);
  });
  it("keeps functional and constraint outcomes orthogonal", () => {
    const metrics = aggregateDashboard([
      run("1", "a", "none", false, "neutral"),
      run("2", "a", "skill-generated", true, "satisfied"),
      run("3", "b", "none", true, "satisfied"),
      run("4", "b", "skill-generated", true, "violated"),
    ]);

    expect(metrics.passRate).toBe(0.75);
    expect(metrics.knowledgeLift).toBe(0.5);
    expect(metrics.passPatchViolationRate).toBeCloseTo(1 / 3);
    expect(metrics.pairedWins).toBe(1);
    expect(metrics.pairedTies).toBe(1);
    expect(metrics.dsr).toBe(0.5);
    expect(metrics.dvr).toBe(0.25);
    expect(metrics.dnr).toBe(0.25);
  });
});

import { describe, expect, it } from "vitest";
import { aggregateDashboard } from "./metrics";
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
  status: "completed",
  testsPassed,
  constraintVerdict,
  costUsd: 1,
});

describe("aggregateDashboard", () => {
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

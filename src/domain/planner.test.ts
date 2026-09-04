import { describe, expect, it } from "vitest";
import { planExperimentRuns, validateExperimentRequest } from "./planner";
import type { CreateExperimentRequest } from "./types";

const request: CreateExperimentRequest = {
  name: "Django paired run",
  benchmark: "ctxbench",
  dataset: "eth-sri/agentbench",
  arms: ["none", "skill-generated"],
  repeats: 3,
  taskIds: ["task-a", "task-b"],
  model: { provider: "mock", model: "deterministic", thinking: "off", maxTokens: 4096 },
  profiles: {
    builder: { provider: "mock", model: "builder", thinking: "off", maxTokens: 4096 },
    solver: { provider: "mock", model: "deterministic", thinking: "off", maxTokens: 4096 },
    constraintMiner: { provider: "mock", model: "miner", thinking: "off", maxTokens: 4096 },
    constraintJudge: { provider: "mock", model: "judge", thinking: "off", maxTokens: 4096 },
  },
  agentImage: "ctxbench/agent-pi:0.1.0",
  resources: { cpus: 4, memoryGb: 8, timeoutMinutes: 30, network: "api-only" },
  seed: 42,
};

describe("planExperimentRuns", () => {
  it("creates complete paired and repeatable plans", () => {
    const first = planExperimentRuns("exp-1", request);
    const second = planExperimentRuns("exp-1", request);

    expect(first).toEqual(second);
    expect(first).toHaveLength(12);
    expect(new Set(first.map((run) => run.pairId))).toHaveLength(6);
    for (const pairId of new Set(first.map((run) => run.pairId))) {
      expect(first.filter((run) => run.pairId === pairId).map((run) => run.arm).sort()).toEqual([
        "none",
        "skill-generated",
      ]);
    }
  });

  it("rejects experiments without a causal baseline", () => {
    expect(validateExperimentRequest({ ...request, arms: ["manual"] })).toContain(
      "The none arm is required for a causal baseline.",
    );
  });
});

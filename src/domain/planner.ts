import type { ContextArm, CreateExperimentRequest, PlannedRun } from "./types";

function hashSeed(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function mulberry32(seed: number): () => number {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let value = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffle<T>(items: readonly T[], seed: number): T[] {
  const result = [...items];
  const random = mulberry32(seed);
  for (let index = result.length - 1; index > 0; index -= 1) {
    const target = Math.floor(random() * (index + 1));
    [result[index], result[target]] = [result[target], result[index]];
  }
  return result;
}

export function validateExperimentRequest(request: CreateExperimentRequest): string[] {
  const errors: string[] = [];
  if (!request.name.trim()) errors.push("Experiment name is required.");
  if (!request.dataset.trim()) errors.push("A dataset or manifest is required.");
  if (request.taskIds.length === 0) errors.push("At least one task is required.");
  if (!Number.isInteger(request.repeats) || request.repeats < 1 || request.repeats > 50) {
    errors.push("Repeats must be an integer between 1 and 50.");
  }
  if (!request.arms.includes("none")) errors.push("The none arm is required for a causal baseline.");
  if (request.arms.length < 2) errors.push("At least one context arm is required.");
  if (new Set(request.arms).size !== request.arms.length) errors.push("Context arms must be unique.");
  if (!request.model.provider.trim() || !request.model.model.trim()) {
    errors.push("A frozen provider and model are required.");
  }
  if (!request.agentImage.trim()) errors.push("A pinned container agent image is required.");
  return errors;
}

export function planExperimentRuns(
  experimentId: string,
  request: CreateExperimentRequest,
): PlannedRun[] {
  const errors = validateExperimentRequest(request);
  if (errors.length > 0) throw new Error(errors.join(" "));

  const plans: PlannedRun[] = [];
  for (const taskId of request.taskIds) {
    for (let repeat = 1; repeat <= request.repeats; repeat += 1) {
      const pairId = `${experimentId}:${taskId}:${repeat}`;
      const orderedArms = shuffle<ContextArm>(request.arms, request.seed ^ hashSeed(pairId));
      for (const arm of orderedArms) {
        plans.push({
          id: `${pairId}:${arm}`,
          experimentId,
          pairId,
          taskId,
          repeat,
          arm,
          ordinal: 0,
          status: "queued",
        });
      }
    }
  }

  return shuffle(plans, request.seed).map((plan, ordinal) => ({ ...plan, ordinal }));
}

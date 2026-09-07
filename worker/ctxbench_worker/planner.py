from __future__ import annotations

import hashlib
import random

from .models import ExperimentSpec, PlannedRun
from .workflows import normalize_workflow


def validate_experiment(spec: ExperimentSpec) -> list[str]:
    errors: list[str] = []
    if not spec.name.strip():
        errors.append("Experiment name is required.")
    if not spec.dataset.strip():
        errors.append("A dataset or manifest is required.")
    if not spec.task_ids:
        errors.append("At least one task is required.")
    if len(set(spec.task_ids)) != len(spec.task_ids):
        errors.append("Task IDs must be unique.")
    if not 1 <= spec.repeats <= 50:
        errors.append("Repeats must be between 1 and 50.")
    if "none" not in spec.arms:
        errors.append("The none arm is required for a causal baseline.")
    if len(spec.arms) < 2:
        errors.append("At least one context arm is required.")
    if len(set(spec.arms)) != len(spec.arms):
        errors.append("Context arms must be unique.")
    if not spec.model.provider.strip() or not spec.model.model.strip():
        errors.append("Provider and model must be frozen before planning.")
    if not spec.agent_image.strip():
        errors.append("A pinned container agent image is required.")
    for workflow in (spec.builder_workflow, spec.solver_workflow):
        try:
            normalize_workflow(workflow)
        except ValueError as error:
            errors.append(str(error))
    return errors


def _derived_seed(seed: int, value: str) -> int:
    digest = hashlib.sha256(f"{seed}:{value}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def plan_runs(experiment_id: str, spec: ExperimentSpec) -> list[PlannedRun]:
    errors = validate_experiment(spec)
    if errors:
        raise ValueError(" ".join(errors))

    result: list[PlannedRun] = []
    for task_id in spec.task_ids:
        for repeat in range(1, spec.repeats + 1):
            pair_id = f"{experiment_id}:{task_id}:{repeat}"
            arms = list(spec.arms)
            random.Random(_derived_seed(spec.seed, pair_id)).shuffle(arms)
            for arm in arms:
                result.append(
                    PlannedRun(
                        id=f"{pair_id}:{arm}",
                        experiment_id=experiment_id,
                        pair_id=pair_id,
                        task_id=task_id,
                        repeat=repeat,
                        arm=arm,
                        ordinal=0,
                    )
                )

    random.Random(spec.seed).shuffle(result)
    return [PlannedRun(**{**run.__dict__, "ordinal": ordinal}) for ordinal, run in enumerate(result)]

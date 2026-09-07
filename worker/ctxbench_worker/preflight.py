"""Read-only workload estimates and stage-admission storage checks."""
import os
import shutil
from pathlib import Path

from .models import ExperimentSpec
from .planner import validate_experiment
from .workflows import step_count


def storage_status(root: Path) -> dict:
    usage = shutil.disk_usage(root)
    minimum = float(os.environ.get('CTXBENCH_MIN_FREE_GB', '5')) * 1024 ** 3
    if not 0 <= minimum <= 1024 ** 5:
        raise ValueError('Invalid minimum free storage configuration.')
    return {'freeBytes': usage.free, 'totalBytes': usage.total, 'minimumFreeBytes': int(minimum),
            'ready': usage.free >= minimum, 'scope': 'worker-filesystem'}


def estimate(spec: ExperimentSpec, tasks: list) -> dict:
    errors = validate_experiment(spec)
    if errors:
        raise ValueError(' '.join(errors))
    count = len(tasks)
    keys = len({(task.repository, task.base_commit) for task in tasks})
    builders = keys if 'skill-generated' in spec.arms else 0
    miners = len({(task.repository, task.base_commit) for task in tasks if not spec.constraint_packages.get(task.id)}) if spec.evaluate_constraints else 0
    solves = count * len(spec.arms) * spec.repeats
    judges = spec.judge_profiles or (spec.profiles.get('constraintJudge', spec.model),) * 3
    allowance = {
        'builder': builders * spec.profiles.get('builder', spec.model).max_tokens,
        'miner': miners * spec.profiles.get('constraintMiner', spec.model).max_tokens,
        'solver': solves * spec.model.max_tokens,
        'judges': solves * sum(profile.max_tokens for profile in judges) if spec.evaluate_constraints else 0,
    }
    return {'tasks': count, 'runs': solves, 'contextKeys': keys, 'builderInvocations': builders,
            'builderPromptSteps': builders * step_count(spec.builder_workflow),
            'solverPromptSteps': solves * step_count(spec.solver_workflow),
            'minerInvocations': miners, 'judgeInvocations': solves * 3 if spec.evaluate_constraints else 0,
            'configuredTokenAllowance': sum(allowance.values()), 'tokensByRole': allowance,
            'cacheReuseNotDeducted': True, 'prepareOnly': spec.prepare_only,
            'note': 'Configured allowances, not a bill or a hard total cap. Cached preparation reduces calls; an in-flight Provider request can overshoot its stage allowance.'}

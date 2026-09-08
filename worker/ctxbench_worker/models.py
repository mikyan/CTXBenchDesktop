from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

BenchmarkKind = Literal["swebench", "ctxbench", "custom"]
ContextArm = Literal["none", "skill-generated", "manual", "developer-historical"]
NetworkPolicy = Literal["offline", "api-only", "unrestricted"]
RunMode = Literal["solve", "generate-context", "grade", "mine-constraints", "judge-constraints"]


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    thinking: str
    max_tokens: int
    temperature: float | None = None


@dataclass(frozen=True)
class ResourcePolicy:
    cpus: float = 4
    memory_gb: float = 8
    timeout_minutes: int = 45
    network: NetworkPolicy = "api-only"


@dataclass(frozen=True)
class ExperimentSpec:
    name: str
    benchmark: BenchmarkKind
    dataset: str
    arms: tuple[ContextArm, ...]
    repeats: int
    task_ids: tuple[str, ...]
    model: ModelConfig
    agent_image: str
    resources: ResourcePolicy
    seed: int
    profiles: dict[str, ModelConfig] = field(default_factory=dict)
    env_names: tuple[str, ...] = ()
    context_artifacts: dict[str, str] = field(default_factory=dict)
    prepare_only: bool = False
    evaluate_constraints: bool = False
    judge_profiles: tuple[ModelConfig, ...] = ()
    constraint_packages: dict[str, str] = field(default_factory=dict)
    budget_id: str = ''
    builder_workflow: dict[str, Any] = field(default_factory=dict)
    solver_workflow: dict[str, Any] = field(default_factory=dict)
    agent_args: tuple[str, ...] = ()
    company_environment: dict[str, Any] = field(default_factory=dict)
    # Old persisted plans deliberately retain their original Agent environment.
    project_environment: bool = False


@dataclass(frozen=True)
class PlannedRun:
    id: str
    experiment_id: str
    pair_id: str
    task_id: str
    repeat: int
    arm: ContextArm
    ordinal: int
    status: str = "queued"


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    mode: RunMode
    image: str
    workspace: str
    output_dir: str
    prompt: str
    model: ModelConfig
    resources: ResourcePolicy
    env_names: tuple[str, ...] = ()
    context_paths: tuple[str, ...] = ()
    skill_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    workflow: dict[str, Any] = field(default_factory=dict)
    agent_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: Literal["completed", "failed", "timed-out", "cancelled"]
    exit_code: int
    duration_seconds: float
    output_dir: str
    failure: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def to_dict(value: Any) -> dict[str, Any]:
    return asdict(value)

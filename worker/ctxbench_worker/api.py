from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .engine import ExperimentEngine, create_engine_from_environment
from .jobs import JobWorker
from .models import ExperimentSpec, ModelConfig, ResourcePolicy, RunSpec


class ModelConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    thinking: str = "high"
    maxTokens: int = Field(default=32_768, ge=1)
    temperature: float | None = None


class ResourcePolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpus: float = Field(default=4, gt=0, le=128)
    memoryGb: float = Field(default=8, gt=0, le=1024)
    timeoutMinutes: int = Field(default=45, ge=1, le=1440)
    network: str = "api-only"


class EvaluationProfilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    builder: ModelConfigInput
    solver: ModelConfigInput
    constraintMiner: ModelConfigInput
    constraintJudge: ModelConfigInput


class ExperimentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    benchmark: str
    dataset: str
    arms: list[str]
    repeats: int = Field(ge=1, le=50)
    taskIds: list[str]
    model: ModelConfigInput
    profiles: EvaluationProfilesInput
    agentImage: str = "ctxbench/agent-pi:0.1.0"
    resources: ResourcePolicyInput
    seed: int


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runId: str
    mode: str = "solve"
    image: str = "ctxbench/agent-pi:0.1.0"
    workspace: str
    prompt: str
    model: ModelConfigInput
    resources: ResourcePolicyInput
    envNames: list[str] = Field(default_factory=list)
    contextPaths: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


def _model(value: ModelConfigInput) -> ModelConfig:
    return ModelConfig(
        provider=value.provider,
        model=value.model,
        thinking=value.thinking,
        max_tokens=value.maxTokens,
        temperature=value.temperature,
    )


def _resources(value: ResourcePolicyInput) -> ResourcePolicy:
    if value.network not in {"offline", "api-only", "unrestricted"}:
        raise ValueError("Unsupported network policy.")
    return ResourcePolicy(
        cpus=value.cpus,
        memory_gb=value.memoryGb,
        timeout_minutes=value.timeoutMinutes,
        network=value.network,  # type: ignore[arg-type]
    )


def _spec(value: ExperimentInput) -> ExperimentSpec:
    if value.benchmark not in {"swebench", "ctxbench", "custom"}:
        raise ValueError("Unsupported benchmark kind.")
    if any(arm not in {"none", "skill-generated", "manual", "developer-historical"} for arm in value.arms):
        raise ValueError("Unsupported context arm.")
    return ExperimentSpec(
        name=value.name,
        benchmark=value.benchmark,  # type: ignore[arg-type]
        dataset=value.dataset,
        arms=tuple(value.arms),  # type: ignore[arg-type]
        repeats=value.repeats,
        task_ids=tuple(value.taskIds),
        model=_model(value.model),
        agent_image=value.agentImage,
        resources=_resources(value.resources),
        seed=value.seed,
        profiles={
            "builder": _model(value.profiles.builder),
            "solver": _model(value.profiles.solver),
            "constraintMiner": _model(value.profiles.constraintMiner),
            "constraintJudge": _model(value.profiles.constraintJudge),
        },
    )


def create_app(engine: ExperimentEngine | None = None) -> FastAPI:
    data_root = Path(os.environ.get("CTXBENCH_DATA_DIR", str(Path.cwd() / "worker-data")))
    selected_engine = engine or create_engine_from_environment(
        data_root, os.environ.get("CTXBENCH_RUNNER", "mock")
    )
    jobs = JobWorker(selected_engine.database, selected_engine.runner)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        jobs.start()
        yield
        jobs.stop()

    app = FastAPI(
        title="CTXBench Worker",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.get("/v1/health")
    def health() -> dict[str, object]:
        return {"status": "healthy", "version": "0.1.0", "runner": type(selected_engine.runner).__name__}

    @app.get("/v1/experiments")
    def experiments() -> list[dict[str, object]]:
        return selected_engine.list_experiments()

    @app.post("/v1/experiments", status_code=201)
    def create_experiment(value: ExperimentInput) -> dict[str, object]:
        try:
            return selected_engine.create_experiment(_spec(value))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/runs", status_code=202)
    def enqueue_run(value: RunInput) -> dict[str, object]:
        if value.mode not in {"solve", "generate-context", "grade", "judge-constraints"}:
            raise HTTPException(status_code=422, detail="Unsupported run mode.")
        try:
            resources = _resources(value.resources)
            workspace = (data_root / "repositories" / value.workspace).resolve()
            output = (data_root / "runs" / value.runId).resolve()
            skill_path = (
                str(selected_engine.context_skill_path)
                if value.mode == "generate-context" and selected_engine.context_skill_path is not None
                else None
            )
            spec = RunSpec(
                run_id=value.runId,
                mode=value.mode,  # type: ignore[arg-type]
                image=value.image,
                workspace=str(workspace),
                output_dir=str(output),
                prompt=value.prompt,
                model=_model(value.model),
                resources=resources,
                env_names=tuple(value.envNames),
                context_paths=tuple(value.contextPaths),
                skill_path=skill_path,
                metadata=value.metadata,
            )
            return jobs.enqueue(spec)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, object]:
        try:
            return selected_engine.database.get_job(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Job not found.") from error

    return app


app = create_app()

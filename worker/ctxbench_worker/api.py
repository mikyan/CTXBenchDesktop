from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .engine import ExperimentEngine, create_engine_from_environment
from .history import GitHubClient, JsonClient, mine_review_archive
from .jobs import JobWorker
from .models import ExperimentSpec, ModelConfig, ResourcePolicy, RunSpec
from .workbench import Workbench
from .runner import ENV_NAME, DEFAULT_SECRET_ALLOWLIST, DockerRunner
from .safe_files import safe_file


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
    envNames: list[str] = Field(default_factory=list)
    contextArtifacts: dict[str, str] = Field(default_factory=dict)
    prepareOnly: bool = False
    evaluateConstraints: bool = False
    judgeProfiles: list[ModelConfigInput] = Field(default_factory=list)
    constraintPackages: dict[str, str] = Field(default_factory=dict)


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


class HistoryMineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    cutoff: str
    maxComments: int = Field(default=50, ge=1, le=500)
    maxPullRequests: int = Field(default=10, ge=1, le=100)
    maxPages: int = Field(default=10, ge=1, le=100)


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
        env_names=tuple(value.envNames), context_artifacts=value.contextArtifacts,
        prepare_only=value.prepareOnly, evaluate_constraints=value.evaluateConstraints,
        judge_profiles=tuple(_model(profile) for profile in value.judgeProfiles),
        constraint_packages=value.constraintPackages,
    )


def create_app(
    engine: ExperimentEngine | None = None, history_client: JsonClient | None = None
) -> FastAPI:
    data_root = Path(os.environ.get("CTXBENCH_DATA_DIR", str(Path.cwd() / "worker-data")))
    selected_engine = engine or create_engine_from_environment(
        data_root, os.environ.get("CTXBENCH_RUNNER", "mock")
    )
    jobs = JobWorker(selected_engine.database, selected_engine.runner)
    selected_history_client = history_client or GitHubClient(os.environ.get("GITHUB_TOKEN") or None)
    workbench = Workbench(selected_engine, selected_history_client)
    data_root = workbench.root

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        jobs.start()
        workbench.start()
        yield
        workbench.stop()
        jobs.stop()

    app = FastAPI(
        title="CTXBench Worker",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in {"http://localhost:43173", "http://127.0.0.1:43173", "http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"}:
            return JSONResponse(status_code=403, content={"detail": "Untrusted desktop origin."})
        if int(request.headers.get("content-length", "0")) > 50 * 1024 * 1024:
            return JSONResponse(status_code=413, content={"detail": "Request exceeds 50 MiB."})
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid_value(_: Request, error: ValueError):
        return JSONResponse(status_code=422, content={"detail": workbench.redact(str(error))})

    @app.exception_handler(KeyError)
    async def missing_value(_: Request, error: KeyError):
        return JSONResponse(status_code=404, content={"detail": f"Record not found: {error}"})

    @app.get("/v1/health")
    def health() -> dict[str, object]:
        return {"status": "healthy", "version": "0.1.0", "runner": type(selected_engine.runner).__name__}

    @app.get("/v1/experiments")
    def experiments() -> list[dict[str, object]]:
        return selected_engine.list_experiments()

    @app.post("/v1/experiments", status_code=201)
    def create_experiment(value: ExperimentInput) -> dict[str, object]:
        try:
            return workbench.create_experiment(_spec(value))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/runs", status_code=202)
    def enqueue_run(value: RunInput) -> dict[str, object]:
        if value.mode not in {
            "solve",
            "generate-context",
            "grade",
            "mine-constraints",
            "judge-constraints",
        }:
            raise HTTPException(status_code=422, detail="Unsupported run mode.")
        try:
            resources = _resources(value.resources)
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", value.runId):
                raise ValueError("Run id must use letters, numbers, hyphens or underscores.")
            workspace = (data_root / "repositories" / value.workspace).resolve()
            output = (data_root / "runs" / value.runId).resolve()
            if (data_root / "repositories").resolve() not in workspace.parents:
                raise ValueError("Workspace must be inside the worker repositories directory.")
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

    @app.get("/v1/snapshot")
    def snapshot():
        return workbench.snapshot()

    @app.post("/v1/experiments/{experiment_id}/{action}")
    def experiment_action(experiment_id: str, action: str):
        return workbench.control(experiment_id, action)

    @app.get("/v1/datasets")
    def datasets():
        return workbench.catalog.list()

    @app.get("/v1/constraint-packages")
    def constraint_packages():
        return [{key: value.get(key) for key in ("id", "repository", "commit", "count", "cutoff", "createdAt", "method", "historyVersion")}
                for value in workbench.db.list_documents("constraintPackages")]

    @app.get("/v1/datasets/{dataset_id}/tasks")
    def tasks(dataset_id: str):
        return workbench.catalog.tasks(dataset_id)

    @app.post("/v1/datasets", status_code=201)
    def import_dataset(value: dict):
        rows = value.get("rows")
        if rows is None:
            path = (data_root / "datasets" / str(value.get("path", ""))).resolve()
            if not path.is_file() or (data_root / "datasets").resolve() not in path.parents:
                raise ValueError("Select a file inside the worker datasets directory.")
            if path.suffix == ".parquet":
                rows = workbench.runtime.import_parquet(path)
            elif path.suffix == ".jsonl":
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            else:
                rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Dataset rows must be an array of task records.")
        return workbench.catalog.register(str(value.get("name", "")), str(value.get("benchmark", "")), rows)

    @app.post("/v1/context/import", status_code=201)
    def import_context(value: dict):
        return workbench.import_context(value)

    @app.get("/v1/context/{key}")
    def get_context(key: str):
        manifest = selected_engine.artifacts.verify(key)
        return {"manifest": manifest, "files": {name: (selected_engine.artifacts.path_for(key) / "files" / name).read_text(encoding="utf-8") for name in manifest["files"]}}

    @app.post("/v1/prepare/{kind}", status_code=202)
    def prepare(kind: str, value: dict):
        if kind not in {"context", "constraints"}:
            raise ValueError("Unknown preparation kind.")
        workbench.catalog.task(value["dataset"], value["taskId"])
        model = _model(ModelConfigInput.model_validate(value["model"]))
        resources = _resources(ResourcePolicyInput.model_validate(value["resources"]))
        payload = {"dataset": value["dataset"], "taskId": value["taskId"], "model": model.__dict__,
                   "resources": resources.__dict__, "agentImage": value.get("agentImage", "ctxbench/agent-pi:0.1.0"), "envNames": value.get("envNames", [])}
        return workbench.enqueue(kind, payload)

    @app.get("/v1/operations/{operation_id}")
    def get_operation(operation_id: str):
        return workbench.db.get_document("operations", operation_id)

    @app.get("/v1/runtime")
    def runtime_settings():
        names = getattr(selected_engine.runner, "env_allowlist", DEFAULT_SECRET_ALLOWLIST)
        return {"runner": type(selected_engine.runner).__name__, "dataDirectory": str(data_root),
                "credentials": [{"name": name, "configured": bool(os.environ.get(name))} for name in sorted(names)],
                "datasetFiles": sorted(path.name for path in (data_root / "datasets").glob("*") if path.suffix in {".parquet", ".jsonl"})}

    @app.post("/v1/runtime/credentials")
    def set_credential(value: dict):
        name, secret = value.get("name", ""), value.get("value", "")
        if not isinstance(name, str) or not ENV_NAME.fullmatch(name) or not isinstance(secret, str):
            raise ValueError("Invalid environment variable name or value.")
        if name in {"PATH", "HOME", "PYTHONPATH", "NODE_OPTIONS", "LD_PRELOAD", "DOCKER_HOST", "HTTP_PROXY", "HTTPS_PROXY"} or name.startswith("CTXBENCH_"):
            raise ValueError("This variable controls the worker and cannot be changed as an agent credential.")
        if any(item["status"] in {"queued", "running"} for item in workbench.db.list_documents("operations")):
            raise ValueError("Finish or pause pending work before changing runtime credentials.")
        if secret:
            os.environ[name] = secret
        else:
            os.environ.pop(name, None)
        if isinstance(selected_engine.runner, DockerRunner):
            selected_engine.runner.env_allowlist = selected_engine.runner.env_allowlist | {name}
        if name == "GITHUB_TOKEN" and isinstance(selected_history_client, GitHubClient):
            selected_history_client.token = secret or None
        return {"name": name, "configured": bool(secret)}

    @app.get("/v1/run-output")
    def run_output(runId: str, file: str = "trajectory.jsonl", offset: int = 0):
        allowed = {"trajectory.jsonl", "trajectory.live.jsonl", "raw_agent.patch", "graded.patch", "context_mutation.patch", "result.json", "container.log", "agent.stderr.log", "grading/evaluator.log", "grading/summary.json"}
        if file not in allowed or offset < 0:
            raise ValueError("Unsupported output file or offset.")
        directory = (data_root / "runs" / runId).resolve()
        path = safe_file(directory, file)
        if (data_root / "runs").resolve() not in directory.parents or directory not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="Output is not available yet.")
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            stream.seek(offset)
            content = stream.read(256000)
            next_offset = stream.tell()
        return {"content": workbench.redact(content), "nextOffset": next_offset, "hasMore": next_offset < path.stat().st_size}

    @app.post("/v1/constraints/review-archive", status_code=201)
    def create_review_archive(value: HistoryMineInput) -> dict[str, object]:
        try:
            archive = mine_review_archive(
                value.repository,
                value.cutoff,
                client=selected_history_client,
                max_comments=value.maxComments,
                max_pull_requests=value.maxPullRequests,
                max_pages=value.maxPages,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except OSError as error:
            raise HTTPException(status_code=502, detail=f"GitHub history request failed: {error}") from error
        encoded = json.dumps(archive, sort_keys=True, separators=(",", ":")).encode()
        key = hashlib.sha256(encoded).hexdigest()
        output = data_root / "review-archives" / f"{key}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(encoded)
        stats = archive["stats"]
        return {
            "key": key,
            "path": str(output),
            "repository": value.repository,
            "cutoff": archive["cutoff"],
            "pullRequests": stats["pullRequests"],
            "inspectedPullRequests": stats["inspectedPullRequests"],
            "comments": stats["comments"],
        }

    return app


app = create_app()

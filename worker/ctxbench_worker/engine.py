from __future__ import annotations

import uuid
import os
import shutil
from pathlib import Path

from .artifacts import ArtifactStore
from .database import Database
from .models import ExperimentSpec, RunResult, RunSpec
from .planner import plan_runs
from .runner import DEFAULT_SECRET_ALLOWLIST, DockerRunner, MockRunner, Runner


class ExperimentEngine:
    """Deep orchestration module for durable plans, artifacts, and isolated runs."""

    def __init__(
        self,
        database: Database,
        artifacts: ArtifactStore,
        runner: Runner,
        context_skill_path: Path | None = None,
    ):
        self.database = database
        self.artifacts = artifacts
        self.runner = runner
        self.context_skill_path = context_skill_path

    def create_experiment(self, spec: ExperimentSpec) -> dict[str, object]:
        experiment_id = f"exp-{uuid.uuid4().hex[:12]}"
        plans = plan_runs(experiment_id, spec)
        return self.database.create_experiment(experiment_id, spec, plans)

    def execute(self, spec: RunSpec) -> RunResult:
        return self.runner.run(spec)

    def list_experiments(self) -> list[dict[str, object]]:
        return self.database.list_experiments()


def create_mock_engine(data_root: str | Path) -> ExperimentEngine:
    root = Path(data_root)
    return ExperimentEngine(
        database=Database(root / "ctxbench.sqlite3"),
        artifacts=ArtifactStore(root / "artifacts"),
        runner=MockRunner(),
    )


def create_engine_from_environment(data_root: str | Path, runner_name: str) -> ExperimentEngine:
    root = Path(data_root)
    database = Database(root / "ctxbench.sqlite3")
    artifacts = ArtifactStore(root / "artifacts")
    if runner_name == "mock":
        runner: Runner = MockRunner()
    elif runner_name == "docker":
        extra_names = {
            name.strip()
            for name in os.environ.get("CTXBENCH_EXTRA_ENV_ALLOWLIST", "").split(",")
            if name.strip()
        }
        bundled_skill = Path(
            os.environ.get(
                "CTXBENCH_BUNDLED_SKILL_DIR",
                str(Path(__file__).resolve().parents[2] / "skills" / "ctxbench-generate-context"),
            )
        ).resolve()
        if not bundled_skill.is_dir():
            raise RuntimeError(f"Bundled context-generation skill is missing: {bundled_skill}")
        context_skill_path = root / "runtime" / "skills" / "ctxbench-generate-context"
        shutil.copytree(bundled_skill, context_skill_path, dirs_exist_ok=True)
        runner = DockerRunner(
            repositories_root=root / "repositories",
            artifacts_root=root / "runs",
            request_root=root / "requests",
            env_allowlist=frozenset(DEFAULT_SECRET_ALLOWLIST | extra_names),
            worker_data_root=root,
            host_data_root=os.environ.get("CTXBENCH_HOST_DATA_DIR", str(root)),
        )
    else:
        raise ValueError(f"Unknown runner adapter: {runner_name}")
    return ExperimentEngine(
        database,
        artifacts,
        runner,
        context_skill_path=context_skill_path if runner_name == "docker" else None,
    )

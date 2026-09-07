from __future__ import annotations

import threading
from dataclasses import asdict

from .database import Database
from .models import ModelConfig, ResourcePolicy, RunSpec
from .runner import Runner
from .agent_args import normalize_agent_args


def run_spec_from_dict(value: dict[str, object]) -> RunSpec:
    model = value["model"]
    resources = value["resources"]
    if not isinstance(model, dict) or not isinstance(resources, dict):
        raise ValueError("Job payload has invalid nested configuration.")
    return RunSpec(
        run_id=str(value["run_id"]),
        mode=str(value["mode"]),  # type: ignore[arg-type]
        image=str(value["image"]),
        workspace=str(value["workspace"]),
        output_dir=str(value["output_dir"]),
        prompt=str(value["prompt"]),
        model=ModelConfig(**model),
        resources=ResourcePolicy(**resources),
        env_names=tuple(value.get("env_names", ())),
        context_paths=tuple(value.get("context_paths", ())),
        skill_path=str(value["skill_path"]) if value.get("skill_path") else None,
        metadata=dict(value.get("metadata", {})),
        workflow=dict(value.get("workflow", {})),
        agent_args=normalize_agent_args(value.get("agent_args")),
    )


class JobWorker:
    """Single-claim durable loop; restart recovery is part of its interface."""

    def __init__(self, database: Database, runner: Runner, poll_seconds: float = 0.25):
        self.database = database
        self.runner = runner
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        self._stop.clear()
        recovered = self.database.recover_interrupted_jobs()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="ctxbench-job-worker", daemon=True)
            self._thread.start()
        return recovered

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def enqueue(self, spec: RunSpec) -> dict[str, object]:
        job = self.database.enqueue_job(spec.mode, asdict(spec))
        self._wake.set()
        return job

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.database.claim_job()
            if job is None:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
                continue
            try:
                payload = job["payload"]
                if not isinstance(payload, dict):
                    raise ValueError("Job payload is not an object.")
                if job["attempts"] > 1:
                    if hasattr(self.runner, "cancel"):
                        self.runner.cancel(str(payload["run_id"]))
                    raise ValueError("Interrupted raw run requires a new run ID and clean workspace. Use experiments for checkpointed recovery.")
                result = self.runner.run(run_spec_from_dict(payload))
                terminal = "completed" if result.status == "completed" else "failed"
                self.database.finish_job(str(job["id"]), terminal, asdict(result))
            except BaseException as error:
                self.database.finish_job(
                    str(job["id"]),
                    "failed",
                    {"failure": f"{type(error).__name__}: {error}"},
                )

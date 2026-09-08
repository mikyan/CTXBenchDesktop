"""Persistent prepare → solve → grade → judge workflow used by the desktop."""
from __future__ import annotations

import json
import hashlib
import os
import threading
import uuid
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from .artifacts import ContextIdentity, is_context_owned, safe_relative_path
from .catalog import Catalog, fingerprint
from .constraint_prompts import judging_prompt, mining_prompt
from .constraints import aggregate_constraint_votes, design_constraints_from_document, issue_verdict, judge_votes_from_document
from .database import utc_now
from .history import mine_review_archive
from .models import ExperimentSpec, ModelConfig, RunSpec
from .runner import DockerRunner, selected_environment
from .runtime import Runtime, git, seal
from .workspace import prepare_context
from .safe_files import safe_file
from .checkpoints import GradeCheckpoint, digest, stage_evidence, verify_stage
from .preflight import estimate, storage_status
from .budgets import TokenBudget, BudgetExhausted
from .workflows import normalize_workflow, workflow_request
from .agent_args import normalize_agent_args, verify_agent_args_receipt
from .project_environment import ProjectEnvironments
from .standard_images import project_image

GENERATION_PROMPT = "/skill:ctxbench-generate-context\n\nCapability: tree-only. Generate a frozen repository context artifact from this exact baseline checkout."


def usage(metadata: dict) -> dict:
    stats = metadata.get("sessionStats") or metadata
    tokens = stats.get("tokens") or {}
    cost = stats.get("cost", stats.get("totalCost"))
    if isinstance(cost, dict):
        cost = cost.get("total")
    return {"inputTokens": stats.get("inputTokens", tokens.get("input")),
            "outputTokens": stats.get("outputTokens", tokens.get("output")),
            "cacheReadTokens": tokens.get("cacheRead"), "cacheWriteTokens": tokens.get("cacheWrite"),
            "totalTokens": tokens.get("total", metadata.get("cumulativeTokens")), "costUsd": cost}


class Interrupted(Exception):
    pass


class Workbench:
    def __init__(self, engine, history_client):
        self.engine, self.db = engine, engine.database
        self.root = self.db.path.parent
        self.catalog = Catalog(self.root, self.db)
        self.runtime = Runtime(self.root, engine.runner)
        self.history_client = history_client
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._active: dict[str, str] = {}
        self._lock = threading.RLock()
        self._scope = threading.local()
        self.budgets = TokenBudget(self.db)
        self.operation_handlers = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.budgets.recover(self.engine.runner)
        # Even a paused/cancelled operation may have an orphan after a process crash.
        # Reap only stages owned by this database before admitting further work.
        if hasattr(self.engine.runner, 'cancel'):
            for stage in self.db.list_documents('stages'):
                if stage['status'] != 'completed':
                    self.engine.runner.cancel(stage['runId'])
        if isinstance(self.engine.runner, DockerRunner):
            ProjectEnvironments(self.runtime, self.redact).recover_exports()
            for prepared in self.db.list_documents('prepared'):
                self._cancel_environment_preparations(prepared['id'])
            for run in self.db.list_runs(compact=True):
                if run['status'] == 'grading' and run.get('outputDir'):
                    self.runtime.cancel_grade(Path(run['outputDir']) / 'grading')
        for operation in self.db.list_documents("operations"):
            if operation["status"] == "running":
                operation["status"] = "failed" if operation["kind"].startswith("intranet:") else "queued"
                if operation["kind"].startswith("intranet:"):
                    operation["failure"] = "Operator operation was interrupted; inspect local resources before explicitly retrying."
                self.db.put_document("operations", operation["id"], operation)
        if not self._thread or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="ctxbench-workbench", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        with self._lock:
            for run_id in self._active.values():
                if hasattr(self.engine.runner, "cancel"):
                    self.engine.runner.cancel(run_id)
            if isinstance(self.engine.runner, DockerRunner):
                for prepared in self.db.list_documents('prepared'):
                    self._cancel_environment_preparations(prepared['id'])
                for run in self.db.list_runs(compact=True):
                    if run['status'] == 'grading' and run.get('outputDir'):
                        self.runtime.cancel_grade(Path(run['outputDir']) / 'grading')
        if self._thread:
            self._thread.join(timeout=5)

    def enqueue(self, kind: str, payload: dict) -> dict:
        operation = {"id": f"op-{uuid.uuid4().hex[:16]}", "kind": kind, "payload": payload,
                     "status": "queued", "createdAt": utc_now(), "updatedAt": utc_now()}
        self.db.put_document("operations", operation["id"], operation)
        self._wake.set()
        return operation

    def control_operation(self, operation_id: str, action: str) -> dict:
        """Durable controls for independent preparation, including rapid pause/resume."""
        allowed = {"pause": {"queued", "running"}, "cancel": {"queued", "running", "paused"},
                   "resume": {"paused"}, "retry": {"failed", "cancelled"}}
        with self._lock:
            operation = self.db.get_document("operations", operation_id)
            if operation["kind"] == "experiment":
                raise ValueError("Use experiment controls for an experiment operation.")
            if action not in allowed or operation["status"] not in allowed[action]:
                raise ValueError("This preparation action is not valid for its current state.")
            operation.update(status={"pause": "paused", "cancel": "cancelled"}.get(action, "queued"),
                             updatedAt=utc_now(), controlRevision=operation.get("controlRevision", 0) + 1)
            if action in {"resume", "retry"}:
                operation.pop("failure", None)
            self.db.put_document("operations", operation_id, operation)
            active = self._active.get(operation_id)
            if action == "cancel" and active and hasattr(self.engine.runner, "cancel"):
                self.engine.runner.cancel(active)
            self._wake.set()
            return operation

    def create_experiment(self, spec: ExperimentSpec) -> dict:
        self.validate_inputs(spec)
        experiment = self.engine.create_experiment(spec)
        self.enqueue("experiment", {"experimentId": experiment["id"]})
        return experiment

    def validate_inputs(self, spec: ExperimentSpec) -> list:
        self.validate_agent_args(spec.agent_args, spec.agent_image)
        self.validate_workflow(spec.builder_workflow, 'generate-context')
        self.validate_workflow(spec.solver_workflow, 'solve')
        if spec.budget_id:
            self.budgets.validate(spec.budget_id, [spec.model, *spec.profiles.values(), *spec.judge_profiles])
        dataset = self.db.get_document("datasets", spec.dataset)
        if dataset["benchmark"] != spec.benchmark:
            raise ValueError("The imported dataset belongs to another benchmark.")
        if spec.profiles.get("solver", spec.model) != spec.model:
            raise ValueError("The solver profile and model must be identical.")
        if spec.judge_profiles and len(spec.judge_profiles) != 3:
            raise ValueError("Research mode requires exactly three frozen judge profiles.")
        task_index = self.catalog.index(spec.dataset)
        if any(task_id not in task_index for task_id in spec.task_ids):
            raise ValueError('Selected tasks must belong to the imported dataset.')
        tasks = [task_index[task_id] for task_id in spec.task_ids]
        for task in tasks:
            task_id = task.id
            if spec.constraint_packages.get(task_id):
                self._validate_constraints(spec.constraint_packages[task_id], task)
            if "manual" in spec.arms:
                key = spec.context_artifacts.get(task_id)
                if not key:
                    raise ValueError(f"Select a frozen manual package for {task_id}.")
                self._validate_artifact(key, task)
        if isinstance(self.engine.runner, DockerRunner):
            selected_environment(spec.env_names, self.engine.runner.env_allowlist)
        return tasks

    def validate_agent_args(self, value: object, image: str) -> tuple[str, ...]:
        args = normalize_agent_args(value)
        if any(self.redact(arg) != arg for arg in args):
            raise ValueError('Do not embed runtime credentials in agent startup arguments; use selected environment variables.')
        if args and isinstance(self.engine.runner, DockerRunner):
            self.engine.runner.validate_agent_args_image(image, args)
        return args

    def validate_workflow(self, workflow: object, mode: str):
        normalized = normalize_workflow(workflow)
        if normalized and mode not in {'generate-context', 'solve'}:
            raise ValueError('Custom workflows are only supported for context generation and solving.')
        text = json.dumps(normalized)
        if self.redact(text) != text:
            raise ValueError('Do not embed runtime credentials in commands or prompts; reference environment variables instead.')

    def preflight(self, spec: ExperimentSpec) -> dict:
        tasks = self.validate_inputs(spec)
        return {**estimate(spec, tasks), 'storage': storage_status(self.root),
                'workerUsesDocker': isinstance(self.engine.runner, DockerRunner),
                'sharedBudget': self.budgets.snapshot(spec.budget_id) if spec.budget_id else None}

    def control(self, experiment_id: str, action: str) -> dict:
        with self._lock:
            record = self.db.get_experiment(experiment_id)
            if action == "pause":
                if record["status"] not in {"preparing", "running"}:
                    raise ValueError("Only active experiments can be paused.")
                self.db.set_experiment_status(experiment_id, "paused")
                self._interrupt_experiment_operations(experiment_id, 'paused')
            elif action == "cancel":
                self.db.set_experiment_status(experiment_id, "cancelled")
                self._interrupt_experiment_operations(experiment_id, 'cancelled')
                self._cancel_environment_preparations(experiment_id)
                for run in self.db.list_runs(experiment_id):
                    if run["status"] == "grading" and run.get("outputDir") and isinstance(self.engine.runner, DockerRunner):
                        self.runtime.cancel_grade(Path(run["outputDir"]) / "grading")
                    if run["status"] not in {"completed", "failed", "cancelled"}:
                        self.db.update_run(run["id"], "cancelled", {})
                if experiment_id in self._active and hasattr(self.engine.runner, "cancel"):
                    self.engine.runner.cancel(self._active[experiment_id])
            elif action in {"resume", "retry"}:
                if record["status"] in {"running", "preparing"}:
                    raise ValueError("This experiment is already active.")
                if action == "resume" and record["status"] not in {"ready", "paused"}:
                    raise ValueError("Resume requires a ready or paused experiment; use retry for failures.")
                if action == "retry" and record["status"] not in {"failed", "cancelled"}:
                    raise ValueError("Only failed or cancelled experiments can be retried.")
                self.db.put_document("executionRequests", experiment_id, {"start": True})
                if action == "retry":
                    for run in self.db.list_runs(experiment_id):
                        if run["status"] in {"failed", "cancelled"}:
                            self.db.update_run(run["id"], "queued", {"failure": None})
                self.db.set_experiment_status(experiment_id, "preparing")
                operations = self.db.list_documents("operations")
                existing = next((item for item in operations if item["kind"] == "experiment" and
                                 item["payload"]["experimentId"] == experiment_id and item["status"] in {"queued", "running"}), None)
                if not existing:
                    self.enqueue("experiment", {"experimentId": experiment_id, "start": True})
            else:
                raise ValueError("Unknown experiment action.")
        return self.db.get_experiment(experiment_id)

    def _cancel_environment_preparations(self, experiment_id: str):
        if not isinstance(self.engine.runner, DockerRunner):
            return
        try:
            prepared = self.db.get_document('prepared', experiment_id)
        except KeyError:
            return
        for task_id, output in prepared.get('environmentOutputs', {}).items():
            if task_id not in prepared.get('graderImages', {}):
                self.runtime.cancel_grade(Path(output))

    def _interrupt_experiment_operations(self, experiment_id: str, status: str):
        for operation in self.db.list_documents('operations'):
            if operation['kind'] == 'experiment' and operation['payload']['experimentId'] == experiment_id and operation['status'] in {'queued', 'running', 'paused'}:
                operation.update(status=status, updatedAt=utc_now(), controlRevision=operation.get('controlRevision', 0) + 1)
                self.db.put_document('operations', operation['id'], operation)

    def _check(self, experiment_id: str | None):
        if self._stop.is_set():
            raise Interrupted("Worker stopped; completed stages are preserved.")
        if experiment_id and self.db.get_experiment(experiment_id)["status"] in {"paused", "cancelled"}:
            raise Interrupted("Experiment paused or cancelled.")
        operation_id = getattr(self._scope, "operation_id", None)
        if operation_id and self.db.get_document("operations", operation_id)["status"] in {"paused", "cancelled"}:
            raise Interrupted("Preparation paused or cancelled; completed stages are preserved.")
        if isinstance(self.engine.runner, DockerRunner) and not storage_status(self.root)['ready']:
            if experiment_id:
                self.db.set_experiment_status(experiment_id, 'paused')
            raise Interrupted('Low worker disk space; execution paused before starting another stage. Free space or adjust CTXBENCH_MIN_FREE_GB, then resume.')

    def _loop(self):
        while not self._stop.is_set():
            with self._lock:
                operations = sorted(self.db.list_documents("operations"), key=lambda item: item["createdAt"])
                operation = next((item for item in operations if item["status"] == "queued"), None)
                if operation:
                    operation.update(status="running", updatedAt=utc_now())
                    self.db.put_document("operations", operation["id"], operation)
            if operation is None:
                self._wake.wait(.5)
                self._wake.clear()
                continue
            self._scope.operation_id = operation["id"]
            try:
                if operation["kind"] == "experiment":
                    spec = self.db.get_spec(operation["payload"]["experimentId"])
                    with self.runtime.using_environment(spec.company_environment):
                        result = self.run_experiment(operation["payload"]["experimentId"], operation["payload"].get("start", False))
                elif operation["kind"] in self.operation_handlers:
                    result = self.operation_handlers[operation["kind"]](operation)
                else:
                    self._check(None)
                    payload = operation["payload"]
                    task = self.catalog.task(payload["dataset"], payload["taskId"])
                    spec = self._preparation_spec(payload)
                    image = self.runtime.resolve_image(spec.agent_image) if isinstance(self.engine.runner, DockerRunner) else spec.agent_image
                    if operation['kind'] == 'context' and spec.project_environment and isinstance(self.engine.runner, DockerRunner):
                        image = self.prepare_project_agent(task, spec, image)['imageId']
                    result = self.generate(task, spec, image) if operation["kind"] == "context" else self.mine(task, spec, image)
                operation.update(status="completed", result=result)
            except Interrupted as error:
                operation.update(status=("failed" if operation["kind"].startswith("intranet:") and self._stop.is_set() else "queued" if self._stop.is_set() else "paused"), failure=str(error))
            except Exception as error:
                operation.update(status="queued" if self._stop.is_set() and not operation["kind"].startswith("intranet:") else "failed", failure=self.redact(f"{type(error).__name__}: {error}"))
                if operation["kind"] == "experiment":
                    experiment_id = operation["payload"]["experimentId"]
                    if not self._stop.is_set() and self.db.get_experiment(experiment_id)["status"] not in {"paused", "cancelled"}:
                        self.db.set_experiment_status(experiment_id, "failed")
            finally:
                self._scope.operation_id = None
            with self._lock:
                current = self.db.get_document("operations", operation["id"])
                # A caller may resume/retry while the old invocation is unwinding.
                # Never overwrite the newer durable control request with stale state.
                if current.get("controlRevision", 0) == operation.get("controlRevision", 0):
                    if current.get('progress'):
                        operation['progress'] = current['progress']
                    operation["updatedAt"] = utc_now()
                    self.db.put_document("operations", operation["id"], operation)

    @staticmethod
    def _preparation_spec(payload: dict) -> ExperimentSpec:
        from .models import ResourcePolicy
        model = ModelConfig(**payload["model"])
        return ExperimentSpec("Preparation", "custom", payload["dataset"], ("none", "skill-generated"), 1,
            (payload["taskId"],), model, payload["agentImage"], ResourcePolicy(**payload["resources"]), 0,
            profiles={"builder": model, "constraintMiner": model}, env_names=tuple(payload.get("envNames", [])), budget_id=payload.get('budgetId', ''),
            builder_workflow=normalize_workflow(payload.get('workflow')), agent_args=normalize_agent_args(payload.get('agentArgs')),
            project_environment=payload.get('projectEnvironment', False))

    def prepare_project_agent(self, task, spec, agent_image, grader_image=None, experiment_id=None):
        """One preparation path for independent builders and paired experiments."""
        scope = experiment_id or getattr(self._scope, 'operation_id', None)
        def progress(message, status='preparing'):
            record = {'message': self.redact(message), 'status': status, 'taskId': task.id, 'updatedAt': utc_now()}
            if scope:
                self.db.put_document('environmentProgress', scope, record)
            operation_id = getattr(self._scope, 'operation_id', None)
            if operation_id:
                with self._lock:
                    operation = self.db.get_document('operations', operation_id)
                    operation['progress'] = record
                    self.db.put_document('operations', operation_id, operation)
        try:
            self._check(experiment_id)
            progress('Preparing project dependencies before knowledge generation or coding. No model is being called.')
            if grader_image:
                source = grader_image
            elif task.source == 'custom':
                source = self.runtime.prepare_test_image(task)
            elif task.source == 'agentbench':
                dataset = self.catalog.verify(spec.dataset)
                harness = self.runtime.resolve_image(self.runtime.environment.get('harnessImage', 'ctxbench/official-harness:0.1.0'))
                source = self.runtime.prepare_agentbench_image(task, Path(dataset['path']), harness, spec.resources, scope=scope or 'project')
            else:
                source = self.runtime.resolve_image(project_image(task))
            self._check(experiment_id)
            result = ProjectEnvironments(self.runtime, self.redact).prepare(task, source, agent_image,
                check=lambda: self._check(experiment_id), progress=progress)
            self.db.put_document('projectEnvironments', result['key'], {**result, 'repository': task.repository,
                'baseCommit': task.base_commit, 'agentAdapter': agent_image, 'createdAt': utc_now()})
            progress('Project build environment is ready. Its frozen image will be reused by both comparison arms.', 'ready')
            return result
        except Exception:
            progress('Project environment preparation did not finish. No Agent is started for this task; inspect the error and retry.', 'failed')
            raise

    def redact(self, text: str) -> str:
        names = getattr(self.engine.runner, "env_allowlist", ())
        for name in names:
            value = os.environ.get(name)
            if value:
                text = text.replace(value, "[REDACTED]")
        return text

    def _agent(self, key: str, mode: str, workspace_factory, prompt: str, model: ModelConfig,
               spec: ExperimentSpec, image: str, *, context_paths=(), experiment_id=None) -> dict:
        workflow = normalize_workflow(spec.builder_workflow if mode == 'generate-context' else spec.solver_workflow if mode == 'solve' else {})
        try:
            stage = self.db.get_document("stages", key)
            if stage["status"] == "completed":
                safe_file(Path(stage["output"]), "result.json").read_bytes()
                verify_stage(stage, mode)
                return stage
            if hasattr(self.engine.runner, "cancel"):
                self.engine.runner.cancel(stage["runId"])
        except KeyError:
            pass
        self._check(experiment_id)
        if workflow and isinstance(self.engine.runner, DockerRunner):
            self.engine.runner.validate_workflow_image(image)
        self.validate_agent_args(spec.agent_args, image)
        run_id = f"{mode[:8]}-{uuid.uuid4().hex[:20]}"
        workspace = workspace_factory()
        expected_document = None
        if mode == "mine-constraints":
            expected_document = json.loads(safe_file(workspace, "review-archive.json").read_text(encoding="utf-8"))
        elif mode == "judge-constraints":
            expected_document = json.loads(safe_file(workspace, "constraints.json").read_text(encoding="utf-8"))
        output = self.root / "runs" / run_id
        if spec.budget_id:
            self.budgets.validate(spec.budget_id, [model])
            try:
                self.budgets.reserve(spec.budget_id, run_id, model.max_tokens, mode=mode, experiment_id=experiment_id, output=str(output))
            except BudgetExhausted as error:
                if experiment_id:
                    self.db.set_experiment_status(experiment_id, 'paused')
                raise Interrupted(str(error)) from error
        scope_id = experiment_id or getattr(self._scope, "operation_id", None) or key
        stage = {"id": key, "status": "running", "runId": run_id, "experimentId": experiment_id,
                 "operationId": getattr(self._scope, "operation_id", None), "workspace": str(workspace), "output": str(output), "startedAt": utc_now()}
        self.db.put_document("stages", key, stage)
        if mode == "solve" and key.startswith("solve:"):
            self.db.update_run(key[len("solve:"):], "running", {"solverRunId": run_id, "outputDir": str(output)})
        with self._lock:
            self._active[scope_id] = run_id
        try:
            result = self.engine.runner.run(RunSpec(run_id, mode, image, str(workspace), str(output), prompt,
                model, spec.resources, spec.env_names, tuple(context_paths),
                str(self.engine.context_skill_path) if mode == "generate-context" and self.engine.context_skill_path else None,
                {"capability": "tree-only"} if mode == "generate-context" else {}, workflow=normalize_workflow(workflow), agent_args=spec.agent_args))
            metadata_path = safe_file(output, "result.json")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            if isinstance(self.engine.runner, DockerRunner) and (metadata.get("schemaVersion") != 1 or metadata.get("runId") != run_id):
                raise ValueError(f"Agent result contract invalid for run {run_id}.")
            if result.status != "completed" or metadata.get("status", "completed") != "completed":
                self._check(experiment_id)
                reason = ("Cumulative token budget exhausted" if metadata.get("budgetInterrupted") else
                          "Agent timed out" if metadata.get("status") == "timed-out" else metadata.get("workflowError") or metadata.get("promptError") or result.failure or "Invalid agent completion")
                stage.update(status="failed", failure=self.redact(str(reason)), metadata=metadata)
                self.db.put_document("stages", key, stage)
                raise RuntimeError(f"{reason}; run {run_id}. Inspect its result.json and trajectory.")
            if workflow and isinstance(self.engine.runner, DockerRunner):
                expected_steps = workflow_request(workflow, prompt)['steps']
                actual_steps = metadata.get('workflowSteps', [])
                if (metadata.get('workflowProtocolVersion') != 1 or len(actual_steps) != len(expected_steps)
                        or any(actual.get('status') != 'completed' or actual.get('promptHash') != hashlib.sha256(expected['prompt'].encode()).hexdigest()
                               for actual, expected in zip(actual_steps, expected_steps))):
                    raise ValueError('Agent did not confirm every configured workflow step; refusing a partial or ignored workflow.')
            if isinstance(self.engine.runner, DockerRunner):
                verify_agent_args_receipt(metadata, spec.agent_args)
            # Do not checkpoint malformed model output as successful: retry must run that
            # stage again, while preserving other completed solve/grade/judge checkpoints.
            if mode == "solve":
                safe_file(output, "graded.patch").read_bytes()
            elif mode == "mine-constraints":
                raw = safe_file(workspace, "constraints.json").read_text(encoding="utf-8")
                if self.redact(raw) != raw:
                    raise ValueError("Miner output contains a configured runtime credential.")
                document = json.loads(raw)
                design_constraints_from_document(document)
                if document["repository"] != expected_document["repository"]:
                    raise ValueError("Miner returned a different repository.")
            elif mode == "judge-constraints":
                raw = safe_file(workspace, "votes.json").read_text(encoding="utf-8")
                if self.redact(raw) != raw:
                    raise ValueError("Judge output contains a configured runtime credential.")
                document = json.loads(raw)
                votes = judge_votes_from_document(document)
                if document["judge"] != key.rsplit(":", 1)[-1] or {item[0] for item in votes} != {item["id"] for item in expected_document["constraints"]}:
                    raise ValueError("Judge output identity or constraint coverage is invalid.")
            elif mode == "generate-context":
                source = output / "context" / "files"
                files = [path for path in source.rglob("*") if path.is_file()]
                if not files or any(not is_context_owned(path.relative_to(source).as_posix()) for path in files):
                    raise ValueError("Generator returned an empty or invalid context package.")
                if sum(safe_file(source, path.relative_to(source).as_posix()).stat().st_size for path in files) > 20 * 1024 * 1024:
                    raise ValueError("Context packages are limited to 20 MiB.")
            stage.update(status="completed", durationSeconds=result.duration_seconds, metadata=metadata, completedAt=utc_now())
            stage['integrity'] = stage_evidence(stage, mode)
            self.db.put_document("stages", key, stage)
            return stage
        finally:
            if spec.budget_id:
                try:
                    accounting = json.loads(safe_file(output, 'result.json').read_text(encoding='utf-8'))
                    if not isinstance(accounting, dict):
                        accounting = None
                except (ValueError, OSError):
                    accounting = None
                self.budgets.settle(run_id, accounting)
            with self._lock:
                self._active.pop(scope_id, None)

    def _validate_artifact(self, key: str, task):
        manifest = self.engine.artifacts.verify(key)
        if manifest["identity"]["repository"] != task.repository or manifest["identity"]["commit"] != task.base_commit:
            raise ValueError("Context package repository and baseline commit must match the task exactly.")
        if manifest["identity"]["capability"] != "tree-only":
            raise ValueError("Primary evaluation only accepts task-blind tree-only context.")
        return manifest

    def _validate_constraints(self, key: str, task):
        package = self.db.get_document("constraintPackages", key)
        repository = task.repository.removeprefix("https://github.com/").removesuffix(".git")
        if package["repository"] != repository or package["commit"] != task.base_commit:
            raise ValueError("Constraint package must match the exact repository and baseline commit.")
        design_constraints_from_document(package["document"])
        return package

    def import_context(self, value: dict) -> dict:
        task = self.catalog.task(value["dataset"], value["taskId"])
        if value.get("baseCommit") != task.base_commit or value.get("repository") != task.repository:
            raise ValueError("Manual package must declare the exact task repository and baseline commit.")
        files = {str(name): str(content).encode() for name, content in value["files"].items()}
        if any(self.redact(content.decode()) != content.decode() for content in files.values()):
            raise ValueError("Context package contains a configured runtime credential.")
        if sum(map(len, files.values())) > 20 * 1024 * 1024:
            raise ValueError("Context packages are limited to 20 MiB.")
        declared = tuple(value.get("contextPaths", files.keys()))
        for name in files:
            safe_relative_path(name)
            if not name.lower().endswith((".md", ".txt", ".rst")):
                raise ValueError("Manual context imports must contain documentation files only.")
        identity = ContextIdentity(task.repository, task.base_commit, "tree-only", "manual-v1",
            fingerprint({name: content.decode() for name, content in files.items()}), ModelConfig("manual", "human", "off", 1))
        self.engine.artifacts.publish(identity, files, {"source": "manual", "createdAt": utc_now(), "declaredPaths": declared}, declared)
        return self.artifact_record(identity.key())

    def generate(self, task, spec: ExperimentSpec, image: str, experiment_id=None) -> dict:
        builder = spec.profiles.get("builder", spec.model)
        skill = self.engine.context_skill_path
        skill_hash = fingerprint((skill / "SKILL.md").read_text(encoding="utf-8")) if skill else "mock-v1"
        generation_inputs = {"prompt": GENERATION_PROMPT, "image": image, "resources": asdict(spec.resources), "envNames": spec.env_names}
        if spec.agent_args:
            generation_inputs['agentArgs'] = spec.agent_args
        if normalize_workflow(spec.builder_workflow):
            generation_inputs['workflow'] = workflow_request(spec.builder_workflow, GENERATION_PROMPT)
        identity = ContextIdentity(task.repository, task.base_commit, "tree-only", skill_hash,
            fingerprint(generation_inputs), builder)
        key = identity.key()
        if not self.engine.artifacts.contains(key):
            def checkout():
                workspace = self.runtime.checkout(task, "builder")
                prepare_context(workspace, "none")
                seal(workspace)
                return workspace
            stage = self._agent(f"context:{key}", "generate-context", checkout, GENERATION_PROMPT, builder, spec, image, experiment_id=experiment_id)
            source = Path(stage["output"]) / "context" / "files"
            files = {path.relative_to(source).as_posix(): safe_file(source, path.relative_to(source).as_posix()).read_bytes() for path in source.rglob("*") if path.is_file()}
            if any(self.redact(content.decode(errors='replace')) != content.decode(errors='replace') for content in files.values()):
                raise ValueError("Context package contains a configured runtime credential.")
            self.engine.artifacts.publish(identity, files, {"source": "skill-generated", "createdAt": utc_now(),
                "runId": stage["runId"], "image": image, "durationSeconds": stage["durationSeconds"], "metadata": stage["metadata"]})
        self.engine.artifacts.verify(key)
        return self.artifact_record(key)

    def artifact_record(self, key: str, reuse_count: int | None = None) -> dict:
        manifest = self.engine.artifacts.verify(key)
        identity, provenance = manifest["identity"], manifest["provenance"]
        builder = dict(identity["builder"])
        builder["maxTokens"] = builder.pop("max_tokens")
        return {"id": key, "repository": identity["repository"], "commit": identity["commit"],
            "capability": identity["capability"], "source": provenance.get("source", "manual"),
            "files": len(manifest["files"]), "filePaths": list(manifest["files"]),
            "bytes": sum((self.engine.artifacts.path_for(key) / "files" / name).stat().st_size for name in manifest["files"]),
            "tasksReused": reuse_count if reuse_count is not None else sum(run.get("contextArtifactId") == key for run in self.db.list_runs(compact=True)),
            "status": "ready", "generatedAt": provenance.get("createdAt"), "builder": builder,
            "generationUsage": usage(provenance.get("metadata", {})), "durationSeconds": provenance.get("durationSeconds"),
            "promptHash": identity["generation_prompt_hash"], "skillVersion": identity["skill_version"], "informed": False}

    def mine(self, task, spec: ExperimentSpec, image: str, experiment_id=None) -> dict:
        _, cutoff = self.runtime.baseline(task)
        repository = task.repository.removeprefix("https://github.com/").removesuffix(".git")
        if repository.count("/") != 1:
            raise ValueError("Automatic review mining currently requires a GitHub owner/repository.")
        model = spec.profiles.get("constraintMiner", spec.model)
        key = fingerprint({"repository": repository, "commit": task.base_commit, "cutoff": cutoff, "historyVersion": 2, "model": asdict(model), "image": image,
                           "prompt": mining_prompt(), "limits": [50, 10, 10], **({'agentArgs': spec.agent_args} if spec.agent_args else {})})
        try:
            return self.db.get_document("constraintPackages", key)
        except KeyError:
            pass
        archive_key = fingerprint({"repository": repository, "cutoff": cutoff, "historyVersion": 2})
        try:
            archive = self.db.get_document("archives", archive_key)
        except KeyError:
            archive = mine_review_archive(repository, cutoff, client=self.history_client, max_comments=50, max_pull_requests=10, max_pages=10)
            self.db.put_document("archives", archive_key, archive)
        if not archive.get("pullRequests"):
            document = {"schemaVersion": 1, "repository": repository, "quality": "silver", "constraints": []}
            stage = None
        else:
            stage = self._agent(f"miner:{key}", "mine-constraints",
                lambda: self.runtime.evaluator_workspace("miner", {"review-archive.json": json.dumps(archive)}),
                mining_prompt(), model, spec, image, experiment_id=experiment_id)
            document = json.loads(safe_file(Path(stage["workspace"]), "constraints.json").read_text(encoding="utf-8"))
        parsed = design_constraints_from_document(document)
        if document["repository"] != repository:
            raise ValueError("Miner returned constraints for a different repository.")
        # Automated candidates are always silver, regardless of model output.
        document["quality"] = "silver"
        package = {"id": key, "repository": repository, "commit": task.base_commit, "cutoff": cutoff,
                   "document": document, "count": len(parsed), "archiveKey": archive_key, "profile": asdict(model),
                   "promptHash": fingerprint(mining_prompt()), "stage": stage, "createdAt": utc_now(),
                   "method": "review-grounded-llm-v1", "historyVersion": 2, "reviewLimits": {"comments": 50, "pullRequests": 10, "pages": 10}}
        self.db.put_document("constraintPackages", key, package)
        return package

    def run_experiment(self, experiment_id: str, start: bool = False) -> dict:
        self._check(experiment_id)
        spec = self.db.get_spec(experiment_id)
        try:
            prepared = self.db.get_document("prepared", experiment_id)
        except KeyError:
            image = self.runtime.resolve_image(spec.agent_image) if isinstance(self.engine.runner, DockerRunner) else spec.agent_image
            harness = self.runtime.resolve_image(self.runtime.environment.get("harnessImage", "ctxbench/official-harness:0.1.0")) if isinstance(self.engine.runner, DockerRunner) and spec.benchmark != "custom" else "custom"
            prepared = {"id": experiment_id, "image": image, "harnessImage": harness, "contexts": {}, "constraints": {}, "graderImages": {}, "agentImages": {},
                        "environmentVersion": 1}
            self.db.put_document("prepared", experiment_id, prepared)
        task_index = self.catalog.index(spec.dataset)
        for task_id in spec.task_ids:
            self._check(experiment_id)
            task = task_index[task_id]
            if task.source == 'agentbench' and prepared.get('environmentVersion') == 1 and isinstance(self.engine.runner, DockerRunner):
                if task_id not in prepared['graderImages']:
                    dataset = self.catalog.verify(spec.dataset)
                    prepared.setdefault('environmentOutputs', {})[task_id] = str(self.runtime.environment_output(
                        task, spec.dataset, prepared['harnessImage'], experiment_id))
                    self.db.put_document('prepared', experiment_id, prepared)
                    self._check(experiment_id)
                    prepared['graderImages'][task_id] = self.runtime.prepare_agentbench_image(
                        task, Path(dataset['path']), prepared['harnessImage'], spec.resources, scope=experiment_id)
                    self.db.put_document('prepared', experiment_id, prepared)
                self._check(experiment_id)
            if task.source == "custom" and isinstance(self.engine.runner, DockerRunner):
                prepared.setdefault("graderImages", {})
                if task_id not in prepared["graderImages"]:
                    prepared["graderImages"][task_id] = self.runtime.prepare_test_image(task)
            if spec.project_environment and isinstance(self.engine.runner, DockerRunner):
                if 'agentImages' not in prepared:
                    raise ValueError('This experiment was prepared without project Agent environments. Create a new experiment; frozen plans cannot be silently upgraded.')
                if task_id not in prepared['agentImages']:
                    result = self.prepare_project_agent(task, spec, prepared['image'], prepared['graderImages'].get(task_id), experiment_id)
                    prepared['agentImages'][task_id] = result['imageId']
                    if task.source == 'custom':
                        prepared['graderImages'][task_id] = result['imageId']
                    prepared.setdefault('projectEnvironmentKeys', {})[task_id] = result['key']
                    self.db.put_document('prepared', experiment_id, prepared)
            if "skill-generated" in spec.arms and task_id not in prepared["contexts"]:
                prepared["contexts"][task_id] = self.generate(task, spec, prepared.get('agentImages', {}).get(task_id, prepared["image"]), experiment_id)["id"]
            if spec.evaluate_constraints and task_id not in prepared["constraints"]:
                package_key = spec.constraint_packages.get(task_id)
                prepared["constraints"][task_id] = (self._validate_constraints(package_key, task) if package_key else self.mine(task, spec, prepared["image"], experiment_id))["id"]
            self.db.put_document("prepared", experiment_id, prepared)
        try:
            start = start or self.db.get_document("executionRequests", experiment_id)["start"]
        except KeyError:
            pass
        if spec.prepare_only and not start:
            self.db.set_experiment_status(experiment_id, "ready")
            return {"prepared": True}
        self._check(experiment_id)
        self.db.set_experiment_status(experiment_id, "running")
        for run in self.db.list_runs(experiment_id):
            self._check(experiment_id)
            if run["status"] in {"completed", "failed", "cancelled"}:
                continue
            try:
                self._run(run, spec, prepared)
            except Interrupted:
                raise
            except Exception as error:
                self._check(experiment_id)
                self.db.update_run(run["id"], "failed", {"failure": self.redact(f"{type(error).__name__}: {error}")})
        self._check(experiment_id)
        runs = self.db.list_runs(experiment_id)
        status = "failed" if any(run["status"] == "failed" for run in runs) else "completed"
        self.db.set_experiment_status(experiment_id, status)
        return {"status": status, "runs": len(runs)}

    def _run(self, run: dict, spec: ExperimentSpec, prepared: dict):
        task = self.catalog.task(spec.dataset, run["taskId"])
        agent_image = prepared.get('agentImages', {}).get(task.id, prepared['image'])
        if spec.project_environment and isinstance(self.engine.runner, DockerRunner) and task.id not in prepared.get('agentImages', {}):
            raise ValueError('The frozen project Agent environment is missing; preparation must finish before coding.')
        if task.id in prepared.get("graderImages", {}):
            task = replace(task, image=prepared["graderImages"][task.id])
        key = (prepared["contexts"].get(task.id) if run["arm"] == "skill-generated" else
               spec.context_artifacts.get(task.id) if run["arm"] == "manual" else None)
        manifest = self._validate_artifact(key, task) if key else None
        # The union is removed for every non-historical arm, including arbitrary imported docs.
        declared = tuple({name for artifact in spec.context_artifacts.values()
                          for name in self.engine.artifacts.verify(artifact)["files"]})
        context_paths = tuple(set(declared) | set(manifest["files"] if manifest else []))
        def checkout():
            workspace = self.runtime.checkout(task, "solver")
            prepare_context(workspace, run["arm"], self.engine.artifacts.path_for(key) / "files" if key else None, context_paths)
            seal(workspace)
            return workspace
        pairing = {"task": task.solver_payload(), "model": asdict(spec.model), "resources": asdict(spec.resources),
                   "image": agent_image, "dataset": spec.dataset, "envNames": spec.env_names, "harness": prepared["harnessImage"], "graderImage": task.image}
        if spec.agent_args:
            pairing['agentArgs'] = spec.agent_args
        workflow = workflow_request(spec.solver_workflow, task.prompt)
        if workflow:
            pairing['workflow'] = workflow
        self.db.update_run(run["id"], "running", {"repository": task.repository, "commit": task.base_commit,
            "startedAt": run.get("startedAt", utc_now()), "contextArtifactId": key,
            "pairingHash": fingerprint(pairing), "promptHash": fingerprint(workflow['steps'] if workflow else task.prompt), "agentImageDigest": agent_image,
            "projectEnvironmentKey": prepared.get('projectEnvironmentKeys', {}).get(task.id),
            "mock": spec.model.provider == "mock" or not isinstance(self.engine.runner, DockerRunner), "agentArgs": list(spec.agent_args)})
        stage = self._agent(f"solve:{run['id']}", "solve", checkout, task.prompt, spec.model, spec, agent_image,
                            context_paths=context_paths, experiment_id=run["experimentId"])
        output = Path(stage["output"])
        safe_file(output, "graded.patch").read_bytes()
        mutation = safe_file(output, "context_mutation.patch")
        result = {"durationSeconds": stage["durationSeconds"], "outputDir": str(output), "solverRunId": stage["runId"],
            **usage(stage["metadata"]), "contextMutated": mutation.exists() and mutation.stat().st_size > 0,
            "evidenceIntegrity": verify_stage(stage, 'solve')}
        self.db.update_run(run["id"], "grading", result)
        grade_dir = output / "grading"
        dataset = self.catalog.verify(spec.dataset)
        binding = fingerprint({'version': 1, 'task': asdict(task), 'dataset': spec.dataset,
                               'patch': digest(output, 'graded.patch'), 'harness': prepared['harnessImage'],
                               'resources': asdict(spec.resources)})
        checkpoint = GradeCheckpoint(grade_dir, binding)
        self._check(run["experimentId"])
        grade = checkpoint.load()
        if grade is None:
            environment_options = {'environment_image': task.image} if task.source == 'agentbench' and prepared.get('environmentVersion') == 1 else {}
            grade = self.runtime.grade(task, Path(dataset["path"]), output / "graded.patch", grade_dir, spec.resources, prepared["harnessImage"], **environment_options)
            checkpoint.save(grade)
        if not isinstance(grade.get("resolved"), bool):
            raise ValueError("Grader must return a boolean resolved result.")
        result["testsPassed"] = grade["resolved"]
        result["grade"] = grade
        if grade.get("graderImageDigests"):
            result["pairingHash"] = fingerprint({**pairing, "actualGraderImages": grade["graderImageDigests"]})
        # Preserve functional evidence even if a later independent judge fails.
        self.db.update_run(run["id"], "grading", result)
        if spec.evaluate_constraints:
            package = self.db.get_document("constraintPackages", prepared["constraints"][task.id])
            document = package["document"]
            ids = [item["id"] for item in document["constraints"]]
            votes, records = [], []
            profiles = spec.judge_profiles or (spec.profiles.get("constraintJudge", spec.model),) * 3
            for index, profile in enumerate(profiles):
                if not ids:
                    break
                judge = f"judge-{index + 1}"
                prompt = judging_prompt(judge_id=judge)
                judge_stage = self._agent(f"judge:{run['id']}:{judge}", "judge-constraints",
                    lambda: self.runtime.evaluator_workspace("judge", {"constraints.json": json.dumps(document),
                        "task.json": json.dumps(task.solver_payload()), "candidate.patch": (output / "graded.patch").read_text(encoding="utf-8")}),
                    prompt, profile, spec, prepared["image"], experiment_id=run["experimentId"])
                vote_document = json.loads(safe_file(Path(judge_stage["workspace"]), "votes.json").read_text(encoding="utf-8"))
                if vote_document["judge"] != judge:
                    raise ValueError("Judge identity did not match the frozen invocation.")
                votes.append(judge_votes_from_document(vote_document))
                records.append({"profile": asdict(profile), "promptHash": fingerprint(prompt), "document": vote_document, "runId": judge_stage["runId"], "usage": usage(judge_stage["metadata"])})
            verdicts = aggregate_constraint_votes(ids, votes) if ids else {}
            result.update(constraintVerdict=issue_verdict(list(verdicts.values())), constraintVerdicts=verdicts,
                          constraintPackageId=package["id"], judgeRecords=records, constraintQuality=document["quality"],
                          constraintMode="research", constraintCount=len(ids), constraintHistoryVersion=package.get("historyVersion", 1))
        self._check(run["experimentId"])
        self.db.update_run(run["id"], "completed", result)

    def snapshot(self, *, compact: bool = False) -> dict:
        runs = self.db.list_runs(compact=compact)
        reuse_counts = Counter(run.get('contextArtifactId') for run in runs)
        artifacts = []
        for path in self.engine.artifacts.root.glob("*/*/manifest.json"):
            try:
                artifacts.append(self.artifact_record(path.parent.name, reuse_counts[path.parent.name]))
            except (ValueError, OSError, KeyError, TypeError) as error:
                artifacts.append({'id': path.parent.name, 'repository': 'Unreadable package', 'commit': '—',
                    'capability': 'tree-only', 'source': 'manual', 'files': 0, 'filePaths': [], 'bytes': 0,
                    'tasksReused': 0, 'status': 'invalid', 'informed': False, 'skillVersion': '', 'promptHash': '',
                    'builder': {'provider': 'unknown', 'model': 'unknown', 'thinking': 'off', 'maxTokens': 0},
                    'failure': self.redact(str(error))})
        constraints = []
        constraint_counts = {}
        for run in runs:
            package_id = run.get('constraintPackageId')
            if package_id:
                counts = constraint_counts.setdefault(package_id, Counter())
                counts.update((key, verdict) for key, verdict in run.get('constraintVerdicts', {}).items())
        for package in self.db.list_documents("constraintPackages"):
            counts = constraint_counts.get(package['id'], Counter())
            for constraint in package["document"]["constraints"]:
                satisfied, violated, neutral = (counts[constraint['id'], verdict] for verdict in ('satisfied', 'violated', 'neutral'))
                options = constraint["options"]
                constraints.append({"id": f"{package['id']}:{constraint['id']}", "packageId": package["id"],
                    "repository": package["repository"], "title": constraint["problem"],
                    "rationale": "\n".join(option["rationale"] for option in options),
                    "provenance": "\n".join(source for option in options for source in option["provenance"]),
                    "quality": package["document"]["quality"], "applicableRuns": satisfied + violated,
                    "satisfied": satisfied, "violated": violated, "neutral": neutral})
        operations = self.db.list_documents("operations")
        # Model requests, dataset gold patches and credentials are never part of a dashboard snapshot.
        experiments = self.db.list_experiments()
        for experiment in experiments:
            try:
                experiment['environmentPreparation'] = self.db.get_document('environmentProgress', experiment['id'])
            except KeyError:
                pass
        return {"experiments": experiments, "runs": runs, "artifacts": artifacts,
            "tokenBudgets": [self.budgets.snapshot(item['id']) for item in self.db.list_documents('tokenBudgets')],
            "constraints": constraints, "datasets": self.catalog.list(), "operations": [
                {**{key: item[key] for key in ("id", "kind", "status", "createdAt", "updatedAt", "failure", "progress") if key in item},
                 "taskId": item["payload"].get("taskId"), "dataset": item["payload"].get("dataset"),
                 "resultId": item.get("result", {}).get("id")} for item in operations],
            "activity": [{"id": item["id"], "kind": "system", "message": item["kind"],
                          "detail": item.get("failure", item["status"]), "timestamp": item["updatedAt"]} for item in sorted(operations, key=lambda item: item["updatedAt"], reverse=True)[:20]],
            "runtime": "desktop", "runner": type(self.engine.runner).__name__, "diagnostics": []}

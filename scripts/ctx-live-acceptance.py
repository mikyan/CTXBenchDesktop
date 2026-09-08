"""Explicitly paid CTXBench acceptance, using the current source and shared budget.

Run inside a Worker container with Docker/data mounts and configured credentials.
No daemon or service restart is needed. Existing experiments are not resumed.
The direct coordinator deliberately does not enqueue work into another Worker's
background queue. Results remain normal experiment records in the desktop.
"""
import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from ctxbench_worker.engine import create_engine_from_environment
from ctxbench_worker.database import Database
from ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from ctxbench_worker.workbench import Workbench


def grade_controls(wb, spec, prepared, output, emit):
    """Evaluator-only controls; callable after a failed solve, with no Agent calls."""
    controls = {}
    dataset_path = Path(wb.catalog.verify(spec.dataset)["path"])
    for task_id in spec.task_ids:
        task = replace(wb.catalog.task(spec.dataset, task_id), image=prepared["graderImages"][task_id])
        controls[task_id] = {}
        for label, content, expected in (("empty", "", False), ("gold", task.gold_patch, True)):
            assert content is not None
            folder = output / hashlib.sha256(task_id.encode()).hexdigest()[:16] / label
            folder.mkdir(parents=True)
            patch = folder / "input.patch"
            patch.write_text(content, encoding="utf-8")
            emit("evaluator-control", task=task_id, control=label)
            grade = wb.runtime.grade(task, dataset_path, patch, folder, ResourcePolicy(cpus=2, memory_gb=4, timeout_minutes=30, network="offline"), prepared["harnessImage"], environment_image=task.image)
            assert grade["resolved"] is expected, f"{task_id} {label} control failed"
            controls[task_id][label] = grade["resolved"]
    return controls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-paid", action="store_true", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--task", action="append", required=True)
    parser.add_argument("--budget", required=True)
    parser.add_argument("--agent-image", required=True)
    parser.add_argument("--harness-image", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--root", type=Path, default=Path("/var/lib/ctxbench"))
    args = parser.parse_args()
    root = args.root.resolve()
    os.environ["CTXBENCH_HOST_DATA_DIR"] = str(root)
    os.environ["CTXBENCH_BUNDLED_SKILL_DIR"] = str(Path(__file__).resolve().parents[1] / "skills" / "ctxbench-generate-context")
    assert os.environ.get("XIAOMI_TOKEN_PLAN_CN_API_KEY"), "Configure MiMo credentials in the Worker environment first."
    # Check exclusivity before engine construction refreshes the runtime Skill.
    database = Database(root / "ctxbench.sqlite3")
    experiments = database.list_experiments()
    assert not any(e["status"] in {"preparing", "running"} for e in experiments), "Pause active experiments before acceptance."
    assert not any(e["name"] == args.name for e in experiments), "Use a new acceptance name; existing experiments are never overwritten."
    assert not any(o["status"] in {"queued", "running"} for o in database.list_documents("operations")), "Wait for queued operations before acceptance."
    engine = create_engine_from_environment(root, "docker")
    wb = Workbench(engine, None)
    budget_before = wb.budgets.snapshot(args.budget)
    profile = ModelConfig("xiaomi-token-plan-cn", "mimo-v2.5", "high", 5_000_000)
    spec = ExperimentSpec(args.name, "ctxbench", args.dataset, ("none", "skill-generated"), 2, tuple(args.task),
                          profile, args.agent_image, ResourcePolicy(cpus=4, memory_gb=8, timeout_minutes=45, network="api-only"), 42,
                          profiles={role: profile for role in ("builder", "solver", "constraintMiner", "constraintJudge")},
                          env_names=("XIAOMI_TOKEN_PLAN_CN_API_KEY",), prepare_only=True, budget_id=args.budget,
                          builder_workflow={"setupCommands": [], "steps": [{"name": args.name, "prompt": None}]})
    wb.validate_inputs(spec)
    # A fresh step label separates this acceptance generation cache; it adds no
    # retrieval hints and does not change either arm's solver prompt.
    experiment = engine.create_experiment(spec)
    experiment_id = experiment["id"]
    output = root / ("acceptance-ctx-live-" + experiment_id)
    output.mkdir()
    report = {"experimentId": experiment_id, "sourceDataset": args.dataset, "tasks": args.task,
              "provider": profile.provider, "model": profile.model, "stageTokenLimit": profile.max_tokens,
              "sharedBudgetId": args.budget, "sharedBudgetLimit": budget_before["limitTokens"],
              "repeats": 2, "arms": list(spec.arms), "root": str(output), "verified": False}
    def emit(stage, **values):
        print(json.dumps({"experimentId": experiment_id, "stage": stage, **values}), flush=True)
    def stage_count():
        return sum(s.get("experimentId") == experiment_id and s["id"].startswith("context:") for s in engine.database.list_documents("stages"))
    try:
        emit("prepare-all-context")
        with wb.runtime.using_environment({"harnessImage": args.harness_image}):
            wb.run_experiment(experiment_id)
        assert engine.database.get_experiment(experiment_id)["status"] == "ready"
        assert all(r["status"] == "queued" for r in engine.database.list_runs(experiment_id)), "Solver started before all contexts were ready"
        prepared = engine.database.get_document("prepared", experiment_id)
        manifests = {key: engine.artifacts.verify(key) for key in prepared["contexts"].values()}
        generations = stage_count()
        expected_keys = {(t.repository, t.base_commit) for t in wb.validate_inputs(spec)}
        assert generations == len(expected_keys), f"Expected {len(expected_keys)} generation stages, got {generations}"
        report.update(generationStages=generations, preparedBeforeSolvers=True, contextIds=prepared["contexts"])
        emit("frozen-context-ready", generationStages=generations, solverRuns=len(args.task) * 4)
        # Reconstruct the coordinator, proving that preparation state is durable.
        wb = Workbench(engine, None)
        wb.run_experiment(experiment_id, start=True)
        runs = engine.database.list_runs(experiment_id)
        assert len(runs) == len(args.task) * 4
        pairs = defaultdict(list)
        for run in runs:
            pairs[run["pairId"]].append(run)
        for pair in pairs.values():
            assert {r["arm"] for r in pair} == set(spec.arms) and len(pair) == 2
            for key in ("promptHash", "commit", "agentImageDigest"):
                assert all(r.get(key) for r in pair) and len({r[key] for r in pair}) == 1, key
            # Grading extends this hash with actual grader image digests. An
            # ungraded timeout retains the pre-grade hash, not a comparable grade.
            if all(type(r.get("testsPassed")) is bool for r in pair):
                assert all(r.get("pairingHash") for r in pair) and len({r["pairingHash"] for r in pair}) == 1
        assert stage_count() == generations, "Repeated solves unexpectedly regenerated context"
        for key, manifest in manifests.items():
            assert engine.artifacts.verify(key) == manifest, "Frozen context changed"
        report.update(pairedRuns=len(runs), frozenContextUnchanged=True, generationsReused=True,
                      runs=[{k: r.get(k) for k in ("id", "taskId", "repeat", "arm", "status", "testsPassed", "mock", "pairingHash", "promptHash", "agentImageDigest", "contextArtifactId", "totalTokens")} for r in runs])
        report.update(controls=grade_controls(wb, spec, prepared, output, emit), harnessImage=prepared["harnessImage"])
        assert all(r["status"] == "completed" and not r.get("mock") and type(r.get("testsPassed")) is bool for r in runs), "Some real runs did not produce a functional verdict"
        report["verified"] = True
    except Exception as cause:
        report["error"] = wb.redact(f"{type(cause).__name__}: {cause}")
        if engine.database.get_experiment(experiment_id)["status"] in {"preparing", "running"}:
            engine.database.set_experiment_status(experiment_id, "failed")
        emit("failed", error=report["error"])
        return 1
    finally:
        after = wb.budgets.snapshot(args.budget)
        report["reportedTokenDelta"] = after["reportedTokens"] - budget_before["reportedTokens"]
        report["chargedTokenDelta"] = after["chargedTokens"] - budget_before["chargedTokens"]
        (output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        emit("finished", verified=report["verified"], report=str(output / "summary.json"))


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pyarrow.parquet as parquet
from grade_validation import require_agentbench_result


def load_rows(dataset: Path) -> list[dict[str, Any]]:
    return parquet.read_table(dataset).to_pylist() if dataset.suffix == ".parquet" else json.loads(dataset.read_text(encoding="utf-8"))


def load_row(dataset: Path, instance_id: str) -> dict[str, Any]:
    for row in load_rows(dataset):
        if row.get("instance_id") == instance_id:
            return row
    raise KeyError(f"Instance not found: {instance_id}")


def inspect_agentbench(dataset: Path) -> None:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in parquet.read_table(dataset).to_pylist():
        groups.setdefault(str(row["repo"]), []).append(row)
    result = [
        {
            "repo": repo,
            "count": len(rows),
            "example": rows[0]["instance_id"],
            "image": rows[0]["docker_image"],
            "promptLength": len(rows[0]["problem_description"]),
        }
        for repo, rows in sorted(groups.items(), key=lambda item: (len(item[1]), item[0]))
    ]
    print(json.dumps(result, indent=2))


def inspect_swebench(dataset: Path) -> None:
    rows = parquet.read_table(dataset).to_pylist()
    result = [
        {
            "instanceId": row["instance_id"],
            "repo": row["repo"],
            "promptLength": len(row["problem_statement"]),
            "patchLength": len(row["patch"]),
            "testPatchLength": len(row["test_patch"]),
        }
        for row in sorted(
            rows,
            key=lambda item: (
                len(item["problem_statement"]),
                len(item["patch"]),
                item["instance_id"],
            ),
        )[:30]
    ]
    print(json.dumps(result, indent=2))


def export_task(benchmark: str, dataset: Path, instance_id: str, output: Path) -> None:
    row = load_row(dataset, instance_id)
    output.mkdir(parents=True, exist_ok=True)
    if benchmark == "agentbench":
        solver = {
            "instanceId": row["instance_id"],
            "repository": f"https://github.com/{row['base_repo']}.git",
            "baseCommit": row["base_sha"],
            "prompt": row["problem_description"],
            "environmentImage": row["docker_image"],
            "source": "eth-sri/agentbench",
        }
    else:
        instance = row["instance_id"].replace("__", "_1776_").lower()
        owner = "tgloaguen" if "matplotlib" in instance else "swebench"
        environment_image = row.get("image") or f"{owner}/sweb.eval.x86_64.{instance}:latest"
        solver = {
            "instanceId": row["instance_id"],
            "repository": f"https://github.com/{row['repo']}.git",
            "baseCommit": row["base_commit"],
            "prompt": row["problem_statement"],
            "environmentImage": environment_image,
            "source": "SWE-bench/SWE-bench_Verified",
        }
    (output / "solver.json").write_text(json.dumps(solver, indent=2), encoding="utf-8")
    (output / "evaluator.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    gold_patch = row["clean_pr_patch"] if benchmark == "agentbench" else row["patch"]
    (output / "gold.patch").write_text(gold_patch, encoding="utf-8")
    print(json.dumps(solver, indent=2))


def grade_agentbench(dataset: Path, instance_id: str, patch_path: Path, output: Path) -> None:
    from agentbench.benchmarks.agentbench import AgentbenchInstance

    row = load_row(dataset, instance_id)
    repo_results = row.get("repo_test_after_pr_patch") or {}
    if isinstance(repo_results, str):
        repo_results = json.loads(repo_results)
    instance = AgentbenchInstance(
        instance_id=row["instance_id"],
        repo=row["base_repo"],
        task=row["problem_description"],
        patch=row["clean_pr_patch"],
        docker_image=row["docker_image"],
        commit=row["base_sha"],
        setup_commands=row["setup_commands"],
        repo_test_commands=row["repo_test_commands"],
        repo_test_runner=row["repo_test_runner"],
        test_file_names=row["test_file_names"],
        test_file_contents=row["test_file_contents"],
        test_file_runner=row["test_file_runner"],
        test_commands=row["test_commands"],
        repo_test_after_pr_patch=repo_results,
    )
    output.mkdir(parents=True, exist_ok=True)
    run_number = int(hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:8], 16)
    resolved = require_agentbench_result(lambda: instance.solve(patch_path.read_text(encoding="utf-8"), output, run_id=run_number))
    summary = {"benchmark": "agentbench", "instanceId": instance_id, "resolved": resolved}
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def grade_swebench(dataset: Path, instance_id: str, patch_path: Path, output: Path) -> None:
    from swebench.harness.run_evaluation import main as run_evaluation

    row = load_row(dataset, instance_id)
    output.mkdir(parents=True, exist_ok=True)
    local_dataset = output / "dataset.json"
    predictions = output / "predictions.json"
    local_dataset.write_text(json.dumps([row]), encoding="utf-8")
    predictions.write_text(
        json.dumps(
            {
                instance_id: {
                    "instance_id": instance_id,
                    "model_name_or_path": "ctxbench-candidate",
                    "model_patch": patch_path.read_text(encoding="utf-8"),
                }
            }
        ),
        encoding="utf-8",
    )
    previous_directory = Path.cwd()
    os.chdir(output)
    run_id = f"ctxbench-{hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:12]}"
    try:
        result_path = run_evaluation(
            dataset_name=str(local_dataset),
            split="test",
            instance_ids=[instance_id],
            predictions_path=str(predictions),
            max_workers=1,
            open_file_limit=4096,
            run_id=run_id,
            timeout=1800,
            rewrite_reports=False,
            modal=False,
        )
        result_file = Path(result_path).resolve()
        result = json.loads(result_file.read_text(encoding="utf-8"))
    finally:
        os.chdir(previous_directory)
    summary = {
        "benchmark": "swebench",
        "instanceId": instance_id,
        "resolved": instance_id in result.get("resolved_ids", []),
        "resultPath": str(result_file),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    catalog_parser = commands.add_parser("catalog")
    catalog_parser.add_argument("--dataset", type=Path, required=True)

    inspect_parser = commands.add_parser("inspect-agentbench")
    inspect_parser.add_argument("--dataset", type=Path, required=True)

    inspect_swe_parser = commands.add_parser("inspect-swebench")
    inspect_swe_parser.add_argument("--dataset", type=Path, required=True)

    export_parser = commands.add_parser("export-task")
    export_parser.add_argument("--benchmark", choices=("agentbench", "swebench"), required=True)
    export_parser.add_argument("--dataset", type=Path, required=True)
    export_parser.add_argument("--instance-id", required=True)
    export_parser.add_argument("--output", type=Path, required=True)

    for name in ("grade-agentbench", "grade-swebench"):
        grade_parser = commands.add_parser(name)
        grade_parser.add_argument("--dataset", type=Path, required=True)
        grade_parser.add_argument("--instance-id", required=True)
        grade_parser.add_argument("--patch", type=Path, required=True)
        grade_parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command.startswith("grade-"):
        from policy import configure
        configure()
    if args.command == "catalog":
        print(json.dumps(load_rows(args.dataset), default=str))
    elif args.command == "inspect-agentbench":
        inspect_agentbench(args.dataset)
    elif args.command == "inspect-swebench":
        inspect_swebench(args.dataset)
    elif args.command == "export-task":
        export_task(args.benchmark, args.dataset, args.instance_id, args.output)
    elif args.command == "grade-agentbench":
        grade_agentbench(args.dataset, args.instance_id, args.patch, args.output)
    else:
        grade_swebench(args.dataset, args.instance_id, args.patch, args.output)


if __name__ == "__main__":
    main()

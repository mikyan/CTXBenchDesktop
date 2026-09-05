import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from worker.ctxbench_worker.artifacts import ContextIdentity
from worker.ctxbench_worker.engine import create_mock_engine
from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy, RunResult
from worker.ctxbench_worker.runtime import git, seal
from worker.ctxbench_worker.workbench import Workbench, Interrupted, usage


class FixtureRunner:
    def __init__(self):
        self.calls = []
        self.fail_grade = False

    def run(self, spec):
        self.calls.append(spec)
        workspace, output = Path(spec.workspace), Path(spec.output_dir)
        output.mkdir(parents=True)
        if spec.mode == "generate-context":
            self.assert_builder = "PRIVATE_TARGET_TASK" not in spec.prompt and not (workspace / "review-archive.json").exists()
            files = output / "context" / "files"
            files.mkdir(parents=True)
            (files / "AGENTS.md").write_text("Frozen architecture", encoding="utf-8")
        else:
            (output / "graded.patch").write_text("patch", encoding="utf-8")
            (output / "context_mutation.patch").write_text("", encoding="utf-8")
        (output / "result.json").write_text(json.dumps({"status": "completed", "sessionStats": {"inputTokens": 17, "outputTokens": 3, "cost": .01}}))
        return RunResult(spec.run_id, "completed", 0, 1, spec.output_dir)


class WorkbenchTests(unittest.TestCase):
    def test_pi_nested_usage_preserves_cached_tokens(self):
        result = usage({'sessionStats': {'tokens': {'input': 10, 'output': 3, 'cacheRead': 100, 'total': 113}, 'cost': 0}})
        self.assertEqual(result['inputTokens'], 10)
        self.assertEqual(result['cacheReadTokens'], 100)
        self.assertEqual(result['totalTokens'], 113)
        self.assertEqual(result['costUsd'], 0)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = create_mock_engine(self.root)
        self.runner = FixtureRunner()
        self.engine.runner = self.runner
        self.workbench = Workbench(self.engine, None)
        self.source = self.root / "fixture"
        self.source.mkdir()
        (self.source / "code.py").write_text("value = 1\n")
        (self.source / "AGENTS.md").write_text("historical knowledge")
        self.commit = seal(self.source)
        self.dataset = self.workbench.catalog.register("Fixture", "custom", [{"id": "task/1", "repository": str(self.source), "baseCommit": self.commit,
            "prompt": "PRIVATE_TARGET_TASK", "image": "fixture:1", "test": {"command": ["true"], "hiddenPatch": "PRIVATE_HIDDEN_TEST"}, "goldPatch": "PRIVATE_GOLD_PATCH"}])
        model = ModelConfig("mock", "deterministic", "off", 1000)
        self.spec = ExperimentSpec("Test", "custom", self.dataset["id"], ("none", "skill-generated"), 2, ("task/1",), model, "fixture:1", ResourcePolicy(network="offline"), 42)
        self.grade_calls = 0
        def grade(task, dataset, patch, output, resources, image):
            self.grade_calls += 1
            if self.runner.fail_grade:
                self.runner.fail_grade = False
                raise RuntimeError("transient grader error")
            output.mkdir(parents=True, exist_ok=True)
            result = {"resolved": True}
            (output / "summary.json").write_text(json.dumps(result))
            return result
        self.workbench.runtime.grade = grade

    def test_prepare_once_repeat_and_restore_without_repaying_solver(self):
        experiment = self.workbench.create_experiment(replace(self.spec, prepare_only=True))
        self.workbench.run_experiment(experiment["id"])
        self.assertEqual(self.engine.database.get_experiment(experiment["id"])["status"], "ready")
        self.assertEqual(len(self.runner.calls), 1)
        self.assertTrue(self.runner.assert_builder)
        restored = Workbench(self.engine, None)
        restored.runtime.grade = self.workbench.runtime.grade
        restored.run_experiment(experiment["id"], start=True)
        self.assertEqual(len(self.runner.calls), 5)
        runs = self.engine.database.list_runs(experiment["id"])
        self.assertTrue(all(run["testsPassed"] for run in runs))
        self.assertEqual(len({run["pairingHash"] for run in runs}), 1)
        self.assertEqual(len({run["contextArtifactId"] for run in runs if run["arm"] != "none"}), 1)
        snapshot = restored.snapshot()
        self.assertNotIn("PRIVATE_GOLD_PATCH", json.dumps(snapshot))
        self.assertNotIn("PRIVATE_HIDDEN_TEST", json.dumps(snapshot))
        self.assertEqual(snapshot["artifacts"][0]["tasksReused"], 2)
        restored.run_experiment(experiment["id"], start=True)
        self.assertEqual(len(self.runner.calls), 5)

    def test_grader_failure_retry_uses_completed_solver_checkpoint(self):
        experiment = self.workbench.create_experiment(self.spec)
        self.runner.fail_grade = True
        self.workbench.run_experiment(experiment["id"])
        self.assertEqual(self.engine.database.get_experiment(experiment["id"])["status"], "failed")
        calls = len(self.runner.calls)
        self.workbench.control(experiment["id"], "retry")
        self.workbench.run_experiment(experiment["id"], start=True)
        self.assertEqual(len(self.runner.calls), calls)
        self.assertEqual(self.engine.database.get_experiment(experiment["id"])["status"], "completed")

    def test_pause_cancel_and_invalid_manual_baseline(self):
        experiment = self.workbench.create_experiment(self.spec)
        self.workbench.control(experiment["id"], "pause")
        with self.assertRaises(Interrupted):
            self.workbench.run_experiment(experiment["id"])
        self.assertFalse(self.runner.calls)
        self.workbench.control(experiment["id"], "cancel")
        self.assertTrue(all(run["status"] == "cancelled" for run in self.engine.database.list_runs()))
        with self.assertRaises(ValueError):
            self.workbench.import_context({"dataset": self.dataset["id"], "taskId": "task/1", "repository": str(self.source), "baseCommit": "0" * 40, "files": {"AGENTS.md": "wrong baseline"}})

    def test_context_tampering_is_rejected(self):
        artifact = self.workbench.import_context({"dataset": self.dataset["id"], "taskId": "task/1", "repository": str(self.source), "baseCommit": self.commit, "files": {"docs/context.md": "Architecture"}})
        path = self.engine.artifacts.path_for(artifact["id"]) / "files" / "docs/context.md"
        path.write_text("changed")
        with self.assertRaises(ValueError):
            self.engine.artifacts.verify(artifact["id"])

    def test_official_agentbench_fields_and_duplicate_ids(self):
        row = {"instance_id": "repo-1", "base_repo": "org/repo", "base_sha": "a" * 40, "problem_description": "Fix a bug", "docker_image": "image:1", "clean_pr_patch": "evaluator"}
        dataset = self.workbench.catalog.register("Official schema", "ctxbench", [row])
        task = self.workbench.catalog.task(dataset["id"], "repo-1")
        self.assertEqual(task.prompt, "Fix a bug")
        self.assertEqual(task.base_commit, "a" * 40)
        self.assertNotIn("evaluator", json.dumps(self.workbench.catalog.tasks(dataset["id"])))
        with self.assertRaises(ValueError):
            self.workbench.catalog.register("duplicate", "ctxbench", [row, row])

    def test_resume_prepared_request_is_durable(self):
        experiment = self.workbench.create_experiment(replace(self.spec, prepare_only=True))
        self.workbench.run_experiment(experiment['id'])
        self.workbench.control(experiment['id'], 'resume')
        # Simulate restart losing the in-memory start flag while preserving the queued operation.
        self.workbench.run_experiment(experiment['id'])
        self.assertEqual(self.engine.database.get_experiment(experiment['id'])['status'], 'completed')
        with self.assertRaises(ValueError):
            self.workbench.control(experiment['id'], 'resume')

    def test_bad_judge_output_is_retryable_without_repeating_solver(self):
        document = {'schemaVersion': 1, 'repository': 'local/fixture', 'quality': 'silver', 'constraints': [
            {'id': 'c1', 'problem': 'Preserve interface', 'options': [{'description': 'Stable interface', 'rationale': 'Compatibility',
             'applicability': 'API changes', 'referenceSnippets': [], 'provenance': ['PR1/comment1'], 'adopted': True}]}]}
        self.engine.database.put_document('constraintPackages', 'fixture-constraints', {'id': 'fixture-constraints', 'document': document})
        self.workbench.mine = lambda *args: {'id': 'fixture-constraints'}
        original = self.runner.run
        judge_calls = []
        def runner(spec):
            result = original(spec)
            if spec.mode == 'judge-constraints':
                judge_calls.append(spec)
                judge = spec.prompt.split('`')[1]
                output = {'schemaVersion': 1, 'judge': judge, 'votes': [{'constraintId': 'c1', 'applicable': True,
                          'verdict': 'violated', 'confidence': .9, 'rationale': 'Fixture violation', 'references': ['code.py']}]}
                (Path(spec.workspace) / 'votes.json').write_text('malformed' if len(judge_calls) == 1 else json.dumps(output))
            return result
        self.runner.run = runner
        experiment = self.workbench.create_experiment(replace(self.spec, repeats=1, evaluate_constraints=True))
        self.workbench.run_experiment(experiment['id'])
        failed = next(run for run in self.engine.database.list_runs(experiment['id']) if run['status'] == 'failed')
        self.assertTrue(failed['testsPassed'])
        solve_count = sum(call.mode == 'solve' for call in self.runner.calls)
        self.workbench.control(experiment['id'], 'retry')
        self.workbench.run_experiment(experiment['id'])
        self.assertEqual(sum(call.mode == 'solve' for call in self.runner.calls), solve_count)
        self.assertTrue(all(run['status'] == 'completed' and run['constraintVerdict'] == 'violated' for run in self.engine.database.list_runs(experiment['id'])))

    def test_reuse_frozen_constraints_without_history_access(self):
        package = {'id': 'existing', 'repository': str(self.source), 'commit': self.commit,
                   'document': {'schemaVersion': 1, 'repository': str(self.source), 'quality': 'silver', 'constraints': []}}
        self.engine.database.put_document('constraintPackages', 'existing', package)
        self.workbench.mine = lambda *args: self.fail('Frozen packages must not access history or miner')
        experiment = self.workbench.create_experiment(replace(self.spec, repeats=1, evaluate_constraints=True, constraint_packages={'task/1': 'existing'}))
        self.workbench.run_experiment(experiment['id'])
        self.assertTrue(all(run['constraintVerdict'] == 'neutral' for run in self.engine.database.list_runs(experiment['id'])))
        package['commit'] = 'f' * 40
        self.engine.database.put_document('constraintPackages', 'existing', package)
        with self.assertRaises(ValueError):
            self.workbench.create_experiment(replace(self.spec, evaluate_constraints=True, constraint_packages={'task/1': 'existing'}))


if __name__ == "__main__":
    unittest.main()

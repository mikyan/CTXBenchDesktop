import json
import tempfile
import threading
import time
import unittest
from dataclasses import asdict, replace
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
    def test_dependency_setup_fails_before_any_paid_builder_or_solver(self):
        from worker.ctxbench_worker.runner import DockerRunner
        self.engine.runner = DockerRunner(self.root / 'repositories', self.root / 'runs', self.root / 'requests')
        task = replace(self.workbench.catalog.task(self.dataset['id'], 'task/1'), source='agentbench')
        experiment = self.workbench.create_experiment(replace(self.spec, prepare_only=True))
        with patch.object(self.workbench, '_check'), patch.object(self.workbench.catalog, 'index', return_value={task.id: task}), \
             patch.object(self.workbench.runtime, 'resolve_image', return_value='sha256:' + 'a' * 64), \
             patch.object(self.workbench.runtime, 'prepare_agentbench_image', side_effect=RuntimeError('dependency setup failed')), \
             patch.object(self.workbench, 'generate') as generate:
            with self.assertRaisesRegex(RuntimeError, 'dependency setup failed'):
                self.workbench.run_experiment(experiment['id'])
        generate.assert_not_called()
        self.assertFalse(self.runner.calls)
        self.assertFalse(self.engine.database.list_documents('stages'))

    def test_evaluator_environment_is_frozen_once_and_legacy_preparation_is_not_rewritten(self):
        from worker.ctxbench_worker.runner import DockerRunner
        self.engine.runner = DockerRunner(self.root / 'repositories', self.root / 'runs', self.root / 'requests')
        task = replace(self.workbench.catalog.task(self.dataset['id'], 'task/1'), source='agentbench')
        experiment = self.workbench.create_experiment(replace(self.spec, prepare_only=True))
        with patch.object(self.workbench, '_check'), patch.object(self.workbench.catalog, 'index', return_value={task.id: task}), \
             patch.object(self.workbench.runtime, 'resolve_image', return_value='sha256:' + 'a' * 64), \
             patch.object(self.workbench.runtime, 'prepare_agentbench_image', return_value='sha256:' + 'b' * 64) as prepare, \
             patch.object(self.workbench, 'generate', return_value={'id': 'frozen-context'}):
            self.workbench.run_experiment(experiment['id'])
            self.workbench.run_experiment(experiment['id'])
            self.assertEqual(prepare.call_count, 1)
            frozen = self.engine.database.get_document('prepared', experiment['id'])
            self.assertEqual(frozen['graderImages'][task.id], 'sha256:' + 'b' * 64)
            # Older experiments retain their old harness and environment rules.
            frozen.pop('environmentVersion')
            frozen['graderImages'] = {}
            self.engine.database.put_document('prepared', experiment['id'], frozen)
            self.workbench.run_experiment(experiment['id'])
            self.assertEqual(prepare.call_count, 1)

    def test_cancel_environment_setup_only_targets_owned_unfinished_paths(self):
        from worker.ctxbench_worker.runner import DockerRunner
        self.engine.runner = DockerRunner(self.root / 'repositories', self.root / 'runs', self.root / 'requests')
        experiment = self.workbench.create_experiment(self.spec)
        active = self.root / 'evaluator-environments' / 'active'
        self.engine.database.put_document('prepared', experiment['id'], {'id': experiment['id'],
            'environmentOutputs': {'active': str(active), 'complete': str(self.root / 'complete')},
            'graderImages': {'complete': 'sha256:' + 'b' * 64}})
        with patch.object(self.workbench.runtime, 'cancel_grade') as cancel:
            self.workbench.control(experiment['id'], 'cancel')
        cancel.assert_called_once_with(active)

    def test_shared_budget_pauses_before_unfunded_solver_without_changing_profile(self):
        self.workbench.budgets.create('small', 1000, 'mock', 'deterministic')
        experiment = self.workbench.create_experiment(replace(self.spec, budget_id='small'))
        with self.assertRaisesRegex(Interrupted, 'Shared token budget'):
            self.workbench.run_experiment(experiment['id'])
        self.assertEqual(self.engine.database.get_experiment(experiment['id'])['status'], 'paused')
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.calls[0].model.max_tokens, 1000)
        self.assertEqual(self.workbench.budgets.snapshot('small')['chargedTokens'], 1000)

    def test_restart_reaps_paused_orphans_without_resuming_or_touching_completed_stages(self):
        operation = self.preparation()
        self.workbench.control_operation(operation['id'], 'pause')
        self.engine.database.put_document('stages', 'orphan', {'status': 'running', 'runId': 'orphan-run'})
        self.engine.database.put_document('stages', 'completed', {'status': 'completed', 'runId': 'completed-run'})
        cancelled = []
        self.runner.cancel = cancelled.append
        self.workbench.start()
        self.addCleanup(self.workbench.stop)
        self.workbench.start()
        self.assertEqual(cancelled, ['orphan-run'])
        self.assertEqual(self.engine.database.get_document('operations', operation['id'])['status'], 'paused')
        self.assertFalse(self.runner.calls)

    def preparation(self):
        return self.workbench.enqueue('context', {'dataset': self.dataset['id'], 'taskId': 'task/1',
            'model': asdict(self.spec.model), 'resources': asdict(self.spec.resources), 'agentImage': 'fixture:1'})

    def wait_operation(self, operation_id, status):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            operation = self.engine.database.get_document('operations', operation_id)
            if operation['status'] == status:
                return operation
            time.sleep(.01)
        self.fail(f'Operation did not reach {status}: {operation}')

    def test_standalone_preparation_pause_resume_and_cache(self):
        operation = self.preparation()
        self.workbench.control_operation(operation['id'], 'pause')
        self.workbench.start()
        self.addCleanup(self.workbench.stop)
        self.assertFalse(self.runner.calls)
        self.workbench.control_operation(operation['id'], 'resume')
        self.wait_operation(operation['id'], 'completed')
        self.assertEqual(len(self.runner.calls), 1)
        second = self.preparation()
        self.wait_operation(second['id'], 'completed')
        self.assertEqual(len(self.runner.calls), 1)
        with self.assertRaises(ValueError):
            self.workbench.control_operation(operation['id'], 'retry')

    def test_standalone_cancel_and_immediate_retry_cannot_lose_request(self):
        entered, cancelled, release = threading.Event(), threading.Event(), threading.Event()
        original = self.runner.run
        calls = []
        def runner(spec):
            calls.append(spec)
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(10))
                raise RuntimeError('Interrupted container')
            return original(spec)
        self.runner.run = runner
        self.runner.cancel = lambda run_id: cancelled.set()
        operation = self.preparation()
        self.workbench.start()
        self.addCleanup(self.workbench.stop)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(10))
        self.workbench.control_operation(operation['id'], 'cancel')
        self.assertTrue(cancelled.is_set())
        self.workbench.control_operation(operation['id'], 'retry')
        release.set()
        self.wait_operation(operation['id'], 'completed')
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0].workspace, calls[1].workspace)

    def test_standalone_stop_recovers_interrupted_stage(self):
        entered, release = threading.Event(), threading.Event()
        original = self.runner.run
        attempts = []
        def runner(spec):
            attempts.append(spec)
            if len(attempts) == 1:
                entered.set()
                self.assertTrue(release.wait(10))
                raise OSError('Worker shutdown interrupted container output')
            return original(spec)
        self.runner.run = runner
        self.runner.cancel = lambda run_id: release.set()
        operation = self.preparation()
        self.workbench.start()
        self.assertTrue(entered.wait(10))
        self.workbench.stop()
        self.assertEqual(self.engine.database.get_document('operations', operation['id'])['status'], 'queued')
        self.workbench = Workbench(self.engine, None)
        self.workbench.start()
        self.addCleanup(self.workbench.stop)
        self.wait_operation(operation['id'], 'completed')
        self.assertEqual(len(attempts), 2)

    def test_experiment_cancel_and_immediate_retry_cannot_lose_request(self):
        entered, release = threading.Event(), threading.Event()
        original = self.runner.run
        calls = []
        def runner(spec):
            calls.append(spec)
            if spec.mode == 'solve' and not entered.is_set():
                entered.set()
                self.assertTrue(release.wait(10))
                raise RuntimeError('Cancelled solver')
            return original(spec)
        self.runner.run = runner
        self.runner.cancel = lambda run_id: None
        experiment = self.workbench.create_experiment(replace(self.spec, repeats=1))
        self.workbench.start()
        self.addCleanup(self.workbench.stop)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(10))
        self.workbench.control(experiment['id'], 'cancel')
        self.workbench.control(experiment['id'], 'retry')
        release.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and self.engine.database.get_experiment(experiment['id'])['status'] != 'completed':
            time.sleep(.01)
        self.assertEqual(self.engine.database.get_experiment(experiment['id'])['status'], 'completed')
        self.assertEqual(sum(call.mode == 'solve' for call in calls), 3)

    def test_pi_nested_usage_preserves_cached_tokens(self):
        result = usage({'sessionStats': {'tokens': {'input': 10, 'output': 3, 'cacheRead': 100, 'total': 113}, 'cost': 0}})
        self.assertEqual(result['inputTokens'], 10)
        self.assertEqual(result['cacheReadTokens'], 100)
        self.assertEqual(result['totalTokens'], 113)
        self.assertEqual(result['costUsd'], 0)

    def test_preflight_is_read_only_and_low_disk_pauses_before_agent(self):
        before = len(self.engine.database.list_documents('operations'))
        report = self.workbench.preflight(self.spec)
        self.assertEqual(report['runs'], 4)
        self.assertEqual(len(self.engine.database.list_documents('operations')), before)
        self.assertFalse(self.runner.calls)
        experiment = self.workbench.create_experiment(self.spec)
        from worker.ctxbench_worker.runner import DockerRunner
        self.engine.runner = DockerRunner(self.root / 'repositories', self.root / 'runs', self.root / 'requests')
        with patch('worker.ctxbench_worker.workbench.storage_status', return_value={'ready': False}):
            with self.assertRaisesRegex(Interrupted, 'disk space'):
                self.workbench.run_experiment(experiment['id'])
        self.assertEqual(self.engine.database.get_experiment(experiment['id'])['status'], 'paused')
        self.assertFalse(self.engine.database.list_documents('stages'))

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
        self.assertEqual(self.workbench.snapshot()['artifacts'][0]['status'], 'invalid')

    def test_extra_context_file_and_dataset_mutation_are_rejected(self):
        artifact = self.workbench.import_context({'dataset': self.dataset['id'], 'taskId': 'task/1', 'repository': str(self.source),
            'baseCommit': self.commit, 'files': {'AGENTS.md': 'Architecture'}})
        (self.engine.artifacts.path_for(artifact['id']) / 'files' / 'extra.md').write_text('Unfrozen instructions')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            self.engine.artifacts.verify(artifact['id'])
        path = self.root / 'datasets' / (self.dataset['id'] + '.json')
        rows = json.loads(path.read_text())
        rows[0]['prompt'] = 'Changed task'
        path.write_text(json.dumps(rows))
        with self.assertRaisesRegex(ValueError, 'dataset contents'):
            self.workbench.catalog.task(self.dataset['id'], 'task/1')

    def test_corrupt_grade_is_retried_without_solver_payment(self):
        experiment = self.workbench.create_experiment(replace(self.spec, repeats=1))
        self.workbench.run_experiment(experiment['id'])
        run = self.engine.database.list_runs(experiment['id'])[0]
        (Path(run['outputDir']) / 'grading' / 'summary.json').write_text('{partial')
        self.engine.database.update_run(run['id'], 'failed', {'failure': 'Interrupted evidence write'})
        self.engine.database.set_experiment_status(experiment['id'], 'failed')
        calls, grades = len(self.runner.calls), self.grade_calls
        self.workbench.control(experiment['id'], 'retry')
        self.workbench.run_experiment(experiment['id'])
        self.assertEqual(len(self.runner.calls), calls)
        self.assertEqual(self.grade_calls, grades + 1)

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

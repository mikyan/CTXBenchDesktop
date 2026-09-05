import tempfile
import unittest
from pathlib import Path

from worker.ctxbench_worker.database import Database
from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from worker.ctxbench_worker.planner import plan_runs


class DatabaseTests(unittest.TestCase):
    def test_experiment_and_run_plan_are_one_transaction(self) -> None:
        spec = ExperimentSpec(
            name="persisted",
            benchmark="custom",
            dataset="manifest.jsonl",
            arms=("none", "manual"),
            repeats=2,
            task_ids=("one", "two"),
            model=ModelConfig("mock", "solver", "off", 2048),
            agent_image="ctxbench/agent-pi:0.1.0",
            resources=ResourcePolicy(network="offline"),
            seed=7,
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "state.sqlite3")
            record = database.create_experiment("exp-one", spec, plan_runs("exp-one", spec))
            self.assertEqual(record["totalRuns"], 8)
            self.assertEqual(record["resources"]["network"], "offline")
            self.assertEqual(database.list_experiments()[0]["id"], "exp-one")
            run = database.list_runs()[0]
            database.update_run(run['id'], 'completed', {'testsPassed': True, 'judgeRecords': [{'rationale': 'Detailed evidence'}], 'grade': {'resolved': True}, 'constraintVerdicts': {'one': 'satisfied'}})
            compact = database.list_runs(compact=True)[0]
            self.assertNotIn('judgeRecords', compact)
            self.assertNotIn('grade', compact)
            self.assertEqual(compact['constraintVerdicts'], {'one': 'satisfied'})
            self.assertEqual(database.get_run(run['id'])['judgeRecords'][0]['rationale'], 'Detailed evidence')
            database.put_document('datasets', 'one', {'id': 'one', 'name': 'Example', 'privatePayload': 'not returned'})
            self.assertEqual(database.list_document_summaries('datasets', ('id', 'name')), [{'id': 'one', 'name': 'Example'}])


if __name__ == "__main__":
    unittest.main()

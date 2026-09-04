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


if __name__ == "__main__":
    unittest.main()

import unittest

from worker.ctxbench_worker.models import ExperimentSpec, ModelConfig, ResourcePolicy
from worker.ctxbench_worker.planner import plan_runs, validate_experiment


class PlannerTests(unittest.TestCase):
    def spec(self) -> ExperimentSpec:
        return ExperimentSpec(
            name="paired",
            benchmark="ctxbench",
            dataset="agentbench",
            arms=("none", "skill-generated"),
            repeats=3,
            task_ids=("a", "b"),
            model=ModelConfig("mock", "deterministic", "off", 4096),
            agent_image="ctxbench/agent-pi:0.1.0",
            resources=ResourcePolicy(),
            seed=42,
        )

    def test_plans_are_deterministic_and_pair_complete(self) -> None:
        first = plan_runs("exp", self.spec())
        second = plan_runs("exp", self.spec())
        self.assertEqual(first, second)
        self.assertEqual(len(first), 12)
        pairs = {run.pair_id for run in first}
        self.assertEqual(len(pairs), 6)
        for pair in pairs:
            self.assertEqual(
                {run.arm for run in first if run.pair_id == pair},
                {"none", "skill-generated"},
            )

    def test_requires_baseline(self) -> None:
        spec = self.spec()
        invalid = ExperimentSpec(**{**spec.__dict__, "arms": ("manual",)})
        self.assertIn("The none arm is required for a causal baseline.", validate_experiment(invalid))


if __name__ == "__main__":
    unittest.main()

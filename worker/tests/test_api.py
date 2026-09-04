import unittest

from worker.ctxbench_worker.api import ExperimentInput, _spec


class ApiInputTests(unittest.TestCase):
    def test_four_model_profiles_are_preserved(self) -> None:
        profile = {"provider": "mock", "model": "deterministic", "thinking": "off", "maxTokens": 4096}
        value = ExperimentInput.model_validate(
            {
                "name": "profiles",
                "benchmark": "ctxbench",
                "dataset": "agentbench",
                "arms": ["none", "skill-generated"],
                "repeats": 2,
                "taskIds": ["a"],
                "model": profile,
                "profiles": {
                    "builder": {**profile, "model": "builder"},
                    "solver": {**profile, "model": "solver"},
                    "constraintMiner": {**profile, "model": "miner"},
                    "constraintJudge": {**profile, "model": "judge"},
                },
                "agentImage": "ctxbench/agent-pi:0.1.0",
                "resources": {"cpus": 2, "memoryGb": 4, "timeoutMinutes": 10, "network": "offline"},
                "seed": 42,
            }
        )
        spec = _spec(value)
        self.assertEqual(set(spec.profiles), {"builder", "solver", "constraintMiner", "constraintJudge"})
        self.assertEqual(spec.profiles["constraintJudge"].model, "judge")


if __name__ == "__main__":
    unittest.main()

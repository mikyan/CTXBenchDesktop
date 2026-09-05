import unittest

from worker.ctxbench_worker.constraint_prompts import judging_prompt, mining_prompt


class ConstraintPromptTests(unittest.TestCase):
    def test_miner_keeps_target_task_out_of_scope(self) -> None:
        prompt = mining_prompt()
        self.assertIn("constraints.json", prompt)
        self.assertIn("target PR", prompt)
        self.assertIn("intentionally absent", prompt)

    def test_judge_names_independent_output(self) -> None:
        prompt = judging_prompt(judge_id="judge-2", output_name="vote-2.json")
        self.assertIn("`judge-2`", prompt)
        self.assertIn("`vote-2.json`", prompt)
        self.assertIn("Tests passing does not imply compliance", prompt)


if __name__ == "__main__":
    unittest.main()

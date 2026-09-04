import unittest

from worker.ctxbench_worker.constraints import (
    JudgeVote,
    ReviewComment,
    candidate_similarity,
    clusters,
    compliance_metrics,
    majority_verdict,
    review_windows,
    structural_similarity,
)


class ConstraintPipelineTests(unittest.TestCase):
    def test_review_windows_do_not_leak_future_comments(self) -> None:
        comments = [
            ReviewComment(str(index), "pr", "review", "thread", f"body {index}", f"2026-01-{index + 1:02d}")
            for index in range(8)
        ]
        windows = review_windows(comments, size=6)
        self.assertEqual(len(windows), 2)
        self.assertEqual(len(windows[0].comments), 6)
        self.assertEqual(windows[0].previous_context, ())
        self.assertEqual(windows[1].previous_context, windows[0].comments)
        self.assertEqual(len(windows[1].comments), 2)

    def test_paper_compatible_similarity_weights_and_threshold(self) -> None:
        structure = structural_similarity(same_thread=False, same_review=True, same_pr=True)
        score = candidate_similarity(0.8, 0.6, structure)
        self.assertAlmostEqual(score, 0.748)
        self.assertEqual(clusters([[1, score, 0.1], [score, 1, 0.2], [0.1, 0.2, 1]]), [(0, 1), (2,)])

    def test_three_judge_majority_and_neutral_fallback(self) -> None:
        votes = [
            JudgeVote("a", True, "violated", 0.9, "r"),
            JudgeVote("b", True, "violated", 0.8, "r"),
            JudgeVote("c", True, "satisfied", 0.7, "r"),
        ]
        self.assertEqual(majority_verdict(votes), "violated")
        split = [
            JudgeVote("a", True, "violated", 0.9, "r"),
            JudgeVote("b", True, "satisfied", 0.8, "r"),
            JudgeVote("c", False, "neutral", 0.7, "r"),
        ]
        self.assertEqual(majority_verdict(split), "neutral")

    def test_ppvr_uses_passing_applicable_denominator(self) -> None:
        metrics = compliance_metrics(
            [(True, "satisfied"), (True, "violated"), (False, "violated"), (True, "neutral")]
        )
        self.assertEqual(metrics.dsr, 0.25)
        self.assertEqual(metrics.dvr, 0.5)
        self.assertEqual(metrics.dnr, 0.25)
        self.assertEqual(metrics.ppvr, 0.5)


if __name__ == "__main__":
    unittest.main()

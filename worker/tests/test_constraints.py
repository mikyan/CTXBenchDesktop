import unittest

from worker.ctxbench_worker.constraints import (
    JudgeVote,
    ReviewComment,
    aggregate_constraint_votes,
    candidate_similarity,
    clusters,
    compliance_metrics,
    design_constraints_from_document,
    judge_votes_from_document,
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

    def test_parses_mined_constraints_and_judge_votes(self) -> None:
        constraints = design_constraints_from_document(
            {
                "schemaVersion": 1,
                "repository": "acme/widget",
                "quality": "silver",
                "constraints": [
                    {
                        "id": "stable-api",
                        "problem": "Public names drift.",
                        "options": [
                            {
                                "description": "Keep names stable.",
                                "rationale": "Clients depend on them.",
                                "applicability": "Public API changes.",
                                "referenceSnippets": ["keep stable"],
                                "provenance": ["PR #7"],
                                "adopted": True,
                            }
                        ],
                    }
                ],
            }
        )
        votes = judge_votes_from_document(
            {
                "schemaVersion": 1,
                "judge": "judge-1",
                "votes": [
                    {
                        "constraintId": "stable-api",
                        "applicable": True,
                        "verdict": "satisfied",
                        "confidence": 0.8,
                        "rationale": "Name is unchanged.",
                        "references": ["src/api.py"],
                    }
                ],
            }
        )
        self.assertEqual(constraints[0].quality, "silver")
        self.assertTrue(constraints[0].options[0].adopted)
        self.assertEqual(votes[0][0], "stable-api")
        self.assertEqual(votes[0][1].verdict, "satisfied")

    def test_aggregates_independent_votes_by_constraint(self) -> None:
        vote_sets = [
            [("c1", JudgeVote("a", True, "violated", 0.8, "r"))],
            [("c1", JudgeVote("b", True, "violated", 0.9, "r"))],
            [("c1", JudgeVote("c", True, "satisfied", 0.7, "r"))],
        ]
        self.assertEqual(aggregate_constraint_votes(["c1"], vote_sets), {"c1": "violated"})


if __name__ == "__main__":
    unittest.main()

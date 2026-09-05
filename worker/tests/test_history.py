import unittest

from worker.ctxbench_worker.history import mine_review_archive


class FakeClient:
    def get(self, path: str, query: dict[str, str] | None = None):
        if path.endswith("pulls/comments"):
            if query and query["page"] != "1":
                return []
            return [
                {
                    "id": 11,
                    "pull_request_review_id": 22,
                    "pull_request_url": "https://api.github.com/repos/acme/widget/pulls/7",
                    "body": "Keep public names stable.",
                    "created_at": "2024-01-02T00:00:00Z",
                    "path": "src/api.py",
                    "line": 10,
                    "commit_id": "abc",
                    "diff_hunk": "@@ public api",
                },
                {
                    "id": 12,
                    "pull_request_review_id": 23,
                    "pull_request_url": "https://api.github.com/repos/acme/widget/pulls/8",
                    "body": "Future comment",
                    "created_at": "2025-01-02T00:00:00Z",
                    "path": "src/future.py",
                },
            ]
        if path.endswith("pulls/7"):
            return {
                "html_url": "https://github.com/acme/widget/pull/7",
                "title": "Stable API",
                "body": "Fixes #3",
                "merged_at": "2024-01-03T00:00:00Z",
                "merge_commit_sha": "def",
                "base": {"sha": "base"},
            }
        if path.endswith("pulls/7/commits"):
            return [
                {
                    "sha": "abc",
                    "commit": {
                        "message": "Apply review",
                        "author": {"date": "2024-01-03T00:00:00Z"},
                    },
                }
            ]
        if path.endswith("pulls/7/files"):
            return [{"filename": "src/api.py", "status": "modified", "patch": "@@ stable name"}]
        raise AssertionError(path)


class HistoryMiningTests(unittest.TestCase):
    def test_excludes_post_cutoff_comments_and_preserves_provenance(self) -> None:
        archive = mine_review_archive(
            "acme/widget",
            "2024-06-01T00:00:00Z",
            client=FakeClient(),
            max_comments=10,
            max_pull_requests=5,
        )
        self.assertEqual(
            archive["stats"],
            {"pullRequests": 1, "inspectedPullRequests": 1, "comments": 1},
        )
        pull = archive["pullRequests"][0]
        self.assertEqual(pull["id"], "#7")
        self.assertEqual(pull["issueIds"], ["3"])
        self.assertEqual(pull["comments"][0]["threadId"], "11")
        self.assertEqual(pull["commits"][0]["sha"], "abc")
        self.assertEqual(pull["files"][0]["path"], "src/api.py")

    def test_rejects_non_github_repository_identifiers(self) -> None:
        with self.assertRaises(ValueError):
            mine_review_archive("https://example.com/repo", "2024-01-01T00:00:00Z", client=FakeClient())


if __name__ == "__main__":
    unittest.main()

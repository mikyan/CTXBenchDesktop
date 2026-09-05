from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Protocol


class JsonClient(Protocol):
    def get(self, path: str, query: dict[str, str] | None = None) -> Any: ...


class GitHubClient:
    def __init__(self, token: str | None = None, api_root: str = "https://api.github.com"):
        self.token = token
        self.api_root = api_root.rstrip("/")

    def get(self, path: str, query: dict[str, str] | None = None) -> Any:
        url = f"{self.api_root}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "CTXBench-Desktop/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _pull_number(url: str) -> int:
    match = re.search(r"/pulls/(\d+)$", url)
    if not match:
        raise ValueError(f"Unrecognized GitHub pull request URL: {url}")
    return int(match.group(1))


def mine_review_archive(
    repository: str,
    cutoff: str,
    *,
    client: JsonClient,
    max_comments: int = 50,
    max_pull_requests: int = 10,
    max_pages: int = 10,
) -> dict[str, Any]:
    """Collect only merged, pre-cutoff GitHub code-review threads."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repository must use the GitHub owner/name form.")
    if max_comments < 1 or max_pull_requests < 1 or max_pages < 1:
        raise ValueError("Mining limits must be positive.")
    cutoff_time = _instant(cutoff)
    comments: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        values = client.get(
            f"repos/{repository}/pulls/comments",
            {"sort": "created", "direction": "desc", "per_page": "100", "page": str(page)},
        )
        if not isinstance(values, list) or not values:
            break
        eligible = [
            value
            for value in values
            if value.get("body") and _instant(str(value["created_at"])) <= cutoff_time
            and _instant(str(value.get("updated_at") or value["created_at"])) <= cutoff_time
        ]
        comments.extend(eligible)

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        grouped[_pull_number(str(comment["pull_request_url"]))].append(comment)

    pull_requests: list[dict[str, Any]] = []
    retained_comments = 0
    inspected_pull_requests = 0
    ordered_groups = sorted(
        grouped.items(),
        key=lambda item: max(_instant(str(value["created_at"])) for value in item[1]),
        reverse=True,
    )
    for number, values in ordered_groups:
        if inspected_pull_requests >= max_pull_requests or retained_comments >= max_comments:
            break
        inspected_pull_requests += 1
        pull = client.get(f"repos/{repository}/pulls/{number}")
        merged_at = pull.get("merged_at") if isinstance(pull, dict) else None
        if not merged_at or _instant(str(merged_at)) > cutoff_time:
            continue
        # GitHub does not expose historic PR text revisions. Do not use text edited after cutoff.
        historic_text = not pull.get("updated_at") or _instant(str(pull["updated_at"])) <= cutoff_time
        body = (pull.get("body") or "") if historic_text else ""
        values = values[: max_comments - retained_comments]
        commits = client.get(
            f"repos/{repository}/pulls/{number}/commits", {"per_page": "100"}
        )
        files = client.get(f"repos/{repository}/pulls/{number}/files", {"per_page": "100"})
        pull_requests.append(
            {
                "id": f"#{number}",
                "url": pull.get("html_url"),
                "title": pull.get("title") if historic_text else "",
                "body": body,
                "issueIds": sorted(set(re.findall(r"#(\d+)", body))),
                "baseCommit": pull.get("base", {}).get("sha"),
                "mergeCommit": pull.get("merge_commit_sha"),
                "mergedAt": merged_at,
                "comments": [
                    {
                        "id": str(comment["id"]),
                        "reviewId": str(comment.get("pull_request_review_id") or ""),
                        "threadId": str(comment.get("in_reply_to_id") or comment["id"]),
                        "body": comment["body"],
                        "createdAt": comment["created_at"],
                        "path": comment.get("path"),
                        "line": comment.get("line") or comment.get("original_line"),
                        "commit": comment.get("commit_id"),
                        "diffHunk": comment.get("diff_hunk"),
                    }
                    for comment in sorted(values, key=lambda value: value["created_at"])
                ],
                "commits": [
                    {
                        "sha": commit.get("sha"),
                        "message": commit.get("commit", {}).get("message"),
                        "authoredAt": commit.get("commit", {}).get("author", {}).get("date"),
                    }
                    for commit in commits
                ],
                "files": [
                    {
                        "path": file.get("filename"),
                        "status": file.get("status"),
                        "patch": file.get("patch"),
                    }
                    for file in files
                ],
            }
        )
        retained_comments += len(values)
    return {
        "schemaVersion": 1,
        "repository": repository,
        "cutoff": cutoff_time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "source": "github-pull-request-review-comments",
        "limits": {
            "maxComments": max_comments,
            "maxPullRequests": max_pull_requests,
            "maxPages": max_pages,
        },
        "pullRequests": pull_requests,
        "stats": {
            "pullRequests": len(pull_requests),
            "inspectedPullRequests": inspected_pull_requests,
            "comments": retained_comments,
        },
    }

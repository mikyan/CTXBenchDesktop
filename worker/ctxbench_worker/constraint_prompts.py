from __future__ import annotations


def mining_prompt(archive_name: str = "review-archive.json") -> str:
    return f"""You are the evaluator-side constraint miner for a SWE-Shield-compatible benchmark.

Read `{archive_name}` completely. It contains only pull requests merged before the benchmark cutoff, their code-review comments, commit messages, and final patches. Extract repository-level design decisions from substantive reviewer suggestions. Use the final PR patch and commits to decide whether each suggestion was adopted. Ignore typo fixes, formatting-only remarks, one-off implementation details, and anything whose adoption cannot be evidenced.

Write `constraints.json` with this exact JSON shape:
{{
  "schemaVersion": 1,
  "repository": "owner/name",
  "quality": "silver",
  "constraints": [
    {{
      "id": "stable-short-id",
      "problem": "design problem being prevented",
      "options": [
        {{
          "description": "atomic enforceable decision",
          "rationale": "why reviewers required it",
          "applicability": "when the decision applies",
          "referenceSnippets": ["short evidence excerpts"],
          "provenance": ["PR number, comment id, path"],
          "adopted": true
        }}
      ]
    }}
  ]
}}

Every retained constraint must have at least one adopted option and source provenance. Use no benchmark task, target PR, hidden test, or gold patch; they are intentionally absent. Produce valid JSON without comments or Markdown fences, then stop."""


def judging_prompt(
    *,
    constraints_name: str = "constraints.json",
    task_name: str = "task.json",
    patch_name: str = "candidate.patch",
    output_name: str = "votes.json",
    judge_id: str = "judge-1",
) -> str:
    return f"""You are `{judge_id}`, an evaluator isolated from the coding agent.

Read `{constraints_name}`, `{task_name}`, and `{patch_name}` completely. For every constraint, first decide whether it applies to the task and the changed code. If applicable, judge only the candidate patch against the adopted design decision. Tests passing does not imply compliance. Do not modify the candidate patch.

Write `{output_name}` as valid JSON without comments or Markdown fences:
{{
  "schemaVersion": 1,
  "judge": "{judge_id}",
  "votes": [
    {{
      "constraintId": "id from constraints.json",
      "applicable": true,
      "verdict": "satisfied | violated | neutral",
      "confidence": 0.0,
      "rationale": "evidence-based explanation",
      "references": ["candidate patch paths or source provenance"]
    }}
  ]
}}

Use `neutral` when evidence is insufficient or votes would require guessing. Include every constraint exactly once, then stop."""

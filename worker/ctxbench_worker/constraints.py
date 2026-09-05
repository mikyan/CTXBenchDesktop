from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Sequence

Verdict = Literal["satisfied", "violated", "neutral"]


@dataclass(frozen=True)
class ReviewComment:
    id: str
    pr_id: str
    review_id: str
    thread_id: str
    body: str
    created_at: str
    commit: str | None = None


@dataclass(frozen=True)
class ReviewWindow:
    thread_id: str
    comments: tuple[ReviewComment, ...]
    previous_context: tuple[ReviewComment, ...]


@dataclass(frozen=True)
class ConstraintOption:
    description: str
    rationale: str
    applicability: str
    reference_snippets: tuple[str, ...]
    provenance: tuple[str, ...]
    adopted: bool


@dataclass(frozen=True)
class DesignConstraint:
    id: str
    repository: str
    problem: str
    options: tuple[ConstraintOption, ...]
    quality: Literal["silver", "gold"] = "silver"


@dataclass(frozen=True)
class JudgeVote:
    judge: str
    applicable: bool
    verdict: Verdict
    confidence: float
    rationale: str
    references: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComplianceMetrics:
    dsr: float
    dvr: float
    dnr: float
    ppvr: float
    issues: int
    passing_applicable: int


def design_constraints_from_document(value: dict[str, Any]) -> tuple[DesignConstraint, ...]:
    if value.get("schemaVersion") != 1 or not isinstance(value.get("repository"), str):
        raise ValueError("Invalid constraint document header.")
    raw_constraints = value.get("constraints")
    if not isinstance(raw_constraints, list):
        raise ValueError("Constraint document must contain a constraints array.")
    quality = value.get("quality", "silver")
    if quality not in {"silver", "gold"}:
        raise ValueError("Constraint quality must be silver or gold.")
    constraints: list[DesignConstraint] = []
    for raw in raw_constraints:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("problem"):
            raise ValueError("Every constraint requires an id and problem.")
        options = raw.get("options")
        if not isinstance(options, list) or not options:
            raise ValueError(f"Constraint {raw.get('id')} requires options.")
        parsed_options = tuple(
            ConstraintOption(
                description=str(option["description"]),
                rationale=str(option["rationale"]),
                applicability=str(option["applicability"]),
                reference_snippets=tuple(str(item) for item in option.get("referenceSnippets", [])),
                provenance=tuple(str(item) for item in option.get("provenance", [])),
                adopted=bool(option["adopted"]),
            )
            for option in options
        )
        if not any(option.adopted for option in parsed_options):
            raise ValueError(f"Constraint {raw['id']} has no adopted option.")
        constraints.append(
            DesignConstraint(
                id=str(raw["id"]),
                repository=value["repository"],
                problem=str(raw["problem"]),
                options=parsed_options,
                quality=quality,
            )
        )
    if len({constraint.id for constraint in constraints}) != len(constraints):
        raise ValueError("Constraint ids must be unique.")
    return tuple(constraints)


def judge_votes_from_document(value: dict[str, Any]) -> tuple[tuple[str, JudgeVote], ...]:
    if value.get("schemaVersion") != 1 or not isinstance(value.get("judge"), str):
        raise ValueError("Invalid judge document header.")
    raw_votes = value.get("votes")
    if not isinstance(raw_votes, list):
        raise ValueError("Judge document must contain a votes array.")
    votes: list[tuple[str, JudgeVote]] = []
    for raw in raw_votes:
        if not isinstance(raw, dict) or raw.get("verdict") not in {"satisfied", "violated", "neutral"}:
            raise ValueError("Invalid judge vote.")
        confidence = float(raw["confidence"])
        if not 0 <= confidence <= 1:
            raise ValueError("Judge confidence must be between zero and one.")
        votes.append(
            (
                str(raw["constraintId"]),
                JudgeVote(
                    judge=value["judge"],
                    applicable=bool(raw["applicable"]),
                    verdict=raw["verdict"],
                    confidence=confidence,
                    rationale=str(raw["rationale"]),
                    references=tuple(str(item) for item in raw.get("references", [])),
                ),
            )
        )
    if len({constraint_id for constraint_id, _ in votes}) != len(votes):
        raise ValueError("A judge may vote only once per constraint.")
    return tuple(votes)


def review_windows(comments: Iterable[ReviewComment], size: int = 6) -> list[ReviewWindow]:
    """Create non-overlapping per-thread windows carrying only the previous window as context."""
    if size < 1:
        raise ValueError("Window size must be positive.")
    grouped: dict[str, list[ReviewComment]] = defaultdict(list)
    for comment in comments:
        grouped[comment.thread_id].append(comment)

    result: list[ReviewWindow] = []
    for thread_id in sorted(grouped):
        ordered = sorted(grouped[thread_id], key=lambda item: (item.created_at, item.id))
        previous: tuple[ReviewComment, ...] = ()
        for offset in range(0, len(ordered), size):
            current = tuple(ordered[offset : offset + size])
            result.append(ReviewWindow(thread_id, current, previous))
            previous = current
    return result


def structural_similarity(
    *, same_thread: bool, same_review: bool, same_pr: bool, provenance_bonus: float = 0.0
) -> float:
    base = 1.0 if same_thread else 0.7 if same_review else 0.3 if same_pr else 0.0
    return min(1.0, max(0.0, base + provenance_bonus))


def candidate_similarity(problem_similarity: float, suggestion_similarity: float, structure: float) -> float:
    """Versioned SWE-Shield-compatible default: semantic .8 + structural .2."""
    semantic = 0.8 * problem_similarity + 0.2 * suggestion_similarity
    return 0.8 * semantic + 0.2 * structure


def clusters(similarity: Sequence[Sequence[float]], threshold: float = 0.6) -> list[tuple[int, ...]]:
    """Connected-link clustering at the paper-compatible threshold."""
    count = len(similarity)
    if any(len(row) != count for row in similarity):
        raise ValueError("Similarity matrix must be square.")
    parents = list(range(count))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parents[root_right] = root_left

    for left in range(count):
        for right in range(left + 1, count):
            if similarity[left][right] >= threshold:
                union(left, right)
    grouped: dict[int, list[int]] = defaultdict(list)
    for index in range(count):
        grouped[find(index)].append(index)
    return [tuple(values) for _, values in sorted(grouped.items(), key=lambda item: min(item[1]))]


def majority_verdict(votes: Sequence[JudgeVote]) -> Verdict:
    if len({vote.judge for vote in votes}) != len(votes):
        raise ValueError("Judge identities must be independent and unique.")
    applicable = [vote for vote in votes if vote.applicable]
    counts = Counter(vote.verdict for vote in applicable)
    if counts["satisfied"] >= 2:
        return "satisfied"
    if counts["violated"] >= 2:
        return "violated"
    return "neutral"


def aggregate_constraint_votes(
    constraint_ids: Sequence[str], vote_sets: Sequence[Sequence[tuple[str, JudgeVote]]]
) -> dict[str, Verdict]:
    expected = set(constraint_ids)
    grouped: dict[str, list[JudgeVote]] = {constraint_id: [] for constraint_id in constraint_ids}
    for vote_set in vote_sets:
        if {constraint_id for constraint_id, _ in vote_set} != expected:
            raise ValueError("Every judge must vote exactly once on every constraint.")
        for constraint_id, vote in vote_set:
            grouped[constraint_id].append(vote)
    return {constraint_id: majority_verdict(votes) for constraint_id, votes in grouped.items()}


def issue_verdict(constraint_verdicts: Sequence[Verdict]) -> Verdict:
    if "violated" in constraint_verdicts:
        return "violated"
    if "satisfied" in constraint_verdicts:
        return "satisfied"
    return "neutral"


def compliance_metrics(outcomes: Sequence[tuple[bool, Verdict]]) -> ComplianceMetrics:
    total = len(outcomes)
    counts = Counter(verdict for _, verdict in outcomes)
    passing_applicable = [(passed, verdict) for passed, verdict in outcomes if passed and verdict != "neutral"]
    passing_violated = sum(1 for passed, verdict in passing_applicable if passed and verdict == "violated")
    rate = lambda value, denominator: 0.0 if denominator == 0 else value / denominator
    return ComplianceMetrics(
        dsr=rate(counts["satisfied"], total),
        dvr=rate(counts["violated"], total),
        dnr=rate(counts["neutral"], total),
        ppvr=rate(passing_violated, len(passing_applicable)),
        issues=total,
        passing_applicable=len(passing_applicable),
    )

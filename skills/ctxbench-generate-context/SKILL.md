---
name: ctxbench-generate-context
description: Generate frozen repository-level context from an exact baseline checkout for a CTXBench knowledge artifact. Use only in a dedicated context-generation run, before benchmark tasks are revealed.
---

# Generate repository context

Build a compact map that helps a future coding agent act correctly in this repository without knowing any benchmark task.

## Evidence boundary

Use the checked-out baseline as the source of truth. The invocation states one capability:

- `tree-only`: inspect files present in the working tree. Treat Git history and network access as out of scope.
- `history-aware`: inspect only local commits and review material whose timestamp is at or before the baseline cutoff supplied by the invocation.

The future task, target PR, gold patch, hidden tests, evaluator constraints, and post-baseline history are outside the evidence boundary. If any appear unexpectedly, leave them unread and report the exposure in the final response.

## Work

1. Survey the repository until every major source, test, build, and extension area has an evidence-backed purpose. Prefer manifests, test configuration, package structure, and representative implementation files over exhaustive reading.
2. Identify the paths a coding agent must follow for common changes: where behavior lives, how modules interact, how tests are selected, which generated or vendored areas require special handling, and which local conventions are easy to violate.
3. Write a root `AGENTS.md` as the discoverable entry point. Keep immediately actionable repository-wide guidance there. Point to `.ctx/architecture.md` and `.ctx/conventions.md` with explicit triggers when their detail is needed.
4. Put the stable architecture map in `.ctx/architecture.md` and evidence-backed implementation/testing conventions in `.ctx/conventions.md`. Omit either file when it would only duplicate `AGENTS.md`.
5. Re-read every claim against the baseline. Remove guesses, generic coding advice, duplicated meanings, task-shaped hints, and details likely to become stale without a commit change.

## Output boundary

The only writable paths are root `AGENTS.md`, root `CLAUDE.md`, `.github/copilot-instructions.md`, `.ctx/**`, and exact additional paths declared by the invocation. Keep source, tests, manifests, dependency locks, build configuration, and existing documentation byte-for-byte unchanged.

Finish when the context files are concise, internally linked, useful without prompt injection, and every repository-specific claim can be traced to baseline evidence. In the final response, list created or changed context files and any uncertainty; the harness records provenance and hashes outside the workspace.

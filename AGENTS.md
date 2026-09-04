# CTXBenchAuto agent guide

Preserve the experiment's causal seam: a paired run may differ only by its frozen context overlay. Keep task prompts, base commits, model configuration, budgets, container resources, network policy, and grading inputs identical within a pair.

Treat target PRs, gold patches, hidden tests, future history, and mined constraints as evaluator-only data. Knowledge builders and coding agents must never receive them.

Context files are passive repository files. The benchmark may overlay them, but it must not alter the task prompt, inject retrieval hints, force file reads, or otherwise help the coding agent discover them.

Keep credentials out of logs, artifacts, images, fixtures, and snapshots. Only pass explicitly allowlisted environment variables to agent containers.

Run `npm test`, `npm run build`, and `npm run worker:test` for changes that touch the corresponding modules. Container integration tests require Docker inside WSL and are allowed to skip with a clear diagnostic when it is unavailable.

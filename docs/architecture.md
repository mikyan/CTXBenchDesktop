# Architecture

CTXBench Desktop is local-first and has three runtime tiers:

```text
Tauri desktop (Windows)
  └─ HTTP on 127.0.0.1:48173
      └─ persistent worker (WSL2 Docker)
          ├─ SQLite + content-addressed artifacts
          ├─ context-generator container (Pi + generation Skill)
          ├─ solver container (Pi, no generation Skill)
          ├─ clean grader container (offline)
          └─ constraint miner/judge containers
```

The desktop diagnoses prerequisites and controls the worker. It does not silently install WSL, Docker, build tools, or reboot Windows. Closing the desktop leaves the worker running. Experiment operations and completed stages persist in SQLite. An interrupted agent stage starts a fresh baseline checkout; completed solve stages are reused when only grading/judging needs retry. Interrupted low-level raw `/runs` jobs fail closed because their caller-owned workspaces cannot safely be reconstructed.

## Deep modules and seams

- `Workbench` owns the persistent prepare → solve → grade → judge lifecycle; `ExperimentEngine` owns plans and adapter interfaces. Preparation is a barrier across all selected tasks, with an optional `ready` stop before solving.
- `ArtifactStore` exposes atomic publish/lookup while hiding canonical identity, path validation, hashing, staging, and deduplication.
- `Runner` is the container execution seam. `MockRunner` and `DockerRunner` are real adapters; tests and production cross the same interface.
- Dataset import is a normalization seam. SWE-bench, CTXBench (formerly AGENTBench), and custom JSONL become one `TaskRecord`; its `solver_payload` excludes evaluator-only fields by construction. Upstream `agentbench` paths and internal source identifiers remain unchanged.
- Constraint extraction/judgment is orthogonal to the functional grader and consumes the patch only after the solver finishes.

## Causal data flow

1. Import a task and pin its base commit, task prompt, test contract, image, model, agent version, resources, budget, and network policy.
2. Compute the context identity from repository, commit, generation Skill version, generation prompt hash, capability, and builder model configuration.
3. Generate a missing context artifact once in a dedicated container. Destroy that container and session after publication.
4. Create clean workspaces from the same base commit. Remove historical context for the `none`, `skill-generated`, and `manual` arms; retain it only for `developer-historical`; overlay the frozen artifact where applicable.
5. Randomize/interleave the paired schedule. The benchmark does not modify the task prompt or tell the solver how to discover context.
6. Diff against the sealed initial commit, including changes staged or committed by the Agent. Save `raw_agent.patch`; exclude context-owned files for `graded.patch` and record their edits as `context_mutation.patch`.
7. Apply only `graded.patch` to the original base in a fresh offline grader. Hidden tests, gold patches, target PR material, and constraints never cross into the builder or solver.

## Network profiles

- `offline`: Docker network disabled.
- `api-only`: agent attaches only to the internal `ctxbench-agent` network and uses the supplied Squid proxy. The proxy allowlist is the enforcement point.
- `unrestricted`: explicit non-primary profile using Docker bridge egress.

Provider credentials are copied by name from the worker environment only when that name is allowlisted. Known injected values are redacted from supported text outputs; values are not deliberately serialized into requests, image build inputs, manifests or exports. This is not protection against an intentionally malicious agent encoding a secret into arbitrary binary output. The worker/Docker host and imported build recipes are trusted; do not treat local Docker execution as a hardened hostile multi-tenant service.

The Pi adapter disables project extensions, Skill discovery, prompt-template discovery, and project trust for every run. Pi still loads repository context files through its native context mechanism. Only the context-generator invocation receives one explicit read-only Skill path; the solver receives none.

The Compose deployment bind-mounts `/var/lib/ctxbench` at the same logical data root and explicitly passes its Docker-host path to the worker. This is required because the worker talks to the host daemon through its socket; generated workspaces, requests, outputs, and the staged generation Skill must all resolve on both sides of that boundary.

Every resolved agent/harness/custom-test image receives a `ctxbench/frozen:sha256-…` reference to survive mutable-tag rebuilds. Do not prune those references while experiments may need retry. Custom test images are built once from the untouched baseline, never from an Agent patch. Run/evaluator containers are disposable; retained checkouts, artifacts and logs are intentionally preserved for audit and consume disk space.

Formal grading uses the pinned `ctxbench/official-harness` image. It vendors fixed commits of the upstream SWE-bench and CTXBench (formerly AGENTBench) harnesses and receives only the generated graded patch plus evaluator-owned task data. The harness container may launch the upstream per-instance grading image through the Docker socket; it never shares Provider credentials with that image.

Historical constraint mining starts from the GitHub repository-wide pull-request review-comment stream. The Worker filters comments and merged PRs against the pinned baseline cutoff before storing them, and preserves review/thread IDs, diff hunks, final PR patches, and commit provenance. The model-based miner sees that archive but not the target task; independent judges see mined constraints, the target task, and the already-produced candidate patch but never participate in solving.

Before mounting a dedicated checkout, the root Worker temporarily assigns that checkout and its run-output directory to the fixed unprivileged Agent UID/GID `10001`. Cleanup restores both trees to the shared data-root owner, so host-side Git operations remain usable. The child container still runs with all Linux capabilities dropped and `no-new-privileges`; ownership changes never target paths outside the validated Worker data root.

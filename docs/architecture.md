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

The desktop diagnoses prerequisites and controls the worker. It does not silently install WSL, Docker, build tools, or reboot Windows. The worker owns durable state so active jobs survive closing the desktop and are re-queued after interruption.

## Deep modules and seams

- `ExperimentEngine` exposes plan creation and execution while hiding pairing, persistence, and artifact orchestration.
- `ArtifactStore` exposes atomic publish/lookup while hiding canonical identity, path validation, hashing, staging, and deduplication.
- `Runner` is the container execution seam. `MockRunner` and `DockerRunner` are real adapters; tests and production cross the same interface.
- Dataset import is a normalization seam. SWE-bench, AGENTBench, and custom JSONL become one `TaskRecord`; its `solver_payload` excludes evaluator-only fields by construction.
- Constraint extraction/judgment is orthogonal to the functional grader and consumes the patch only after the solver finishes.

## Causal data flow

1. Import a task and pin its base commit, task prompt, test contract, image, model, agent version, resources, budget, and network policy.
2. Compute the context identity from repository, commit, generation Skill version, generation prompt hash, capability, and builder model configuration.
3. Generate a missing context artifact once in a dedicated container. Destroy that container and session after publication.
4. Create clean workspaces from the same base commit. Remove historical context for the `none`, `skill-generated`, and `manual` arms; retain it only for `developer-historical`; overlay the frozen artifact where applicable.
5. Randomize/interleave the paired schedule. The benchmark does not modify the task prompt or tell the solver how to discover context.
6. Save every solver change as `raw_agent.patch`. Exclude context-owned files for `graded.patch` and record their edits as `context_mutation.patch`.
7. Apply only `graded.patch` to the original base in a fresh offline grader. Hidden tests, gold patches, target PR material, and constraints never cross into the builder or solver.

## Network profiles

- `offline`: Docker network disabled.
- `api-only`: agent attaches only to the internal `ctxbench-agent` network and uses the supplied Squid proxy. The proxy allowlist is the enforcement point.
- `unrestricted`: explicit non-primary profile using Docker bridge egress.

Provider credentials are copied by name from the worker environment only when that name is allowlisted. Secret values are redacted from RPC trajectories and logs and are never included in requests, images, manifests, or exports.

The Pi adapter disables project extensions, Skill discovery, prompt-template discovery, and project trust for every run. Pi still loads repository context files through its native context mechanism. Only the context-generator invocation receives one explicit read-only Skill path; the solver receives none.

The Compose deployment bind-mounts `/var/lib/ctxbench` at the same logical data root and explicitly passes its Docker-host path to the worker. This is required because the worker talks to the host daemon through its socket; generated workspaces, requests, outputs, and the staged generation Skill must all resolve on both sides of that boundary.

Before mounting a dedicated checkout, the root Worker temporarily assigns that checkout and its run-output directory to the fixed unprivileged Agent UID/GID `10001`. Cleanup restores both trees to the shared data-root owner, so host-side Git operations remain usable. The child container still runs with all Linux capabilities dropped and `no-new-privileges`; ownership changes never target paths outside the validated Worker data root.

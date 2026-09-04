# Container agent adapter contract

Pi is the preinstalled reference adapter, but the worker depends on an image contract rather than Pi internals. A company-internal coding agent can be added as another image without changing experiment planning, pairing, artifact storage, or grading.

The reference image also recognizes `provider: mock`. That path runs a deterministic JSONL-RPC stand-in inside the same container, mounts, network, resource, and output contract as Pi. It is for infrastructure smoke tests only and is always labeled as mock output.

## Runtime contract

The worker starts one disposable container per run with:

- `/workspace` — writable checkout pinned to the run's base commit.
- `/ctxbench/request.json` — read-only request conforming to `schemas/agent-request.schema.json`.
- `/ctxbench/output` — writable result directory.
- the configured CPU, memory, PID, timeout, capability-drop, and network policy.
- only requested environment variables whose names are in the worker allowlist.

The image must execute its adapter as the default entrypoint, consume the request once, and write `result.json` conforming to `schemas/agent-result.schema.json`. A solver adapter must also produce:

- `trajectory.jsonl`, with credential values redacted;
- `raw_agent.patch`, containing every workspace change;
- `graded.patch`, excluding all context-owned paths;
- `context_mutation.patch`, containing only context-owned changes.

Exit `0` only after outputs are durably written. Use `124` for a timeout and a non-zero code for other failures. Do not persist credentials, provider session state, or home-directory configuration in the image or output.

`model.max_tokens` is the cumulative run budget. The reference Pi adapter adds provider-reported usage from completed assistant messages and aborts before the next turn once the budget is reached. Since providers report usage after a response, the last response can overshoot; that behavior is identical across paired arms and is recorded as `budgetExceeded` plus `cumulativeTokens`.

## Isolation rules

The context-generation Skill is mounted by the worker only when `mode` is `generate-context`; solver images never receive it. Hidden tests, the gold patch, target PR content, and mined constraints belong to evaluator workspaces and must not be copied into agent requests or solver mounts.

`api-only` containers receive HTTP(S) proxy variables and can reach only provider domains admitted by the egress proxy. New internal provider domains should be reviewed and added to `docker/egress-proxy/squid.conf`; do not switch formal experiments to unrestricted network merely to make an adapter work.

## Adding internal credentials

Add credential variable names—not values—to `CTXBENCH_EXTRA_ENV_ALLOWLIST`, define the matching variables in the runtime `.env`, and select those names in the run configuration. The worker rejects malformed or non-allowlisted names before starting a container. Any internal adapter must redact the resulting values from stdout, stderr, trajectories, and diagnostic artifacts.

Pin the image by immutable digest for formal comparisons. Changing the adapter image, agent version, provider, model, prompt, budget, resources, or network policy creates a new comparison block.

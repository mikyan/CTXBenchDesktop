# Container agent adapter contract

Pi is the preinstalled reference adapter, but the worker depends on an image contract rather than Pi internals. A company-internal coding agent can be added as another image without changing experiment planning, pairing, artifact storage, or grading.

For **coding-only** integration, v0.1.7 offers a simpler alternative: configure a case's `agent.image` and `agent.command` and let the service inject its standalone Python command adapter. See [the guided image/custom-command instructions](image-workshop.md). It requires no Pi or image protocol labels, replaces ENTRYPOINT/CMD, and reports unknown usage rather than implementing the Pi token guard. The full adapter contract below remains necessary for other roles or verified model-usage integration. Command-image and service-adapter hashes are frozen alongside each case; setup cannot change the frozen repository, and grading still uses its own commands or CI adapter.

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

`model.max_tokens` is the cumulative run budget. The reference Pi adapter adds provider-reported usage from completed assistant messages and aborts before the next turn once the budget is reached. Since providers report usage after a response, the last response can overshoot; that behavior is identical across paired arms and is recorded as `budgetExceeded` plus `cumulativeTokens`. A budget hit during a tool-use turn is a failed run; a final completed answer that crosses the threshold remains gradeable. Context generation additionally fails when it produces no context files.

The adapter writes `trajectory.live.jsonl` while Pi is running, then writes the canonical redacted `trajectory.jsonl` on exit. Prompt-submission errors terminate immediately instead of occupying the queue until the outer timeout.

## Optional workflow protocol v1

Experiments freeze `builderWorkflow` and `solverWorkflow` separately. Independent `/prepare/context` operations accept `workflow`. Configuration uses `setupCommands: string[]` and ordered `steps: [{name, prompt}]`; a null prompt means the existing stage default, while `{{default_prompt}}` explicitly substitutes that default in custom text. Omitting configuration preserves the original one-step behavior and cache keys.

The Worker resolves prompts, sends the optional `workflow: {version: 1, setupCommands, steps}` in the agent request, and requires image label `io.ctxbench.workflow=1`. All steps execute sequentially in one container with fresh agent sessions, shared files, one cumulative token allowance and one wall-clock deadline. Bash startup commands run once as the unprivileged agent user, before model calls; exported environment/venv activation transfers in memory, never through output artifacts. The baseline must remain unchanged. Package downloads use the same explicitly selected network policy as the agent; setup commands never run in evaluator containers.

The bundled Pi image includes pip and venv. Prefer `$HOME/bench-env` for dependencies; system packages belong in the Dockerfile. Pin dependency versions or bake dependencies into an immutable image for reproducibility. A step may use predecessor files, but the adapter does not automatically add conversation history, retrieval hints or forced context reads. Generation receives only baseline code and generation prompts; final generated files must remain context-owned.

Fail fast on setup/step failures, enforce the shared token/deadline limits across steps, and produce `workflow.json`, `setup.log` and the existing final patch/trajectory outputs. Results report `workflowProtocolVersion: 1`, `modelInvocations`, `workflowError`, ordered `workflowSteps` (status, SHA-256 of the exact UTF-8 prompt, usage) and aggregate `cumulativeTokens`/`sessionStats`. The Worker rejects adapters that do not confirm all configured steps. No-model setup failures with a valid zero-call receipt release the token reservation; interrupted model calls retain conservative accounting. Retrying a failed workflow uses a clean container and replays the whole workflow, not an incomplete middle checkpoint.

Run `scripts/container-workflow-smoke.py` inside the Worker image with the Docker socket, shared data directory and repository mounted at `/source:ro`. It uses synthetic prompts and an offline fixture wheel, checks generation/solving, fresh sessions, failure stops, shared budgets and paired reuse, and never calls a Provider. `CTXBENCH_WORKFLOW_TEST_IMAGE` optionally selects a test image instead of `ctxbench/agent-pi:0.1.0`. Run `node --test /source/docker/agent-pi/workflow-runtime.integration.mjs` inside the Pi image with the repository mounted read-only to verify timeout/process cleanup and environment transfer. These Linux-only tests are separate from the frontend Vitest suite.

## Optional startup-arguments protocol v1

Experiments, independent `/prepare/context` and `/prepare/constraints` operations, and raw `/runs` requests accept `agentArgs: string[]` (default `[]`). In the desktop, use **New experiment → Runtime and budgets → Agent startup arguments**, or the same field in generation/mining dialogs. Each row is one literal argv element: `--tools` and `read,bash` are two rows. Preserve order, duplicates, Unicode, whitespace and empty strings; do not shell-split, expand variables, evaluate expressions, or add quoting. Startup arguments are different from Bash startup commands. Limits: 128 arguments, 4096 Unicode code points per argument, 32768 in total; control characters and unpaired surrogates are forbidden.

One experiment-wide list applies to builders, solvers, miners, judges and every fresh prompt session. It is persisted for restart/retry and included in generation/miner cache identity and pairing hashes, but never sent to the hidden-test grader. An empty list preserves legacy cache keys and does not require the new capability. Previously frozen manual/imported packages remain explicitly reusable.

The Worker passes non-empty `agentArgs` through the read-only request, **not** as Docker `command` or an entrypoint override. Images supporting this feature must declare `LABEL io.ctxbench.agent-args="1"`. Every successful adapter run must report `agentArgsProtocolVersion: 1` and `agentArgsHash`: lowercase SHA-256 of the UTF-8, compact JSON array (`JSON.stringify(args)` in JavaScript; `json.dumps(args, ensure_ascii=False, separators=(',', ':'))` in Python). Compute the receipt from the actual applied extra argv, after validation. A missing/mismatched receipt or an old image is rejected, not silently treated as a valid run. Custom adapters must reject unsupported options before model calls and must not let options override frozen prompts, models, budgets or isolation policies.

The Pi image additionally declares `io.ctxbench.agent-kind="pi"`. Its pinned CLI supports these extra options here:

- Value options: `--tools` / `-t`, `--exclude-tools` / `-xt`, followed by a separate non-empty tool-list argument (not `--tools=value`).
- Switches: `--verbose`, `--no-tools` / `-nt`, `--no-builtin-tools` / `-nbt`, `--no-themes`, `--no-context-files` / `-nc`.

`--no-context-files` disables Pi's automatic context-file loading in **both** arms; choose it only when that is the agent behavior you intend to measure. Provider/model/thinking, RPC mode, benchmark prompts, sessions, extensions and Skills remain controlled by the adapter. Unknown flags and positional prompts are rejected before model calls. Company agents may implement their own options under the same image contract; the Pi-specific list does not apply to them.

Arguments are non-secret, persisted configuration. Use selected environment variables for credentials, never `--api-key`, `--token`, etc. The Worker rejects credential flags and configured credential values before persisting argv. No variable interpolation is performed: an internal adapter needing credentials as CLI values must obtain them from its explicitly selected environment at runtime and redact them; such resolved secrets must not enter the request, receipt or artifacts.

Existing installations need an updated Worker **and** rebuilt/imported Pi image for non-empty arguments. From the project or the desktop's staged deployment directory, `docker compose -f docker/compose.yaml --profile build-only build ctxbench-worker agent-pi-image` builds both (check the compose service names before using custom deployments). Restart the Worker only after active jobs finish. Publishing a desktop installer alone does not update an already running Worker or image.

## Isolation rules

The context-generation Skill is mounted by the worker only when `mode` is `generate-context`; solver images never receive it. Hidden tests, the gold patch, target PR content, and mined constraints belong to evaluator workspaces and must not be copied into agent requests or solver mounts.

`api-only` containers receive HTTP(S) proxy variables and can reach only provider domains admitted by the egress proxy. New internal provider domains should be reviewed and added to `docker/egress-proxy/squid.conf`; do not switch formal experiments to unrestricted network merely to make an adapter work.

## Adding internal credentials

Use Infrastructure's runtime credential form to add internal names/values in worker memory, then select only the names in the experiment. For persistent deployment, add names to `CTXBENCH_EXTRA_ENV_ALLOWLIST` **and explicitly pass those variables into the worker's Compose environment** (for example through a local Compose override). A `.env` interpolation file alone does not automatically forward arbitrary variables. Never put credentials into Dockerfiles or build arguments. Any internal adapter must redact values from its outputs.

The form supports multiple name/value rows with **Add variable** and **Save environment variables**. All rows are validated before any values are changed; duplicate names, reserved worker controls and invalid rows reject the entire batch. Values are masked and cleared from the form after saving. In experiments, context generation and constraint mining, select multiple configured names or paste names separated by newlines, spaces or commas. These fields accept **names only**, not `NAME=value`; saved variables are not automatically passed to every agent. A base-URL variable only has an effect if the selected agent adapter recognizes that name, and it does not bypass the network allowlist.

`POST /v1/runtime/credentials` accepts `{"variables":[{"name":"INTERNAL_AGENT_KEY","value":"<runtime value>"},{"name":"INTERNAL_AGENT_URL","value":"https://provider.internal/v1"}]}`. The response contains only variable names and configured flags. The previous single `{name, value}` request remains supported. Restarting the worker clears UI-entered values.

The bundled Pi image supports Xiaomi Token Plan China with provider `xiaomi-token-plan-cn`, model `mimo-v2.5-pro` (or `mimo-v2.5`), and runtime variable `XIAOMI_TOKEN_PLAN_CN_API_KEY`. The API-only proxy admits only the China Token Plan hostname for this adapter.

Pin the image by immutable digest for formal comparisons. Changing the adapter image, agent version, provider, model, prompt, budget, resources, or network policy creates a new comparison block.

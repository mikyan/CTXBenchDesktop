# CTXBench Desktop

[English](README.md) | [简体中文](README.zh-CN.md)

CTXBench Desktop is a local-first Windows desktop benchmark workbench for paired coding-agent experiments. It compares identical runs with and without frozen repository context, evaluates functional correctness, and adds a SWE-Shield-compatible design-constraint layer.

## Implemented workbench

- SWE-bench, CTXBench/AGENTBench, and custom-manifest experiment types.
- Paired and randomized `none` versus `skill-generated`, `manual`, or `developer-historical` context arms.
- Content-addressed context artifacts generated once per exact repository commit and reused across runs.
- Pi coding-agent image using its JSONL RPC mode, with provider/model selection and allowlisted environment injection.
- A persistent WSL Docker worker: dataset import → prepare all context → solve → official/custom tests → three independent constraint judges.
- Pause, resume, cancel, and stage-aware retry; closing the desktop does not stop the worker.
- Chinese/English UI, actual live state, run trajectories/patches/voting evidence, frozen package inspection and export.
- Functional pass rate, knowledge lift, variance, win/loss/tie, and SWE-Shield-style DSR/DVR/DNR plus PPVR metrics.
- JSON, spreadsheet-safe CSV, and self-contained HTML reports; Windows NSIS installer containing the image build sources.

The CTXBench adapter targets the task format and harness from the [CTXBench/AgentBench paper](https://arxiv.org/abs/2602.11988) and [official repository](https://github.com/eth-sri/agentbench). The SWE-Shield layer is a documented compatible implementation, not a claim of bit-for-bit replication.

## Run the available development mode

```powershell
npm install
npm run dev
```

The browser development mode connects to the **real WSL worker** through the Vite proxy. It does not silently substitute sample results when disconnected. Open `http://localhost:43173/?demo=1` only for an explicitly labelled visual demo.

For source-level tests of the API (not container benchmark acceptance):

```powershell
python -m pip install -r worker/requirements-dev.txt
npm run worker:dev
```

```powershell
npm run tauri dev
```

The source Worker defaults to a deterministic test adapter. Full benchmark execution requires the WSL/Compose deployment, including when using the containerized `mock` Provider for infrastructure tests. Desktop worker controls are available in Tauri, not in the browser preview.

## Desktop workflow

1. In **Infrastructure**, select the WSL distribution, build the bundled images, then start the worker. Configure API keys there (memory-only until restart), or through deployment environment variables.
2. In **Experiments → Import dataset**, import JSON/JSONL, or a parquet file already placed in the worker's `/var/lib/ctxbench/datasets` directory. Official sources: [ETH SRI AgentBench](https://huggingface.co/datasets/eth-sri/agentbench) and [SWE-bench Verified](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified). Dataset rows are content-hashed and frozen.
3. Select actual imported tasks, Provider/model, role-specific token budgets, resources, repeats, and a context arm. Check **prepare all context first** to stop at `ready`; resume when ready to solve.
4. For cross-model comparisons without regenerating context, select **Frozen package** and reuse a generated or manually imported package with exactly matching repository and baseline commit. JSON packages and documentation folders are supported. A manually supplied baseline declaration is an assertion by its author, not proof of how the document was generated.
5. Optionally enable historical-PR constraint mining. Automatic packages are **silver** and use three independent judge sessions (separate models are optional). Failed judges are visible and retryable; they never become invented neutral votes.
6. Inspect results and evidence, then export. A single task with many repeats does **not** establish population-level knowledge lift.

Independent generation/mining jobs have their own pause, resume, cancel and retry controls in Knowledge / Constraints. Pause lets the current stage finish so its checkpoint can be reused; cancel stops the active container. An interrupted stage is retried from a fresh checkout, not a partially edited workspace.

Use **Workload preflight** before creating an experiment (required in the desktop for more than 20 tasks). It counts solver, builder, miner and judge invocations and sums their configured token allowances. It does not call a Provider, deduct cache hits, calculate an actual bill, or enforce a hard experiment-wide token cap. WSL virtual-disk free space is not physical Windows volume capacity: check both. `CTXBENCH_MIN_FREE_GB` defaults to 5; low Worker filesystem space pauses before the next stage. This cannot prevent an in-flight stage from filling the disk.

For cross-experiment spending control, create a **Shared token budget** on the Experiments page and attach its ID when creating experiments. The current verified accounting adapter supports MiMo Token Plan CN (`mimo-v2.5` / `mimo-v2.5-pro`) and infrastructure mocks. All attached roles must use the authorized Provider/model. Creation cannot overwrite an existing budget. Explicit increases use **Increase total allowance** or `POST /v1/token-budgets/{id}/increase` with `expectedLimitTokens`, `limitTokens` and an authorization `reason`; they retain all attempts/reservations and append an audit record. Each new stage reserves its cumulative allowance plus two maximum-size model requests (2,359,296 tokens for these MiMo models); completed, protocol-confirmed usage releases the unused reservation. Failures, missing usage and crash recovery conservatively keep the reservation charged. Reported usage, charged allowance and in-flight reservations are shown separately. This guard is not a Provider billing reconciliation or a universal hard cap for arbitrary third-party agents. It never decreases one arm's configured limits to fit the remainder.

New forms and campaign plans default to 5,000,000 cumulative tokens per role and 1,000,000,000 total tokens; these are configurable allowances, not expected consumption. Changing a stage allowance requires new paired experiments. To retain a previous campaign's exact task order, use a new `--root`, a distinct `--campaign-id`, the same `--budget-id`, `--source-plan /path/to/old/plan.json`, `--stage-tokens 5000000` and the authorized `--limit-tokens`. This does not mutate the old plan, skip cases based on outcomes, reset spending, or merge old low-allowance results into the new comparison.

`scripts/run-campaign.py` freezes a 638-task official dataset plan without spending by default; `--execute` explicitly starts real calls against an existing Worker. `--budget-id`, `--root`, and an immutable `--agent-image` are required. It alternates datasets using seeded repository round-robin order after two disclosed compatibility cases, prepares each baseline once, and runs two repetitions per arm. A matching existing constraint package is recorded explicitly; unavailable historical mining is deferred, never counted as a neutral/pass result. `--stop-after 2` verifies the compatibility prefix before the remainder. Supplying `--host-volume` with an empty read-only directory on the Windows volume that contains WSL lets the coordinator check actual host capacity and stop at 25 GiB free. Three consecutive cases without any functional grading stop the campaign, checked both globally and independently within each dataset. A healthy SWE case cannot reset a CTX failure streak; real functional failures do reset the streak because they are valid scores. The state records the triggering scope and experiment IDs. Keep one coordinator per frozen plan; restart it with the same arguments and state directory to resume without duplicating experiments.

To stop the whole campaign from the desktop, pause the active experiment after its current stage, or cancel it. The coordinator then exits without starting the next task. Closing the desktop window alone does not stop the Worker or campaign. Resume the experiment and restart the coordinator explicitly when ready; never run two coordinators for one plan.

An operating-system file lock on the state directory rejects concurrent coordinators before any API request. A crashed process releases this lock automatically; the retained lock file is not itself a stale lock and should not be deleted.

Token budget means cumulative Provider-reported tokens, including cached input. Repository exploration/mining may require substantially more tokens than one answer. Provider-reported cost can be zero for subscription products; it is not a bill calculation.

## Build and test

```powershell
npm ci
python -m pip install -r worker/requirements-dev.txt
npm test
npm run worker:test
npm run build
cargo test --manifest-path src-tauri/Cargo.toml
npm run tauri build
```

The installer is written to `src-tauri/target/release/bundle/nsis/`. Bundled deployment files deliberately exclude `.env`, datasets, credentials, run results and caches. For Docker lifecycle and crash/restart regressions without paid API calls, see `scripts/container-smoke.py` and `scripts/container-resilience.py`. The latter kills only its uniquely labelled isolated Worker; it never restarts the production Worker. `python scripts/scale-smoke.py` tests a temporary synthetic 638-task / 2,552-run database, not model quality. See [the reassessment](docs/reassessment.md) for verified delivery scope and remaining release boundaries.

## Desktop prerequisites

The Tauri desktop shell follows the official Windows prerequisites: Microsoft C++ Build Tools with the Desktop C++ workload, WebView2, and the Rust MSVC toolchain. Install these explicitly before starting the desktop command above.

The app diagnoses WSL and Docker without silently installing or rebooting the machine.

## WSL worker and images

After installing Docker Engine inside the selected WSL2 distribution:

```bash
docker compose -f docker/compose.yaml --profile build-only build
docker compose -f docker/compose.yaml up -d ctxbench-worker
```

The build-only profile also produces `ctxbench/official-harness:0.1.0`. That image pins upstream SWE-bench and ETH SRI AgentBench revisions. Solver containers never receive the Docker socket. The trusted evaluator supervisor may fetch/build official images; its child **test containers are offline** with CPU/memory limits. Upstream test selection and scoring are retained.

New AgentBench experiments prepare a baseline-specific evaluator environment **before any builder or solver call**. The original instance image may contain only the repository, not its dependencies. Baseline setup runs in one networked shell, preserving virtual-environment activation, in a child with no host mounts, Docker socket or injected Provider credentials. The resulting image and setup receipt are frozen by digest. A separate offline gold-patch self-check must pass before the environment is admitted; gold patches and test runners never enter the reusable setup image or agents. Test commands also share a shell, and missing/empty/malformed result maps are evaluator errors, not failed model scores. Full runner diagnostics are retained in evaluator-only `repo-tests.json` and `instance-tests.json`.

Known dependency compatibility pins are baseline-scoped and included in the image identity, in [agentbench_environment.py](docker/official-harness/agentbench_environment.py). They are explicit adapter differences, not an upstream lockfile. An incompatible official test is blocked and diagnosed; it is not rewritten to make the gold patch pass. Existing experiments keep their frozen harness and preparation rules. Test a repaired harness against retained patches in separate output directories; do not silently upgrade half a pair or merge repaired scores into an old campaign. Offline transfers must include the prepared evaluator images as well as the original instance images.

The install script creates `/var/lib/ctxbench`, which Compose bind-mounts at the same path so child agent containers can safely receive workspaces through the host Docker daemon. To use another WSL-native location, set `CTXBENCH_HOST_DATA_DIR` to its absolute path before starting Compose.

The worker binds only to `127.0.0.1:48173`. API credentials are passed from an explicit environment-variable allowlist. This is a trusted single-user local service with Docker-host privileges, not a remotely exposed or multi-tenant server. Do not expose its port publicly. For air-gapped use, export the application images **and** all required dataset instance images, repositories and data; application images alone are insufficient.

Historical design evidence can be collected with `POST /v1/constraints/review-archive`. The request fixes a GitHub `owner/name`, cutoff timestamp, and bounded page/PR/comment limits. The worker retains only review comments from PRs merged by the cutoff and stores a content-addressed evaluator-only archive under `/var/lib/ctxbench/review-archives`. `GITHUB_TOKEN` is optional for public repositories and is never written to the archive.

## Repository layout

- `src/` — React desktop interface and testable experiment domain modules.
- `src-tauri/` — Tauri control layer and WSL/worker diagnostics.
- `worker/` — persistent benchmark orchestration module and mock/Docker runner seam.
- `docker/agent-pi/` — pinned Pi agent image and RPC adapter.
- `docs/agent-adapters.md` — stable container contract for future company-internal agents.
- `skills/ctxbench-generate-context/` — isolated knowledge-generation skill.
- `schemas/` — portable custom task, context artifact, and agent contracts.
- `docs/` — architecture and evaluation methodology.

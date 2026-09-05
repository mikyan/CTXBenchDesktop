# CTXBench Desktop

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

The installer is written to `src-tauri/target/release/bundle/nsis/`. Bundled deployment files deliberately exclude `.env`, datasets, credentials, run results and caches. For a Docker-only lifecycle regression without paid API calls, see `scripts/container-smoke.py`. See [the reassessment](docs/reassessment.md) for verified delivery scope and remaining release boundaries.

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

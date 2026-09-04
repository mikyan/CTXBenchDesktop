# CTXBench Desktop

CTXBench Desktop is a local-first Windows desktop benchmark workbench for paired coding-agent experiments. It compares identical runs with and without frozen repository context, evaluates functional correctness, and adds a SWE-Shield-compatible design-constraint layer.

## What the MVP includes

- SWE-bench, CTXBench/AGENTBench, and custom-manifest experiment types.
- Paired and randomized `none` versus `skill-generated`, `manual`, or `developer-historical` context arms.
- Content-addressed context artifacts generated once per exact repository commit and reused across runs.
- Pi coding-agent image using its JSONL RPC mode, with provider/model selection and allowlisted environment injection.
- A persistent WSL Docker worker interface, mock runner, SQLite state, local artifacts, and resumable job records.
- Functional pass rate, knowledge lift, variance, win/loss/tie, and SWE-Shield-style DSR/DVR/DNR plus PPVR metrics.
- JSON, CSV, and self-contained HTML export contracts.

The CTXBench adapter targets the task format and harness from the [CTXBench/AgentBench paper](https://arxiv.org/abs/2602.11988) and [official repository](https://github.com/eth-sri/agentbench). The SWE-Shield layer is a documented compatible implementation, not a claim of bit-for-bit replication.

## Run the available development mode

```powershell
npm install
npm run dev
```

The browser development mode automatically uses the in-memory mock adapter. It exercises experiment creation, navigation, diagnostics, progress, filtering, and exports without credentials or Docker.

For the real desktop shell with the durable mock Worker, start these in two PowerShell terminals:

```powershell
python -m pip install -r worker/requirements.txt
npm run worker:dev
```

```powershell
npm run tauri dev
```

The source Worker defaults to deterministic mock execution, so it never spends Provider credits accidentally. Use `CTXBENCH_RUNNER=docker` only through the WSL/Compose deployment.

## Desktop prerequisites

The Tauri desktop shell follows the official Windows prerequisites: Microsoft C++ Build Tools with the Desktop C++ workload, WebView2, and the Rust MSVC toolchain. Install these explicitly before starting the desktop command above.

The app diagnoses WSL and Docker without silently installing or rebooting the machine.

## WSL worker and images

After installing Docker Engine inside the selected WSL2 distribution:

```bash
docker compose -f docker/compose.yaml --profile build-only build
docker compose -f docker/compose.yaml up -d ctxbench-worker
```

The install script creates `/var/lib/ctxbench`, which Compose bind-mounts at the same path so child agent containers can safely receive workspaces through the host Docker daemon. To use another WSL-native location, set `CTXBENCH_HOST_DATA_DIR` to its absolute path before starting Compose.

The worker binds only to `127.0.0.1:48173`. API credentials remain runtime-only and are passed to agent containers from an explicit environment-variable allowlist.

## Repository layout

- `src/` — React desktop interface and testable experiment domain modules.
- `src-tauri/` — Tauri control layer and WSL/worker diagnostics.
- `worker/` — persistent benchmark orchestration module and mock/Docker runner seam.
- `docker/agent-pi/` — pinned Pi agent image and RPC adapter.
- `docs/agent-adapters.md` — stable container contract for future company-internal agents.
- `skills/ctxbench-generate-context/` — isolated knowledge-generation skill.
- `schemas/` — portable custom task, context artifact, and agent contracts.
- `docs/` — architecture and evaluation methodology.

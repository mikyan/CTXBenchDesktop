# Company CI adapter contract / 公司平台二开

The replaceable platform **seam** is `worker/ctxbench_worker/ci_protocol.py:Platform`. GitHub Actions and the reference HTTP gateway are two **Adapters** behind the same **Interface**. Common grading policy, JUnit parsing, frozen targets, credentials and durable receipts live in separate modules; do not copy that policy into a platform adapter.

最快接公司平台：实现下面的 HTTP 网关协议，页面选择 **公司 HTTP CI 网关**。也可以直接新增 Python 适配器调用公司 SDK；仅修改适配器注册、配置枚举和平台选项，不必改实验调度、知识库构建或结果统计。

## HTTP gateway v1

The configured base URL must use HTTPS, e.g. `https://ci.company.example/ctxbench`. Paths below are relative to it. Requests use JSON and an explicit `Authorization: Bearer <token>` supplied only by the evaluation service. Do not redirect authenticated requests. Private CA/proxy configuration belongs to the evaluation service environment; do not disable TLS verification. The adapter never uses ambient `.netrc` credentials.

| Method and path | Required behavior |
| --- | --- |
| `POST /v1/targets/resolve` | Read-only resolution of an exact baseline and immutable workflow version; must not start work |
| `PUT /v1/evaluations/{evaluationId}` | Durably idempotent submission by this ID; return the same evaluation for replays |
| `GET /v1/evaluations/{evaluationId}` | Read only that candidate's execution state and exact gate results |
| `GET /v1/evaluations/{evaluationId}/junit?artifact={name}` | Return a ZIP containing only the selected execution's JUnit evidence |
| `POST /v1/evaluations/{evaluationId}/cancel` | Cancel only this evaluation; safe to repeat, including after an uncertain submission |

### 1. Resolve the target

Request shape:

```json
{
  "repository": "team/backend-bench",
  "workflow": "test-pipeline",
  "sourceRepository": "https://git.company.example/team/backend-bench.git",
  "baseCommit": "<exact 40-hex baseline commit>"
}
```

Response shape (placeholders must be replaced with actual identifiers):

```json
{
  "repository": "team/backend-bench",
  "baseCommit": "<the same baseline commit>",
  "baseTree": "<40-hex Git tree at that commit>",
  "workflowId": "test-pipeline",
  "workflowPath": "ci/tests.yml",
  "workflowBlob": "<immutable workflow revision or content hash>",
  "protectedPaths": ["ci/", "tests/grading/", "scripts/grade.sh"]
}
```

Only these fields are accepted. `repository`, `baseCommit`, `baseTree` and nonempty `workflowBlob` are required; paths/ID are adapter-defined metadata. A mutable name such as `latest` is **not** an immutable workflow revision. The gateway must retain the exact resolved evaluator version for both arms and all repeats, including restored experiments. Resolve source mirrors explicitly and verify the same source tree. Never return auth headers, secrets or signed URLs in this public snapshot.

`protectedPaths` protects both an exact path and descendants. `.github/` and `.git/` are always protected. These paths stop candidate edits being uploaded; they do not make baseline files invisible to the Agent. Hidden tests and gold material must remain outside the Agent-visible repository.

### 2. Submit the candidate

```json
{
  "evaluationId": "<64-hex durable idempotency key>",
  "target": { "...": "the complete frozen target above" },
  "candidate": {
    "baseCommit": "<baseline commit>",
    "treeSha": "<40-hex exact candidate Git tree>",
    "patchSha256": "<64-hex graded.patch hash>",
    "files": [
      { "path": "src/App.java", "mode": "100644", "base64": "<base64 bytes>" }
    ]
  }
}
```

The changed-file list is relative to the baseline, not a full repository upload. File modes: `100644` regular, `100755` executable, `120000` symbolic-link content; `000000` means delete. Never follow candidate symlinks during reconstruction. Submodules are not supported by this submission format. Limit: 500 changed files / 10 MiB decoded contents. The gateway must reconstruct and verify `treeSha`, not trust it without checking.

Return JSON with `evaluationId`, `treeSha` and optional `commit`. On retry after timeout, the same ID and content **must return the same remote evaluation without starting another one**. A reused ID with different content must be rejected. Record the ID durably before starting CI. Do not merge, deploy, force-push or delete unrelated objects. Branch names in the desktop are local receipt labels; a gateway using another submission mechanism owns its remote ref mapping.

### 3. Poll only the owned evaluation

```json
{
  "evaluationId": "<same ID>",
  "treeSha": "<same candidate tree>",
  "status": "completed",
  "conclusion": "success",
  "attempt": 1,
  "url": "https://ci.company.example/runs/123",
  "jobs": [
    { "name": "test", "status": "completed", "conclusion": "success" }
  ]
}
```

While pending use `queued` / `in_progress`, `conclusion: null`, `jobs: []`. Completed legitimate test outcomes use `success` or `failure`. Cancellation, timeout, skip, blocked/unknown gates are infrastructure errors, never successful functional grades. Return all gate entries, handling your platform's pagination internally. Gate names must be unique and match the case's configured display names exactly, including matrix suffixes.

The gateway must bind workflow version, source tree, gate records and report artifact to one immutable execution attempt. Do not return a branch's latest green run or silently replace a result after someone reruns the platform job. Use a new CTXBench experiment for a new attempt. The `url` is optional; if returned, it must be a public-to-the-operator HTTPS navigation URL without credentials or signed access parameters.

### 4. Report and cancel

The report endpoint returns the named artifact as ZIP bytes, not base64 JSON. It must reject missing, ambiguous, expired or mismatched evidence. Convert company-specific reports to JUnit on the trusted gateway if necessary. Accepted XML roots are `testsuite` / `testsuites`; actual `testcase` elements are counted. DTD/entity declarations, malformed/empty evidence and excessive archive sizes are rejected. Response bound: 16 MiB; uncompressed archive bound: 32 MiB / 2,000 entries. Raw test names/logs are not retained in CTXBench's result record; only aggregate counts and the report hash are persisted.

Cancellation should be idempotent and use the exact evaluation ID. Return 200/202/204 once handled or accepted; report authorization/communication failures. A lost submission response can still be followed by cancel, so a tombstone or equivalent race-safe mechanism is recommended. Never cancel an unrelated pipeline by branch name alone. The desktop warns that cancellation may not be confirmed and that remote work may continue.

## Direct Python adapter

Implement five methods in a new `ci_<platform>.py`:

- `prepare(task) -> dict`: no remote mutation; return the frozen target.
- `submit(target, candidate, receipt, save)`: perform only idempotent submission; persist uncertainty/commit/remote ID with `save()` before moving to the next remote write.
- `poll(receipt) -> dict`: validate exact run identity and attempt, return normalized state/jobs.
- `report(receipt, name) -> bytes`: return only this evaluation's ZIP evidence.
- `cancel(receipt)`: cancel only this receipt's remote execution.

Register the factory in `ci_grading.py:ADAPTERS`, allow its provider ID in `ci_config.py:ci_connection`, add the option to `src/components/CIGradingFields.tsx` and translations. Reuse `Transport` for explicit credentials, bounded requests and cancellation checks. API errors must raise sanitized `CIError` messages without server bodies or secrets. Do not export the platform token to Docker, `os.environ`, task manifests or snapshots. Company SDK calls must apply equivalent deadlines, TLS and credential rules.

The invariant is unchanged: `ci_grading.gate_result` owns pass/fail and test-count policy; `ci_reports.junit_counts` owns parsing; `CIGrading` owns candidate reconstruction, protected-file checks and receipts; `Workbench` freezes one target per task before any paid Agent stage. An adapter does not change prompts, context discovery or pairing inputs.

## Verification before company rollout

Use `worker/tests/test_ci_adapters.py` as the platform contract test pattern. Verify: read-only prepare, exact source tree, durable replay after timeout, cancellation races, identity mismatch refusal, skipped/absent/duplicate gates, matrix pagination, failed-test reports, missing/empty JUnit evidence, secret-free errors, and platform rerun refusal. Run `npm test`, `npm run build`, `npm run worker:test`; `scripts/ci-grading-ui-smoke.mjs` checks both UI languages against fixtures. Then use a dedicated company test repository for one real paired integration run. The shipped reference gateway adapter itself is not a deployed company gateway.

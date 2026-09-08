# Project image installation verification / 项目镜像安装验证

Verified in the development worktree on 2026-09-08. No Provider calls, production dataset writes, service restarts or full-suite image downloads were performed.

## Automated coverage

- `npm test`: 131 passed.
- `npm run build`: passed (existing bundle-size warning remains).
- `npm run worker:test`: 175 total, 173 passed, 2 skipped because Windows does not permit unprivileged symlinks. Test temporary files used `D:\CTXBenchVerifications\unit-temp`.
- `node scripts/standard-images-ui-smoke.mjs` with Microsoft Edge: English and Chinese task selection, native confirmation/escape, cancellation, retry, reopened progress/failure, completion without polling loops, old-service guidance and no horizontal overflow passed. Screenshots in ignored `artifacts/standard-images-ui/`.
- Existing authoring UI regression passed in both languages; `python -m unittest discover -s scripts/tests -v`: 49 total, 45 passed, 4 environment-dependent skips.
- New backend coverage exercises the public plan/install interface: no evaluator data or task prompts in plans, frozen-data integrity, deduplication, cache reuse, explicit consent, foreign task IDs, duplicate operations, image-platform conflicts, failure, cancellation during silent pulls, and Provider credentials excluded from the download helper environment.

## Docker inside WSL

`scripts/standard-images-smoke.py` ran with current source mounted read-only in the existing worker image, an isolated temporary database and the WSL Docker socket:

- CTX project image `tgloaguen/planbenchx86_opshin_opshin:latest`: inspected and reused; ID `sha256:54606a55032dbae09e0948080da9805d19969219c0ae760cf3e075092065d16a`.
- SWE instance image `swebench/sweb.eval.x86_64.sympy_1776_sympy-12489:latest`: inspected and reused; ID `sha256:da745b29eda94f68cb55a6648fb5767ea6709c242d7cc1c93caee41256ca02c6`.
- `--pull-smoke`: exercised a real Docker SDK registry pull of the tiny `hello-world:linux` transport fixture. Three Docker events received; new test tag removed afterward. This is a download-transport check, **not** an official benchmark environment or full layer-transfer performance test.
- Read-only inventory of the local official files: CTX 138 tasks reference 12 distinct project images (none missing a reference); SWE 500 tasks include 34 matplotlib cases needing the solver compatibility variant in addition to the official grader image. No full-suite downloads were attempted.

## Real SWE-bench grader compatibility

`scripts/swe-harness-compatibility-smoke.py` archived the exact pinned v4.1.0 source from the installed upstream Git clone into an ephemeral container directory. The original v5 installation was not edited. Current `harness.py` and `policy.py` were used; dataset mount read-only, network disabled, no pulls allowed, no model/Agent.

- Official Verified task: `sympy__sympy-12489`.
- Official reference patch applied **only in the evaluator**.
- Result: **1 submitted, 1 completed, 1 resolved, 0 errors**, about 18 seconds of test execution.
- Original project image preserved, **0 images removed** by the harness, no unstopped evaluator containers.

This verifies the changed grading call and dataset-schema compatibility using actual project tests. It is not a real-Provider solve, a 500-task SWE score, a fresh build of all release images, or proof that all CTX baseline-specific dependency recipes work offline.

## 中文结论

安装入口的中英文交互、镜像检查/缓存复用、真实下载通道已验证。SWE 评分器格式不兼容问题通过对齐 v4.1.0 修复，并实际用一个官方用例的参考修复完成评分端自检（通过）。已安装镜像、依赖准备完成、测试通过是三个不同状态，界面不混用。更新尚未提交、发布或热替换正在运行的评测服务；使用需重新构建并安装配套桌面与镜像。

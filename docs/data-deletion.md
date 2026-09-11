# 删除用例、评测集和实验结果 / Delete benchmark data

在桌面端的用例卡片、评测集卡片、实验卡片上点击对应的“删除”按钮。结果表和结果详情中的“删除本轮对照组”用于删除一个用例的某一轮结果。

每次都会打开确认弹窗，先查询当前影响范围，再允许确认。默认焦点在“保留数据”，按 Esc 可取消；提交删除期间不可重复确认或关闭弹窗。数据发生变化时，本次操作不生效，需要重新检查范围并确认。

| 删除对象 | 删除范围 | 保留内容 |
| --- | --- | --- |
| 评测用例 | 独立用例定义，以及所有可编辑评测集对它的引用 | 其他用例、评测集、已冻结的历史定义及结果 |
| 评测集 | 此评测集的组合定义 | 全部独立用例、其他评测集、历史快照及结果 |
| 实验 | 此实验、全部结果记录和该实验的操作队列记录 | 其他实验、用例、评测集，以及下文列出的共享材料 |
| 本轮对照组 | 同一实验、同一用例、同一轮次的全部组别，包括无知识库组 | 其他轮次、其他用例及实验的冻结配置 |

实验需要已完成、失败或取消，且当前操作完全退出后才允许删除。准备中、运行中和暂停中的实验不能直接删除。可先取消任务，等待后台停止后，重新检查影响范围。删除操作不会替你停止远端 CI；如有尚未结束的远端任务，请在取消实验时处理，并到对应平台确认。

删除最后一个成员用例会使评测集变为空集。可以编辑组合补充用例，也可以删除该空集；空集不能启动实验。

删除导入的评测集后，刷新或重启不会自动恢复它。重新导入同一份文件可恢复初始组合；之前编辑过的独立用例不会被覆盖。若只删除了导入集合中的部分用例、但保留了集合，该集合会保持当前组合，不会因刷新或再次导入而补回成员；如需恢复原始完整组合，先删除该集合再重新导入。

## 不自动清理文件

此功能删除的是数据库中的记录，没有一键撤销功能，也不等同于磁盘清理或安全擦除。以下内容不会被删除：

- 冻结的数据集源文件和运行快照；知识库包及约束包。
- Docker 镜像、项目仓库缓存、构建环境缓存。
- 证据文件、已保存的日志、阶段检查点、原始执行请求文件及远端 CI 收据。
- Token 预算、已消耗的 Token 账目；不会因删除实验而返还已使用额度。

删除结果后，后续统计和导出仅包含剩余结果。页面和 HTML 报告会注明已删除对照组，JSON 保留 `deletedResultGroups` / `deletedResultRuns`，CSV 的每行包含该实验的删除计数；全部结果删除后 CSV 只有表头，请用 JSON/HTML 查看空实验及删除计数。实验的冻结配置仍描述原始计划，不能将剩余样本当作未经筛选的完整评测结果。已有导出文件不会被改写。若需备份，请先导出结果；完整恢复仍需工作目录备份。

桌面端与评测服务镜像需同时更新。旧镜像没有删除接口时，弹窗会显示更新提示，不能提交删除。

## API / extension points

`POST /v1/data-deletions/preview` accepts `{ "kind": "case|set|experiment|result", "id": "exact-record-id" }`. `result` accepts a run ID and resolves its complete pair group server-side. The response contains the current impact, blockers and a fingerprint token; it never includes prompts, hidden tests, gold patches or credentials.

`POST /v1/data-deletions` accepts only `{ "kind": "…", "id": "…", "token": "preview-token" }`. The service recomputes the plan under the scheduler lock and a SQLite write transaction. A blocked or stale plan returns HTTP 409, a missing record 404, and malformed input 422. No partial deletions are committed. These endpoints share the existing local-origin protections. They do not invoke Docker, delete files, stop remote workflows or reset budgets.

`worker/ctxbench_worker/deletions.py` owns planning and deletion. `deletionEvents` keeps a minimal receipt with target identity/time/counts (not deleted result payloads). `deletedLibrarySources` suppresses automatic re-adoption of deleted imports. Neither receipt is a backup or an undo stack.

## Verification

Run `npm test`, `npm run build`, `npm run worker:test`. `node scripts/data-deletion-ui-smoke.mjs` uses a locally available Playwright installation and a headless browser (`CTXBENCH_BROWSER_CHANNEL=msedge` on Windows if needed). Its service calls use fixtures only; it tests both languages, actual native dialog focus/stacking, cancellation, stale/blocked requests and every deletion entry point. No existing workspace data is deleted by these tests.

`scripts/case-library-container-smoke.py` also checks deletion after generating context and completing four paired runs in real Docker, using the deterministic mock Agent (no paid Provider). It deletes only that script's fresh fixture records, then verifies that context packages, original snapshots and all saved evidence files remain. Existing services and images are not changed.

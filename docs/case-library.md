# 独立用例、评测集组合与运行快照 / Case library

v0.1.7 新增。桌面端与评测服务镜像必须一起更新；只安装旧版 v0.1.6 不会出现这些入口。

## 从一个后端仓库开始

1. 打开 **评测用例 → 创建评测用例**，填写用例名称。
2. 在 **仓库与环境** 填写 Git 地址、修复前的完整 40 位提交号，选择公司测试镜像或基线中的 Dockerfile。镜像需要有项目所需依赖；测试命令本身不会安装依赖。
3. 在 **任务与测试** 填写任务 ID、需求描述和测试命令。隐藏测试、参考修复只放在评分字段，不能写入 Agent 提示词或知识库。
4. 在 **检查并保存** 检查定义。提供参考修复后可单独运行容器自检。保存用例本身不调用模型，也不创建评测集。
5. 用例卡片可直接点 **生成知识库**，选择 Provider、模型及凭据环境变量后提交；也可以直接点 **新建实验**，比较无知识库和使用知识库的效果。
6. 需要批量跑时，打开 **评测集 → 组合评测集**，命名并勾选已有用例。同一用例可以加入多个评测集；不同评分方式（自定义、SWE-bench、CTXBench）不能混在一个评测集中。

知识库仍只基于代码基线生成。相同基线和构建配置可以复用冻结知识库；用例里的任务描述、隐藏测试和参考答案不会交给知识库构建 Agent。实验中的配对提示词、模型、资源、预算、网络策略和评分材料保持一致，只有冻结上下文覆盖不同。

需要用 GitHub 流水线判定自定义用例时，在 **任务与测试 → 评分方式** 选择 **远程 CI 流水线门禁**。可配置多个必过任务及可选 JUnit 测试数量，CI 配置也随用例冻结；平台令牌单独设置且不进快照。参见 [CI 使用指南](ci-grading.md)。

## 编辑与历史数据

- **编辑评测用例** 可修改仓库、基线、提示词、测试环境、测试及参考修复。版本号递增，引用它的所有评测集在下一次启动时看到最新版。
- **编辑评测集组合** 可改名称、加入或移除成员。移除成员不删除用例，更不删除历史运行。
- 同时打开两个编辑窗口时，旧版本保存会被拒绝并保留当前输入，不会覆盖别人刚保存的版本。启动前发现选择已变更，也会要求重新加载和检查。
- 任务在**创建并进入队列时**自动冻结选中用例；不等真正开始执行才冻结。快照包含源版本、成员版本和内容哈希，执行定义包含完整基线、提示词、镜像/构建定义及评分材料。
- 修改用例不会影响排队中、进行中或已完成的任务。恢复、取消后重试都继续用原快照；要使用新定义请创建新任务。
- 实验和准备任务上的 **查看运行快照** 可回看原定义摘要；**运行快照** 列表集中展示历史版本。公开摘要和导出的快照清单不包含隐藏测试、参考修复；不是完整离线资源包。
- 原始官方数据导入后会产生独立用例和一个初始组合。编辑官方用例会标为本地修改，不应再作为未经修改的官方基准报告。

已导入的旧数据会首次打开用例库时自动迁移。原始数据文件、旧实验及结果不变；旧任务继续使用原有内容哈希，后续编辑不覆盖原始导入。新快照不会重新导入成一套重复用例。

如果 v0.1.7 刚打开页面就提示“单个用例定义不能超过 10MB”，这是旧数据自动载入误用了编辑限额：官方 CTXBench 中有超过 10MB 的测试材料，不是你创建操作有误。此修复需要同时更新桌面端和评测服务镜像；不用删除或重新下载官方数据。已验证的原始导入会完整迁移，不裁剪测试或参考修复；手工保存定义按 UTF-8 JSON 实际字节计算，上限 32 MiB。

单份旧数据丢失或校验失败时，页面会列出受影响的评测集，其余用例与独立创建入口仍可用；恢复该评测服务原有的数据目录后点 **刷新** 重试。列表服务整体不可用时，会明确提示“用例库加载失败”，而不是误报新建用例太大或显示空库；仍可打开创建表单，但保存需要评测服务正常响应。不要通过清空数据目录解决载入错误。

未提交表单不会自动保存，关闭时会居中确认。以前保存的多用例草稿仍可从 **标准下载 → 旧版草稿导入（高级）** 恢复；导入会新增用例与初始组合，而非覆盖现有用例。已保存用例的自检仍在 **用例自检**；自定义资源迁移在 **设置 → 资源迁移**。

## API / storage boundary

The editable library is separate from the immutable catalog. `CaseLibrary.freeze` is the shared execution boundary for experiments, independent context/constraint preparation and source-dependent operator jobs. Selection reads use one SQLite transaction; writes use optimistic revisions and a write transaction. Workers receive only immutable catalog IDs. Resume/retry never resolve a live source again.

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/library` | Migrate legacy imports idempotently; list public cases/sets and nonblocking `importWarnings` per unavailable source |
| `POST /v1/library/cases` | Create `{name, benchmark, row}` without a set |
| `GET/PUT /v1/library/cases/{id}` | Operator-only full definition / save with `expectedRevision` |
| `POST /v1/library/sets` | Compose `{name, caseIds}` referencing existing cases |
| `PUT /v1/library/sets/{id}` | Save composition with `expectedRevision` |
| `GET /v1/library/selections/{id}` | Coherent public tasks and composite `revision` for a case or set |
| `GET /v1/library/snapshots?source={id}` | Immutable run receipt inventory, optionally filtered |
| `GET /v1/library/snapshots/{id}` | Receipt plus public frozen task summaries |

Submit the selection's `revision` as `datasetRevision` when creating experiments or preparing context/constraints. The server returns HTTP 409 on a stale selection/editor. Source IDs use `case-` / `set-`; snapshot provenance uses `snapshot-`; executable datasets retain their content hash. Legacy immutable `/v1/datasets` clients remain supported. The operator definition endpoint includes evaluator-only data and must never be exposed to Agent containers.

No Docker image layers or repository clones are duplicated just to save a definition snapshot. Existing image, baseline and context caches continue to be used. Snapshot rows are content-addressed and verified against both source bytes and normalized database metadata before execution.

## Verification

- `npm test`, `npm run build`, `npm run worker:test`; native `cargo test --manifest-path src-tauri/Cargo.toml --locked`.
- `scripts/case-library-ui-smoke.mjs`: headless English/Chinese creation during list failures, partial-import warnings and recovery, genuine empty states, revision conflict, composition changes, unsaved-close confirmation, direct preparation/experiment and historical snapshot interactions. Uses fixture API responses.
- `scripts/case-library-import-smoke.py SOURCE.json EMPTY_OUTPUT_DIR`: real legacy dataset migration into an isolated fresh database; checks all rows, the largest case's editing/frozen grading data, independent creation, restart idempotence and unchanged source hash. Supports `--benchmark ctxbench|swebench|custom`; no model calls or live database changes. Mount the source read-only in Docker.
- `scripts/case-library-container-smoke.py`: real WSL Docker execution in a unique scratch directory. Edits baseline/prompt/grader/membership after queue capture, independently generates context, restarts coordination, cancels/retries, completes four paired runs and verifies context reuse and future edits. Deterministic mock Agent mode, not a real Provider or full official benchmark run. Existing production services and images are untouched.

2026-09-09 startup regression acceptance: all 138 locally available official CTXBench rows loaded in an isolated WSL Docker container, with zero warnings. Two rows exceeded 10 MB; the largest was 12,635,007 UTF-8 JSON bytes. Its rename/save and frozen row equality passed, as did independent creation and restart without duplicates. The source was mounted read-only and its SHA-256 stayed unchanged. This verifies library startup/import, not execution of all official benchmark tasks; no model calls were made.

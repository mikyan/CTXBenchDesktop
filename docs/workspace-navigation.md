# 工作台导航与配置分层

本文对应 v0.1.5 的 UI 重构。旧版 v0.1.4 仍使用“基础设施”和“实验 → 导入/创建评测集”入口。

v0.1.7 新增：侧栏分为 **评测用例** 与 **评测集**。前者独立创建、编辑用例，也能直接生成知识库；后者仅组合已有用例并编辑成员。二者共用标准导入、自检与运行快照入口，旧版草稿在标准下载的高级导入区域。历史任务与重试绑定启动前快照，不跟随编辑变化，详见[新版操作与数据说明](case-library.md)。以下旧版本导航以此为准。

## 先找到要做的事情

- **概览**：各场景真实已评分次数、选定实验组的配对指标与最近结果。次数不等于完整评测集验收；重复运行不等于独立任务。
- **实验**：实验计划、结果与证据、Token 总预算分别查看。结果支持按 CTXBench / SWE-bench / 自定义筛选；导出按钮明确导出整个工作区，不是仅导出当前筛选。
- **评测集**：已导入评测集与任务浏览、标准集下载、自定义用例自检。创建/导入入口在这里；从评测集卡片新建实验会自动选中该数据集。
- **知识库 / 约束**：冻结包列表和后台生成/挖掘队列分开。查看运行时先展示结论，原始参数与校验标识可展开。

## 设置不再是一张长表单

| 分类 | 配置内容 |
| --- | --- |
| 基础连接 → 运行环境 | WSL 选择、系统诊断、启动与日志；安全停止和手动命令折叠展示 |
| 基础连接 → 模型凭据 | 多组环境变量；只回显配置状态，不回显密钥 |
| 安装与交付 → 应用镜像 | 离线导入/在线构建，与导出定制镜像分开操作 |
| 公司适配 → 公司环境方案 | 可复用的模型/镜像默认值，Git 镜像和 Provider 域名按需展开 |
| 公司适配 → 镜像适配 | 基于已有镜像安装内部依赖、生成新镜像 |
| 公司适配 → 资源迁移 | 自定义评测集、基线、测试镜像和冻结知识库的迁移 |

同一设置页内切换分类不会清空输入；离开设置主页面或关闭软件会丢弃未保存的表单。密钥不会保存到浏览器草稿。保存的密钥只驻留 Worker 内存，重启清除；部署环境配置仍可用。

“公司方案”报接口不存在时，需要更新 Worker 镜像，而不是重新输入 API Key。暂停实验、保留数据卷，再从“应用镜像”安装匹配镜像并显式重启。

## 新建实验三步

1. **任务与对照**：名称、评测集、任务筛选、上下文分支、重复次数。
2. **模型与执行**：Provider/模型、角色额度与共享预算；启动命令、多步 Prompt、Agent 参数、资源和网络在高级项中。默认仍只有一个 Agent 步骤。
3. **检查并创建**：核对计划、执行只读预检，选择“先统一准备知识库”后创建。返回修改不丢输入；变更后原预检失效。

生成知识库不会自动改变求解 Prompt，也不会强制 Agent 读取文档。有/无上下文两侧仍只能在冻结文档覆盖层上不同。

## 2026-09-08 回归验证

- 前端：`npm test`，22 个文件、113 项通过；`npm run build` 通过。新增覆盖分类唯一性、中英文标签、分步表单、真实运行统计和当前实验任务归属。
- Worker：Windows 执行 144 项，142 项通过、2 项因无符号链接权限跳过；WSL Docker 中 144 项全部通过。修复 Windows 临时文件被短暂占用导致的清理抖动，持续失败仍会上报，不隐藏断言失败。
- 操作脚本：48 项，44 项通过；4 项需显式启用的镜像打包往返测试跳过，本轮未修改打包逻辑。新增评分对照测试确认不调用 Agent、不联网、不允许危险任务路径逃逸，并能识别错误的正负判定。
- 原生层：18 项通过、6 项需要显式外部操作的测试忽略；另完成 Windows 原生启动和真实 WSL/Docker/Worker 诊断检查。
- Docker 集成：真实容器、模拟 Provider 的 8 次配对运行通过，覆盖冻结包复用、人工导入、基线构建、负评分、取消清理、镜像重标记后仍使用固定镜像。
- 界面实测：中文/英文、六类设置、未保存表单的分类切换、新建实验前进/返回、任务筛选、结果证据展开，以及 1060×680 最小桌面宽度无横向裁切。

真实 MiMo CTXBench 专项与模拟 Provider 集成分开记录，见 [CTXBench 专项验收](ctx-live-acceptance.md)。构建仍有约 595 kB 单个 JS 分块的体积提示，不影响构建和原生启动；未将其描述为零警告。

## English overview

Settings has six task-oriented categories: Runtime & diagnostics, Model credentials, Application images, Company profiles, Image adaptation, and Resource migration. Datasets is now a primary destination with library/download/self-test views. Experiment plans, results, and budgets have separate views; creation has Tasks → Execution → Review steps. Advanced configuration is collapsed, not removed. Section switches preserve in-memory input, but leaving a main page does not persist unsaved forms.

The redesign is included in v0.1.5. Older v0.1.4 downloads retain their previous navigation. This is a presentation change, not a change to paired experiment, credential, context discovery, or evaluator-isolation rules.

## v0.1.6：导入和异常恢复

以下改进从 v0.1.6 提供，需要同步更新桌面和评测服务镜像；v0.1.5 不包含这些改进：

- “本地评测服务”替代日常界面中的“工作节点”；Worker 只在技术说明、日志和容器名中保留。
- 运行环境与应用镜像页面都显示镜像更新安全检查。列出所选 Docker 中运行的服务、Agent／知识库生成和评分容器；未知状态不等于空闲。停止需要确认已暂停并等待任务结束，不自动删除容器或数据卷。
- 导入／构建前在原生层再次检查容器；离线导入器完成文件校验后还会复查。其他部署的服务也会阻塞镜像替换，本部署停止按钮不会强停其他部署。
- 失败消息带刷新、日志、运行环境、离线安装或版本下载等处理入口。查看日志不会覆盖原始失败；构建失败后的进度条不再继续转动。
- 评测集导入改为本地 Parquet／JSON／JSONL 文件选择、检查、确认、成功结果四个状态，取消了手动填写服务路径。上限 32 MiB，预览不返回参考补丁或隐藏测试，登记前保持只读。
- 数据目录说明明确 `/var/lib/ctxbench` 为服务管理目录，日常导入不需要用户拥有其写权限。`CTXBENCH_HOST_DATA_DIR` 是高级挂载配置，不是自动迁移功能。

验证：前端单元／构建、原生单元、Worker 单元、脚本回归，以及 `scripts/maintenance-ui-smoke.mjs` 的中英文页面点击检查。`scripts/dataset-file-import-smoke.py` 在独立 WSL Docker 测试目录中实际传送、解析并确认了固定快照的 CTXBench 138 项和 SWE-bench Verified 500 项；没有调用 Agent、没有修改生产数据目录。该检查验证导入，不代表全套 benchmark 已执行。

### 用例创建与确认弹窗（v0.1.6）

- 长表单固定标题与关闭按钮，内容单独滚动。放弃编辑、覆盖草稿、删除用例、停止服务、取消实验／准备任务均采用居中的原生确认框，默认焦点放在保留操作上。Esc 只退出最上层确认框，恢复原焦点；Tab 不穿透到底层表单。
- 异步处理期间禁用关闭按钮并说明原因。提交、导入和日志读取失败时将错误移入视线；成功、进度和普通说明仍保留在对应区域，避免过多弹窗。
- 删除非空编排命令、删除有内容的提示词步骤、用默认提示词覆盖自定义内容，需要确认；不改动已冻结的实验。
- 自定义测试镜像支持当前 WSL 的本地列表、刷新、手工填写，以及四类基础镜像的用途和复用条件说明。不是安装状态即兼容，不自动选择不合适的测试环境；标准库 Python 模板改用 `python3`。

交互回归：`scripts/authoring-ui-smoke.mjs` 使用隔离的 Edge 页面与模拟服务响应，覆盖中英文、长表单、焦点／Esc、保存期间关闭、三种草稿覆盖入口、镜像列表失败与手填、创建成功、编排内容保护、实验／准备任务取消。`scripts/maintenance-ui-smoke.mjs` 继续覆盖维护确认和文件导入。不会启动真实 Agent、提交真实评测集或修改生产数据。

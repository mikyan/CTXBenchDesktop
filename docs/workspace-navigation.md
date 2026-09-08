# 工作台导航与配置分层

本文对应 v0.1.5 的 UI 重构。旧版 v0.1.4 仍使用“基础设施”和“实验 → 导入/创建评测集”入口。

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

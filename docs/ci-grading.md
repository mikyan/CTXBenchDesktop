# 自定义用例接入 GitHub 流水线 / CI grading

v0.1.7 新增。需同时更新桌面端和评测服务镜像。原来的本地 Docker 测试命令仍然可用；官方 SWE-bench / CTXBench 评分方式不变。

## 先分清两种“用例数”

- **评测用例**：你在用例库里创建的一个编码任务。门禁全过，该次评测才算功能通过；知识库对照组分别评分。
- **单元测试数量**：例如 `mvn test` 执行了 120 个测试。GitHub 的 job 数量不是单测数量。填写 JUnit 产物名称后，可统计总数、通过、失败、异常和跳过；不填则只判断门禁，数量显示为未知，不会伪记为 0。

此版本是**自动提交候选代码、触发指定工作流并读取结果**，不是关联一个任意的已有 CI 绿勾。软件会为每个对照组、每次重复创建独立的 `ctxbench-eval/<id>` 分支，不合并 PR、不覆盖已有分支、不删除分支。

## 第一次配置：以 Maven 后端为例

1. 准备一个**专门用于评测的 GitHub 仓库**。可见性要符合代码保密要求。不要放生产密钥，不要有提交代码后自动部署的工作流，不要让不可信候选代码使用有生产权限的自托管执行节点。创建评测分支也可能触发仓库原有的其他自动化，请一并检查。
2. 将 [Maven 工作流示例](../examples/ci/github-maven.yml) 放到该仓库的 `.github/workflows/ctxbench.yml`。把示例中的镜像占位符换成你批准的、固定 digest 的 Maven/JDK 镜像，并配置项目依赖源。示例不能在未替换镜像时直接运行。
3. 将工作流提交到默认分支并启用。用包含工作流的**完整 40 位 commit** 作为用例基线。工作流必须支持 `workflow_dispatch`，且不能要求本工具未提供的必填 inputs。它应检出当前评测提交（`${{ github.sha }}`），不要检出 `main` 或“最新版本”。建议先由你在 GitHub 手动验证一次工作流能运行且报告上传正常。
4. 软件中打开 **评测用例 → 创建评测用例**，填写同一个仓库、基线、任务提示词，以及本地 Agent 所需项目镜像。此镜像给容器内 Agent 提供编码工具；**最终构建和测试改由远程工作流环境执行**。
5. 在 **任务与测试 → 评分方式** 选择 **远程 CI 流水线门禁**，展开 **添加平台连接／新配置版本**，填写：

   | 字段 | GitHub.com 示例 |
   | --- | --- |
   | 平台 | GitHub Actions / Enterprise |
   | API 根地址 | `https://api.github.com` |
   | CI 代码仓 | `your-team/backend-bench`，不是完整 URL |
   | 工作流文件名 | `ctxbench.yml`，不是 `.github/workflows/ctxbench.yml` |

6. 保存连接，再展开 **平台访问令牌** 单独输入 Token。推荐只授权该评测仓库的 fine-grained token，需 **Contents: Read and write**、**Actions: Read and write**，并完成组织要求的审批。令牌仅保存在评测服务内存，不进入用例、快照、Agent 环境变量或日志；评测服务重启后需重新输入。**保存连接和设置令牌都不上传代码、不触发流水线。**
7. 必过门禁填写 `test`（与示例 `jobs.test.name` 一致）。多个门禁每行一个，必须使用准确显示名称，包括矩阵展开后的后缀。需要统计测试数时，JUnit 产物填 `test-results`，最少实际执行测试数设为 `1` 或符合项目规模的下限。
8. 检查上传授权提示并勾选，保存用例。直接新建实验或将它加入评测集；选择真实 Provider 和模型后执行。GitHub Actions 可能消耗 CI 额度。Mock 模式不会启动真实 CI；本地“用例自检”也不会上传代码，CI 用例应通过实验验证。
9. 打开运行详情，查看 **CI 流水线证据**：分支、候选提交、流水线编号、门禁、单测统计。可复制对应流水线地址到浏览器排查。

私有仓库的**本地基线获取凭据**与**CI 平台令牌**是两回事。此功能不会把平台令牌交给 Agent，也不会自动拿它给 Git clone 登录。请先通过现有 Git 镜像映射、预置基线缓存或公司批准的克隆凭据方案确保评测服务能取得基线。

## 怎么判定通过

工作流必须完成，整体状态和每一个指定门禁均须成功。缺失、重复、跳过、取消、超时及无法读取的门禁会报告执行异常，不会当作测试通过。成功读取且门禁明确失败才产生功能 FAIL；缺证据的执行异常不伪造功能评分。

填写了 JUnit 产物时，还要求：产物属于本次候选提交、名称唯一且未过期；XML 有实际 `<testcase>`；`总数 - 跳过数 ≥ 最少实际执行测试数`；失败和异常均为 0。统计逐个 testcase，不信任测试套件中可能重复或失真的汇总属性。报告需为包含 JUnit XML 的 ZIP，支持 Maven Surefire 等输出；其他格式由工作流先转换。为避免误计，不要在同一产物里重复放同一轮测试报告。

示例不吞掉 `mvn test` 的失败退出码，并用 `if: always()` 上传失败时的报告。若项目自己配置了“忽略测试失败”、跳过测试或伪造报告，工具无法仅凭绿勾证明实现正确。应由评测维护者保证测试和门禁有效；更改构建脚本或测试框架设置后要重新审核。

## 快照、复现与安全

- 用例快照固定连接版本、门禁名称、报告要求和超时；执行准备阶段解析并固定基线 Git tree 与工作流版本。两个对照组复用同一个目标配置，不修改任务提示词、不提示 Agent 阅读知识库。
- Agent 仍在 Docker 内编码。评分只将基线加 `graded.patch` 得到的候选文件变更提交到平台；不会上传本地隐藏测试、参考修复、挖掘约束、Agent 对话或凭据。CI 用例不能同时附带本地隐藏测试/参考修复补丁；隐藏评分材料应放在平台受信任的评测设施中，不能放进 Agent 可见仓库。
- 候选改动触及 `.github/` 或适配器声明的评分保护路径时，会在远程提交前拒绝。它不能自动保证仓库其他测试/构建脚本也不可被篡改。严肃测评可通过公司网关的 `protectedPaths` 增加保护，或在可信评测侧恢复固定评分材料。
- 工作流固定不等于远程环境完全固定。必须自行固定镜像 digest、Action commit、工具链、依赖、外部评分材料与资源限制；使用相同的 runner 配置，避免在配对期间修改平台变量、密钥、缓存内容或外部脚本。软件不能冻结 GitHub 托管 runner 的底层宿主系统。
- GitHub 结果匹配同一仓库、工作流、事件、分支、候选提交和执行尝试，不读取“最近一次成功”。恢复任务观察原流水线，不重复触发。发生不确定的 dispatch 网络错误时，宁可等待原流水线出现，也不自动再发一次。
- 暂停只停止本地等待，远程流水线可能继续。取消会尝试取消已提交的对应远程评测；失败会提示人工检查。超时后可重试继续观察。若首次触发实际未成功且没有任何流水线出现，请检查平台后创建新实验；不要手动重跑原流水线来替换历史结果。
- 评测分支保留用于审计，需你按保留策略手动清理。此功能不删除远程分支或报告。软件保存报告 SHA-256、产物 ID 和聚合统计，不保存原始 XML、测试名称、平台日志或签名下载 URL。

## 公司内网如何替换

**GitHub Enterprise**：仍选 GitHub Actions，API 地址改成企业实例的 `https://git.company.example/api/v3`，用例来源仓库也使用该实例。认证和工作流规则按公司策略配置。GitHub.com 的 Action 示例并不直接等于 GHES 兼容版本：`upload-artifact` v4+ 当前不支持 GHES，需按企业版本选用受支持的 Action 并固定 commit；镜像和 Action 源也需要在公司可达。

**其他平台**：已有 **公司 HTTP CI 网关** 适配器，不需要把 GitHub 逻辑改散到各个页面。实现 [公司网关协议与适配指南](ci-platform-adapter.md) 的五个操作，再在页面选择该平台和网关根地址即可。网关负责翻译成公司流水线接口和 JUnit 报告；统一评分规则、快照、上下文对照实验无需改动。此适配器不是“把 Jenkins 任意 URL 填进去就能用”，需要公司侧实现协议。

## 开发验证范围

后端测试覆盖真实本地 Git 候选树、完整配对执行调度（fixture Agent/平台）、门禁分页、提交身份、断线幂等、报告解析、取消和凭据隔离；英文/中文浏览器测试覆盖创建、授权、保存、编辑及统计展示。2026-09-08 又完成了[真实 GitHub Actions 联调](ci-live-acceptance.md)：原样候选 PASS、故障候选 FAIL，均读取 192 项 JUnit 测试，重启观察复用原流水线。该次未调用模型，也未验证真实企业平台；企业上线仍需使用专用仓库做实际联调。

另外在 WSL Docker 的临时、禁网容器内执行了 20 项 CI 专项检查，源目录只读挂载，使用 fixture 平台与 Agent；没有重启或更换现有评测服务。生产镜像不包含 API 测试客户端，所以该容器检查选取核心评分、GitHub/公司适配器、恢复及配对调度测试；HTTP API 测试由本机开发环境执行。

## English quick start

Custom cases can use **Remote CI pipeline gates** instead of a local Docker grading command. Save a GitHub Actions connection, configure its token separately, specify exact required job names and optionally a JUnit artifact/minimum executed-test count, acknowledge remote execution, then start a real-Agent experiment. Each arm/repeat gets its own evaluation branch. No report means unknown test counts, not zero; job count is never unit-test count. The Agent remains containerized and never receives the platform token. Connection versions and grading targets are frozen; old experiments are not repointed by editing a case. Restarting the evaluation service requires re-entering its in-memory token. See the linked adapter contract for company platforms and the [real GitHub CI acceptance record](ci-live-acceptance.md) for verified pass/fail, counts and restored observation. The acceptance controls did not call an Agent or measure knowledge effects.

References: [workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event), [workflow runs](https://docs.github.com/en/rest/actions/workflow-runs), [attempt-specific jobs](https://docs.github.com/en/rest/actions/workflow-jobs), [artifacts](https://docs.github.com/en/rest/actions/artifacts), [checkout](https://github.com/actions/checkout), [upload-artifact / GHES support](https://github.com/actions/upload-artifact).

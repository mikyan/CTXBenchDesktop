# Docker Pi → MiMo → GitHub CI 全链路验收

2026-09-08 已真实跑通。与[之前仅测试 CI 的正反例](ci-live-acceptance.md)不同，这次候选补丁由 **Docker 内的 Pi 0.84.4 调用 MiMo v2.5 自行生成**。验收脚本没有编写或提供答案补丁，也没有直接调用评分模块绕过任务队列。

## 跑了什么

使用用户的公开仓库 `mikyan/CTXBenchDesktop`，基线为此前已证实会失败的提交 `15676d44d236c2e4b01afb2d2774c4f4446b0585`。任务是修复 SWE-Shield 兼容相似度评分退化，保持接口，不修改测试和流水线。

实际经过：正常服务 API 创建独立用例 → 冻结用例快照 → 创建实验并排队 → 拉取固定基线 → 创建隔离 Docker 容器 → Pi 调用真实 Provider 查代码、修改代码及自行测试 → 提取候选补丁 → 上传 GitHub 专用评测分支 → 触发固定工作流 → 检查门禁并解析 JUnit → 软件自动写回 PASS。

实验 `exp-6204d3b488c3`，快照 `snapshot-d91b00417e974d2ea980a35a947a26da`。未生成知识库；使用 `none` 与 `developer-historical` 两组、各一次，同一个用例独立执行两次。两组提示词、基线、模型、资源、预算、网络策略和评分输入一致，配对哈希一致。没有把第一轮候选拿来作为第二轮起点。

## 实际结果

| 运行组 | 模型 Token（含缓存读取） | CI 测试总数 | 通过 / 失败 / 跳过 | 软件判分 |
| --- | ---: | ---: | --- | --- |
| [保留基线既有上下文](https://github.com/mikyan/CTXBenchDesktop/actions/runs/34224153508) | 168,287 | 192 | 191 / 0 / 1 | PASS |
| [不加载知识库](https://github.com/mikyan/CTXBenchDesktop/actions/runs/34224328594) | 69,830 | 192 | 191 / 0 / 1 | PASS |

两轮 errors 均为 0。跳过的是仅适用于 Windows 8.3 目录别名的用例。原故障基线的相同测试集为 190 通过、1 失败、1 跳过；本次两轮均修复了真实失败的断言。

两次独立 Pi 会话均只修改 `worker/ctxbench_worker/constraints.py`，没有修改测试或 CI 定义。补丁均为 722 字节，SHA-256 均为 `365108fbd771fc6bae3670a27f1798e19849db3aec761452163db788fef65113`。轨迹中保留模型自己的查找、编辑和测试工具调用。

总计 **238,117 Token**，两次 Agent 会话，不是两次底层模型请求。每阶段上限仍为 5,000,000。先在原有 1,000,000,000 总预算中预留本次两阶段最大额度，再按独立子账本的真实已确认用量结算；没有重置、扩容或绕开总账。结束时本次预留全部结清，无不确定用量。

## Docker 和凭据

- Agent 镜像：`ctxbench/agent-pi:args-dev-20260907`，运行时固定为 `sha256:d9d1566b02efff953dc8d5489461f111a39a6e3d321c9a3fe73c7b5c5de79992`。
- 两次独立容器；非 root 用户 `10001:10001`，2 CPU / 4 GiB，30 分钟，`api-only` 网络，经已有出站代理访问 Provider。
- Agent 只挂载基线工作区、自己的输出目录和只读请求文件；没有 Docker socket。环境变量只显式传入 MiMo 所需密钥，**没有 GitHub 令牌**。
- GitHub CLI 的凭据仅注入本地评测服务内存，评分服务负责上传候选和读取 CI；任务、快照和 Agent 不持有平台凭据。
- 对本地 12 个证据文件、WSL 独立数据目录的 2,963 个文件进行凭据字符串扫描，零命中。
- Pi RPC 完成时会发出 `agent_settled`，收集用量后适配器主动停止 RPC 子进程；结果中的子进程退出码 143 对应这一收尾过程，不是超时。两轮 `settled=true`，没有预算中断或请求错误，最终是否修复仍由独立 CI 判定。

Agent 基础镜像没有 pytest 和全项目依赖；本次 Pi 自行改用 Python 标准库 unittest 验证相关测试。**完整 192 项测试是在 GitHub 的固定 Python 3.13 Docker 环境中安装依赖后执行**，不是声称基础 Pi 镜像能直接构建所有项目。内网自定义项目仍应选择自己的项目镜像，或使用项目环境准备和启动命令。

## 证据与外部改动

本地报告：`artifacts/ci-agent-live-20260908-run2/report.json`。同目录保留用例定义、实验请求、完整结果快照、容器配置证据、两个 `result.json`、模型轨迹及原始候选补丁。Windows 导出保留 LF 字节，可直接核对补丁哈希。

完整独立服务数据保留在 WSL `/tmp/ctxbench-ci-agent-live-x65hFuhR`；这是验收临时目录，不是用户数据目录默认值，不应依赖其永久保存。临时服务端口为 `48174`，运行结束后已关闭，临时 API 和 Agent 容器均已移除，原桌面端服务和代理未重启。验收用例及实验没有混入正式桌面数据库；正式总预算仅增加一条汇总消费记录。

新增远程评测分支/提交：

- `ctxbench-eval/034533395d049f6c8e7d7547d951c553` → `87046823a3534807a4c415ff9352f6852bdfe751`
- `ctxbench-eval/76f5d66c4a7df5ab2cf837a3075d5dad` → `a90ecb7a13763117385c20784fc918637364f9d8`

`master` 前后均为 `bcae82cb3d7496d7adba0f2544187bf32ec5fc3b`。没有合并、创建 PR、发布 Release，也没有推送本机尚未提交的功能代码。远程评测分支保留供审计，JUnit 产物按工作流保留 7 天。

## 复跑

脚本：[scripts/ci-agent-live-acceptance.py](../scripts/ci-agent-live-acceptance.py)。这是当前开发机和已审核仓库的验收工具，不是通用数据集下载器。要求 `gh` 已登录 `mikyan`、Python 已安装 `requests`、WSL `Ubuntu` 有 Docker、现有评测服务已配置 MiMo，并已有上述 Agent/worker 镜像及出站代理。脚本通过 loopback API 配置内存凭据，使用当前源码启动独立服务。

以下命令会真实消耗模型和 GitHub Actions 资源；使用全新输出目录，默认端口 `48174` 必须空闲：

```powershell
python scripts/ci-agent-live-acceptance.py --execute-paid --execute-remote --root artifacts/ci-agent-live-next
```

脚本发现费用状态不确定时保守保留预留额度，不把中断当成零费用。不自动删除审计分支和历史报告。

## 验收边界

这次证明一个自定义用例的 **应用 API/队列 → 真实容器 Agent → 真实模型 → 真实 CI → 结果落库** 已通。不是用鼠标重做整套桌面 UI，也不是官方 CTXBench 全集验收、知识库生成质量或统计显著性实验；没有新增上下文包，不能由两轮 Token 差异推断知识库收益。

本机回归：后端 250 项（248 通过、2 项 Windows 符号链接条件跳过），前端当前 `src` 的 146 项通过，生产构建通过。默认 `npm test` 也通过，但会额外发现历史验收检出目录中的测试；因此这里不把其 806 项总数误报为当前源码新增覆盖。

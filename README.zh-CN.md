# CTXBench Desktop

[English](README.md) | [简体中文](README.zh-CN.md)

CTXBench Desktop 是本地优先的 Windows 桌面代码 Agent 评测工作台。它在相同仓库、基线 commit、任务提示词、模型和资源配置下，对比有无冻结知识库的生成效果，并结合功能测试与 SWE-Shield 风格的设计约束评审。

命名说明：论文 [v1](https://arxiv.org/html/2602.11988v1#S3) 将评测集称为 AGENTbench，[v2](https://arxiv.org/html/2602.11988v2#S3) 改称 CTXbench。因此界面统一显示 **CTXBench（原 AGENTBench）**；官方 `eth-sri/agentbench` 地址、内部来源标识及既有冻结数据保持不变。名称更新不代表已逐项核验 v2 的全部测试修订。

## 支持的场景

- **SWE-bench**：导入官方任务，执行代码修复，使用官方测试评分。
- **CTXBench（原 AGENTBench）**：对比无知识库、Skill 生成、人工导入和基线自带上下文。适配 [CTXBench 论文](https://arxiv.org/abs/2602.11988)及[官方仓库](https://github.com/eth-sri/agentbench)的数据和评分工具。
- **SWE-Shield 风格约束评测**：从基线截止日期之前的历史 PR 评审中挖掘设计约束，再由三个独立评审会话判断候选补丁是否满足约束；支持测试通过后仍违反约束的统计。这是有来源证据的兼容实现，不是论文的逐项完整复现。
- **自定义任务**：可在 **实验 → 创建评测集** 中按四步向导添加任务，设置默认或独立仓库环境、测试命令及隐藏测试；支持定义校验和 JSON 导出，也保留 manifest 导入。[查看用例设计与创建指南](docs/custom-datasets.md)。

知识库是被动的仓库文件，例如 `AGENTS.md` 或文档目录。工具不会修改任务提示词、插入检索提示或强制 Agent 阅读知识库。生成只依赖指定基线，不得接触目标 PR、标准答案、隐藏测试、未来历史或挖掘出的约束。

知识库按内容寻址存储，可先统一生成并冻结，再跨重复实验或模型复用。配对实验除了上下文覆盖层之外，必须保持其余输入一致；单任务多次重复不等于总体效果已经得到验证。

## 当前工作台能力

- 预装 Pi 的 Agent 容器、Provider / 模型选择、按角色设置 Token 额度，以及显式白名单环境变量注入。
- 持久化 WSL Docker Worker：数据集导入 → 准备知识库及环境 → 求解 → 功能评分 → 约束评审。
- 实验及独立知识库生成、约束挖掘任务的暂停、恢复、取消和阶段重试。
- 中英文界面、实时运行状态、轨迹、补丁、投票证据、冻结包检查及导出。
- 功能通过率、知识库提升、方差、胜负平，以及 DSR / DVR / DNR / PPVR 等约束指标。
- JSON、电子表格安全的 CSV、自包含 HTML 报告，以及包含镜像构建源码的 Windows NSIS 安装包。

关闭桌面窗口**不会**停止后台 Worker 或批次。暂停允许当前阶段结束并保存检查点；取消会停止活动容器。中断的 Agent 阶段会从干净工作区重试，不会沿用半修改的目录。

## 开发启动

```powershell
npm install
npm run dev
```

访问 `http://localhost:43173`。浏览器开发模式通过 Vite 代理连接**真实 WSL Worker**，断开连接时不会偷偷显示示例成绩。只有显式访问 `http://localhost:43173/?demo=1` 才会进入带标记的界面演示。

源码级 API 开发（不是容器评测验收）：

```powershell
python -m pip install -r worker/requirements-dev.txt
npm run worker:dev
```

启动桌面开发模式：

```powershell
npm run tauri dev
```

源码 Worker 默认使用确定性测试适配器。完整评测必须使用 WSL / Compose 部署，即使 Provider 选择用于基础设施测试的 `mock` 也必须容器化。桌面基础设施控制仅在 Tauri 应用中可用，浏览器预览不具备这些原生能力。

## 桌面操作流程

首次安装、内网镜像导入及“工作节点无法启动”等问题，请看[桌面安装与故障排查](docs/desktop-setup.md)。基础设施页面提供分步引导、启动条件检查、脱敏日志和带实际绝对路径的手动命令；默认启动只使用本地镜像，不会自动构建或拉取。

**发行版自动检测**：基础设施页面通过 `wsl --list --verbose` 列出本机已安装的发行版及 WSL 版本，可下拉选择，也可手动输入 `Ubuntu-24.04` 等准确名称。软件会记住你的选择；首次使用优先选 WSL 2，条件相同时优先系统默认发行版，不会自动选中 Docker Desktop 的内部发行版。安装或导入新发行版后可点击“刷新发行版”。版本判断不再依赖内核名称；启动失败会保留具体错误。此功能仅在桌面应用中可用。

1. 在**基础设施**中选择 WSL 发行版，构建镜像并启动 Worker。Agent 环境变量支持**添加变量**，填写多组名称和值后**保存全部环境变量**（仅保留到 Worker 重启），或通过部署环境变量配置；不要把密钥写入仓库、镜像或知识库。在实验、知识库生成和约束挖掘窗口中，可勾选多个已配置变量，或输入以换行、空格、逗号分隔的变量名；此处只填名称，不填值。只有选中的变量会传入 Agent，地址等配置是否生效取决于 Agent 是否识别对应变量名。
2. 在**实验 → 导入数据集**中导入 JSON / JSONL；parquet 文件须先放入 Worker 的 `/var/lib/ctxbench/datasets`。官方来源：[CTXBench（原 AGENTBench）](https://huggingface.co/datasets/eth-sri/agentbench)、[SWE-bench Verified](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified)。导入内容会计算哈希并冻结。
3. 选择实际任务、Provider / 模型、各角色额度、资源、重复次数及上下文分支。选择**先准备全部上下文**可停在 `ready` 状态，之后显式恢复求解。
4. 跨模型复用时选择**冻结包**。支持 JSON 包和文档目录，仓库与基线 commit 必须完全匹配。人工提供的基线声明是作者声明，并不能证明文档确实基于该版本生成。
5. 按需开启历史 PR 约束挖掘。自动生成的约束包标为银级（silver）；三个评审会话相互独立，可配置不同模型。评审失败会明确报错，不会伪造为中立票。
6. 查看配对结果和证据后导出报告。基础设施错误不应算成模型功能测试失败，也不能进入有效功能评分的分母。

## 启动命令与多步 Prompt 编排

在新建实验中分别展开**知识库生成编排**和**评测求解编排**；单独生成知识库的窗口也提供相同配置。默认没有启动命令，只有一步，使用原有的生成指令或当前任务 Prompt。可添加、删除、上下移动步骤，每步填写自己的 Prompt；`{{default_prompt}}` 可引用该阶段原有的默认 Prompt，不会额外注入知识库读取提示。

- **启动命令**在用户启动任务后、Agent 模型调用前执行，只在隔离容器内运行。多条命令共用 Bash 环境，`export`、`source` 激活的环境会传给所有后续步骤。镜像已预装 Python pip/venv；建议在 `$HOME` 下创建虚拟环境，固定依赖版本。命令不能修改基线代码、提交或知识上下文；系统级依赖仍应放入 Dockerfile。
- **独立步骤**顺序执行，共享容器、依赖和工作目录文件，但每步开启全新的 Pi 会话，不自动传递前一步对话。最终合并所有步骤的文件改动再评分；知识库文件仍只能来自文档路径。
- **失败与预算**：安装失败不调用模型；中间步骤失败或超时会阻止后续步骤。整条流程共享所选角色原有的 Token 和超时额度，增加步骤不会自动扩大额度。失败、中断后重试会从干净容器重新执行该流程，当前不提供步骤中间断点续跑。
- **网络与评分隔离**：启动命令遵守用户选定的网络策略，`api-only` 不会自动放行 pip/npm 仓库。内网包源需配置代理白名单，或预装进镜像；若显式选择 `unrestricted`，该策略对整条 Agent 流程生效。启动命令不在隐藏测试评分器中执行，评分依赖仍由用例测试镜像/官方评测环境准备。
- **配对与复用**：有、无知识库两侧使用相同求解编排；改动命令或 Prompt 会改变配对标识，生成编排变更也会产生新的知识库缓存标识。已完成的冻结知识库仍可供多个实验复用。
- **证据**：知识库准备队列提供**编排日志**；求解运行详情中可选择 `workflow.json` 查看每步状态和用量，选择 `setup.log` 查看脱敏后的安装输出。

使用此功能需要更新桌面、Worker 和 Pi 镜像。内部 Agent 镜像须实现工作流协议 v1 并声明 `io.ctxbench.workflow=1`；旧镜像不会静默忽略编排。命令和 Prompt 会作为实验配置保存，请只引用环境变量，不要直接粘贴密钥。

## 额度、批次与磁盘

创建大实验前先做**工作量预检**；桌面中超过 20 个任务时必须预检。它计算求解、生成、挖掘和评审调用次数及配置额度之和，不调用 Provider，不扣除缓存命中，不估算真实账单，也不单独执行实验级硬限额。

需要跨实验控制消费时，在实验页创建并关联**共享 Token 预算**。目前核验过的记账适配器支持 MiMo Token Plan 中国区（`mimo-v2.5` / `mimo-v2.5-pro`）及基础设施 mock。所有角色必须使用该预算授权的 Provider / 模型。

- 新表单和批次默认每个角色累计 **5,000,000 Token**、总额 **1,000,000,000 Token**，均可配置；这是上限，不是预计消费。
- 每阶段预留累计额度及两次最大模型请求的裕量；当前 MiMo 模型的裕量为 2,359,296 Token。已完成且协议确认的调用释放未使用预留；失败、缺失用量或崩溃恢复会保守记账。
- 界面区分模型已上报用量、保守记账与在途预留。缓存输入也计入 Token；订阅产品上报费用为零不代表免费。
- 创建预算不能覆盖旧预算。提额必须显式使用界面或 `POST /v1/token-budgets/{id}/increase`，提交 `expectedLimitTokens`、`limitTokens`、`reason`；原用量、尝试、预留和提额审计记录会保留。
- 修改阶段额度必须建立新配对实验，不得把旧额度成绩混入新配置，也不会为了剩余额度单独降低某一分支的额度。

`scripts/run-campaign.py` 默认只冻结官方 638 任务计划，只有 `--execute` 才启动真实调用。必须指定 `--budget-id`、`--root` 和不可变的 `--agent-image sha256:...`。顺序为两个公开的兼容性用例，随后按种子固定的仓库轮转交替运行两个数据集，每分支重复两次。`--stop-after 2` 可仅验证兼容性前缀；它不是代表性样本。

保留旧任务顺序但改变阶段额度时，使用新 `--root`、独立 `--campaign-id`、原 `--budget-id`、`--source-plan /path/to/old/plan.json`、新 `--stage-tokens` 与已授权总额。旧计划和旧成绩保留，不按结果挑选跳过任务，不重置消费。

同一计划只能有一个协调器，操作系统文件锁会拒绝重复启动。恢复时使用同一状态目录和参数；不要因看到锁文件就删除它，进程退出后系统锁会自动释放。暂停或取消当前实验会让协调器退出，不会继续派发下一条；恢复实验和重启协调器都需要显式操作。

连续三条任务没有任何有效功能评分时，批次会停止诊断；同时检查全局和**每个数据集各自的连续记录**。交替执行时，SWE 的有效结果不会清除 CTX 的失败计数。正常的功能测试未通过仍是有效评分，会清除相应连续异常计数。停止原因及相关实验 ID 写入状态文件，不自动跳过问题任务。

**项目在 D 盘不代表 WSL 数据也在 D 盘。** 镜像和 `/var/lib/ctxbench` 默认位于所选 WSL 发行版的虚拟磁盘。Linux 的虚拟磁盘可用空间不等于 Windows 宿主卷的实际剩余空间，两者都要检查。Worker 的 `CTXBENCH_MIN_FREE_GB` 默认为 5 GiB；批次传入 `--host-volume`，挂载 WSL 所在 Windows 卷的空目录用于容量检查，可在宿主剩余不足 25 GiB 时停止。运行中的阶段仍可能占满磁盘。当前不自动清理保留的镜像或证据。

## WSL Worker 与镜像

在所选 WSL2 发行版中安装 Docker Engine 后，在仓库目录执行：

```bash
docker compose -f docker/compose.yaml --profile build-only build
docker compose -f docker/compose.yaml up -d ctxbench-worker
```

构建产物包括 Pi Agent、Worker、出口代理，以及固定上游 SWE-bench / CTXBench（原 AGENTBench）评分工具版本的 `ctxbench/official-harness:0.1.0`。

也可以提前生成**独立于桌面安装包的离线镜像包**：

```bash
python3 scripts/images-release.py pack --version v0.1.0 --output artifacts/images-v0.1.0
```

GitHub Actions 的 **Offline Docker images** 支持手动构建下载；发布 Release 时会基于对应标签构建并上传独立镜像附件。包内包含 gzip 分片、SHA-256、镜像清单、中英文说明、自包含导入器和禁止联网构建/拉取的 Compose 文件。仅包含四个应用镜像，不包含用例镜像或数据。内网导入、发布权限、版本匹配和使用示例见[离线镜像发布说明](docs/offline-images.md)。

Agent 容器没有 Docker socket，只接收白名单环境变量。可信评分监督进程可下载或构建环境；正式测试子容器断网并限制 CPU / 内存。官方测试选择及评分规则保留。

新建 CTXBench 实验会在**任何知识库生成或求解调用之前**准备基线专属评分环境：原始实例镜像可能只有仓库，没有 Python 等运行依赖。准备命令在同一个联网 shell 内执行，保留虚拟环境激活；准备子容器没有宿主目录挂载、Docker socket 或注入的 Provider 密钥。完成后按 digest 冻结镜像，再在独立断网容器中执行标准答案自检。自检通过才允许后续 Agent 阶段；标准答案和隐藏测试不会写入可复用的准备镜像，也不会交给 Agent。

正式测试同样保留 shell 状态。结果 JSON 缺失、为空或类型错误会明确算作评分器异常，执行诊断保存在评测专用 `repo-tests.json`、`instance-tests.json`。已知依赖兼容性限制在 [agentbench_environment.py](docker/official-harness/agentbench_environment.py) 中按基线版本声明，进入镜像身份与来源记录；它们不是上游自带的 lockfile。官方测试与基线本身不兼容时停止诊断，不擅自修改测试或标准答案。

旧实验保留原评分镜像和准备规则，不在一组配对中途升级。修复后的评分工具可在独立输出目录中重评已有补丁，不覆盖原成绩。离线迁移也必须携带这些准备好的评分环境镜像。

安装脚本创建 `/var/lib/ctxbench`，Compose 按相同路径绑定挂载，确保子容器通过宿主 Docker 正确访问工作区。更改 WSL 内数据位置可设置绝对路径 `CTXBENCH_HOST_DATA_DIR`；这不等于迁移 Windows 上的 WSL 虚拟磁盘。

Worker 仅监听 `127.0.0.1:48173`。它是拥有 Docker-host 权限的可信单用户本地服务，**不是公网或多租户服务**，不要公开端口。

迁往公司内网时，需要准备应用镜像、所有任务实例/评分环境镜像、仓库与数据，并适配内部 Agent、Provider 和 API 域名白名单。仅导出应用镜像不足以离线运行完整 benchmark。首版支持 API Key，不包含交互式网页登录或 SSO。扩展契约见 [Agent 适配说明](docs/agent-adapters.md)。

历史约束材料可通过 `POST /v1/constraints/review-archive` 采集，指定 GitHub `owner/name`、截止时间及分页 / PR / 评论上限。只保留截止日期前已合并 PR 的符合时间条件的评审，存入评测专用内容寻址归档。公开仓库可不配置 `GITHUB_TOKEN`，但会受匿名配额限制；密钥不会写入归档。

## Agent 启动参数

在「新建实验 → 运行环境与预算」中配置 **Agent 启动参数**；独立生成知识库、挖掘约束的窗口也有相同入口。支持添加、删除和调整顺序，每行是一个独立参数，例如 `--tools` 与 `read,bash` 分别填两行。含空格的值保留为一个参数，不加 Shell 引号，不展开 `$变量`，也不会执行命令。需要先安装依赖时，仍使用编排中的「容器启动命令」。

参数随实验冻结，作用于各 Agent 阶段和 Prompt 步骤；两组对照及每次重复保持一致，不传给隐藏测试评分容器。修改参数会改变知识库生成、约束挖掘的缓存标识。内置 Pi 允许工具选择等参数，Provider/模型、RPC、会话和提示词仍由评测工具管理；不要把密钥放在参数中，请使用环境变量。

已有安装需要更新 Worker 并重建或导入新版 Agent 镜像，旧镜像会明确提示不支持启动参数。自定义内网 Agent 的协议、Pi 支持列表与升级命令见 [Agent 适配说明](docs/agent-adapters.md#optional-startup-arguments-protocol-v1)。

## 构建与测试

```powershell
npm ci
python -m pip install -r worker/requirements-dev.txt
npm test
npm run worker:test
npm run build
cargo test --manifest-path src-tauri/Cargo.toml
npm run tauri build
```

桌面开发需要 Microsoft C++ Build Tools 的桌面 C++ 工作负载、WebView2 和 Rust MSVC 工具链。应用会诊断 WSL / Docker，但不会静默安装或重启系统。

安装包输出到 `src-tauri/target/release/bundle/nsis/`；打包资源排除 `.env`、数据集、密钥、运行结果和缓存。

- `scripts/container-smoke.py`：真实 Docker + mock Provider 的基础设施流程验证，不是模型质量分数。
- `scripts/container-resilience.py`：隔离 Worker 的崩溃、重启和取消回归，不重启生产 Worker。
- `scripts/regrade-acceptance.py`：对保留的真实补丁重新评分，不重新调用 Provider。
- `scripts/scale-smoke.py`：合成 638 任务 / 2,552 运行的数据库容量测试，不代表已完成全量真实评测。

容器测试需要 WSL 内的 Docker；不可用时应明确报告跳过。已验证范围、历史验收证据及尚未完成的发行签名、自动更新、全新 Windows 安装验收等边界，见[项目重新评估](docs/reassessment.md)和[评测方法](docs/evaluation.md)。不能用少量 smoke 用例通过代替全量验收。

## 目录结构

- `src/`：React 桌面界面与可测试的实验领域模块。
- `src-tauri/`：Tauri 控制层、WSL / Worker 诊断。
- `worker/`：持久化编排、mock / Docker 运行适配。
- `docker/agent-pi/`：固定版本 Pi 镜像和 RPC 适配器。
- `docker/official-harness/`：官方评分适配与容器隔离策略。
- `skills/ctxbench-generate-context/`：隔离的知识库生成 Skill。
- `schemas/`：自定义任务、知识库和 Agent 的交换契约。
- `docs/`：架构、评测方法及验收记录。

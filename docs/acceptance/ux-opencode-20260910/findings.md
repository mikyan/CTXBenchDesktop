# CTXBench Desktop 普通用户黑盒验收记录

日期：2026-09-10 至 2026-09-11（Asia/Hong_Kong）

## 当前状态

验收主链路通过（2026-09-11）：本人在指定 debug 原生桌面完成真实 OpenCode 镜像制作、用例录入、MiMo 配对实验。最终实验 `ux-opencode-20260910-mimo-retest2` 完成 2/2，本人逐组读取独立评分日志，均为 9/9 通过；两份原生导出记录均为 `mock: false`、评分退出码 0、证据校验通过。编码阶段日志可见真实 OpenCode 工具事件、`mimo-v2.5` 模型标识和最终修复消息。

最终 HOME 修复镜像已打包进 ZIP、保存至本人资料目录，整包及 5/5 负载校验通过，原生 UI 导入前检查通过。UX-009/010 修复后原生复测通过，没有重跑模型。未执行第二台机器上的实际导入或离线运行，故结论是“可打包携带、通过导入前校验”，不是“跨机器复用已实测”。

下文“等待安装确认”“待运行”等制作进度是首次探索历史，不代表当前状态。生产服务始终未操作；未读取产品源码、产品测试脚本、内部实现、数据库或内部接口。所有产品操作使用真实 Windows 原生窗口，没有浏览器替代验收。

### 最终证据索引

所有下列素材均在 `D:\Code\CTXBenchAuto\artifacts\ux-opencode-20260910\` 内。

| 验收项 | 本人观察与结果 | 证据 |
| --- | --- | --- |
| 真实镜像制作 | 软件基础镜像 → npm 安装 OpenCode 1.18.30 → HOME 权限修复新镜像；旧标签未修改 | `provider/build-result.json`、`provider/build-homefix.json`、`evidence/ux008-homefix-build-native.jpg` |
| 可判定的失败基线 | 自创库存 HTTP 后端；独立 9 项中 4 项失败，基线未修复且工作树仍干净 | `case/baseline.json`、`case/evaluator/acceptance.mjs` |
| 真实模型及独立评分 | MiMo 中国 Token Plan / mimo-v2.5；none、manual 都独立 9/9；非 mock | `evidence/retest2-none-run.json`、`evidence/retest2-manual-run.json`、`evidence/retest2-none-opencode-final-native.jpg`、`evidence/retest2-manual-nine-pass-native.jpg` |
| 配对条件 | 两份导出记录的 commit、promptHash、pairingHash、agentImageDigest 全部相等 | 上述两份原生导出 JSON |
| 镜像可打包携带 | 新镜像、精确基线、单用例及同一冻结知识包；整包 SHA 与 UI 一致，5/5 负载哈希和大小匹配 | `provider/ux-opencode-20260910-resource-homefix.zip`、`provider/export-homefix.json` |
| UI 导入前检查 | 1 镜像、1 基线、1 冻结知识包；校验完成，未实际导入 | `evidence/homefix-resource-export-native.jpg`、`evidence/homefix-resource-verify-native.jpg` |

### UX 最终复测范围

| 编号 | 严重度 | 本人最终状态 |
| --- | --- | --- |
| UX-001 | S3 | 应用内中英文帮助主路径通过 |
| UX-002 | S2 | 本地基础镜像列表、工具说明、刷新通过 |
| UX-003 | S3 | 隐藏补丁位置状态文字通过；镜像文件位置、原生取消保留草稿未完成复测 |
| UX-004 | S3 | 下一步回到步骤顶部通过 |
| UX-005 | S3 | 匹配规则、刷新、导入引导与已有匹配包通过；空列表分支未重建 |
| UX-006 | S3 | 最终计划显示实际用例镜像通过 |
| UX-007 | S1 | 固定 Git 基线获取与资源导出通过 |
| UX-008 | S2 | HOME 修复新镜像构建及真实模型/评分运行通过 |
| UX-009 | S2 | 原生运行详情日志、阶段切换、从头阅读与返回尾部通过 |
| UX-010 | S3 | 多行证据区域及内部滚动至评分汇总通过 |

上述结论只覆盖一个小型用例与一对运行，不证明知识库改善效果、长期稳定性或所有入口无缺陷。隔离实例明确禁用的正式服务控制、应用运行环境镜像安装没有测试；没有读取或展示 API 密钥。

## 范围与验收目标

仅以普通用户方式操作真实 UI、阅读 UI 帮助和公开用户文档；自行创建的仓库与素材位于 `D:\Code\CTXBenchAuto\artifacts\ux-opencode-20260910\`。不修改产品代码、已有数据、已有镜像标签或现有容器，不上传内容。

计划建立一个小型库存预留后端用例，验证正常预留、库存不足、非法数量、重复请求等真实行为。最终用例范围依软件用户入口和公开文档确定。

完成验收需要分别保留以下证据（详细执行与复测按时间追加在下文）：

- 基于软件提供的镜像制作自己的镜像，并安装真实 OpenCode。
- 经软件运行 OpenCode，使用用户授权的 MiMo 中国区 Token Plan API、模型 `mimo-v2.5`；密钥仅由协调者安全注入运行时。
- 自创仓库完成代码任务，并由独立测试执行获得真实通过结果；不使用 mock Agent。
- 自制镜像能够导出打包，并验证可复用。
- 如果探索有无知识库比较，配对仅改变冻结的上下文文件，其他条件保持相同；独立评分测试不得泄露给编码 Agent。

## 工具准备证据（不计为产品 UX 发现）

- 已完整阅读 computer-use 的 SKILL.md、guidance.md、api.md、confirmations.md。
- `@oai/sky` 在持久 JavaScript 会话初始化成功，原生应用枚举成功。
- 枚举结果存在 `CTXBench Desktop`（`io.ctxbench.desktop`），当时无打开窗口；未主动启动。
- 浏览器工具可枚举 Edge 与 Codex 内置浏览器。优先使用原生 Windows UI；若后续使用浏览器替代，将明确列出未测的原生能力。
- 当前工具未提供 `send_input`；使用可用的任务消息通道联系修复 agent James（`01a08936-15b3-7b30-971f-510320977ecc`）和协调者（`01a06b47-944f-76f3-8380-74bb83cda689`）。
- 本阶段证据为工具初始化和应用枚举结果；没有产品截图或模型日志，也没有接触密钥。

## 协调者已知设施事项

协调者说明：native 开发实例端口固定，暂时无法独立运行，已交修复 agent 处理。此事项来自协调者，未经本验收 agent 自行复现，不计入首次用户体验发现。

## 问题记录约定

首次自行发现的问题从 `UX-001` 起编号，记录：阶段（首次探索/修复后复测）、期望、实际看到的内容、实际操作、报错、严重度、脱敏截图或日志证据、对后续操作的影响、反馈对象和复测结果。仅记录实际观察，不将推测写成事实。

已核验唯一指定 debug 原生窗口，UI 显示“隔离验收实例 — 不是你的正式工作区”和 `http://127.0.0.1:48174/v1`。首次探索使用原生 Windows UI，浏览器仅阅读“帮助”打开的公开文档。

### UX-001：中文帮助入口落到英文仓库首页

- 阶段：首次探索；严重度：S3（轻微、非阻断）。
- 期望：点击中文 UI 的“帮助”，直接看到中文用户入门或可扫描的帮助目录。
- 操作：概览右上角“帮助” → 检查新打开的 Edge 标签 → 在 README 定位“Remote images, guided image recipes and custom coding commands” → 打开中文 `docs/image-workshop.md` 用户指南。
- 实际：先进入 `https://github.com/mikyan/CTXBenchDesktop` 的英文 README，混合用户、开发和架构说明，需额外定位到与目标相关的中文指南。无报错，已自行恢复。
- 脱敏证据：原生 AX 为“链接 帮助”；新 Edge 标签标题 `mikyan/CTXBenchDesktop`；后续文档标题“使用公司镜像和自己的 Agent”。没有打开实现文件、开发脚本或内部接口。
- 反馈：已发 James 并抄送协调者。James 已确认拟改应用内随语言切换的用户帮助；待修复后复测。

修复后复测（中文原生界面）：再次点击右上角“帮助”，确实在应用内打开“使用帮助·从一个用例开始”，可直接看到准备镜像、创建用例、运行实验三个步骤，以及概念和凭据/日志说明的展开入口。没有再次跳往 GitHub。

修复后复测（英文原生界面）：点击 EN 后再打开帮助，应用内弹窗标题为“User guide · start with one case”，三个步骤及说明均随语言切换。中文和英文帮助主路径均通过。关闭弹窗后原有构建配方仍在，未触发构建。

### UX-002：制作向导缺少本地基础镜像列表

- 阶段：首次探索；严重度：S2（中等、可绕行）。
- 期望：在“1. 选择基础镜像”中直接选择软件已经提供的本地镜像，并知道基本语言工具条件。
- 操作：“设置 → 镜像适配 → 一步步制作自己的镜像”，点击“本地基础镜像”；再绕到“应用镜像 → 打包自定义 Docker 镜像”展开 Pi Agent 镜像建议。
- 实际：制作页只有普通文本框及公司地址占位示例，无本地选择建议；打包区的组合框中才找到 `ctxbench/agent-pi:0.1.0`。已自行发现标签并回填制作向导。无产品报错。
- 脱敏证据：制作页 AX 为“编辑 本地基础镜像 Description: registry.company.example/team/backend:1.0”；打包页 AX 为“组合框 Pi Agent 镜像”，原生截图可见下拉建议 `ctxbench/agent-pi:0.1.0`。
- 反馈：已发 James 并抄送协调者。James 拟在制作第一步增加本地列表与基础工具说明；待复测。
- 尚未构建、拉取、修改已有标签或执行导出。

修复后复测（中文原生界面）：第一步现有“选择已安装的基础镜像”组合框及“刷新本地镜像”按钮。展开列表可直接看到 `ctxbench/agent-pi:0.1.0`，不用再绕到打包页；显示当前 WSL 发行版 Ubuntu，以及 Pi 基础镜像自带 Node.js/npm、Python 3、Git、Shell 的说明，并提示已安装不代表兼容验证。点击刷新时显示“正在读取本地镜像...”，随后恢复原标签。未改变镜像选择、未下载或构建。列表可发现性和刷新主路径通过。

工具备注（非产品问题）：原生工具一次 UIA set_value 报 CacheRequest 错误，未写入内容，已核查为空并改用普通键盘输入；一次窗口捕获报 `no monitor found for window`，重新枚举和绑定同一窗口后恢复。没有将工具失败当成产品 UX 发现。

### UX-003：配置已加载但文件控件仍显示未选择

- 阶段：首次探索；严重度：S3（轻微、非阻断）。
- 期望：导入文件后，已加载状态与文件控件文字一致。
- 操作：镜像向导第3步选择自己的 `provider/opencode.json`；原生文件对话框输入绝对路径并确认；进入第4步，将方案填入最终表单。
- 实际：“未选择文件”仍显示在文件控件旁边，下方同时显示 `opencode.json → /opt/company/opencode.json`；最终表单也显示“未选择文件”，却已有 `opencode.json` 的构建上下文路径。无错误提示。根据映射及 COPY 预览继续，没有重复导入。
- 脱敏证据：原生截图及 AX 的“上传非敏感配置文件: 未选择文件”与文件映射文本同时存在。
- 反馈：已发 James 并抄送协调者，请其待配方提交后再热更新相关表单。待复测。

补充首次出现位置（2026-09-11）：创建用例“隐藏测试与参考修复”中，通过原生文件对话框选择本人 hidden-tests.patch，隐藏补丁 textarea 已实际显示正确 Git diff，但上传控件仍显示“未选择文件”。此处尚未因镜像页修复而改变，已反馈同一问题的范围扩展。

### 当前制作进度

UX-003修复后原生复测（隐藏补丁位置）：打开已保存用例，第2步展开评分专用隐藏补丁区。已有Git diff仍可见，导入入口已改为“上传隐藏测试补丁”，并明确显示“编辑框已有补丁内容，可能来自导入或手动编辑；保存时以当前文字为准”，不再显示“未选择文件”。状态文字主路径通过。随后打开原生文件对话框并用工具向主窗口发送Escape，文件对话框和编辑模态同时关闭，因此该次取消行为不能据以确认草稿保留；没有改字段或保存，既有v1用例仍在。原生镜像导入位置与点击取消按钮的复测仍待完成。

### UX-004：下一步沿用旧滚动位置，任务字段不在视野内

- 阶段：首次探索，2026-09-11；严重度：S3（非阻断）。
- 期望：从“仓库与环境”点击底部“下一页”后，新步骤从顶部展示任务 ID 和 Agent 提示词。
- 操作：完成第1步仓库、固定基线和测试镜像后，下滚点击“下一页”。
- 实际：第2步仍在旧滚动位置，屏幕直接显示编码启动方式和评分命令、底部下一页；任务 ID 和提示词在视野上方。无报错。通过手动上滚可恢复。
- 证据：原生截图第2步首屏顶部已是“使用实验中配置的 Agent”，AX 同时列出不可见的任务 ID 和任务提示词字段。
- 已反馈 James 并抄送协调者，要求待用例保存后再热更新；复测待定。

### 用例录入进度

UX-004修复后原生复测：打开自己的用例编辑页，不更改任何字段；在第1步滚到最底部，点击“下一页”。第2步立即显示“任务与测试”标题、任务ID和完整提示词，未再停在旧底部，主路径通过。证据 `evidence/ux004-retest-step-top-native.jpg`；没有保存新用例版本。

### UX-005：空的冻结知识库下拉缺少后续引导

- 阶段：首次探索，2026-09-11；严重度：S3（非阻断）。
- 期望：新实验的冻结知识库选项没有匹配资源时，说明原因并提供创建或导入路径。
- 操作：用例卡片新建实验 → 上下文对比 → 已冻结知识库 → 打开任务对应下拉。
- 实际：只有“选择匹配的知识库包”占位项，没有空状态或导入链接。本人关闭刚填写名称但尚未提交的临时实验，去主导航“知识库 → 导入知识包”自行恢复。未删除任何已保存实验或用例。
- 已反馈 James 并抄送协调者；待修复复测。

### UX-006：实验确认页只显示默认镜像，未显示用例覆盖

- 阶段：首次探索，2026-09-11；严重度：S3（非阻断、确认歧义）。
- 期望：最终计划明确实际代码 Agent 镜像，或列出每个用例的覆盖关系。
- 操作：从自创用例新建实验，选择人工冻结知识库，进入模型与执行、检查并创建。
- 实际：第1步明示用例覆盖为 `ctxbench/adapted:91d5e4cf0966445991274e1a098328e9`，最终摘要却只显示 `Agent 镜像: ctxbench/agent-pi:0.1.0`，容易担心误跑默认 Pi。无错误提示。继续点击运行规模预检检查可见信息。
- 证据：原生确认页截图和 AX 同时显示实验名 `ux-opencode-20260910-mimo-first-real`、模型 `xiaomi-token-plan-cn / mimo-v2.5`、默认 Pi 镜像。已发 James 并抄送协调者；修复须等实验提交安全点。

实验设置探索：选择同一任务与基线、人工包 `645a49662b7ae77b`、重复1、seed42，共2次运行；不挖掘历史约束、不额外评审，不自动生成知识库。按页面高级模式说明使用已备好依赖的自定义镜像，取消额外项目依赖准备。仅允许传入 `XIAOMI_TOKEN_PLAN_CN_API_KEY` 变量名；没有读取密钥。默认 CPU4/内存8GiB/API-only 网络保留，将每次超时从45分钟缩短为5分钟。页面明确自定义命令的 Token 用量未知，累计预算不能硬限制该命令，不能将显示为0理解为免费。

### UX-007：Windows挂载仓库在获取Git基线时被所有权检查阻断

- 阶段：首次真实实验，2026-09-11；严重度：S1（当前主目标阻断）。
- 期望：已通过保存/规模预检的本地Git用例能够从固定基线启动Agent。
- 操作：原生UI预检显示2次求解、0次知识库生成/约束挖掘/评审后，点击一次“创建并准备”。
- 实际：`ux-opencode-20260910-mimo-first-real` 卡片立即显示失败，2/2运行结束。失败步骤“获取指定 Git 基线版本”，明示“本次尝试未记录到 Agent 容器启动”。错误为 `RuntimeError: fatal: detected dubious ownership in repository at '/mnt/d/Code/CTXBenchAuto/artifacts/ux-opencode-20260910/case/repo/.git'`，随后 `Could not read from remote repository`。UI建议全局safe.directory例外及检查WSL目录所属用户/UID10001/可写性。
- 证据：原生实验卡片及其AX失败详情；未调用模型的界面证据只证明未记录Agent启动，不将失败计为独立测试结果。
- 已发James并抄送协调者，提供长表单结束的HMR安全点。本人未修改全局Git信任、权限、服务或产品实现；继续探索镜像导出，修复后从UI重试。

UX-007范围补充：原生资源迁移导出 `op-0c9ee27f18cc4970` 同样在“获取指定Git基线版本”失败，错误路径与dubious ownership相同。已通过UI新建 `ux-opencode-20260910-portable-reservation`（只引用自己的1个用例），导出仅附加本人的adapted镜像及中性知识包；尚未得到ZIP。UI下拉展开后也出现了原单用例名称，说明“自定义评测集”标题并不直观表达全部可选资源。未再次提交失败导出。

UX-007原生失败截图：`artifacts/ux-opencode-20260910/evidence/ux007-baseline-ownership-native.jpg`。

修复后复测进度：协调者通知仅48174隔离服务已加载修复且健康后，本人经UI新建 `ux-opencode-20260910-mimo-retest1`，原首次失败实验保留。保持用例v1、原基线/提示/测试/镜像/知识包/资源/API-only/5分钟/重复1/seed42不变。提交后显示准备中0/2，不能提前宣称模型或评分成功。

UX-006修复后原生复测通过：最终计划已区分“实验默认 Agent 镜像”和“各任务实际使用的代码 Agent 镜像”，后者准确显示自己的adapted镜像，并说明用例自定义命令保留自身模型配置。证据 `evidence/ux006-retest-actual-image-native.jpg`。

UX-005修复后原生部分复测：已可见仓库/完整基线匹配规则、刷新知识库包、在当前实验上方导入且保留草稿的说明及按钮；自己的匹配包仍可选择。未为复测删除现有包或伪造不匹配基线，因此空列表分支尚未亲测。

### 人工知识库准备

### UX-008：镜像构建成功后 OpenCode 的 HOME 日志文件不可写

- 阶段：首次到达真实 OpenCode 启动，2026-09-11；严重度：S2（当前模型链路阻断，具体归因待确认）。
- 期望：向导已为 HOME `/home/ctxbench` 生成 UID10001 的目录权限步骤，完成安装及版本检查的镜像应可在评测用户下启动。
- 操作：保持原镜像和用例，通过原生 UI 提交 `ux-opencode-20260910-mimo-retest1`；从实时日志下拉选择“编码 Agent · 16:07:50”。
- 实际：取回固定基线、建立干净 checkout 成功，Agent 容器已启动；退出码1，`PermissionDenied: FileSystem.open (/home/ctxbench/.local/share/opencode/log/opencode.log)`。未见真实模型响应或评分，不能认定 Token 调用成功。
- 证据：`evidence/ux008-opencode-home-permission-native.jpg`，run `solve-30a7444066154ba8ab25`。原 failed 实验保留。
- 已发 James 并抄送协调者。没有修改宿主权限、全局 Git 或运行服务；继续独立导出入口。UX-007 的运行端 Git 获取/checkout 复测通过，导出端待复测。

### 人工知识库准备（原记录）

### UX-007 导出端原生复测通过

保持原集合、原镜像、原中性知识包，重新经资源迁移表单提交 `op-e8827c4723664a34`。界面显示精确基线打包、保存镜像1/1后“已完成”，ZIP路径 `/tmp/ctxbench-ux-opencode-20260910-N8UHwU/intranet/transfers/ctxbench-resources-op-e8827c4723664a34-1a2b7104.zip`，SHA256 `b88f2a220362ae55de2e1b57fd47641ebbded9e0fbe35ec6863c51f5ab40e079`。截图 `evidence/ux007-retest-export-complete-native.jpg`。按页面提供的Windows映射路径复制本人ZIP到 `provider/ux-opencode-20260910-resource-before-homefix.zip` 以保留证据；它包含尚有HOME权限问题的原镜像，打包成功不等于模型链路通过。没有上传任何内容，也没有改动已有标签。

### 早期准备流水

UX-008修复后本人原生操作：阅读新向导“工具已安装可留空安装命令”“安装后默认HOME权限收尾与UID10001检查”，创建 `ux-opencode-20260910-mimo-homefix`。以原own镜像为基础，安装命令留空、不加文件、保留默认HOME/LANG、离线构建。`op-2ff9ab040e4f4ba1` 已完成，新tag `ctxbench/adapted:26b31b1f25d24dee8679f5508cf4a305`，ID `sha256:5908f6a2f0c243c6f7d54d95111b84fba99fbd36de2643c621be53a2aad4e625`；未重复下载OpenCode、未改旧标签、未改宿主权限。运行端复测仍待完成。

旧ZIP完整性复核：本人本地SHA与UI一致，6条目；manifest列出的5个负载校验和全部吻合。另经原生“验证校验和、依赖与冲突”，`op-36d5db6faad64b76` 已完成，显示1镜像、1基线、1知识包；未勾信任/点击导入，不覆盖原数据。

UX-008运行复测推进：本人经原生编辑将自己的用例保存为v2，仅更换编码/评分镜像为HOME修复后的新镜像；没有变更提示、基线、测试或命令。2026-09-11 16:41左右通过新建实验表单提交 `ux-opencode-20260910-mimo-retest2`。预检明确2次求解、0次知识库生成/挖掘/评审，重复1、seed42、相同人工冻结知识包，CPU4/8GiB/API-only/5分钟，直接使用已准备的镜像，仅允许MiMo变量名。卡片显示运行中并明确用例v2；实时日志已有真实OpenCode `step_start` 事件，尚不能单独证明Provider成功或评分通过。

### UX-009：已完成运行的详情实时日志持续断连

- 阶段：首次结果详情探索，2026-09-11；S2（证据入口故障，有替代入口）。
- 期望：实验完成后可在对应分支详情看到编码和评分容器记录。
- 操作：retest2完成后从结果表点击无上下文“详情”，打开阶段下拉，点击“立即刷新日志”。
- 实际：持续显示“日志连接中断，正在自动重连”，下拉只有“自动定位最近失败或当前执行”；从头查看/导出当前窗口日志禁用。稍后重新观察及立即刷新仍相同。
- 替代入口：下方“证据文件”可选择 `grading/evaluator.log`，成功显示真实TAP E01-E09全部ok，tests9/pass9/fail0/cancelled0/skipped0，耗时458.787944ms。因此不是将断连误认为评分失败。
- 已发James并抄送协调者。仍需模型调用轨迹、另一组评分及新ZIP完整性确认，不能仅凭结果表宣布全部验收完成。

retest2结果表已显示人工提供/无上下文两组均已完成且测试通过，截图 `evidence/retest2-two-arms-pass-native.jpg`。新镜像资源包由本人经UI单用例导出提交 `op-b34f7dc7536a4d35`，附加新HOMEfix镜像、同一冻结知识包；看到排队中，未重复提交。

### UX-010：已保存证据正文只有一行高度

- 阶段：首次结果证据探索；S3（阅读困难，AX或导出可替代）。
- 操作：无上下文详情下拉选择 `grading/evaluator.log`，滚动到证据区域。
- 期望：能看到多行TAP并滚动阅读完整评分；实际：正文约29px高，只露出 `TAP version 13` 一行和极小滚动条，周围有大量空白。AX可读到完整9/9输出，但普通视觉阅读非常困难。
- 证据：`evidence/ux010-one-line-evidence-native.jpg`；已发James并抄送协调者。此问题不改写真实评分结果，不要求扩大修复范围。
- 原生“导出运行记录”另存为已成功：`evidence/retest2-none-run.json`，仅本人的单次运行，没有使用“导出全部结果”。

### 原始准备流水（保留）

依据原生导入界面提供的“相对路径与文件内容映射”格式，自制 `case/knowledge-baseline.json`。只含 `docs/backend-overview.md`，介绍基线仓库 Node.js/ESM、文件组织、HTTP入口和已有开发测试命令，不含任务提示、隐藏测试、预期修复或答案。通过 UI 绑定同一基线导入；界面显示人工提供、仅代码树、1文件768B。冻结 key 为 `645a49662b7ae77b6d4afca15d38df15d2b4eab8fa82a6fa8ca80a51eb692712`，文件 SHA256 为 `964cd3386b080baafc84920d5989e8b0caa84927456fadbd0b471c20f27b8cbd`，收据已存 `case/knowledge-receipt.json`。不是独立盲法自动生成知识库；仅计划重复1次、两臂链路验收，不作知识库有效性结论。

已通过创建评测用例原生表单填写用例名称 `ux-opencode-20260910-reservation-idempotency`、自己的 Worker Linux 仓库路径、完整基线及新建镜像。第2步“如何编写并加入测试用例？”明确提供隐藏测试 Git 补丁方案。依该 UI 指引在自己的 `case/evaluator-workspace` 独立克隆基线，只新增自己的 evaluator 文件，用 intent-to-add 生成 `case/evaluator/hidden-tests.patch`。新增文件 SHA256 与原独立测试完全相同；对 Agent 原始基线执行 `git apply --check` 通过，未实际应用到基线，也未提供实现修复。

用例随后已真实保存，列表显示共 1 条并出现上述名称。任务 ID `ux-opencode-20260910-reservation`，评分命令 `node evaluator/acceptance.mjs /workspace`，OpenCode 命令来自本人 `provider/agent-command.txt`；隐藏测试通过原生文件选择器载入评分专用字段，参考修复保持空白。未执行要求参考修复的用例自检，也未启动模型实验。已通知 James 可进行 UX-004 安全热更新。

已通过原生向导完成 `ux-opencode-20260910-mimo` 配方：基础镜像 `ctxbench/agent-pi:0.1.0`，从 npm 官方源固定安装 `opencode-ai@1.18.30` 并检查版本，导入无密钥配置到 `/opt/company/opencode.json`。最终构建表单已检查，尚未勾信任框或点击构建。已向协调者请求此次安装的动作时确认。依据 computer-use 的 Windows 安装确认规则，属于工具规定，不算产品问题。

协调者已告知确认问题已发给真实用户，尚未收到答复；继续保持信任框未选、构建未点击。等待期间只进行不修改配方的帮助复测。

2026-09-11 恢复：协调者明确转达真实用户“继续啊”为本次具体构建动作的同意。重新核验 debug 原生窗口与 `48174/v1` 隔离标记，原方案名称、基础镜像、npm 固定版本、非敏感文件和网络设置仍完整一致。勾选信任并仅点击一次构建。UI 已受理 `op-13d9c7bf9a4646ed`，显示“运行中”“任务在本机评测队列中运行，离开此页面不会停止”，日志开始 Docker Step 1/9 至 Step 3/9；基础固定为 `sha256:74459c940cff8120a90edad0988c1d39dc1fbd283b065d62452939ce4d12478e`。已通知 James 表单到达可热更新安全点。尚不能据此宣称镜像或评测成功。

## 自创用例准备（产品探索前）

### 真实镜像制作结果（2026-09-11）

原生 UI 构建操作 `op-13d9c7bf9a4646ed` 最终显示“已完成”，生成 `ctxbench/adapted:91d5e4cf0966445991274e1a098328e9`，镜像 ID `sha256:0c17af7f94de29ce92b6a0adc8b9507ebe7e917f1f9e1f5888876fa2280f48fa`，并说明“原有镜像未变”“未消耗模型 Token”。Docker 日志真实输出 Node v22.22.0、npm 10.9.4、Python 3.11.2、Git 2.39.5，官方 npm 安装 added 3 packages in 8s，`opencode --version` 为 1.18.30，最后 Successfully built。脱敏结果保存在 `provider/build-result.json`。这是镜像制作成功证据，尚非真实模型或独立评分通过证据。

- 仓库：`artifacts/ux-opencode-20260910/case/repo/`；无第三方依赖的 Node.js 库存预留 HTTP 服务。
- 固定基线：`d82fe7a849b150a9149918cc68430aaca5d40d9d`，创建后工作树干净。没有修复分支或参考答案放入该仓库。
- 基线已实际执行：公开开发测试 4 项，3 通过、1 失败；仓库外独立验收测试 9 项，5 通过、4 失败，二者退出码均为 1。
- 独立测试从仓库外启动真实后端子进程，用本机随机端口发 HTTP 请求，不导入后端内部模块；每项测试独立启动并仅终止自己的进程。不传递宿主凭据。
- 失败事实：重试预留 2 件时返回 201 而非 200，余量为 1 而非 3；耗尽库存后的重试返回 409；并发重试重复创建；错误扣减使后续不同 ID 的合法预留失败。
- 失败测试为本人自创业务用例的预期基线，不属于 CTXBench UX 问题。独立评价脚本保持 evaluator-only，不交给编码 Agent。
- 任务、测试和配置 SHA256 见 `artifacts/ux-opencode-20260910/case/baseline.json`。
- 官方文档确认 OpenCode npm 安装包、MiMo 中国 Token Plan OpenAI 兼容配置、环境变量替换。配置仅启用 `mimo/mimo-v2.5`，使用协调者提供的 `XIAOMI_TOKEN_PLAN_CN_API_KEY` 变量名；未获取变量值。文档来源与方案见 `artifacts/ux-opencode-20260910/provider/plan.md`。

## 最终运行与闭环（2026-09-11）

### UX-008 运行端复测通过：真实 OpenCode / MiMo，不是 mock

最终实验 `ux-opencode-20260910-mimo-retest2`（`exp-ec7368d4195c`）已完成 2/2。原生结果表两组均显示测试通过，随后本人逐组读取独立 TAP，并用“导出运行记录”分别保存 JSON；没有导出整个工作区。

| 分支 | solverRunId | 独立评分 | TAP 耗时 | Agent 耗时（导出记录） |
| --- | --- | --- | --- | --- |
| none | `solve-8261622da0f1414f885a` | 9/9，fail/cancelled/skipped/todo 均 0 | 458.787944 ms | 150.0535101139685 秒 |
| manual | `solve-df51c4e9108c4fa0a3bc` | 9/9，fail/cancelled/skipped/todo 均 0 | 461.269954 ms | 137.00646401790436 秒 |

两份记录均为 `status: completed`、`testsPassed: true`、`mock: false`、`evidenceIntegrity: verified`、`grade.exitCode: 0`、`grade.resolved: true`。评分器镜像摘要与本人的 HOME 修复镜像一致。共同冻结标识如下：

- commit：`d82fe7a849b150a9149918cc68430aaca5d40d9d`
- promptHash：`206125f7fc2efe0d02e2fd7c869fc84ed3da2c4c2a89d73cbd3634c75d540404`
- pairingHash：`cb093d64baca52888bc38f873c94e55eb9001afad98a647f6c52caad059b9a10`
- agentImageDigest：`sha256:5908f6a2f0c243c6f7d54d95111b84fba99fbd36de2643c621be53a2aad4e625`

日志入口恢复后，本人在 none 的“编码 Agent”阶段看见 OpenCode JSON 事件：主会话 `ses_f705cc983ffeN72W6gsq2KM0QD`，`task` 工具完成、模型元数据 `{modelID: mimo-v2.5, providerID: mimo}`，读取本人 `/workspace/src/app.mjs`，以及最终完成消息。最终消息说明在冲突检测后添加 `if (existing) return [200, existing];`，补充4个开发测试，并报告8个开发测试通过。这8个是 Agent 的开发测试，不与后续独立9项评分混为一谈。

模型事件含非零 token 计数；事件中的 `cost: 0` 不能当作免费或实际账单。本人没有读取 Provider 网络请求、密钥值或账单；真实调用的验收依据是本人官方配置、真实 OpenCode 安装/启动、MiMo 模型工具事件及后续独立评分。没有用 mock 脚本生成回答或测试结果。

独立 E01–E09 分别覆盖正常预留、重复请求响应与库存、耗尽后重试、并发重复投递、后续不同请求ID库存、冲突ID不变更两种SKU、非法输入、不存在SKU与库存不足、非法JSON与未知路由。与事前的5通过/4失败基线形成区分。收尾时仅对本人仓库执行 `git status --short`（空输出）和 `rev-parse HEAD`，基线仍固定，未把 Agent 修复或评分补丁写回基线仓库。

### UX-009 修复后原生复测通过

协调者通知48174隔离服务恢复后，本人原none详情不再持续断连，显示“日志流已结束 · 退出码: 0”。阶段下拉出现项目测试、编码Agent、校验并启动Agent容器、准备并执行评测用例。选择编码Agent可见真实JSON输出，点击“从头查看完整日志”进入字节位置0的分页模式，再返回实时尾部可见最终完成消息。打开manual详情也自动加载独立评分日志。

证据：`evidence/ux009-retest-native-log.jpg`、`evidence/retest2-none-opencode-final-native.jpg`。已反馈James并抄送协调者。只读取已有运行，未重跑模型；未验证大于一页的超长日志分页或“导出当前窗口日志”文件内容，不能扩张该复测范围。

### UX-010 修复后原生复测通过

本人在manual详情选择 `grading/evaluator.log`。正文现在有约360px高的独立多行阅读区，可同时看见E01–E03及各自状态；鼠标滚动后看见E04–E06，拖动内部滚动条至末尾，可直接看见E09及 `tests 9 / pass 9 / fail 0` 汇总。不再只有约29px的一行。

证据：`evidence/ux010-retest-multiline-native.jpg`、`evidence/ux010-retest-scroll-bottom-native.jpg`。已反馈James并抄送协调者；没有改变评分或运行记录。

### 最终新镜像打包及导入前校验通过

本人回到“设置 → 资源迁移 → 最近的适配／自检／迁移操作”，打开先前提交的 `op-b34f7dc7536a4d35`。页面明确显示资源包导出已完成，文件 `ctxbench-resources-op-b34f7dc7536a4d35-95104fba.zip`，SHA-256 `c31168eb9bfe600ef0dda1d8ba19f7c18e0ff4ce0c2e8cd03a00c05379fccad9`。

依据页面显示的 Windows WSL 映射目录，将这一个自有 ZIP 复制到 `provider/ux-opencode-20260910-resource-homefix.zip`（587227148字节），目标原先不存在，没有覆盖旧包。只读取本人的导出包：manifest列出单用例、固定基线、新镜像5908…、同一冻结知识包；共6条目，其中5个负载的哈希与长度全部匹配。导出的用例定义含新镜像及OpenCode命令、本人独立测试，未含旧镜像引用。清单标明 `agentCredentialsIncluded: false`；这不是对任意镜像层安全性的万能保证。

随后在原生“检查并导入资源 ZIP”填入刚看到的文件名，点击一次“验证校验和、依赖与冲突”。`op-a4f9fb87fc1e4e7c` 已完成，界面确认对应自有用例、1镜像、1基线、1冻结知识库，SHA与本地一致，预计需2.1GiB。UI的可用860.1GiB是WSL视角，不将它当作Windows宿主实际剩余空间。

证据：`provider/export-homefix.json`、`evidence/homefix-resource-export-native.jpg`、`evidence/homefix-resource-verify-native.jpg`。没有勾选导入信任框或点击“导入已检查资源”，没有修改现有镜像标签/已有资源。没有第二台独立电脑，因此跨机器实际导入、再运行及完全离线可用性未测。为目标机复用仍需独立准备本地评测运行环境，并安全配置运行时MiMo密钥。

本次因 computer-use 技能要求，所有原生动作使用受支持的窗口操作，安装动作曾停等真实用户确认；此停顿保留为工具安全要求，不计产品UX。最终没有浏览器同版应用替代；浏览器仅用于官方/公开用户文档。所有问题保留首次探索与修复后复测的区别，失败实验与旧镜像包均未删除。

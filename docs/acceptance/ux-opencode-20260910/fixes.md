# OpenCode 黑盒可用性验收修复记录

修复 agent 只依据体验反馈改进产品，不向体验 agent 提供内部 API 配方，不替它创建用例或跑通任务。原有未提交的数据删除功能保持不变；不提交、推送、发布或修改生产容器。

## INFRA-01：独立验收实例不能选择本机服务端口

- 来源：协调者报告，桌面端固定 48173，与已运行生产实例冲突。
- 原因：普通请求、健康检查、上传共用编译常量，无法安全指向隔离实例；环境管理操作仍指向正式 Compose 项目。
- 改动：仅调试构建读取 `CTXBENCH_DEBUG_WORKER_PORT`，进程首次读取后固定；只接受 1–65535 的纯数字端口，地址固定 `http://127.0.0.1:<port>/v1`。非法值失败关闭，不回退到生产端口。发布构建不读取该变量，保持 48173。
- 隔离保护：所有原生服务请求统一基址，禁用代理及 HTTP 重定向。隔离模式在页面持续显示中英文标记，隐藏生产环境启停/日志/镜像安装入口，原生层也拒绝相应命令。定制镜像、独立用例/实验、只读镜像列表及导出仍可使用；镜像和 Docker Engine 仍与生产共享，禁止替换生产标签。
- 回归：Rust 原生单测 26 通过、5 项 WSL 环境集成测试默认忽略；前端生产构建通过，新增中英文隔离提示与生产入口隐藏测试通过。协调者已编译启动 48174 原生实例，普通用户开始使用；文件上传端到端待实际导入操作验证。
- 协调者集成补查：显式覆盖到 48173 也必须拒绝，否则正式服务会被误标为隔离。已补校验及含前导零的等价端口回归；默认未覆盖/发布版仍为正常正式服务语义。当前实际 48174 实例不受影响，待下次统一原生构建应用。中文错误提示已在 2026-09-11 体验者构建提交安全点落地，并通过翻译回归。

## INFRA-02：正式测试扫描到自定义验收仓库

- 来源：本轮 `npm test` 实际扫描到 `artifacts/.../case/repo/test/reservations.test.mjs`，协调者确认修复。
- 原因：Vitest 默认全仓发现，误把评测输入中的 Node test 文件当作产品测试。目标基线中的失败是预期行为，不应由产品测试执行。
- 改动：新增 `vitest.config.ts`，沿用 Vite 构建配置，仅在 `src/` 下发现产品测试；不读改评测仓的内容，不跳过任何现有产品测试。
- 回归：完整 `npm test` 33 文件、198 项通过，`npm run build` 通过；新建自定义仓仍保留在原位置，不再被扫描。此前全仓统计包含 `artifacts` 下的副本和外部套件，不能作为产品测试数量；收窄后涵盖全部 `src` 产品测试。

## 待处理实测反馈

## UX-001：中文“帮助”落到英文 GitHub 仓库首页

- 来源：普通用户首次探索，S3 非阻断，需在长 README 中找镜像工坊文档。
- 原因：全局帮助直接使用仓库根页链接，没有按使用语言和用户任务组织帮助。
- 改动：改为应用内双语帮助弹窗，给出镜像适配 → 独立用例 → 实验及结果的可见操作路径；解释用例/评测集/实验/知识库；明确 API Key 运行时配置、未知 Token 不阻断评分、独立判分和日志入口。GitHub 根页只保留为明确标注“高级”的可选链接。无源码/API 配方，无 OpenCode 代配置。
- 回归：双语内容、帮助按钮不直接外跳、凭据/因果边界说明的前端测试通过。体验 agent 已独立确认中文与英文原生帮助主路径均通过：对应语言的应用内三步入门及概念/凭据日志说明正常展示，不跳 GitHub；已记录于 findings.md。

## UX-002：制作镜像时无法发现本地基础镜像

- 来源：普通用户首次探索，S2 可绕行；不得不去镜像导出页查看标签再返回制作页。
- 原因：制作第一步只有镜像名自由输入框，没有现有 WSL 镜像清单和自带工具说明。
- 改动：第一步直接提供当前 WSL 已安装镜像下拉框与刷新按钮，保留手动输入和拉取入口。只读列举，不自动拉取或更换标签；提示自带 Pi 镜像含 Node/npm、Python、Git、Shell，安装不代表项目依赖齐备或评测兼容。
- 回归：前端完整 34 文件、204 项通过，build 通过；覆盖双语入口、空发行版提示、清单去重且不虚构已安装镜像。Headless 回归覆盖选择回填、刷新失败保留手动输入及恢复。体验 agent 已独立完成原生只读复测：第一步直接显示 Ubuntu 本地镜像下拉、`ctxbench/agent-pi:0.1.0` 与基础工具说明，刷新经历读取状态后恢复原标签，无报错；展开后 Escape 关闭，未改变已有配方选择。记录见 findings.md。
- 测试部署注意：本次 HMR 落地时体验 agent 可能仍在表单。已立即告知潜在状态重置风险，后续编辑表单相关组件先协商时间；测试热更新扰动不冒充产品首次用户发现。

## 边界补充回归（非用户发现）

- OpenCode 的公开配置支持 `{env:NAME}` 引用（[官方配置文档](https://opencode.ai/docs/config/)）。新增回归确认这种非密钥占位值原样进入制作材料，替换成已知运行时密钥时在持久化前拒绝。
- `npm run worker:test` 完整通过：306 项，其中 2 项 Windows 无权限创建符号链接而跳过。测试临时目录位于 D 盘；没有调用真实 Provider、构建新镜像或触碰生产数据。

## UX-003：已上传文件与“未选择文件”显示矛盾

- 来源：普通用户首次探索，S3 非阻断，镜像向导第三步和最终构建表单均复现。
- 原因：文件内容加载进组件状态后清空原生 file input 以允许重选同文件，浏览器据此显示“未选择文件”；这个原生值不代表已加载材料的实际状态。
- 改动：两处统一使用“选择/替换文件”按钮与显式已载入文件数，保留现有路径映射；取消选择不丢已有内容，重复选择相同文件仍可更新。原生文件控件隐藏，不再同时展示矛盾状态。读取失败保留原列表，最终表单成功更换文件后需重新确认信任。
- 应用时机：2026-09-11 体验者自行提交构建 `op-13d9c7bf9a4646ed` 后明确通知安全点，才应用 HMR；同时补齐 48173 端口拒绝错误中文提示。未重启服务或干预构建。
- 回归：`npm test` 34 文件、207 项通过；`npm run build` 通过。扩展 `scripts/image-workshop-ui-smoke.mjs`，英文/中文均通过真实控件交互：选择按钮打开文件选择器、已载入计数、空选择/取消不丢内容、读取失败保留旧列表、同名文件可重选更新、方案传入最终表单仍显示已载入、替换文件后重新确认信任，以及最终请求保留正确字节。用例自定义 Agent 与独立评分命令、未知 Token 不阻断实验等旧链路回归同时通过。全部服务调用为测试桩；真实原生复测由体验 agent 独立完成。

## UX-004：切换用例编辑步骤后仍停在旧滚动位置

- 来源：普通用户首次探索，S3 非阻断。从仓库环境页底部进入任务与测试页后，直接看到下方评分命令，看不到顶部任务 ID 和 Agent 提示词；需自行上滚。
- 原因：用例编辑器切换步骤只替换内容，没有同步滚动位置与键盘焦点。
- 改动：新步骤显示明确标题，切步后滚动到该步骤开头并聚焦标题；首次打开不额外移动焦点，保留原有模态焦点行为，不清空任何字段。仅步骤变化触发，普通字段编辑和校验错误不改变滚动/步骤。实测原有初始焦点在关闭按钮，Tab 可到用例名称；此前计划中“默认名称输入焦点”描述已据证据纠正。
- 应用时机：体验者自行保存用例成功后通知安全点，才更新；未打断其长表单。针对实际滚动区 `.workbench-dialog > .workbench-form`，不修改全局模态滚动策略。
- 回归：`src/testing/case-step-focus.smoke.mjs` 中英文均通过，覆盖前进/后退、标题可见/焦点、Tab 进入首字段、普通编辑不跳顶部、校验失败不提交/不跳步、字段保留。全部原生/服务调用为测试桩，未操作体验者窗口或真实用例。体验者随后独立完成中文原生只读复测，确认仓库页底部点下一页后，从任务页标题/任务 ID/完整提示词开头显示，主路径通过。

### UX-003 补充：隐藏测试 / 参考修复上传控件

- 体验者在用例隐藏测试上传处再次实测到相同矛盾。该处与旧数据集向导共用字段组件，已一起换成明确的导入按钮与补丁文字状态。
- 不虚构文件来源：有内容时说明“可能来自导入或手动编辑，保存以当前文字为准”，不显示原文件已选中或仍与磁盘同步。取消/失败保留当前文字，导入新文件替换文字；隐藏测试仍然仅供评分器使用。
- 在上述用例保存安全点一并更新。`npm test` 34 文件、209 项通过，`npm run build` 通过。上述步骤回归另覆盖导入按钮打开选择器、空选择保留文字、读取失败保留文字、同名文件再次导入、导入后手工改写并提交当前文字；中英文均通过。
- 体验者原生只读复测确认已有 Git diff 保留、按钮与“保存以当前文字为准”说明正常，旧的“未选择”不再出现。原生文件选择器 Escape 那次因自动化发给主窗口造成两层一起关闭，体验者明确标记工具焦点不确定，不记为产品取消路径通过或失败；已完成的 headless 取消回归仍有效。

## UX-005：冻结知识库选择没有空状态解释和导入路径

- 来源：体验者在新实验选择“已冻结知识库”后，下拉只显示占位文字，不知道为何没有选项；自行绕行关闭实验、到知识库页面导入。S3 非阻断。
- 原因：选择器只过滤仓库、完整基线提交及 ready 状态，没有说明过滤条件或未匹配原因。
- 改动：`FrozenPackagePicker` 解释匹配条件与所需仓库/完整提交，分别说明尚无包、不匹配、生成中或失效；从实验内打开现有导入弹窗，保留草稿，完成后刷新可选包，不自动选择。App 的读取失败、手动刷新中状态优先于空状态，避免把读取失败说成没有包。未改变任务、模型、预算或匹配规则。
- 应用时机：体验者实验提交后、组合小集保存且资源包导出已提交的安全点，才 HMR。
- 回归：`src/testing/frozen-package.smoke.mjs` 中英文均通过加载/失败/恢复、上下两层真实模态、取消或成功导入后实验草稿保留、导入后不自动选包、显式选包才传入实验请求。SSR 覆盖无包/不匹配/未就绪/严格匹配条件。前端 35 文件、217 项通过，build 通过。
- 原生复测：体验者确认匹配说明、刷新和就地导入入口可见。已有匹配包，未为制造空态删除/修改数据；空态与就地导入交互由独立双语 headless 覆盖，不冒充完整原生复测。

## UX-006：最终确认页只显示默认 Agent 镜像

- 来源：体验者首次新实验的确认摘要显示默认 Pi 标签，与任务页明确展示的自定义 Agent 覆盖冲突，担心跑错工具。S3，体验者继续预检。
- 原因：确认摘要直接显示实验默认镜像，没有呈现用例自定义命令的实际镜像优先级。
- 改动：确认摘要明确标注“实验默认”模型/镜像，新增各任务代码 Agent 镜像来源（用例覆盖、实验直接使用、待合成基础镜像），区分知识构建角色；不把尚未构建的合成镜像说成已有最终摘要。仅修展示，不改已配置请求、镜像或执行行为。在上述同一安全点应用。
- 回归：混合自定义/默认、全自定义、项目合成开/关、知识生成开/关的双语组件测试通过；上述 headless 确认自定义镜像与覆盖说明出现在最终确认页，明确选包的实验请求不变。
- 原生复测：体验者新建同条件 retest1 时确认最终页已区分实验默认 Pi，逐任务展示其 adapted 镜像与自定义命令覆盖说明；已自行截图留证，主路径通过。

## UX-007：Windows/WSL 跨 UID 本地仓库在 Agent 启动前被 Git 拒绝

- 来源：体验者自行提交真实实验 `exp-efbc54f1cb29`，两臂在 `Fetch frozen Git baseline` 失败且 `agentStarted=false`；资源包导出 `op-0c9ee27f18cc4970` 随后复现同一错误。首次失败保留，不算模型评测通过。
- 原因：源仓库为只读挂载、UID 1000，评测服务进程 UID 0。路径存在且可读，Git 的跨所有者信任检查拒绝本地传输的独立 upload-pack 子进程，而不是普通写权限不足。
- 改动：中央 baseline fetch 对用户明确选择的绝对本地仓库（或显式本地 mirror）传递命令级 upload-pack：禁用 hooks，重置该子进程的 safe.directory 列表，仅信任确切仓库及其 `.git`。不写全局配置，不修改源仓库所有者/权限/文件；远程 URL、相对路径、非仓库、`.git` 间接跳转或通配路径不增加信任例外。Git 官方文档说明 [safe.directory 的受保护配置作用域](https://git-scm.com/docs/git-config#Documentation/git-config.txt-safedirectory)；实现使用 [fetch 的 upload-pack 选项](https://git-scm.com/docs/git-fetch#Documentation/git-fetch.txt---upload-packltupload-packgt) 将例外限于这一次本地读取。
- 诊断：单独识别 dubious ownership，明确这不是写权限错误，提示更新服务获得命令级兼容；不再误导用户 chmod/chown 或全局信任所有仓库。中文同步。
- 回归：新增本地 Git 4 项在 Ubuntu 原生 Python/Git 全通过；跨所有权情形验证无例外时失败、仅本次 fetch 成功、再次无例外仍失败，原配置/文件不变、固定提交不变；涵盖含空格/单引号路径、显式 bare 仓库、远程和无效路径边界。Windows 此传输检查未触发，相关项明确跳过，其他项通过。协调者另在一次性同版本 Linux 评测镜像中确认这 4 项通过。完整 `npm run worker:test` 共 311 项，308 通过、3 明确跳过（上述 Git 项及 2 项 Windows 符号链接权限），耗时 318.9 秒。
- 部署：协调者已确认空闲后仅重启 48174 隔离实例并恢复健康，正式服务启动时间保持不变；已通知体验者自主通过 UI 重跑。修复 agent 未操作生产容器或代重跑实验。同版本一次性 Linux 镜像的本地 Git 与诊断合计 16 项通过。
- 原生重测：体验者自行提交 retest1，确认指定 Git 基线获取和干净 checkout 均成功，自己的 Agent 镜像容器实际启动，原运行阻断已解除。之后失败为另一个镜像 HOME 问题（UX-008），尚未证明 MiMo 调用或独立评分成功；资源导出原生复测另行进行。
- 导出原生复测：体验者自行提交 `op-e8827c4723664a34` 并确认完成，1 个自创集合/基线/原 Agent 镜像/中性知识包。ZIP 为 432068108 字节，界面 SHA256 `b88f2a220362ae55de2e1b57fd47641ebbded9e0fbe35ec6863c51f5ab40e079`；其自行复制保存，截图已记录。此包包含 HOME 修复前的镜像，导出成功不等于模型通过。

### UX-007 补充文案：导出源支持单用例，但只写“自定义评测集”

- 来源：体验者原发现记录指出，下拉展开后才看到独立用例，先额外组合了一个集合。协调者要求仅修该入口，不全局改变评测集概念。
- 核实：前端来源实际合并独立 cases 与 sets；后端导出能冻结两类来源，原本不要求先建集合。
- 改动：仅导出选择器标为“要导出的自定义用例或评测集”，占位及选项类型前缀明确两类；说明可以直接导出单用例，ZIP 包含定义、固定基线、必需及所选镜像、所选冻结知识库，目标机运行时凭据另配。保留自检入口、ID、过滤规则和导出请求不变。
- 时机与回归：体验者 retest2 已提交、明确不在编辑长表单后才 HMR，未重启服务或操作实验。双语回归检查导出新标签/提示且自检旧概念未变化；前端 35 文件、220 项及 build 通过。无代导出或新后端行为。
- 原生复测：体验者进入资源迁移后，通过 AX/截图确认新标题及“可以直接导出一个用例”说明已显示，随后自主填写新镜像导出表单。

## UX-008：向导安装后的 HOME 子目录仍属于 root

- 来源：协调者先通过只读证据定位，之后体验者从原生实时日志独立发现并编号；`PermissionDenied: FileSystem.open (/home/ctxbench/.local/share/opencode/log/opencode.log)`，Agent 已启动、退出码 1，未见模型输出。体验者截图 `evidence/ux008-opencode-home-permission-native.jpg`。当前模型主链路阻断。
- 原因：镜像向导只在安装前将 HOME 顶层交给 UID 10001；后续 root 安装或执行版本检查会在 HOME 内创建新的 root-owned 缓存目录，没有安装后权限收尾。实际顶层为 UID 10001，`.local/share/.../log` 各层为 root:root 755，不是体验者遗漏向导要求。
- 改动：默认 `/home/ctxbench` 在安装/配置后做 `chown -R -h 10001:10001` 所有权收尾，以 `USER 10001:10001` 检查可写/可进入，再恢复原有镜像默认 root；实际 Agent 运行仍强制 UID 10001。所有 chown 前拒绝 HOME 根及 `/home` 父目录 symlink，递归不跟随子链接。任意自定义 HOME/外部缓存配置路径不自动递归处理，双语界面与公开文档明确其权限责任；不特殊处理 OpenCode，不改任务或评分。
- 应用时机：体验者资源导出已提交、明确无草稿后，一次性 HMR。仅回报新界面已就绪，让体验者自主阅读并制作新镜像。
- 回归：前端 35 文件、218 项通过，build 通过；`scripts/image-workshop-ui-smoke.mjs` 中英文全部通过。`src/testing/image-home.container.mjs` 从实际生成配方提取 RUN，在无网络/无挂载/无凭据的一次性基础容器验证 root 新建缓存收尾后真实 UID 10001 可创建日志、子 symlink 不改变外部 owner、根/父 symlink 在任何 chown 前拒绝。负例将相同 guard 映射到容器临时目录，避免移动 overlayfs 的原始 HOME；三场景通过。测试容器自动移除，未生成或替换用户镜像。
- 普通角色仍自主导出/制作，不代构建、代配置或代跑。现有安装工具镜像可作为后续适配基底，无需重下 OpenCode；旧镜像与失败实验保留。
- 原生制作复测：体验者自行阅读新界面后，以原 Agent 镜像为基底、安装命令留空、无新文件、离线构建完成 `op-2ff9ab040e4f4ba1`。新标签 `ctxbench/adapted:26b31b1f25d24dee8679f5508cf4a305`，ID `sha256:5908f6a2f0c243c6f7d54d95111b84fba99fbd36de2643c621be53a2aad4e625`；向导无需重复安装的路径原生通过，后续由其自行修改用例并新建实验验证运行。
- 协调者补查：修正版镜像在无网络/无挂载的一次性容器中，以真实 UID 10001 可向原先失败的 OpenCode 日志目录创建文件；14 层 gzip 的已知运行时 Key 审计无匹配。不将已知 Key 检查等同于穷尽所有未知凭据，也不将此权限探针等同于模型运行通过。
- 旧资源包校验亦由其自行完成：`op-36d5db6faad64b76` 展示 1 镜像/1 基线/1 知识包，未导入或覆盖已有数据。

## 双语界面回归证据

- 脚本：`src/testing/ux-feedback.smoke.mjs`。独立 headless 浏览器、端口 43186；所有原生/服务调用均为测试桩，不接触体验窗口、Docker 或模型。
- 英文/中文均通过：选择本地镜像回填输入；刷新失败保留手填值；列表恢复后重新选择；帮助位于真正的模态顶层、不打开外部标签页；Escape 关闭帮助后镜像配方仍在；无页面异常。
- 脱敏截图：`artifacts/ux-feedback-headless/en-help.png`、`zh-CN-help.png`。
- 以上是产品 UI 回归证据，不替代普通用户在真实原生实例的独立复测。
- 既有 `scripts/maintenance-ui-smoke.mjs` 已补正常连接的测试响应，中英文维护确认/恢复路径/状态保留/活动与未知容器保护/响应式布局，以及本地 Parquet 选择/旧服务提示/预览失效/显式导入确认全部通过。

## UX-009：完成结果的日志请求被误报为连接中断

- 来源：体验者原生结果详情只有自动定位选项，持续自动重连，但同一结果的独立评分证据文件可读。协调者只读复核真实 `benchmarkRunId` 请求返回 HTTP 422。
- 原因：planner 生成 `experiment:task:repeat:arm`，日志列表却对所有 scope 使用不允许冒号的短 ID 规则；与 48174、任务已完成或日志存储无关。前端又把确定性参数拒绝混同网络断线。
- 改动：仅 `benchmarkRunId` 支持 planner 的有界复合格式，兼容任务 ID 的中文、点及冒号；重复次数 1–50、已知分组、最长 4096，无控制字符。旧简单 ID 保留；其他 scope 和日志文件/session ID 验证不变。任务部分仅作为参数化 SQL 的元数据等值查询，不参与路径构造。前端对这条确定性拒绝明确提示更新匹配服务后刷新，不再每秒无效重连；正常网络故障保留自动重连。
- 回归：真实 planner ID、长任务名、中文/斜杠/冒号任务名、各任务/各组隔离、SQL 字面量不扩散查询、非法范围/控制字符/路径的后端回归通过。`test_live_logs` + `test_diagnostics` 27 项通过。新 `src/testing/run-evidence.smoke.mjs` 中英文验证拒绝只请求一次、恢复后完成态阶段/归档可读、独立评分证据不丢失，全部接口为只读测试桩。
- 部署：协调者确认所有任务空闲后，仅更新 48174；真实两臂日志接口现在均 HTTP 200，各有 4 个 session，未串组。不重新运行模型、不改分数或历史记录。
- 原生复测：体验者确认 none 详情自动恢复，显示日志流结束、退出码 0；阶段下拉包含项目测试、编码 Agent、启动校验与准备。选择编码 Agent 可见真实 OpenCode / mimo-v2.5 工具事件及最终修复消息，从头读取完整日志与返回尾部均可操作。证据为 `evidence/ux009-retest-native-log.jpg`、`evidence/retest2-none-opencode-final-native.jpg`，主路径通过。

## UX-010：评分证据正文被模态布局压缩为一行

- 来源：体验者看到 TAP 证据正文视觉高度约 29px，只有一行与极小滚动条；AX 虽可读取全文，但人眼难以阅读。协调者要求只修该证据容器。
- 原因：直接置于纵向 flex 表单的 `pre` 允许收缩，内部 overflow 导致可视正文被挤压。
- 改动：只对运行详情的证据 `pre.run-evidence-output` 禁止收缩，设随视口调整的合理最小高度与上限，保留内部滚动；可聚焦并有双语区域名称。不改变其他预览、日志数据、加载分页或全局模态布局。
- 回归：上述新 headless 在 850px/600px 高视口均验证正文至少 240px、上限不超过半屏、内部滚动和 End 键可读到底。中英文通过，截图位于 `artifacts/ux-feedback-headless/evidence-en.png` 与 `evidence-zh-CN.png`；已查看中文截图，正文恢复多行可读。
- 两项在体验者明确只读、无未保存表单的同一个安全点 HMR；没有操作其文件、实验或导出。前端当前 35 文件、221 项及 build 通过。
- 原生复测：体验者在 manual 的 `grading/evaluator.log` 确认约 360px 多行独立阅读区，可见 E01–E03；鼠标滚动与拖动滚动条均可到达末尾 9/9 汇总。证据为 `evidence/ux010-retest-multiline-native.jpg`、`evidence/ux010-retest-scroll-bottom-native.jpg`。UX-009/010 本轮均闭环，无后续产品修改。

## 最终真实链路结论与限制（2026-09-11）

- 体验者独立通过原生界面构建 OpenCode 镜像、配置运行时变量名、设计自己的 Node.js 后端用例及 evaluator-only 的 HTTP 断言、导入基线中性知识包、修改用例版本并创建实验。修复 agent 未替其创建/配置/运行用例，也未提供通关命令模板。
- 最终实验 `exp-ec7368d4195c`（`ux-opencode-20260910-mimo-retest2`）：协调者独立核验真实 OpenCode + MiMo，两臂各 9/9 独立 HTTP 测试通过，`mock=false`、`evidenceIntegrity=verified`。体验者亦已从原生 UI 看到两组通过，且自行读取 none / manual 的 TAP E01–E09 全部通过、0 失败/跳过（none 458.787944ms，manual 461.269954ms），保存原生导出记录。修复前失败实验仍保留。
- 新镜像为 `sha256:5908f6a2f0c243c6f7d54d95111b84fba99fbd36de2643c621be53a2aad4e625`。新资源包导出 `op-b34f7dc7536a4d35` 已由体验者通过 UI 提交，协调者确认完成；最终包的复制、原生校验和独立审计由体验者/协调者收尾，不以旧镜像 ZIP 代替最终包。
- 范围只证明一个自创后端用例、重复 1 次的两臂实际链路，不是官方 SWE/CTX 全集验收，不验证自动生成知识库的质量，也不能得出知识库是否改善模型效果的统计结论。知识库为人工基于固定基线提供的中性文档，模型用量仍是未知而非零。
- 凭据只在运行时传递。协调者报告新镜像 14 层已知 Key 审计无匹配；此项不代表能穷尽所有未知凭据。无 commit/push/release、无生产服务重启、无删除用户数据或更换旧快照。

### 最终回归计数

- `npm test`：35 文件、221 项通过；`npm run build` 通过，保留既有大分包警告。
- 最终完整 `npm run worker:test`：协调者在全部修复合入工作区后复核 313 项，310 通过、3 明确跳过，耗时 271.301 秒。跳过仍为 Windows 两项符号链接权限、一项 Git ownership 检查；Linux 补充回归覆盖所有者边界。修复侧此前完整 311 项与 UX-009 后定向 27 项亦通过，不重复计数。
- Linux：本地 Git 4 项全过；同版本临时镜像 Git+诊断 16 项全过；默认 HOME 权限/符号链接边界 3 个离线一次性容器场景全过。
- 双语 headless：帮助/本地镜像、文件上传状态、用例切步、嵌套知识库导入与镜像确认、镜像工坊完整旧链路、维护/导入页面、完成态结果日志与证据尺寸均通过。长日志既有脚本覆盖完整 1.2M 字符分页，不以 UI 尾窗代表全部归档。
- 原生调试端口回归：协调者此前报告 Rust 27 项通过、5 项明确忽略；非法端口与发布版固定端口语义有覆盖，当前日志与样式修复未再改原生代码。

### 修复 agent 修改文件清单

以下路径相对于仓库根目录；包含与原有删除功能同文件上的小范围改动，但不将删除功能本身归因于本次修复。原有 README、删除功能实现与其测试保持不回滚。

原生连接与隔离：

```text
src-tauri/src/worker_connection.rs
src-tauri/src/lib.rs
src-tauri/src/dataset_upload.rs
src/lib/desktop.ts
src/lib/use-desktop-connection.ts
src/components/IsolationNotice.tsx
src/components/InfrastructureSetup.tsx
src/pages/InfrastructurePage.tsx
```

界面、镜像配方与文案：

```text
src/App.tsx
src/components/Topbar.tsx
src/components/UserHelpDialog.tsx
src/components/LocalImageSelect.tsx
src/components/BuildFilePicker.tsx
src/components/PatchFileImport.tsx
src/components/CaseEditor.tsx
src/components/DatasetWizardFields.tsx
src/components/ImageRecipeGuide.tsx
src/components/IntranetWorkbench.tsx
src/components/FrozenPackagePicker.tsx
src/components/AgentImageReview.tsx
src/components/ExperimentComposer.tsx
src/components/WorkbenchDialogs.tsx
src/components/ContainerLogs.tsx
src/lib/image-recipes.ts
src/i18n.tsx
src/i18n.user-help.ts
src/i18n.image-workshop.ts
src/i18n.experiment-guidance.ts
src/i18n.intranet.ts
src/i18n.live-logs.ts
src/ux.css
```

后端与后端回归：

```text
worker/ctxbench_worker/runtime.py
worker/ctxbench_worker/diagnostics.py
worker/ctxbench_worker/live_logs.py
worker/tests/test_local_git.py
worker/tests/test_diagnostics.py
worker/tests/test_live_logs.py
worker/tests/test_intranet.py
```

前端与独立交互回归：

```text
vitest.config.ts
src/lib/desktop-isolation.test.tsx
src/lib/user-help.test.tsx
src/lib/image-workshop.test.tsx
src/lib/case-library.test.tsx
src/lib/experiment-guidance.test.tsx
src/lib/intranet.test.tsx
src/lib/live-logs.test.tsx
scripts/image-workshop-ui-smoke.mjs
scripts/maintenance-ui-smoke.mjs
src/testing/ux-feedback.smoke.mjs
src/testing/case-step-focus.smoke.mjs
src/testing/frozen-package.smoke.mjs
src/testing/image-home.container.mjs
src/testing/run-evidence.smoke.mjs
```

文档：

```text
docs/image-workshop.md
docs/acceptance/ux-opencode-20260910/fixes.md
```

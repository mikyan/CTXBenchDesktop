# 公司镜像仓库：只下载需要的用例

适用于“可以联网，但 Docker Hub 不通；公司仓库只保存部分项目镜像”的环境。不需要先完整打包整个官方评测集。

**如果 Docker Hub 可以下载，直接使用默认官方来源即可：无需配置镜像映射，也无需完整离线包。** 在软件中选择少量用例、按需安装镜像；缓存可供后续重复实验复用。若选择了公司配置，请确保没有开启“离线准备”，也没有启用不需要的公司镜像映射。公司 npm／pip／Maven 源是另外的配置问题。

本功能从 v0.1.6 提供；使用旧安装包时，需要更新桌面端、本地评测服务和官方评测器镜像。旧评测器会明确提示升级，不会悄悄按公共镜像地址执行。安装、知识库准备、评测共用同一套镜像解析规则。

## 直接填写单个镜像地址（v0.1.7）

公司自定义测试／Agent 镜像不必经过官方镜像映射：**设置 → 镜像适配 → 拉取现成镜像** 可以按完整地址下载，旁边还有安装依赖和修改默认配置的四步向导。用例镜像字段也有快捷下载入口。见[公司镜像和自定义 Agent 指南](image-workshop.md)。此通用入口填写镜像名，而下文的官方逐镜像入口还支持粘贴 `docker pull …`。

现在可以不去设置页写前缀规则，直接在 **评测用例／评测集 → 安装项目镜像** 操作，SWE-bench 和 CTXBench 都支持：

1. 选择想跑的用例，在 **所选镜像的下载地址** 中找到对应的官方镜像名。
2. 输入内网完整地址，也可以粘贴完整命令，例如：

   ```text
   docker pull harbor.company.example/bench/planbenchx86_opshin_opshin:latest
   ```

3. 点 **保存地址并刷新**，检查页面的“当前实际下载地址”和本机安装状态。
4. 点 **安装所选项目镜像**，确认后下载。也可以先检查仓库可用性。

软件只提取镜像名，通过 Docker 接口拉取，不执行粘贴的 Shell 命令。支持域名、端口、多层路径、标签或 `@sha256:…` 摘要；不接受 `docker login`、`--platform` 等附加参数、管道、凭据 URL 或多条命令。平台固定为 linux/amd64。留空并保存可恢复公司前缀映射或官方默认地址。

未选择公司方案时，精确地址作为这些官方镜像的默认来源，其他评测集若使用同名镜像也会复用；选择了公司方案则只在该方案版本下生效。后续知识库准备、实验会自动复制对应地址到运行配置中，模型配置不变。已排队、已准备、恢复或重试的任务不追随新的地址修改。原始评测集和本机官方标签都不会被覆盖。

优先级：**单个镜像的完整地址 → 公司最长前缀规则 → 官方原始名称**。存在有效的精确地址或公司规则时，未映射的缺失镜像不会自动从 Docker Hub 拉取；请为其指定允许使用的完整地址，或事先安装到本机。已指定地址拉取失败时不会退回官方名称。SWE 个别用例的编码环境与评分环境镜像不同，需分别指定页面列出的地址。

应指定同一项目镜像在内网的对应副本，而不是任意基础镜像；工具会记录实际镜像 ID，但不会仅因地址替换就证明内容与官方等价。公司镜像改造之后仍需验证基线依赖与测试。私有仓库认证方式见下文，不要把登录口令填在镜像地址里。

这项新入口需同时升级桌面端与本地评测服务镜像，旧版 v0.1.6 的前缀配置能力仍保留。

## 1. 配置公司地址

在 **设置 → 公司配置 → 公司 Docker 镜像仓库** 中添加映射。例如公司提供的命令为：

```text
docker pull registry.company.example/swe-bench-verifield/sympy_1776_sympy-18189:latest
```

配置为：

| 字段 | 内容 |
| --- | --- |
| 原始镜像名前缀 | `swebench/sweb.eval.x86_64.` |
| 公司镜像名前缀 | `registry.company.example/swe-bench-verifield/` |

域名是示例，必须替换。`swe-bench-verifield` 按实际仓库目录填写，软件不会自动纠正拼写。后面的用例名和标签保持不变。可添加多个规则，最长匹配优先；完整镜像名也可作为单个镜像的精确规则。配置中不得放密码、Token 或带认证信息的 URL。

允许从公司仓库下载时，**取消“离线准备”**，保存配置版本。

SWE 的规则不覆盖 CTXBench。CTXBench 需要按页面列出的原镜像名另配规则。部分 SWE matplotlib 用例还需要单独的 Agent 项目环境变体；页面会列出全部需求，不会只检查评分镜像。

## 2. 检查、选择、下载

1. 导入官方评测集文件，在评测集卡片点 **安装项目镜像**。
2. 选择刚保存的公司配置。
3. 可先筛选项目，点 **检查筛选结果所需的镜像**。只查询镜像信息，不下载镜像层，不调用模型；进度可查看、取消、重试。
4. 点 **只选镜像可用的用例**，检查所选范围，确认下载。
5. 安装后点 **用所选用例创建实验**，自动带入用例和公司配置；也可以在独立知识库生成时选择该配置。

| 状态 | 含义与操作 |
| --- | --- |
| 本机已安装 | 镜像存在且平台匹配，但不表示项目测试已验证通过 |
| 仓库中可下载 | 元数据检查通过，仍需安装；检查有效期 15 分钟 |
| 仓库中未找到 | 该镜像没有同步到公司仓库，换用例或请管理员补充 |
| 需要登录或权限 | 不能认定镜像不存在；先处理认证 |
| 连接失败 | 不能确定有无镜像；检查 DNS、证书、网络后重试 |
| 未配置可访问来源 | 补充映射，或将对应镜像导入所选 Docker 引擎 |

没有匹配规则的镜像仅允许使用本机已有版本。只要公司配置包含镜像映射，软件就不会自动退回 Docker Hub。原始公共标签已缓存也不会绕过已配置的公司映射。检查不会删除用例或修改原始评测集；子集实验仅代表所选用例，不是完整官方集成绩。

## 3. 私有仓库登录

WSL 中的 `docker login` 凭据不会自动共享进本地评测服务容器；Agent 的 API Key 也不能用于 Docker 仓库登录。

当前可在软件选择的同一 WSL 发行版中执行 `docker login 公司域名`，随后按页面导出的完整名称 `docker pull 镜像名`，回来点刷新。所有操作针对同一个 Docker 引擎，因此软件能直接复用拉取后的镜像。无需手工复制文件到容器，也不要把登录凭据写进公司配置或镜像层。

## 4. 空间与可复现性

不要默认下载全部。2026-09-08 本机实测：SWE SymPy `sympy__sympy-12489` 的镜像大小约 3.92 GB，CTX opshin 项目镜像约 815 MB。它们是 Docker 报告的镜像大小，不是压缩下载量或每个镜像独占的磁盘空间；共享层可复用，构建后的环境又会增加占用。

SWE-bench [官方 Docker 指南](https://www.swebench.com/SWE-bench/guides/docker_setup/)建议至少 120 GB 空闲空间，并指出缓存全部实例镜像可能达到约 2 TB。这是通用规划参考，不是 Verified 500 或任意子集的精确下载总量。镜像所在的 WSL 虚拟磁盘和 Windows 宿主盘都要有空间。

实验开始时，软件先解析全部所选用例的项目镜像，再开始付费知识库构建或求解。镜像按实际内容 ID 冻结，配对、重复和恢复使用相同 ID；已冻结镜像丢失时必须恢复原镜像，不会重新下载同名 `latest` 来替换。

官方评分器也只使用传入的本机固定镜像，不会在内部重新拉官方地址。SWE 使用临时独立标签兼容官方评分器，结束后仅移除自己的临时标签，不覆盖公共标签。

## 边界

- 镜像可用不等于测试已跑通。CTXBench 仍需按基线版本准备依赖并执行评分器自检。
- 本功能不替换 npm、pip、Maven 源，也不重写任意 Dockerfile 的 FROM。公司受限模式下，自定义用例必须提供预构建测试镜像，避免 Dockerfile 绕过来源配置。可先使用镜像适配功能准备好所需工具和源配置。
- 公司自定义镜像的内容与官方是否一致，需要自行验证；报告记录实际镜像 ID，不把公司改造镜像宣称为官方等价镜像。
- 没有批量下载完整官方集，没有用付费 Provider 做本次验证，也尚未连到实际公司域名验证仓库覆盖率。

## 开发验证

### 单个完整地址入口（当前源码）

`npm test` 141 项通过，`npm run build` 通过（保留已有大分包警告）；`npm run worker:test` 共 219 项，217 项通过、2 项因 Windows 符号链接权限跳过。新增镜像地址回归 11 项通过，覆盖完整命令提取、摘要地址、凭据／Shell 拒绝、乐观版本冲突、公司方案隔离、精确地址优先级、离线限制、恢复默认、未配置来源禁止自动拉取，以及修改前已排队任务保持原地址。中英文镜像安装、用例库和用例创建交互脚本均通过。

`scripts/project-image-address-container-smoke.py` 在真实 WSL Docker 中通过：将本机已有的公开 `hello-world` 内容通过临时 HTTPS 镜像仓库提供给 Docker，CTX 镜像安装操作实际拉取用户指定的完整地址，SWE 操作复用同一目标；排队后修改配置不影响该操作，运行时解析得到已下载镜像的同一内容 ID。测试结束移除自己创建的下载／冻结标签及临时证书，原 `hello-world` 保留。不调用模型、不访问外部镜像源、不修改 Docker 守护进程配置，也不重启现有评测服务。这是镜像下载与配置传递验证，不是实际公司仓库连通性或官方全集评分测试。

### 既有前缀映射与评分器验证

2026-09-08：`npm test` 132 项通过，`npm run build` 通过（保留已有大分包警告）；`npm run worker:test` 191 项中 189 项通过、2 项因 Windows 符号链接权限跳过；脚本测试 49 项中 45 项通过、4 项跳过。中英文镜像安装、用例创建和维护交互脚本均通过。新增回归覆盖映射优先级、旧配置兼容、认证/缺失/网络区分、检查取消、固定 ID 恢复、缺少后续用例镜像时零 Agent 调用，以及独立知识库配置传递。

真实 WSL Docker 检查（不调用模型、不拉公共镜像）：

- `scripts/company-registry-smoke.py`：本机临时 Registry 协议服务，实际 Docker 元数据请求验证可用、404、401 三种状态，9 次请求，0 个镜像变化。
- `scripts/swe-harness-compatibility-smoke.py`：官方 v4.1.0，`sympy__sympy-12489` 的参考补丁在原始名称和固定 ID 两条路径均通过，所有 SDK 拉取调用禁用，原镜像保留、临时标签移除。
- `scripts/ctx-image-source-smoke.py`：`opshin_opshin-28` 使用缓存的基线依赖环境；即使给定不存在的原始镜像名，明确传入的源镜像 ID 仍能准备并通过官方参考补丁测试，禁止回退拉取。

这些是镜像来源与评分集成验证，不代表完成 SWE 500／CTX 138 全集，也不代表模型通过率。

## English summary

v0.1.7 adds per-image full address fields directly to the official image installer. Paste `registry/path:tag`, a digest reference, or a single `docker pull registry/path:tag` command; only the reference is used. Save and refresh before checking/installing. Exact addresses take priority over prefix mappings, are remembered by original image identity within the selected profile (or default scope), and are captured for new official experiments and independent context jobs. Existing jobs, custom cases, model settings and local official tags are unchanged. Empty values restore inherited defaults. Updates use optimistic revisions; queued operations retain their captured mapping even after edits.

Save optional `imageMappings: [{source, target}]` in a versioned company profile. Select that profile in the project image installer, independent preparation or experiment. The longest prefix wins; non-empty mappings disable implicit Docker Hub fallback. Unmapped images must already exist locally. Registry checks are explicit metadata-only operations, distinguish missing/auth/network errors and expire after 15 minutes. Select and install an explicit subset, then carry its task IDs and profile into a new experiment.

Experiment source images are pinned by content before paid preparation; CTX and SWE nested evaluators receive local immutable IDs. Old harness images fail with upgrade guidance. Dockerfile and package-manager source rewriting are outside this feature. Host registry credentials are not automatically mounted into the service; authenticated host `docker pull` followed by refresh is supported. See the verification record above for the exact limited, no-model integration coverage.

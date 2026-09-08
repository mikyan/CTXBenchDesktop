# 内网适配工作台 / Intranet workbench

入口：**设置 → 公司环境方案 / 镜像适配 / 资源迁移**。需要同时更新桌面前端和 Worker 镜像；旧 Worker 不支持 `/v1/intranet`。升级前让已有实验结束或暂停，保留原数据卷，不要清空实验数据。

## 公司环境方案

填写名称、Provider、模型、Agent／官方评测器镜像、Agent 参数和**环境变量名**。保存／导入／导出经过服务端校验，每个版本按内容哈希保存。创建新实验时选择方案，会填入默认配置，准备策略随实验冻结；之后仍可编辑本次实验的模型等配置，实际值以实验记录为准。已有实验不变。

密钥、接口地址等环境变量**值**在「运行环境」单独配置，只留在 Worker 内存，不随方案共享。仍需显式白名单。Provider 必须被当前 Agent 支持，填写新名称不会自动为 Pi 注册 Provider。公司 Agent 配置文件可随适配镜像安装，通过其支持的参数选用。

“离线准备”禁止自动 fetch/pull，要求已缓存基线与预构建镜像；缺少时明确失败。目前严格离线方案仅支持自定义评测集。Agent 自身网络由实验 offline / api-only / unrestricted 单独配置；离线准备不等于禁止模型 API 请求。

Git 镜像映射按完整地址精确匹配，例如原仓库 `https://github.com/example/project.git` 对应公司镜像 `https://gitee.company.example/mirrors/project.git`。只改变缺失 commit 的获取位置，不改任务、提示词、知识库身份或 commit。支持无嵌入凭据的 HTTPS、`ssh://git@host/path`、绝对 Worker 路径。Git 认证、known_hosts 和 CA 仍需运维准备，不会把 Agent API 密钥用于 Git 登录。导入资源包后可不再访问原仓库。

Provider 域名列表只**导出固定版本 Squid 配置**，不热修改运行中的代理。将 `squid.conf` 加入代理镜像适配，使用 `COPY squid.conf /etc/squid/squid.conf`，再通过已有镜像导出／导入流程部署。先结束受影响的评测，避免配对中途改变网络。导出规则只允许所列域名的 HTTPS CONNECT 443；其他协议／端口需单独审查适配。

## 镜像适配

选择已存在的本地基础镜像，输入 FROM 后的 Dockerfile 指令，添加公开 CA 证书、依赖清单或安装文件。FROM 自动固定为解析出的镜像 ID，在独立上下文构建，输出 `ctxbench/adapted:<唯一值>`；不改被测基线、不替换生产标签、不自动 pull 基础镜像。

```dockerfile
COPY company-ca.crt /usr/local/share/ca-certificates/company-ca.crt
RUN update-ca-certificates
COPY requirements.txt /opt/company/requirements.txt
RUN pip install --no-cache-dir --index-url https://packages.company.example/simple -r /opt/company/requirements.txt
```

联网安装需显式选择允许联网，默认构建命令网络为 none。文件最多 30 MiB／200 个，可修改上下文内相对路径；上传替换当前列表。大型依赖请先制成本地基础镜像。公开 CA 证书不是私钥，禁止上传私钥和凭据。暂不支持多阶段 FROM、ARG、BuildKit secret/SSH forwarding、任意主机构建目录；需要构建认证时请在可信外部流程预制基础镜像，不能把密钥写进 ARG、ENV、命令或文件。

记录可导出为 JSON，包含配方、文件、基础镜像 ID、结果 ID、标签、入口及兼容标签。进度页展示 Docker 构建日志，百分比仅代表外层阶段，不伪造依赖安装进度。日志按当前凭据脱敏。**兼容标签不是协议测试**，更换 Agent 后先跑小用例。这里没有实现自动 Agent 协议认证、交互式调试容器或 commit 工作流。

适配结果可用作自定义用例的 `image`，通过评测资源 ZIP 携带。已有“打包自定义 Docker 镜像”仍用于四角色运行环境包。

## 用例编写与无模型自检

在“实验 → 创建自定义评测集”中可保存／恢复 Worker 草稿版本，导出／导入草稿 JSON，将已有自定义评测集复制为可编辑草稿，查看相较加载版本的新增／删除／修改数量。编辑后创建新内容版本；完全相同内容复用原数据集，不借改名覆盖旧记录。

向导最后一步和“评测集 → 用例自检”都可真实自检。每次最多 20 个任务，必须提供 evaluator-only `goldPatch`，不调用 Agent。每阶段离线容器运行，2 CPU／4 GiB／10 分钟。

有隐藏补丁时依次检查原有测试＋基线、原有测试＋参考修复、隐藏测试＋基线、相同隐藏测试＋参考修复。没有隐藏补丁时只执行基线／参考两种命令组合，不假装验证了独立回归集。期望原有测试通过、目标基线失败、参考修复通过；缺镜像／依赖、命令不存在、导入错误等不能冒充有效行为失败。每阶段展示退出码和日志。

“自检组合符合预期”仅是**待人工复核的候选**。退出 1 不能证明断言正确覆盖需求，仍须检查失败原因。尚无逐断言结构化结果协议，不编造逐测试明细。草稿、隐藏测试和参考补丁仅保存在 evaluator 数据区，不写浏览器存储，不进入 Builder／Agent 仓库。自检和实验串行排队，离开页面后可查看最近操作。

## 评测资源 ZIP

**完整迁移范围：自定义评测集＋预构建测试镜像。暂不支持官方 SWE/CTX 全套动态测试环境。** 标准集仍参考[官方下载指南](standard-datasets.md)与[离线镜像流程](offline-images.md)，不能据此承诺全套脱网运行。

联网准备机器：

1. 自定义任务引用预构建测试镜像，注册后先自检。
2. 在迁移页选择数据集、附加 Agent 镜像，勾选冻结知识库和公司方案。测试镜像、选中方案的 Agent 镜像自动纳入。其他运行环境镜像可额外添加；目标 Worker 首次安装仍使用独立运行环境包。
3. 生成 ZIP，包含 evaluator 定义、精确 commit 的 Git 对象、本地镜像、所选知识库和方案。不复制原始 `.git`、父/未来提交、运行数据库、运行日志或密钥。LFS 指针和子模块会被拦截，需先固定并审查实际内容。缺失镜像不自动拉取。
4. 页面同时显示 Worker、WSL 和 Windows 资源管理器路径。按组织政策及数据／镜像许可复制 ZIP；校验和不是可信签名，扫描也不能保证任意镜像层没有历史泄露。

内网目标机器：

1. 启动 Worker，将 ZIP 复制到页面显示的迁移目录，填写 **ZIP 文件名**，不是 `C:\...`。
2. 后台验证逐文件 SHA-256、数据集／知识库身份、依赖、镜像标签／知识库冲突和空间，并显示进度。通过后确认可信来源再导入。
3. 导入重新核对 ZIP 未变，在隔离目录验证 Git 对象和 Docker/OCI 内容，再加载镜像。包内标签不能直接覆盖生产标签；不同 ID 标签会阻止导入。`repo@sha256:...` 引用通过导入记录映射到验证过的本地 ID。目标 Docker 需支持相应镜像格式和架构。
4. 单独配置 API 环境变量，选离线准备方案再次自检。新实验再选择导入的用例、知识库和方案，之后才调用真实模型。

操作进持久队列，提供阶段日志。暂存空间估计较保守，可能需要资源体积数倍；自动清理本次暂存文件，保留输入和最终 ZIP。重启后中断的适配／导入标为失败，不静默重放，人工检查后重试。Docker 与 SQLite 没有跨系统事务：中途失败时已加载的部分镜像可能保留，不自动删除可能在使用的镜像。已有实验和不同内容的资源不会被故意覆盖。

## Acceptance / English summary

The workbench adds versioned non-secret company profiles, isolated image builds, no-Agent custom dataset self-tests, and verified portable custom-dataset ZIPs. Profiles are explicitly applied to new experiments and frozen there. Proxy rules are exported, not hot-applied. API values stay in Worker memory and remain allowlisted.

`scripts/container-intranet-smoke.py` adapts a uniquely tagged image, checks baseline/reference tests, exports a baseline/image/context, imports into a fresh Worker after removing only its owned image, disconnects the original repository, and repeats tests with downloads forbidden. It checks parent/future history and hidden tests do not enter solver inputs. No model calls or production alias changes.

Remaining boundaries: official SWE/CTX dynamic dependency closure, LFS/submodule vendoring, complete database/constraint backups, Agent protocol certification, build-secret mounts, interactive debug containers, large arbitrary host contexts, automated Git credentials and dynamic proxy deployment are not implemented here. Image recipes are separate JSON exports, not automatically bundled.

# Standard dataset downloads / 标准评测集下载

These are the two full upstream snapshots linked by CTXBench Desktop v0.1.4+, not demo subsets. Verified on 2026-09-07. Their counts and checksums refer to the pinned revisions below, not a moving `main` branch. This guide is a download index, **not a dataset mirror or an offline runtime bundle**.

以下为桌面 v0.1.4 起提供入口的两份官方完整快照，不是演示子集。任务数和校验值绑定下列固定 revision；核验日期为 2026-09-07。此文件可作为 Release 的下载索引，但它**不包含数据本体，也不是完整离线运行包**。

## CTXBench（原 AGENTBench）

- [Official dataset / 官方页面](https://huggingface.co/datasets/eth-sri/agentbench)
- [Download pinned Parquet / 下载固定版本数据](https://huggingface.co/datasets/eth-sri/agentbench/resolve/82c4b95db706965e82736ef5fe8404be3c0f79ba/data/train-00000-of-00001.parquet?download=true)
- Upstream ID: `eth-sri/agentbench`; split: `train`; **138 tasks**, approximately **7.69 MB**. `train` is the upstream split name, not an instruction to train the agent.
- Revision: `82c4b95db706965e82736ef5fe8404be3c0f79ba`
- Downloaded filename: `train-00000-of-00001.parquet`; suggested Worker filename: `agentbench.parquet`.
- SHA-256: `a5df3bc98d8a9eed9c5c07a9aed63821c86f212c319e9d4b8623b4dfd6fd0832`

## SWE-bench Verified（人工验证版）

- [Official dataset / 官方页面](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified)
- [Download pinned Parquet / 下载固定版本数据](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/c104f840cc67f8b6eec6f759ebc8b2693d585d4a/data/test-00000-of-00001.parquet?download=true)
- Upstream ID: `princeton-nlp/SWE-bench_Verified`; split: `test`; **500 tasks**, approximately **2.10 MB**. This is Verified, not the original full SWE-bench or SWE-bench Lite.
- Revision: `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`
- Downloaded filename: `test-00000-of-00001.parquet`; suggested Worker filename: `swebench-verified.parquet`.
- SHA-256: `a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd`

## 下载与内网导入

以下是当前开发版新增的本地文件导入流程，需要同步更新桌面和本地评测服务镜像。已发布的 v0.1.5 尚未包含这项改进；旧服务会提示先升级，不要求用户退回手动复制。

1. 在联网电脑点击对应的 **下载固定版本 Parquet**。下载的是文件，不是网页或 Git LFS 指针。
2. 内网使用时，把文件传到内网 Windows 电脑的“下载”或任何普通文件夹。**不用复制到 WSL／Docker，不需要 sudo，不需要改名或转换格式。**
3. 在 **设置 → 运行环境** 启动本地评测服务。Parquet 解析需要已安装匹配的官方评测执行器镜像；四镜像离线包已包含该镜像，不需要模型密钥。
4. 打开 **评测集 → 导入评测集**，选择 CTXBench 或 SWE-bench 来源，从文件选择器选择下载的 `.parquet`。也支持 `.json`、`.jsonl`，单文件上限 32 MiB。
5. 点击 **检查所选文件**。软件自动传递文件、解析用例并显示数量和校验结果。正确的固定快照分别为 138 和 500 个用例，SHA-256 应与上方一致。
6. 点击 **确认导入评测集** 后才会保存到评测集列表。检查结果一小时后失效，服务重启后需重新检查。文件原件不会修改。

导入成功仅代表任务定义可用，不代表代码仓库、依赖和测试环境已准备，也不会执行 Agent 或调用模型。下一步可在该评测集卡片点击 **安装项目镜像**，预先下载所选用例对应的镜像；内网还需要另行准备基线代码与额外依赖。

### 项目镜像下载（当前开发版）

两个标准评测集都提供镜像或镜像引用，但不是“一份数据文件加一个通用镜像”：

- **SWE-bench Verified**：官方 Docker Hub 的 `swebench/sweb.eval.x86_64.<用例 ID>:latest`，用例 ID 中的 `__` 换成 `_1776_`。例如 `swebench/sweb.eval.x86_64.sympy_1776_sympy-12489:latest`。评分端使用官方镜像；上游 CTX 实验对于 matplotlib 的编码环境使用 `tgloaguen` 兼容变体，软件会把两者分别列出，不混为同一个镜像。[上游评分器说明](https://www.swebench.com/SWE-bench/reference/harness/)
- **CTXBench**：原始数据的 `docker_image` 字段指定项目镜像，常见为 `tgloaguen/planbenchx86_<组织>_<项目>:latest`，不同用例可共享一个镜像。还需在精确基线执行数据中的依赖准备步骤，镜像下载成功不等于测试已通过。[作者的运行说明](https://github.com/eth-sri/agentbench/blob/main/src/agentbench/README.md)

操作：**评测集 → 已登记评测集 → 安装项目镜像 → 选用例 → 确认安装镜像**。

- 默认只选第一个用例，可搜索、逐条选择或选中筛选结果；镜像清单自动去重，无须自己填写名称。
- 检查已有镜像只访问本机 Docker；安装时只拉取缺失项，保留已安装版本，不强制更新已有标签。
- 安装前弹窗确认；展示总镜像数、已安装数、待下载数和存储提示。总传输量未知，**不会拿 WSL 虚拟盘剩余空间冒充 Windows 宿主盘空间**。建议从少量用例开始，全量可能占用数百 GB。
- 持久队列显示镜像数量进度和 Docker 层下载/解压日志；无输出时显示等待提示，支持取消、重试及关闭窗口后重新查看。取消保留已完成镜像与缓存层，不执行清理命令。
- “已安装”只表示 linux/amd64 镜像存在，不代表依赖验证或测试已通过。此入口不会执行代码、克隆基线、生成知识库、运行 Agent 或调用模型。启动实验时才继续准备依赖、组合 Pi 项目环境并进行评测。
- 老版本服务没有此入口时明确提示更新配套镜像，不显示虚假的已安装状态。需同时更新桌面、评测服务和官方评分器镜像；尚未发布到 v0.1.5。

**内网**：可以导出清单，在联网机器安装并用 `docker save` 导出相应项目镜像，在目标 WSL 中 `docker load` 后保留清单标签，软件即可识别；或由公司配置 Docker 镜像加速/代理。项目镜像包不包含完整 Git 基线、所有额外依赖和应用镜像，因此不能把它称为“官方评测集完整离线包”。当前整套可搬运资源包仍只支持已封闭依赖的自定义评测集。

### Official project images (development build)

After importing the downloaded file, open **Datasets → Registered datasets → Install project images**. Select tasks, review deduplicated local/missing image references, then explicitly confirm installation. Only the first task is selected by default. Local tags are reused without updates; the downloader is cancellable and logs real Docker layer events. Overall percentage counts completed images, not transferred bytes. No model, repository checkout or evaluator command runs during installation.

SWE-bench uses per-instance Docker Hub images; CTXBench supplies per-project references in `docker_image` plus baseline-specific setup steps. The four application images are separate. Downloading project images is **not** an offline-readiness or test-pass guarantee. Preserve image tags when moving archives into the selected WSL Docker engine, and provision exact repositories and remaining dependencies separately.

**Harness compatibility:** the original pinned `princeton-nlp/SWE-bench_Verified` snapshot uses the v4 schema. The official harness now pins SWE-bench **v4.1.0 / `726c5461e2ef52d83cf1ea2107870a8bb3328d57`**, instead of the v5 commit that requires `eval_script`, `log_parser`, `eval_type` and `image` fields absent from this snapshot. Grading explicitly uses `namespace=swebench`, `cache_level=instance`, `clean=False`, `force_rebuild=False` so installed official instance images are reused and retained. This does not silently upgrade existing experiments' frozen harness IDs.

“包含参考修复和测试材料”是正常内容说明，**不是报错**。这些评分资料不会进入被测 Agent 或知识库生成程序的输入。

### 本地评测服务和数据目录

本地评测服务就是本软件保存数据、运行隔离测试的后台程序，技术日志中称为 Worker。用户无需手动管理其内部文件。

默认 `/var/lib/ctxbench` 是服务数据目录，不是 root 家目录 `/root`，但通常由服务账户管理。直接复制需要 sudo 不代表数据只能放在那里。高级部署支持 `CTXBENCH_HOST_DATA_DIR` 指定其他 WSL 目录，包括专用的用户目录；容器内部仍使用 `/var/lib/ctxbench`。修改挂载路径**不会迁移旧数据**，必须先暂停任务、停止服务、备份并校验迁移，再切换配置；不要删除旧目录或递归开放权限。日常导入用文件选择器，不需要更改目录权限。

The current development version supports **Datasets → Import dataset → select local Parquet/JSON/JSONL → Check selected file → Confirm dataset import**. The app transfers bounded file bytes to the local evaluation service over loopback, checks the task schema, and returns a public preview without reference patches or hidden tests. No manual Docker/WSL copy, sudo, renaming, Provider credential, or model call is required. Both desktop and service images must be updated; v0.1.5 predates this workflow. Task environment preparation remains separate from dataset import.

## Release 与许可 / Release and redistribution

目前本项目 Release 不包含这两个数据集的镜像附件。SWE-bench 上游仓库说明其代码和数据采用 MIT 许可；CTXBench 的评测工具仓库采用 MIT 许可，但此处核验的 Hugging Face 数据卡没有明确的数据再分发许可字段。不能仅凭工具代码许可推定所有数据材料的再分发条件。公开分发数据本体前应确认适用许可、第三方仓库条款及应保留的声明；本次仅提供官方链接及固定快照索引。

Sources: [SWE-bench citation and license](https://github.com/SWE-bench/SWE-bench#-citation--license), [CTXBench harness](https://github.com/eth-sri/agentbench), [CTXBench pinned dataset card](https://huggingface.co/datasets/eth-sri/agentbench/blob/82c4b95db706965e82736ef5fe8404be3c0f79ba/README.md).

The desktop project's license does not relicense upstream datasets. A future mirrored dataset asset should preserve source revision, all applicable notices and checksums, and remain separate from the installer and Docker image ZIP. This guide may be linked from Release notes without redistributing dataset contents.

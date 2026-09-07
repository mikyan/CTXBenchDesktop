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

1. 在能访问 Hugging Face 的电脑下载对应 Parquet；不要下载 Git 仓库中的 LFS/Xet 指针，也不要只复制网页可见行。
2. 复制到内网后，核对 SHA-256。Windows 可用 `Get-FileHash -Algorithm SHA256 -LiteralPath 'D:\下载\文件名.parquet'`，WSL 可用 `sha256sum -- '/mnt/d/下载/文件名.parquet'`。替换为真实路径。
3. 安装/启动同版本 Worker，并确认 `ctxbench/official-harness:0.1.0` 镜像已在本地。Parquet 解析由此镜像在容器中执行；只启动桌面前端还不够。
4. 在所选 WSL 内，将文件复制到 Worker 数据挂载目录的 `datasets` 子目录。标准部署默认 `/var/lib/ctxbench/datasets`；自定义 `CTXBENCH_HOST_DATA_DIR` 时使用其实际宿主路径。使用文件管理器或复制工具即可，不要覆盖已有同名数据；可用新文件名并在导入时填写。
5. 打开 **实验 → 导入数据集**，选择对应来源；在“Worker 数据集目录中的文件”填写下载文件名，或上面的建议名称（如果已重命名）。这里不是 Windows 文件路径。界面连接 Worker 后显示实际容器目录供对照。
6. 导入冻结的是任务定义，**不是**完成评测环境准备。还需迁移或准备基线仓库、用例镜像、依赖和评分环境；数据里的镜像名称不代表镜像已下载。知识库须另行生成/导入。

JSON/JSONL 可以直接从导入窗口选择本地文件，但上述官方快照是 Parquet；更改后缀不等于格式转换。下载两个文件时保留不同名称，来源选择也必须匹配。定义中包含参考修复、PR 及测试材料，仅供评测端使用，不能整包给知识库生成器或求解 Agent。

Download on a connected computer, verify SHA-256 after transferring internally, and copy each intact Parquet into the selected WSL Worker's datasets mount. Default host location is `/var/lib/ctxbench/datasets`; customized deployments may map it elsewhere. Start the Worker and make the official-harness image available locally. In **Experiments → Import dataset**, select the corresponding source and enter the actual filename relative to its datasets directory. JSON/JSONL uploads are also supported, but Parquet must not simply be renamed. Task definitions do not include baseline repositories, Docker layers or prepared dependencies. Never pass evaluator-only dataset contents to builders or solvers.

## Release 与许可 / Release and redistribution

目前本项目 Release 不包含这两个数据集的镜像附件。SWE-bench 上游仓库说明其代码和数据采用 MIT 许可；CTXBench 的评测工具仓库采用 MIT 许可，但此处核验的 Hugging Face 数据卡没有明确的数据再分发许可字段。不能仅凭工具代码许可推定所有数据材料的再分发条件。公开分发数据本体前应确认适用许可、第三方仓库条款及应保留的声明；本次仅提供官方链接及固定快照索引。

Sources: [SWE-bench citation and license](https://github.com/SWE-bench/SWE-bench#-citation--license), [CTXBench harness](https://github.com/eth-sri/agentbench), [CTXBench pinned dataset card](https://huggingface.co/datasets/eth-sri/agentbench/blob/82c4b95db706965e82736ef5fe8404be3c0f79ba/README.md).

The desktop project's license does not relicense upstream datasets. A future mirrored dataset asset should preserve source revision, all applicable notices and checksums, and remain separate from the installer and Docker image ZIP. This guide may be linked from Release notes without redistributing dataset contents.

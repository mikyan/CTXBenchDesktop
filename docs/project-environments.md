# Project build environments / Agent 项目构建环境

## 中文

新建实验与独立“生成知识库”默认开启“为知识库生成和编码准备项目依赖”。**不再默认让 Agent 在只有 Pi 的基础镜像里处理所有代码仓。**

1. 官方 CTXBench 用例先按基线安装步骤准备项目依赖；SWE-bench 使用对应实例的项目镜像；自定义用例使用所选测试镜像或基线 Dockerfile。
2. 从依赖镜像导出文件系统，移除旧仓库、Git 历史、常见评测材料与缓存，再从空镜像构建，避免继承旧镜像层里的代码和答案。
3. 从已安装的新版 Pi 镜像复制适配器，离线校验 Node、Pi、Git、ripgrep、Bash 与运行账户权限；不会临时下载另一份 Pi。项目本身的 Node/Python 版本保持不变。
4. 只有环境准备成功，才开始知识库生成或编码。界面显示准备阶段及 Docker 构建输出；失败可在处理镜像问题后重试。
5. 按仓库、完整基线提交、依赖镜像摘要、Pi 镜像摘要及准备协议生成缓存键。独立生成、整批准备、重启恢复及重复评测复用匹配的环境；两个对照分支始终使用同一个镜像摘要。

知识库仍只是基线旁的被动文档，不会增加读取提示。目标任务提示词不传给知识库构建器；参考修复、隐藏测试和挖掘约束仍只给评测端。自定义评分可以复用清理后的依赖镜像，但使用独立的测试入口，不启动 Pi、不传入模型密钥，也不开放网络。官方评分继续使用其独立适配流程。

### 使用与更新

- 同时更新桌面端、本地评测服务镜像和 Pi 镜像。旧服务不能静默忽略新选项；旧 Pi 镜像缺少协议标签时会在模型调用前报出更新指导。
- 旧实验保留原来的环境方式，不会自动改变已冻结的计划。要采用此功能，请新建实验。
- “先统一生成知识库、稍后执行评测”仍可使用：准备阶段也会冻结对应 Agent 项目环境。
- 首次合成会临时保存较大的文件系统归档，随后缓存新的项目镜像。检查 WSL 可用空间，也要检查承载 WSL 虚拟磁盘的 Windows 分区；WSL 显示的虚拟容量不是 Windows 的真实剩余空间。

### 自定义镜像与内网

这不是一个自动猜测任意项目依赖的安装器。Python 包、编译器、JDK、数据库客户端等，仍需由用例的测试镜像或基线 Dockerfile 明确提供。四个应用基础镜像不是万能项目环境。

推荐把依赖安装在 `/opt/venv` 等绝对路径并配置 `PATH`。自动准备也支持把项目工作目录下的 `.venv`、`venv`、`node_modules` 搬到隔离目录，并在运行时恢复相同的路径，避免 `/workspace` 挂载遮挡依赖。依赖链接不进入补丁或知识库；如果基线中跟踪了同名目录，会明确失败。其他自定义依赖目录需自行放到仓库外。向导的基线/参考自检直接测试原测试镜像，因此仍建议使用仓库外的依赖路径。

目前自动组合支持带新版协议的 Pi 适配器，以及能运行其 Node 二进制的 Linux 项目镜像。镜像必须有专用工作目录，不支持声明 `VOLUME` 的镜像；缺少 Git/Bash、CPU 架构不一致、系统库过旧等情况会失败并保留诊断，不会回退成缺依赖的 Pi 基础环境。需要系统安装权限的操作应提前在镜像适配阶段完成，Agent 仍以非 root 用户运行。

公司其他 Agent 可关闭推荐选项，使用“直接使用 Agent 镜像（高级）”：自行提供已经含项目依赖、符合适配协议的 Agent 镜像。已有启动命令、多提示词步骤、环境变量白名单照常使用。

离线使用时先导入对应依赖镜像、Pi 镜像及基线代码；官方 CTXBench 还需要准备好的基线依赖镜像。匹配缓存的组合过程无网络下载。自定义评测集资源包会自动纳入本机与基线匹配的已准备 Agent 镜像及其 Pi 适配镜像；在目标环境导入后可复用缓存。资源包 v1 **仍只支持已有测试镜像的自定义数据集**，不是所有官方数据依赖的一键打包器。

镜像来自可信、已审查的来源是前提。自动清理覆盖已知仓库和评测路径，不能证明任意第三方二进制、安装包或未知目录中都没有答案、隐藏测试或密钥；自定义镜像作者必须保证依赖本身干净。不要把目标修复打进 site-packages、其他安装目录或基线 Dockerfile。

## English

New experiments and independent context generation enable project preparation by default. One shared preparation module resolves baseline-specific dependencies, exports and sanitizes the merged filesystem, composes an installed Pi adapter **FROM scratch**, validates its tools offline and caches the result by repository, baseline and immutable image identities. Builders and paired solvers use the same frozen project image; grading remains separate. No model is called during environment preparation.

Update the desktop, service and Pi images together. Legacy plans keep their original mode. Custom datasets must supply their own runtime/compiler/test dependencies through a test image or baseline Dockerfile; missing dependencies are not inferred. Prefer dependency paths outside `/workspace`. The composer can relocate `.venv`, `venv` and `node_modules` from the original working directory, restoring their locations in fresh containers without changing the graded patch. Agents remain non-root. Other company Agents can explicitly choose as-is mode with their own project-capable adapter.

Official instance images, compatible Linux libraries, adequate WSL **and Windows backing-volume** space, and trusted image contents remain prerequisites. Unknown embedded answers or secrets cannot be made safe by a filename filter. Custom resource bundles include matching prepared Agent images and adapters; portable v1 still does not close official datasets' dynamic dependency graphs.

## Verification

本轮验收结果与已确认的上游限制见 [2026-09-08 验证记录](project-environments-verification.md)。

`scripts/project-environment-smoke.py` runs inside an isolated service-image container with this repository mounted read-only at `/source`, a fresh `/tmp/ctxbench-project-test-*` directory mounted at the same path, and the Docker socket. It reuses the installed Pi package and copies current adapter sources into a separate verification image; installed application tags and production services are not changed. Use `--root` for the isolated directory. Keep checkouts on a Linux filesystem for ownership/symlink support. The isolated directory's `project-environments` subdirectory may be separately bind-mounted from another volume for large temporary archives; Docker's own layers still consume space in its data root.

The default case checks real dependency availability, source/history removal, one mock builder plus four paired mock solvers, restart/cache reuse and reference-fix grading. `--official-image IMAGE --compile-path DIRECTORY --test-command-json '["python", "-m", "pytest", "-q", "tests/visible_test.py"]'` additionally checks compilation of the image's real baseline source and the selected visible dependency test. Select the project's own test runner (e.g. SymPy's `python bin/test`); pytest is not assumed to exist in every project. These are container/runtime acceptance checks with **zero Provider calls**, not official benchmark scores or evidence of real-model problem-solving quality.

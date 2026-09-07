# Desktop setup and troubleshooting / 桌面安装与故障排查

## 中文

WSL、发行版、Docker Engine 三项通过，只说明基础环境就绪。CTXBench Worker 是单独的容器服务，须准备镜像、启动服务并通过 `http://127.0.0.1:48173/v1/health` 的健康检查。此阶段不需要模型密钥，不会启动评测或调用 Provider。

在 **基础设施 → 安装并启动工作节点** 中：

1. 选择正确的 WSL2 发行版。Docker Engine 与 Compose 插件均须安装在这个发行版中。
2. 选择镜像准备方式。内网模式默认不显示构建按钮；Windows 安装包只包含部署源码，不包含 Docker 镜像。
3. 内网安装：在外网下载同一版本的全部 `ctxbench-images-*` 附件，在所选 WSL 中进入镜像文件夹，依次执行页面中的校验、验证、导入命令。命令要求 Python 3.10+ 和 Docker；请使用公司认可的安装来源。导入不会自动启动服务。替换已有镜像前应先暂停实验并停止相关服务。
4. 点击 **检查启动条件**。依次确认部署文件、Compose、四个应用镜像和 WSL 数据目录。缺少数据目录时，手动命令区会生成针对实际目录的创建命令，不会自动删除或修改已有数据。
5. 点击 **启动工作节点**。启动明确使用 `--no-build --pull never`，不会隐式联网构建或下载。只有 Windows 端健康检查通过才提示启动成功。
6. 成功后再配置 Agent 环境变量、评测集和基线资源。离线应用镜像不包含数据集、基线仓库或用例测试镜像，详见 [离线镜像说明](offline-images.md)。

### 在线构建进度

选择 **可联网 / 构建镜像 → 构建镜像** 后，会持续显示当前构建步骤、进度条、已耗时、最近输出时间和脱敏日志。Docker 报告镜像层传输字节数时，还会显示该层的下载进度。步骤总数是构建过程中逐步发现的，可能增加；这不是整体耗时百分比，也不预测剩余时间。只有构建命令成功退出后才显示完成。

超过 30 秒没有新输出会出现排查提示，但不会直接判定卡死或自动重试。部分依赖安装步骤输出较少；持续无变化时可检查网络、镜像源和磁盘空间。失败后保留日志及处理建议，修复原因后可重新点击构建。命令超时或连接中断不保证 Docker 的后台工作已停止，重试前先检查状态。

可关闭自动跟随来阅读较早输出，也可复制当前保留的日志。为限制内存占用，界面只保留最近最多 500 行、100,000 个字符（先达到哪个上限就截断）；原生层会在传入界面前脱敏并限制缓存大小。保持桌面应用开启时，切换页面再回来仍可查看构建；这些日志不落盘，重启应用或再次构建会清空。此行为与持久化 Worker 的实验日志不同。

### 文件路径与命令

安装版使用 `软件安装目录\deployment\docker\compose.yaml`；开发版使用仓库内的 `docker/compose.yaml`。正确后缀为 `.yaml`，不是 `.yml`。不要只移动 exe，部署目录必须随完整安装包保留。

**手动命令与故障排查** 会显示 Windows 路径及其对应的 WSL 绝对路径，并分别提供 Windows PowerShell、所选 WSL 终端两种命令。按你选择的终端复制即可，不依赖当前工作目录。不能确认路径时不会生成猜测的相对路径命令。

### 常见故障

| 提示 | 下一步 |
| --- | --- |
| 找不到部署文件 | 检查安装目录中的 deployment 文件夹；重新安装完整桌面包，不是重装 WSL。 |
| Docker Compose 不可用 | 安装 Compose 插件；Engine 检测通过不代表插件也已安装。 |
| 缺少镜像 | 在同一个 WSL 发行版导入同版本镜像，或在联网模式先构建。 |
| 数据目录不可用 | 按页面显示的真实路径创建目录或修正挂载，勿删除原实验数据。 |
| 访问权限不足 | 检查 Docker 套接字和目录访问权限；勿使用 chmod 777 或关闭安全防护。 |
| 端口 48173 被占用 | 先识别占用进程/容器，不能直接停止无关服务。 |
| 容器已启动但无法连接 | 查看容器日志；若容器运行正常，排查 Windows 到 WSL 的 localhost 转发。 |
| 操作超时 | 先检查容器状态和日志，再决定重试；超时不等于后台操作已停止。 |

错误会保留在页面中，包含处理建议及脱敏后的技术详情，可复制诊断报告。仍应在分享前检查内容；不要上传 `.env`、密钥值或未脱敏的完整配置。停止 Worker 不会删除数据，但应先暂停活动实验。

旧版 `v0.1.0` 独立离线 Compose 文件可能带有 CI 构建机目录前缀；本次修正打包脚本，使之后生成的文件保留可移植路径。已发布附件未被静默替换。旧包完成镜像导入后，可以使用桌面安装目录内的 `deployment/docker/compose.yaml` 启动，而不是旧的独立离线 Compose 文件。

## English

Online **Build images** streams redacted stdout/stderr, current operations, elapsed time and time since the last output. The progress bar counts completed versus discovered BuildKit steps (the total can grow), not estimated time. A separate layer-transfer bar appears when Docker reports byte counts. Only a successful command exit marks the build complete. A 30-second silence warning is informational, not automatic cancellation or retry. After a timeout or connection loss, inspect Docker before retrying: background work may still be running.

Logs support auto-follow and copy, retaining at most 500 recent lines / 100,000 characters in memory. Native output is also bounded and redacted before reaching the UI. Navigation away and back retains the build while the app remains open; restarting the app or starting another build clears this session-only log. This is separate from persistent Worker experiment logs.

WSL and Docker readiness do not imply that the CTXBench worker is installed. In **Infrastructure → Install and start the worker**, select one WSL2 distribution, prepare the matching images, check prerequisites, and start the worker. Docker Engine and the Compose plugin must both be available in that distribution. No Provider key is required for setup.

The default offline path guides verification/import of the separate image bundle. Online builds are an explicit alternative. Startup uses local images only (`--no-build --pull never`) and reports success only after Windows can reach the worker health endpoint. Missing files, Compose, images, data mounts, permissions, port conflicts and unreachable workers have distinct next steps and redacted technical details.

The installed Compose file is `<installation directory>/deployment/docker/compose.yaml`. Manual commands use detected absolute paths and can be copied for either PowerShell or the selected WSL shell. Do not move only the executable, guess relative paths, or change `.yaml` to `.yml`. Read container logs and copy the limited diagnostic report for support; review it before sharing and never include credentials or `.env` files.

Pause active experiments before stopping or replacing a worker. The application image bundle does not include datasets, baseline repositories or task-specific test images. Older `v0.1.0` standalone offline Compose files can include a CI-host path prefix; the exporter is now corrected for future bundles, without modifying already-published assets. After importing old images, use the desktop's bundled Compose file instead. See [offline images](offline-images.md).

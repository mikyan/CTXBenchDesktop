# 使用公司镜像和自己的 Agent

v0.1.7 提供。需同时更新桌面端和本地评测服务镜像；不要在实验运行中强制重启服务。自定义编码命令由服务提供适配器，无需在自己的镜像里安装 Pi 或编写 CTXBench 结果协议。

## 先分清三个配置

| 配置 | 在哪里设置 | 负责什么 |
| --- | --- | --- |
| 自定义 Agent 镜像和启动命令 | 创建／编辑评测用例 → 任务与测试 → 编码 Agent | 接收 Prompt，在代码仓中修改代码 |
| 测试镜像和测试命令 | 同一用例的仓库环境、测试设置 | 在独立容器中测试候选代码，决定是否通过；也可选择远程 CI 门禁 |
| 镜像制作时的安装命令 | 设置 → 镜像适配 | 安装 Agent、语言工具、依赖，修改镜像默认配置；构建一次，多次复用 |

Agent 镜像与测试镜像可以使用同一标签，前提是它同时具备两种用途所需的工具。测试成功必须由独立评分器确认，Agent 自己退出 0 不算用例通过。知识库生成和约束相关角色仍使用实验中原有的 Agent 配置，**用例中的命令只替换编码角色**。

## 1. 已有公司镜像：直接下载

打开 **设置 → 镜像适配 → 拉取现成镜像**。用例的测试镜像选择器和自定义 Agent 镜像旁边也提供相同入口。

1. 启动“运行环境”中的本地评测服务，确认使用正确的 WSL 发行版。
2. 填写完整镜像地址，例如 `harbor.company.example/team/backend-agent:2026.09`。这个通用入口填写镜像名，不粘贴 `docker pull` 命令。
3. 确认信任来源并允许磁盘占用，点“下载镜像”。可查看分层下载日志、取消及重试；解压阶段没有可信百分比，因此不会显示虚假的进度数字。
4. 下载完成后，使用返回的标签选择或填写测试／Agent 镜像。

支持 Linux amd64 镜像，以及带 `@sha256:…` 的远端内容摘要。拉取不会启动镜像、不调用模型。本地已有同名标签会直接复用，不覆盖；需要新版时，填写新版本标签或摘要。填写完整公司仓库地址时不会改去 Docker Hub 下载。

**私有仓库认证**目前需在软件选定的同一 WSL 发行版里执行 `docker login 公司域名`，然后 `docker pull 完整镜像名`，再回软件刷新。WSL 登录状态不会自动传给评测服务容器，模型 API Key 也不是镜像仓密码。无需复制文件到容器，不要把密码放在镜像地址中。

官方 SWE／CTX 用例的逐镜像地址替换仍使用原来的“安装项目镜像”页面，见[公司镜像仓库说明](company-image-registry.md)。不要用任意公司基础镜像冒充对应的官方项目环境。

## 2. 镜像缺工具：四步制作

打开 **设置 → 镜像适配 → 一步步制作自己的镜像**：

1. **选择基础镜像**：填写方案名称和已经下载的本地基础镜像。优先使用公司已有的语言运行环境。工具已安装时可直接选这个镜像，安装命令留空，只做默认 HOME 的权限适配，无需再次下载软件。
2. **安装依赖**：填写 Shell 命令，可追加 Python、Node.js、Java／Maven、自定义 Agent 必备工具模板。模板不会知道公司实际包名和网址，必须修改占位内容。这里只填命令，不写 `FROM` 或 `RUN`。
3. **添加默认配置**：上传不含凭据的配置文件，填写每行一个 `NAME=value` 默认环境变量。文件会先复制到 `/opt/company/文件名`，再执行上一步命令，因此可用 `cp`、`sed` 调整 `/etc` 等位置的默认配置。
4. **检查构建方案**：检查 Dockerfile 和构建网络，点“将方案填入构建表单”，然后在下方表单明确确认并构建。安装包需要联网时选择允许联网，并使用公司的源地址；离线模式要求基础镜像或上传材料已经备齐。

构建以本地基础镜像的内容 ID 为起点，产出新的 `ctxbench/adapted:…` 标签，不修改原镜像。成功后把新标签填入用例，先跑小用例验证，再使用已有的镜像导出／打包入口带到其他机器。

### 安装依赖示例

下面是 **Debian／Ubuntu 系、已有 Node.js 的镜像**示例。其他系统需使用相应包管理器；纯 distroless 镜像通常还缺少本功能所需的 Shell、Python、Git。

```sh
apt-get update
apt-get install -y --no-install-recommends python3 git ca-certificates
npm install --global YOUR_AGENT_PACKAGE --registry=https://npm.company.example
```

`YOUR_AGENT_PACKAGE` 和域名均为占位符，替换成公司实际内容并固定版本。若基础镜像也无法访问 apt 源，先按公司的要求配置系统软件源，或换成已装好这些工具的内部基础镜像。

Python 项目可以创建固定路径的虚拟环境：

```sh
python3 -m venv /opt/venv
/opt/venv/bin/pip install --no-cache-dir --index-url https://pip.company.example/simple pytest
```

基础镜像须提供 `venv`；项目实际依赖应一起安装并固定版本。测试命令可直接写 `/opt/venv/bin/python -m pytest -q`，避免依赖交互式 Shell 的激活状态。

### 修改默认配置示例

上传不含令牌的 `settings.json`，设置镜像默认环境变量：

```text
HOME=/home/ctxbench
LANG=C.UTF-8
MY_AGENT_CONFIG=/opt/company/settings.json
```

如果 Agent 要求固定的 `/etc/my-agent/settings.json`，在“安装依赖、修改配置的命令”中追加：

```sh
mkdir -p /etc/my-agent
cp /opt/company/settings.json /etc/my-agent/settings.json
chmod 644 /etc/my-agent/settings.json
```

Maven 可同样上传无凭据的 `settings.xml`，测试命令指定 `mvn -s /opt/company/settings.xml test`。这只配置源，不会自动下载项目依赖。**本地评分阶段无网络，也没有 Agent 的 API Key**，Maven 缓存、npm 包、Python 依赖等仍需预先准备到测试镜像中 UID 10001 可读的位置。

### 目录、用户和密钥

- `/workspace` 会被本次基线代码覆盖，不能把唯一的一份依赖、默认配置或 Agent 程序只放在那里；使用 `/opt`、系统路径或可用的 HOME。
- 容器以 `10001:10001` 运行，即使镜像默认用户为 root。向导在**所有安装与配置完成后**将默认 `/home/ctxbench` 目录树交给该用户，并用 UID 10001 检查顶层访问；因此 root 安装／版本检查新建的默认 HOME 子目录也被包含。不会递归跟随符号链接，HOME 根或 `/home` 为符号链接时拒绝构建。这个探针不代表所有 Agent 功能已通过测试。
- 其他 HOME、外部缓存或配置路径不会被自动递归修改，需要在自己的方案中保证 UID 10001 所需的读取、执行、写入权限。适配器仅在 HOME 顶层不可写时使用临时 HOME；顶层可写但深层目录不可写不会触发此回退。不要通过 root 运行或全局放宽权限绕过。
- 权限适配也会生成新镜像标签，原镜像和历史实验不变。将新标签选入用例后新建实验；重试旧快照不会自动换成新镜像。
- 镜像不要包含参考答案、隐藏测试、历史会话、登录状态和 API Key。不要把完整任务代码仓打进通用 Agent 镜像，避免基线和评测材料泄漏。
- API Key 在软件的“运行时环境变量”中配置，再在实验中选择允许传入的变量名；不要写到构建命令、ENV、配置文件或用例命令中。需要构建期私有包认证的情况，当前向导没有 BuildKit secret 入口，请使用公司安全构建流程产出的基础镜像。

## 3. 用自己的 Agent 执行用例

在 **评测用例 → 创建／编辑 → 任务与测试 → 编码 Agent** 中选择 **执行我自己的 Agent 命令**，填写镜像和命令。

工具把每一步原始 Prompt 放进 `CTXBENCH_PROMPT_FILE` 指向的临时文件。以下是接口示意，需按你的 CLI 实际参数修改：

```sh
company-agent --model "$CTXBENCH_MODEL" --prompt "$(cat "$CTXBENCH_PROMPT_FILE")"
```

如果 CLI 支持从标准输入读取任务，可以使用：

```sh
company-agent --model "$CTXBENCH_MODEL" < "$CTXBENCH_PROMPT_FILE"
```

Shell 模式使用 `/bin/sh -eu -c`。也支持 JSON 参数数组；数组按字面传入，不自动展开 `$变量`、重定向或引号，需要这些功能时显式调用 Shell。`$(cat …)` 会去掉文件末尾的换行；若 CLI 支持文件参数或 stdin，优先直接传文件／重定向，保持提示词字节不变。

镜像必须安装自己的 Agent、`python3`、`git`、`/bin/sh`，并支持非交互式运行、完成后退出。镜像原有 `ENTRYPOINT` 和 `CMD` 会被命令适配器替换，**所有必要启动参数都写进用例命令**。命令在 `/workspace` 编码；适配器负责生成补丁、剥离知识库文件修改、提交给原有测试／CI 判分流程。它不插入知识库读取提示，也不控制 Agent 如何发现上下文。

实验的“评测求解编排”仍可配置启动前安装命令和多个独立 Prompt 步骤。自定义模式的启动命令共用 `/bin/sh`，使用 `. /path/to/activate` 而非 Bash 专属的 `source`。导出的变量传给后续步骤；不允许改动基线代码或知识库。每步启动新命令进程、共享工作区文件，工具不自动携带对话历史；是否复用 CLI 自身会话由命令和镜像决定。任一步失败／超时都会阻止后续步骤，不会当成测试通过。

### 模型配置与计费边界

环境变量 `CTXBENCH_PROVIDER`、`CTXBENCH_MODEL`、`CTXBENCH_THINKING`、`CTXBENCH_MAX_TOKENS` 提供实验中的配置值，自己的命令必须正确应用它们。工具无法从任意 CLI 验证其实际模型，也无法强制其 Token 上限。

自定义命令的 Token／费用显示为**未知，而非零**，缺少用量不影响执行、测试判分、通过率或配对比较。实验可以关联共享 Token 预算，但自定义命令阶段不预留、不扣账，也不因该预算耗尽而暂停；知识库生成、默认 Pi 求解、约束评估等可统计角色仍按原规则受预算保护。界面显示的 Token 总量和配置额度不包含自定义命令，不代表它们没有消耗，请在 Agent／Provider 侧设置消费限额。容器运行时长、CPU、内存及网络限制仍有效。自定义参数写在用例命令中，不使用实验全局 Pi 启动参数。只用自定义编码命令、关闭知识库生成和约束角色的实验，不要求安装默认 Pi 镜像。

用例保存与运行快照包含独立的 `agent: {image, command: string[]}`，与 `test.command`／`test.ci` 分开。排队时冻结用例定义，准备时固定镜像 ID 和适配器代码哈希；修改用例影响未来任务，不改变已有配对／重试。如果恢复时服务中的适配器已改变，会提示恢复匹配版本或新建实验，不会混用实现。自定义资源包也会收集用例引用的 Agent 镜像。

## 验证记录（2026-09-08）

- 前端当前源码 151 项测试通过，生产构建通过（保留已有的大分包警告）；后端 255 项测试中 253 项通过、2 项因 Windows 符号链接权限跳过。
- 中英文浏览器交互均通过：下载确认、失败与重试、四步镜像方案、配置上传、构建确认、自定义 Agent 与 Maven 测试命令独立保存。浏览器接口使用测试桩。
- 真实 WSL Docker 完成公开小镜像 `busybox:1.37.0` 的首次下载及缓存复用；用本地镜像构建未安装 Pi 的自定义 Agent 镜像，并安装／读取 `/etc` 默认配置。
- 实验 `exp-156cd5adcdb9` 的两个上下文分支，各执行两步命令，独立评分均通过；确认上下文修改不进入评分补丁、退出 17 保留失败、启动命令篡改基线／上下文被拒绝、编辑用例不影响原快照、适配器版本变化被拒绝。
- 该 Agent 是确定性验收程序，**没有调用真实模型、没有证明公司 Agent 已接通，也不构成知识库效果结论**。脚本为 `scripts/command-agent-container-smoke.py`；本机报告保存在 WSL `/tmp/ctxbench-command-wDSnsRih/summary.json`。

同日补充验证 Token 缺失不影响测试：关联已耗尽、且模型不同的共享预算，真实 Docker 中 `exp-496aa7c9b905` 两个分支测试通过，`exp-32da69c422ae` 两个分支按预期断言失败；四次运行均正常完成评分、用量未知、未产生自定义命令的预算扣账。报告位于 WSL `/tmp/ctxbench-command-9nSkg7JO/summary.json`。回归也覆盖可统计角色仍受预算保护、未知用量不影响通过率／配对指标，以及中英文界面保留自定义模型并允许带预算创建实验。

## English summary

v0.1.7: use **Settings → Image adaptation** to pull a complete Linux amd64 image reference or follow the four-step dependency/configuration recipe guide. Existing tags and base images are not overwritten. Registry authentication currently requires login/pull in the selected WSL distribution.

In **Evaluation cases → Task and tests → Coding Agent**, select a custom image and command independently of the grading image/command or CI gates. The image needs Python 3, Git, `/bin/sh`, and your non-interactive Agent, not Pi. The read-only service adapter replaces ENTRYPOINT/CMD, runs as UID 10001 in `/workspace`, exposes the prompt file and model settings via `CTXBENCH_*`, extracts candidate patches and delegates grading. Dependencies and defaults belong under `/opt`, `/etc` or a writable HOME; credentials are runtime-only.

The guide finalizes ownership of the fixed `/home/ctxbench` tree **after** all root installation/version checks, then probes top-level access as UID 10001. It rejects a symlink HOME or `/home` parent and does not follow child symlinks. Arbitrary HOME or external cache/configuration paths are never recursively changed: manage their permissions explicitly. A HOME probe is not a full Agent compatibility test. To adapt permissions on tools already installed, select that local image and leave dependency commands empty; no reinstall is needed. Select the newly built tag in the case and create a new experiment. Existing images, queued runs and historical snapshots do not change, and Agents never run as root.

This override applies to coding only. Each workflow step launches a new command; setup must not change baseline/context. Arbitrary CLI usage is unknown, not zero, and never gates execution or functional grading. Shared budgets may remain attached, but custom command stages bypass reservations/charges and exhaustion checks; metered roles retain their existing protection. Displayed token totals/allowances exclude custom commands, so use provider-side spending limits. Global Pi arguments remain unsupported for these commands. Cases, actual images and adapter code are frozen for reproducibility. The Docker acceptance uses a deterministic non-Pi fixture, not paid inference or an actual company Agent. See [adapter contracts](agent-adapters.md) for integrating additional roles or trustworthy usage reporting.

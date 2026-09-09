# 创建自己的评测集 / Authoring custom datasets

## 中文

v0.1.7 入口：**评测用例 → 创建评测用例**。先独立保存用例，再去 **评测集 → 组合评测集** 勾选已有用例。无需手写 JSON，也不会在保存定义时调用模型。[完整流程、编辑和快照规则](case-library.md)。

使用公司自己的 Agent 时，在“任务与测试 → 编码 Agent”选择 **执行我自己的 Agent 命令**，单独填写 Agent 镜像和命令，无需 Pi。它与判分用的测试命令不同。测试／Agent 镜像旁可直接拉取远端镜像；安装依赖和修改默认配置见[四步镜像制作及接入指南](image-workshop.md)。自定义命令只覆盖编码角色，Token 用量未知不影响执行或判分；关联的共享预算只保护可统计角色，自定义命令阶段跳过 Token 记账和额度检查。

自定义用例也可选择 **远程 CI 流水线门禁**，自动提交候选代码到 GitHub 并读取门禁／JUnit 统计；不再填写本地评分命令。[GitHub 操作步骤与安全要求](ci-grading.md)、[公司平台适配协议](ci-platform-adapter.md)。Agent 本身仍在本地 Docker 内编码，CI Token 不会传给它。

1. 填写**用例名称**，在 **仓库与环境** 填写 Git 地址、修复前的完整 40 位提交号，以及测试镜像或基线 Dockerfile。Gitee、公司内网 Git 均可；评测服务必须能访问仓库。不要在 URL 中嵌入凭据。仓库路径必须是服务容器可见的 Linux 路径。
2. 在 **任务与测试** 填写唯一任务 ID、给 Agent 的需求描述，以及判分用的测试命令。一个用例是一个独立编码问题；多个断言不等于多次 Agent 运行。重复次数在实验中配置。
3. 在 **检查并保存** 检查定义；提供参考修复后可另行执行容器自检。保存后用例卡片可直接“生成知识库”或“新建实验”，也可加入多个评测集。

### 一个具体的用例怎么设计

假设仓库 `names.py` 中的 `normalize_name` 忘记移除首尾空白。选定**尚未修复**的基线，任务描述可写：

> 修复 normalize_name：移除字符串首尾空白、保留内部空格，并正确处理空字符串。

在独立的用例编写工作区中编写 `tests/test_regression.py`：

```python
from names import normalize_name

def test_trim():
    assert normalize_name("  Ada  ") == "Ada"

def test_empty():
    assert normalize_name("") == ""

def test_internal_spaces():
    assert normalize_name("Ada Lovelace") == "Ada Lovelace"
```

测试命令填写 `python -m pytest -q tests`。模板只是填入常用命令，**不会自动创建测试文件或安装 pytest**。测试在隔离容器的 `/workspace` 中离线执行：退出码 0 表示通过，非 0 表示失败。断言必须能发现问题，不能只打印结果，也不能用 `|| true` 等方式掩盖失败。

测试镜像与 Agent 镜像是两个用途不同的配置，但**可以复用同一个合适的镜像**。前者执行测试，在此向导设置；后者运行编码 Agent，默认在实验配置中选择，也可在用例中用自定义镜像和命令覆盖。构建模式中的 Dockerfile 相对构建目录，构建目录相对仓库根目录，且 Dockerfile 必须存在于所选基线。不要向镜像写入密钥。

### 已经导入四个基础镜像，测试镜像怎么选？（v0.1.7）

向导会读取“设置 → 运行环境”所选 WSL 的本地镜像，支持下拉选择、刷新和手填内网标签／摘要。列表只确认镜像已安装，不证明测试兼容性。

| 基础镜像 | 用途与复用条件 |
| --- | --- |
| `ctxbench/agent-pi:0.1.0` | 自带 Node.js/npm、Python 3。可以运行无额外依赖的脚本或 Python 标准库测试；未预装 pytest 和项目依赖。 |
| `ctxbench/official-harness:0.1.0` | 官方数据导入和评分适配器，不是每个官方任务所需的项目测试环境。 |
| `ctxbench/worker:0.1.0` | 本地接口和任务调度，不建议作为项目测试环境。 |
| `ctxbench/egress-proxy:0.1.0` | 网络访问控制，不用于项目测试。 |

例如，仅依赖标准库的 Python 测试可选择 Pi 镜像，使用 `python3 -m unittest discover -s tests -v`。运行自定义测试时覆盖镜像启动入口，只执行测试命令，不启动 Pi、不调用模型、不传入 Agent API 密钥。需要 pytest 或其他依赖时，请先在“设置 → 镜像适配”制作专用镜像，或使用基线 Dockerfile 构建。

依赖请安装到 `/opt/venv` 等路径；评分时 `/workspace` 会被干净基线和待评测补丁的挂载遮盖。测试阶段无网络，不能临时联网安装依赖。不要把答案或隐藏测试打入共享镜像。最后一步可提供参考修复补丁并运行自测，确认基线因为行为断言失败、正确修复通过。

关闭有修改的用例或组合表单会居中弹出确认，包括只点击“从评测集移除”的修改。未提交表单不会自动保存。以前保存的多用例草稿可在“标准下载 → 旧版草稿导入（高级）”中恢复，旧向导的草稿版本、导出和恢复能力继续保留。

### 隐藏测试与参考修复

基线已有的测试文件对 Agent 可见。如果要保密，将新增断言打成补丁，填写到“隐藏测试补丁”。例如在独立编写工作区执行（把 BASE 替换为真实完整提交号）：

```bash
git add -N tests/test_regression.py
git diff --binary BASE -- tests/test_regression.py > hidden-tests.patch
```

`git add -N` 使尚未跟踪的新文件进入 diff；**不要把隐藏测试提交到基线**。检查补丁只含测试、不含答案和密钥，然后上传到向导。测试命令必须能发现新增文件；补丁路径需与对应基线一致。

可选的“参考修复补丁”是 gold patch，只供评测端保存。向导不会自动运行它。正式采用分数前，请在与评测一致的隔离测试环境里验证：

- 基线 + 隐藏测试：应因目标行为断言失败，而不是因为缺依赖或命令错误。
- 正确修复 + 同样的隐藏测试：应全部通过，同时保留必要的回归断言。
- 不同知识库分支使用完全相同的任务、测试、基线和环境；不得在提示词中加入知识库读取指令。

**定义校验不等于试跑通过**：这里只检查格式、完整提交号、ID 唯一性和环境配置，不检查仓库连通性、镜像存在性、补丁适用性或测试结果，也不消费模型 Token。约束挖掘、知识库生成和配对评测依然是独立流程。

用例和评测集均可继续编辑。启动任务入队前会按内容哈希创建不可变快照；恢复和重试都用原快照，采用编辑后的定义需新建任务。共享用例修改会影响所有引用它的评测集的未来运行。JSON 定义及旧版草稿导出可能包含隐藏测试和参考修复，属于评测端材料，不能作为知识库提供给 Agent。

新版实验会默认为知识库生成和编码准备项目依赖，不用再手动把 Pi 安装到每个测试镜像里。具体边界、缓存及内网说明见 [Agent 项目构建环境](project-environments.md)。

## English

Cases optionally override the coding image/command under **Coding Agent → Run my own Agent command**, independently of grading. Pi is not required for that image. See [remote images and guided recipes](image-workshop.md) for prerequisites, prompt/environment handoff, runtime credentials and unknown-token limitations. Other Agent roles retain the experiment configuration.

New experiments prepare project dependencies for builders and coding Agents by default. See [Project build environments](project-environments.md) for caching, offline use and compatibility limits.

v0.1.7: open **Evaluation cases → Create evaluation case**. Name the case, configure Repository and environment → Task and tests → Review and save. Run it directly or compose datasets from existing cases using **Datasets → Compose dataset**. Both cases and set membership are editable. Each case can contain multiple assertions; experiment repeats are separate. See the [case-library guide](case-library.md).

Use a full pre-fix commit and a credential-free Git URL reachable by the worker (not necessarily GitHub). Worker-local paths must be absolute Linux paths visible inside the worker. The test image is separate from the coding Agent image. It must contain runtime/test dependencies; grading executes offline at `/workspace`. Alternatively, build from a Dockerfile at the baseline: the Dockerfile is relative to the build context, which is relative to the repository.

Describe requirements, not solutions. For the `normalize_name` example above, test whitespace trimming, empty input and preservation of internal spaces. `python -m pytest -q tests` is a command, not a test implementation: create the assertions separately. A zero exit code passes; nonzero fails. Templates do not install dependencies, and failures must not be swallowed. Images without `/bin/sh` can use a JSON argument array.

Tests committed at baseline are agent-visible. For private tests, author them in a separate checkout, use the `git add -N` / `git diff --binary BASE -- ...` commands above, and upload the patch under **Hidden tests and reference fix**. Do not commit hidden tests into the baseline. Ensure the grading command discovers them. Reference fixes and hidden tests remain evaluator-only, never context files or agent prompts.

Definition validation is read-only and shares registration checks. It does **not** clone repositories, pull images, apply patches, run tests, validate the reference fix or spend model tokens. Independently verify baseline FAIL / correct-fix PASS for behavioral reasons before trusting scores. Repository connectivity and patch applicability still need runtime verification.

Queueing an execution freezes its selected definitions by content hash. Edits affect future jobs only; queued work, completed results and retries retain their snapshot. Definition exports include evaluator-only materials; never provide them to Agents. Unsaved forms stay in memory and closing asks for confirmation. Legacy multi-case drafts remain accessible through Standard downloads → Legacy draft import (advanced).
## Draft versions and container self-tests / 草稿版本与容器自检

The legacy draft importer retains service-stored versions, JSON restoration and copying frozen custom datasets. Its review step and the independent case editor can run actual baseline/reference tests without an Agent. Existing cases and datasets can also be self-tested from Dataset self-test. Definitions and execution results remain separate; inspect baseline failures manually before trusting scores. See the [intranet workbench guide](intranet-workbench.md) for limits.

v0.1.7: choose an installed image from the configured WSL distribution, refresh the list, or type an internal tag/digest. The test and Agent roles may reuse a suitable image: the bundled Pi image supports Python standard-library tests using `python3 -m unittest discover -s tests -v` and dependency-free Node scripts, but has no pytest or project packages. The harness, service and proxy images have separate application roles and are not universal project environments. Custom grading overrides the image entrypoint; it does not launch Pi or pass Agent credentials. Install dependencies outside `/workspace` before offline grading. Centered dialogs now confirm unsaved close, draft replacement and task removal; Escape returns to editing, and saved versions remain intact.

创建向导现支持 Worker 内的草稿版本、草稿 JSON 恢复、复制已有评测集继续编辑，以及无 Agent 的真实基线／参考修复测试。“评测集 → 用例自检”也可重新自检已有评测集。定义校验不等于执行通过，请人工确认基线失败原因。详见[内网适配工作台](intranet-workbench.md)。

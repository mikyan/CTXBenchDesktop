# 创建自己的评测集 / Authoring custom datasets

## 中文

入口：**评测集 → 创建评测集**。无需手写 JSON，也不会在创建时调用模型。

1. **评测集信息**：填写名称。一个任务是一个独立编码问题；任务中的多个测试断言不等于多次 Agent 运行。重复次数在实验中配置。
2. **默认仓库与环境**：填写 Git 地址、修复前的完整 40 位提交号，以及测试镜像或基线 Dockerfile。Gitee、公司内网 Git 均可，不限 GitHub；Worker 必须能访问仓库。不要在 URL 中嵌入凭据。仓库路径必须是 Worker 容器可见的 Linux 路径。
3. **任务与测试用例**：填写唯一任务 ID、给 Agent 的需求描述，以及判分用的测试命令。可添加、复制、删除任务；可单独覆盖任务的仓库、基线和环境。未覆盖的任务会随默认值更新，覆盖的任务独立保存。
4. **检查并创建**：检查各任务的环境和隐藏测试来源，可校验定义、预览或导出 JSON，最后创建。创建后到“新建实验”选择它，再设置模型、知识库分支、编排和重复次数。

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

测试镜像与 Agent 镜像是两个用途不同的配置，但**可以复用同一个合适的镜像**。前者执行测试，在此向导设置；后者运行编码 Agent，在实验配置中选择。构建模式中的 Dockerfile 相对构建目录，构建目录相对仓库根目录，且 Dockerfile 必须存在于所选基线。不要向镜像写入密钥。

### 已经导入四个基础镜像，测试镜像怎么选？（待发布）

向导会读取“设置 → 运行环境”所选 WSL 的本地镜像，支持下拉选择、刷新和手填内网标签／摘要。列表只确认镜像已安装，不证明测试兼容性。

| 基础镜像 | 用途与复用条件 |
| --- | --- |
| `ctxbench/agent-pi:0.1.0` | 自带 Node.js/npm、Python 3。可以运行无额外依赖的脚本或 Python 标准库测试；未预装 pytest 和项目依赖。 |
| `ctxbench/official-harness:0.1.0` | 官方数据导入和评分适配器，不是每个官方任务所需的项目测试环境。 |
| `ctxbench/worker:0.1.0` | 本地接口和任务调度，不建议作为项目测试环境。 |
| `ctxbench/egress-proxy:0.1.0` | 网络访问控制，不用于项目测试。 |

例如，仅依赖标准库的 Python 测试可选择 Pi 镜像，使用 `python3 -m unittest discover -s tests -v`。运行自定义测试时覆盖镜像启动入口，只执行测试命令，不启动 Pi、不调用模型、不传入 Agent API 密钥。需要 pytest 或其他依赖时，请先在“设置 → 镜像适配”制作专用镜像，或使用基线 Dockerfile 构建。

依赖请安装到 `/opt/venv` 等路径；评分时 `/workspace` 会被干净基线和待评测补丁的挂载遮盖。测试阶段无网络，不能临时联网安装依赖。不要把答案或隐藏测试打入共享镜像。最后一步可提供参考修复补丁并运行自测，确认基线因为行为断言失败、正确修复通过。

关闭未完成表单、覆盖草稿、删除用例等操作会居中弹出确认，不再把提示放到表单顶部。Esc 只返回当前编辑；放弃必须明确确认。需要中途保存时，可使用顶部“保存或恢复评测集草稿”，无须先填完整个评测集。

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

创建后按内容哈希冻结，不会修改旧实验的数据。导出的是可由现有“导入数据集 → 自定义”直接导入的 JSON 数组；它包含隐藏测试和参考修复，属于评测端材料，不能作为知识库提供给 Agent。当前未提交表单只保存在内存，关闭会提示放弃；需要保留时请在最后一步导出。导出与创建都需连接新版 Worker 完成校验。

新版实验会默认为知识库生成和编码准备项目依赖，不用再手动把 Pi 安装到每个测试镜像里。具体边界、缓存及内网说明见 [Agent 项目构建环境](project-environments.md)。

## English

New experiments prepare project dependencies for builders and coding Agents by default. See [Project build environments](project-environments.md) for caching, offline use and compatibility limits.

Open **Datasets → Create dataset**. The four steps cover dataset naming, shared repository/environment defaults, individual tasks and tests, then review/validation/creation. Add, duplicate or remove independent tasks and optionally override their repository, baseline and test environment. Unoverridden tasks inherit defaults live. Each task can contain multiple assertions; experiment repeats are a separate setting.

Use a full pre-fix commit and a credential-free Git URL reachable by the worker (not necessarily GitHub). Worker-local paths must be absolute Linux paths visible inside the worker. The test image is separate from the coding Agent image. It must contain runtime/test dependencies; grading executes offline at `/workspace`. Alternatively, build from a Dockerfile at the baseline: the Dockerfile is relative to the build context, which is relative to the repository.

Describe requirements, not solutions. For the `normalize_name` example above, test whitespace trimming, empty input and preservation of internal spaces. `python -m pytest -q tests` is a command, not a test implementation: create the assertions separately. A zero exit code passes; nonzero fails. Templates do not install dependencies, and failures must not be swallowed. Images without `/bin/sh` can use a JSON argument array.

Tests committed at baseline are agent-visible. For private tests, author them in a separate checkout, use the `git add -N` / `git diff --binary BASE -- ...` commands above, and upload the patch under **Hidden tests and reference fix**. Do not commit hidden tests into the baseline. Ensure the grading command discovers them. Reference fixes and hidden tests remain evaluator-only, never context files or agent prompts.

Definition validation is read-only and shares registration checks. It does **not** clone repositories, pull images, apply patches, run tests, validate the reference fix or spend model tokens. Independently verify baseline FAIL / correct-fix PASS for behavioral reasons before trusting scores. Repository connectivity and patch applicability still need runtime verification.

Creation freezes the definition by content hash; existing experiment datasets are unchanged. Select it in **New experiment** to configure models, context arms, workflows and repeats. Export produces the existing custom-import JSON array and includes evaluator-only materials; handle it accordingly. Unsaved forms remain in memory and closing asks for confirmation. Use the final-step export to preserve completed definitions. Export and creation need an updated worker connection.
## Draft versions and container self-tests / 草稿版本与容器自检

The creation wizard now supports Worker-stored draft versions, JSON draft restoration, and copying a frozen custom dataset into an editable draft. Its review step can run actual baseline/reference tests without an Agent. Existing datasets can also be self-tested from Datasets → Self-test. Definitions and execution results remain separate; inspect baseline failures manually before trusting scores. See the [intranet workbench guide](intranet-workbench.md) for limits and the complete workflow.

Unreleased: choose an installed image from the configured WSL distribution, refresh the list, or type an internal tag/digest. The test and Agent roles may reuse a suitable image: the bundled Pi image supports Python standard-library tests using `python3 -m unittest discover -s tests -v` and dependency-free Node scripts, but has no pytest or project packages. The harness, service and proxy images have separate application roles and are not universal project environments. Custom grading overrides the image entrypoint; it does not launch Pi or pass Agent credentials. Install dependencies outside `/workspace` before offline grading. Centered dialogs now confirm unsaved close, draft replacement and task removal; Escape returns to editing, and saved versions remain intact.

创建向导现支持 Worker 内的草稿版本、草稿 JSON 恢复、复制已有评测集继续编辑，以及无 Agent 的真实基线／参考修复测试。“评测集 → 用例自检”也可重新自检已有评测集。定义校验不等于执行通过，请人工确认基线失败原因。详见[内网适配工作台](intranet-workbench.md)。

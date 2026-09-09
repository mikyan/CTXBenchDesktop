# GitHub CI 真实联调记录 — 2026-09-08

后续已补跑 [Docker Pi → MiMo → GitHub CI 全链路](ci-agent-live-acceptance.md)：两次候选由真实 Agent 生成，两次最终评分均 PASS。下文仍保留早先 CI-only 控制实验的原始范围，不将两次验收混为一谈。

已在用户拥有的公开仓库 [mikyan/CTXBenchDesktop](https://github.com/mikyan/CTXBenchDesktop) 验证真实 GitHub Actions 的提交、触发、门禁读取、JUnit 统计及恢复观察。不是 Mock 平台，但也**不是 Agent 编码或知识库效果测评**：候选由验收脚本构造，没有调用模型，没有消耗模型 Token。

## 结果

| 独立验收控制 | 测试总数 | 通过 | 失败 | 跳过 | 软件判分 |
| --- | ---: | ---: | ---: | ---: | --- |
| [原样代码](https://github.com/mikyan/CTXBenchDesktop/actions/runs/34222196860) | 192 | 191 | 0 | 1 | PASS |
| [故意改坏一处逻辑](https://github.com/mikyan/CTXBenchDesktop/actions/runs/34222200341) | 192 | 190 | 1 | 1 | FAIL |

两次测试异常（errors）均为 0。跳过的是只适用于 Windows 8.3 目录别名的测试，GitHub 运行环境是 Linux。故意失败的用例为 `ConstraintPipelineTests.test_paper_compatible_similarity_weights_and_threshold`：把 `candidate_similarity` 的返回值改成 `0.0`，原有测试期望 `0.748`。没有修改测试断言，也没有吞掉测试失败退出码。

评分不是从终端输出人工填写：本地当前源码的 `CIGrading.grade` 调用真实 GitHub API，检查候选提交和工作流身份，读取 `backend-tests` 门禁，下载 `ctxbench-junit` ZIP，并解析其中的 JUnit XML。最低实际执行测试数设为 100，两组实际执行均为 191。

关闭验收脚本后启动新进程，重新注入内存令牌，再使用已保存的提交回执调用同一评分模块：两组均复用了原流水线编号，报告 SHA-256 和统计完全一致，没有创建新的流水线。

## 基线与外部改动

- 测试前后的默认 `master` 均为 `bcae82cb3d7496d7adba0f2544187bf32ec5fc3b`，没有改动默认分支。
- 新增准备分支：`codex/ci-live-baseline-20260908`，提交 `bb433fb2b677179b5d7535dcbde10756cefadefc`。相对原有提交，**仅替换该分支中的 `.github/workflows/ci.yml`**，改为手动触发的后端测试与 JUnit 上传；没有发布本机其他未提交代码。
- 原样候选分支：`ctxbench-eval/50ad994bef2e43546d8adf0f4bdcf832`，提交 `5a3b8305e64aa498f2d2da840b20538b0dde5e93`。
- 故障候选分支：`ctxbench-eval/3b81502a58f97eb1f5315fab1af10b96`，提交 `15676d44d236c2e4b01afb2d2774c4f4446b0585`。
- 分支保留供审计，没有创建 PR、合并、打 tag、发布 Release 或删除远程数据。
- 此次读取并执行的是远程已提交版本的后端测试，所以总数 192，不等于本机包含尚未发布功能的 250 项后端测试。

原有 `ci.yml` 已存在于默认分支；测试分支中的版本启用了 `workflow_dispatch`，使用 API 指定测试分支触发成功。没有为获得 UI 手动运行按钮而修改主分支。

## 运行环境与凭据

GitHub 托管 `ubuntu-24.04`，测试在固定 Python 3.13.11 Docker 镜像中运行（linux/amd64 digest `sha256:ac76900038d8606cc99b413d4ede77bc7152f1e42b94cf5d50d4b80a999652fe`），限制 2 CPU / 4 GiB。Checkout / Upload Artifact Action 固定 commit，pytest 固定 8.4.2。apt 与部分传递依赖尚不是完整可复现锁定环境；本记录只证明 CI 对接，不宣称该环境足以支持严肃的知识库因果结论。

仓库 Actions 已启用，检查时仓库 Actions Secrets 为 0。测试工作流只申请 `contents: read`，检出时不持久化凭据，不含部署或发布步骤。GitHub CLI 的现有登录仅供本地评分模块访问平台，令牌通过子进程内存读取，没有打印、上传或写进镜像、用例与结果。

本地状态位于忽略目录 `artifacts/ci-live-20260908/`：`baseline.json`、`results.json`、候选 patch、独立验收数据库及临时基线检出。不修改桌面端正在使用的数据库或服务。验收数据库中的记录标为基础设施控制，不进入正常模型效果统计。GitHub JUnit 产物保留 7 天；本地保留聚合结果、产物 ID、内容哈希，不保留原始报告和测试日志。

## 复跑与边界

脚本：[scripts/ci-live-acceptance.py](../scripts/ci-live-acceptance.py)；工作流：[examples/ci/github-python-acceptance.yml](../examples/ci/github-python-acceptance.yml)。脚本特意限制为当前登录用户的 `CTXBenchDesktop`，防止将含故障注入的项目专用控制误用在其他仓库。

读取已完成的同一远程评测，验证恢复幂等：

```powershell
python scripts/ci-live-acceptance.py grade --execute-remote --verify-resume --repo mikyan/CTXBenchDesktop --root artifacts/ci-live-20260908
```

需要报告产物尚未过期且 GitHub CLI 已登录。若需要新一轮执行，使用新的本地目录、新的 `codex/ci-live-…` 准备分支和当前经审核的默认提交，先运行脚本 `prepare`，再 `grade`。这些命令会真实写入测试分支并消耗 CI 运行资源；不会自动清理旧分支。

本次未覆盖：通过桌面端启动真实 Provider 编码后上传候选、完整知识库配对效果评估、GitHub Enterprise、公司 HTTP 网关、私有基线克隆认证。已有双语 UI 测试和容器专项测试仍属于各自独立的验证层，不能与本次记录合并宣称所有链路均已真实运行。

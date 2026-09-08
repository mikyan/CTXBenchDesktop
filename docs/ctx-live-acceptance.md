# CTXBench 专项验收

## 复现实验

`scripts/ctx-live-acceptance.py` 是显式付费的操作员验收入口。没有 `--execute-paid` 不会执行；必须指定已有共享预算、已导入的数据集、实际任务、Agent 和评分镜像。每次使用新的实验名，不覆盖已有实验。

在挂载代码、数据目录、Docker socket 的 Worker 容器中运行，使用其部署环境中已有的 `XIAOMI_TOKEN_PLAN_CN_API_KEY`；不要把密钥写入脚本、参数或镜像。该脚本不会从桌面内存 API 导出密钥，也不会自动重启服务或恢复历史实验。运行前须等待其他准备操作结束并暂停活跃实验。

```bash
python /source/scripts/ctx-live-acceptance.py \
  --execute-paid \
  --dataset IMPORTED_CTXBENCH_HASH \
  --task opshin_opshin-28 --task qodo-ai_pr-agent-1954 \
  --budget EXISTING_AUTHORIZED_BUDGET \
  --agent-image YOUR_PINNED_PI_IMAGE \
  --harness-image YOUR_PINNED_OFFICIAL_HARNESS \
  --name UNIQUE_ACCEPTANCE_NAME
```

此入口固定使用 MiMo v2.5、单角色 5,000,000 累计 Token、两个重复、无上下文/Skill 生成两臂。沿用预算账本并计入本轮消耗，不重置历史用量。它直接调用当前源码的协调器，避免旧 Worker 后台队列抢走验收任务；实验和运行仍写入普通数据库，可在桌面的“实验 → 结果与证据”查看。

验收要求：

1. 基线与官方测试环境先准备；每个仓库/基线只生成一次知识库。
2. 所有上下文冻结到 `ready` 时，求解运行仍全部为 `queued`。
3. 重建协调器后执行重复求解，不能再次生成知识库，冻结文件校验必须保持不变。
4. 每组配对的 Prompt、模型/额度、资源、网络、基线、Agent/评分镜像必须相同。仅知识库覆盖层不同。
5. 所有运行必须是真实 Provider 且得到布尔功能判定；模型修复失败属于有效结果，不可为了让验收通过而篡改测试。
6. 额外运行 evaluator-only 的空补丁负对照和参考补丁正对照，分别要求失败/通过；它们不进入 Agent 工作区，也不调用模型。

摘要写入 Worker 的 `acceptance-ctx-live-实验ID/summary.json`。完整轨迹、冻结包、配对标识和评分日志仍在原有运行目录。两个任务的冒烟验收不能代替官方 138 任务全量评测，也不能据此宣称知识库整体提升或下降。

## 本轮记录

实验：`UX-CTX-live-20260908` / `exp-154a89e09637`，2026-09-08（香港时间）执行结束。真实 Provider 为 `xiaomi-token-plan-cn / mimo-v2.5`，thinking 为 `high`。每阶段 5,000,000 累计 Token、45 分钟、4 CPU / 8 GiB，沿用 1,000,000,000 Token 总预算。

| 官方任务 | 无知识库，重复 1 / 2 | Skill 知识库，重复 1 / 2 |
| --- | --- | --- |
| `opshin_opshin-28` | 通过 / 通过 | 通过 / 通过 |
| `qodo-ai_pr-agent-1954` | 通过 / Agent 超时，无功能评分 | 通过 / 通过 |

结果是 **7 次通过官方测试，1 次执行超时**，不是 8 次全部通过。超时运行 `solve-cafef5a473c64e049b59` 在完成 45 个模型响应后持续输出思考，触发既定阶段超时；最终状态为 `timed-out`、`settled=false`、`budgetExceeded=false`。没有修改该侧参数、放宽测试、补跑覆盖或人为标记成功。容器自动回收，之后四次求解正常继续并通过。

- 两个仓库/基线各生成一次知识库；全部准备完成前 8 次求解均未启动。重建协调器后复用同样的两个冻结包，未追加生成，文件清单和内容校验通过。
- 4 组配对的执行参数绑定逐项核对通过；其中 **3 组有完整双侧评分**。评分后的 `pairingHash` 额外绑定实际评分镜像，超时运行保留评分前标识，因此不能直接拿它和已评分一侧的最终标识比较，也不能把该组计入完整配对提升。
- 四项独立评分对照均符合预期：两个任务的空补丁都失败，参考补丁都通过。对照在求解结束后单独执行，网络关闭、仅评分器可见，不调用 Agent。
- 严格“所有运行都有功能判定”的验收仍为 **未通过**（`verified=false` / `fullFunctionalAcceptance=false`）；对照通过不覆盖这一事实。

数据集 SHA-256：`8a796d5bb9931836a8b0067f690086e8e8dbc730f7ce9b540acc6fd572b6049b`。本次只有其中两个任务，**不是官方 138 任务全量验收**；样本量不足以评价知识库总体效果，也未在本轮追加 SWE-SHIELD 真实评审。

固定镜像：

- Pi Agent：`sha256:d9d1566b02efff953dc8d5489461f111a39a6e3d321c9a3fe73c7b5c5de79992`
- 官方评分器：`sha256:a53e2c771d08865516b3cc6fa1c702545e5fac465e1342d84c83484ac90e25db`

Provider 已完整/部分上报的累计用量为 **3,899,217 Token**。共享账本扣减 **10,257,778 Token**：超时请求缺少最终完整用量，账本按含超限缓冲的预留额保守计入，不能将此数当作 Provider 实际账单。历史预算和用量没有重置。

证据留在 Worker 数据目录：

- `acceptance-ctx-live-exp-154a89e09637/summary.json`：原始执行摘要，保留严格验收失败。
- `acceptance-ctx-live-exp-154a89e09637/independent-verification/verification.json`：独立配对绑定、冻结复用和正负对照核对结果。
- `runs/solve-cafef5a473c64e049b59/`：超时结果、轨迹与阶段证据。

摘要副本在本地忽略目录 `acceptance-results/ctx-ux-20260908.json` 和 `acceptance-results/ctx-ux-evidence-20260908.json`；原始轨迹、参考补丁与隐藏测试没有加入 Git。桌面入口为“实验 → 结果与证据”，选择上述实验名。当前运行的 Worker 镜像较旧，本轮通过当前源码协调器执行；使用新增公司配置功能需安装匹配的新 Worker 镜像，未在有活跃任务时重启现有服务。

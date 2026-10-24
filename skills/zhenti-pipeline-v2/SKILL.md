---
name: zhenti-pipeline-v2
description: 真题整理与成书流水线的总入口：科目受理、阶段编排、续跑、审批门与交付。当用户要求整理历年真题、把试卷转录成结构化题库、合并成书、走审批改库或中断后继续时使用；路由到 zhenti-tiku（转录分类）与 exam-compilation（合并成书）两个下游 skill。
---

# zhenti-pipeline-v2 · 流水线总入口

职责：受理任务、显式参数、阶段编排与续跑、审批范围记录、把工作路由到下游 skill。
本 skill 不直接转录、不直接改库——一切写操作由确定性执行器完成（agent 说"已改"一律不算数）。

## 阶段地图（确定性核心由 CLI 编排）

| 阶段 | 执行者 | 工具 |
|---|---|---|
| index（原料/卷清单就绪） | CLI | `python -m zhenti_pipeline workflow run-stage index --workspace <W> --subject <slug> --batch-id <B>` |
| transcribe（逐卷转录） | **zhenti-tiku skill**（agent） | 产物落 `papers/<subject>/<fileId>.json` |
| verify / check | CLI | `... run-stage verify` / `... run-stage check` |
| gate（出版门禁） | CLI | `... run-stage gate` |
| merge-preview → 用户批准 → merge-apply | CLI + 用户 | `... run-stage merge-preview` → 用户批准指纹 → `... run-stage merge-apply --approve <指纹>` |
| errata（勘误） | CLI（凭据） | 设 `ZHENTI_ERRATA_TABLE` 后 `... run-stage errata --approve <指纹>` |
| build / publish | CLI + 用户 | `... run-stage build`；`... run-stage publish --approve <指纹>` |
| 外审打包/回收 | 本地工具 | `external-review/` 脚本（发送属外部副作用，需用户批准，见下） |

约定：
- **显式参数**：workspace / subject / batch-id 必填，缺一即问，绝不回落历史科目。
- **续跑**：中断后 `python -m zhenti_pipeline workflow resume --workspace <W> --subject <slug> --batch-id <B>`（按 run_state 的 nextStage 继续）。
- **审批门**：merge-apply / errata / publish 必须携带本次凭据 verify 的输出作为 `--approve`；
  批准对象 = 本次预览指纹，旧批准、漂移输入一律被执行器拒绝。
- **只读检查**：`python -m zhenti_pipeline check-papers --workspace <W> --subject <slug>` 不做任何写入。
- agent 阶段（转录、复核、外审发送）CLI 返回 pending——由对应 skill 会话推进，不循环空转。

## 路由规则

- "整理一批新试卷/新科目" → 先走 zhenti-tiku（转录+门禁），到达 merge-preview 停孔。
- "合并/成书/出 PDF" → exam-compilation；"只重出 PDF"不重跑转录阶段。
- "接着上次的做" → `workflow status` + `resume`，不凭会话记忆猜路径。
- "只帮我检查" → 只读命令（check-papers / gate / status / legacy-inspect），不进写库流程。
- 课堂笔记、教材入库、单题答疑 → **不要**触发本流水线（近邻负例）。

## 审批与授权边界

批准范围分别记录：合并（merge）、入库（ingest）、勘误（errata-write）、外发（external-send）、
发布（publish）。同一批准单次有效、绑定本次指纹；输入或目标变化须重新批准。
外审发送、云解析上传是外部副作用：仅在用户当次明确授权下执行（未配置适配器不自动寻找账号）。

## 参考

- 数据契约 [papers-v2](../../docs/contracts/papers-v2.md)；环境要求 [environment](../../docs/contracts/environment.md)。
- 威胁模型与阶段治理文档在 `sources/workflow/optimization/v2/`（内部资料，公开发布前移出）。

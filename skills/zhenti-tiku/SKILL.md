---
name: zhenti-tiku
description: 将真题 PDF/解析包逐卷转录为 papers/<subject> 结构化题库：卷级来源核对、章/节分类、题图验真、缺答案登记与交接门禁；不修改正式 bank-data。当用户要求"转录试卷/切卷/按教材章节分类/核对题图"时使用。
---

# zhenti-tiku · 真题转录

上游 skill：只负责把原卷变成**逐卷**结构化题库并通过交接门禁；合并、成书、发布一律交给下游。

## 不可更改规则

1. 原题身份是 `(fileId, num)`；原卷只转录一次。同题跨章/节出现是**合法双归属**，用 `also_chapter`
   表达（不复制同 num 条目、不自动删题）。
2. `textbook.json` 是唯一合法目录源：不凭关键词偷重分章、不虚构节名；候选分类须交用户核对。
3. 缺答案/解析：原题保留并登记卷级 `missing`；受托 AI 解题必须**事先获得本批次用户授权**，
   内部记录来源与授权（`_qa/provenance.json`），公开成品不加 AI 标注。
4. 缺图、看不清、来源不可证实：保留数据并标 `releaseBlocked/reviewStatus`，阻断交接与出版，
   交用户确认——不猜图、不删题。
5. 原卷 PDF、解析产物、正式题库只读；上传用户素材到第三方解析服务须用户当次授权。

## 阶段

- **Stage 0 受理**：建立 run（`workflow run-stage index` 前置：清点科目 slug、输入清单、
  教材章节树、答案来源、是否授权补解）。未确认的事项逐项列出，不猜默认。
- **Stage 1 解析留档**：优先本地解析包（MinerU 备料用
  `zhenti_pipeline.adapters.mineru.prepare`，缓存键含源哈希；上传属外部副作用，须授权）。
  记录输入哈希与页码清单到 `_qa/inputs.json`。
- **Stage 2 卷清单**：每卷建 `_qa/paper-index.json`（起止页、fileId、考试类型、学期、A/B、
  题数、答案来源、模糊页）；空白答题卡/重复页排除。卷清单经用户确认后才转录。
- **Stage 3 章节目录**：以 `textbook.json` 为准给出候选分类与 `unmatched` 清单；
  分类批准 ≠ 合并批准。
- **Stage 4 逐卷转录**：一卷一文件 `papers/<subject>/<fileId>.json`；卷内 `num` 唯一；
  保留原卷缺答案事实并对账 `missing`。
- **Stage 5 图片与 meta**：`meta.mockSource` 只填用户确认的模拟题文档全名（不造假来源）；
  题图/解析图逐张核对可解码与归属；缺图记录阻断。
- **Stage 6 交接门禁**：`python -m zhenti_pipeline check-papers --workspace <W> --subject <slug>`
  （或 `workflow run-stage check`）。错误须先纠正；合法双归属不得误报为坏重复。
  **上游 PASS 不替代出版门禁**（下游 exam-compilation 另跑 gate）。
- **Stage 7 交接**：交付卷清单、papers/、校验统计、missing/待核清单、授权记录；
  多会话接力记录 run_id、输入/输出哈希与未定事项。

## 合同

数据契约见 [papers-v2](../../docs/contracts/papers-v2.md)（增补优先于历史科目旧契约）；
环境要求见 [environment](../../docs/contracts/environment.md)。

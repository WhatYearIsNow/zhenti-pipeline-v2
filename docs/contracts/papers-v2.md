# papers v2 统一数据契约（业务规则已确认；校验器 v2.1 实施版）

本文件面向两个 Skill。**兼容原则**：不破坏已有 `papers/<slug>/<fileId>.json`，新增审计性字段可选；旧题库先能通过只读适配与升级预览，再逐批迁移。下游最终来源显示和用户定稿 PDF 版式保持不变。

## 1. 文件和职责

```text
papers/<slug>/
  textbook.json                # 章节唯一事实源，version/hash 可选
  meta.json                    # subject、mockSource、schemaVersion 等
  <fileId>.json                # 原卷级源文件，严格一卷一文件
  images/<fileId>-T<num>-<k>.png
  _qa/                         # 可选内部报告，不被成书过程作为正文读取
    paper-index.json           # 物理页、题数对账、人工复核证据
    provenance.json            # 来源与答案/解析来源（内部使用）
```

## 2. 卷级对象（v1 字段保留）

```json
{
  "fileId": "18191",
  "kind": "final",
  "ab": null,
  "course": "示例科目",
  "paperDisplay": "2018—2019学年第一学期《示例科目》期末考试试卷",
  "sourceFile": "真题原卷.pdf 第1页",
  "missing": [2],
  "questions": []
}
```

- `fileId`：必填、不允许路径字符，文件名必须恰为 `<fileId>.json`；非纯数字的合法样式如期中、月考、A/B、不同课程后缀应显式规则化。验证年份与学期并检查来源一致，禁止只看字符串前 5 位。
- `kind`：兼容 `final | midterm`，其中阶段考试、月考、模拟题需以 `paperDisplay` 或新增 `examType` 细分；不隐式将月考改成期末。
- `ab`：`"A" | "B" | null`；当卷名标明卷别时必须匹配。
- `paperDisplay`：用于输出书中来源；`sourceFile` 仅为溯源到 PDF 的卷级起始页，两者不能混淆。
- `missing`：保留 v1 数字数组，只登记**答案或解析至少一项缺失**的题号；去重排序，每个号必须真实存在；新增内部更细的缺失原因表（如 `answer_missing`,`analysis_missing`,`unreadable_image`）不改变既有字段语义。
- `questions`：至少 1 题；若确有空卷，仅作为待处理草稿，不允许交接合并。

## 3. 题目对象（兼容最小字段）

```json
{
  "num": 2,
  "type": "choice",
  "subtype": "judge",
  "chapter": {"label": "第一章 示例", "section": null},
  "desc": "判断以下命题。",
  "options": [{"letter": "T", "text": "正确"}, {"letter": "F", "text": "不正确"}],
  "answer": "",
  "analysis": "",
  "images": []
}
```

- `num`：正整数，**单个原卷 JSON 内唯一**。允许同一原题在成书不同章节重复收录；使用 `also_chapter` 声明另一归属，合并后的 `-x2` 是合法副本，不得自动删去。中文序号转数字时记录内部的原号映射；不得自动重排有明确原始数字号的试题。
- `type`：仅 `choice | fill | open`；多选为 `choice + subtype=multi`；判断为 `choice + subtype=judge`。
- `subtype`：限定 `calc | fill | solution | choice | single | judge | multi | ""`；按题型设语义规则，而非单独允许任意组合。
- `options`：仅 choice 可非空；常规 single/multi 的选项为 A、B、C……连续不重复；judge 固定为 T/F；有图片选项仍需保留 A-D 与相应图顺序；空文字选项要有对应图片的校验凭据。
- `answer`：允许空（仅在卷级 missing 收录）；single 有值须是合法单个选项字母，multi 有值须是去重字母串，judge 有值须为 `T` 或 `F`，open/fill 保持来源可支持的 LaTeX 原答案。
- `analysis`：允许空（仅在 missing 收录）；受托解题不得伪装成“源卷转录”内部记录，内部溯源但不更改用户定稿的公开 PDF 标注策略。
- `chapter`：`label` 必须属于当前科目 `textbook.sections`；若该章的节列表为空，则 `section=null`；若章下有非空节树，归节策略由科目配置确定，线性代数已确认按章、节分类；以用户确认后的最新版线性代数 textbook.sections 为准（旧版 7 章 section=null 契约作废；在新版目录到位前，禁止凭空编造节名）。
- `also_chapter`：可选 `{label, section}`，须合法且不能与主章/节定位相同；合并生成 `-x2` 副本时不得二次复制。
- `images`：磁盘相对文件名（禁止绝对路径/`../`）+ `where=desc|analysis`；文件实际存在、可解码、宽高有效；相同图片可复用引用。内嵌 base64 是 legacy 兼容，不是新转录输入格式。
- `desc/answer/analysis`：Unicode + LaTeX 文本，不直接拼接 JSON；危险控制字符直接报错，不能以 `_sanitize` 自动修复为数据质量保证。

## 4. meta.json 与 taxonomy

```json
{
  "subject": "微积分",
  "mockSource": "经用户核实的原始模拟题来源书全名",
  "schemaVersion": 2,
  "taxonomyVersion": "calculus-11ch-2026-10-07"
}
```

`mockSource` 没有模拟卷时允许空串；当存在模拟卷时必须有真实经确认的来源。merge 后保留该值，生成器和验证器用同一个来源解析器。禁止将科目名称或卷号误当原始资料来源。

## 5. 错误级别与门禁

| 类别 | 行为 | 示例 |
|---|---|---|
| ERROR / 阻断合并 | 修正或人工确认后才能发布 | 同一原卷 JSON 中重复 num（跨章副本不算）；图像缺失；非法章节；合法来源不能转格式；源 JSON 损坏；答案与 missing 不一致 |
| WARN / 交付披露 | 保留记录并在验收报告说明 | 原卷本无答案/解析；某章无 notes；已知 OCR 模糊但不影响关键题意、且已内部确认 |
| INFO / 统计 | 仅输出数字 | 每卷题数、各题型分布、双归属数量、唯一原题数 |

**必须同时通过三层检查：** (1) 原题覆盖与文字/图完整性；(2) 下游渲染序列与图片/来源/题号的 ID 映射完整性；(3) PDF 编译和关键页/全文自动抽检。

## 6. 用户已确认的不可更改业务规则

1. **允许跨章节重复**：同一原题可在多章/多节完整收录；禁止在汇编时自动去重。单卷 JSON 同一原题只转录一次，额外归属由 `also_chapter` 声明；未来如需多于两处归属，先扩展显式多归属结构。
2. **线性代数按章、节分类**：以用户批准的新版节目录为准；当前旧七章仅章目录不足以凭空给出合法节名，先暂停线代新卷发布直到节目录明确。
3. **AI 补答案/解析须事先逐批获得用户授权**：默认留空与 missing，补做后在 `_qa/provenance.json` 记录答案来源、授权依据、人工核验状态。
4. **图片缺失或题干关键内容无法辨认**：原记录保留，标记 `releaseBlocked` / `_qa` 待核，阻断问题题的正式出版，等待用户确认，禁止静默删除或悄悄改写。
5. **合并需确认**：默认 dry-run 出具变更清单；只有用户确认后才允许 apply，执行前备份并原子写入。
6. **保持原定稿版式**：上述内控标识不自动印在最终 PDF。

## 7. 2B 合并实施补充（2026-10-09）

- `merge_papers.py` 默认只读预览；只能在输入校验器完全通过后生成合并计划。
- 同一 `id`、相同正文：保留旧记录不重复追加；同一 `id`、不同正文：列为 `conflicts`，**任何情况下不自动覆盖**。
- 新题 `also_chapter` 作为 `-x2` 独立收录；源卷 `num` 仍唯一。
- 原题库中不在本轮输入的记录保留；特别是大学物理历史题不可被删除。
- 教材目录变化视为高风险：本版本直接阻断 apply，需另行计划目录迁移。
- apply 必须绑定当前计划指纹；指纹包含旧题库哈希、全量本轮输入的内容哈希、变更清单及目标位置。
- 正式 apply 会先备份旧题库、再在相同磁盘目录写临时文件并原子替换。合并前不得把 dry-run 预览等同用户已批准。


## v3.1 P0 补充（2026-10-09）

- `bank-data` 与从 `papers` 合并的数据都必须经独立 `publication_gate.py` 校验；`check_papers.py` 通过≠准予出版。
- 模拟题来源以 `bank.meta.mockSource` 为动态配置；原版已知科目历史默认值仅用于兼容旧快照，新增来源必须用户确认，不得编造。
- 教材目录迁移不是普通合并：核对稿、目录整体批准哈希、逐题 `from/to/confirmed`、变更指纹、正式 apply 均为独立步骤。
- 已归章但重复收录的同一原题，封面去重按 `(fileId,num)`；正文仍完整保留所有合法章节收录。
- `textbook.notes` 字段整个缺失时视为空提要，不因之剔除题目；待核、非法小节、损坏图片必须阻断出版。
- 最新“答案策略总则”优先：受托解题获用户本次授权后可补解，内部留据，公开 PDF 不额外增加 AI 标签。
- 原有 Stage 0—7、服务器/Windows 双环境及已验收版式保留。真实整本 PDF 视觉回归仍为未验收状态。

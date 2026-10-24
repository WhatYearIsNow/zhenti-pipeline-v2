---
name: exam-compilation
description: 将结构化真题 bank 安全合并并按 exam-zh/XeLaTeX 版式成书：独立出版门禁、来源验证、经审批的章节迁移、题号/题图核验与原子发布。当用户要求"合并题库/出书/重出 PDF/发布成书"时使用。
---

# exam-compilation · 分类汇编与成书

下游 skill：从已过交接门禁的 papers 出发，合并、出版检查、构建、发布。
一切正式写库/落位必须有**本次预览指纹的用户批准**。

## 必须遵守的口径

1. **成品设计冻结**：不以"优化"为由改动已验收的封面、序言、正文、答案、来源、页眉页脚；
   私有文案与品牌配置留在本地 profile，不入公共模板。
2. 原题身份 `(fileId, num)` 去重；跨章/节重复收录是另一计数口径；成书题号全书连续；不为凑数删原题。
3. 章节树以用户确认的 `textbook.json` 为准；章节迁移审批与普通合并审批**分开**，互不替代。
4. 缺答案/解析保留题目；受托解题须本批授权（同 zhenti-tiku 规则）。
5. 缺图、来源不可核实、`releaseBlocked`：阻断正式出书，按原题 ID 出错单，不用改 TeX 掩盖数据错误。
6. 拟对外分发的成品只在用户授权的本地环境处理，不外传。

## 流程（命令以显式路径/参数执行，不依赖 CWD）

### Stage 1 依赖检查

Python ≥3.11、XeLaTeX、`pdfinfo`、Pillow（真实解码）、收录 PDF 图片时 PyMuPDF；
TeX 资源与字库核对 [environment](../../docs/contracts/environment.md)。缺依赖给诊断，不自动安装。

### Stage 2 预检与出版门禁（绝不可绕过）

```bash
# 1) 交接检查（只读）
python -m zhenti_pipeline check-papers --workspace <W> --subject <slug>
# 2) 合并先预览：记录 fingerprint（conflicts 必须为 0；目录变化直接停止）
python -m zhenti_pipeline workflow run-stage merge-preview --workspace <W> --subject <slug> --batch-id <B>
# 3) 用户批准本次指纹后：
python -m zhenti_pipeline workflow run-stage merge-apply --workspace <W> --subject <slug> --batch-id <B> --approve <fingerprint>
# 4) 出版门禁独立运行（上游 PASS 不替代）：
python -m zhenti_pipeline workflow run-stage gate --workspace <W> --subject <slug> --batch-id <B>
```

门禁内容：发布阻断字段、真实章/节、原卷来源（`source_resolver` + `meta.mockSource`）、
数学定界风险、图片可读可解码、原题身份、双归属计数、空答案容忍。失败出错单到**源数据**处理。

#### Stage 2A 章节/目录迁移（独立于普通合并）

先出逐题核对稿与只读迁移计划（`taxonomy_migrate.py --report --review-md`），用户逐题填
`from/to/confirmed` 并确认新目录哈希后重新预览；`ready=true` 且用户**再次批准本次指纹**
才 `--apply --approve`。程序绝不自动给出未经确认的新章/节。

### Stage 3 构建与题图

```bash
python -m zhenti_pipeline workflow run-stage build --workspace <W> --subject <slug> --batch-id <B>
```

隔离目录构建；整本入口**再次内置门禁**；每遍 XeLaTeX 退出码与 `!` 错误行完整纳入判定，
残留旧 PDF 不充当成功依据；页数两遍一致才算稳定。题图缩放/裁白边/预放大在生成期处理，
不改已验收版式。构建报告记录输入、工具链与产物哈希。

### Stage 4 发布（与构建分开）

```bash
python -m zhenti_pipeline workflow run-stage publish --workspace <W> --subject <slug> --batch-id <B> --approve <fingerprint>
```

publish 默认 dry-run；`--apply` 需 `type=publish` 凭据（preview=隔离 PDF SHA，old-target=目标现 SHA）。
原子落位 + 读回校验；旧正式版备份保留（`*.bak-publish-*`），**永不删除**；目标被占用即停。

## 外审（可选适配器）

本地闭环：打包（脱敏扫描）→ 发送（外部副作用，须用户当次批准）→ 回收 → `parse_review.py`
解析（守恒与越界 id 对账）→ 独立复核 → `build_errata_candidates.py` 候选表（**决策支持件，
不可直接 apply**）→ 用户逐项批准定稿勘误表 → `apply_errata_v2.py apply`（凭据 + 事务 +
崩溃恢复）。网页适配器未配置时闭环照样可走完本地部分。

## 参考

数据契约 [papers-v2](../../docs/contracts/papers-v2.md)；环境 [environment](../../docs/contracts/environment.md)。

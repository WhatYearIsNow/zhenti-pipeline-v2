# zhenti-pipeline · 真题整理与成书流水线

以一组 Agent Skills 提供真题整理与成书能力，共用 Python 核心负责确定性执行。

> 当前状态：**候选版开发中（0.1.0.dev0），未公开发布**。发布物、许可证与仓库名称待维护者确认。

## 这是什么

- **zhenti-tiku**：把真题 PDF/解析包逐卷转录为结构化题库（`papers/<科目>/<卷号>.json`），
  含卷级来源核对、教材章节分类、题图验真、缺答案登记与交接门禁。
- **exam-compilation**：安全合并到题库 bank、独立出版门禁、XeLaTeX 成书、原子发布。
- **zhenti-pipeline-v2**：总入口，阶段编排与续跑；一切写操作由确定性执行器完成，
  agent 说的"已改"不算数——正式写入必须携带本次预览指纹的用户批准。

业务不变量：原题身份 `(fileId, num)`、合法跨章双归属不删题、缺答案保留 `missing` 记录、
缺图/来源不明阻断交付、上游检查不替代出版门禁、批准范围分别记录。

## 安装

要求 Python ≥ 3.11（Windows / Linux；路径含中文与空格受支持）。

```bash
pip install -e ".[dev]"      # 开发安装（含测试依赖）
# 或安装发布包后按需 extras：images / pdf / review-pdf / schema
```

## 快速开始（合成样例，全程离线）

```bash
# 1) 检查一个 papers 目录（只读）
python -m zhenti_pipeline check-papers --workspace examples/synthetic --subject demo

# 2) 阶段编排：计划 / 状态 / 单阶段 / 续跑
python -m zhenti_pipeline workflow plan   --workspace examples/synthetic --subject demo --batch-id b1
python -m zhenti_pipeline workflow status --workspace examples/synthetic --subject demo --batch-id b1
python -m zhenti_pipeline workflow run-stage check --workspace examples/synthetic --subject demo --batch-id b1
python -m zhenti_pipeline workflow resume --workspace examples/synthetic --subject demo --batch-id b1
```

stdout 输出唯一的 JSON envelope（schemaVersion/ok/status/data/errors/warnings/artifacts）。
完整离线样例与端到端演示在 `examples/synthetic/`（构建中，见 CHANGELOG）。

## 测试

```bash
pytest -q -m "not rendering"   # 单元/契约/集成/恢复（无网络、无账号、仅临时目录）
pytest -q -m rendering         # 渲染层：需要本机 XeLaTeX + pdfinfo
```

## 权限与副作用边界

- 测试默认在连接层禁网；CI 无外部服务凭据。
- 云解析（MinerU）、外审网页发送、发布落位是**显式副作用**：仅在用户当次授权下执行；
  未配置适配器时不自动寻找账号。
- 审批凭据四元组单次有效，绑定本次指纹；执行器自身核验，不依赖调用纪律。

## 文档

- 架构与阶段：`docs/`（baseline/ 各阶段设计与证据）
- 数据契约：`docs/contracts/papers-v2.md`；环境要求：`docs/contracts/environment.md`
- 贡献：[CONTRIBUTING.md](CONTRIBUTING.md)；安全：[SECURITY.md](SECURITY.md)；
  第三方组件：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## 限制

- 锁与原子性保证仅限本地文件系统；网络盘/同步盘未验证。
- 渲染层第三方 TeX 资源（exam-zh、字体等）的分发许可在核清前不随仓库 vendor。
- 真实 OCR/转录准确性属于适配器 smoke 与 skill 行为评估，不在离线 E2E 覆盖范围内；
  各阶段实际执行者与替身见 `evals/README.md` 的诚实台账。

### English (brief)

Pipeline of Agent Skills + a deterministic Python core for curating exam papers into
structured item banks and typeset books. Explicit workspace/subject/batch parameters,
approval-gated writes bound to per-batch fingerprints, crash-recoverable multi-file
transactions, offline-by-default tests. Python ≥3.11; see docs/ and CONTRIBUTING.md.

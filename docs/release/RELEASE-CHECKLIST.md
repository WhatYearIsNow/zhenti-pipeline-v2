# 发布清单（S6/S7 用）

每次候选发布逐项勾选；未完成项必须写明原因，不得静默跳过。

## A. 自动化证据

- [x] `pytest -q -m "not rendering"` 全绿（Windows 本机；CI 3.11–3.13 × Win/Linux）
- [x] `pytest --collect-only` 无错误
- [x] `pytest -q -m rendering` 在固定工具链（TeX Live 2026 / Windows）全绿
- [x] 非 rendering 测试在干净 Linux（GitHub CI ubuntu × 3.11–3.13）实跑通过（首跑 run 40111639612，6/6 job 绿）；渲染层 Linux job 仍待 TeX 资源许可
- [x] 并发/进程终止场景：多进程启动 + os._exit 注入（无随机 sleep）

## B. 发布物

- [x] `pip wheel .` → 安装到**全新 venv** → `python -m zhenti_pipeline --version`、
      `check-papers` 样例可跑（PKG-01）
- [ ] skill 发布包（如发布）：解包后相对引用可达；核心包版本锁定
- [x] wheel 构建含全部包模块（S3 已验证；正式发布重跑）

## C. 公开边界（OSS-01/02）

- [x] allowlist 复扫：导出物（src/skills/schemas/tests/evals/examples/docs/{contracts,release}）
      对私人路径/真实科目字面量/凭据模式命中为 0；`docs/baseline/` 为内部阶段证据，
      **不在公开导出物**（其内容含 RED 清单表述，属有意保留的内部文档）
- [x] 误报登记：`tests/test_rendering.py` 的 `C:	exlive6` 为环境文档声明的标准
      TeX Live 安装路径（非私人目录），接受保留；`tests/test_{test_hygiene,skills_spec}.py`
      守卫正则中的 `/Users/`、`/home/` 为通用 Unix 路径检测模式，接受保留
- [x] RED 清单文件不在导出物（stage 报告/真实科目 fixture/历史包/审计依据等）
- [x] **代码 LICENSE：MIT（用户 2026-10-24 决定）**，已写入 LICENSE 与 pyproject
- [x] 仓库名称/归属：WhatYearIsNow/zhenti-pipeline-v2（公开，allowlist 导出+全新历史，2026-10-24 用户决定）
- [ ] THIRD_PARTY_NOTICES：PyMuPDF 分发形态、TeX 资源（exam-zh/字体）许可材料核清
- [x] 外审网页适配器**不随候选版公开**（用户 2026-10-24 决定；test_skills_spec 锁定）

## D. 行为与文档

- [x] skills/ 三份 SKILL.md frontmatter/引用/无私特点（测试锁定）
- [x] evals 诚实台账：live 行为评估 NOT RUN 已声明（不冒充通过）
- [ ] 独立会话行为评估 ≥12 场景、高风险 ×3（NOT RUN，规程与场景已就绪；宿主待声明）
- [x] README 快速开始命令在合成样例上实际执行过
- [x] CHANGELOG / CONTRIBUTING / SECURITY 齐备

## E. 已知未解决问题（随候选版交付）

见 `docs/candidate/RELEASE-NOTES-0.1.0-rc.1.md` 的 Open issues 节。

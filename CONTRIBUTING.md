# 贡献指南

## 快速开始

```bash
git clone <仓库> && cd zhenti-pipeline-v2
pip install -e ".[dev]"
pytest -q -m "not rendering"   # 常规测试（渲染层另见下）
pytest -q -m rendering         # 需要本机 XeLaTeX + pdfinfo（TeX Live，见 docs/contracts/environment.md）
```

## 添加新科目

科目是数据不是代码：填科目 manifest（`slug`、`displayName`、`inputDir`、`textbookPath`、
`mockSource`、`answerPolicy` 等），经校验 → dry-run 指纹 → 用户批准 → 安装。
参考 `sources/workflow/config/subjects/README.md` 的流程说明（历史版本）与
`sources/workflow/optimization/v2/onboarding/` 的实现。**不要**把科目白名单写进代码。

## 添加回归用例

- 缺陷修复必须带最小复现用例（历史事故优先：写清事故现场与断言）。
- 并发/进程终止用多进程同时启动与 `os._exit` 复现，不用随机 sleep。
- 测试默认无网络、无真实账号、全部写入临时目录（仓库 conftest 在连接层禁网）。
- 渲染层证据标 `@pytest.mark.rendering`，默认 CI 排除。

## 架构约定

- 单一实现：`src/zhenti_pipeline/` 是唯一实现；`sources/` 下旧脚本一律薄包装，禁止新增逻辑。
- 显式参数：workspace / subject / batch-id 必填；不回落历史科目；不依赖 CWD。
- 审批：一切正式写入由执行器自身核验批准对象（凭据四元组 + 本次指纹）；`--approve` 不是装饰参数。
- envelope：CLI stdout 只输出一个 JSON envelope；诊断走 stderr。
- schema 管结构，domain 校验管语义；不在多处复制完整校验器。

## 提交

小批次提交：一个阶段/一个主题一个提交，测试不过不进下一阶段。
公共提交信息不包含私人路径、账号、真实科目批次事实。

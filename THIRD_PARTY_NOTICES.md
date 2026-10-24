# 第三方组件与许可通知

本仓库核心 Python 代码零第三方运行时依赖（stdlib only）。可选功能组引入以下第三方库；
**分发方式与许可证由用户在公开发布前最终确认**（方案 §9）。

## Python 依赖（extras）

| 组 | 组件 | 用途 | 许可（待发布前复核） |
|---|---|---|---|
| images | Pillow | 题图解码/裁边 | MIT-CMU |
| images | numpy | 图像数值处理 | BSD-3 |
| pdf | PyMuPDF (fitz) | PDF 结构对账 | AGPL-3.0 / 商业双许可 —— **发布形态须专项确认** |
| review-pdf | reportlab | 目录迁移复核 PDF | BSD-3 |
| schema | jsonschema | 契约结构校验 | MIT |
| dev | pytest | 测试 | MIT |

## TeX 资源（构建链，当前未 vendor 进仓库）

| 资源 | 用途 | 状态 |
|---|---|---|
| TeX Live / XeLaTeX / pdfinfo | 编译与页数 | 系统级安装，不随仓库分发 |
| exam-zh 文档类 | 试卷版式 | CTAN 可装；**许可与分发材料待核清后决定 vendor 或安装指引** |
| ulem、STIXTwo、Asana 等 | 数学/字体 | 同上；在核清前不进入发布物（方案 §9） |

## 仓库内历史快照（sources/）

`sources/` 保留迁移来源快照与历史阶段治理文档，**属内部资料，不在公开发布 allowlist 内**；
其中部分文件含私人路径与真实批次事实（见 docs/baseline/S0-公开边界与allowlist.md RED 清单）。
公开发布将通过 allowlist 导出，不整体推送本仓库。

## 测试资产

- 合成 fixtures（1×1 PNG、演示科目数据）为自制，随仓库分发；
- 历史契约文档（docs/contracts/papers-v2.md）来自项目内部定稿，发布前逐字复核。

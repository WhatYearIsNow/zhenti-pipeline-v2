# 环境要求（通用版）

本文件描述运行本流水线所需的环境；不针对任何个人机器。CI 与发布包据此声明支持矩阵。

## Python

- **3.11 / 3.12 / 3.13**（Windows / Linux）。命令名按平台：Windows 常见 `python`，
  Linux 常见 `python3`；脚本不假定具体名字，由调用方提供。
- 统一 `PYTHONUTF8=1` 运行（Windows 控制台编码防御）。
- 安装：`pip install -e .`（开发）或安装发布包；核心零第三方依赖，
  按需 extras：`images`（Pillow、numpy）、`pdf`（PyMuPDF）、`review-pdf`（reportlab）、`schema`（jsonschema）。

## TeX / PDF 工具链（仅构建与发布需要）

- XeLaTeX（TeX Live 或等价发行版）、`pdfinfo`（poppler-utils）。
- `exam-zh` 文档类与配套宏包、中文字库：**安装方式与许可见发布说明**；
  在查清第三方资源分发许可前，公共仓库不直接 vendor（见方案 §9）。
- 构建使用隔离目录；工具链版本记录进 build-report。

## 外部服务（可选，均属外部副作用）

- MinerU 云解析：`mineru-open-api` CLI（Node ≥20）；认证一次性 `auth` 或 `MINERU_TOKEN`。
  未配置时备料适配器 fail-closed 报错，不降级、不换服务。
- 外审网页发送：可选适配器；未配置时本地闭环（打包→回收→解析→复核→候选表）照常可用。

## 平台注意

- 路径含中文与空格受支持且被测试覆盖；脚本一律显式路径，不依赖 CWD。
- Windows：只读句柄不可 fsync（备份以写模式落盘）；PDF 可能被阅读器锁定（发布前探测，
  不强删）。锁与原子写在 NTFS/ext4 本地盘上保证；网络盘/同步盘另列支持边界。

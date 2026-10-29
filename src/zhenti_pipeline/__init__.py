"""zhenti-pipeline · 真题整理与成书共用核心（S3 起）。

单一实现的 Python 包：skills 入口与旧脚本一律薄包装到本包（方案 §4）。
分层：
  storage/  原子写、锁、状态、审批、接力（确定性执行底座，全 stdlib）
  domain/   卷/题/目录/来源/收录身份与业务校验（全 stdlib）
  adapters/ MinerU、TeX、外审（S4 起迁入）
  cli.py    `python -m zhenti_pipeline` 统一入口（envelope JSON，显式 workspace）
"""

__version__ = "0.1.0.dev0"

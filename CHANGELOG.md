# 更新日志

## Unreleased maintenance

- 固定开发格式工具并接入现有 CI；补充隔离验证、候选构建、健康检查、代码/数据回退边界与源码阅读路线。运行接口与数据格式保持不变。

本仓库版本号独立于旧文档中的"v2 / v3.2"口径（那是工作流与 skill 契约版本）。首个候选发布目标 `0.1.0-rc.1`。

## 0.1.0.dev0（候选开发中）

### 迁移与基线
- 2026-10-24：由生产工作区迁入开发仓库（快照基线 f6c0cfa）；S0 产出来源/依赖清单与公开 allowlist（GREEN/YELLOW/RED 三级）。

### S1 测试隔离
- 旧脚本式自测转 unittest（修复收集期 stdout 重定向/生产路径导入/sys.exit）；
- 仓库级网络守卫（连接层禁网）；合成项目 + 失败复现测试。

### S2 一致性修复（P0）
- 审批台账锁 + 唯一临时文件（并发消费恰一成功）；
- run_state verify 只读、互更 revision CAS；
- 勘误/入库执行器自核批准对象；勘误事务 journal+备份+recover（进程崩溃可恢复）；
- 编译判定完整纳入每遍退出码，残留 PDF 不再混淆成功。

### S3 共用核心与配置
- `src/zhenti_pipeline` 包（storage/domain/adapters/workflow/cli）；
- 5 对重复副本收敛，旧入口薄包装；
- envelope CLI、显式 workspace、CWD 无关（CFG-01/02）；
- 旧数据只读适配 + papers-v2 schema 起点。

### S4 全流程与 skills
- workflow 阶段层（plan/status/run-stage/resume，审批门，不依赖专有 DSL）；
- MinerU 适配器（源哈希缓存键、统一数组契约、上传可注入）；
- 外审本地闭环回归（守恒/越界 id/候选表不可直接 apply）；
- `skills/` 三份标准化 SKILL.md 与 contracts 文档；evals 脚手架（live 评估 NOT RUN）。

### S5 排版
- 真实 XeLaTeX 构建回归、PDF-01 结构对账、视觉抽样、原子发布（凭据+备份+幂等拒绝）。

### S6 开源标准化
- CI（3.11–3.13 × Windows/Linux，最小权限，Actions 固定 SHA；渲染层暂缓——第三方 TeX 资源许可待核）；
- 贡献/安全/第三方通知/发布清单文档。

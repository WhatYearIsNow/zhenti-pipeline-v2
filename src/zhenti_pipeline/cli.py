"""`python -m zhenti_pipeline` 统一入口（S3 起点）。

约定（方案 §5.1 的落地起点）：
- **显式 workspace**：资料路径一律相对 --workspace 解析；不依赖 CWD、不回落历史科目；
- stdout 仅一个 JSON envelope：{schemaVersion, ok, status, data, errors, warnings, artifacts}；
  诊断走 stderr；exit 0=成功，2=无效输入，1=执行/校验未过；
- 只读命令不产生任何写入（artifacts 需 --json-report 显式给路径才落盘）。

S3 先落 check-papers 与 legacy-inspect 两个只读命令；approvals/run-state 仍走
storage 模块原 CLI（合同由 S2 测试锁定），S4 起并入本入口。
"""
import argparse
import json
import sys
from pathlib import Path

from zhenti_pipeline import __version__
from zhenti_pipeline.domain import check_papers, legacy

ENVELOPE_VERSION = 1


def envelope(ok: bool, status: str, data=None, errors=None, warnings=None, artifacts=None) -> dict:
    return {"schemaVersion": ENVELOPE_VERSION, "ok": ok, "status": status,
            "data": data or {}, "errors": errors or [], "warnings": warnings or [],
            "artifacts": artifacts or []}


def cmd_check_papers(args) -> tuple[int, dict]:
    papers_dir = Path(args.workspace) / "papers" / args.subject
    if not papers_dir.is_dir():
        return 2, envelope(False, "invalid-input",
                           errors=[f"papers 目录不存在: {papers_dir}（workspace={args.workspace}, subject={args.subject}）"])
    result = check_papers.audit(papers_dir)
    artifacts = []
    if args.json_report:
        out = Path(args.json_report)
        if not out.is_absolute():
            out = Path.cwd() / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        artifacts.append(str(out))
    status = "ok" if result["ok"] else "blocked"
    data = {"subject": args.subject, "papersDir": str(papers_dir), **result}
    return (0 if result["ok"] else 1), envelope(result["ok"], status, data=data,
                                                errors=result["errors"],
                                                warnings=result["warnings"],
                                                artifacts=artifacts)


def cmd_legacy_inspect(args) -> tuple[int, dict]:
    papers_dir = Path(args.workspace) / "papers" / args.subject
    if not papers_dir.is_dir():
        return 2, envelope(False, "invalid-input",
                           errors=[f"papers 目录不存在: {papers_dir}"])
    report = legacy.inspect_papers(papers_dir)
    status = "ok" if not report["errors"] else "blocked"
    return (0 if not report["errors"] else 1), envelope(not report["errors"], status,
                                                        data=report, errors=report["errors"],
                                                        warnings=report["warnings"])


def cmd_workflow(args) -> tuple[int, dict]:
    from zhenti_pipeline.workflow.stages import WorkflowRunner

    runner = WorkflowRunner(Path(args.workspace), args.subject, args.batch_id,
                            run_id=args.run_id)
    if args.op == "plan":
        plan = runner.plan()
        return 0, envelope(True, "ok", data=plan)
    if args.op == "status":
        st = runner.status()
        return 0, envelope(True, "ok", data=st)
    if args.op == "run-stage":
        r = runner.run_stage(args.stage, approve=args.approve)
        code = {"ok": 0, "blocked": 1, "pending": 0, "invalid-input": 2}[r.status]
        return code, envelope(r.status == "ok", r.status, data=r.as_dict())
    if args.op == "resume":
        r = runner.resume(approve=args.approve)
        code = {"ok": 0, "blocked": 1, "pending": 0, "invalid-input": 2}[r.status]
        return code, envelope(r.status == "ok", r.status, data=r.as_dict())
    return 2, envelope(False, "invalid-input", errors=[f"未知 workflow 操作 {args.op!r}"])


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="zhenti_pipeline", description="真题流水线共用核心 CLI（只读命令；显式 workspace）")
    ap.add_argument("--version", action="version", version=f"zhenti-pipeline {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    cp = sub.add_parser("check-papers", help="只读卷级交接检查（显式 workspace）")
    cp.add_argument("--workspace", required=True, help="工作区根：papers/<subject> 相对它解析")
    cp.add_argument("--subject", required=True, help="科目 slug（必填，不回落历史科目）")
    cp.add_argument("--json-report", default=None, help="可选：审计结果 JSON 落盘路径")
    cp.set_defaults(func=cmd_check_papers)

    li = sub.add_parser("legacy-inspect", help="只读巡检旧格式 papers（未知字段不丢弃、逐项报告）")
    li.add_argument("--workspace", required=True)
    li.add_argument("--subject", required=True)
    li.set_defaults(func=cmd_legacy_inspect)

    wf = sub.add_parser("workflow", help="阶段编排：plan/status/run-stage/resume（确定性核心；agent 阶段返回 pending）")
    wf.add_argument("op", choices=["plan", "status", "run-stage", "resume"])
    wf.add_argument("--workspace", required=True)
    wf.add_argument("--subject", required=True)
    wf.add_argument("--batch-id", required=True)
    wf.add_argument("--run-id", default=None)
    wf.add_argument("--stage", default=None, help="run-stage 的目标阶段")
    wf.add_argument("--approve", default=None, help="审批门阶段的凭据 verify 输出")
    wf.set_defaults(func=cmd_workflow)
    return ap


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    code, env = args.func(args)
    print(json.dumps(env, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

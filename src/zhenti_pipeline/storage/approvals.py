#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审批凭据台账（阶段06，落地 approval-threat-model §4.3 草案）。

六类型：merge|ingest|taxonomy|external-send|errata-write|publish。
凭据 = 类型 + batchId + previewSha256 + oldTargetSha256 + target 四元组绑定，单次有效。

用法:
  python approvals.py record --type merge --batch-id <id> --preview-sha <64hex> \
      --input-sha <64hex> --old-target-sha <64hex|new> --target <path> --evidence "<用户批复依据>"
  python approvals.py verify --type merge --batch-id <id> --preview-sha <64hex> \
      --old-target-sha <64hex|new> --target <path> [--input-sha <64hex>]
      # 四元组+input 匹配且未消费 → stdout 首行 = previewSha256，exit 0，并标记消费
      # 不匹配/已消费/输入漂移 → exit 1（不输出指纹）
  python approvals.py peek  # 同 verify 语义但不消费（供调度器检查资格，真正放行仍在 verify 消费点）

record 只能由主会话在用户明确批准后调用（evidence 必填用户批复依据）；
verify 供工作流在任何 --apply 前调用——approve 值只能取 verify 的 stdout，
禁止脚本字面量（首跑 L598 事故的结构性封堵）。
台账 append-only：optimization/v2/approvals/ledger.jsonl，每行一条凭据（含消费状态）。
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from zhenti_pipeline.storage.filelock import exclusive_lock

def ledger_path() -> Path:
    """台账路径：env 优先；旧脚本布局默认由 pipeline 薄包装在 __main__ 守卫内注入。"""
    env = os.environ.get("APPROVALS_LEDGER")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "approvals" / "ledger.jsonl"


TYPES = {"merge", "ingest", "taxonomy", "external-send", "errata-write", "publish"}


def load() -> list:
    led = ledger_path()
    if not led.is_file():
        return []
    rows = []
    for line in led.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def save(rows: list) -> None:
    """唯一临时文件 + fsync + 原子替换（S2 P0-A01：不再用固定 .tmp 名整体覆盖）。

    必须在 exclusive_lock(ledger_path().lock) 内调用——record/verify 的读改写全程持锁，
    并发消费同一凭据时只有持锁者能完成标记。
    """
    led = ledger_path()
    led.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(led.parent), prefix=".ledger-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, led)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def rec_id(row: dict) -> str:
    return hashlib.sha256(json.dumps(
        {k: row[k] for k in ("type", "batchId", "previewSha256", "oldTargetSha256", "target")},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="审批凭据台账（record=登记用户批准 / verify=写前验证并消费）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    for k in ("--type", "--batch-id", "--preview-sha", "--input-sha", "--old-target-sha", "--target", "--evidence"):
        r.add_argument(k, required=True)
    for name in ("verify", "peek"):
        v = sub.add_parser(name)
        for k in ("--type", "--batch-id", "--preview-sha", "--old-target-sha", "--target"):
            v.add_argument(k, required=True)
        v.add_argument("--input-sha", default=None, help="提供时一并核对输入指纹（fail on drift）")
    args = ap.parse_args()
    if args.type not in TYPES:
        print(f"ERROR: 未知凭据类型 {args.type!r}（{sorted(TYPES)}）", file=sys.stderr)
        return 2

    # record 与 verify(消费) 都是读改写：全程持台账锁（S2 P0-A01——
    # 并发 verify 同一凭据时，后到者必须看到先到者的 consumed 标记）。
    with exclusive_lock(ledger_path().with_suffix(".lock")):
        return _dispatch(args)


def _dispatch(args) -> int:
    rows = load()

    if args.cmd == "record":
        row = {
            "type": args.type, "batchId": args.batch_id,
            "previewSha256": args.preview_sha, "inputSha256": args.input_sha,
            "oldTargetSha256": args.old_target_sha, "target": args.target.replace("\\", "/"),
            "evidence": args.evidence,
            "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "consumed": False, "consumedAt": None,
        }
        row["id"] = rec_id(row)
        rows.append(row)
        save(rows)
        print(f"recorded {row['id']}（{args.type} @ {args.batch_id}，未消费）")
        return 0

    # verify/peek：四元组全匹配 + 未消费（+可选输入指纹一致）→ 输出指纹（peek 不消费）
    consume = args.cmd == "verify"
    # 2026-10-12：同四元组重新走审核孔后台账里会同时存在已消费旧凭据与新凭据——
    # 查找必须优先未消费行，否则"重新走审核孔"被旧行永久堵死（历史勘误重试踩过）。
    def _quad_match(row):
        return (row["type"] == args.type and row["batchId"] == args.batch_id
                and row["previewSha256"] == args.preview_sha
                and row["oldTargetSha256"] == args.old_target_sha
                and row["target"] == args.target.replace("\\", "/"))

    matches = [r for r in rows if _quad_match(r)]
    unconsumed = [r for r in matches if not r.get("consumed")]
    if not matches:
        print("ERROR: 无匹配凭据（类型/批次/预览指纹/目标旧值/路径 四元组任一不符）——未获批准，禁止写入", file=sys.stderr)
        return 1
    if not unconsumed:
        print(f"ERROR: 凭据 {matches[0]['id']} 已消费（单次有效）且无未消费的新凭据——重复执行须重新走审核孔", file=sys.stderr)
        return 1
    row = unconsumed[0]
    if args.input_sha and row["inputSha256"] != args.input_sha:
        print(f"ERROR: 输入指纹漂移（凭据 {row['id']}）——输入已变化，须重新审批", file=sys.stderr)
        return 1
    if consume:
        row["consumed"] = True
        row["consumedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        save(rows)
        print(f"# consumed credential {row['id']} ({row['type']} @ {row['batchId']})", file=sys.stderr)
    else:
        print(f"# peek ok (未消费) credential {row['id']}", file=sys.stderr)
    print(row["previewSha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

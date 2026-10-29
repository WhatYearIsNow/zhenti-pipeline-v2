#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行状态清单（阶段06）：跨 Amend/新会话的可恢复状态与漂移停机。

每个 run 的状态：_work/workflow-zhenti/runs/<runId>/state.json
内容：runId/subject/batchId/owner/revision、启动参数回声、输入指纹、科目配置与章节树哈希、
逐卷进度（fileId→{sha,stage}）、审批引用（approvalId 列表，凭据本体在 approvals 台账）、
pausePoint/nextStage。

用法:
  python run_state.py init --subject <s> --batch-id <b> --input-dir <d> --config-path <p> [--run-id <id>]
      # 建/复用 run 目录；已存在则走 verify 分支
  python run_state.py verify --run-dir <dir> --subject <s> --batch-id <b> --input-dir <d> --config-path <p>
      # 参数回声 + 输入指纹 + 章节树/配置哈希逐项比对；任一漂移 → exit 1（Amend 丢 args 后
      # 绝不回退默认科目——必须人工核对）；一致 → exit 0 并输出当前指纹。
      # S2 P0-A04：verify 为只读检查，不递增 revision、不写回（STA-03）。
  python run_state.py record-approval --run-dir <dir> --approval-id <id> [--expected-revision N]
  python run_state.py set-paper --run-dir <dir> --file-id <id> --sha <64hex> --stage <stage> [--expected-revision N]
  python run_state.py set-point --run-dir <dir> --pause-point <p> --next-stage <n> [--expected-revision N]

S2 P0-A04：互更（set-paper/set-point/record-approval/refresh）全程持锁 + 可选
--expected-revision CAS；成功必递增 revision 并输出 {"ok":true,"revision":N}。
全部原子写（唯一临时文件+替换）+ 写后读回；锁随进程死亡自动释放（filelock.py）。
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


# S3：包内默认 env 优先、CWD 兜底；旧脚本布局默认（workflow/runs）由 pipeline 薄包装
# 在 __main__ 守卫内注入（模块导入不得改写进程环境——S4 教训：会污染调用方）。
def runs_root() -> Path:
    env = os.environ.get("ZHENTI_RUNS_DIR")
    if env:
        return Path(env)
    return Path.cwd() / "runs"


def _hash_inputs_cmd() -> list[str]:
    """hash_inputs 调用形态：包内模块优先（发布包自足）；env/旧布局为兼容回退。"""
    env = os.environ.get("ZHENTI_HASH_INPUTS")
    if env:
        return [str(Path(env))]
    here = Path(__file__).resolve()
    for cand in (
        here.parents[3] / "sources" / "workflow" / "hash_inputs.py",
        Path.cwd() / "hash_inputs.py",
    ):
        if cand.is_file():
            return [str(cand)]
    return ["-m", "zhenti_pipeline.workflow.hash_inputs"]


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def atomic_write(path: Path, obj) -> None:
    """唯一临时文件 + fsync + 原子替换 + 读回（S2 P0-A04：不再用固定 .tmp 名）。

    互更（set-paper/set-point/record-approval/refresh）必须在
    exclusive_lock(state.json.lock) 内调用，配合 expected-revision 做 CAS。
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".state-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if json.loads(path.read_text(encoding="utf-8")).get("runId") != obj.get("runId"):
            raise RuntimeError("state readback mismatch")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def ws_rel(p: Path) -> str:
    cwd = os.getcwd().replace("\\", "/")
    s = str(p).replace("\\", "/")
    return s[len(cwd) + 1 :] if s.startswith(cwd + "/") else s


def snapshot(subject: str, config_path: str) -> dict:
    cfg = Path(config_path)
    tb = Path("papers") / subject / "textbook.json"
    meta = Path("papers") / subject / "meta.json"
    snap = {
        "configSha256": sha_file(cfg) if cfg.is_file() else None,
        "textbookSha256": sha_file(tb) if tb.is_file() else None,
        "metaSha256": sha_file(meta) if meta.is_file() else None,
    }
    return snap


def input_fingerprint(input_dir: str, subject: str, out: Path) -> str | None:
    """调 hash_inputs v2 算输入指纹（fail-closed）；章节树存在时一并纳入。
    mineru/ 目录排除——它是本 run 的派生产物而非原料，否则备料本身会造成指纹漂移。"""
    roots = [input_dir]
    tb = Path("papers") / subject / "textbook.json"
    if tb.is_file():
        roots.append(str(tb))
    import subprocess

    r = subprocess.run(
        [sys.executable, *_hash_inputs_cmd(), "--exclude-dir", "mineru", *roots, str(out)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONUTF8="1"),
    )
    return r.stdout.strip().splitlines()[0] if r.returncode == 0 else None


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="run 状态清单（init/verify/record-approval/set-paper/set-point）"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "verify"):
        s = sub.add_parser(name)
        for k in ("--subject", "--batch-id", "--input-dir", "--config-path"):
            s.add_argument(k, required=True)
        s.add_argument("--run-id", default=None)
    p = sub.add_parser("refresh")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--config-path", required=True)
    p.add_argument(
        "--why", required=True, help="为何刷新（如：第0步章树定稿回填 / onboard 更新 manifest）"
    )
    for name, keys in (
        ("record-approval", ["--approval-id"]),
        ("set-paper", ["--file-id", "--sha", "--stage"]),
        ("set-point", ["--pause-point", "--next-stage"]),
    ):
        s = sub.add_parser(name)
        s.add_argument("--run-dir", required=True)
        for k in keys:
            s.add_argument(k, required=True)
        s.add_argument(
            "--expected-revision",
            type=int,
            default=None,
            help="CAS：提供时与当前 revision 不符即拒绝（S2 P0-A04）",
        )
    p.add_argument("--expected-revision", type=int, default=None)
    args = ap.parse_args()

    if args.cmd in ("init", "verify"):
        run_id = getattr(args, "run_id", None) or f"{args.subject}-{args.batch_id}"
        run_dir = runs_root() / run_id
        state_path = run_dir / "state.json"
        args_echo = {
            "subject": args.subject,
            "batchId": args.batch_id,
            "inputDir": args.input_dir.replace("\\", "/"),
            "configPath": args.config_path.replace("\\", "/"),
        }
        fp_out = run_dir / "input-fingerprint.json"
        if args.cmd == "init" and not state_path.is_file():
            # init 与并发 init/verify 竞争：建目录与落盘持锁，锁内复查避免双建
            with exclusive_lock(run_dir / "state.json.lock"):
                if state_path.is_file():
                    print(json.dumps({"ok": True, "reused": True}, ensure_ascii=False))
                    return 0
                run_dir.mkdir(parents=True, exist_ok=True)
                fp = input_fingerprint(args_echo["inputDir"], args.subject, fp_out)
                if fp is None:
                    print(
                        "ERROR: 输入指纹计算失败（hash_inputs fail-closed：原料目录或章节树缺失）",
                        file=sys.stderr,
                    )
                    return 1
                st = {
                    "runId": run_id,
                    "owner": os.environ.get("USERNAME") or "unknown",
                    "revision": 1,
                    "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "argsEcho": args_echo,
                    "inputFingerprint": fp,
                    **snapshot(args.subject, args.config_path),
                    "papers": {},
                    "approvalIds": [],
                    "pausePoint": "init",
                    "nextStage": "index",
                }
                atomic_write(state_path, st)
            print(
                json.dumps(
                    {"ok": True, "runDir": ws_rel(run_dir), "inputFingerprint": fp},
                    ensure_ascii=False,
                )
            )
            return 0
        # init 已存在 或 verify：逐项核对，漂移即停机
        if not state_path.is_file():
            print("ERROR: state.json 不存在（先 init）", file=sys.stderr)
            return 1
        st = json.loads(state_path.read_text(encoding="utf-8"))
        # S2 P0-A04：verify/init-复用是只读检查，不再递增 revision、不再写回
        drift = []
        for k, v in args_echo.items():
            if st["argsEcho"].get(k) != v:
                drift.append(f"参数回声 {k}: state={st['argsEcho'].get(k)!r} 当前={v!r}")
        cur = snapshot(args.subject, args.config_path)
        for k in ("configSha256", "textbookSha256", "metaSha256"):
            if st.get(k) != cur[k]:
                drift.append(f"{k}: state={str(st.get(k))[:12]}… 当前={str(cur[k])[:12]}…")
        fp = input_fingerprint(args_echo["inputDir"], args.subject, fp_out)
        if fp is None:
            drift.append("输入指纹计算失败（原料/章节树缺失）")
        elif fp != st["inputFingerprint"]:
            drift.append(f"输入指纹: state={st['inputFingerprint'][:12]}… 当前={fp[:12]}…")
        if drift:
            print(
                "DRIFT: 状态与当前环境不一致——Amend/恢复后参数或输入已变化，禁止回退默认科目，须人工核对：",
                file=sys.stderr,
            )
            for d in drift:
                print(f"  - {d}", file=sys.stderr)
            return 1
        if args.cmd == "verify":
            print(
                json.dumps(
                    {
                        "ok": True,
                        "inputFingerprint": fp,
                        "papers": st["papers"],
                        "nextStage": st["nextStage"],
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        print(json.dumps({"ok": True, "reused": True, "inputFingerprint": fp}, ensure_ascii=False))
        return 0

    if args.cmd == "refresh":
        # 供 run 内的既定动作（第0步章树定稿回填 / onboard 更新 manifest）刷新哈希：
        # 输入指纹仍严格比对（原料漂移照常拦），仅配置/章树/元数据哈希在留痕后更新。
        run_dir = Path(args.run_dir)
        state_path = run_dir / "state.json"
        if not state_path.is_file():
            print("ERROR: state.json 不存在", file=sys.stderr)
            return 1
        with exclusive_lock(state_path.with_suffix(".lock")):
            st = json.loads(state_path.read_text(encoding="utf-8"))
            if st["argsEcho"]["subject"] != args.subject:
                print("ERROR: subject 与 state 不符", file=sys.stderr)
                return 1
            cas = _check_cas(st, getattr(args, "expected_revision", None))
            if cas:
                print(cas, file=sys.stderr)
                return 3
            fp = input_fingerprint(
                st["argsEcho"]["inputDir"], args.subject, run_dir / "input-fingerprint.json"
            )
            if fp is None or fp != st["inputFingerprint"]:
                print(
                    f"ERROR: 输入指纹漂移（{str(st['inputFingerprint'])[:12]}… → {str(fp)[:12]}…）——原料变动须重新审批，不允许 refresh",
                    file=sys.stderr,
                )
                return 1
            cur = snapshot(args.subject, args.config_path)
            changed = False
            for k in ("configSha256", "textbookSha256", "metaSha256"):
                if st.get(k) != cur[k]:
                    st["history"] = st.get("history", [])
                    st.setdefault("hashHistory", []).append(
                        {
                            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                            "why": args.why,
                            "field": k,
                            "was": st.get(k),
                            "now": cur[k],
                        }
                    )
                    st[k] = cur[k]
                    changed = True
            if changed:
                st["revision"] = int(st.get("revision", 1)) + 1
                atomic_write(state_path, st)
        print(json.dumps({"ok": True, "refreshed": changed, "why": args.why}, ensure_ascii=False))
        return 0

    run_dir = Path(args.run_dir)
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        print("ERROR: state.json 不存在", file=sys.stderr)
        return 1
    # 互更持锁 + CAS：两个写者持相同 expected revision 时恰有一个成功（S2 P0-A04）
    with exclusive_lock(state_path.with_suffix(".lock")):
        st = json.loads(state_path.read_text(encoding="utf-8"))
        cas = _check_cas(st, getattr(args, "expected_revision", None))
        if cas:
            print(cas, file=sys.stderr)
            return 3
        if args.cmd == "record-approval":
            st["approvalIds"].append(args.approval_id)
        elif args.cmd == "set-paper":
            st["papers"][args.file_id] = {"sha256": args.sha, "stage": args.stage}
        elif args.cmd == "set-point":
            st["pausePoint"] = args.pause_point
            st["nextStage"] = args.next_stage
        st["revision"] = int(st.get("revision", 1)) + 1
        atomic_write(state_path, st)
    print(json.dumps({"ok": True, "revision": st["revision"]}, ensure_ascii=False))
    return 0


def _check_cas(st: dict, expected) -> str | None:
    """expected-revision CAS；None 表示不启用。返回错误文案或 None。"""
    if expected is None:
        return None
    cur = int(st.get("revision", 1))
    if cur != expected:
        return (
            f"REVISION-CONFLICT: 当前 revision {cur} ≠ expected {expected}——"
            f"状态已被其他写者更新，请重读状态后重试（不静默覆盖）"
        )
    return None


if __name__ == "__main__":
    raise SystemExit(main())

"""P0-A01 回归：审批台账并发消费与原子性（APR-02/03/04）。

台账经 APPROVALS_LEDGER 环境变量指向 tmp；全程无网络、无正式区访问（ISO-02/03）。
"""

import json
import subprocess
import sys
from pathlib import Path

APPROVALS = ["-m", "zhenti_pipeline.storage.approvals"]  # 包内模块（发布包自足）

QUAD = [
    "--type",
    "errata-write",
    "--batch-id",
    "b1",
    "--preview-sha",
    "a" * 64,
    "--old-target-sha",
    "b" * 64,
    "--target",
    "bank-data/demo.json",
]
INPUT = ["--input-sha", "c" * 64]
EVIDENCE = ["--evidence", "测试批复依据"]


def run_ledger(tmp_path, *argv):
    env = {
        "PATH": "",
        "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        "PYTHONUTF8": "1",
        "APPROVALS_LEDGER": str(tmp_path / "ledger.jsonl"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    return subprocess.run(
        [sys.executable, *APPROVALS, *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        env={**__import__("os").environ, **env},
    )


def record(tmp_path, preview="a" * 64):
    return run_ledger(
        tmp_path,
        "record",
        "--type",
        "errata-write",
        "--batch-id",
        "b1",
        "--preview-sha",
        preview,
        "--input-sha",
        "c" * 64,
        "--old-target-sha",
        "b" * 64,
        "--target",
        "bank-data/demo.json",
        "--evidence",
        "测试批复依据",
    )


def load_rows(tmp_path):
    text = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def test_verify_consumes_once_and_replay_refused(tmp_path):
    assert record(tmp_path).returncode == 0
    ok = run_ledger(tmp_path, "verify", *QUAD, *INPUT)
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.strip().splitlines()[0] == "a" * 64
    replay = run_ledger(tmp_path, "verify", *QUAD, *INPUT)
    assert replay.returncode == 1
    assert "已消费" in replay.stderr
    rows = load_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["consumed"] is True


def test_wrong_tuple_and_input_drift_refused_zero_state_change(tmp_path):
    before = tmp_path / "ledger.jsonl"
    assert record(tmp_path).returncode == 0
    snapshot = before.read_text(encoding="utf-8")
    wrong_type = run_ledger(
        tmp_path,
        "verify",
        "--type",
        "publish",
        "--batch-id",
        "b1",
        "--preview-sha",
        "a" * 64,
        "--old-target-sha",
        "b" * 64,
        "--target",
        "bank-data/demo.json",
    )
    assert wrong_type.returncode == 1
    wrong_preview = run_ledger(
        tmp_path,
        "verify",
        "--type",
        "errata-write",
        "--batch-id",
        "b1",
        "--preview-sha",
        "f" * 64,
        "--old-target-sha",
        "b" * 64,
        "--target",
        "bank-data/demo.json",
    )
    assert wrong_preview.returncode == 1
    drift = run_ledger(tmp_path, "verify", *QUAD, "--input-sha", "d" * 64)
    assert drift.returncode == 1
    assert "漂移" in drift.stderr
    assert before.read_text(encoding="utf-8") == snapshot  # 拒绝路径零状态变化
    assert all(not r["consumed"] for r in load_rows(tmp_path))


def test_peek_does_not_consume(tmp_path):
    assert record(tmp_path).returncode == 0
    peek = run_ledger(tmp_path, "peek", *QUAD, *INPUT)
    assert peek.returncode == 0
    again = run_ledger(tmp_path, "peek", *QUAD, *INPUT)
    assert again.returncode == 0
    verify = run_ledger(tmp_path, "verify", *QUAD, *INPUT)
    assert verify.returncode == 0  # peek 未消费，verify 仍可消费


def test_re_approval_after_consume_creates_new_credential(tmp_path):
    # 历史教训：重新走审核孔必须放行新凭据，不被旧行堵死
    assert record(tmp_path).returncode == 0
    assert run_ledger(tmp_path, "verify", *QUAD, *INPUT).returncode == 0
    assert record(tmp_path).returncode == 0
    assert run_ledger(tmp_path, "verify", *QUAD, *INPUT).returncode == 0  # 新凭据可消费
    assert len(load_rows(tmp_path)) == 2


def test_concurrent_verify_single_winner(tmp_path):
    # APR-03：多进程同时消费同一批准，仅一个 operation 成功；锁保证后到者看到 consumed。
    # （S2 修复前此场景会双放行——无锁读改写。）
    assert record(tmp_path).returncode == 0
    env = {
        **__import__("os").environ,
        "PYTHONUTF8": "1",
        "APPROVALS_LEDGER": str(tmp_path / "ledger.jsonl"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    procs = [
        subprocess.Popen(
            [sys.executable, *APPROVALS, "verify", *QUAD, *INPUT],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        for _ in range(8)
    ]
    outs = [p.communicate() for p in procs]
    codes = [p.returncode for p in procs]
    assert codes.count(0) == 1, f"恰好一个消费者成功，实际 {codes}\n{outs}"
    rows = load_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["consumed"] is True
    # 台账始终是合法 JSONL（无交错写坏）
    assert load_rows(tmp_path) == rows


def test_concurrent_records_keep_ledger_valid(tmp_path):
    env = {
        **__import__("os").environ,
        "PYTHONUTF8": "1",
        "APPROVALS_LEDGER": str(tmp_path / "ledger.jsonl"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                *APPROVALS,
                "record",
                "--type",
                "errata-write",
                "--batch-id",
                f"b{i}",
                "--preview-sha",
                f"{i:064x}",
                "--input-sha",
                "c" * 64,
                "--old-target-sha",
                "b" * 64,
                "--target",
                "bank-data/demo.json",
                "--evidence",
                "并发登记测试",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        for i in range(8)
    ]
    for p in procs:
        assert p.communicate() is not None
    assert all(p.returncode == 0 for p in procs)
    rows = load_rows(tmp_path)
    assert len(rows) == 8 and len({r["id"] for r in rows}) == 8

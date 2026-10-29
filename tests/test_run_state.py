"""P0-A04 回归：run_state 只读 verify、revision 递增、CAS 并发单赢家（STA-01/02/03）。

ZHENTI_RUNS_DIR 指向 tmp；workspace 为合成目录。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

RUN_STATE = ["-m", "zhenti_pipeline.storage.run_state"]  # 包内模块（发布包自足）

ARGS = [
    "--subject",
    "calculus",
    "--batch-id",
    "b1",
    "--input-dir",
    "input",
    "--config-path",
    "config.json",
]


def make_workspace(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "raw.txt").write_text("合成原料", encoding="utf-8")
    tb = tmp_path / "papers" / "calculus"
    tb.mkdir(parents=True)
    (tb / "textbook.json").write_text(
        json.dumps({"sections": {"第一章": ["1.1"]}}), encoding="utf-8"
    )
    (tb / "meta.json").write_text(
        json.dumps({"subject": "calculus", "mockSource": ""}), encoding="utf-8"
    )
    (tmp_path / "config.json").write_text(json.dumps({"demo": True}), encoding="utf-8")


def run_state(tmp_path, *argv):
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "ZHENTI_RUNS_DIR": str(tmp_path / "runs"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    return subprocess.run(
        [sys.executable, *RUN_STATE, *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(tmp_path),
        env=env,
    )


def state_path(tmp_path):
    return tmp_path / "runs" / "calculus-b1" / "state.json"


def load_state(tmp_path):
    return json.loads(state_path(tmp_path).read_text(encoding="utf-8"))


def init(tmp_path):
    make_workspace(tmp_path)
    r = run_state(tmp_path, "init", *ARGS)
    assert r.returncode == 0, r.stderr
    return r


def test_init_creates_state_revision_1(tmp_path):
    init(tmp_path)
    st = load_state(tmp_path)
    assert st["revision"] == 1
    assert st["argsEcho"]["subject"] == "calculus"
    assert st["inputFingerprint"]


def test_verify_is_readonly(tmp_path):
    # A04：verify 不再递增 revision、不再写回（修复前 verify 一次 revision +1）
    init(tmp_path)
    before = state_path(tmp_path).read_bytes()
    r = run_state(tmp_path, "verify", *ARGS)
    assert r.returncode == 0, r.stderr
    assert state_path(tmp_path).read_bytes() == before
    assert load_state(tmp_path)["revision"] == 1
    assert not list(state_path(tmp_path).parent.glob("*.tmp"))


def test_mutators_increment_revision(tmp_path):
    init(tmp_path)
    r1 = run_state(
        tmp_path,
        "set-paper",
        "--run-dir",
        str(tmp_path / "runs" / "calculus-b1"),
        "--file-id",
        "30001",
        "--sha",
        "a" * 64,
        "--stage",
        "checked",
    )
    assert r1.returncode == 0, r1.stderr
    assert json.loads(r1.stdout)["revision"] == 2
    r2 = run_state(
        tmp_path,
        "set-point",
        "--run-dir",
        str(tmp_path / "runs" / "calculus-b1"),
        "--pause-point",
        "review",
        "--next-stage",
        "merge",
    )
    assert json.loads(r2.stdout)["revision"] == 3
    r3 = run_state(
        tmp_path,
        "record-approval",
        "--run-dir",
        str(tmp_path / "runs" / "calculus-b1"),
        "--approval-id",
        "cred-1",
    )
    assert json.loads(r3.stdout)["revision"] == 4
    st = load_state(tmp_path)
    assert st["papers"]["30001"]["stage"] == "checked"
    assert st["approvalIds"] == ["cred-1"]


def test_expected_revision_conflict_refused(tmp_path):
    init(tmp_path)
    run_dir = str(tmp_path / "runs" / "calculus-b1")
    r = run_state(
        tmp_path,
        "set-paper",
        "--run-dir",
        run_dir,
        "--file-id",
        "30001",
        "--sha",
        "a" * 64,
        "--stage",
        "checked",
        "--expected-revision",
        "99",
    )
    assert r.returncode == 3
    assert "REVISION-CONFLICT" in r.stderr
    assert load_state(tmp_path)["revision"] == 1  # 拒绝路径零状态变化
    ok = run_state(
        tmp_path,
        "set-paper",
        "--run-dir",
        run_dir,
        "--file-id",
        "30001",
        "--sha",
        "a" * 64,
        "--stage",
        "checked",
        "--expected-revision",
        "1",
    )
    assert ok.returncode == 0


def test_concurrent_writers_single_winner(tmp_path):
    # STA-01：两个写者持相同 expected revision，恰一个成功，无静默覆盖
    init(tmp_path)
    run_dir = str(tmp_path / "runs" / "calculus-b1")
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "ZHENTI_RUNS_DIR": str(tmp_path / "runs"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                *RUN_STATE,
                "set-paper",
                "--run-dir",
                run_dir,
                "--file-id",
                fid,
                "--sha",
                "b" * 64,
                "--stage",
                "checked",
                "--expected-revision",
                "1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(tmp_path),
            env=env,
        )
        for fid in ("30001", "30002")
    ]
    outs = [p.communicate() for p in procs]
    codes = [p.returncode for p in procs]
    assert sorted(codes) == [0, 3], f"恰一个成功一个冲突，实际 {codes}\n{outs}"
    st = load_state(tmp_path)
    assert st["revision"] == 2
    winners = [fid for fid in ("30001", "30002") if fid in st["papers"]]
    assert len(winners) == 1  # 失败者的写入不存在


def test_verify_detects_input_drift(tmp_path):
    init(tmp_path)
    (tmp_path / "input" / "raw.txt").write_text("原料被改动", encoding="utf-8")
    r = run_state(tmp_path, "verify", *ARGS)
    assert r.returncode == 1
    assert "DRIFT" in r.stderr

"""P0-A02 回归（ingest 侧）：入库执行器自身核验 type=ingest 凭据，不再依赖调用方纪律。

沙箱：staging → papers/calculus；VALIDATE/_CHECK 用仓库快照；台账经 APPROVALS_LEDGER 指向 tmp。
"""

import hashlib
import json
import os
import subprocess
import sys

import pytest
from pathlib import Path

_SOURCES_PRESENT = (Path(__file__).resolve().parents[1] / "sources").exists()
pytestmark = [
    pytest.mark.skipif(
        not _SOURCES_PRESENT,
        reason="内部工具链快照（sources/）不在发布包内——私有证据层，公开 CI 不跑",
    )
]

REPO = Path(__file__).resolve().parents[1]
INGEST = REPO / "sources" / "workflow" / "optimization" / "v2" / "pipeline" / "ingest_paper.py"
APPROVALS = REPO / "sources" / "workflow" / "optimization" / "v2" / "pipeline" / "approvals.py"
CHECK = REPO / "sources" / "skills" / "zhenti-tiku" / "scripts" / "check_papers.py"


def make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    tb = ws / "papers" / "calculus"
    tb.mkdir(parents=True)
    (tb / "textbook.json").write_text(
        json.dumps({"sections": {"第一章": ["1.1 基础"]}}, ensure_ascii=False), encoding="utf-8"
    )
    (tb / "meta.json").write_text(
        json.dumps(
            {
                "subject": "微积分",
                "mockSource": "",
                "schemaVersion": 2,
                "taxonomyVersion": "demo-3ch",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    staging = ws / "staging" / "papers" / "calculus"
    staging.mkdir(parents=True)
    paper = {
        "fileId": "30002",
        "kind": "final",
        "ab": None,
        "course": "微积分",
        "paperDisplay": "2024—2025学年第一学期《微积分》期末考试试卷",
        "sourceFile": "合成样卷第1页",
        "missing": [],
        "questions": [
            {
                "num": 1,
                "type": "open",
                "subtype": "",
                "chapter": {"label": "第一章", "section": "1.1 基础"},
                "desc": "求 $\\int x\\,dx$。",
                "options": [],
                "answer": "$\\frac{x^2}{2}+C$",
                "analysis": "基本积分表。",
                "images": [],
            },
        ],
    }
    (staging / "30002.json").write_text(
        json.dumps(paper, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return ws


def run_ingest(ws: Path, ledger: Path, *argv):
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "APPROVALS_LEDGER": str(ledger),
        "ZHENTI_CHECK_PAPERS": str(CHECK),
    }
    return subprocess.run(
        [sys.executable, str(INGEST), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ws),
        env=env,
        timeout=180,
    )


def record(ws: Path, ledger: Path, sha: str, old_target: str):
    return subprocess.run(
        [
            sys.executable,
            str(APPROVALS),
            "record",
            "--type",
            "ingest",
            "--batch-id",
            "calculus",
            "--preview-sha",
            sha,
            "--input-sha",
            sha,
            "--old-target-sha",
            old_target,
            "--target",
            "papers/calculus/30002.json",
            "--evidence",
            "测试批复",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1", "APPROVALS_LEDGER": str(ledger)},
        timeout=60,
    )


def test_ingest_without_or_with_wrong_approve_is_refused(tmp_path):
    ws = make_workspace(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    src = ws / "staging" / "papers" / "calculus" / "30002.json"
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    args = [
        "--subject",
        "calculus",
        "--file-id",
        "30002",
        "--staging",
        "staging",
        "--expected-sha",
        sha,
    ]

    none = run_ingest(ws, ledger, *args)
    assert none.returncode == 2 and "approve" in none.stderr
    assert not (ws / "papers/calculus/30002.json").exists()

    assert record(ws, ledger, sha, "new").returncode == 0
    wrong = run_ingest(ws, ledger, *args, "--approve", "f" * 64)
    assert wrong.returncode == 1 and "BLOCKED" in wrong.stderr
    assert not (ws / "papers/calculus/30002.json").exists()  # 零写入


def test_ingest_with_valid_credential_writes(tmp_path):
    ws = make_workspace(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    src = ws / "staging" / "papers" / "calculus" / "30002.json"
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    assert record(ws, ledger, sha, "new").returncode == 0
    ok = run_ingest(
        ws,
        ledger,
        "--subject",
        "calculus",
        "--file-id",
        "30002",
        "--staging",
        "staging",
        "--expected-sha",
        sha,
        "--approve",
        sha,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr
    dest = ws / "papers" / "calculus" / "30002.json"
    assert dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == sha
    # 幂等：同输入重复 apply 因凭据已消费被拒（单次有效）
    again = run_ingest(
        ws,
        ledger,
        "--subject",
        "calculus",
        "--file-id",
        "30002",
        "--staging",
        "staging",
        "--expected-sha",
        sha,
        "--approve",
        sha,
    )
    assert again.returncode == 1


def test_dry_run_skips_credential_and_writes_nothing(tmp_path):
    ws = make_workspace(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    src = ws / "staging" / "papers" / "calculus" / "30002.json"
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    dry = run_ingest(
        ws,
        ledger,
        "--subject",
        "calculus",
        "--file-id",
        "30002",
        "--staging",
        "staging",
        "--expected-sha",
        sha,
        "--dry-run",
    )
    assert dry.returncode == 0 and "DRY-RUN" in dry.stdout
    assert not (ws / "papers/calculus/30002.json").exists()
    assert not ledger.exists()  # 未触碰台账

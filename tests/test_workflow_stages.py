"""S4 回归：workflow 阶段层 plan/status/run/resume + 合成批次端到端（确定性核心）。

端到端：index → verify → check → merge-preview → (批准) merge-apply → gate。
agent/人工阶段（转录/外审发送等）由 skill 层推进，本层返回 pending。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import base64

import pytest  # noqa: E402

_SOURCES_PRESENT = (Path(__file__).resolve().parents[1] / "sources").exists()
needs_tools = pytest.mark.skipif(
    not _SOURCES_PRESENT, reason="成书工具链不在发布包内（TOOLS_PENDING 边界）"
)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from zhenti_pipeline.workflow.stages import STAGE_GRAPH, WorkflowRunner  # noqa: E402

# 1×1 真实 PNG（与 stage01 fixture 构建器同源；gate 做真实 PIL 解码）
VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    d = ws / "papers" / "calculus"
    (d / "images").mkdir(parents=True)
    (ws / "input").mkdir()
    (ws / "input" / "raw.txt").write_text("合成原料", encoding="utf-8")
    (ws / "config.json").write_text(json.dumps({"demo": True}), encoding="utf-8")
    (d / "textbook.json").write_text(
        json.dumps(
            {"sections": {"第一章": ["1.1 基础"], "第二章": ["2.1 进阶"]}}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    (d / "meta.json").write_text(
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
    paper = {
        "fileId": "30001",
        "kind": "final",
        "ab": None,
        "course": "微积分",
        "paperDisplay": "2025—2026学年第一学期《微积分》期末考试试卷",
        "sourceFile": "合成样卷第1页",
        "missing": [],
        "questions": [
            {
                "num": 1,
                "type": "choice",
                "subtype": "single",
                "chapter": {"label": "第一章", "section": "1.1 基础"},
                "desc": "求极限。",
                "options": [{"letter": "A", "text": "1"}, {"letter": "B", "text": "2"}],
                "answer": "A",
                "analysis": "由定义。",
                "images": [],
            },
            {
                "num": 2,
                "type": "open",
                "subtype": "",
                "chapter": {"label": "第二章", "section": "2.1 进阶"},
                "also_chapter": {"label": "第一章", "section": "1.1 基础"},
                "desc": "证明。",
                "options": [],
                "answer": "证毕。",
                "analysis": "略。",
                "images": [{"file": "30001-T2-1.png", "where": "desc"}],
            },
        ],
    }
    (d / "30001.json").write_text(
        json.dumps(paper, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (d / "images" / "30001-T2-1.png").write_bytes(VALID_PNG)
    return ws


def test_plan_lists_stage_graph_with_kinds(tmp_path):
    runner = WorkflowRunner(make_workspace(tmp_path), "calculus", "b1")
    plan = runner.plan()
    names = [s["stage"] for s in plan["stages"]]
    for expect in ("index", "verify", "check", "merge-preview", "merge-apply", "build", "publish"):
        assert expect in names
    kinds = {s["stage"]: s["kind"] for s in plan["stages"]}
    assert kinds["merge-apply"] == "approval-gated"
    assert kinds["transcribe"] == "agent/human"  # agent 阶段列出但不执行
    assert plan["initialized"] is False


def test_agent_stage_and_unknown_stage_pending_or_invalid(tmp_path):
    runner = WorkflowRunner(make_workspace(tmp_path), "calculus", "b1")
    assert runner.run_stage("transcribe").status == "pending"
    assert runner.run_stage("nope").status == "invalid-input"


@needs_tools
def test_e2e_deterministic_core(tmp_path):
    ws = make_workspace(tmp_path)
    runner = WorkflowRunner(ws, "calculus", "b1")

    assert runner.run_stage("index").status == "ok"  # 建run状态
    assert runner.run_stage("verify").status == "ok"  # 只读
    check = runner.run_stage("check")
    assert check.status == "ok" and check.data["stats"]["questions"] == 2

    # gate 在 bank 生成前是 pending（不是错误）
    assert runner.run_stage("gate").status == "pending"

    mp = runner.run_stage("merge-preview")
    assert mp.status == "ok"
    fingerprint = mp.data["fingerprint"]

    # 审批门：无 approve → pending；带指纹 → 执行器自核后写 bank
    assert runner.run_stage("merge-apply").status == "pending"
    apply_r = runner.run_stage("merge-apply", approve=fingerprint)
    assert apply_r.status == "ok", apply_r.detail
    bank = ws / "exam-compilation/exam-compilation/bank-data/calculus.json"
    assert bank.is_file()

    gate = runner.run_stage("gate")
    assert gate.status == "ok", gate.detail
    assert gate.data.get("ok") is True

    # 进度已记录：status 可读。注意重放较早阶段（gate）会把 nextStage 拨回其后续——
    # 各阶段幂等（预览/门禁只读），重放安全。
    st = runner.status()
    assert st["initialized"] and st["pausePoint"] == "gate"
    assert st["nextStage"] == "merge-preview"


def test_resume_continues_from_state(tmp_path):
    ws = make_workspace(tmp_path)
    runner = WorkflowRunner(ws, "calculus", "b1")
    runner.run_stage("index")
    r = runner.resume()
    assert r.status == "ok" and r.detail.startswith("resume→verify")
    assert runner.status()["pausePoint"] == "verify"


def test_resume_without_init_is_invalid(tmp_path):
    runner = WorkflowRunner(make_workspace(tmp_path), "calculus", "b1")
    assert runner.resume().status == "invalid-input"


def test_cli_workflow_plan_and_status(tmp_path):
    ws = make_workspace(tmp_path)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(REPO / "src")}
    base = [
        sys.executable,
        "-m",
        "zhenti_pipeline",
        "workflow",
        "--workspace",
        str(ws),
        "--subject",
        "calculus",
        "--batch-id",
        "b1",
    ]
    p = subprocess.run(
        base + ["plan"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(tmp_path),
        timeout=120,
    )
    assert p.returncode == 0, p.stderr
    env_json = json.loads(p.stdout)
    assert env_json["schemaVersion"] == 1 and len(env_json["data"]["stages"]) >= 9
    s = subprocess.run(
        base + ["status"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(tmp_path),
        timeout=120,
    )
    assert json.loads(s.stdout)["data"]["initialized"] is False


def test_stage_graph_order_is_stable():
    order = [s[0] for s in STAGE_GRAPH]
    assert order == [
        "index",
        "verify",
        "check",
        "gate",
        "merge-preview",
        "merge-apply",
        "errata",
        "build",
        "publish",
    ]

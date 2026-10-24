"""P0-A02/A03 回归：勘误执行器自核 approve、持久化事务、进程终止后恢复（APR-02/TX-01/02/03）。

沙箱布局（全部位于 tmp）：
  papers/calculus/…（合成卷，30001 T2 含双归属 also_chapter）
  exam-compilation/exam-compilation/tools/{make_book,source_resolver}.py（仓库快照副本，供 gate 渲染器相对路径）
  bank-data/calculus.json（由仓库快照 merge_papers 真实预览+apply 生成，保证镜像同构）
  errata.json + ledger
工具经 ZHENTI_* 环境变量指向仓库快照，绝不触碰生产安装目录与正式区（ISO-02/03）。
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SOURCES_PRESENT = (Path(__file__).resolve().parents[1] / "sources").exists()
pytestmark = [pytest.mark.skipif(not _SOURCES_PRESENT,
                reason="内部工具链快照（sources/）不在发布包内——私有证据层，公开 CI 不跑")]

REPO = Path(__file__).resolve().parents[1]
V2 = REPO / "sources" / "workflow" / "optimization" / "v2"
APPLY = V2 / "pipeline" / "apply_errata_v2.py"
APPROVALS = V2 / "pipeline" / "approvals.py"
CHECK = REPO / "sources" / "skills" / "zhenti-tiku" / "scripts" / "check_papers.py"
MERGE = REPO / "sources" / "skills" / "exam-compilation" / "scripts" / "merge_papers.py"
GATE = REPO / "sources" / "skills" / "exam-compilation" / "scripts" / "publication_gate.py"
PROJECT_TOOLS = REPO / "sources" / "exam-compilation-project" / "tools"

OLD = "旧解析待修。"
NEW = "修正后的解析。"
# 1×1 真实 PNG（与 stage01 fixture 构建器同源；gate 做真实 PIL 解码，必须是合法图）
import base64 as _b64
VALID_PNG = _b64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _write_papers(ws: Path):
    d = ws / "papers" / "calculus"
    (d / "images").mkdir(parents=True)
    (d / "textbook.json").write_text(json.dumps(
        {"sections": {"第一章": ["1.1 基础"], "第二章": ["2.1 进阶"]}}, ensure_ascii=False), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(
        {"subject": "微积分", "mockSource": "", "schemaVersion": 2,
         "taxonomyVersion": "demo-3ch"}, ensure_ascii=False), encoding="utf-8")
    paper = {
        "fileId": "30001", "kind": "final", "ab": None, "course": "微积分",
        "paperDisplay": "2025—2026学年第一学期《微积分》期末考试试卷",
        "sourceFile": "合成样卷第1页", "missing": [],
        "questions": [
            {"num": 1, "type": "choice", "subtype": "single",
             "chapter": {"label": "第一章", "section": "1.1 基础"},
             "desc": "求极限。", "options": [{"letter": "A", "text": "1"}, {"letter": "B", "text": "2"}],
             "answer": "A", "analysis": "由定义。", "images": []},
            {"num": 2, "type": "open", "subtype": "",
             "chapter": {"label": "第二章", "section": "2.1 进阶"},
             "also_chapter": {"label": "第一章", "section": "1.1 基础"},
             "desc": "证明单调有界。", "options": [], "answer": "证毕。", "analysis": OLD,
             "images": [{"file": "30001-T2-1.png", "where": "desc"}]},
        ],
    }
    (d / "30001.json").write_text(json.dumps(paper, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (d / "images" / "30001-T2-1.png").write_bytes(VALID_PNG)


def _seed_bank(ws: Path):
    """用快照 merge_papers 的真实预览+apply 生成 bank（镜像与 papers 同构）。"""
    bank_dir = ws / "exam-compilation" / "exam-compilation" / "bank-data"
    report = ws / "merge-preview.json"
    r = _run(ws, None, str(MERGE), "--papers-root", "papers", "--bank-dir",
             str(bank_dir.relative_to(ws)).replace("\\", "/"), "--subject", "calculus",
             "--report", str(report.relative_to(ws)).replace("\\", "/"))
    assert r.returncode == 0, r.stdout + r.stderr
    fp = json.loads(report.read_text(encoding="utf-8"))["fingerprint"]
    r = _run(ws, None, str(MERGE), "--papers-root", "papers", "--bank-dir",
             str(bank_dir.relative_to(ws)).replace("\\", "/"), "--subject", "calculus",
             "--report", str((ws / "merge-apply.json").relative_to(ws)).replace("\\", "/"),
             "--apply", "--approve", fp)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (bank_dir / "calculus.json").is_file()


def _env(ws: Path, ledger: Path | None):
    env = {**os.environ, "PYTHONUTF8": "1",
           "ZHENTI_CHECK_PAPERS": str(CHECK),
           "ZHENTI_MERGE_PAPERS": str(MERGE),
           "ZHENTI_PUBLICATION_GATE": str(GATE)}
    if ledger:
        env["APPROVALS_LEDGER"] = str(ledger)
    return env


def _run(ws: Path, ledger: Path | None, *argv, timeout=300):
    return subprocess.run([sys.executable, *[str(a) for a in argv]], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          cwd=str(ws), env=_env(ws, ledger), timeout=timeout)


def _make_table(ws: Path) -> Path:
    table = ws / "errata.json"
    table.write_text(json.dumps({
        "batchId": "b-errata-1",
        "items": [{"fileId": "30001", "num": 2, "field": "analysis",
                   "oldValue": OLD, "newValue": NEW, "anchor": OLD}],
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return table


def _digest_and_record(ws: Path, table: Path, ledger: Path) -> dict:
    r = _run(ws, ledger, APPLY, "digest", "--table", table, "--subject", "calculus")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    bp = (ws / "exam-compilation/exam-compilation/bank-data/calculus.json").resolve()
    rec = _run(ws, ledger, APPROVALS, "record", "--type", "errata-write",
               "--batch-id", "b-errata-1", "--preview-sha", d["tableDigest"],
               "--input-sha", d["papersSha"], "--old-target-sha", d["bankSha"],
               "--target", str(bp).replace("\\", "/"), "--evidence", "测试批复依据")
    assert rec.returncode == 0, rec.stderr
    return d


def _paper_analysis(ws: Path) -> str:
    p = json.loads((ws / "papers/calculus/30001.json").read_text(encoding="utf-8"))
    return next(q for q in p["questions"] if q["num"] == 2)["analysis"]


def _bank_analyses(ws: Path) -> list[str]:
    b = json.loads((ws / "exam-compilation/exam-compilation/bank-data/calculus.json").read_text(encoding="utf-8"))
    return [q["analysis"] for q in b["questions"]
            if q.get("fileId") == "30001" and q.get("num") == 2]


@pytest.fixture()
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    tools = ws / "exam-compilation" / "exam-compilation" / "tools"
    tools.mkdir(parents=True)
    shutil.copyfile(PROJECT_TOOLS / "make_book.py", tools / "make_book.py")
    shutil.copyfile(PROJECT_TOOLS / "source_resolver.py", tools / "source_resolver.py")
    _write_papers(ws)
    _seed_bank(ws)
    return ws


def test_apply_requires_approve_equal_to_digest(workspace, tmp_path):
    # APR-02 / P0-A02：先建有效凭据，再传错误 --approve → 拒绝、零写入、凭据未消费
    ws = workspace
    table = _make_table(ws)
    ledger = tmp_path / "ledger.jsonl"
    d = _digest_and_record(ws, table, ledger)
    bad = _run(ws, ledger, APPLY, "apply", "--table", table, "--subject", "calculus",
               "--approve", "f" * 64)
    assert bad.returncode == 2, bad.stdout + bad.stderr
    assert _paper_analysis(ws) == OLD and set(_bank_analyses(ws)) == {OLD}
    # 凭据未被误消费：verify 仍能成功输出指纹
    bp = (ws / "exam-compilation/exam-compilation/bank-data/calculus.json").resolve()
    v = _run(ws, ledger, APPROVALS, "verify", "--type", "errata-write", "--batch-id", "b-errata-1",
             "--preview-sha", d["tableDigest"], "--input-sha", d["papersSha"],
             "--old-target-sha", d["bankSha"], "--target", str(bp).replace("\\", "/"))
    assert v.returncode == 0, v.stderr
    # 拒绝发生在 journal 创建之前：本表不应存在任何事务痕迹
    assert not (ws / "errata.journal.json").exists()


def test_apply_happy_path_commits_transaction(workspace, tmp_path):
    ws = workspace
    table = _make_table(ws)
    ledger = tmp_path / "ledger.jsonl"
    d = _digest_and_record(ws, table, ledger)
    ok = _run(ws, ledger, APPLY, "apply", "--table", table, "--subject", "calculus",
              "--approve", d["tableDigest"])
    assert ok.returncode == 0, ok.stdout + ok.stderr
    out = json.loads(ok.stdout)
    assert out["ok"] is True and out["items"] == 1
    assert out["bankRecords"] == 2  # 主记录 + -x2 双归属副本都改到
    assert _paper_analysis(ws) == NEW
    assert set(_bank_analyses(ws)) == {NEW}
    j = json.loads((ws / "errata.journal.json").read_text(encoding="utf-8"))
    assert j["state"] == "committed"
    # 凭据单次有效：重复 verify 被拒
    bp = (ws / "exam-compilation/exam-compilation/bank-data/calculus.json").resolve()
    v = _run(ws, ledger, APPROVALS, "verify", "--type", "errata-write", "--batch-id", "b-errata-1",
             "--preview-sha", d["tableDigest"], "--input-sha", d["papersSha"],
             "--old-target-sha", d["bankSha"], "--target", str(bp).replace("\\", "/"))
    assert v.returncode == 1 and "已消费" in v.stderr


def test_crash_after_papers_then_recover(workspace, tmp_path):
    # TX-01：papers 写后进程被终止 → 恢复后双侧一致（回滚到写前）
    ws = workspace
    table = _make_table(ws)
    ledger = tmp_path / "ledger.jsonl"
    d = _digest_and_record(ws, table, ledger)
    killed = _run(ws, ledger, APPLY, "apply", "--table", table, "--subject", "calculus",
                  "--approve", d["tableDigest"], "--fault-after-papers-kill")
    assert killed.returncode == 137  # 模拟进程终止
    assert _paper_analysis(ws) == NEW and set(_bank_analyses(ws)) == {OLD}  # 半写状态
    # active journal 阻断其他模式（不盲目重放）
    blk = _run(ws, ledger, APPLY, "check", "--table", table, "--subject", "calculus")
    assert blk.returncode == 3 and "recover" in blk.stderr
    rec = _run(ws, ledger, APPLY, "recover", "--table", table)
    assert rec.returncode == 0, rec.stdout + rec.stderr
    assert json.loads(rec.stdout)["action"] == "rolled-back"
    assert _paper_analysis(ws) == OLD and set(_bank_analyses(ws)) == {OLD}  # 双侧一致
    j = json.loads((ws / "errata.journal.json").read_text(encoding="utf-8"))
    assert j["state"] == "rolled-back"
    # TX-02：恢复可重复（再次 recover 无动作）
    again = _run(ws, ledger, APPLY, "recover", "--table", table)
    assert again.returncode == 0 and json.loads(again.stdout)["action"] == "none"
    # TX-03：凭据已消费不恢复——重新 apply 被拒，文件不动
    redo = _run(ws, ledger, APPLY, "apply", "--table", table, "--subject", "calculus",
                "--approve", d["tableDigest"])
    assert redo.returncode == 1
    assert _paper_analysis(ws) == OLD and set(_bank_analyses(ws)) == {OLD}


def test_crash_after_bank_then_recover(workspace, tmp_path):
    # TX-01：bank 写后进程被终止 → 恢复后双侧一致
    ws = workspace
    table = _make_table(ws)
    ledger = tmp_path / "ledger.jsonl"
    d = _digest_and_record(ws, table, ledger)
    killed = _run(ws, ledger, APPLY, "apply", "--table", table, "--subject", "calculus",
                  "--approve", d["tableDigest"], "--fault-after-bank-kill")
    assert killed.returncode == 137
    assert _paper_analysis(ws) == NEW and set(_bank_analyses(ws)) == {NEW}
    rec = _run(ws, ledger, APPLY, "recover", "--table", table)
    assert rec.returncode == 0
    assert json.loads(rec.stdout)["action"] == "rolled-back"
    assert _paper_analysis(ws) == OLD and set(_bank_analyses(ws)) == {OLD}


def test_simulated_failure_flags_rollback_in_place(workspace, tmp_path):
    # 原有 --fault-after-*（模拟失败并回滚）语义保留
    ws = workspace
    table = _make_table(ws)
    ledger = tmp_path / "ledger.jsonl"
    d = _digest_and_record(ws, table, ledger)
    r = _run(ws, ledger, APPLY, "apply", "--table", table, "--subject", "calculus",
             "--approve", d["tableDigest"], "--fault-after-papers")
    assert r.returncode == 1 and "BLOCKED" in r.stderr
    assert _paper_analysis(ws) == OLD and set(_bank_analyses(ws)) == {OLD}
    j = json.loads((ws / "errata.journal.json").read_text(encoding="utf-8"))
    assert j["state"] == "rolled-back"

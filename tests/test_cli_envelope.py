"""S3 回归：CLI envelope、显式 workspace 与 CWD 无关性（CFG-01/02）。

dev 布局下包经仓库 src/ 导入（PYTHONPATH 注入子进程）；真实 pip 安装复验属 S6（PKG-01）。
"""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def demo_workspace(tmp_path: Path) -> Path:
    """合成 workspace（目录名含中文与空格，CFG-02），papers/calculus 与 S1 合成数据同构。"""
    ws = tmp_path / "工作区 demo"
    d = ws / "papers" / "calculus"
    (d / "images").mkdir(parents=True)
    (d / "textbook.json").write_text(json.dumps(
        {"sections": {"第一章": ["1.1 基础"], "第二章": ["2.1 进阶"]}}, ensure_ascii=False), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(
        {"subject": "微积分", "mockSource": ""}, ensure_ascii=False), encoding="utf-8")
    paper = {
        "fileId": "30001", "kind": "final", "ab": None, "course": "微积分",
        "paperDisplay": "2025—2026学年第一学期《微积分》期末考试试卷",
        "sourceFile": "合成样卷第1页", "missing": [],
        "questions": [
            {"num": 1, "type": "choice", "subtype": "single",
             "chapter": {"label": "第一章", "section": "1.1 基础"},
             "desc": "求 $1+1$ 的值。", "options": [{"letter": "A", "text": "2"}, {"letter": "B", "text": "3"}],
             "answer": "A", "analysis": "由算术。", "images": []},
        ],
    }
    (d / "30001.json").write_text(json.dumps(paper, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (d / "images" / "30001-T1-1.png").write_bytes(VALID_PNG)
    return ws


def run_cli(cwd: Path, *argv):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(REPO / "src")}
    return subprocess.run([sys.executable, "-m", "zhenti_pipeline", *argv], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", cwd=str(cwd),
                          env=env, timeout=120)


def test_envelope_shape_and_ok_path(tmp_path):
    ws = demo_workspace(tmp_path)
    r = run_cli(REPO, "check-papers", "--workspace", str(ws), "--subject", "calculus")
    assert r.returncode == 0, r.stderr
    env = json.loads(r.stdout)  # stdout 恰为一个 JSON 文档
    assert set(env) == {"schemaVersion", "ok", "status", "data", "errors", "warnings", "artifacts"}
    assert env["schemaVersion"] == 1 and env["ok"] is True and env["status"] == "ok"
    assert env["data"]["stats"]["questions"] == 1


def test_cwd_independence_identical_output(tmp_path):
    # CFG-02：不同 CWD 调用同一 workspace，结果逐字节一致
    ws = demo_workspace(tmp_path)
    a = run_cli(REPO, "check-papers", "--workspace", str(ws), "--subject", "calculus")
    b = run_cli(tmp_path, "check-papers", "--workspace", str(ws), "--subject", "calculus")
    other = tmp_path / "另外的目录"
    other.mkdir()
    c = run_cli(other, "check-papers", "--workspace", str(ws), "--subject", "calculus")
    assert a.returncode == b.returncode == c.returncode == 0
    assert a.stdout == b.stdout == c.stdout


def test_missing_subject_fails_without_fallback(tmp_path):
    # CFG-01：缺 subject 准确报错，不回落历史科目
    ws = demo_workspace(tmp_path)
    r = run_cli(REPO, "check-papers", "--workspace", str(ws))
    assert r.returncode == 2
    assert "--subject" in r.stderr
    nosuch = run_cli(REPO, "check-papers", "--workspace", str(ws), "--subject", "no-such-subject")
    assert nosuch.returncode == 2
    assert "不存在" in nosuch.stdout and "no-such-subject" in nosuch.stdout


def test_check_papers_blocks_on_bad_data_and_reports(tmp_path):
    ws = demo_workspace(tmp_path)
    p = ws / "papers" / "calculus" / "30001.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["questions"][0]["answer"] = ""  # 缺答案未登记 missing
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    report = tmp_path / "out" / "report.json"
    r = run_cli(REPO, "check-papers", "--workspace", str(ws), "--subject", "calculus",
                "--json-report", str(report))
    assert r.returncode == 1
    env = json.loads(r.stdout)
    assert env["status"] == "blocked" and any("未登记 missing" in e for e in env["errors"])
    assert report.is_file() and env["artifacts"]  # 报告落盘且登记在 artifacts


def test_legacy_inspect_reports_unknown_fields_readonly(tmp_path):
    ws = demo_workspace(tmp_path)
    p = ws / "papers" / "calculus" / "30001.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["legacyExtra"] = {"oldBatch": True}          # 卷级未知字段
    data["questions"][0]["qaNote"] = "人工备注"        # 题目级未知字段
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    before = p.read_bytes()
    r = run_cli(REPO, "legacy-inspect", "--workspace", str(ws), "--subject", "calculus")
    assert r.returncode == 0, r.stdout + r.stderr
    env = json.loads(r.stdout)
    assert env["data"]["papers"]["30001.json"]["unknownPaperFields"] == ["legacyExtra"]
    assert env["data"]["papers"]["30001.json"]["unknownQuestionFields"] == {"1": ["qaNote"]}
    assert p.read_bytes() == before  # 只读：文件零变化

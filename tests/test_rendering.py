"""S5 渲染层回归：真实 XeLaTeX 构建、PDF 结构对账（PDF-01）、视觉抽样、原子发布。

需要本机 TeX 工具链（xelatex/pdfinfo，见 docs/contracts/environment.md）；无工具链时
显式跳过并说明（环境证据，不冒充通过）。模块级 fixture 只构建一次。
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from zhenti_pipeline.workflow.stages import WorkflowRunner  # noqa: E402
from test_workflow_stages import make_workspace  # noqa: E402  # 合成 workspace 复用

TEXBIN = r"C:\texlive\2026\bin\windows"
HAVE_TEX = (Path(TEXBIN) / "xelatex.exe").is_file() or shutil.which("xelatex")
BUILD_PUBLISH = REPO / "sources" / "workflow" / "optimization" / "v2" / "build-publish"
APPROVALS = REPO / "sources" / "workflow" / "optimization" / "v2" / "pipeline" / "approvals.py"

import pytest  # noqa: E402

_SOURCES_PRESENT = (Path(__file__).resolve().parents[1] / "sources").exists()
pytestmark = [
    pytest.mark.rendering,
    pytest.mark.skipif(not HAVE_TEX, reason="需要真实 XeLaTeX 工具链（渲染层环境证据）"),
    pytest.mark.skipif(
        not _SOURCES_PRESENT, reason="内部工具链快照（sources/）不在发布包内——私有证据层"
    ),
]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """合成 calculus 科目走完 index→merge-apply→build，产物供本模块全部用例复用。"""
    tmp = tmp_path_factory.mktemp("s5-render")
    ws = make_workspace(tmp)
    env = (
        {"PATH": TEXBIN + os.pathsep + os.environ.get("PATH", "")}
        if (Path(TEXBIN) / "xelatex.exe").is_file()
        else {}
    )
    runner = WorkflowRunner(ws, "calculus", "b1", env=env)
    runner.run_stage("index")
    mp = runner.run_stage("merge-preview")
    assert runner.run_stage("merge-apply", approve=mp.data["fingerprint"]).status == "ok"
    b = runner.run_stage("build")
    assert b.status == "ok", b.detail
    return {"ws": ws, "runner": runner, "build": b.data, "env": env}


def _run(ws, env, *argv, timeout=300):
    e = {**os.environ, "PYTHONUTF8": "1", **({"PATH": env["PATH"]} if env else {})}
    return subprocess.run(
        [sys.executable, *[str(a) for a in argv]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ws),
        env=e,
        timeout=timeout,
    )


def test_build_is_stable_and_reported(built):
    data = built["build"]
    assert data["ok"] is True and data["stable"] is True
    assert data["passes"] >= 2 and data["pages"] > 0
    report = json.loads((built["runner"].run_dir / "build-report.json").read_text(encoding="utf-8"))
    assert report["blocked"] in (None, []) and report["texErrors"] == []
    assert report["pdfSha256"] == data["sha256"]


def test_pdf_structure_audit_matches_bank(built):
    # PDF-01：封面原题数/正文收录数/答案来源/题号映射逐项一致
    ws = built["ws"]
    out = built["runner"].run_dir / "build"
    tex = sorted(out.glob("*.tex"))[0]
    a = _run(
        ws,
        built["env"],
        BUILD_PUBLISH / "audit_structure.py",
        "--bank",
        ws / "exam-compilation/exam-compilation/bank-data/calculus.json",
        "--tex",
        tex,
        "--pdf",
        built["build"]["pdf"],
    )
    assert a.returncode == 0, a.stdout + a.stderr
    rep = json.loads(a.stdout)
    assert rep["problems"] == []
    assert rep["uniqueOriginals"] == 2  # (30001,1) 与 (30001,2)
    assert rep["placements"] == 3  # 含 1 个合法双归属收录
    assert rep["legalDuals"] == 1
    assert rep["solnumContinuous"] is True and rep["sourceLines"] == rep["placements"]


def test_visual_sample_renders_all_pages(built):
    ws = built["ws"]
    v = _run(
        ws,
        built["env"],
        BUILD_PUBLISH / "visual_sample.py",
        "--pdf",
        built["build"]["pdf"],
        "--out-dir",
        ws / "visual",
    )
    assert v.returncode == 0, v.stderr
    res = json.loads(v.stdout)
    assert res["ok"] is True and res["sampled"] == res["pages"] == built["build"]["pages"]
    pngs = sorted((ws / "visual").glob("p-*.png"))
    assert len(pngs) == built["build"]["pages"]
    assert all(p.stat().st_size > 1000 for p in pngs)


def test_publish_atomic_with_credential(built, tmp_path):
    ws = built["ws"]
    pdf = Path(built["build"]["pdf"])
    target_dir = ws / "exam-compilation/exam-compilation/book"
    target = target_dir / "calculus-book.pdf"
    ledger = tmp_path / "ledger.jsonl"
    env = {**built["env"], "APPROVALS_LEDGER": str(ledger)}

    def run_pub(*extra):
        e = {**os.environ, "PYTHONUTF8": "1", **env}
        return subprocess.run(
            [
                sys.executable,
                str(BUILD_PUBLISH / "publish_book.py"),
                "--pdf",
                pdf,
                "--subject",
                "calculus",
                "--target-dir",
                target_dir.relative_to(ws).as_posix(),
                *extra,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ws),
            env=e,
            timeout=120,
        )

    # dry-run：零写入
    dry = run_pub()
    assert dry.returncode == 0 and "DRY-RUN" in dry.stdout
    assert not target.exists()

    # 凭据：preview=隔离 PDF sha，old-target=new，target=正式路径
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    rec = subprocess.run(
        [
            sys.executable,
            str(APPROVALS),
            "record",
            "--type",
            "publish",
            "--batch-id",
            "calculus",
            "--preview-sha",
            sha,
            "--input-sha",
            sha,
            "--old-target-sha",
            "new",
            "--target",
            "exam-compilation/exam-compilation/book/calculus-book.pdf",
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
    assert rec.returncode == 0, rec.stderr

    ok = run_pub("--apply", "--approve", sha)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == sha

    # 单次有效：重复 apply 被拒（凭据已消费），旧成品不动
    again = run_pub("--apply", "--approve", sha)
    assert again.returncode == 1 and "已消费" in (again.stderr + again.stdout)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == sha

"""S3 回归：包单一实现与薄包装合同。

- 旧路径导入与包内实现一致（去掉重复副本后旧入口仍可用）；
- papers-v2 schema（结构层）与 check_papers（语义层）分工：schema 过 ≠ 语义过。
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SOURCES_PRESENT = (Path(__file__).resolve().parents[1] / "sources").exists()
needs_sources = pytest.mark.skipif(not _SOURCES_PRESENT, reason="内部工具链快照不在发布包内")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from zhenti_pipeline import __version__  # noqa: E402
from zhenti_pipeline.domain import check_papers, source_resolver  # noqa: E402
from zhenti_pipeline.storage import filelock, handoff_state, run_state, safe_io, approvals  # noqa: E402


def test_package_version_and_modules():
    assert __version__
    for mod in (
        check_papers,
        source_resolver,
        filelock,
        handoff_state,
        run_state,
        safe_io,
        approvals,
    ):
        assert mod.__name__.startswith("zhenti_pipeline.")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@needs_sources
def test_wrappers_delegate_to_package():
    """旧入口包装应暴露与包相同的实现对象（单一实现，不再有第二份代码）。"""
    for rel, pkgmod, attr in [
        ("sources/skills/exam-compilation/scripts/check_papers.py", check_papers, "audit"),
        ("sources/skills/zhenti-tiku/scripts/check_papers.py", check_papers, "audit"),
        ("sources/skills/exam-compilation/scripts/safe_io.py", safe_io, "safe_replace"),
        ("sources/skills/exam-compilation/scripts/source_resolver.py", source_resolver, "resolve"),
        ("sources/workflow/optimization/v2/pipeline/filelock.py", filelock, "exclusive_lock"),
        ("sources/workflow/optimization/v2/pipeline/approvals.py", approvals, "main"),
        ("sources/workflow/optimization/v2/pipeline/run_state.py", run_state, "main"),
    ]:
        wrapper = _load(REPO / rel, "wrap_" + pkgmod.__name__.replace(".", "_"))
        assert getattr(wrapper, attr) is getattr(pkgmod, attr), rel


@needs_sources
def test_duplicate_legacy_paths_are_gone():
    # 曾字节级重复的 5 对副本，现在都应是包装（<100 行）或删除，不得再有第二份实现
    for rel in [
        "sources/skills/zhenti-tiku/scripts/safe_io.py",
        "sources/skills/exam-compilation/scripts/safe_io.py",
        "sources/skills/zhenti-tiku/scripts/check_papers.py",
        "sources/skills/exam-compilation/scripts/check_papers.py",
        "sources/skills/zhenti-tiku/scripts/handoff_state.py",
        "sources/skills/exam-compilation/scripts/handoff_state.py",
        "sources/skills/exam-compilation/scripts/source_resolver.py",
    ]:
        lines = (REPO / rel).read_text(encoding="utf-8").count("\n")
        assert lines < 30, f"{rel} 应为薄包装，实际 {lines} 行"


def test_schema_structure_layer_vs_semantics(tmp_path):
    pytest.importorskip("jsonschema")
    import jsonschema

    schema = json.loads((REPO / "schemas" / "papers-v2.schema.json").read_text(encoding="utf-8"))
    # 结构合法但语义非法：答案为空且 missing 未登记 → schema 过、check_papers 拒
    paper = {
        "fileId": "30001",
        "kind": "final",
        "ab": None,
        "paperDisplay": "2025—2026学年第一学期《演示》期末考试试卷",
        "missing": [],
        "questions": [
            {
                "num": 1,
                "type": "open",
                "subtype": "",
                "chapter": {"label": "第一章"},
                "desc": "题干",
                "options": [],
                "answer": "",
                "analysis": "",
                "images": [],
            }
        ],
    }
    jsonschema.validate(paper, schema)  # 结构层通过
    d = tmp_path / "papers" / "demo"
    d.mkdir(parents=True)
    (d / "textbook.json").write_text(json.dumps({"sections": {"第一章": []}}), encoding="utf-8")
    (d / "30001.json").write_text(json.dumps(paper, ensure_ascii=False), encoding="utf-8")
    result = check_papers.audit(d)
    assert not result["ok"] and any("missing" in e for e in result["errors"])  # 语义层拦截


def test_schema_rejects_structural_violations():
    pytest.importorskip("jsonschema")
    import jsonschema

    schema = json.loads((REPO / "schemas" / "papers-v2.schema.json").read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"fileId": "../evil", "kind": "final", "paperDisplay": "x", "questions": []}, schema
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {
                "fileId": "30001",
                "kind": "weekly",
                "paperDisplay": "x",
                "questions": [{"num": 1, "type": "open", "chapter": {"label": "一"}, "desc": "d"}],
            },
            schema,
        )

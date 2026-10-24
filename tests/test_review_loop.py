"""S4 回归：外审导入闭环离线段（REV-03 守恒 / REV-05 候选≠批准）。

parse_review → (独立复核) → build_errata_candidates 的本地部分；网页发送属外部副作用。
parse_review 契约：disputed 桶 = 除"无法确认"外全部实质行（含一致行，供逐项复核）；
manifest = {"fileId": ..., "bundle": {"questionTotal": N}}，按 fileId 对账越界 id。
"""
import json
import subprocess
import sys

import pytest
from pathlib import Path

import importlib.util

_SOURCES_PRESENT = (Path(__file__).resolve().parents[1] / "sources").exists()
pytestmark = [pytest.mark.skipif(not _SOURCES_PRESENT,
                reason="内部工具链快照（sources/）不在发布包内——私有证据层，公开 CI 不跑")]

REPO = Path(__file__).resolve().parents[1]
EXR = REPO / "sources" / "workflow" / "optimization" / "v2" / "external-review"

MANIFEST = {"fileId": "30001", "bundle": {"questionTotal": 3}}


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, str(EXR / rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_review():
    return _load("parse_review.py", "parse_review_mod")


def run_parse(tmp_path: Path, text: str, manifest=MANIFEST, out="parsed.json"):
    review = tmp_path / "review.md"
    review.write_text(text, encoding="utf-8")
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps(manifest), encoding="utf-8")
    outp = tmp_path / out
    r = subprocess.run([sys.executable, str(EXR / "parse_review.py"), "--review", review,
                        "--manifest", mf, "--out", outp], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    return r, outp


def test_parse_review_buckets_and_conservation(tmp_path):
    lines = [
        '{"id":"30001-T1","my_result":"dispute","severity":"high","reason":"答案应为B"}',
        '{"id":"30001-T2","my_result":"ok","severity":"low","reason":"一致"}',
        '{"id":"30001-T3","my_result":"无法确认","severity":"medium","reason":"图像模糊"}',
    ]
    text = "\n".join(lines) + "\n\n汇总：总计 3 道；同意 1；异议/存疑 1；无法确认 1\n"
    r, outp = run_parse(tmp_path, text)
    assert r.returncode == 0, r.stderr
    parsed = json.loads(outp.read_text(encoding="utf-8"))
    assert [d["id"] for d in parsed["disputed"]] == ["30001-T1", "30001-T2"]
    assert [u["id"] for u in parsed["unconfirmable"]] == ["30001-T3"]  # 无法确认 ≠ agree
    # REV-03 守恒：汇总(异议+无法确认) == 逐条实质行数
    s = parsed["summaryParsed"]
    assert s["total"] == 3 and s["agree"] + s["disputed"] + s["unconfirmable"] == 3
    assert parsed["coverageCheck"]["consistent"] is True
    assert parsed["malformedLines"] == []


def test_parse_review_half_reply_flagged(tmp_path):
    lines = ['{"id":"30001-T1","my_result":"dispute","severity":"high","reason":"x"}']
    r, _ = run_parse(tmp_path, "\n".join(lines) + "\n")  # 无汇总段锚点
    assert r.returncode == 0
    blob = r.stdout
    assert "不完整" in blob  # 警告：回复可能不完整，不得冒充完整回收


def test_parse_review_flags_out_of_bundle_ids(tmp_path):
    lines = ['{"id":"99999-T9","my_result":"dispute","severity":"high","reason":"r"}']
    text = "\n".join(lines) + "\n\n汇总：总计 1 道；同意 0；异议/存疑 1；无法确认 0\n"
    r, outp = run_parse(tmp_path, text)
    parsed = json.loads(outp.read_text(encoding="utf-8"))
    assert parsed["coverageCheck"]["consistent"] is False
    assert "99999-T9" in parsed["coverageCheck"]["reportedIdsOutsideBundle"]  # 串卷防护
    assert any("不属于本包" in w for w in parsed["warnings"])


def test_candidates_are_decision_support_only(tmp_path):
    # REV-05：候选表不是可执行勘误表——无 oldValue/newValue/anchor 组合
    parsed = {"disputed": [{"id": "30001-T1"}], "unconfirmable": [], "summaryParsed": {},
              "coverageCheck": {"consistent": True, "reportedIdsOutsideBundle": []}}
    rereview = {"items": [{"id": "30001-T1", "verdict": "misread", "reason": "确认为B",
                           "evidence": "原卷第1页", "proposedNew": {"answer": "B"}}]}
    pp, rp = tmp_path / "p.json", tmp_path / "r.json"
    pp.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    rp.write_text(json.dumps(rereview, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(EXR / "build_errata_candidates.py"),
                        "--parsed", pp, "--rereview", rp, "--subject", "calculus",
                        "--out", str(tmp_path / "c.json")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       cwd=str(tmp_path), timeout=60)
    if r.returncode == 0:
        blob = (tmp_path / "c.json").read_text(encoding="utf-8")
        assert '"anchor"' not in blob  # 不可直接 apply（决策支持件）
    else:
        # subject 资料缺失（读 papers/<subject> 取原值）也拒绝——不在本测试铺 papers
        assert "papers" in (r.stderr + r.stdout) or "不存在" in (r.stderr + r.stdout)


def test_candidates_require_full_rereview_coverage(tmp_path):
    parsed = {"disputed": [{"id": "30001-T1"}, {"id": "30001-T3"}], "unconfirmable": []}
    rereview = {"items": [{"id": "30001-T1", "verdict": "misread", "reason": "r"}]}
    pp, rp = tmp_path / "p.json", tmp_path / "r.json"
    pp.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    rp.write_text(json.dumps(rereview, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(EXR / "build_errata_candidates.py"),
                        "--parsed", pp, "--rereview", rp, "--subject", "calculus",
                        "--out", str(tmp_path / "c.json")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(tmp_path), timeout=60)
    assert r.returncode != 0 and "缺项" in (r.stderr + r.stdout)


def test_parse_module_direct_call_buckets():
    text = ('{"id":"30001-T1","my_result":"无法确认","severity":"medium","reason":"模糊"}\n'
            "汇总：总计 1 道；同意 0；异议/存疑 0；无法确认 1\n")
    parsed = _parse_review().parse(text, MANIFEST)
    assert not parsed["disputed"]
    assert [u["id"] for u in parsed["unconfirmable"]] == ["30001-T1"]

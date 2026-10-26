"""合成 papers 项目 + 失败复现（S1）。

在 tmp_path 构造自制演示科目 papers 目录，验证只读检查 check_papers.audit：
- 合法项目通过；合法双归属（also_chapter）保留且计入 cross_chapter；
- 各类坏数据被准确定位（重复 num / missing 未登记 / missing 多登记 /
  图片路径越界 / 未注册章节 / Markdown 残留）。
全部写入临时目录，不触碰正式区（ISO-02）。
"""

import base64
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SCRIPT = REPO / "sources" / "skills" / "exam-compilation" / "scripts" / "check_papers.py"

import pytest

pytestmark = pytest.mark.skipif(
    not _SCRIPT.is_file(), reason="内部工具链快照（sources/）不在发布包内——私有证据层"
)


def _check_papers():
    spec = importlib.util.spec_from_file_location("check_papers_s1", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 1×1 真实 PNG（与 stage01 fixture 构建器同源，PIL 可解码）
VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

TEXTBOOK = {"sections": {"第一章": ["1.1 基础"], "第二章": ["2.1 进阶"]}}
META = {"subject": "demo", "mockSource": ""}


def paper(extra_q=None, missing=None):
    questions = [
        {
            "num": 1,
            "type": "choice",
            "subtype": "single",
            "chapter": {"label": "第一章", "section": "1.1 基础"},
            "desc": "求 $1+1$ 的值。",
            "options": [{"letter": "A", "text": "2"}, {"letter": "B", "text": "3"}],
            "answer": "A",
            "analysis": "由算术可知选 A。",
            "images": [],
        },
        {
            "num": 2,
            "type": "open",
            "subtype": "",
            "chapter": {"label": "第二章", "section": "2.1 进阶"},
            "desc": "证明单调性。",
            "options": [],
            "answer": "证明如下。",
            "analysis": "略。",
            "images": [],
        },
    ]
    if extra_q:
        questions.extend(extra_q)
    return {
        "fileId": "30001",
        "kind": "final",
        "ab": None,
        "course": "演示科目",
        "sourceFile": "合成样卷第1页",
        "paperDisplay": "2025—2026学年第一学期《演示科目》期末考试试卷",
        "missing": missing or [],
        "questions": questions,
    }


def write_project(tmp_path, paper_obj):
    d = tmp_path / "papers" / "demo"
    (d / "images").mkdir(parents=True)
    (d / "textbook.json").write_text(json.dumps(TEXTBOOK, ensure_ascii=False), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(META, ensure_ascii=False), encoding="utf-8")
    (d / "30001.json").write_text(json.dumps(paper_obj, ensure_ascii=False), encoding="utf-8")
    (d / "images" / "30001-T2-1.png").write_bytes(VALID_PNG)
    return d


def test_valid_synthetic_project_passes(tmp_path):
    result = _check_papers().audit(write_project(tmp_path, paper()))
    assert result["ok"], result["errors"]
    assert result["stats"]["files"] == 1
    assert result["stats"]["questions"] == 2
    assert result["stats"]["missing"] == 0


def test_legal_dual_attribution_is_kept(tmp_path):
    p = paper(extra_q=[])
    p["questions"][1]["also_chapter"] = {"label": "第一章", "section": "1.1 基础"}
    result = _check_papers().audit(write_project(tmp_path, p))
    assert result["ok"], result["errors"]
    assert result["stats"]["cross_chapter"] == 1  # 原题数不变，收录次数另计


def test_duplicate_num_is_rejected(tmp_path):
    p = paper(extra_q=[dict(paper()["questions"][0])])  # 同 num=1 重复出现
    result = _check_papers().audit(write_project(tmp_path, p))
    assert not result["ok"]
    assert any("num 重复" in e and "also_chapter" in e for e in result["errors"])


def test_unregistered_missing_is_rejected(tmp_path):
    p = paper()
    p["questions"][0]["answer"] = ""  # 答案为空但 missing 未登记
    result = _check_papers().audit(write_project(tmp_path, p))
    assert not result["ok"]
    assert any("未登记 missing" in e for e in result["errors"])


def test_overregistered_missing_is_rejected(tmp_path):
    result = _check_papers().audit(write_project(tmp_path, paper(missing=[3])))
    assert not result["ok"]
    assert any("missing 多登记" in e for e in result["errors"])


def test_image_path_escape_is_rejected(tmp_path):
    p = paper()
    p["questions"][1]["images"] = [{"file": "../evil.png", "where": "desc"}]
    result = _check_papers().audit(write_project(tmp_path, p))
    assert not result["ok"]
    assert any("路径越界" in e or "非法" in e for e in result["errors"])


def test_unregistered_chapter_is_rejected(tmp_path):
    p = paper()
    p["questions"][0]["chapter"] = {"label": "第三章", "section": "3.1"}
    result = _check_papers().audit(write_project(tmp_path, p))
    assert not result["ok"]
    assert any("不在 textbook.sections" in e for e in result["errors"])


def test_markdown_residue_is_rejected(tmp_path):
    p = paper()
    p["questions"][0]["desc"] = "## 残留标题\n求 $1+1$ 的值。"
    result = _check_papers().audit(write_project(tmp_path, p))
    assert not result["ok"]
    assert any("Markdown 残留" in e for e in result["errors"])

"""S4 回归：MinerU 备料适配器（A06 契约 / A07 缓存键），全程离线（uploader 注入替身）。"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from zhenti_pipeline.adapters import mineru  # noqa: E402

# 最小合法 PNG 字节（内容不必可解码：备料层只做闭包/缓存管理，解码属 gate/validate 层）
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "input"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"%PDF-1.4 fake-A")
    (root / "a.jpg").write_bytes(b"\xff\xd8 fake-JPEG")       # 同名不同格式（OCR-01）
    (root / "sub").mkdir(exist_ok=True)
    (root / "sub" / "b.pdf").write_bytes(b"%PDF-1.4 fake-B")  # 递归
    return root


def fake_uploader(ok=True):
    def upload(src, pkg, model, ocr):
        if not ok:
            return False, "fake failure"
        (pkg / f"{src.stem}.md").write_text(f"# {src.stem}\n\n正文", encoding="utf-8")
        return True, ""
    return upload


def test_contract_arrays_and_recursive_discovery(tmp_path):
    root = make_root(tmp_path)
    out = mineru.prepare(root, uploader=fake_uploader())
    assert out["ok"] is True
    # A06：parsed/skipped/needsCheck/failed 均为数组（旧 dwf 曾声明为数字）
    for k in ("parsed", "skipped", "needsCheck", "failed"):
        assert isinstance(out[k], list), k
    assert {p["file"] for p in out["parsed"]} == {"a.pdf", "a.jpg", "sub/b.pdf"}


def test_same_stem_different_format_no_collision(tmp_path):
    # A07：缓存键含源哈希——a.pdf 与 a.jpg 同 stem 不碰撞，各自独立缓存
    root = make_root(tmp_path)
    out = mineru.prepare(root, uploader=fake_uploader())
    keys = {p["file"]: p["cacheKey"] for p in out["parsed"]}
    assert keys["a.pdf"] != keys["a.jpg"]
    again = mineru.prepare(root, uploader=fake_uploader())
    assert {p["file"] for p in again["skipped"]} == {"a.pdf", "a.jpg", "sub/b.pdf"}
    assert again["parsed"] == [] and again["failed"] == []


def test_source_change_invalidates_cache(tmp_path):
    root = make_root(tmp_path)
    mineru.prepare(root, uploader=fake_uploader())
    (root / "a.pdf").write_bytes(b"%PDF-1.4 CHANGED-CONTENT")
    out = mineru.prepare(root, uploader=fake_uploader())
    assert {"a.pdf"} <= {p["file"] for p in out["parsed"]}  # 源变→重新解析
    assert {"a.jpg", "sub/b.pdf"} <= {p["file"] for p in out["skipped"]}


def test_option_change_invalidates_cache(tmp_path):
    root = make_root(tmp_path)
    mineru.prepare(root, uploader=fake_uploader(), model="vlm")
    out = mineru.prepare(root, uploader=fake_uploader(), model="pipeline")
    assert {p["file"] for p in out["parsed"]} == {"a.pdf", "a.jpg", "sub/b.pdf"}


def test_legacy_layout_marked_needs_check_not_reused(tmp_path):
    root = make_root(tmp_path)
    legacy = root / "mineru" / "a" / "auto"
    legacy.mkdir(parents=True)
    (legacy / "full.md").write_text("# 旧布局产物", encoding="utf-8")
    out = mineru.prepare(root, uploader=fake_uploader())
    assert {"a.pdf"} <= {p["file"] for p in out["needsCheck"]}  # 缺凭据不冒充已备料


def test_missing_image_closure_fails(tmp_path):
    root = make_root(tmp_path)
    (root / "a.pdf").unlink()
    (root / "a.jpg").unlink()
    (root / "sub" / "b.pdf").unlink()
    (root / "c.pdf").write_bytes(b"%PDF-1.4 C")

    def bad_upload(src, pkg, model, ocr):
        (pkg / f"{src.stem}.md").write_text("![x](images/missing.png)", encoding="utf-8")
        return True, ""

    out = mineru.prepare(root, uploader=bad_upload)
    assert out["ok"] is False
    assert out["failed"][0]["file"] == "c.pdf" and "闭包" in out["failed"][0]["why"]


def test_uploader_failure_partial_success_resume(tmp_path):
    root = make_root(tmp_path)
    calls = {"n": 0}

    def flaky(src, pkg, model, ocr):
        calls["n"] += 1
        if src.name == "a.pdf":
            return False, "网络抖动"
        (pkg / f"{src.stem}.md").write_text("x", encoding="utf-8")
        return True, ""

    out1 = mineru.prepare(root, uploader=flaky)
    assert out1["failed"][0]["file"] == "a.pdf" and out1["ok"] is False
    out2 = mineru.prepare(root, uploader=fake_uploader())  # 重跑只补缺口
    assert {p["file"] for p in out2["parsed"]} == {"a.pdf"}
    assert {p["file"] for p in out2["skipped"]} == {"a.jpg", "sub/b.pdf"}


def test_missing_root_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        mineru.prepare(tmp_path / "nope", uploader=fake_uploader())

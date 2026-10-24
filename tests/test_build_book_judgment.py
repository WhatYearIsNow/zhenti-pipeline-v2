"""P0-A05 回归：编译结果判定完整纳入每遍退出码，残留旧 PDF 不再混淆成功（TEX-01）。

用注入的 runner/pages_fn 替身，不依赖真实 TeX 工具链；构建目录位于 tmp。
"""
import importlib.util
from pathlib import Path

_BUILD = Path(__file__).resolve().parents[1] / "sources" / "workflow" / "optimization" / "v2" / "build-publish" / "build_book.py"

import pytest

pytestmark = pytest.mark.skipif(not _BUILD.is_file(),
                                reason="内部工具链快照（sources/）不在发布包内——私有证据层")


def _bb():
    spec = importlib.util.spec_from_file_location("build_book_s2", _BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_runner(seq, out=None):
    """依次返回 (returncode, stdout)；rc==0 时模拟编译器产出 PDF（让 pages_fn 生效）。"""
    it = iter(seq)

    def runner(cmd):
        rc, text = next(it)
        if rc == 0 and out is not None:
            (out / "book.pdf").write_bytes(b"%PDF-fake")
        return type("R", (), {"returncode": rc, "stdout": text})()

    return runner


def test_stale_pdf_is_removed_before_first_pass(tmp_path):
    out = tmp_path / "build"
    out.mkdir()
    stale = out / "book.pdf"
    stale.write_bytes(b"OLD-PDF-LEFTOVER")
    observed = []

    def runner(cmd):
        observed.append(stale.exists())
        if stale.parent.exists() and not stale.exists():
            stale.write_bytes(b"%PDF-fake")  # 模拟编译器产出
        return type("R", (), {"returncode": 0, "stdout": ""})()

    passes, pages, errors, _ = _bb().run_passes(out, out / "book.tex", 2, runner=runner,
                                             pages_fn=lambda p: 47)
    assert observed[0] is False  # 首遍前旧 PDF 已清除（此后为编译器产出，允许存在）
    assert passes == [0, 0] and pages == [47, 47]


def test_second_pass_failure_not_masked_by_same_page_old_pdf(tmp_path):
    # TEX-01：第二遍非零退出，即使目录里留着同页数 PDF 也不得判成功
    out = tmp_path / "build"
    out.mkdir()
    seq = iter([(0, ""), (1, "")])  # pass2 失败

    def runner(cmd):
        rc, text = next(seq)
        if rc == 0 and not (out / "book.pdf").exists():  # 模拟编译器产出
            (out / "book.pdf").write_bytes(b"%PDF-fake")
        return type("R", (), {"returncode": rc, "stdout": text})()

    passes, pages, errors, details = _bb().run_passes(out, out / "book.tex", 5, runner=runner,
                                                   pages_fn=lambda p: 47)
    pdf = out / "book.pdf"
    pdf.write_bytes(b"%PDF-stale-same-pages")  # 残留产物在场
    verdict = _bb().judge_build(passes, pages, errors, pdf)
    assert passes == [0, 1]
    assert verdict["ok"] is False
    assert any("非零退出" in r for r in verdict["reasons"])


def test_error_line_breaks_and_blocks(tmp_path):
    out = tmp_path / "build"
    out.mkdir()
    runner = fake_runner([(0, "! LaTeX Error: Misplaced \\cr")])
    passes, pages, errors, _ = _bb().run_passes(out, out / "book.tex", 5, runner=runner,
                                             pages_fn=lambda p: 47)
    (out / "book.pdf").write_bytes(b"%PDF")
    verdict = _bb().judge_build(passes, pages, errors, out / "book.pdf")
    assert verdict["ok"] is False and errors


def test_stable_clean_build_is_success(tmp_path):
    out = tmp_path / "build"
    out.mkdir()
    runner = fake_runner([(0, ""), (0, "")], out=out)
    passes, pages, errors, _ = _bb().run_passes(out, out / "book.tex", 5, runner=runner,
                                             pages_fn=lambda p: 47)
    verdict = _bb().judge_build(passes, pages, errors, out / "book.pdf")
    assert verdict == {"ok": True, "stable": True, "reasons": []}


def test_unstable_pages_not_judged_success(tmp_path):
    out = tmp_path / "build"
    out.mkdir()
    pages_seq = iter([47, 48, 49, 50, 51])
    runner = fake_runner([(0, "")] * 5, out=out)
    passes, pages, errors, _ = _bb().run_passes(out, out / "book.tex", 5, runner=runner,
                                             pages_fn=lambda p: next(pages_seq))
    verdict = _bb().judge_build(passes, pages, errors, out / "book.pdf")
    assert verdict["ok"] is False and not verdict["stable"]

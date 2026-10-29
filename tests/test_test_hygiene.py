"""ISO-01 静态守卫：测试模块不得在收集/导入期产生副作用（回归 A11）。

扫描 sources/skills/**/tests/**/*.py（含子代 regressions/）：
- 禁止任何 sys.exit(...)（收集期会中止 runner）
- 禁止对 sys.stdout / sys.stderr 赋值（重定向全局状态）
- 禁止盘符绝对路径字面量（历史 A11 曾从生产工作区导入）
- 禁止网络类 import（socket/urllib/requests/http.client，ISO-03）

本文件只覆盖历史快照区测试；根 tests/ 下的新代测试自身即守卫产物。
"""

import ast
import re
from pathlib import Path

import pytest

_SOURCES_PRESENT = (Path(__file__).resolve().parents[1] / "sources").exists()
pytestmark = [
    pytest.mark.skipif(
        not _SOURCES_PRESENT,
        reason="内部工具链快照（sources/）不在发布包内——私有证据层，公开 CI 不跑",
    )
]

REPO = Path(__file__).resolve().parents[1]
SCAN_ROOTS = sorted((REPO / "sources" / "skills").glob("*/tests"))
# A11 的实质风险是引用生产工作区/安装目录/用户资料，不是系统字体探测（Windows/Linux
# 字体候选路径属环境探测，允许）。因此只拦截用户内容目录（结构性检测；
# 具体私人名单的扫描在私有工具链里做，不进公共仓库）。
ABS_PATH_RE = re.compile(r"([A-Za-z]:[\\/](Users|Documents)[\\/]|/Users/|/home/)")
NETWORK_ROOTS = {"socket", "urllib", "requests", "http", "ftplib", "smtplib"}


def _module_sources():
    cases = []
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("test_*.py")):
            cases.append((path.relative_to(REPO).as_posix(), path.read_text(encoding="utf-8")))
    return cases


CASES = _module_sources()
CASE_IDS = [relpath for relpath, _ in CASES]


def test_hygiene_scan_finds_legacy_test_modules():
    # 守卫自身必须真的覆盖到历史测试，防止目录调整后空转
    assert any("zhenti-tiku" in f for f in CASE_IDS), CASE_IDS
    assert any("exam-compilation" in f for f in CASE_IDS), CASE_IDS
    assert len(CASES) >= 10, CASE_IDS


@pytest.mark.parametrize("relpath,source", CASES, ids=CASE_IDS)
def test_no_sys_exit_anywhere(relpath, source):
    tree = ast.parse(source, filename=relpath)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "exit"
                and isinstance(func.value, ast.Name)
                and func.value.id == "sys"
            ):
                pytest.fail(f"{relpath}: 含 sys.exit 调用（应改为 unittest 断言）")


@pytest.mark.parametrize("relpath,source", CASES, ids=CASE_IDS)
def test_no_stdout_redirection(relpath, source):
    tree = ast.parse(source, filename=relpath)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in ("stdout", "stderr"):
                    pytest.fail(
                        f"{relpath}: 对 sys.{target.attr} 赋值（ISO-01：收集期不得改写全局流）"
                    )


@pytest.mark.parametrize("relpath,source", CASES, ids=CASE_IDS)
def test_no_private_absolute_paths(relpath, source):
    if ABS_PATH_RE.search(source):
        pytest.fail(
            f"{relpath}: 引用用户资料/私人工作区路径（历史 A11：测试只允许 __file__ 相对与系统目录探测）"
        )


@pytest.mark.parametrize("relpath,source", CASES, ids=CASE_IDS)
def test_no_network_imports(relpath, source):
    tree = ast.parse(source, filename=relpath)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            if name.split(".")[0] in NETWORK_ROOTS:
                pytest.fail(f"{relpath}: 测试模块 import {name}（ISO-03：默认无网络）")

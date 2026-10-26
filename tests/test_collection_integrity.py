"""ISO-01 收集完整性：全树一次收集成功，不因单个模块中止。

S1 退出标准之一：一条命令（python -m pytest）可收集并执行全部隔离测试。
"""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COLLECTED_RE = re.compile(r"^\d+ tests collected", re.M)


def _collect():
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=str(REPO),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )


def test_full_tree_collects_without_errors():
    proc = _collect()
    detail = proc.stdout[-4000:] + "\n--- stderr ---\n" + proc.stderr[-2000:]
    assert proc.returncode == 0, detail
    assert COLLECTED_RE.search(proc.stdout), detail
    assert " no tests ran" not in proc.stdout, detail


def test_collected_volume_is_meaningful():
    proc = _collect()
    assert proc.returncode == 0, proc.stdout[-4000:]
    match = COLLECTED_RE.search(proc.stdout)
    assert match, proc.stdout[-2000:]
    count = int(match.group(0).split()[0])
    # 历史 8+3+1 个测试文件（67+15 方法）+ S1 新增；若大幅缩水应先查收集
    assert count >= 80, f"收集数异常偏少: {count}\n{proc.stdout[-2000:]}"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨进程文件锁（S2 P0-A01/A04 共用原语；S3 起并入 storage 包）。

语义：同一台机器上，同一把锁同一时刻至多一个持有者；持有进程死亡时由 OS 释放锁
（Windows msvcrt 区域锁 / POSIX flock 均随句柄关闭失效），因此**不存在需要按计时
清理的过期锁**（方案 §5.3）。等待超过 timeout 视为冲突，fail-closed 抛错，绝不抢占。

锁文件本身只作锁载体（内容记录持有者便于排障），删除与否不影响锁语义；
默认保留，避免删除窗口期的竞态。
"""
import os
import time
from contextlib import contextmanager

try:  # POSIX
    import fcntl

    def _try_lock(fd) -> bool:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
except ImportError:  # Windows
    import msvcrt

    def _try_lock(fd) -> bool:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True


class LockBusy(RuntimeError):
    """锁等待超时：有其他进程正在同一资源上操作（fail-closed，不抢占）。"""


@contextmanager
def exclusive_lock(lock_path, timeout: float = 10.0, poll: float = 0.02):
    lock_path = _as_path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o666)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                _try_lock(fd)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockBusy(f"锁等待超时（{timeout}s）: {lock_path}——另一进程可能正在操作") from None
                time.sleep(poll)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            os.truncate(fd, 0)
            os.write(fd, f"pid={os.getpid()} at={time.strftime('%Y-%m-%dT%H:%M:%S')}\n".encode())
        except OSError:
            pass  # 锁内容仅排障用，写不进不影响互斥
        yield
    finally:
        try:
            if os.name != "nt":
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass  # 进程退出同样释放
        os.close(fd)


def _as_path(p):
    from pathlib import Path
    return Path(p)

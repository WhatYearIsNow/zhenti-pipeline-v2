#!/usr/bin/env python3
"""保守 Windows/Unix 写盘工具；永不解锁他人文件。"""

import contextlib, hashlib, json, os, pathlib, shutil, tempfile, time, datetime


class BusyError(RuntimeError):
    pass


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


@contextlib.contextmanager
def claim(target, owner, *, timeout=0.0, poll=0.1):
    target = pathlib.Path(target).resolve()
    lock = target.with_name(target.name + '.workflow.lock')
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(
                    {
                        'owner': owner,
                        'pid': os.getpid(),
                        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    },
                    f,
                )
                f.flush()
                os.fsync(f.fileno())
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise BusyError(f'已有写入所有者；不可擅自删除锁：{lock}')
            time.sleep(poll)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def safe_replace(
    target, data, *, owner, expected_sha256=None, timeout=0.0, retries=3, delay=0.2, backup=True
):
    """文件原子替换+读回；重试只处理权限/共享冲突，失败保留源文件与备份。"""
    target = pathlib.Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with claim(target, owner, timeout=timeout):
        if expected_sha256 is not None:
            actual = sha256(target) if target.exists() else None
            if actual != expected_sha256:
                raise ValueError('文件在审批后发生变化，阻断写回')
        bak = None
        if backup and target.exists():
            bak = target.with_name(
                target.name + '.bak-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f')
            )
            shutil.copy2(target, bak)
            if sha256(bak) != sha256(target):
                raise OSError('备份读回不一致')
        fd, tmp = tempfile.mkstemp(prefix='.' + target.name + '.', suffix='.tmp', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            if (
                hashlib.sha256(pathlib.Path(tmp).read_bytes()).digest()
                != hashlib.sha256(data).digest()
            ):
                raise OSError('临时文件读回失败')
            for attempt in range(retries + 1):
                try:
                    os.replace(tmp, target)
                    break
                except PermissionError:
                    if attempt == retries:
                        raise BusyError(
                            '目标文件可能被 Windows 阅读器/同步器锁定；保留备份，关闭占用程序或改用新输出名'
                        )
                    time.sleep(delay * (attempt + 1))
            if sha256(target) != hashlib.sha256(data).hexdigest():
                raise OSError('最终文件读回哈希失败')
            return {'sha256': sha256(target), 'backup': str(bak) if bak else None}
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

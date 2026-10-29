"""输入指纹 v2（fail-closed + 根清单 + 路径规范化）。

用法: python hash_inputs.py <dir|file>... <out.json>

v2 变更（相对 v1，2026-10-11 阶段01，回滚见 optimization/v2/backups-stage01/）：
- fail-closed：任一根路径不存在 → 立即报错退出（exit 1），不写输出文件。
  v1 会静默跳过缺失根，导致"部分输入"也产出合法指纹（威胁模型 T4）。
- 输出 JSON 新增 toolVersion=2 与 roots（调用方传入的根清单）；消费方须核对
  根清单与 fileCount 与预期一致，否则指纹无效。
- 路径以工作区相对规范形式表达：cwd 内相对化、统一正斜杠、realpath 去别名，
  避免不同机器/绝对路径写法造成的指纹漂移；同一物理文件经不同根重复命中只计一次。
- 生成中的输出目录不应作为根传入：本脚本按调用方给的根全量哈希（调用纪律）。
- stdout 首行仍为总指纹（旧消费方按 stdout 首行消费，保持兼容）；明细原子写 + 读回校验保留。

输入变更的后果：total 变化即意味着原料/定稿文件被改动，已有试点结论与审批凭据
（approval-threat-model §四 invalid_at 条款）随之失效，须重新走审核。
"""

import hashlib
import json
import os
import sys

TOOL_VERSION = 2


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def display_path(full: str, cwd: str) -> str:
    """规范显示路径：cwd 内相对化 + 正斜杠；越界（盘符不同等）保留规范绝对路径。"""
    p = full.replace("\\", "/")
    try:
        rel = os.path.relpath(full, cwd).replace("\\", "/")
        if not rel.startswith("..") and not os.path.isabs(rel):
            return rel
    except ValueError:
        pass
    return p


def collect(roots, cwd, exclude_dirs=()):
    entries = {}
    seen_real = {}
    aliases = 0

    def add(full: str):
        nonlocal aliases
        real = os.path.realpath(full)
        disp = display_path(full, cwd)
        if real in seen_real:
            if seen_real[real] != disp:
                aliases += 1
            return
        seen_real[real] = disp
        entries[disp] = sha256_file(full)

    for root in roots:
        norm = root.replace("\\", "/")
        if os.path.isfile(norm):
            add(norm)
        elif os.path.isdir(norm):
            for dirpath, dirnames, filenames in os.walk(norm):
                # 排除目录名（如 mineru/ 派生产物——它们随解析生成，不属于"原料输入"，
                # 否则备料本身就会造成指纹漂移、误撤审批）
                dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
                dirnames.sort()
                for name in sorted(filenames):
                    add(os.path.join(dirpath, name))
        # 根存在性已在 main 里 fail-closed 校验，此处不再有第三种情况
    return entries, aliases


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = sys.argv[1:]
    exclude_dirs = []
    while args and args[0].startswith("--exclude-dir"):
        exclude_dirs.append(args[1])
        args = args[2:]
    if len(args) < 2:
        print(
            "usage: hash_inputs.py [--exclude-dir NAME]... <dir|file>... <out.json>",
            file=sys.stderr,
        )
        return 2
    out_path = args[-1].replace("\\", "/")
    roots = args[:-1]

    # fail-closed：每个根必须真实存在，缺一即整体失败且不写输出
    missing_roots = [r for r in roots if not os.path.exists(r.replace("\\", "/"))]
    if missing_roots:
        for r in missing_roots:
            print(f"ERROR: 输入根不存在: {r}", file=sys.stderr)
        print(
            f"ERROR: {len(missing_roots)} 个输入根缺失，拒绝输出指纹（fail-closed）",
            file=sys.stderr,
        )
        return 1

    cwd = os.getcwd()
    entries, aliases = collect(roots, cwd, tuple(exclude_dirs))
    if not entries:
        print("ERROR: no files hashed", file=sys.stderr)
        return 1
    total = hashlib.sha256(
        "\n".join(f"{k}:{v}" for k, v in sorted(entries.items())).encode("utf-8")
    ).hexdigest()

    payload = {
        "toolVersion": TOOL_VERSION,
        "roots": [r.replace("\\", "/") for r in roots],
        "excludeDirs": exclude_dirs,
        "total": total,
        "fileCount": len(entries),
        "aliasedEntries": aliases,
        "files": dict(sorted(entries.items())),
    }
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, out_path)
    # 写后读回验证（本机写盘偶发延迟的既定对策）
    with open(out_path, "r", encoding="utf-8") as f:
        check = json.load(f)
    if check.get("total") != total or check.get("fileCount") != len(entries):
        print("ERROR: fingerprint file readback mismatch", file=sys.stderr)
        return 1
    print(total)
    print(
        f"files={len(entries)} roots={len(roots)} aliases={aliases} -> {out_path}", file=sys.stderr
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

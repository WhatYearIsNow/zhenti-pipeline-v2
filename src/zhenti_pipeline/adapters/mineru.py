"""MinerU 备料适配器（S4）：发现、缓存、统一返回契约；上传调用可注入。

修复的两个审计缺陷：
- A07：缓存目录曾以源文件 stem 命名（同名不同格式碰撞）、复用条件仅"md 非空"、
  无源哈希/解析配置匹配。现在缓存键 = 源内容 SHA256（+模型/OCR/解析器版本），
  复用条件 = 元数据匹配 **且** md 非空 **且** 图片引用闭包存在；旧布局包缺凭据
  → 标为 needs-check，绝不静默当已备料（方案 §5.4）。
- A06：返回契约统一为 parsed/skipped/failed **数组**（元素为对象），与所有消费者一致；
  旧 dwf 入口把 parsed/skipped 声明为数字，属于契约漂移——新 skills/CLI 只认本契约。

上传（mineru-open-api extract）是外部副作用：默认仅当 prepare(upload=None) 走真实 CLI
时发生；测试与 dry-run 注入 uploader 替身，零网络（ISO-03）。flash-extract 永不使用
（公式/图表占位符不可用——用户 2026-10-12 红线）。
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 统一可解析格式（MinerU 云端原生支持 Office/网页；与脚本既有清单一致）
DEFAULT_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".ppt", ".pptx", ".html"}
PARSER_VERSION = "mineru-open-api-extract/1"  # 缓存键组成部分；解析实现变更时递增


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def discover_inputs(root: Path, exts: set[str] | None = None) -> list[Path]:
    """递归枚举原料（排除 mineru/ 输出树自身）；返回排序后的相对稳定清单。"""
    root = Path(root)
    allowed = exts or DEFAULT_EXTS
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in allowed
        and "mineru" not in p.relative_to(root).parts[:-1]
    )


def _cache_key(src: Path, model: str, ocr: bool) -> str:
    payload = json.dumps(
        {"sha256": sha_file(src), "model": model, "ocr": bool(ocr), "parser": PARSER_VERSION},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def cache_dir(root: Path, src: Path, model: str, ocr: bool) -> Path:
    """A07：缓存目录由缓存键寻址，同名 a.pdf/a.jpg 内容不同→不同键，不碰撞。"""
    rel = Path(src).relative_to(root)
    return (
        Path(root)
        / "mineru"
        / "cache"
        / f"{_cache_key(root / src if not src.is_absolute() else src, model, ocr)}-{rel.stem}"
    )


def _closure_ok(pkg: Path, md_name: str) -> bool:
    """md 非空且存在；图片引用闭包检查（引用的相对图片文件在包内或 images/ 下存在）。"""
    md = pkg / md_name
    if not md.is_file() or md.stat().st_size == 0:
        return False
    text = md.read_text(encoding="utf-8", errors="replace")
    missing = []
    for token in text.split("](")[1:]:
        name = token.split(")")[0].strip().lstrip("./")
        if not name or name.startswith(("http://", "https://")):
            continue
        if not ((pkg / name).is_file() or (pkg / "images" / Path(name).name).is_file()):
            missing.append(name)
    return not missing


def prepare(
    root: str | Path,
    model: str = "vlm",
    force_ocr: bool = False,
    uploader=None,
    min_md_bytes: int = 1,
) -> dict:
    """备料主入口（幂等只补缺口）。uploader(file, out_pkg, model, ocr) -> bool 可注入。

    返回契约（A06）：{"ok", "inputDir", "parsed": [..], "skipped": [..],
    "needsCheck": [..], "failed": [..], "model", "ocr"} —— 数组元素均为对象。
    """
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"原料目录不存在: {root}")
    parsed, skipped, needs_check, failed = [], [], [], []
    for src in discover_inputs(root):
        rel = src.relative_to(root)
        pkg = cache_dir(root, src, model, force_ocr)
        meta_path = pkg / "mineru-meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if (
                meta.get("sourceSha256") == sha_file(src)
                and meta.get("model") == model
                and meta.get("ocr") == bool(force_ocr)
                and _closure_ok(pkg, f"{src.stem}.md")
            ):
                skipped.append(
                    {
                        "file": str(rel).replace("\\", "/"),
                        "cacheKey": meta_path.parent.name,
                        "md": f"{src.stem}.md",
                    }
                )
                continue
            # 键目录存在但凭据不符（源被改/选项变化）→ 失效，重解析
        # 旧布局（stem 目录 / auto/full.md 等）：缺凭据，只登记 needs-check，不当已备料
        legacy_root = root / "mineru" / rel.parent / src.stem
        if legacy_root.is_dir() and any(legacy_root.rglob("*.md")):
            needs_check.append(
                {
                    "file": str(rel).replace("\\", "/"),
                    "why": "旧布局缓存无源哈希凭据，需人工核验或重新备料",
                }
            )
        pkg.mkdir(parents=True, exist_ok=True)
        ok, why = False, ""
        if uploader is None:
            ok, why = _cli_extract(src, pkg, model, force_ocr)
        else:
            ok, why = uploader(src, pkg, model, force_ocr)
        if ok and _closure_ok(pkg, f"{src.stem}.md"):
            meta = {
                "sourceRel": str(rel).replace("\\", "/"),
                "sourceSha256": sha_file(src),
                "model": model,
                "ocr": bool(force_ocr),
                "parser": PARSER_VERSION,
                "mdBytes": (pkg / f"{src.stem}.md").stat().st_size,
            }
            (pkg / "mineru-meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
            parsed.append(
                {"file": str(rel).replace("\\", "/"), "cacheKey": pkg.name, "md": f"{src.stem}.md"}
            )
        else:
            failed.append({"file": str(rel).replace("\\", "/"), "why": why or "闭包检查未过"})
    return {
        "ok": not failed,
        "inputDir": str(root).replace("\\", "/"),
        "parsed": parsed,
        "skipped": skipped,
        "needsCheck": needs_check,
        "failed": failed,
        "model": model,
        "ocr": bool(force_ocr),
    }


def _cli_extract(src: Path, pkg: Path, model: str, force_ocr: bool) -> tuple[bool, str]:
    """默认上传路径：mineru-open-api extract（外部副作用：内容上传 mineru.net）。"""
    cli = shutil.which("mineru-open-api") or "mineru-open-api"
    env = dict(os.environ, PYTHONUTF8="1")
    probe = subprocess.run(
        [cli, "version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )
    if probe.returncode != 0:
        return False, f"{cli} 不可用（npm install -g mineru-open-api）：{probe.stderr[:200]}"
    cmd = [cli, "extract", str(src), "-o", str(pkg), "-f", "md,json", "--model", model]
    if force_ocr:
        cmd.append("--ocr")
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=900,
    )
    blob = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        if "401" in blob or "unauthorized" in blob.lower() or "token" in blob.lower():
            return False, (
                "auth：云端认证未通过——执行一次 `mineru-open-api auth` 或设 MINERU_TOKEN；"
                "不降级到 flash-extract"
            )
        return False, blob[-300:]
    return True, ""

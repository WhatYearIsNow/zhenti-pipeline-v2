"""旧数据只读适配（S3）：读旧格式 papers，逐项报告未知字段，绝不改写。

方案 §5.2：旧格式通过只读适配器读入；升级先输出逐项差异和新文件，不静默覆写；
未知字段不无意丢失。本模块只读——任何写入都属于后续显式迁移命令（S5 审批式迁移）。
"""
import json
from pathlib import Path

# papers-v2 契约（references/papers-v2.md + check_papers 语义）已知的卷级/题目字段。
KNOWN_PAPER_FIELDS = {
    "fileId", "kind", "ab", "course", "paperDisplay", "sourceFile",
    "missing", "questions", "schemaVersion", "taxonomyVersion", "notes",
}
KNOWN_QUESTION_FIELDS = {
    "num", "type", "subtype", "chapter", "also_chapter", "desc", "options",
    "answer", "analysis", "images", "releaseBlocked", "reviewStatus", "status", "flags",
}
LEGACY_SCHEMA_VERSIONS = {None, 1, 2}  # 无 schemaVersion 的最老批次按 None 记录


def load_json_readonly(path: Path):
    """只读加载 JSON；返回 (data, notes)。解析失败时 data=None 并给 note。"""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, [f"{path.name}: 读取失败 {exc}"]
    if raw.startswith(b"\xef\xbb\xbf"):
        # BOM 不改写文件，仅报告（check_papers 视其为错误；适配器保留信息供迁移决策）
        return json.loads(raw.decode("utf-8-sig")), [f"{path.name}: 含 UTF-8 BOM（旧批次常见）"]
    try:
        return json.loads(raw.decode("utf-8")), []
    except (UnicodeError, ValueError) as exc:
        return None, [f"{path.name}: JSON 解析失败 {exc}"]


def _unknown_fields(obj: dict, known: set) -> list:
    return sorted(k for k in obj if k not in known)


def inspect_paper(data: dict) -> dict:
    """单卷只读巡检：未知字段、schema 版本、逐题未知字段。不改任何值。"""
    notes: list[str] = []
    warnings: list[str] = []
    version = data.get("schemaVersion")
    if version not in LEGACY_SCHEMA_VERSIONS:
        warnings.append(f"未知 schemaVersion={version!r}：按只读兼容处理，迁移前须人工核对")
    unknown = _unknown_fields(data, KNOWN_PAPER_FIELDS)
    if unknown:
        notes.append(f"卷级未知字段（保留不丢）: {unknown}")
    per_question = {}
    for q in data.get("questions", []) if isinstance(data.get("questions"), list) else []:
        if not isinstance(q, dict):
            continue
        uq = _unknown_fields(q, KNOWN_QUESTION_FIELDS)
        if uq:
            per_question[str(q.get("num"))] = uq
    if per_question:
        notes.append(f"题目级未知字段（保留不丢）: {per_question}")
    return {"schemaVersion": version, "unknownPaperFields": unknown,
            "unknownQuestionFields": per_question, "notes": notes, "warnings": warnings}


def inspect_papers(papers_dir: Path) -> dict:
    """科目 papers 目录只读巡检（textbook/meta/卷 JSON/图片清单）。零写入。"""
    papers_dir = Path(papers_dir)
    files = {"papers": {}, "errors": [], "warnings": [], "counts": {}}
    tb = papers_dir / "textbook.json"
    meta = papers_dir / "meta.json"
    counts = {"papers": 0, "questions": 0, "images": 0}
    if tb.is_file():
        data, notes = load_json_readonly(tb)
        files["textbook"] = {"loaded": data is not None, "notes": notes}
        if isinstance(data, dict):
            files["textbook"]["sectionCount"] = len(data.get("sections", {}))
    else:
        files["errors"].append("textbook.json 缺失")
    if meta.is_file():
        data, notes = load_json_readonly(meta)
        files["meta"] = {"loaded": data is not None, "notes": notes,
                         "unknownFields": _unknown_fields(data, {
                             "subject", "mockSource", "schemaVersion", "taxonomyVersion", "files"})}
    else:
        files["warnings"].append("meta.json 不存在（旧卷兼容，新交付应提供）")
    for path in sorted(papers_dir.glob("*.json")):
        if path.name in ("textbook.json", "meta.json"):
            continue
        data, notes = load_json_readonly(path)
        if data is None:
            files["errors"].extend(notes)
            continue
        rep = inspect_paper(data)
        counts["papers"] += 1
        counts["questions"] += len(data.get("questions", []) or [])
        files["papers"][path.name] = {"schemaVersion": rep["schemaVersion"],
                                      "unknownPaperFields": rep["unknownPaperFields"],
                                      "unknownQuestionFields": rep["unknownQuestionFields"],
                                      "notes": rep["notes"]}
        files["warnings"].extend(rep["warnings"])
    img = papers_dir / "images"
    if img.is_dir():
        counts["images"] = sum(1 for p in img.iterdir() if p.is_file())
    files["counts"] = counts
    return files

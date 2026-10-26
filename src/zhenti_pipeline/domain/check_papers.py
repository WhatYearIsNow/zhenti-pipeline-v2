#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读 papers 交接检查。 python check_papers.py PAPERS_DIR [--json-report PATH]"""

import argparse
import json
import re
import sys
from pathlib import Path

SUBTYPES = {'', 'calc', 'fill', 'solution', 'choice', 'single', 'judge', 'multi'}
TYPES = {'choice', 'fill', 'open'}


def audit(directory):
    directory = Path(directory)
    errors, warnings = [], []
    stats = {'files': 0, 'questions': 0, 'missing': 0, 'cross_chapter': 0}

    def error(msg):
        errors.append(msg)

    def warn(msg):
        warnings.append(msg)

    def read(path):
        try:
            raw = path.read_bytes()
            if raw.startswith(b'\xef\xbb\xbf'):
                error(f'{path.name}: UTF-8 BOM 不允许')
            value = json.loads(raw.decode('utf-8'))
            return value
        except (OSError, UnicodeError, ValueError) as exc:
            error(f'{path.name}: 文件读取/编码/JSON 解析失败: {exc}')
            return None

    tb = read(directory / 'textbook.json')
    if not isinstance(tb, dict) or not isinstance(tb.get('sections'), dict):
        error('textbook.json: 必须包含对象 sections；无法执行章节验证')
        sections = {}
    else:
        sections = tb['sections']
    meta_path = directory / 'meta.json'
    if meta_path.exists():
        meta = read(meta_path)
        if meta is not None and not isinstance(meta, dict):
            error('meta.json: 须为对象')
    else:
        warn('meta.json 不存在；旧卷暂兼容，但新交付应提供')
    referenced = set()
    identities = {}
    for path in sorted(directory.glob('*.json')):
        if path.name in ('meta.json', 'textbook.json'):
            continue
        stats['files'] += 1
        p = read(path)
        if p is None:
            continue
        if not isinstance(p, dict):
            error(f'{path.name}: 卷级 JSON 必须是对象')
            continue
        fid = p.get('fileId')
        if not isinstance(fid, str) or not re.fullmatch(r'[\w\-\u4e00-\u9fff]+', fid):
            error(f'{path.name}: fileId 非法（不得有路径字符）')
            continue
        if path.stem != fid:
            error(f'{path.name}: 文件名和 fileId={fid} 不一致')
        if fid in identities:
            error(f'{path.name}: 卷级 fileId {fid} 已出现于 {identities[fid]}')
        identities[fid] = path.name
        if p.get('kind') not in ('final', 'midterm'):
            error(f'{fid}: kind 非法 {p.get("kind")!r}')
        if p.get('ab') not in (None, 'A', 'B'):
            error(f'{fid}: ab 非法')
        if not isinstance(p.get('paperDisplay'), str) or not p['paperDisplay'].strip():
            error(f'{fid}: paperDisplay 缺失')
        if not isinstance(p.get('sourceFile'), str) or not p['sourceFile'].strip():
            warn(f'{fid}: sourceFile 缺失，建议补原卷页')
        qs = p.get('questions')
        if not isinstance(qs, list):
            error(f'{fid}: questions 必须是数组')
            continue
        if not qs:
            error(f'{fid}: questions 为空，禁止交接')
        missing = p.get('missing')
        if not isinstance(missing, list) or any(type(x) is not int or x < 1 for x in missing):
            error(f'{fid}: missing 必须是正整数数组')
            missing = []
        if len(missing) != len(set(missing)):
            error(f'{fid}: missing 存在重复登记')
        stats['missing'] += len(missing)
        numbers = set()
        actual_missing = set()
        for i, q in enumerate(qs, 1):
            stats['questions'] += 1
            loc = f'{fid} 条目{i}'
            if not isinstance(q, dict):
                error(f'{loc}: 题目不是对象')
                continue
            num = q.get('num')
            if type(num) is not int or num < 1:
                error(f'{loc}: num 必须为正整数')
                continue
            loc = f'{fid} T{num}'
            # 留存原始记录，但对正式交接设置发布阻断；不得静默跳题。
            if q.get('releaseBlocked') is True or q.get('reviewStatus') in (
                'pending',
                'unreadable',
                'blocked',
            ):
                error(f'{loc}: 题面/图片待核，禁止交接出版；请人工核验后解除阻断')
            # 卷内每道原题出现一次；同题多个章节用 also_chapter。合并后 -x2 副本合法。
            if num in numbers:
                error(
                    f'{loc}: 同一原卷 JSON 中 num 重复；跨章节请用 also_chapter，不是新增同 num 条目'
                )
            numbers.add(num)
            typ, subtype = q.get('type'), q.get('subtype', '')
            if typ not in TYPES:
                error(f'{loc}: type 非法 {typ!r}')
            if subtype not in SUBTYPES:
                error(f'{loc}: subtype 非法 {subtype!r}')
            options = q.get('options')
            if not isinstance(options, list):
                error(f'{loc}: options 必须为数组')
                options = []
            letters = []
            for option in options:
                if (
                    not isinstance(option, dict)
                    or not isinstance(option.get('letter'), str)
                    or not isinstance(option.get('text'), str)
                ):
                    error(f'{loc}: 选项必须有字符串 letter/text')
                    continue
                letters.append(option['letter'])
            if typ == 'choice':
                if not letters:
                    error(f'{loc}: 选择/判断题无 options')
                if subtype == 'judge':
                    if letters != ['T', 'F']:
                        error(f'{loc}: 判断题选项必须依次为 T/F')
                elif letters != [chr(65 + x) for x in range(len(letters))]:
                    error(f'{loc}: 选项字母必须从 A 连续且不重复')
                answer = q.get('answer', '')
                if isinstance(answer, str) and answer.strip():
                    a = answer.strip()
                    if subtype == 'judge':
                        if a not in ('T', 'F'):
                            error(f'{loc}: 判断答案必须是 T/F')
                    elif subtype == 'multi':
                        if len(a) != len(set(a)) or any(c not in letters for c in a):
                            error(f'{loc}: 多选答案字母重复或超出选项')
                    elif len(a) != 1 or a not in letters:
                        error(f'{loc}: 单选答案必须为一个已有选项字母')
            elif typ in ('fill', 'open') and options:
                error(f'{loc}: 非选择题的 options 必须是 []')
            for key in ('desc', 'answer', 'analysis'):
                value = q.get(key)
                if not isinstance(value, str):
                    error(f'{loc}: {key} 必须是字符串')
                    continue
                if re.search(r'[\x00-\x08\x0b-\x1f]', value):
                    error(f'{loc}: {key} 有控制字符')
                if '**' in value or '|---|' in value or re.search(r'^#{1,6} ', value, re.M):
                    error(f'{loc}: {key} 有 Markdown 残留')
            if not str(q.get('answer', '')).strip() or not str(q.get('analysis', '')).strip():
                actual_missing.add(num)
            for key in ('chapter', 'also_chapter'):
                chapter = q.get(key)
                if key == 'also_chapter' and chapter is None:
                    continue
                if not isinstance(chapter, dict):
                    error(f'{loc}: {key} 必须是章/节对象')
                    continue
                label, section = chapter.get('label'), chapter.get('section')
                if label not in sections:
                    error(f'{loc}: {key}.label 不在 textbook.sections')
                    continue
                allowed = sections[label]
                if not isinstance(allowed, list):
                    error(f'{loc}: textbook.sections[{label}] 必须为数组')
                    continue
                if allowed and section not in allowed:
                    error(f'{loc}: {key}.section 必须从本章真实节目录选择')
                if not allowed and section is not None:
                    error(f'{loc}: {key}.section 应为 null（该章无小节）')
            if q.get('also_chapter') is not None:
                stats['cross_chapter'] += 1
                if q.get('also_chapter') == q.get('chapter'):
                    error(f'{loc}: also_chapter 不能与主章节完全相同')
            images = q.get('images', [])
            if not isinstance(images, list):
                error(f'{loc}: images 必须是数组')
                continue
            for image in images:
                if not isinstance(image, dict):
                    error(f'{loc}: 图片项不是对象')
                    continue
                name, where = image.get('file'), image.get('where')
                if (
                    not isinstance(name, str)
                    or not name
                    or Path(name).name != name
                    or '/' in name
                    or '\\' in name
                ):
                    error(f'{loc}: 图片文件名非法/路径越界: {name!r}')
                    continue
                if where not in ('desc', 'analysis'):
                    error(f'{loc}: 图片 where 只允许 desc/analysis')
                referenced.add(name)
                if not (directory / 'images' / name).is_file():
                    error(f'{loc}: 图片不存在 {name}')
        for num in sorted(actual_missing - set(missing)):
            error(f'{fid} T{num}: 答案或解析缺失但未登记 missing')
        for num in sorted(set(missing) - actual_missing):
            error(f'{fid} T{num}: missing 多登记（答案与解析均非空或题不存在）')
    imgdir = directory / 'images'
    if imgdir.is_dir():
        for image_path in imgdir.iterdir():
            if image_path.is_file() and image_path.name not in referenced:
                warn(f'孤儿图片: {image_path.name}')
    return {'ok': not errors, 'errors': errors, 'warnings': warnings, 'stats': stats}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('papers_dir', help='科目 papers 目录，必须显式指定')
    parser.add_argument('--json-report', help='可选：将结果写入 JSON 文件')
    args = parser.parse_args(argv)
    result = audit(args.papers_dir)
    for item in result['errors']:
        print('FAIL:', item)
    for item in result['warnings']:
        print('WARN:', item)
    print('统计:', json.dumps(result['stats'], ensure_ascii=False))
    print(f"== {len(result['errors'])} FAIL, {len(result['warnings'])} WARN ==")
    if args.json_report:
        Path(args.json_report).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
        )
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())

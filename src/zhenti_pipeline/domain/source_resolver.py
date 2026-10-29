#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""来源解析与格式转换 · 单点模块 v2（阶段04，2026-10-11 定稿）。

这是全流水线**唯一**的来源语义实现：merge 预检、publication_gate（交叉校验）与
make_book（渲染）都从本模块取 resolve/is_mock_paper，禁止再内嵌来源正则副本。
部署形态：canonical = <工作区>/exam-compilation/exam-compilation/tools/source_resolver.py；
skill 侧 scripts/source_resolver.py 由 dual-copy/sync_make_book.py 单向同步。

v2 相对 v1 的语义（以 2026-10-11 对 226 条真实卷名串的零漂移快照为准）：
- YYSSN 分支吸收 make_book 的合法宽松形态：卷号后允许 "_-/B卷/中文课程名" 后缀
  （physics '15161 大学物理2B A卷' 等已验收数据依赖此形态；后缀中的课程名不进输出，
  B卷 标记按含 'B卷' 判定——与已验收书一致，A 卷不带标记）。
- fail-closed 收紧（真实数据 0 命中，仅拦垃圾）：学期位只认 1/2；两位年份必须连续
  （YYSSN、阿拉伯与完整卷名三分支一致）；其余未知形态 ValueError（不得自动删除原题）。
- 模拟卷两类形态无 mockSource 一律 ValueError（禁止用科目名凑来源）。

输出格式（已验收书定稿，字节级冻结）：
- 完整卷名/阿拉伯/YYSSN 真题：'20xx—20xx 学年第N学期…试卷（B卷）'（完整卷名带空格、
  去《课程名》；阿拉伯与 YYSSN 旧格式无空格）。
- 模拟卷：'文档全名 第N学期…模拟题N' / '文档全名模拟卷N'。
"""

import re

DEFAULT_MOCK = {
    'calculus': '天津大学高等数学考试真题解析（2018-2022）',
    'probability': '天津大学概率论与数理统计1考试真题解析（2018-2022）',
}
CN = {'1': '一', '2': '二'}
# 学期位接受中文/阿拉伯数字（卷面两种印法都合法，如 2020—2021学年第1学期《课程名》…），
# 输出统一归一为中文数字。
PAPER = re.compile(
    r'^20\d{2}—20\d{2}学年第([一二12])学期《[^》]+》(?:期末考试|期中考试|阶段考试|第[一二三四]次月考|月考)试卷(?:（[AB]卷）)?$'
)
ARABIC = re.compile(r'^20(\d{2})-20(\d{2})学年第([12])学期([AB])卷$')
TERM_MOCK = re.compile(r'^第([一二])学期(期中|期末)考试模拟题([一二])$')
SHORT_MOCK = re.compile(r'^模拟卷([1-9]\d*)$')
# YYSSN 卷号 + 可选后缀：裸 5 位 / '_xxx'、'-xxx' / '_B卷'、'B卷' / 中文课程名后缀
# （'15161 大学物理2B A卷' 归一化后 = '15161大学物理2BA卷'，走中文后缀分支）。
YEAR_ID = re.compile(r'^(\d{2})(\d{2})([12])(?:[_\-].*|_?B卷|[\u4e00-\u9fff].*)?$')


def normalize(name):
    return re.sub(r'\s+', '', str(name).replace('～', '—').replace('〜', '—').replace('~', '—'))


def is_mock_paper(paper):
    """模拟卷类统一判定（排序/凡例/按需校验共用；勿再写 startswith('模拟卷')）。"""
    p = normalize(paper)
    return bool(SHORT_MOCK.match(p) or TERM_MOCK.match(p))


def _check_contiguous(start: int, end: int, p: str) -> None:
    if end != (start + 1) % 100:
        raise ValueError('卷号/卷名年份不连续：' + p)


def resolve(paper, subject, mock_source=None):
    p = normalize(paper)
    mock = mock_source if mock_source is not None else DEFAULT_MOCK.get(subject, '')
    if PAPER.fullmatch(p):
        y = re.match(r'^(20\d{2})—(20\d{2})学年', p)
        _check_contiguous(int(y.group(1)[-2:]), int(y.group(2)[-2:]), p)
        no_course = re.sub(r'《[^》]+》', '', p)
        no_course = re.sub(r'第([12])学期', lambda m: '第' + CN[m.group(1)] + '学期', no_course)
        return re.sub(r'^(20\d{2}—20\d{2})学年', r'\1 学年', no_course)
    match = ARABIC.fullmatch(p)
    if match:
        _check_contiguous(int(match[1]), int(match[2]), p)
        return f'20{match[1]}—20{match[2]}学年第{CN[match[3]]}学期期末考试试卷（{match[4]}卷）'
    match = TERM_MOCK.fullmatch(p)
    if match:
        if not isinstance(mock, str) or not mock.strip():
            raise ValueError(f'{subject}: 模拟题必须提供用户确认的 meta.mockSource')
        return f'{mock.strip()} 第{match[1]}学期{match[2]}模拟题{match[3]}'
    match = SHORT_MOCK.fullmatch(p)
    if match:
        if not isinstance(mock, str) or not mock.strip():
            raise ValueError(f'{subject}: 模拟卷必须提供用户确认的 meta.mockSource')
        return f'{mock.strip()}模拟卷{match[1]}'
    match = YEAR_ID.fullmatch(p)
    if match:
        start, end, term = int(match[1]), int(match[2]), match[3]
        _check_contiguous(start, end, p)
        result = f'20{start:02d}—20{end:02d}学年第{CN[term]}学期期末考试试卷'
        if 'B卷' in p:
            result += '（B卷）'
        return result
    raise ValueError(f'未知卷名或来源格式（不得自动删除原题）：{paper!r}')


def configure_renderer(renderer, subject, mock_source):
    """单次构建从 bank.meta 读取来源；只作用于该次加载的排版器副本。"""
    if mock_source is None:
        return
    if not isinstance(mock_source, str):
        raise ValueError('meta.mockSource 必须为字符串')
    if mock_source.strip():
        renderer.MOCK_SOURCE[subject] = mock_source.strip()
    else:
        renderer.MOCK_SOURCE.pop(subject, None)

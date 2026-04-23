#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TOC 工具：章节过滤 + slot 分配 + 文件名生成。

EPUB 和 PDF 提取器共用。核心设计：用结构信号（标题里的章号、TOC 位置）
做决策，不靠语义分类词表猜"front/back matter"。

slot 格式：
    "01"-"99"   真实章节（标题里抓到章号 N）
    "00a".."00z"  首章之前的额外内容（按 TOC 顺序）
    "99a".."99z"  末章之后的额外内容
    "{N}b".."{N}z"  章 N 和章 N+1 之间的插曲（a 位给章 N 本身）

降级：全书抓到的 chapter 数 < 2 → 全部走纯提取顺序 "01".."NN"。
"""

import re


# ---------- SKIP 规则：标题级硬过滤，必然非内容 ----------

SKIP_TITLES_EXACT = {
    # 结构性
    'cover', 'title', 'title page', 'half title', 'halftitle', 'fulltitle',
    'copyright',
    'contents', 'table of contents',
    'list of figures', 'list of tables', 'list of illustrations',
    'list of contributors', 'editorial board', 'notes on contributors',
    'index', 'index2',
    'figures', 'contributors',
    # 形式性（通常无研究价值）
    'acknowledgments', 'acknowledgements',
    'dedication', 'epigraph',
    'about the author', 'about the authors', 'about the book',
    'author biographies',
}

SKIP_PATTERNS = [
    re.compile(r'^Part\s+[IVXLCDM\d]+\b', re.IGNORECASE),  # Part II, Part 3 标题页
    re.compile(r'^Frontmatter$', re.IGNORECASE),            # split_chapters.py 伪章节
]


def is_skip(title: str) -> bool:
    """标题是否应整体丢弃（不进 manifest）。"""
    t = (title or '').strip()
    if t.lower() in SKIP_TITLES_EXACT:
        return True
    return any(p.match(t) for p in SKIP_PATTERNS)


# ---------- 章号抓取 ----------

# 按尝试顺序；抓到即返回
CHAPTER_PATTERNS = [
    re.compile(r'^(\d+)\.\s+'),              # "1. Title"
    re.compile(r'^Chapter\s+(\d+)\b', re.IGNORECASE),  # "Chapter 1" / "chapter 1: ..."
    re.compile(r'^CH\s*(\d+)\b'),            # "CH1", "CH 1"
    re.compile(r'^第(\d+)章'),                # "第1章"
]


def extract_chapter_num(title: str) -> int | None:
    """从标题抓章号；抓不到返回 None。只支持阿拉伯数字。"""
    t = (title or '').strip()
    for pat in CHAPTER_PATTERNS:
        m = pat.match(t)
        if m:
            return int(m.group(1))
    return None


# ---------- slot 分配 ----------

def _letter_suffix(idx: int) -> str:
    """0→'a', 1→'b', ... 25→'z', 26→'aa', ..."""
    if idx < 26:
        return chr(ord('a') + idx)
    first, second = divmod(idx - 26, 26)
    return chr(ord('a') + first) + chr(ord('a') + second)


def assign_slots(entries: list[dict]) -> list[dict]:
    """
    给每个 entry 分配 slot 字段。原地修改并返回 entries。

    entries: 已通过 is_skip 过滤的列表，按 TOC 出现顺序。
             每项至少有 'title'。
    """
    if not entries:
        return entries

    # Pass 1: 抓章号
    for e in entries:
        e['_ch_num'] = extract_chapter_num(e['title'])

    chapters = [i for i, e in enumerate(entries) if e['_ch_num'] is not None]

    # 降级：章号信号不足，走纯提取顺序
    if len(chapters) < 2:
        for i, e in enumerate(entries, start=1):
            e['slot'] = f"{i:02d}"
            e.pop('_ch_num', None)
        return entries

    first_ch = chapters[0]
    last_ch = chapters[-1]

    # Pass 2: 分配
    front_idx = 0
    back_idx = 0
    current_ch: int | None = None
    interlude_idx = 0

    for i, e in enumerate(entries):
        if e['_ch_num'] is not None:
            e['slot'] = f"{e['_ch_num']:02d}"
            current_ch = e['_ch_num']
            interlude_idx = 0
        elif i < first_ch:
            e['slot'] = f"00{_letter_suffix(front_idx)}"
            front_idx += 1
        elif i > last_ch:
            e['slot'] = f"99{_letter_suffix(back_idx)}"
            back_idx += 1
        else:
            # 章间插曲：a 位给 chapter 本身，插曲从 b 开始
            e['slot'] = f"{current_ch:02d}{_letter_suffix(interlude_idx + 1)}"
            interlude_idx += 1
        e.pop('_ch_num', None)

    return entries


# ---------- 文件名 ----------

def make_filename(slot: str, title: str, ext: str = 'txt') -> str:
    """统一文件名生成，避免 EPUB/PDF 两侧不一致。"""
    safe = re.sub(r'[^\w\s-]', '', title or '')[:50]
    safe = re.sub(r'\s+', '_', safe).strip('_')
    return f"{slot}_{safe}.{ext}"

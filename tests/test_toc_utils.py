#!/usr/bin/env python3
"""Tests for scripts/extract/toc_utils."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts' / 'extract'))

from toc_utils import (  # noqa: E402
    is_skip,
    extract_chapter_num,
    assign_slots,
    make_filename,
)


def _slots(titles: list[str]) -> list[str]:
    entries = [{'title': t} for t in titles if not is_skip(t)]
    assign_slots(entries)
    return [e['slot'] for e in entries]


def test_is_skip_basic():
    assert is_skip('Cover')
    assert is_skip('ACKNOWLEDGMENTS')  # case-insensitive
    assert is_skip('Acknowledgements')  # alt spelling
    assert is_skip('Table of Contents')
    assert is_skip('Index')
    assert is_skip('Dedication')
    assert not is_skip('Foreword')
    assert not is_skip('Preface')
    assert not is_skip('1. Introduction')


def test_is_skip_part_title():
    assert is_skip('Part II')
    assert is_skip('Part III: Some Subtitle')
    assert is_skip('PART 2')
    assert is_skip('Frontmatter')
    assert not is_skip('Particular Things')  # not "Part " prefix


def test_extract_chapter_num():
    assert extract_chapter_num('1. Introduction') == 1
    assert extract_chapter_num('12. Something') == 12
    assert extract_chapter_num('Chapter 3: Networks') == 3
    assert extract_chapter_num('CHAPTER 5') == 5
    assert extract_chapter_num('第7章 网络') == 7
    assert extract_chapter_num('Foreword') is None
    assert extract_chapter_num('Introduction') is None
    assert extract_chapter_num('1984 Revisited') is None  # 不误伤年份
    assert extract_chapter_num('1.1 Subsection') is None  # 子节不该被当成章号


def test_slots_normal_book():
    # 最典型：前言 + 正文 + 后记
    slots = _slots([
        'Cover',           # skip
        'Copyright',       # skip
        'Foreword',        # 00a
        'Preface',         # 00b
        '1. Introduction', # 01
        '2. Networks',     # 02
        '3. Futures',      # 03
        'Afterword',       # 99a
        'Bibliography',    # 99b
        'Index',           # skip
    ])
    assert slots == ['00a', '00b', '01', '02', '03', '99a', '99b']


def test_slots_interlude():
    slots = _slots([
        '1. First Chapter',
        'Interlude',
        '2. Second Chapter',
        'Another Interlude',
        'Third Interlude',
        '3. Third Chapter',
    ])
    assert slots == ['01', '01b', '02', '02b', '02c', '03']


def test_slots_part_titles_filtered():
    # damasio-style: Part 标题页被 SKIP 过滤掉，真章号不受影响
    slots = _slots([
        'Foreword',
        '1. Ch One',
        '2. Ch Two',
        'Part II',         # skip
        '3. Ch Three',
        '4. Ch Four',
        'Part III',        # skip
        '5. Ch Five',
    ])
    assert slots == ['00a', '01', '02', '03', '04', '05']


def test_slots_degrade_no_chapter_numbers():
    # 全书无章号前缀 → 纯提取顺序
    slots = _slots([
        'Networks of Affect',
        'Media Ecology',
        'Infrastructure',
        'Futures',
    ])
    assert slots == ['01', '02', '03', '04']


def test_slots_degrade_single_chapter():
    # 只有一个匹配章号也降级（章号信号不足）
    slots = _slots([
        'Foreword',
        '1. Only Chapter',
        'Afterword',
    ])
    assert slots == ['01', '02', '03']


def test_slots_chapter_num_gap():
    # 书本身跳号（罕见但合法）：保持真实章号
    slots = _slots([
        '1. Ch One',
        '3. Ch Three',  # 作者跳过 2
    ])
    assert slots == ['01', '03']


def test_slots_many_interludes():
    # 超过 26 个的字母进位（极端情况不应崩）。
    # 需要 >=2 个真章节避免触发降级。
    titles = ['1. Ch One'] + [f'Interlude {i}' for i in range(28)] + ['2. Ch Two']
    slots = _slots(titles)
    assert slots[0] == '01'
    assert slots[1] == '01b'       # 首个插曲从 b 起（a 是 chapter 本身）
    assert slots[25] == '01z'      # 第 25 个（idx 24+1）是 z
    assert slots[26] == '01aa'     # 第 26 个进位到 aa
    assert slots[27] == '01ab'
    assert slots[-1] == '02'


def test_make_filename_whitespace_consistency():
    # tab/newline 都要被归一化，避免 manifest vs 文件名不一致
    assert make_filename('01', 'Foo\tBar') == '01_Foo_Bar.txt'
    assert make_filename('01', 'Foo Bar  Baz') == '01_Foo_Bar_Baz.txt'
    assert make_filename('00a', 'Foreword') == '00a_Foreword.txt'


def test_make_filename_special_chars():
    assert make_filename('01', 'Chapter: A/B & C') == '01_Chapter_AB_C.txt'


if __name__ == '__main__':
    import traceback
    failed = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for t in tests:
        try:
            t()
            print(f'  ✓ {t.__name__}')
        except Exception:
            print(f'  ✗ {t.__name__}')
            traceback.print_exc()
            failed += 1
    print(f'\n{len(tests) - failed}/{len(tests)} passed')
    sys.exit(1 if failed else 0)

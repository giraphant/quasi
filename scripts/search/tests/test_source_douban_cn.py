#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import search
from sources import douban_cn


def test_supports():
    assert douban_cn.SUPPORTS == ["book"]


def test_direct_path_used_first():
    """When direct subject search returns results, no dokobot fallback called."""
    fake_direct = [{"title": "X", "year": 2020, "douban_subject_id": "1"}]
    with patch("sources.douban_cn._direct_search", return_value=fake_direct), \
         patch("sources.douban_cn._cndouban_works_page", return_value=[]) as mock_fb, \
         patch("sources.douban_cn._related_version_search", return_value=[]) as mock_related:
        r = douban_cn.search_book(search.BookQuery(title="X"))
    assert r.success is True
    assert len(r.entries) == 1
    assert not mock_fb.called
    assert not mock_related.called


def test_cjk_author_triggers_works_page():
    """When --author contains CJK, also enumerate works page for translations."""
    with patch("sources.douban_cn._direct_search", return_value=[]), \
         patch("sources.douban_cn._cndouban_works_page", return_value=[
             {"title": "原书中文版", "year": 2022, "douban_subject_id": "2"}
         ]) as mock_fb:
        r = douban_cn.search_book(search.BookQuery(author="哈拉维"))
    assert r.success is True
    assert mock_fb.called
    assert r.entries[0]["title"] == "原书中文版"


def test_subject_zh_triggers_related_versions_when_direct_hits():
    """--subject zh inspects direct hit related-version links and emits translations."""
    fake_direct = [{
        "title": "Original",
        "year": 1990,
        "douban_subject_id": "1",
        "preview_link": "https://book.douban.com/subject/1/",
    }]
    fake_related = [{
        "title": "原书中文版",
        "publisher": "河南大学出版社",
        "year": 2012,
        "douban_subject_id": "2",
        "douban_url": "https://book.douban.com/subject/2/",
        "isbn_13": "9787564906962",
    }]
    with patch("sources.douban_cn._direct_search", return_value=fake_direct), \
         patch("sources.douban_cn._related_version_search", return_value=fake_related) as mock_related, \
         patch("sources.douban_cn._cndouban_works_page", return_value=[]) as mock_fb:
        r = douban_cn.search_book(search.BookQuery(title="Original", subject="zh"))
    assert r.success is True
    assert mock_related.called
    assert not mock_fb.called
    assert len(r.entries) == 1
    assert r.entries[0]["title"] == "原书中文版"
    assert r.entries[0]["isbn_13"] == "9787564906962"


def test_parse_doko_references_decodes_link2_subject_url():
    body = """
    [35] https://www.douban.com/link2/?url=https%3A%2F%2Fbook.douban.com%2Fsubject%2F4175504%2F&query=X
    """
    refs = douban_cn._parse_doko_references(body)
    assert refs["35"] == "https://book.douban.com/subject/4175504/"


def test_parse_doko_subject_page_handles_inline_metadata():
    body = """
    # Cyborg Manifesto (豆瓣)
    **Cyborg Manifesto**
    作者: Donna J. Haraway [21]出版社: Feltrinelli出版年: 1995 ISBN: 9788807460012页数: 194装帧: Paperback
    8.7
    199人评价 [3]
    """
    parsed = douban_cn._parse_doko_subject_page(body, "https://book.douban.com/subject/4175504/")
    assert parsed is not None
    assert parsed["title"] == "Cyborg Manifesto"
    assert parsed["authors"] == ["Donna J. Haraway"]
    assert parsed["publisher"] == "Feltrinelli"
    assert parsed["year"] == 1995
    assert parsed["isbn_13"] == "9788807460012"
    assert parsed["ratings_count"] == 199


def main():
    tests = [
        test_supports,
        test_direct_path_used_first,
        test_cjk_author_triggers_works_page,
        test_subject_zh_triggers_related_versions_when_direct_hits,
        test_parse_doko_references_decodes_link2_subject_url,
        test_parse_doko_subject_page_handles_inline_metadata,
    ]
    failed = 0
    for t in tests:
        try: t(); print(f"  PASS  {t.__name__}")
        except Exception as e: failed += 1; print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

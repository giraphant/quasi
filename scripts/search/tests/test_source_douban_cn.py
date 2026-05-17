#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import search_new as search
from sources import douban_cn


def test_supports():
    assert douban_cn.SUPPORTS == ["book"]


def test_direct_path_used_first():
    """When direct subject search returns results, no dokobot fallback called."""
    fake_direct = [{"title": "X", "year": 2020, "douban_subject_id": "1"}]
    with patch("sources.douban_cn._direct_search", return_value=fake_direct), \
         patch("sources.douban_cn._cndouban_works_page", return_value=[]) as mock_fb:
        r = douban_cn.search_book(search.BookQuery(title="X"))
    assert r.success is True
    assert len(r.entries) == 1
    assert not mock_fb.called


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


def main():
    tests = [test_supports, test_direct_path_used_first, test_cjk_author_triggers_works_page]
    failed = 0
    for t in tests:
        try: t(); print(f"  PASS  {t.__name__}")
        except Exception as e: failed += 1; print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

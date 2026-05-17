#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import search_new as search
from sources import scholar


def test_supports_both():
    assert "book" in scholar.SUPPORTS
    assert "paper" in scholar.SUPPORTS


def test_book_search_filters_book_tag_only():
    """When called via search_book, only [BOOK]-tagged results are returned."""
    fake_raw = [
        {"title": "[BOOK] Cyborg Manifesto", "authors": ["Haraway"], "year": 1985,
         "url": "https://x"},
        {"title": "Cyborg paper", "authors": ["Haraway"], "year": 1991,
         "url": "https://y", "doi": "10.1/z"},
    ]
    with patch("sources.scholar._scrape_scholar", return_value=fake_raw):
        r = scholar.search_book(search.BookQuery(author="Haraway"))
    assert r.success is True
    assert len(r.entries) == 1
    assert "Cyborg Manifesto" in r.entries[0]["title"]


def test_paper_search_excludes_book_tag():
    fake_raw = [
        {"title": "[BOOK] B", "authors": ["X"], "year": 2000, "url": "u1"},
        {"title": "Article P", "authors": ["X"], "year": 2001, "url": "u2", "doi": "10.1/p"},
    ]
    with patch("sources.scholar._scrape_scholar", return_value=fake_raw):
        r = scholar.search_paper(search.PaperQuery(author="X"))
    assert r.success is True
    assert len(r.entries) == 1
    assert r.entries[0]["title"] == "Article P"


def test_captcha_returns_failure():
    with patch("sources.scholar._scrape_scholar", side_effect=scholar.ScholarBlockedError("captcha")):
        r = scholar.search_book(search.BookQuery(query="X"))
    assert r.success is False
    assert "captcha" in (r.error or "").lower()


def main():
    tests = [test_supports_both, test_book_search_filters_book_tag_only,
             test_paper_search_excludes_book_tag, test_captcha_returns_failure]
    failed = 0
    for t in tests:
        try: t(); print(f"  PASS  {t.__name__}")
        except Exception as e: failed += 1; print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

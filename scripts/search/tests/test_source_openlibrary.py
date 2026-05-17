#!/usr/bin/env python3
"""Tests for sources/openlibrary.py."""

from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import search_new as search
from sources import openlibrary


def test_openlibrary_book_only():
    assert openlibrary.SUPPORTS == ["book"]
    assert openlibrary.SOURCE_ID == "openlibrary"


def test_isbn_uses_isbn_param():
    fake = {"docs": [{"title": "T", "isbn": ["9780000000001"], "first_publish_year": 2020,
                      "author_name": ["X"], "key": "/works/OL1W"}]}
    with patch("sources.openlibrary._get_json", return_value=fake) as mock_get:
        r = openlibrary.search_book(search.BookQuery(isbn="9780000000001"))
    assert r.success is True
    assert "isbn=9780000000001" in mock_get.call_args[0][0]


def test_strict_author_uses_author_param():
    fake = {"docs": [{"title": "T", "author_name": ["Haraway"], "first_publish_year": 2016,
                      "key": "/works/OL2W"}]}
    with patch("sources.openlibrary._get_json", return_value=fake) as mock_get:
        r = openlibrary.search_book(search.BookQuery(author="Haraway"))
    assert r.success is True
    assert "author=Haraway" in mock_get.call_args[0][0]


def test_combined_title_author_uses_both():
    fake = {"docs": []}
    with patch("sources.openlibrary._get_json", return_value=fake) as mock_get:
        openlibrary.search_book(search.BookQuery(title="Cyborg Manifesto", author="Haraway"))
    url = mock_get.call_args[0][0]
    assert "title=Cyborg" in url
    assert "author=Haraway" in url


def main():
    tests = [test_openlibrary_book_only, test_isbn_uses_isbn_param,
             test_strict_author_uses_author_param, test_combined_title_author_uses_both]
    failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}")
        except Exception as e:
            failed += 1; print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

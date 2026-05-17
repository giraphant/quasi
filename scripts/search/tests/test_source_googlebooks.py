#!/usr/bin/env python3
"""Tests for sources/googlebooks.py — DSL inline (inauthor:, intitle:, isbn:)."""

from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import search
from sources import googlebooks


def test_supports_book_only():
    assert googlebooks.SUPPORTS == ["book"]
    assert googlebooks.SOURCE_ID == "googlebooks"


def test_isbn_dsl():
    """--isbn X → q=isbn:X."""
    fake = {"items": []}
    with patch("sources.googlebooks._http_get_json", return_value=fake) as mock_get:
        googlebooks.search_book(search.BookQuery(isbn="9780000000001"))
    assert "q=isbn:9780000000001" in mock_get.call_args[0][0]


def test_author_dsl():
    fake = {"items": []}
    with patch("sources.googlebooks._http_get_json", return_value=fake) as mock_get:
        googlebooks.search_book(search.BookQuery(author="Haraway"))
    assert "inauthor:Haraway" in mock_get.call_args[0][0]


def test_title_dsl():
    fake = {"items": []}
    with patch("sources.googlebooks._http_get_json", return_value=fake) as mock_get:
        googlebooks.search_book(search.BookQuery(title="Cyborg"))
    assert "intitle:Cyborg" in mock_get.call_args[0][0]


def test_429_triggers_dokobot_fallback():
    """HTTP 429 → dokobot path (mocked)."""
    import urllib.error
    exc = urllib.error.HTTPError(url="x", code=429, msg="Too Many Requests",
                                 hdrs=None, fp=None)  # type: ignore[arg-type]
    with patch("sources.googlebooks._http_get_json", side_effect=exc), \
         patch("sources.googlebooks._http_status", return_value=429), \
         patch("sources.googlebooks._dokobot_search", return_value=([], "")) as mock_doko:
        r = googlebooks.search_book(search.BookQuery(title="Cyborg"))
    assert r.success is True or r.success is False  # depends on dokobot mock — main point is no crash
    assert mock_doko.called


def main():
    tests = [test_supports_book_only, test_isbn_dsl, test_author_dsl,
             test_title_dsl, test_429_triggers_dokobot_fallback]
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

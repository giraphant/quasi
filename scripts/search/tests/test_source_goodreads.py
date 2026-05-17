#!/usr/bin/env python3
"""Tests for sources/goodreads.py."""

from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import search_new as search
from sources import goodreads as gr_adapter


def test_supports():
    assert gr_adapter.SUPPORTS == ["book"]


def test_calls_legacy_with_concatenated_query():
    fake_raw = [{"title": "T", "authors": ["A"], "year": 2020, "goodreads_id": 1}]
    with patch("sources.goodreads._scrape_goodreads", return_value=fake_raw) as mock_leg:
        r = gr_adapter.search_book(search.BookQuery(title="Cyborg", author="Haraway"))
    assert r.success is True
    assert len(r.entries) == 1
    assert r.entries[0]["title"] == "T"
    assert "Cyborg" in mock_leg.call_args[0][0]
    assert "Haraway" in mock_leg.call_args[0][0]


def test_legacy_exception_caught():
    with patch("sources.goodreads._scrape_goodreads", side_effect=RuntimeError("boom")):
        r = gr_adapter.search_book(search.BookQuery(title="X"))
    assert r.success is False
    assert "boom" in r.error


def main():
    tests = [test_supports, test_calls_legacy_with_concatenated_query,
             test_legacy_exception_caught]
    failed = 0
    for t in tests:
        try: t(); print(f"  PASS  {t.__name__}")
        except Exception as e: failed += 1; print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

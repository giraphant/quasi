#!/usr/bin/env python3
"""Tests for sources/amazon.py."""

from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import search
from sources import amazon


def test_supports():
    assert amazon.SUPPORTS == ["book"]
    assert amazon.SOURCE_ID == "amazon"


def test_calls_legacy_with_concatenated_query():
    fake = [{"title": "T", "authors": ["A"], "year": 2020, "asin": "B0TEST"}]
    with patch("sources.amazon._scrape_amazon", return_value=fake) as mock_leg:
        r = amazon.search_book(search.BookQuery(title="Cyborg", author="Haraway"))
    assert r.success is True
    assert r.entries[0]["asin"] == "B0TEST"
    assert "Cyborg" in mock_leg.call_args[0][0]


def test_legacy_exception_caught():
    with patch("sources.amazon._scrape_amazon", side_effect=RuntimeError("boom")):
        r = amazon.search_book(search.BookQuery(title="X"))
    assert r.success is False
    assert "boom" in r.error

#!/usr/bin/env python3
"""Tests for sources/openalex.py adapter."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import search
from sources import openalex


def test_openalex_supports_both():
    assert "book" in openalex.SUPPORTS
    assert "paper" in openalex.SUPPORTS
    assert openalex.SOURCE_ID == "openalex"


def test_book_search_by_isbn_routes_to_filter():
    """When query.isbn is set, adapter hits OA with filter=ids.isbn:X."""
    fake_resp = {"results": [{"id": "https://openalex.org/W123", "title": "X",
                              "publication_year": 2020, "ids": {"isbn": "9780000000001"}}]}
    with patch("sources.openalex._get_json", return_value=fake_resp) as mock_get:
        result = openalex.search_book(search.BookQuery(isbn="9780000000001"))
    assert result.success is True
    assert result.source == "openalex"
    assert len(result.entries) == 1
    called_url = mock_get.call_args[0][0]
    assert "filter=ids.isbn:9780000000001" in called_url


def test_book_search_empty_query_returns_failure():
    """No identifier at all → adapter still returns AdapterResult with success=False (not exception)."""
    result = openalex.search_book(search.BookQuery())
    assert result.success is False
    assert result.entries == []


def test_paper_search_by_doi_routes_to_lookup():
    fake_resp = {"id": "https://openalex.org/W999", "title": "Y", "doi": "10.1/x",
                 "publication_year": 2021}
    with patch("sources.openalex._get_json", return_value=fake_resp) as mock_get:
        result = openalex.search_paper(search.PaperQuery(doi="10.1/x"))
    assert result.success is True
    assert "works/doi:10.1/x" in mock_get.call_args[0][0] or "works/https" in mock_get.call_args[0][0]

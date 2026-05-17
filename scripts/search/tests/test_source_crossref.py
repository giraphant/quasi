#!/usr/bin/env python3
"""Tests for sources/crossref.py adapter."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import search_new as search
from sources import crossref


def test_crossref_paper_only():
    assert crossref.SUPPORTS == ["paper"]
    assert crossref.SOURCE_ID == "crossref"


def test_doi_lookup_hits_works_endpoint():
    fake_resp = {"status": "ok", "message": {
        "DOI": "10.1/y", "title": ["Test"], "issued": {"date-parts": [[2020]]},
        "author": [{"family": "Smith", "given": "J"}], "type": "journal-article",
    }}
    with patch("sources.crossref._get_json", return_value=fake_resp) as mock_get:
        r = crossref.search_paper(search.PaperQuery(doi="10.1/y"))
    assert r.success is True
    assert len(r.entries) == 1
    assert r.entries[0]["doi"] == "10.1/y"
    assert "works/10.1/y" in mock_get.call_args[0][0]


def test_author_filter_uses_query_author():
    """--author should map to query.author=X param."""
    fake_resp = {"status": "ok", "message": {"items": [
        {"DOI": "10.1/a", "title": ["A"], "author": [{"family": "Haraway"}],
         "issued": {"date-parts": [[2016]]}, "type": "book"},
    ]}}
    with patch("sources.crossref._get_json", return_value=fake_resp) as mock_get:
        r = crossref.search_paper(search.PaperQuery(author="Haraway", limit=5))
    assert r.success is True
    called_url = mock_get.call_args[0][0]
    assert "query.author=Haraway" in called_url


def test_empty_query_returns_failure():
    r = crossref.search_paper(search.PaperQuery())
    assert r.success is False


def main():
    tests = [
        test_crossref_paper_only,
        test_doi_lookup_hits_works_endpoint,
        test_author_filter_uses_query_author,
        test_empty_query_returns_failure,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except (AssertionError, Exception) as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

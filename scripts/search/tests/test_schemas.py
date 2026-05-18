#!/usr/bin/env python3
"""Tests for new search.py schemas: BookRecord / PaperRecord / SearchResponse."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import search


def test_book_record_blank_has_all_keys():
    """A blank BookRecord must have every canonical field, filled with None/[]/"" defaults."""
    r = search.BookRecord()
    d = r.to_dict()
    expected_keys = {
        "title", "subtitle", "authors", "translators", "original_title",
        "series", "year", "publish_date", "publisher", "language",
        "isbn_13", "isbn_10", "asin", "page_count", "description",
        "categories", "cover_url", "preview_link", "ratings",
        "cited_by_count", "source_ids", "_sources", "_field_src",
    }
    assert set(d.keys()) == expected_keys, f"missing/extra: {set(d.keys()) ^ expected_keys}"
    assert d["title"] == ""
    assert d["authors"] == []
    assert d["year"] is None
    assert d["ratings"] == {"count": None, "average": None}
    assert d["source_ids"] == {
        "openalex": None, "openlibrary": None, "googlebooks": None,
        "douban_cn": None, "goodreads": None, "storygraph": None,
        "amazon": None, "scholar": None,
    }


def test_paper_record_blank_has_all_keys():
    r = search.PaperRecord()
    d = r.to_dict()
    expected_keys = {
        "title", "authors", "year", "doi", "type", "publisher", "venue",
        "volume", "issue", "pages", "abstract", "cited_by_count",
        "is_oa", "oa_url", "url", "source_ids", "_sources", "_field_src",
    }
    assert set(d.keys()) == expected_keys, f"missing/extra: {set(d.keys()) ^ expected_keys}"
    assert d["doi"] is None
    assert d["authors"] == []
    assert d["source_ids"] == {"openalex": None, "crossref": None, "scholar": None}


def test_search_response_envelope_shape():
    """SearchResponse envelope has fixed top-level keys."""
    r = search.SearchResponse(kind="book", query={"title": "X"}, results=[])
    d = r.to_dict()
    assert set(d.keys()) == {"kind", "query", "results", "localisations", "diagnostics"}
    assert d["diagnostics"] == {
        "sources_attempted": [], "sources_hit": [], "errors": [],
        "conflicts": [], "raw_doko_excerpts": None,
    }


def test_book_query_optional_fields():
    """BookQuery accepts any subset of identifier fields."""
    q = search.BookQuery(isbn="9780822373780")
    assert q.isbn == "9780822373780"
    assert q.title is None
    assert q.author is None
    assert q.limit == 10  # default


def test_paper_query_optional_fields():
    q = search.PaperQuery(doi="10.1215/9780822373780")
    assert q.doi == "10.1215/9780822373780"
    assert q.limit == 30  # default differs from book


def test_adapter_result_shape():
    r = search.AdapterResult(source="openalex", success=True, entries=[{"title": "X"}])
    assert r.source == "openalex"
    assert r.success is True
    assert r.entries == [{"title": "X"}]
    assert r.error is None


def main():
    """Run all tests as a script (matches existing repo convention)."""
    tests = [
        test_book_record_blank_has_all_keys,
        test_paper_record_blank_has_all_keys,
        test_search_response_envelope_shape,
        test_book_query_optional_fields,
        test_paper_query_optional_fields,
        test_adapter_result_shape,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

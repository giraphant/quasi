#!/usr/bin/env python3
"""End-to-end tests for book_search() / paper_search() main functions.

Mocks each adapter's search_book/search_paper return values; verifies
the main function builds the SearchResponse envelope correctly,
runs adapters in parallel, and applies merge + sort.
"""

from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import search


def _adapter_result(source: str, entries: list[dict], success: bool = True) -> search.AdapterResult:
    return search.AdapterResult(source=source, success=success, entries=entries)


def test_book_search_fan_out_and_merge():
    """book_search calls all default adapters, merges, returns envelope."""
    def fake_oa(q): return _adapter_result("openalex",
                                            [{"title": "X", "isbn_13": "ISBN1", "year": 2020,
                                              "_sources": ["openalex"]}])
    def fake_ol(q): return _adapter_result("openlibrary",
                                            [{"title": "X", "isbn_13": "ISBN1", "year": 2020,
                                              "_sources": ["openlibrary"]}])
    fake = {"openalex": fake_oa, "openlibrary": fake_ol}

    with patch("search._adapter_search_book", side_effect=lambda src, q: fake[src](q)
                                                   if src in fake
                                                   else _adapter_result(src, [], success=False)):
        resp = search.book_search(search.BookQuery(isbn="ISBN1"))
    assert resp.kind == "book"
    assert len(resp.results) == 1
    assert resp.results[0]["title"] == "X"
    assert set(resp.diagnostics["sources_attempted"]) >= {"openalex", "openlibrary"}
    assert "openalex" in resp.diagnostics["sources_hit"]


def test_paper_search_returns_paper_envelope():
    fake_oa = _adapter_result("openalex", [{"title": "P", "doi": "10.1/x", "year": 2020,
                                             "_sources": ["openalex"]}])
    with patch("search._adapter_search_paper", return_value=fake_oa):
        resp = search.paper_search(search.PaperQuery(doi="10.1/x"))
    assert resp.kind == "paper"
    assert len(resp.results) >= 1


def test_failed_adapter_recorded_in_errors_not_raises():
    fail_result = search.AdapterResult(source="googlebooks", success=False,
                                        error="HTTP 429")
    ok = _adapter_result("openalex", [{"title": "X", "isbn_13": "i", "_sources": ["openalex"]}])
    fakes = {"openalex": ok, "googlebooks": fail_result}
    with patch("search._adapter_search_book",
               side_effect=lambda src, q: fakes.get(src,
                                                    search.AdapterResult(source=src,
                                                                          success=True, entries=[]))):
        resp = search.book_search(search.BookQuery(isbn="i"))
    assert any(e["source"] == "googlebooks" for e in resp.diagnostics["errors"])


def test_book_search_exposes_zh_localisations_sidecar():
    original = _adapter_result("openalex", [{
        "title": "Staying with the Trouble",
        "authors": ["Donna Haraway"],
        "isbn_13": "9780822373780",
        "year": 2016,
        "_sources": ["openalex"],
    }])
    zh = _adapter_result("douban_cn", [{
        "title": "与麻烦共处",
        "authors": ["唐娜·哈拉维"],
        "translators": ["译者甲"],
        "publisher": "某出版社",
        "year": 2024,
        "isbn_13": "9787000000001",
        "preview_link": "https://book.douban.com/subject/1234567/",
        "ratings": {"count": 100, "average": None},
        "source_ids": {"douban_cn": "1234567"},
        "_sources": ["douban_cn"],
    }])

    def fake(src, q):
        if src == "openalex":
            return original
        if src == "douban_cn" and q.subject == "zh":
            return zh
        return _adapter_result(src, [])

    with patch("search._adapter_search_book", side_effect=fake):
        resp = search.book_search(
            search.BookQuery(isbn="9780822373780", title="Staying with the Trouble"),
            sources=["openalex", "douban_cn"],
        )

    assert resp.results[0]["title"] == "Staying with the Trouble"
    assert resp.localisations["zh"]["status"] == "found"
    assert resp.localisations["zh"]["candidates"][0]["douban_id"] == "1234567"
    assert resp.localisations["zh"]["candidates"][0]["translator"] == "译者甲"


def main():
    tests = [test_book_search_fan_out_and_merge,
             test_paper_search_returns_paper_envelope,
             test_failed_adapter_recorded_in_errors_not_raises,
             test_book_search_exposes_zh_localisations_sidecar]
    failed = 0
    for t in tests:
        try: t(); print(f"  PASS  {t.__name__}")
        except Exception as e: failed += 1; print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Tests for the merge module — match keys, priority lists, conflict surfacing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import search


# Helper: build a BookRecord with overrides
def br(**kw) -> dict:
    r = search.BookRecord()
    for k, v in kw.items():
        setattr(r, k, v)
    return r.to_dict()


def test_isbn_exact_match_merges_records():
    """Two adapter entries with the same ISBN_13 collapse to one merged candidate."""
    by_source = {
        "openlibrary": [br(title="Imagination and Invention", isbn_13="9781517909437", year=2022)],
        "googlebooks": [br(title="Imagination and Invention", isbn_13="9781517909437", year=2023, page_count=200)],
    }
    merged = search.match_and_priority_merge(by_source, kind="book")
    assert len(merged) == 1
    assert merged[0]["isbn_13"] == "9781517909437"
    assert merged[0]["page_count"] == 200  # OL didn't have it; GB filled


def test_year_conflict_surfaces_in_diagnostics():
    """Simondon Q4-press case: 4 sources say 2023, 1 says 2022 — both go into evidence."""
    by_source = {
        "goodreads":   [br(title="Imagination and Invention", isbn_13="9781517909437", year=2023)],
        "amazon":      [br(title="Imagination and Invention", isbn_13="9781517909437", year=2023)],
        "openlibrary": [br(title="Imagination and Invention", isbn_13="9781517909437", year=2023)],
        "openalex":    [br(title="Imagination and Invention", isbn_13="9781517909437", year=2022)],
    }
    merged, conflicts = search.match_and_priority_merge_with_conflicts(by_source, kind="book")
    assert len(merged) == 1
    year_conflicts = [c for c in conflicts if c["field"] == "year"]
    assert len(year_conflicts) == 1
    c = year_conflicts[0]
    assert c["chosen"] == 2023  # priority list picks goodreads
    assert c["chosen_from"] == "goodreads"
    assert c["evidence"] == {
        "goodreads": 2023, "amazon": 2023, "openlibrary": 2023, "openalex": 2022,
    }


def test_no_conflict_when_all_sources_agree():
    by_source = {
        "goodreads":   [br(isbn_13="X", year=2023)],
        "openlibrary": [br(isbn_13="X", year=2023)],
    }
    _, conflicts = search.match_and_priority_merge_with_conflicts(by_source, kind="book")
    assert [c for c in conflicts if c["field"] == "year"] == []


def test_fuzzy_title_year_merge_when_no_isbn():
    """When neither record has an ISBN but titles match and years are within 1, merge."""
    by_source = {
        "amazon":   [br(title="Staying with the Trouble", year=2016)],
        "goodreads": [br(title="Staying with the Trouble: Making Kin in the Chthulucene", year=2016)],
    }
    merged = search.match_and_priority_merge(by_source, kind="book")
    assert len(merged) == 1
    # longest title wins
    assert merged[0]["title"] == "Staying with the Trouble: Making Kin in the Chthulucene"


def test_paper_doi_exact_match():
    pr = search.PaperRecord(title="X", doi="10.1234/y", year=2020).to_dict()
    pr2 = search.PaperRecord(title="X", doi="10.1234/y", year=2020, cited_by_count=42).to_dict()
    by_source = {"openalex": [pr], "crossref": [pr2]}
    merged = search.match_and_priority_merge(by_source, kind="paper")
    assert len(merged) == 1
    assert merged[0]["cited_by_count"] == 42


def test_conflict_only_on_whitelist_fields():
    """categories / subtitle / language disagreement does NOT surface as conflict."""
    by_source = {
        "goodreads":   [br(isbn_13="X", year=2023, categories=["Philosophy"], language="en")],
        "openlibrary": [br(isbn_13="X", year=2023, categories=["Theory"], language="eng")],
    }
    _, conflicts = search.match_and_priority_merge_with_conflicts(by_source, kind="book")
    fields = {c["field"] for c in conflicts}
    assert "year" not in fields  # agree
    assert "categories" not in fields  # not in whitelist
    assert "language" not in fields  # not in whitelist


def main():
    tests = [
        test_isbn_exact_match_merges_records,
        test_year_conflict_surfaces_in_diagnostics,
        test_no_conflict_when_all_sources_agree,
        test_fuzzy_title_year_merge_when_no_isbn,
        test_paper_doi_exact_match,
        test_conflict_only_on_whitelist_fields,
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

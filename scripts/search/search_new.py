#!/usr/bin/env python3
"""quasi-search — book / paper search across multiple sources.

Two-verb CLI. `quasi-search book` and `quasi-search paper` fan out to
per-platform source adapters in `sources/`, merge results into a fixed
BookRecord / PaperRecord schema, and emit a SearchResponse envelope.

This file is sectioned, top-to-bottom:
    1. SCHEMAS  — BookRecord, PaperRecord, SearchResponse, BookQuery, PaperQuery, AdapterResult
    2. MERGE    — match_and_priority + conflict surfacing
    3. BOOK     — book_search() main function
    4. PAPER    — paper_search() main function
    5. CLI      — argparse, main()

See docs/superpowers/specs/2026-05-17-search-refactor-design.md for design.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# adapter modules imported in Phase 4-9; left blank for skeleton


# ===============================================
# === 1. SCHEMAS
# ===============================================


@dataclass
class BookRecord:
    title: str = ""
    subtitle: str = ""
    authors: list[str] = field(default_factory=list)
    translators: list[str] = field(default_factory=list)
    original_title: str = ""
    series: str = ""
    year: int | None = None
    publish_date: str | None = None
    publisher: str = ""
    language: str | None = None
    isbn_13: str | None = None
    isbn_10: str | None = None
    asin: str | None = None
    page_count: int | None = None
    description: str = ""
    categories: list[str] = field(default_factory=list)
    cover_url: str | None = None
    preview_link: str = ""
    ratings: dict = field(default_factory=lambda: {"count": None, "average": None})
    cited_by_count: int | None = None
    source_ids: dict = field(default_factory=lambda: {
        "openalex": None, "openlibrary": None, "googlebooks": None,
        "douban_cn": None, "goodreads": None, "storygraph": None,
        "amazon": None, "scholar": None,
    })
    _sources: list[str] = field(default_factory=list)
    _field_src: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PaperRecord:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    type: str = ""
    publisher: str = ""
    venue: str = ""
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    abstract: str = ""
    cited_by_count: int | None = None
    is_oa: bool | None = None
    oa_url: str | None = None
    url: str = ""
    source_ids: dict = field(default_factory=lambda: {
        "openalex": None, "crossref": None, "scholar": None,
    })
    _sources: list[str] = field(default_factory=list)
    _field_src: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BookQuery:
    isbn: str | None = None
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    query: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    limit: int = 10


@dataclass
class PaperQuery:
    doi: str | None = None
    title: str | None = None
    author: str | None = None
    query: str | None = None
    year_from: int | None = None
    limit: int = 30


@dataclass
class AdapterResult:
    source: str
    success: bool
    entries: list[dict] = field(default_factory=list)
    error: str | None = None
    raw_excerpts: dict | None = None


@dataclass
class SearchResponse:
    kind: str  # "book" | "paper"
    query: dict
    results: list[dict] = field(default_factory=list)
    diagnostics: dict = field(default_factory=lambda: {
        "sources_attempted": [],
        "sources_hit": [],
        "errors": [],
        "conflicts": [],
        "raw_doko_excerpts": None,
    })

    def to_dict(self) -> dict:
        return asdict(self)


# ===============================================
# === 2. MERGE
# ===============================================

# (populated by Task 2.1)


# ===============================================
# === 3. BOOK SEARCH
# ===============================================

# (populated by Task 5.1)


# ===============================================
# === 4. PAPER SEARCH
# ===============================================

# (populated by Task 5.1)


# ===============================================
# === 5. CLI
# ===============================================

# (populated by Task 6.1)


if __name__ == "__main__":
    raise SystemExit("search_new.py: CLI not yet wired (Phase 6 pending)")

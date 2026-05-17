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


# --- identifier sniffers (used by adapters when caller passes ISBN/DOI as --query) ---

_ISBN_RE = re.compile(r"\b(?:97[89][- ]?)?\d{1,5}[- ]?\d{1,7}[- ]?\d{1,7}[- ]?[\dX]\b")
_DOI_RE  = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)


def sniff_isbn(s: str | None) -> str | None:
    """Return canonical ISBN (digits + uppercase X, no hyphens) if `s` is an ISBN-like string."""
    if not s:
        return None
    m = _ISBN_RE.search(s)
    if not m:
        return None
    raw = re.sub(r"[^\dX]", "", m.group(0).upper())
    if len(raw) in (10, 13):
        return raw
    return None


def sniff_doi(s: str | None) -> str | None:
    if not s:
        return None
    m = _DOI_RE.search(s)
    return m.group(0) if m else None


# ===============================================
# === 2. MERGE
# ===============================================


# Per-field source priority lists. Higher index = lower priority.
# Picked from current 0.20.0 schema; sources extended for scholar.
_BOOK_YEAR_PRIO  = ["goodreads", "amazon", "googlebooks", "openlibrary",
                    "storygraph", "douban_cn", "openalex", "scholar"]
_BOOK_PUB_PRIO   = ["goodreads", "amazon", "openlibrary", "googlebooks",
                    "storygraph", "douban_cn", "openalex", "scholar"]
_BOOK_ISBN_PRIO  = ["goodreads", "amazon", "openlibrary", "storygraph",
                    "douban_cn", "googlebooks", "scholar"]
_PAPER_YEAR_PRIO = ["openalex", "crossref", "scholar"]
_PAPER_PUB_PRIO  = ["openalex", "crossref", "scholar"]

# Fields whose conflicts are surfaced in diagnostics.conflicts.
_CONFLICT_FIELDS_BOOK  = {"year", "isbn_13", "publisher", "page_count", "authors"}
_CONFLICT_FIELDS_PAPER = {"year", "publisher", "authors"}


def _norm_title(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for fuzzy matching."""
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _title_fuzzy(a: str, b: str) -> float:
    """Jaccard token overlap on normalised titles.

    Also returns 1.0 when the shorter title's tokens are fully contained in
    the longer one — handles 'Title' vs 'Title: Subtitle' cases.
    """
    ta, tb = set(_norm_title(a).split()), set(_norm_title(b).split())
    if not ta or not tb:
        return 0.0
    # subset containment: short title is fully within the longer one
    shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if shorter and shorter.issubset(longer):
        return 1.0
    return len(ta & tb) / len(ta | tb)


def _book_match(a: dict, b: dict) -> bool:
    """Match key: ISBN exact, or fuzzy title + year within 1."""
    for k in ("isbn_13", "isbn_10"):
        if a.get(k) and b.get(k) and a[k] == b[k]:
            return True
    ya, yb = a.get("year"), b.get("year")
    if (a.get("title") and b.get("title")
            and _title_fuzzy(a["title"], b["title"]) >= 0.85
            and ya and yb and abs(ya - yb) <= 1):
        return True
    return False


def _paper_match(a: dict, b: dict) -> bool:
    if a.get("doi") and b.get("doi") and a["doi"] == b["doi"]:
        return True
    ya, yb = a.get("year"), b.get("year")
    if (a.get("title") and b.get("title")
            and _title_fuzzy(a["title"], b["title"]) >= 0.85
            and ya and yb and abs(ya - yb) <= 1):
        return True
    return False


def _pick_by_priority(entries_by_src: dict, field_name: str, prio: list[str]) -> tuple[Any, str | None]:
    """Return (chosen_value, source_id) by walking priority list, taking first non-empty."""
    for src in prio:
        if src in entries_by_src:
            v = entries_by_src[src].get(field_name)
            if v not in (None, "", [], {}):
                return v, src
    # fall back: any non-empty value from any source
    for src, e in entries_by_src.items():
        v = e.get(field_name)
        if v not in (None, "", [], {}):
            return v, src
    return None, None


def _merge_candidate(entries_by_src: dict[str, dict], kind: str) -> tuple[dict, list[dict]]:
    """Merge a set of matched entries (one per source) into one record + per-field conflicts."""
    is_book = kind == "book"
    merged = (BookRecord() if is_book else PaperRecord()).to_dict()

    year_prio = _BOOK_YEAR_PRIO if is_book else _PAPER_YEAR_PRIO
    pub_prio  = _BOOK_PUB_PRIO  if is_book else _PAPER_PUB_PRIO

    # title: longest wins (favours subtitled versions)
    title_candidates = [(s, e.get("title") or "") for s, e in entries_by_src.items()]
    title_candidates.sort(key=lambda x: -len(x[1]))
    if title_candidates and title_candidates[0][1]:
        merged["title"] = title_candidates[0][1]
        merged["_field_src"]["title"] = title_candidates[0][0]

    # year / publisher / isbn — priority-driven
    field_specs: list[tuple[str, list[str]]] = [
        ("year", year_prio),
        ("publisher", pub_prio),
    ]
    if is_book:
        field_specs.extend([
            ("isbn_13", _BOOK_ISBN_PRIO),
            ("isbn_10", _BOOK_ISBN_PRIO),
        ])

    for fld, prio in field_specs:
        v, src = _pick_by_priority(entries_by_src, fld, prio)
        if v is not None:
            merged[fld] = v
            merged["_field_src"][fld] = src

    # all other fields: first non-empty wins (source iteration order)
    skip = {"title", "year", "publisher", "isbn_13", "isbn_10",
            "_sources", "_field_src", "source_ids", "ratings"}
    for src, e in entries_by_src.items():
        for fld, v in e.items():
            if fld in skip:
                continue
            if v in (None, "", [], {}):
                continue
            if merged.get(fld) in (None, "", [], {}):
                merged[fld] = v
                merged["_field_src"][fld] = src

    # ratings / source_ids: component-wise union
    for src, e in entries_by_src.items():
        sids = e.get("source_ids") or {}
        for k, v in sids.items():
            if v and not merged["source_ids"].get(k):
                merged["source_ids"][k] = v
        if is_book:
            r = e.get("ratings") or {}
            if r.get("count") and not merged["ratings"]["count"]:
                merged["ratings"]["count"] = r["count"]
                merged["_field_src"]["ratings.count"] = src
            if r.get("average") and not merged["ratings"]["average"]:
                merged["ratings"]["average"] = r["average"]
                merged["_field_src"]["ratings.average"] = src

    merged["_sources"] = list(entries_by_src.keys())

    # Conflict surfacing on whitelist fields
    conflict_fields = _CONFLICT_FIELDS_BOOK if is_book else _CONFLICT_FIELDS_PAPER
    conflicts = []
    for fld in conflict_fields:
        evidence = {}
        for src, e in entries_by_src.items():
            v = e.get(fld)
            if v not in (None, "", [], {}):
                evidence[src] = v
        # only surface if there's actual disagreement
        unique_vals = {repr(v) for v in evidence.values()}
        if len(unique_vals) >= 2:
            conflicts.append({
                "field": fld,
                "chosen": merged.get(fld),
                "chosen_from": merged["_field_src"].get(fld),
                "evidence": evidence,
                "policy_note": None,
            })
    return merged, conflicts


def match_and_priority_merge(by_source: dict[str, list[dict]], kind: str) -> list[dict]:
    """Public API: merge multi-source entries into deduplicated candidate list."""
    merged, _ = match_and_priority_merge_with_conflicts(by_source, kind)
    return merged


def match_and_priority_merge_with_conflicts(
    by_source: dict[str, list[dict]], kind: str,
) -> tuple[list[dict], list[dict]]:
    """Merge + return (merged_candidates, all_conflicts_across_candidates)."""
    is_book = kind == "book"
    matcher = _book_match if is_book else _paper_match

    # Flatten all entries with their source label
    flat: list[tuple[str, dict]] = []
    for src, entries in by_source.items():
        for e in entries:
            flat.append((src, e))

    # Greedy clustering: each cluster = one merged candidate
    clusters: list[dict[str, dict]] = []
    for src, entry in flat:
        placed = False
        for cluster in clusters:
            if any(matcher(entry, e) for e in cluster.values()):
                # If source already in cluster, keep first occurrence (don't overwrite)
                cluster.setdefault(src, entry)
                placed = True
                break
        if not placed:
            clusters.append({src: entry})

    merged_list: list[dict] = []
    all_conflicts: list[dict] = []
    for cluster in clusters:
        m, c = _merge_candidate(cluster, kind)
        merged_list.append(m)
        all_conflicts.extend(c)

    # Sort: more sources first, then by ratings count (book) / cited_by (paper)
    if is_book:
        merged_list.sort(key=lambda r: (
            -len(r.get("_sources", [])),
            -(r.get("ratings", {}).get("count") or 0),
            -(r.get("cited_by_count") or 0),
        ))
    else:
        merged_list.sort(key=lambda r: (
            -(r.get("cited_by_count") or 0),
            -(r.get("year") or 0),
        ))
    return merged_list, all_conflicts


# ===============================================
# === 3. BOOK SEARCH
# ===============================================

import importlib
from concurrent.futures import as_completed
from sources import BOOK_ADAPTERS, PAPER_ADAPTERS

DEFAULT_BOOK_SOURCES = list(BOOK_ADAPTERS)
DEFAULT_PAPER_SOURCES = list(PAPER_ADAPTERS)


def _adapter_search_book(source_id: str, query: BookQuery) -> AdapterResult:
    """Look up sources/<source_id>.py and call its search_book."""
    try:
        mod = importlib.import_module(f"sources.{source_id}")
    except ImportError as e:
        return AdapterResult(source=source_id, success=False, error=f"adapter import failed: {e}")
    if "book" not in getattr(mod, "SUPPORTS", []):
        return AdapterResult(source=source_id, success=False,
                             error=f"adapter does not support book")
    return mod.search_book(query)


def book_search(query: BookQuery, sources: list[str] | None = None) -> SearchResponse:
    sources = sources or DEFAULT_BOOK_SOURCES
    diagnostics = {
        "sources_attempted": list(sources),
        "sources_hit": [],
        "errors": [],
        "conflicts": [],
        "raw_doko_excerpts": None,
    }
    by_source: dict[str, list[dict]] = {}

    with ThreadPoolExecutor(max_workers=min(8, len(sources) or 1)) as ex:
        futures = {ex.submit(_adapter_search_book, src, query): src for src in sources}
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                result = fut.result(timeout=60)
            except Exception as e:
                diagnostics["errors"].append({"source": src, "error": f"{type(e).__name__}: {e}"})
                continue
            if not result.success:
                diagnostics["errors"].append({"source": src, "error": result.error or "unknown"})
                continue
            if result.entries:
                diagnostics["sources_hit"].append(src)
                by_source[src] = result.entries
            if result.raw_excerpts:
                diagnostics["raw_doko_excerpts"] = (diagnostics["raw_doko_excerpts"] or {})
                diagnostics["raw_doko_excerpts"].update(result.raw_excerpts)

    merged, conflicts = match_and_priority_merge_with_conflicts(by_source, kind="book")
    diagnostics["conflicts"] = conflicts

    return SearchResponse(
        kind="book",
        query=asdict(query),
        results=merged,
        diagnostics=diagnostics,
    )


# ===============================================
# === 4. PAPER SEARCH
# ===============================================


def _adapter_search_paper(source_id: str, query: PaperQuery) -> AdapterResult:
    try:
        mod = importlib.import_module(f"sources.{source_id}")
    except ImportError as e:
        return AdapterResult(source=source_id, success=False, error=f"adapter import failed: {e}")
    if "paper" not in getattr(mod, "SUPPORTS", []):
        return AdapterResult(source=source_id, success=False,
                             error="adapter does not support paper")
    return mod.search_paper(query)


def paper_search(query: PaperQuery, sources: list[str] | None = None) -> SearchResponse:
    sources = sources or DEFAULT_PAPER_SOURCES
    diagnostics = {
        "sources_attempted": list(sources), "sources_hit": [],
        "errors": [], "conflicts": [], "raw_doko_excerpts": None,
    }
    by_source: dict[str, list[dict]] = {}

    with ThreadPoolExecutor(max_workers=min(8, len(sources) or 1)) as ex:
        futures = {ex.submit(_adapter_search_paper, src, query): src for src in sources}
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                result = fut.result(timeout=60)
            except Exception as e:
                diagnostics["errors"].append({"source": src, "error": str(e)})
                continue
            if not result.success:
                diagnostics["errors"].append({"source": src, "error": result.error or "unknown"})
                continue
            if result.entries:
                diagnostics["sources_hit"].append(src)
                by_source[src] = result.entries

    merged, conflicts = match_and_priority_merge_with_conflicts(by_source, kind="paper")
    diagnostics["conflicts"] = conflicts

    return SearchResponse(
        kind="paper",
        query=asdict(query),
        results=merged,
        diagnostics=diagnostics,
    )


# ===============================================
# === 5. CLI
# ===============================================

# (populated by Task 6.1)


if __name__ == "__main__":
    raise SystemExit("search_new.py: CLI not yet wired (Phase 6 pending)")

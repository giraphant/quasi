"""Douban CN adapter — books only (CJK / Chinese-translation lookup).

Combines two legacy paths:
    1. douban_direct.search_douban_direct (primary subject search, no dokobot)
    2. cndouban.run_cndouban (works-page CJK enumeration, dokobot-driven)

Path selection (internal, caller doesn't specify):
    - For non-CJK author / general query: primary direct path
    - For CJK author / explicit --subject zh / when direct returns nothing:
      fall back to works-page enumeration
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import search_new as _s
from douban_direct import search_douban_direct as _direct_search_legacy
from cndouban import run_cndouban as _cndouban_legacy

SUPPORTS = ["book"]
SOURCE_ID = "douban_cn"


def _has_cjk(s: str | None) -> bool:
    return bool(s) and any("一" <= c <= "鿿" for c in s)


def _normalise(raw: dict) -> dict:
    b = _s.BookRecord().to_dict()
    b["title"]          = raw.get("title", "") or ""
    b["authors"]        = raw.get("authors") or ([raw.get("author")] if raw.get("author") else [])
    b["translators"]    = ([raw.get("translator")] if raw.get("translator") else []) \
                          or (raw.get("translators") or [])
    b["original_title"] = raw.get("original_title", "") or ""
    b["year"]           = raw.get("year")
    b["publisher"]      = raw.get("publisher", "") or ""
    b["isbn_13"]        = raw.get("isbn") if (raw.get("isbn") and len(raw["isbn"]) == 13) else None
    b["isbn_10"]        = raw.get("isbn") if (raw.get("isbn") and len(raw["isbn"]) == 10) else None
    b["language"]       = "zh"
    b["ratings"]        = {"count": raw.get("ratings_count"),
                           "average": raw.get("douban_rating")}
    b["preview_link"]   = raw.get("douban_url", "") or raw.get("preview_link", "") or ""
    b["source_ids"]["douban_cn"] = raw.get("douban_subject_id") or raw.get("douban_id")
    b["_sources"] = [SOURCE_ID]
    return b


def _direct_search(query: _s.BookQuery) -> list[dict]:
    """Wrap douban_direct.search_douban_direct with our query dataclass."""
    q_text = " ".join(filter(None, [
        query.isbn, query.title, query.author, query.query,
    ]))
    if not q_text:
        return []
    try:
        result = _direct_search_legacy(q_text, limit=query.limit)
        return (result.get("results") if isinstance(result, dict) else result) or []
    except Exception:
        return []


def _cndouban_works_page(query: _s.BookQuery) -> list[dict]:
    """Wrap cndouban.run_cndouban (works-page enumeration via dokobot)."""
    import argparse
    args = argparse.Namespace(
        isbn=query.isbn, title=query.title, author=query.author,
        slug=None, year=query.year_from,
    )
    try:
        # run_cndouban writes JSON to stdout; we want it returned.
        # Refactor: the legacy run_cndouban returns int exit code and prints.
        # For adapter use, we'll need a refactor that returns the structured result.
        # As an interim shim:
        from io import StringIO
        import contextlib, json as _json
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            _cndouban_legacy(args)
        try:
            payload = _json.loads(buf.getvalue())
        except _json.JSONDecodeError:
            return []
        return payload.get("translations") or []
    except Exception:
        return []


def search_book(query: _s.BookQuery) -> _s.AdapterResult:
    if not any([query.isbn, query.title, query.author, query.query, query.subject]):
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No query")
    # Primary path
    direct = _direct_search(query)
    works = []
    # Fallback when primary empty AND we have CJK author or subject 'zh'
    if not direct and (_has_cjk(query.author) or (query.subject or "").lower() in ("zh", "chinese")):
        works = _cndouban_works_page(query)
    all_raw = direct + works
    if not all_raw:
        return _s.AdapterResult(source=SOURCE_ID, success=True, entries=[])  # success, just empty
    return _s.AdapterResult(source=SOURCE_ID, success=True,
                            entries=[_normalise(e) for e in all_raw[:query.limit]])

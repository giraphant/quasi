"""Amazon adapter — books only.

Wraps existing scripts/search/amazon.py:search_amazon(). source_ids.amazon
= ASIN. Phase 9 will inline the legacy scraper and delete the standalone file.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import search_new as _s
from amazon import search_amazon as _legacy

SUPPORTS = ["book"]
SOURCE_ID = "amazon"


def _normalise(raw: dict) -> dict:
    """Project legacy amazon dict to BookRecord."""
    b = _s.BookRecord().to_dict()
    b["title"]       = raw.get("title", "") or ""
    b["authors"]     = raw.get("authors") or []
    b["year"]        = raw.get("year")
    b["asin"]        = raw.get("asin")
    b["source_ids"]["amazon"] = raw.get("asin")
    b["preview_link"]= raw.get("url", "") or ""
    b["cover_url"]   = raw.get("cover_url")
    b["page_count"]  = raw.get("page_count")
    b["publisher"]   = raw.get("publisher", "") or ""
    b["isbn_13"]     = raw.get("isbn_13")
    b["isbn_10"]     = raw.get("isbn_10")
    b["ratings"]     = {"count": raw.get("ratings_count"),
                        "average": raw.get("amazon_rating")}
    b["_sources"] = [SOURCE_ID]
    return b


def search_book(query: _s.BookQuery) -> _s.AdapterResult:
    """Search Amazon for books."""
    q_text = " ".join(filter(None, [
        query.isbn, query.title, query.author, query.subject, query.query,
    ]))
    if not q_text:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No query")
    try:
        result = _legacy(q_text, limit=query.limit)
        raw = result.get("results") if isinstance(result, dict) else result
        raw = raw or []
        return _s.AdapterResult(source=SOURCE_ID, success=True,
                                entries=[_normalise(e) for e in raw])
    except Exception as e:
        return _s.AdapterResult(source=SOURCE_ID, success=False,
                                error=f"{type(e).__name__}: {e}")

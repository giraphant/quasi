"""Goodreads adapter — books only.

Scraper. No strict author/title param — falls back to full-text search.
Port of existing scripts/search/goodreads.py:search_goodreads().
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import search_new as _s

# Import the existing scraper module's main function. After Phase 9
# delete, that file will be removed and this import becomes self-contained.
# For Phase 4, we keep the old file in place and just wrap it.
sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: duplicate but explicit
from goodreads import search_goodreads as _legacy_search  # noqa: E402

SUPPORTS = ["book"]
SOURCE_ID = "goodreads"


def _normalise(raw: dict) -> dict:
    """Project legacy goodreads dict to BookRecord."""
    b = _s.BookRecord().to_dict()
    b["title"]      = raw.get("title", "") or ""
    b["authors"]    = raw.get("authors") or []
    b["year"]       = raw.get("year")
    b["isbn_13"]    = raw.get("isbn_13")
    b["isbn_10"]    = raw.get("isbn_10")
    b["page_count"] = raw.get("page_count")
    b["description"]= raw.get("description", "") or ""
    b["cover_url"]  = raw.get("cover_url")
    b["preview_link"]= raw.get("url", "") or ""
    b["publisher"]  = raw.get("publisher", "") or ""
    b["categories"] = raw.get("categories") or []
    b["ratings"]    = {
        "count":   raw.get("ratings_count"),
        "average": raw.get("avg_rating"),
    }
    b["source_ids"]["goodreads"] = str(raw.get("goodreads_id") or "") or None
    b["_sources"] = [SOURCE_ID]
    return b


def search_book(query: _s.BookQuery) -> _s.AdapterResult:
    # Build a free-text query from whatever the caller gave us.
    q_text = " ".join(filter(None, [
        query.isbn, query.title, query.author, query.subject, query.query,
    ]))
    if not q_text:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No identifier or query")
    try:
        raw_entries = _legacy_search(q_text, limit=query.limit) or []
        entries = [_normalise(e) for e in raw_entries]
        return _s.AdapterResult(source=SOURCE_ID, success=True, entries=entries)
    except Exception as e:
        return _s.AdapterResult(source=SOURCE_ID, success=False,
                                error=f"{type(e).__name__}: {e}")

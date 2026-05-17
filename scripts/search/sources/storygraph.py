"""StoryGraph adapter — books only.

Wraps existing scripts/search/storygraph.py:search_storygraph().
Translator field normalised from str → list. Phase 9 will inline the legacy
scraper and delete the standalone file.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import search_new as _s
from storygraph import search_storygraph as _legacy

SUPPORTS = ["book"]
SOURCE_ID = "storygraph"


def _normalise(raw: dict) -> dict:
    """Project legacy storygraph dict to BookRecord."""
    b = _s.BookRecord().to_dict()
    b["title"]       = raw.get("title", "") or ""
    b["authors"]     = raw.get("authors") or []
    # StoryGraph returns translator as a string, normalise to list
    tr = raw.get("translator")
    b["translators"] = [tr] if (tr and isinstance(tr, str)) else (tr or [])
    b["year"]        = raw.get("year")
    b["page_count"]  = raw.get("page_count")
    b["preview_link"]= raw.get("preview_link", "") or ""
    b["cover_url"]   = raw.get("cover_url")
    b["categories"]  = raw.get("categories") or raw.get("genres") or []
    b["source_ids"]["storygraph"] = raw.get("storygraph_id")
    b["_sources"] = [SOURCE_ID]
    return b


def search_book(query: _s.BookQuery) -> _s.AdapterResult:
    """Search StoryGraph for books."""
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

"""OpenLibrary adapter — books only.

Endpoint: /search.json — accepts strict ?isbn, ?author, ?title, ?subject + ?q.
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import search_new as _s
import requests

SUPPORTS = ["book"]
SOURCE_ID = "openlibrary"

_BASE = "https://openlibrary.org/search.json"


def _get_json(url: str, timeout: int = 20) -> dict | None:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "quasi-search/1.0"})
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def _normalise(doc: dict) -> dict:
    b = _s.BookRecord().to_dict()
    b["title"]    = doc.get("title") or ""
    b["subtitle"] = doc.get("subtitle") or ""
    b["authors"]  = doc.get("author_name") or []
    b["year"]     = doc.get("first_publish_year")
    pubs          = doc.get("publisher") or []
    b["publisher"] = " / ".join(pubs) if pubs else ""
    isbns          = doc.get("isbn") or []
    isbn13 = next((i for i in isbns if len(i.replace("-", "")) == 13), None)
    isbn10 = next((i for i in isbns if len(i.replace("-", "")) == 10), None)
    b["isbn_13"] = (isbn13 or "").replace("-", "") or None
    b["isbn_10"] = (isbn10 or "").replace("-", "") or None
    b["page_count"] = doc.get("number_of_pages_median")
    b["language"]   = (doc.get("language") or [None])[0]
    b["preview_link"] = f"https://openlibrary.org{doc.get('key','')}" if doc.get("key") else ""
    b["source_ids"]["openlibrary"] = doc.get("key") or None
    b["_sources"] = [SOURCE_ID]
    return b


def search_book(query: _s.BookQuery) -> _s.AdapterResult:
    isbn = query.isbn or _s.sniff_isbn(query.query)
    params: list[str] = [f"limit={query.limit}"]
    if isbn:
        params.append(f"isbn={isbn}")
    if query.author:
        params.append(f"author={urllib.parse.quote(query.author)}")
    if query.title:
        params.append(f"title={urllib.parse.quote(query.title)}")
    if query.subject:
        params.append(f"subject={urllib.parse.quote(query.subject)}")
    if query.query and not (isbn or query.author or query.title or query.subject):
        params.append(f"q={urllib.parse.quote(query.query)}")
    if query.year_from:
        params.append(f"first_publish_year={query.year_from}-{query.year_to or 9999}")

    if not any(p.startswith(("isbn=", "author=", "title=", "subject=", "q=")) for p in params):
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No identifier or query")

    url = f"{_BASE}?{'&'.join(params)}"
    data = _get_json(url)
    if data is None:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="HTTP failure")
    docs = data.get("docs") or []
    entries = [_normalise(d) for d in docs[:query.limit]]
    return _s.AdapterResult(source=SOURCE_ID, success=True, entries=entries)

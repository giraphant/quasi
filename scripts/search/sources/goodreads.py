"""Goodreads adapter — books only.

Scraper. No strict author/title param — falls back to full-text search.
Inlined from scripts/search/goodreads.py (Phase 9.1). The standalone file
is kept on disk until Phase 9.2 deletes it.

Two-stage pipeline:
  1. Autocomplete (`/book/auto_complete?format=json`) — fast, returns basic
     metadata (title, author, pages, rating, bookId).
  2. Book page (`/book/show/{id}`) — scrapes `__NEXT_DATA__` Apollo state
     for full metadata (ISBN, publisher, date, genres, translators,
     originalTitle, ASIN, cover, description).

No auth required.  No browser/dokobot dependency — plain urllib works
because the autocomplete endpoint is a public JSON API and the book page
serves server-rendered HTML with embedded Apollo state.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import search_new as _s

SUPPORTS = ["book"]
SOURCE_ID = "goodreads"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_AUTOCOMPLETE_URL = "https://www.goodreads.com/book/auto_complete"
_BOOK_URL = "https://www.goodreads.com/book/show"


def _fetch(url: str, timeout: int = 20, accept: str | None = None) -> tuple[int, str]:
    headers: dict[str, str] = {"User-Agent": _UA}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        return e.code, body
    except Exception as e:
        return 0, str(e)


# ------------------------------------------------------------------
# Stage 1: Autocomplete
# ------------------------------------------------------------------

def _autocomplete(query: str, limit: int = 20) -> list[dict]:
    url = f"{_AUTOCOMPLETE_URL}?format=json&q={urllib.parse.quote(query)}"
    status, body = _fetch(url, accept="application/json")
    if status != 200:
        return []
    try:
        data = json.loads(body)
        return data[:limit] if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ------------------------------------------------------------------
# Stage 2: Book page Apollo state
# ------------------------------------------------------------------

_NEXT_DATA_RE = re.compile(
    r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def _extract_year_from_epoch_ms(ms: int | float | None) -> int | None:
    if not ms or not isinstance(ms, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).year
    except (OSError, ValueError):
        return None


def _extract_date_from_epoch_ms(ms: int | float | None) -> str | None:
    if not ms or not isinstance(ms, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OSError, ValueError):
        return None


def _clean_isbn(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9X]", "", str(raw).upper())
    return cleaned if cleaned else None


def _get_nested(obj: dict, *keys):
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _scrape_book_page(book_id: str) -> dict | None:
    """Scrape a Goodreads book page and extract metadata from Apollo state."""
    url = f"{_BOOK_URL}/{book_id}"
    status, body = _fetch(url)
    if status != 200:
        return None

    m = _NEXT_DATA_RE.search(body)
    if not m:
        return None

    try:
        nd = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

    apollo = _get_nested(nd, "props", "pageProps", "apolloState")
    if not isinstance(apollo, dict):
        return None

    book_keys = [k for k in apollo if k.startswith("Book:")]
    if not book_keys:
        return None
    bk = apollo[book_keys[0]]
    if not isinstance(bk, dict):
        return None

    details = bk.get("details") or {}

    # Authors & translators
    authors: list[str] = []
    translators: list[str] = []

    def _collect_contributor(edge):
        if not isinstance(edge, dict):
            return
        role = (edge.get("role") or "").lower()
        ref = _get_nested(edge, "node", "__ref")
        if not ref or ref not in apollo:
            return
        name = apollo[ref].get("name", "")
        if not name or name.lower() == "unknown author":
            return
        if role == "translator":
            if name not in translators:
                translators.append(name)
        elif role in ("author", "pseudonym", ""):
            if name not in authors:
                authors.append(name)

    _collect_contributor(bk.get("primaryContributorEdge"))
    for edge in bk.get("secondaryContributorEdges") or []:
        _collect_contributor(edge)

    # Genres
    genres: list[str] = []
    for g in bk.get("bookGenres") or []:
        if isinstance(g, dict):
            name = _get_nested(g, "genre", "name")
            if name and name not in genres:
                genres.append(name)

    # Original title
    original_title = ""
    work_ref = _get_nested(bk, "work", "__ref")
    if work_ref and work_ref in apollo:
        original_title = _get_nested(apollo[work_ref], "details", "originalTitle") or ""

    # Description
    desc = bk.get('description({"stripped":true})') or ""
    if not desc:
        raw_desc = bk.get("description")
        if isinstance(raw_desc, dict):
            desc = raw_desc.get("html") or raw_desc.get("text") or ""
        elif isinstance(raw_desc, str):
            desc = raw_desc
    # Strip HTML tags from description
    desc = re.sub(r"<[^>]+>", "", desc).strip()

    isbn_raw = _clean_isbn(str(details.get("isbn", "")))
    isbn13_raw = _clean_isbn(str(details.get("isbn13", "")))
    isbn_10 = isbn_raw if isbn_raw and len(isbn_raw) == 10 else (
              isbn13_raw if isbn13_raw and len(isbn13_raw) == 10 else None)
    isbn_13 = isbn13_raw if isbn13_raw and len(isbn13_raw) == 13 else (
              isbn_raw if isbn_raw and len(isbn_raw) == 13 else None)

    pub_time = details.get("publicationTime")

    return {
        "title": bk.get("title") or bk.get("titleComplete") or "",
        "authors": authors,
        "translators": translators,
        "year": _extract_year_from_epoch_ms(pub_time),
        "publish_date": _extract_date_from_epoch_ms(pub_time),
        "publisher": details.get("publisher") or "",
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "page_count": details.get("numPages"),
        "asin": details.get("asin") or "",
        "categories": genres,
        "original_title": original_title,
        "description": desc[:500] if desc else "",
        "cover_url": bk.get("imageUrl") or "",
        "preview_link": f"{_BOOK_URL}/{book_id}",
        "book_id": book_id,
    }


# ------------------------------------------------------------------
# Scrape entry point (formerly search_goodreads in legacy file)
# ------------------------------------------------------------------

def _scrape_goodreads(
    query: str,
    limit: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
    enrich: bool = True,
) -> list[dict]:
    """Search Goodreads. Returns a list of raw result dicts.

    When *enrich* is True (default), fetches the book page for each
    autocomplete hit to get ISBN / publisher / genres / translators.
    Set to False for fast search-only mode (no ISBN, no publisher).
    """
    ac_results = _autocomplete(query, limit=min(limit * 2, 25))
    if not ac_results:
        return []

    results: list[dict] = []
    for item in ac_results:
        book_id = str(item.get("bookId") or item.get("id") or "")
        if not book_id:
            continue

        title = (item.get("title") or "").strip()
        author_obj = item.get("author")
        author_name = ""
        if isinstance(author_obj, dict):
            author_name = author_obj.get("name", "")
        elif isinstance(author_obj, str):
            author_name = author_obj
        if not author_name:
            author_name = str(item.get("authorName") or item.get("author_name") or "")

        entry: dict = {
            "title": title,
            "subtitle": "",
            "authors": [author_name] if author_name else [],
            "year": None,
            "publisher": "",
            "isbn_13": None,
            "isbn_10": None,
            "description": "",
            "categories": [],
            "page_count": item.get("numPages"),
            "preview_link": f"{_BOOK_URL}/{book_id}",
            "goodreads_id": book_id,
            "avg_rating": item.get("avgRating"),
            "ratings_count": item.get("ratingsCount"),
            "source": "Goodreads",
        }

        if enrich:
            time.sleep(0.4)
            detail = _scrape_book_page(book_id)
            if detail:
                entry["title"] = detail["title"] or entry["title"]
                entry["authors"] = detail["authors"] or entry["authors"]
                entry["year"] = detail["year"]
                entry["publisher"] = detail["publisher"]
                entry["isbn_13"] = detail["isbn_13"]
                entry["isbn_10"] = detail["isbn_10"]
                entry["page_count"] = detail["page_count"] or entry["page_count"]
                entry["description"] = detail["description"]
                entry["categories"] = detail["categories"]
                entry["asin"] = detail["asin"]
                entry["original_title"] = detail["original_title"]
                entry["translators"] = detail["translators"]
                entry["cover_url"] = detail["cover_url"]

        # Year filter
        if year_from and entry.get("year") and entry["year"] < year_from:
            continue
        if year_to and entry.get("year") and entry["year"] > year_to:
            continue

        results.append(entry)
        if len(results) >= limit:
            break

    return results


# ------------------------------------------------------------------
# Adapter normalise + search_book
# ------------------------------------------------------------------

def _normalise(raw: dict) -> dict:
    """Project goodreads result dict to BookRecord."""
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
        raw_entries = _scrape_goodreads(q_text, limit=query.limit) or []
        entries = [_normalise(e) for e in raw_entries]
        return _s.AdapterResult(source=SOURCE_ID, success=True, entries=entries)
    except Exception as e:
        return _s.AdapterResult(source=SOURCE_ID, success=False,
                                error=f"{type(e).__name__}: {e}")

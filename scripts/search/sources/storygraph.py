"""StoryGraph adapter — books only.

Translator field normalised from str → list. Inlined from
scripts/search/storygraph.py (Phase 9.1). Standalone file kept until Phase 9.2.

StoryGraph blocks non-browser TLS fingerprints (returns 403).  curl_cffi
with `impersonate="chrome"` bypasses this by using Chrome's TLS stack.

Two-stage pipeline:
  1. Search (`/browse?search_term=...`) — returns book panes with title,
     author, link, and book ID.
  2. Editions page (`/books/{id}/editions`) — returns per-edition metadata
     (ISBN, publisher, date, pages) across all available editions.

Falls back gracefully when curl_cffi is not installed.
"""

from __future__ import annotations

import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import search_new as _s

try:
    from curl_cffi import requests as _cffi_requests
    _HAS_CFFI = True
except ImportError:
    _HAS_CFFI = False

SUPPORTS = ["book"]
SOURCE_ID = "storygraph"

_BASE = "https://app.thestorygraph.com"


def _fetch(url: str, timeout: int = 15) -> tuple[int, str]:
    if not _HAS_CFFI:
        return 0, "curl_cffi not installed"
    try:
        r = _cffi_requests.get(url, impersonate="chrome", timeout=timeout)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


# ------------------------------------------------------------------
# Parse helpers
# ------------------------------------------------------------------

_BOOK_LINK_RE = re.compile(r'<a[^>]*href="(/books/[0-9a-f-]+)"[^>]*>([^<]*)</a>')
_ISBN13_RE = re.compile(r"\b(97[89]\d{10})\b")
_PAGES_RE = re.compile(r"(\d+)\s*pages", re.IGNORECASE)
_PUBLISHER_RE = re.compile(r"Publisher:\s*([^<\n]+)", re.IGNORECASE)
_PUB_DATE_RE = re.compile(
    r"(?:Edition Pub Date|Edition Published|Pub Date):\s*([^<\n]+)",
    re.IGNORECASE,
)
_ISBN_LABEL_RE = re.compile(r"ISBN(?:/UID)?:\s*([^<\n]+)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")


def _extract_year(date_str: str) -> int | None:
    m = _YEAR_RE.search(date_str or "")
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _parse_search_results(body: str) -> list[dict]:
    """Extract book entries from a StoryGraph search page."""
    results: list[dict] = []
    seen_hrefs: set[str] = set()

    for href, title in _BOOK_LINK_RE.findall(body):
        title = title.strip()
        if not title or "/editions" in href:
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        # Extract book UUID from href
        book_id_m = re.search(r"/books/([0-9a-f-]+)", href)
        book_id = book_id_m.group(1) if book_id_m else ""

        results.append({
            "title": title,
            "href": href,
            "book_id": book_id,
            "full_link": f"{_BASE}{href}",
        })

    return results


def _parse_editions(body: str) -> list[dict]:
    """Parse edition metadata from a StoryGraph editions page.

    Splits the HTML by `data-book-id` boundaries and extracts
    ISBN / publisher / date / pages from each edition block.
    """
    editions: list[dict] = []
    # Split on edition boundaries
    chunks = re.split(r'data-book-id="', body)
    if len(chunks) <= 1:
        return editions

    for chunk in chunks[1:]:
        eid = chunk.split('"')[0] if '"' in chunk else ""

        isbn_13 = None
        isbn_10 = None
        publisher = None
        pub_date = None
        year = None
        pages = None

        # ISBN from label
        isbn_label_m = _ISBN_LABEL_RE.search(chunk)
        if isbn_label_m:
            raw = isbn_label_m.group(1).strip()
            digits = re.sub(r"[^0-9X]", "", raw, flags=re.IGNORECASE)
            if len(digits) == 13:
                isbn_13 = digits
            elif len(digits) == 10:
                isbn_10 = digits

        # ISBN-13 from raw text (fallback)
        if not isbn_13:
            isbn_m = _ISBN13_RE.search(chunk)
            if isbn_m:
                isbn_13 = isbn_m.group(1)

        # Publisher
        pub_m = _PUBLISHER_RE.search(chunk)
        if pub_m:
            publisher = pub_m.group(1).strip().rstrip("<")

        # Date
        date_m = _PUB_DATE_RE.search(chunk)
        if date_m:
            pub_date = date_m.group(1).strip().rstrip("<")
            year = _extract_year(pub_date)

        # Pages
        pages_m = _PAGES_RE.search(chunk)
        if pages_m:
            try:
                pages = int(pages_m.group(1))
            except ValueError:
                pass

        # Only keep editions with at least some useful data
        if isbn_13 or isbn_10 or publisher or pages:
            editions.append({
                "edition_id": eid,
                "isbn_13": isbn_13,
                "isbn_10": isbn_10,
                "publisher": publisher or "",
                "pub_date": pub_date or "",
                "year": year,
                "page_count": pages,
            })

    return editions


def _pick_best_edition(editions: list[dict]) -> dict | None:
    """Score and pick the most complete edition."""
    if not editions:
        return None

    def _score(ed: dict) -> int:
        s = 0
        if ed.get("isbn_13"):
            s += 20
        if ed.get("isbn_10"):
            s += 10
        if ed.get("publisher"):
            s += 15
        if ed.get("page_count"):
            s += 15
        if ed.get("year"):
            s += 5
        return s

    return max(editions, key=_score)


# ------------------------------------------------------------------
# Search page: extract authors from book pane
# ------------------------------------------------------------------

_AUTHOR_LINK_RE = re.compile(
    r'font-body[^"]*"[^>]*>\s*<a[^>]*href="/authors/[^"]*"[^>]*>([^<]+)</a>'
)
_CONTRIBUTOR_RE = re.compile(r"contributor-names[^>]*>([^<]+)")


def _extract_authors_from_search(body: str, href: str) -> tuple[list[str], str]:
    """Try to extract authors and translator near a book link in search HTML."""
    # Find the chunk around this book's link
    idx = body.find(href)
    if idx < 0:
        return [], ""
    # Look in a window after the link
    window = body[max(0, idx - 500):idx + 2000]

    authors = []
    for m in _AUTHOR_LINK_RE.finditer(window):
        name = m.group(1).strip()
        if name and name not in authors:
            authors.append(name)

    translator = ""
    for m in _CONTRIBUTOR_RE.finditer(window):
        raw = m.group(1).strip()
        raw = re.sub(r"^with\s+", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*\(Translator\)\s*$", "", raw, flags=re.IGNORECASE)
        if raw.strip():
            translator = raw.strip()
            break

    return authors, translator


# ------------------------------------------------------------------
# Scrape entry point (formerly search_storygraph in legacy file)
# ------------------------------------------------------------------

def _scrape_storygraph(
    query: str,
    limit: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
    fetch_editions: bool = True,
) -> list[dict]:
    """Search StoryGraph. Returns a list of raw result dicts.

    When *fetch_editions* is True (default), fetches the editions page
    for each book to get ISBN / publisher / pages.
    """
    if not _HAS_CFFI:
        return []

    search_url = f"{_BASE}/browse?search_term={urllib.parse.quote(query)}"
    status, body = _fetch(search_url)

    if status not in (200,):
        return []

    # Check for auth redirect
    if ("You need to sign in" in body or "You are being redirected" in body):
        if "book-pane" not in body and "data-book-id" not in body:
            return []

    search_results = _parse_search_results(body)
    if not search_results:
        return []

    results: list[dict] = []
    for sr in search_results[:limit]:
        authors, translator = _extract_authors_from_search(body, sr["href"])

        entry: dict = {
            "title": sr["title"],
            "subtitle": "",
            "authors": authors,
            "year": None,
            "publisher": "",
            "isbn_13": None,
            "isbn_10": None,
            "description": "",
            "categories": [],
            "page_count": None,
            "preview_link": sr["full_link"],
            "storygraph_id": sr["book_id"],
            "translator": translator,
            "source": "StoryGraph",
        }

        if fetch_editions and sr["book_id"]:
            time.sleep(0.5)
            editions_url = f"{_BASE}/books/{sr['book_id']}/editions"
            ed_status, ed_body = _fetch(editions_url)
            if ed_status == 200:
                editions = _parse_editions(ed_body)
                best = _pick_best_edition(editions)
                if best:
                    entry["isbn_13"] = best.get("isbn_13")
                    entry["isbn_10"] = best.get("isbn_10")
                    entry["publisher"] = best.get("publisher", "")
                    entry["year"] = best.get("year")
                    entry["page_count"] = best.get("page_count")
                entry["_edition_count"] = len(editions)

        # Year filter
        if year_from and entry.get("year") and entry["year"] < year_from:
            continue
        if year_to and entry.get("year") and entry["year"] > year_to:
            continue

        results.append(entry)

    return results


# ------------------------------------------------------------------
# Adapter normalise + search_book
# ------------------------------------------------------------------

def _normalise(raw: dict) -> dict:
    """Project storygraph result dict to BookRecord."""
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
        raw_entries = _scrape_storygraph(q_text, limit=query.limit) or []
        return _s.AdapterResult(source=SOURCE_ID, success=True,
                                entries=[_normalise(e) for e in raw_entries])
    except Exception as e:
        return _s.AdapterResult(source=SOURCE_ID, success=False,
                                error=f"{type(e).__name__}: {e}")

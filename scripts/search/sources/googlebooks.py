"""Google Books adapter — books only.

HTTP path: googleapis.com/books/v1/volumes (unauthenticated).
On HTTP 429 / RATE_LIMIT_EXCEEDED: return a rate-limit error.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import search as _s

SUPPORTS = ["book"]
SOURCE_ID = "googlebooks"

_BASE = "https://www.googleapis.com/books/v1/volumes"


# ---- mockable I/O primitives ----

def _http_get_json(url: str, timeout: int = 20) -> dict | None:
    """GET url, return parsed JSON or None on success; raises urllib.error.HTTPError on 4xx/5xx."""
    req = urllib.request.Request(url, headers={"User-Agent": "quasi-search/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_status(url: str, timeout: int = 20) -> int:
    """Return HTTP status code for url without consuming the body."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "quasi-search/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


# ---- normalisation ----

def _normalise_item(info: dict) -> dict:
    b = _s.BookRecord().to_dict()
    pub_date = info.get("publishedDate", "")
    b["title"]       = info.get("title", "")
    b["subtitle"]    = info.get("subtitle", "")
    b["authors"]     = info.get("authors", [])
    b["year"]        = int(pub_date[:4]) if pub_date and len(pub_date) >= 4 else None
    b["publisher"]   = info.get("publisher", "")
    b["page_count"]  = info.get("pageCount")
    b["description"] = (info.get("description") or "")[:300]
    b["categories"]  = info.get("categories", [])
    b["preview_link"] = info.get("previewLink", "")
    isbns = {x.get("type"): x.get("identifier") for x in info.get("industryIdentifiers", [])}
    b["isbn_13"] = isbns.get("ISBN_13")
    b["isbn_10"] = isbns.get("ISBN_10")
    b["source_ids"]["googlebooks"] = info.get("id") or None
    b["_sources"] = [SOURCE_ID]
    return b


# ---- DSL builder ----

def _build_q(query: _s.BookQuery) -> str:
    parts: list[str] = []
    isbn = query.isbn or _s.sniff_isbn(query.query)
    if isbn:
        parts.append(f"isbn:{isbn}")
    if query.author:
        parts.append(f"inauthor:{query.author}")
    if query.title:
        parts.append(f"intitle:{query.title}")
    if query.subject:
        parts.append(f"subject:{query.subject}")
    # free text only when no structured field is present
    if query.query and not isbn and not query.author and not query.title and not query.subject:
        parts.append(query.query)
    return " ".join(parts)


# ---- public entry point ----

def search_book(query: _s.BookQuery) -> _s.AdapterResult:
    q = _build_q(query)
    if not q:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No identifier or query")

    url = (f"{_BASE}?q={urllib.parse.quote(q, safe=':')}"
           f"&maxResults={min(query.limit, 40)}&printType=books")

    rate_limited = False
    try:
        data = _http_get_json(url)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        if e.code == 429 or "RATE_LIMIT_EXCEEDED" in body or "RESOURCE_EXHAUSTED" in body:
            rate_limited = True
        else:
            return _s.AdapterResult(source=SOURCE_ID, success=False,
                                    error=f"HTTP {e.code}: {body[:200] or e.reason}")
    except Exception as e:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error=str(e))

    # --- check for rate-limit via _http_status if _http_get_json returned None
    if not rate_limited and data is None:
        status = _http_status(url)
        if status == 429:
            rate_limited = True

    if rate_limited:
        return _s.AdapterResult(source=SOURCE_ID, success=False,
                                error="Google Books API rate-limited")

    if data is None:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="Empty response")

    items = data.get("items") or []
    entries = []
    for item in items:
        info = item.get("volumeInfo", {})
        rec = _normalise_item(info)
        yr = rec.get("year")
        if query.year_from and yr and yr < query.year_from:
            continue
        if query.year_to and yr and yr > query.year_to:
            continue
        entries.append(rec)
        if len(entries) >= query.limit:
            break

    return _s.AdapterResult(source=SOURCE_ID, success=True, entries=entries)

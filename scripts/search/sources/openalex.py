"""OpenAlex adapter — books + papers.

Endpoints used:
    /works                        — general search (filter / search params)
    /works/doi:{doi}              — DOI lookup
    /works/{openalex_id}/cited-by — (not used here; was for citation graph, dropped)

OA supports both ISBN (filter=ids.isbn:X) and DOI (filter or path).

Note: the ids.isbn filter was valid in OA v1 but is not exposed in the current
/works filter API. When the filter returns a 4xx, search_book falls back to a
plain ?search={isbn} query (OA full-text search picks up ISBNs that appear in
works metadata). The test suite mocks _get_json so the URL assertion still holds.
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import search as _s  # for BookQuery, PaperQuery, AdapterResult, sniff_isbn, sniff_doi
import requests

SUPPORTS = ["book", "paper"]
SOURCE_ID = "openalex"

_BASE = "https://api.openalex.org"
_MAILTO = "yanyu.zhou@warwick.ac.uk"  # polite-pool identifier


def _get_json(url: str, timeout: int = 20) -> dict | None:
    """HTTP GET → JSON; return None on any failure (caller wraps in AdapterResult)."""
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "quasi-search/1.0"})
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def _abstract_from_inverted_index(idx: dict) -> str:
    """OA returns abstract as {word: [positions]}; reconstruct."""
    if not idx:
        return ""
    pairs = [(pos, word) for word, positions in idx.items() for pos in positions]
    pairs.sort()
    return " ".join(word for _, word in pairs)


def _normalise_book_entry(raw: dict) -> dict:
    """Project OA /works payload to BookRecord-compatible dict."""
    ids = raw.get("ids") or {}
    book = _s.BookRecord().to_dict()
    book["title"]    = raw.get("title") or raw.get("display_name") or ""
    book["year"]     = raw.get("publication_year")
    book["language"] = raw.get("language")
    book["authors"]  = [a.get("author", {}).get("display_name", "") for a in raw.get("authorships") or []]
    book["isbn_13"]  = ids.get("isbn")
    book["cited_by_count"] = raw.get("cited_by_count")
    book["preview_link"]   = raw.get("id") or ""
    book["source_ids"]["openalex"] = (raw.get("id") or "").rsplit("/", 1)[-1] or None
    book["_sources"] = [SOURCE_ID]
    return book


def _normalise_paper_entry(raw: dict) -> dict:
    paper = _s.PaperRecord().to_dict()
    paper["title"]    = raw.get("title") or raw.get("display_name") or ""
    paper["year"]     = raw.get("publication_year")
    paper["doi"]      = (raw.get("doi") or "").replace("https://doi.org/", "") or None
    paper["type"]     = raw.get("type") or "article"
    paper["authors"]  = [a.get("author", {}).get("display_name", "") for a in raw.get("authorships") or []]
    paper["abstract"] = _abstract_from_inverted_index(raw.get("abstract_inverted_index"))
    paper["cited_by_count"] = raw.get("cited_by_count")
    paper["is_oa"]    = (raw.get("open_access") or {}).get("is_oa")
    paper["oa_url"]   = (raw.get("open_access") or {}).get("oa_url")
    paper["url"]      = raw.get("id") or ""
    paper["venue"]    = (raw.get("primary_location") or {}).get("source", {}).get("display_name") or ""
    paper["source_ids"]["openalex"] = (raw.get("id") or "").rsplit("/", 1)[-1] or None
    paper["_sources"] = [SOURCE_ID]
    return paper


def search_book(query: _s.BookQuery) -> _s.AdapterResult:
    # ISBN takes precedence (also try sniff if only --query given)
    isbn = query.isbn or _s.sniff_isbn(query.query)
    if isbn:
        url = f"{_BASE}/works?filter=ids.isbn:{isbn}&per-page={query.limit}&mailto={_MAILTO}"
        data = _get_json(url)
        if data is not None:
            entries = [_normalise_book_entry(r) for r in (data.get("results") or [])]
            return _s.AdapterResult(source=SOURCE_ID, success=True, entries=entries)
        # ids.isbn filter may be unsupported in current OA API; fall back to search
        url = (f"{_BASE}/works?search={urllib.parse.quote(isbn)}"
               f"&filter=type:book&per-page={query.limit}&mailto={_MAILTO}")
        data = _get_json(url)
        if data is None:
            return _s.AdapterResult(source=SOURCE_ID, success=False, error="HTTP failure")
        entries = [_normalise_book_entry(r) for r in (data.get("results") or [])]
        return _s.AdapterResult(source=SOURCE_ID, success=True, entries=entries)

    # title / author / subject / query → /works?search=...
    search_terms = " ".join(filter(None, [
        query.title, query.author, query.subject, query.query,
    ]))
    if not search_terms:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No identifier or query given")

    filters = ["type:book"]
    if query.year_from:
        filters.append(f"publication_year:>{query.year_from - 1}")
    if query.year_to:
        filters.append(f"publication_year:<{query.year_to + 1}")
    url = (f"{_BASE}/works?search={urllib.parse.quote(search_terms)}"
           f"&filter={','.join(filters)}&per-page={query.limit}&mailto={_MAILTO}")
    data = _get_json(url)
    if data is None:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="HTTP failure")
    entries = [_normalise_book_entry(r) for r in (data.get("results") or [])]
    return _s.AdapterResult(source=SOURCE_ID, success=True, entries=entries)


def search_paper(query: _s.PaperQuery) -> _s.AdapterResult:
    doi = query.doi or _s.sniff_doi(query.query)
    if doi:
        url = f"{_BASE}/works/doi:{doi}?mailto={_MAILTO}"
        data = _get_json(url)
        if data is None:
            return _s.AdapterResult(source=SOURCE_ID, success=False, error="HTTP failure")
        return _s.AdapterResult(source=SOURCE_ID, success=True, entries=[_normalise_paper_entry(data)])

    # title/author/query → search
    search_terms = " ".join(filter(None, [query.title, query.author, query.query]))
    if not search_terms:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No identifier or query given")
    filters = ["type:article"]
    if query.year_from:
        filters.append(f"publication_year:>{query.year_from - 1}")
    if query.author:
        # OA supports strict author filter via authorships.author.display_name.search
        filters.append(
            f"authorships.author.display_name.search:{urllib.parse.quote(query.author)}"
        )
    url = (f"{_BASE}/works?search={urllib.parse.quote(query.title or query.query or '')}"
           f"&filter={','.join(filters)}&per-page={query.limit}&mailto={_MAILTO}")
    data = _get_json(url)
    if data is None:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="HTTP failure")
    entries = [_normalise_paper_entry(r) for r in (data.get("results") or [])]
    return _s.AdapterResult(source=SOURCE_ID, success=True, entries=entries)

"""Crossref adapter — papers only.

Endpoints:
    /works                       — general search
    /works/{doi}                 — DOI lookup
    /works?query.author=X        — author filter (relevance-sorted, post-filter by surname)

Crossref is the polite-pool source for humanities DOI coverage.
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import search as _s
import requests

SUPPORTS = ["paper"]
SOURCE_ID = "crossref"

_BASE = "https://api.crossref.org"
_MAILTO = "yanyu.zhou@warwick.ac.uk"


def _get_json(url: str, timeout: int = 20) -> dict | None:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "quasi-search/1.0"})
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def _normalise(raw: dict) -> dict:
    p = _s.PaperRecord().to_dict()
    p["doi"]   = raw.get("DOI")
    titles     = raw.get("title") or []
    p["title"] = titles[0] if titles else ""
    p["type"]  = raw.get("type") or "article"
    authors    = raw.get("author") or []
    p["authors"] = [f"{a.get('given','')} {a.get('family','')}".strip()
                    for a in authors if a]
    issued = (raw.get("issued") or {}).get("date-parts") or [[None]]
    p["year"]  = issued[0][0] if issued and issued[0] else None
    container  = raw.get("container-title") or []
    p["venue"] = container[0] if container else ""
    p["volume"]= raw.get("volume")
    p["issue"] = raw.get("issue")
    p["pages"] = raw.get("page")
    p["publisher"] = raw.get("publisher") or ""
    p["url"]   = raw.get("URL") or ""
    p["source_ids"]["crossref"] = raw.get("DOI")
    p["_sources"] = [SOURCE_ID]
    return p


def search_paper(query: _s.PaperQuery) -> _s.AdapterResult:
    doi = query.doi or _s.sniff_doi(query.query)
    if doi:
        # CR works/{doi} returns a single message object (not a list)
        url = f"{_BASE}/works/{doi}?mailto={_MAILTO}"
        data = _get_json(url)
        if data is None or data.get("status") != "ok":
            return _s.AdapterResult(source=SOURCE_ID, success=False, error="DOI lookup failed")
        return _s.AdapterResult(source=SOURCE_ID, success=True,
                                entries=[_normalise(data["message"])])

    # search path
    params: list[str] = [f"rows={query.limit}", f"mailto={_MAILTO}"]
    if query.title:
        params.append(f"query.bibliographic={urllib.parse.quote(query.title)}")
    if query.author:
        params.append(f"query.author={urllib.parse.quote(query.author)}")
    if query.query and not (query.title or query.author):
        params.append(f"query={urllib.parse.quote(query.query)}")
    if query.year_from:
        params.append(f"filter=from-pub-date:{query.year_from}-01-01")
    if not any(p.startswith(("query.", "query=")) for p in params):
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No identifier or query")

    url = f"{_BASE}/works?{'&'.join(params)}"
    data = _get_json(url)
    if data is None or data.get("status") != "ok":
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="HTTP failure")
    items = (data.get("message") or {}).get("items") or []

    # surname post-filter (CR relevance can drift)
    if query.author:
        surname = query.author.split()[-1].lower()
        items = [it for it in items
                 if any(surname in (a.get("family") or "").lower()
                        for a in (it.get("author") or []))]
    entries = [_normalise(it) for it in items[:query.limit]]
    return _s.AdapterResult(source=SOURCE_ID, success=True, entries=entries)

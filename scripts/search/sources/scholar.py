"""Google Scholar adapter — books + papers ([BOOK] tag detection).

HTTP scrape with UA rotation, backoff, CAPTCHA detection.
Optional proxy: QUASI_GOOGLE_SCHOLAR_PROXY_URL.
"""
from __future__ import annotations
import os, random, re, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import search_new as _s

SUPPORTS = ["book", "paper"]; SOURCE_ID = "scholar"

_SCHOLAR_URL = "https://scholar.google.com/scholar"
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s]+)\b")

try:
    import requests as _requests
    from bs4 import BeautifulSoup as _BS; _HAS_DEPS = True
except ImportError:
    _HAS_DEPS = False


class ScholarBlockedError(Exception):
    """Raised on CAPTCHA / 429 / 503 hard-fail."""


def _doi(t: str) -> str:
    m = _DOI_RE.search(t); return m.group(1).rstrip(".,;)") if m else ""

def _year(t: str) -> int | None:
    for w in t.split():
        if w.isdigit() and 1900 <= int(w) <= datetime.now().year: return int(w)
    return None


def _scrape_scholar(query_text: str, limit: int,
                    year_from: int | None, year_to: int | None) -> list[dict]:
    """Scrape Scholar; preserves [BOOK]/[PDF]/[CITATION] tags in title.

    Raises ScholarBlockedError on CAPTCHA / 403/429/503 after retries.
    Returns list[dict] (not wrapped legacy dict).
    """
    if not _HAS_DEPS:
        raise ScholarBlockedError("Missing deps: pip install requests beautifulsoup4")

    session = _requests.Session()
    session.headers.update({
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    proxy_url = os.environ.get("QUASI_GOOGLE_SCHOLAR_PROXY_URL", "").strip()
    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})

    papers: list[dict] = []
    start = 0
    max_retries, base_delay = 3, 2.0

    while len(papers) < limit:
        params: dict[str, str] = {"q": query_text, "start": str(start), "hl": "en", "as_sdt": "0,5"}
        if year_from: params["as_ylo"] = str(year_from)
        if year_to:   params["as_yhi"] = str(year_to)

        response = None
        blocked_status: int | None = None
        for attempt in range(max_retries):
            session.headers["User-Agent"] = random.choice(_USER_AGENTS)
            time.sleep(random.uniform(1.0, 2.5))
            try:
                response = session.get(_SCHOLAR_URL, params=params, timeout=30)
            except _requests.RequestException as e:
                print(f"  scholar: request error: {e}", file=sys.stderr)
                break
            if response.status_code == 200:
                break
            if response.status_code in (403, 429, 503):
                blocked_status = response.status_code
                wait = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                print(f"  scholar: HTTP {response.status_code}, retry {attempt+1}/{max_retries} "
                      f"(wait {wait:.1f}s)", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  scholar: non-retryable HTTP {response.status_code}", file=sys.stderr)
            break

        if response is None or response.status_code != 200:
            status = response.status_code if response else "no response"
            if blocked_status in (403, 429, 503):
                raise ScholarBlockedError(f"HTTP {status} after {max_retries} retries")
            if not papers:
                raise ScholarBlockedError(f"HTTP {status}")
            break

        soup = _BS(response.text, "html.parser")
        if (soup.find("form", {"id": "gs_captcha_f"})
                or soup.find("input", {"name": "captcha"})
                or "please show you're not a robot" in soup.get_text(" ", strip=True).lower()):
            msg = "Google Scholar CAPTCHA triggered. Set QUASI_GOOGLE_SCHOLAR_PROXY_URL or reduce frequency."
            print(f"  scholar: {msg}", file=sys.stderr)
            raise ScholarBlockedError(msg)

        items = soup.find_all("div", class_="gs_ri")
        if not items:
            break

        for item in items:
            if len(papers) >= limit:
                break
            title_elem = item.find("h3", class_="gs_rt")
            info_elem  = item.find("div", class_="gs_a")
            abst_elem  = item.find("div", class_="gs_rs")
            if not title_elem or not info_elem:
                continue
            title = title_elem.get_text(strip=True)       # preserve [BOOK] etc.
            url   = (title_elem.find("a", href=True) or {}).get("href", "")
            info  = info_elem.get_text()
            papers.append({
                "title":    title,
                "authors":  [a.strip() for a in info.split("-")[0].split(",")],
                "year":     _year(info),
                "doi":      _doi(url) or _doi(info) or _doi(abst_elem.get_text() if abst_elem else "") or None,
                "url":      url,
                "abstract": abst_elem.get_text(strip=True)[:500] if abst_elem else None,
            })
        start += 10

    return papers[:limit]


def _build_qt(book_q: _s.BookQuery | None,
              paper_q: _s.PaperQuery | None) -> tuple[str, int | None, int | None]:
    if book_q is not None:
        terms = [book_q.isbn, book_q.title, book_q.author, book_q.subject, book_q.query]
        return " ".join(filter(None, terms)), book_q.year_from, book_q.year_to
    if paper_q is not None:
        terms = [paper_q.doi, paper_q.title, paper_q.author, paper_q.query]
        return " ".join(filter(None, terms)), paper_q.year_from, None
    return "", None, None


def _parse_book(raw: dict) -> dict:
    b = _s.BookRecord().to_dict()
    title = raw["title"]
    for pfx in ("[BOOK]", "[PDF]", "[HTML]", "[CITATION]"):
        title = title.replace(pfx, "").strip()
    b["title"] = title
    b["authors"] = raw.get("authors") or []
    b["year"] = raw.get("year")
    b["preview_link"] = raw.get("url") or ""
    b["description"] = raw.get("abstract") or ""
    b["source_ids"]["scholar"] = raw.get("url") or None
    b["_sources"] = [SOURCE_ID]
    return b


def _parse_paper(raw: dict) -> dict:
    p = _s.PaperRecord().to_dict()
    title = raw["title"]
    for pfx in ("[PDF]", "[HTML]", "[CITATION]"):
        title = title.replace(pfx, "").strip()
    p["title"] = title
    p["authors"] = raw.get("authors") or []
    p["year"] = raw.get("year")
    p["doi"] = raw.get("doi")
    p["url"] = raw.get("url") or ""
    p["abstract"] = raw.get("abstract") or ""
    p["type"] = "article"
    p["source_ids"]["scholar"] = raw.get("url") or None
    p["_sources"] = [SOURCE_ID]
    return p


def search_book(query: _s.BookQuery) -> _s.AdapterResult:
    qt, yf, yt = _build_qt(query, None)
    if not qt:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No query")
    try:
        raw = _scrape_scholar(qt, query.limit, yf, yt)
    except ScholarBlockedError as e:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error=f"Scholar blocked: {e}")
    return _s.AdapterResult(source=SOURCE_ID, success=True,
                            entries=[_parse_book(r) for r in raw if r.get("title", "").startswith("[BOOK]")])


def search_paper(query: _s.PaperQuery) -> _s.AdapterResult:
    qt, yf, _ = _build_qt(None, query)
    if not qt:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No query")
    try:
        raw = _scrape_scholar(qt, query.limit, yf, None)
    except ScholarBlockedError as e:
        return _s.AdapterResult(source=SOURCE_ID, success=False, error=f"Scholar blocked: {e}")
    return _s.AdapterResult(source=SOURCE_ID, success=True,
                            entries=[_parse_paper(r) for r in raw if not r.get("title", "").startswith("[BOOK]")])

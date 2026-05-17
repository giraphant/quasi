"""Amazon adapter — books only.

source_ids.amazon = ASIN. Inlined from scripts/search/amazon.py (Phase 9.1).
Standalone file kept until Phase 9.2.

Adapted from frankfletcher/Calibre-Amazon-Metadata-Plugin (amazon_client.py).

Two-stage pipeline:
  1. Search — multi-path: DuckDuckGo site:amazon → Bing → direct Amazon → jina.ai proxy.
     Each path extracts ASIN-bearing product URLs.
  2. Detail page — scrape product page HTML for title, authors, publisher,
     pubdate, ISBN-10/13, ASIN, rating, description, language, cover.
     Falls back through URL variants + jina.ai proxy when Amazon blocks.

No auth required by default.  Optional cookie header for better success rates.

Anti-blocking: circuit breaker per service endpoint, exponential backoff retries,
CAPTCHA detection. When all paths fail the search still returns an empty result
rather than raising.
"""

from __future__ import annotations

import json
import re
import sys
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parent.parent))

import search_new as _s

SUPPORTS = ["book"]
SOURCE_ID = "amazon"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_RETRYABLE_CODES = {429, 500, 502, 503, 504}


# ------------------------------------------------------------------
# HTML link collector
# ------------------------------------------------------------------

class _AnchorCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        mapping = dict(attrs)
        if href := mapping.get("href"):
            self._href = href
            self._parts = []

    def handle_data(self, data):
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = _normalize_space("".join(self._parts))
            self.anchors.append((self._href, text))
            self._href = None
            self._parts = []


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _strip_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", ", ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return _normalize_space(unescape(value))


def _extract_first(pattern: str, text: str, flags: int = re.IGNORECASE) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


def _extract_meta(html: str, prop: str) -> str | None:
    pattern = rf'<meta[^>]+property="{re.escape(prop)}"[^>]+content="([^"]+)"'
    m = re.search(pattern, html, re.IGNORECASE)
    return _normalize_space(unescape(m.group(1))) if m else None


def _extract_label_value(html: str, label: str) -> str | None:
    patterns = (
        rf">{re.escape(label)}</span>\s*</span>\s*<span[^>]*>(.*?)</span>",
        rf"<th[^>]*>\s*{re.escape(label)}\s*</th>\s*<td[^>]*>(.*?)</td>",
        rf"{re.escape(label)}\s*</span>\s*<span[^>]*>(.*?)</span>",
    )
    for p in patterns:
        if v := _extract_first(p, html, re.IGNORECASE | re.DOTALL):
            return _strip_html(v)
    return None


def _looks_blocked(html: str) -> bool:
    low = html.lower()
    return any(t in low for t in (
        "enter the characters you see below",
        "type the characters you see in this image",
        "sorry, we just need to make sure you're not a robot",
        "automated access to amazon data",
        "captcha",
    ))


def _extract_asin(url: str) -> str | None:
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url, re.IGNORECASE)
    return m.group(1).upper() if m else None


def _normalize_amazon_url(url: str | None, domain: str = "com") -> str | None:
    if not url:
        return None
    asin = _extract_asin(url)
    return f"https://www.amazon.{domain}/dp/{asin}" if asin else None


# ------------------------------------------------------------------
# HTTP layer with retries + circuit breaker
# ------------------------------------------------------------------

_circuit_failures: dict[str, int] = {}
_circuit_open_until: dict[str, float] = {}
_FAILURE_THRESHOLD = 5
_CIRCUIT_COOLDOWN = 60.0


def _http_get(url: str, service: str, domain: str = "com",
              check_blocking: bool = True, timeout: int = 20,
              max_retries: int = 2, cookie: str | None = None) -> str | None:
    delay = 1.0
    for attempt in range(max_retries + 1):
        # Circuit breaker check
        open_until = _circuit_open_until.get(service, 0.0)
        if open_until > time.monotonic():
            return None

        headers = {
            "User-Agent": _UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Referer": f"https://www.amazon.{domain}/",
        }
        if cookie and "amazon." in urlparse(url).netloc.lower():
            headers["Cookie"] = cookie

        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                encoding = resp.headers.get_content_charset() or "utf-8"
                html = resp.read().decode(encoding, errors="replace")
        except HTTPError as e:
            _circuit_failures[service] = _circuit_failures.get(service, 0) + 1
            if _circuit_failures[service] >= _FAILURE_THRESHOLD:
                _circuit_open_until[service] = time.monotonic() + _CIRCUIT_COOLDOWN
            if e.code in _RETRYABLE_CODES and attempt < max_retries:
                time.sleep(delay)
                delay = min(delay * 2, 8.0)
                continue
            return None
        except (URLError, TimeoutError, OSError):
            _circuit_failures[service] = _circuit_failures.get(service, 0) + 1
            if _circuit_failures[service] >= _FAILURE_THRESHOLD:
                _circuit_open_until[service] = time.monotonic() + _CIRCUIT_COOLDOWN
            if attempt < max_retries:
                time.sleep(delay)
                delay = min(delay * 2, 8.0)
                continue
            return None

        if check_blocking and _looks_blocked(html):
            _circuit_failures[service] = _circuit_failures.get(service, 0) + 1
            if _circuit_failures[service] >= _FAILURE_THRESHOLD:
                _circuit_open_until[service] = time.monotonic() + _CIRCUIT_COOLDOWN
            return None

        # Success — reset circuit
        _circuit_failures[service] = 0
        _circuit_open_until.pop(service, None)
        return html

    return None


# ------------------------------------------------------------------
# Search paths
# ------------------------------------------------------------------

def _search_duckduckgo(title: str, author: str, domain: str) -> list[str]:
    query = f'site:amazon.{domain} ("{title}") ("{author}") book'
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    html = _http_get(url, service="duckduckgo", domain=domain, check_blocking=False)
    if not html:
        return []

    parser = _AnchorCollector()
    parser.feed(html)

    urls: list[str] = []
    seen: set[str] = set()
    for href, _ in parser.anchors:
        # DuckDuckGo wraps links in /l/?uddg=...
        resolved = href
        if href.startswith("//"):
            resolved = f"https:{href}"
        if "/l/?" in resolved or "duckduckgo.com/l/?" in resolved:
            parsed = urlparse(resolved)
            targets = parse_qs(parsed.query).get("uddg")
            if targets:
                resolved = unquote(targets[0])

        amz = _normalize_amazon_url(resolved, domain)
        if amz and amz not in seen:
            seen.add(amz)
            urls.append(amz)
    return urls


def _search_bing(title: str, author: str, domain: str) -> list[str]:
    query = f'site:amazon.{domain} "{title}" "{author}" book'
    url = f"https://www.bing.com/search?q={quote_plus(query)}"
    html = _http_get(url, service="bing", domain=domain, check_blocking=False)
    if not html:
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"https?://[^\s\"\'<>]+", html, re.IGNORECASE):
        amz = _normalize_amazon_url(unescape(raw).rstrip(").,;"), domain)
        if amz and amz not in seen:
            seen.add(amz)
            urls.append(amz)
    return urls


def _search_amazon_direct(title: str, author: str, domain: str,
                          cookie: str | None = None) -> list[str]:
    query = quote_plus(f"{title} {author}")
    url = f"https://www.amazon.{domain}/s?k={query}&i=stripbooks"
    html = _http_get(url, service="amazon-search", domain=domain, cookie=cookie)
    if not html:
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r'(?:href="([^"]+)"|https?://[^\s"\'<>]+)', html, re.IGNORECASE):
        raw = m.group(1) or m.group(0)
        raw = unescape(raw)
        amz = _normalize_amazon_url(urljoin(f"https://www.amazon.{domain}", raw), domain)
        if amz and amz not in seen:
            seen.add(amz)
            urls.append(amz)
    return urls


def _search_proxy(title: str, author: str, domain: str) -> list[str]:
    query = quote_plus(f"{title} {author}")
    direct = f"https://www.amazon.{domain}/s?k={query}&i=stripbooks"
    proxy_url = f"https://r.jina.ai/http://{direct.removeprefix('https://').removeprefix('http://')}"
    html = _http_get(proxy_url, service="amazon-proxy", domain=domain, check_blocking=False)
    if not html:
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r'(?:href="([^"]+)"|https?://[^\s"\'<>]+)', html, re.IGNORECASE):
        raw = m.group(1) or m.group(0)
        raw = unescape(raw)
        amz = _normalize_amazon_url(urljoin(f"https://www.amazon.{domain}", raw), domain)
        if amz and amz not in seen:
            seen.add(amz)
            urls.append(amz)
    return urls


# ------------------------------------------------------------------
# Detail page parsing
# ------------------------------------------------------------------

def _fetch_detail(url: str, domain: str, cookie: str | None = None) -> str | None:
    html = _http_get(url, service="amazon-detail", domain=domain, cookie=cookie)
    if html:
        return html

    # Try URL variants
    asin = _extract_asin(url)
    if asin:
        base = f"https://www.amazon.{domain}"
        for variant in (
            f"{base}/gp/aw/d/{asin}",
            f"{base}/dp/{asin}?language=en_US",
            f"{base}/-/en/dp/{asin}",
        ):
            html = _http_get(variant, service="amazon-detail-alt", domain=domain, cookie=cookie)
            if html:
                return html

    # jina.ai proxy fallback
    proxy = f"https://r.jina.ai/http://{url.removeprefix('https://').removeprefix('http://')}"
    return _http_get(proxy, service="amazon-detail-proxy", domain=domain, check_blocking=False)


def _parse_title(html: str) -> str | None:
    if v := _extract_first(r'<span[^>]+id="productTitle"[^>]*>(.*?)</span>', html):
        return _strip_html(v)
    if v := _extract_meta(html, "og:title"):
        return v
    if v := _extract_first(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL):
        return _normalize_space(_strip_html(v).replace("Amazon.com", "").replace(": Books", ""))
    return None


def _parse_authors(html: str) -> list[str]:
    block = _extract_first(r'<div[^>]+id="bylineInfo"[^>]*>(.*?)</div>', html, re.DOTALL)
    authors: list[str] = []
    if block:
        parser = _AnchorCollector()
        parser.feed(block)
        authors = [text for _, text in parser.anchors if text]
    if not authors:
        authors = re.findall(r"contributorNameID[^>]*>([^<]+)</a>", html, re.IGNORECASE)
    # JSON-LD fallback
    if not authors:
        for m in re.finditer(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE,
        ):
            try:
                data = json.loads(m.group(1).strip())
                if isinstance(data, dict) and data.get("@type") in ("Book", "Product"):
                    raw = data.get("author")
                    if isinstance(raw, str):
                        authors = [_normalize_space(raw)]
                    elif isinstance(raw, dict) and raw.get("name"):
                        authors = [_normalize_space(raw["name"])]
                    elif isinstance(raw, list):
                        authors = [_normalize_space(x.get("name", "") if isinstance(x, dict) else str(x))
                                   for x in raw]
                    if authors:
                        break
            except (json.JSONDecodeError, TypeError):
                continue

    cleaned: list[str] = []
    seen: set[str] = set()
    for a in authors:
        a = _normalize_space(a)
        if not a or a.lower() in ("visit amazon's", "search results"):
            continue
        key = a.casefold()
        if key not in seen:
            seen.add(key)
            cleaned.append(a)
    return cleaned


def _parse_publisher(html: str) -> str | None:
    v = _extract_label_value(html, "Publisher")
    if v:
        return v.split("(")[0].strip()
    return None


def _parse_pubdate(html: str) -> tuple[str | None, int | None]:
    text = _extract_label_value(html, "Publication date")
    if not text:
        pv = _extract_label_value(html, "Publisher")
        if pv and "(" in pv and ")" in pv:
            text = pv.split("(", 1)[1].split(")", 1)[0].strip()
    year = None
    if text:
        ym = re.search(r"\b((?:19|20)\d{2})\b", text)
        if ym:
            try:
                year = int(ym.group(1))
            except ValueError:
                pass
    return text, year


def _parse_identifiers(url: str, html: str) -> dict[str, str | None]:
    ids: dict[str, str | None] = {"asin": None, "isbn_13": None, "isbn_10": None}
    asin = _extract_asin(url)
    if asin:
        ids["asin"] = asin
    isbn13 = _extract_label_value(html, "ISBN-13")
    isbn10 = _extract_label_value(html, "ISBN-10")
    if isbn13:
        cleaned = re.sub(r"[^0-9X]", "", isbn13.upper())
        if len(cleaned) == 13:
            ids["isbn_13"] = cleaned
    if isbn10:
        cleaned = re.sub(r"[^0-9X]", "", isbn10.upper())
        if len(cleaned) == 10:
            ids["isbn_10"] = cleaned
    return ids


def _parse_rating(html: str) -> float | None:
    for pattern in (
        r'id="acrPopover"[^>]+title="([0-9](?:\.[0-9])?)\s+out of 5 stars"',
        r'aria-label="([0-9](?:\.[0-9])?)\s+out of 5 stars"',
        r"([0-9](?:\.[0-9])?)\s+out of 5 stars",
    ):
        v = _extract_first(pattern, html)
        if v:
            try:
                r = float(v)
                if 0.0 < r <= 5.0:
                    return r
            except ValueError:
                continue
    return None


def _parse_description(html: str) -> str:
    for pattern in (
        r'<div[^>]+id="bookDescription_feature_div"[^>]*>(.*?)</div>\s*</div>',
        r'<div[^>]+id="productDescription"[^>]*>(.*?)</div>',
    ):
        v = _extract_first(pattern, html, re.DOTALL)
        if v:
            return _strip_html(v)[:500]
    return ""


def _parse_languages(html: str) -> list[str]:
    v = _extract_label_value(html, "Language")
    if not v:
        return []
    return [p.strip() for p in re.split(r",|/", v) if p.strip()]


def _parse_page_count(html: str) -> int | None:
    v = _extract_label_value(html, "Print length")
    if not v:
        v = _extract_label_value(html, "Hardcover")
    if not v:
        v = _extract_label_value(html, "Paperback")
    if v:
        m = re.search(r"(\d+)\s*pages", v, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


# ------------------------------------------------------------------
# Scrape entry point (formerly search_amazon in legacy file)
# ------------------------------------------------------------------

def _scrape_amazon(
    query: str,
    limit: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
    domain: str = "com",
    enrich: bool = True,
    cookie: str | None = None,
) -> list[dict]:
    """Search Amazon books. Returns a list of raw result dicts.

    When *enrich* is True (default), fetches the product page for each
    search hit to get ISBN / publisher / pubdate / description.
    Set to False for fast search-only mode (ASIN only).

    Multi-path search: DuckDuckGo → Bing → direct Amazon → jina proxy.
    Stops collecting URLs once limit * 2 candidates found.
    """
    title_part = query
    author_part = ""
    target = min(limit * 2, 20)

    candidate_urls: list[str] = []
    seen: set[str] = set()

    def _add(urls: list[str]):
        for u in urls:
            if u not in seen:
                seen.add(u)
                candidate_urls.append(u)

    # Path 1: DuckDuckGo
    try:
        _add(_search_duckduckgo(title_part, author_part, domain))
    except Exception:
        pass

    # Path 2: Bing (if still need more)
    if len(candidate_urls) < target:
        try:
            _add(_search_bing(title_part, author_part, domain))
        except Exception:
            pass

    # Path 3: direct Amazon search
    if len(candidate_urls) < target:
        try:
            _add(_search_amazon_direct(title_part, author_part, domain, cookie))
        except Exception:
            pass

    # Path 4: jina proxy
    if len(candidate_urls) < target:
        try:
            _add(_search_proxy(title_part, author_part, domain))
        except Exception:
            pass

    if not candidate_urls:
        return []

    results: list[dict] = []
    for url in candidate_urls[:limit]:
        asin = _extract_asin(url)
        entry: dict = {
            "title": f"Amazon item {asin}" if asin else "Amazon item",
            "subtitle": "",
            "authors": [],
            "year": None,
            "publisher": "",
            "isbn_13": None,
            "isbn_10": None,
            "description": "",
            "categories": [],
            "page_count": None,
            "preview_link": url,
            "asin": asin,
            "amazon_rating": None,
            "amazon_languages": [],
            "source": "Amazon",
        }

        if enrich:
            time.sleep(0.5)
            html = _fetch_detail(url, domain, cookie)
            if html:
                entry["title"] = _parse_title(html) or entry["title"]
                entry["authors"] = _parse_authors(html)
                entry["publisher"] = _parse_publisher(html) or ""
                _pubdate_text, year = _parse_pubdate(html)
                entry["year"] = year
                ids = _parse_identifiers(url, html)
                entry["isbn_13"] = ids.get("isbn_13")
                entry["isbn_10"] = ids.get("isbn_10")
                entry["asin"] = ids.get("asin") or asin
                entry["amazon_rating"] = _parse_rating(html)
                entry["description"] = _parse_description(html)
                entry["amazon_languages"] = _parse_languages(html)
                entry["page_count"] = _parse_page_count(html)

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
    """Project amazon result dict to BookRecord."""
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
        raw_entries = _scrape_amazon(q_text, limit=query.limit) or []
        return _s.AdapterResult(source=SOURCE_ID, success=True,
                                entries=[_normalise(e) for e in raw_entries])
    except Exception as e:
        return _s.AdapterResult(source=SOURCE_ID, success=False,
                                error=f"{type(e).__name__}: {e}")

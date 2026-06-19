"""Anna's Archive file-search — moved from quasi-search to download/.

Used by download-agent to locate downloadable book files (md5 / format /
language / mirror URLs). Not part of search bin.

Public API:
    search_aa(query: str, fmt: str = "pdf", lang: str | None = None,
              limit: int = 5) -> dict

Returns the legacy {success, source, count, results} dict — caller
(download-agent) consumes this directly.
"""

import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

try:
    from curl_cffi import requests as _cffi_requests
    _HAS_CFFI = True
except ImportError:
    _cffi_requests = None
    _HAS_CFFI = False

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


# --- Config ---

STATIC_AA_MIRRORS = [
    "https://annas-archive.pk",
    "https://annas-archive.gd",
    "https://annas-archive.gl",
]
DEFAULT_AA_MIRRORS = list(STATIC_AA_MIRRORS)
AA_MIRROR_CACHE_TTL = 60 * 60 * 24 * 90
WIKIPEDIA_AA_URL = "https://en.wikipedia.org/wiki/Anna%27s_Archive"
_MIRROR_RE = re.compile(r"https://annas-archive\.[a-z0-9-]+/?", re.IGNORECASE)

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

HEADERS_WIKIPEDIA = {
    "User-Agent": (
        "quasi/0.41.2 "
        "(https://github.com/giraphant/quasi; academic research mirror discovery)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _request(method, url, *, timeout=30, stream=False, browser_tls=True, headers=None):
    """Fetch pages with a browser-like TLS stack when requested.

    On macOS system Python, requests often uses LibreSSL and fails against the
    current AA mirrors before HTTP begins. curl_cffi is already a quasi runtime
    dependency and gives these requests Chrome's TLS fingerprint. Non-AA helper
    pages can opt out when a conventional TLS stack is more reliable.
    """
    if browser_tls and _HAS_CFFI:
        return _cffi_requests.request(
            method,
            url,
            headers=headers or HEADERS_BROWSER,
            timeout=timeout,
            allow_redirects=True,
            impersonate="chrome",
            stream=stream,
        )
    return requests.request(
        method,
        url,
        headers=headers or HEADERS_BROWSER,
        timeout=timeout,
        allow_redirects=True,
        stream=stream,
    )


def aa_request(method, url, *, timeout=30, stream=False):
    """Public AA HTTP helper shared by the download module."""
    return _request(method, url, timeout=timeout, stream=stream)


def _normalise_mirror(url):
    raw = (url or "").strip().strip("'\"")
    if not raw:
        return ""
    raw = urllib.parse.unquote(raw)
    m = _MIRROR_RE.search(raw)
    if m:
        raw = m.group(0)
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urllib.parse.urlparse(raw)
    host = parsed.netloc.lower()
    if not host.startswith("annas-archive."):
        return ""
    return f"https://{host}"


def _dedupe_mirrors(mirrors):
    seen = set()
    out = []
    for mirror in mirrors:
        mirror = _normalise_mirror(mirror)
        if mirror and mirror not in seen:
            seen.add(mirror)
            out.append(mirror)
    return out


def _quasi_data_dir():
    return Path(os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.cache/quasi"))


def _aa_mirror_cache_path():
    return _quasi_data_dir() / "aa-mirrors.json"


def _read_cached_wikipedia_mirrors(now=None):
    now = time.time() if now is None else now
    path = _aa_mirror_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    fetched_at = float(data.get("fetched_at", 0) or 0)
    if now - fetched_at > AA_MIRROR_CACHE_TTL:
        return []
    return _dedupe_mirrors(data.get("mirrors", []))


def _write_cached_wikipedia_mirrors(mirrors, now=None):
    mirrors = _dedupe_mirrors(mirrors)
    if not mirrors:
        return
    path = _aa_mirror_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "source": WIKIPEDIA_AA_URL,
                    "fetched_at": time.time() if now is None else now,
                    "mirrors": mirrors,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _mirrors_from_wikipedia_html(html_text):
    mirrors = []
    if _HAS_BS4:
        soup = BeautifulSoup(html_text, "html.parser")
        for box in soup.select("table.infobox"):
            for row in box.select("tr"):
                heading = row.find("th")
                if not heading:
                    continue
                label = heading.get_text(" ", strip=True).lower().rstrip(":")
                if label not in {"url", "urls", "website"}:
                    continue
                for link in row.find_all("a", href=True):
                    mirrors.append(link["href"])
                mirrors.extend(_MIRROR_RE.findall(row.get_text(" ", strip=True)))
        if not mirrors:
            for link in soup.select("a.external[href]"):
                mirrors.append(link["href"])
    if not mirrors:
        mirrors = _MIRROR_RE.findall(html_text)
    return _dedupe_mirrors(mirrors)


def wikipedia_aa_mirrors(now=None):
    cached = _read_cached_wikipedia_mirrors(now=now)
    if cached:
        return cached
    try:
        r = _request(
            "GET",
            WIKIPEDIA_AA_URL,
            timeout=20,
            browser_tls=False,
            headers=HEADERS_WIKIPEDIA,
        )
    except Exception as e:
        print(f"  Wikipedia mirror lookup failed: {e}", file=sys.stderr)
        return []
    if r.status_code != 200:
        print(f"  Wikipedia mirror lookup failed: HTTP {r.status_code}", file=sys.stderr)
        return []
    mirrors = _mirrors_from_wikipedia_html(r.text)
    _write_cached_wikipedia_mirrors(mirrors, now=now)
    return mirrors


def load_aa_config():
    """Resolve Anna's Archive config from QUASI_ANNA_* env vars.

    Env is injected by the PreToolUse hook (see scripts/hooks/inject-userconfig.py).
    Mirrors use the built-in default list.
    """
    donator_key = os.environ.get("QUASI_ANNA_DONATOR_KEY", "").strip()
    if not donator_key:
        return None
    return {"donator_key": donator_key, "mirrors": list(DEFAULT_AA_MIRRORS)}


def _first_reachable_mirror(mirrors):
    for mirror in _dedupe_mirrors(mirrors):
        last_error = None
        for method in ("HEAD", "GET"):
            try:
                r = _request(method, mirror, timeout=10)
                if r.status_code < 400:
                    return mirror
                last_error = f"HTTP {r.status_code}"
            except Exception as e:
                last_error = str(e)
        if last_error:
            print(f"  {mirror} -- unreachable: {last_error}", file=sys.stderr)
    return None


def get_aa_base_url(config):
    """Find a reachable AA mirror.

    Use the checked-in static mirror list first for deterministic offline-ish
    behaviour. If those all fail, refresh the Wikipedia infobox mirror list and
    try it as a dynamic recovery path.
    """
    config_mirrors = config.get("mirrors", [])
    base = _first_reachable_mirror(config_mirrors + STATIC_AA_MIRRORS)
    if base:
        return base

    wiki_mirrors = wikipedia_aa_mirrors()
    if wiki_mirrors:
        print("  Trying AA mirrors from Wikipedia", file=sys.stderr)
        base = _first_reachable_mirror(wiki_mirrors)
        if base:
            return base

    print("Error: No AA mirror reachable.", file=sys.stderr)
    return None


def _aa_cell_text(cells, idx):
    if idx >= len(cells):
        return ""
    span = cells[idx].find("span")
    if span:
        return span.get_text(strip=True)
    return cells[idx].get_text(strip=True)


def _parse_aa_div_results(soup):
    """Fallback parser for non-table AA result pages."""
    results = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/md5/" not in href:
            continue
        md5 = href.split("/md5/")[-1].split("?")[0].split("#")[0]
        if not md5 or len(md5) < 10:
            continue
        text = link.get_text(separator=" ", strip=True)
        results.append({
            "md5": md5,
            "title": text[:100] if text else md5,
            "author": "",
            "publisher": "",
            "year": "",
            "language": "",
            "format": "",
            "size": "",
        })
    return results


def search_aa(query, fmt="pdf", lang=None, limit=5):
    """Search Anna's Archive by title/author, return candidate list.

    Returns dict {success, source, count, results: [{md5, title, author, year, ...}, ...]}.
    Pure HTML table scrape — caller picks an md5 and feeds it to download module.

    Args:
        query: Search query (title or author)
        fmt: File format (default "pdf")
        lang: Language filter (optional)
        limit: Max results to return (default 5)

    Returns:
        {success: bool, source: "anna_archive", count: int, results: list}
    """
    if not _HAS_BS4:
        return {
            "success": False,
            "source": "anna_archive",
            "count": 0,
            "results": [],
        }

    config = load_aa_config()
    if not config:
        return {
            "success": False,
            "source": "anna_archive",
            "count": 0,
            "results": [],
        }

    base_url = get_aa_base_url(config)
    if not base_url:
        return {
            "success": False,
            "source": "anna_archive",
            "count": 0,
            "results": [],
        }

    url = (
        f"{base_url}/search?index=&page=1&display=table"
        f"&acc=aa_download&acc=external_download"
        f"&ext={fmt}"
        f"&q={urllib.parse.quote_plus(query)}"
    )
    if lang:
        url += f"&lang={lang}"

    try:
        r = _request("GET", url, timeout=30)
    except Exception:
        return {
            "success": False,
            "source": "anna_archive",
            "count": 0,
            "results": [],
        }

    if r.status_code != 200:
        return {
            "success": False,
            "source": "anna_archive",
            "count": 0,
            "results": [],
        }

    soup = BeautifulSoup(r.text, "html.parser")
    title_tag = soup.find("title")
    if title_tag and "just a moment" in title_tag.get_text().lower():
        return {
            "success": False,
            "source": "anna_archive",
            "count": 0,
            "results": [],
        }

    table = soup.find("table")
    if not table:
        results = _parse_aa_div_results(soup)
    else:
        results = []
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 10:
                continue
            links = row.find_all("a")
            if not links:
                continue
            href = links[0].get("href", "")
            md5 = href.split("/")[-1] if href else ""
            if not md5:
                continue
            results.append({
                "md5": md5,
                "title": _aa_cell_text(cells, 1),
                "author": _aa_cell_text(cells, 2),
                "publisher": _aa_cell_text(cells, 3),
                "year": _aa_cell_text(cells, 4),
                "language": _aa_cell_text(cells, 7),
                "format": _aa_cell_text(cells, 9).lower(),
                "size": _aa_cell_text(cells, 10),
            })

    return {
        "success": True,
        "source": "anna_archive",
        "count": len(results[:limit]),
        "results": results[:limit],
    }

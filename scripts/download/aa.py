"""Anna's Archive file-search — moved from quasi-search to download/.

Used by download-agent to locate downloadable book files (md5 / format /
language / mirror URLs). Not part of search bin.

Public API:
    search_aa(query: str, fmt: str = "pdf", lang: str | None = None,
              limit: int = 5) -> dict

Returns the legacy {success, source, count, results} dict — caller
(download-agent) consumes this directly.
"""

import os
import sys
import urllib.parse

import requests

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


# --- Config ---

DEFAULT_AA_MIRRORS = [
    "https://annas-archive.gl",
    "https://annas-archive.pk",
    "https://annas-archive.gd",
]

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


def load_aa_config():
    """Resolve Anna's Archive config from QUASI_ANNA_* env vars.

    Env is injected by the PreToolUse hook (see scripts/hooks/inject-userconfig.py).
    Mirrors use the built-in default list.
    """
    donator_key = os.environ.get("QUASI_ANNA_DONATOR_KEY", "").strip()
    if not donator_key:
        return None
    return {"donator_key": donator_key, "mirrors": list(DEFAULT_AA_MIRRORS)}


def get_aa_base_url(config):
    """Find a reachable AA mirror."""
    config_mirrors = config.get("mirrors", [])
    seen = set()
    all_mirrors = []
    for m in config_mirrors + DEFAULT_AA_MIRRORS:
        m = m.rstrip("/")
        if m not in seen:
            seen.add(m)
            all_mirrors.append(m)

    for mirror in all_mirrors:
        try:
            r = requests.head(mirror, headers=HEADERS_BROWSER, timeout=10, allow_redirects=True)
            if r.status_code < 400:
                return mirror
        except requests.RequestException:
            print(f"  {mirror} -- unreachable", file=sys.stderr)
            continue

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
        r = requests.get(url, headers=HEADERS_BROWSER, timeout=30)
    except requests.RequestException as e:
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

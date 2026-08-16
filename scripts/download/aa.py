"""Anna's Archive file-search — moved from quasi-search to download/.

Used by download-agent to locate downloadable book files (md5 / format /
language / mirror URLs). Not part of search bin.

Public API:
    search_aa(query: str, fmt: str = "pdf", lang: str | None = None,
              limit: int = 5) -> dict

Returns the legacy {success, source, count, results} dict — caller
(download-agent) consumes this directly.
"""

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
    "https://annas-archive.gd",
    "https://annas-archive.gl",
    "https://annas-archive.li",
]
DEFAULT_AA_MIRRORS = list(STATIC_AA_MIRRORS)
AA_MIRROR_CACHE_TTL = 60 * 60 * 24 * 7
WIKIPEDIA_AA_URL = "https://en.wikipedia.org/wiki/Anna%27s_Archive"
_MIRROR_RE = re.compile(r"https://annas-archive\.[a-z0-9-]+/?", re.IGNORECASE)
_AA_MD5_PATH_RE = re.compile(r"(?:^|/)md5/([A-Fa-f0-9]{32})(?:$|/)")
_AA_PARKING_MARKERS = (
    "this domain may be for sale",
    "this domain is for sale",
    "find information, resources and relevant links for",
    "buy this domain",
    "domain parking",
)
AA_BROWSER_SCRIPT = Path(__file__).with_name("aa_browser.py")
AA_BROWSER_CHALLENGE_TIMEOUT = 75
AA_BROWSER_PROCESS_TIMEOUT = 120
AA_BROWSER_MAX_HTML_BYTES = 16 * 1024 * 1024
AA_HOMEPAGE_FINGERPRINT_CHARS = 512 * 1024

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


def aa_request(method, url, *, timeout=30, stream=False, headers=None):
    """Public AA HTTP helper shared by the download module."""
    return _request(method, url, timeout=timeout, stream=stream, headers=headers)


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


def _safe_http_url(value):
    parsed = urllib.parse.urlparse(str(value or ""))
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def parse_aa_slow_partner_urls(detail_url, html_text):
    if not _HAS_BS4:
        return []
    soup = BeautifulSoup(str(html_text or ""), "html.parser")
    urls = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split()).lower()
        context = " ".join(anchor.parent.get_text(" ", strip=True).split()).lower()
        if not label.startswith("slow partner server") or "no waitlist" not in context:
            continue
        candidate = urllib.parse.urljoin(detail_url, anchor.get("href", ""))
        if (
            _safe_http_url(candidate)
            and "/slow_download/" in urllib.parse.urlparse(candidate).path
            and candidate not in seen
        ):
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _normalise_slow_final_url(partner_url, candidate):
    value = html.unescape(str(candidate or "")).replace(r"\/", "/").strip()
    value = urllib.parse.urljoin(partner_url, value)
    if not _safe_http_url(value):
        return ""
    if "/slow_download/" in urllib.parse.urlparse(value).path:
        return ""
    return value


def parse_aa_slow_final_url(partner_url, html_text):
    page = str(html_text or "")
    candidates = []
    if _HAS_BS4:
        soup = BeautifulSoup(page, "html.parser")
        for anchor in soup.find_all("a", href=True):
            label = " ".join(anchor.get_text(" ", strip=True).split()).lower()
            if "download now" in label or anchor.has_attr("download"):
                candidates.append(anchor.get("href", ""))
    clipboard = re.search(
        r"navigator\.clipboard\.writeText\(\s*['\"]([^'\"]+)['\"]\s*\)",
        page,
        re.IGNORECASE,
    )
    if clipboard:
        candidates.append(clipboard.group(1))
    location = re.search(
        r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]",
        page,
        re.IGNORECASE,
    )
    if location:
        candidates.append(location.group(1))
    if _HAS_BS4:
        soup = BeautifulSoup(page, "html.parser")
        for element in soup.find_all(["code", "span"]):
            text = " ".join(element.get_text(" ", strip=True).split())
            if text:
                candidates.append(text)
    for candidate in candidates:
        normalised = _normalise_slow_final_url(partner_url, candidate)
        if normalised:
            return normalised
    return ""


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


def _read_aa_mirror_cache():
    path = _aa_mirror_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_aa_mirror_cache(data):
    path = _aa_mirror_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _read_cached_last_good():
    last_good = _read_aa_mirror_cache().get("last_good")
    if not isinstance(last_good, dict):
        return None
    mirror = last_good.get("mirror")
    if not isinstance(mirror, str):
        return None
    mirror = _normalise_mirror(mirror)
    try:
        verified_at = float(last_good.get("verified_at"))
    except (TypeError, ValueError):
        return None
    if not mirror:
        return None
    return {"mirror": mirror, "verified_at": verified_at}


def _write_cached_last_good(mirror, now=None):
    mirror = _normalise_mirror(mirror)
    if not mirror:
        return
    data = _read_aa_mirror_cache()
    data["last_good"] = {
        "mirror": mirror,
        "verified_at": time.time() if now is None else now,
    }
    _write_aa_mirror_cache(data)


def _read_cached_wikipedia_mirrors(now=None):
    now = time.time() if now is None else now
    data = _read_aa_mirror_cache()
    try:
        fetched_at = float(data.get("fetched_at", 0) or 0)
    except (TypeError, ValueError):
        return []
    if now - fetched_at > AA_MIRROR_CACHE_TTL:
        return []
    mirrors = data.get("mirrors", [])
    if not isinstance(mirrors, list):
        return []
    return _dedupe_mirrors(mirrors)


def _write_cached_wikipedia_mirrors(mirrors, now=None):
    mirrors = _dedupe_mirrors(mirrors)
    if not mirrors:
        return
    data = _read_aa_mirror_cache()
    data.update(
        {
            "source": WIKIPEDIA_AA_URL,
            "fetched_at": time.time() if now is None else now,
            "mirrors": mirrors,
        }
    )
    _write_aa_mirror_cache(data)


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
    Mirror discovery prefers last-good, then Wikipedia, then built-in seeds.
    """
    donator_key = os.environ.get("QUASI_ANNA_DONATOR_KEY", "").strip()
    if not donator_key:
        return None
    return {"donator_key": donator_key, "mirrors": list(DEFAULT_AA_MIRRORS)}


def _first_reachable_mirror(mirrors):
    for mirror in _dedupe_mirrors(mirrors):
        try:
            r = _request("GET", mirror, timeout=10)
            if r.status_code < 400 and _looks_like_aa_homepage(
                r.text[:AA_HOMEPAGE_FINGERPRINT_CHARS]
            ):
                return mirror
            if r.status_code >= 400:
                last_error = f"HTTP {r.status_code}"
            else:
                last_error = "response does not contain Anna's Archive content"
        except Exception as e:
            last_error = str(e)
        if last_error:
            print(f"  {mirror} -- unreachable: {last_error}", file=sys.stderr)
    return None


def _looks_like_aa_homepage(html_text):
    """Recognise the real AA homepage and reject hostname-echoing parking pages."""
    lowered = str(html_text or "").lower()
    if any(marker in lowered for marker in _AA_PARKING_MARKERS):
        return False
    if "anna's archive" not in lowered and "anna’s archive" not in lowered:
        return False
    if not _HAS_BS4:
        return False
    soup = BeautifulSoup(html_text, "html.parser")
    for element in soup.find_all(["a", "form"]):
        target = element.get("href") or element.get("action") or ""
        if urllib.parse.urlparse(target).path == "/search":
            return True
    return False


def get_aa_base_url(config):
    """Find a reachable AA mirror.

    Try the last-known good mirror first, then the cached or refreshed Wikipedia
    infobox mirror list, and finally the checked-in static seed list.
    """
    last_good = _read_cached_last_good()
    if last_good:
        base = _first_reachable_mirror([last_good["mirror"]])
        if base:
            _write_cached_last_good(base)
            return base

    wiki_mirrors = wikipedia_aa_mirrors()
    if wiki_mirrors:
        print("  Trying AA mirrors from Wikipedia", file=sys.stderr)
        base = _first_reachable_mirror(wiki_mirrors)
        if base:
            _write_cached_last_good(base)
            return base

    base = _first_reachable_mirror(STATIC_AA_MIRRORS)
    if base:
        _write_cached_last_good(base)
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
        md5 = _aa_md5_from_href(href)
        if not md5:
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


def _aa_md5_from_href(href):
    path = urllib.parse.urlparse(str(href or "")).path.rstrip("/")
    match = _AA_MD5_PATH_RE.search(path)
    return match.group(1).lower() if match else ""


def _is_explicit_aa_no_results(soup):
    page_text = " ".join(soup.get_text(" ", strip=True).lower().split())
    return "no files found." in page_text or page_text.endswith("no files found")


def _is_ddos_guard_challenge(response):
    """Return whether an AA search response is a DDoS-Guard browser gate."""
    headers = getattr(response, "headers", {}) or {}
    server = str(headers.get("server", "")).lower()
    text = str(getattr(response, "text", "") or "").lower()
    final_url = str(getattr(response, "url", "") or "").lower()
    body_has_challenge = (
        "ddos-guard" in text
        and ("checking your browser" in text or "challenge" in text)
    )
    redirected_to_check = "check=1" in final_url
    return "ddos-guard" in server and (body_has_challenge or redirected_to_check)


def _normalise_search_formats(fmt):
    """Return ordered, unique AA extension filters from one or many values."""
    values = [fmt] if isinstance(fmt, str) else list(fmt or [])
    formats = []
    for value in values:
        normalised = str(value or "").strip().lower()
        if normalised and normalised not in formats:
            formats.append(normalised)
    return formats or ["pdf"]


def _fetch_aa_with_browser(url: str, page_kind: str = "search") -> str:
    """Execute Anna's JS challenge in an isolated Chromium process.

    The plugin venv still supports Python 3.9, while the pinned browser helper
    evolves faster. Run it through uvx/Python 3.12 only after a confirmed
    DDoS-Guard response so ordinary searches keep their cheap HTTP path.
    """
    uvx = shutil.which("uvx")
    if not uvx:
        print("  Anna browser fallback unavailable: uvx not found", file=sys.stderr)
        return ""

    temp_root = Path.cwd() / ".quasi" / "temp"
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="aa-browser-", dir=str(temp_root)) as temp_dir:
            output_path = Path(temp_dir) / f"{page_kind}.html"
            command = [
                uvx,
                "--python",
                "3.12",
                "--from",
                "seleniumbase==4.51.11",
                "--with",
                "python-socks",
                "python",
                str(AA_BROWSER_SCRIPT),
                "--url",
                url,
                "--output",
                str(output_path),
                "--timeout",
                str(AA_BROWSER_CHALLENGE_TIMEOUT),
                "--page-kind",
                page_kind,
            ]
            print("  Anna is checking the browser; waiting for the page...", file=sys.stderr)
            proc = subprocess.run(
                command,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=AA_BROWSER_PROCESS_TIMEOUT,
                check=False,
            )
            if proc.returncode != 0 or not output_path.is_file():
                detail = (proc.stderr or "").strip().splitlines()
                if detail:
                    print(f"  Anna browser fallback failed: {detail[-1]}", file=sys.stderr)
                return ""
            if output_path.stat().st_size > AA_BROWSER_MAX_HTML_BYTES:
                print("  Anna browser fallback returned an oversized page", file=sys.stderr)
                return ""
            return output_path.read_text(encoding="utf-8")
    except subprocess.TimeoutExpired:
        print("  Anna browser fallback timed out", file=sys.stderr)
    except (OSError, UnicodeError) as e:
        print(f"  Anna browser fallback failed: {e}", file=sys.stderr)
    return ""


def fetch_aa_page(url: str, *, page_kind: str) -> str:
    """Fetch a bounded Anna page, invoking Chromium only for verified gates."""
    if page_kind not in {"search", "detail", "slow"}:
        raise ValueError(f"unsupported Anna page kind: {page_kind}")
    try:
        response = _request("GET", url, timeout=30)
    except Exception:
        return ""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if _is_ddos_guard_challenge(response) or (
        response.status_code == 403 and host.startswith("annas-archive.")
    ):
        return _fetch_aa_with_browser(url, page_kind)
    return response.text if response.status_code == 200 else ""


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

    format_query = "".join(
        f"&ext={urllib.parse.quote_plus(file_format)}"
        for file_format in _normalise_search_formats(fmt)
    )
    url = (
        f"{base_url}/search?index=&page=1&display=table"
        f"&acc=aa_download&acc=external_download"
        f"{format_query}"
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

    response_text = r.text
    if _is_ddos_guard_challenge(r):
        browser_html = _fetch_aa_with_browser(url)
        if not browser_html:
            return {
                "success": False,
                "source": "anna_archive",
                "count": 0,
                "results": [],
                "error": "ddos_guard_challenge",
            }
        response_text = browser_html
    elif r.status_code != 200:
        return {
            "success": False,
            "source": "anna_archive",
            "count": 0,
            "results": [],
        }

    soup = BeautifulSoup(response_text, "html.parser")
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
            md5 = next(
                (
                    candidate
                    for link in row.find_all("a", href=True)
                    if (candidate := _aa_md5_from_href(link.get("href", "")))
                ),
                "",
            )
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

    if not results and not _is_explicit_aa_no_results(soup):
        return {
            "success": False,
            "source": "anna_archive",
            "count": 0,
            "results": [],
            "error": "aa_search_page_incomplete",
        }

    return {
        "success": True,
        "source": "anna_archive",
        "count": len(results[:limit]),
        "results": results[:limit],
    }

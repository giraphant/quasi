#!/usr/bin/env python3
"""Unified academic file download — pure acquisition, no search logic.

Accepts a resolved identifier (MD5, DOI, URL) and downloads the file.
For search/discovery, use search.py first.

Usage:
    # Download book by MD5 (Anna's Archive Fast API)
    python3 download.py --md5 abc123def456 --filename poggi-durkheim

    # Download paper by DOI (cascade: OA → EZProxy → Wayback)
    python3 download.py --doi "10.1080/1600910X.2019.1641121"

    # Download from direct URL
    python3 download.py --url "https://discovery.ucl.ac.uk/paper.pdf" --filename author-2023

    # Batch: download all metadata_found papers in a manifest
    python3 download.py --manifest manifest.json --batch

Config (AA only): .claude/config/anna-archive.json
    {"donator_key": "YOUR_KEY", "mirrors": ["https://annas-archive.gs", ...]}

Config (EZproxy): quasi/skills/download/config/ezproxy.json (or .claude/config/ezproxy.json)
    {"cookie": "VALUE", "cookie_name": "ezproxy", "domain": "...", "login_url": "...", ...}
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import requests

# --- Config ---

_CONFIG_DIR = Path(__file__).resolve().parents[4] / ".claude" / "config"
_SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = _CONFIG_DIR / "anna-archive.json"
# EZProxy: skill-local first, .claude/config fallback
_EZPROXY_LOCAL = _SKILL_DIR / "config" / "ezproxy.json"
_EZPROXY_GLOBAL = _CONFIG_DIR / "ezproxy.json"

DEFAULT_AA_MIRRORS = [
    "https://annas-archive.gl",
    "https://annas-archive.li",
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

HEADERS_API = {"User-Agent": "BTS-Research/1.0 (mailto:research@example.com)"}

DELAY = 5  # Human-like pacing to avoid EZProxy rate limits


class EZProxyCookieExpired(Exception):
    """Raised when EZProxy returns a login page instead of content."""
    pass


class AAQuotaExhausted(Exception):
    """Raised when AA donator key daily download quota is exhausted."""
    pass


def load_ezproxy_config():
    """Load EZProxy cookie config. Skill-local first, .claude/config fallback."""
    for path in (_EZPROXY_LOCAL, _EZPROXY_GLOBAL):
        if path.exists():
            with open(path) as f:
                config = json.load(f)
            if (config.get("cookie") or config.get("cookies")) and config.get("domain"):
                return config
    return None


def _url_matches_ezproxy(url, ezproxy_config):
    """Check if a URL belongs to the EZProxy domain."""
    if not ezproxy_config:
        return False
    domain = ezproxy_config["domain"].lstrip(".")
    return domain in url


# Publisher PDF URL patterns: given a proxied landing page URL,
# match publisher domain hint → construct direct PDF URL.
# Ported from /home/ramu/reeder/src/reeder/fulltext/ezproxy.py
PUBLISHER_PDF_PATTERNS = [
    ("sagepub",      "/doi/pdf/{doi}"),
    ("oup.com",      "/doi/pdf/{doi}"),
    ("academic.oup", "/doi/pdf/{doi}"),
    ("wiley",        "/doi/pdfdirect/{doi}"),
    ("tandfonline",  "/doi/pdf/{doi}"),
    ("springer",     "/content/pdf/{doi}.pdf"),  # reeder uses /article/{doi}/fulltext.pdf
    ("nature.com",   "/content/pdf/{doi}.pdf"),
    ("uchicago",     "/doi/pdf/{doi}"),
    ("mit.edu",      "/doi/pdf/{doi}"),
    ("mitpress",     "/doi/pdf/{doi}"),
]


def _is_pdf_data(data):
    """Check if raw bytes look like a PDF."""
    return data[:5] == b"%PDF-" or (
        len(data) > 50000 and b"<html" not in data[:1000].lower()
    )


def _build_ezproxy_session(config):
    """Build a requests.Session with EZProxy cookies properly scoped.

    Uses requests.Session instead of urllib to ensure cookies are forwarded
    across 302 redirects (urllib drops custom Cookie headers on redirect).
    Supports both single cookie (cookie/cookie_name) and multi-cookie (cookies dict).
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    domain = config.get("domain", ".eux.idm.oclc.org")
    # Multi-cookie: {"cookies": {"name1": "val1", "name2": "val2"}}
    cookies = config.get("cookies", {})
    if cookies:
        for name, value in cookies.items():
            session.cookies.set(name, value, domain=domain)
    else:
        # Single cookie: {"cookie_name": "name", "cookie": "value"}
        cookie_name = config.get("cookie_name", "ezproxy")
        session.cookies.set(cookie_name, config["cookie"], domain=domain)

    return session


def try_ezproxy_download(doi, output_path):
    """Download paper via EZProxy: login redirect → publisher PDF pattern → HTML scrape.

    Returns True on success (file written to output_path), False otherwise.
    Raises EZProxyCookieExpired if session is expired.
    """
    config = load_ezproxy_config()
    if not config:
        return False

    login_url = config.get("login_url", "https://login.eux.idm.oclc.org/login?url=")
    session = _build_ezproxy_session(config)

    # Step 1: Follow EZProxy redirect to proxied publisher landing page
    target_url = f"{login_url}https://doi.org/{doi}"
    print(f"  EZProxy: {target_url[:80]}", file=sys.stderr)

    try:
        resp = session.get(target_url, allow_redirects=True, timeout=30)
    except (requests.RequestException, TimeoutError, OSError) as e:
        print(f"  EZProxy redirect failed: {e}", file=sys.stderr)
        return False

    final_url = str(resp.url)
    landing_html = resp.content

    # Check for expired session — no redirect means cookie not accepted
    if final_url.startswith(login_url.rstrip("?").rsplit("/", 1)[0]):
        lower_html = landing_html[:2000].lower()
        if b"shibboleth" in lower_html or (b"login" in lower_html and b"password" in lower_html):
            raise EZProxyCookieExpired(f"EZProxy cookie expired. Update: {_EZPROXY_LOCAL}")
        # Stayed on login page but no explicit auth form — still expired
        if len(resp.history) == 0:
            raise EZProxyCookieExpired(f"EZProxy cookie not accepted. Update: {_EZPROXY_LOCAL}")

    if resp.status_code != 200:
        print(f"  EZProxy: HTTP {resp.status_code}", file=sys.stderr)
        return False

    print(f"  EZProxy landed: {final_url[:80]}", file=sys.stderr)

    # Step 2: Try known publisher PDF URL patterns
    for publisher_hint, pattern in PUBLISHER_PDF_PATTERNS:
        if publisher_hint in final_url:
            parsed = urllib.parse.urlparse(final_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            pdf_url = base + pattern.format(doi=doi)
            print(f"  EZProxy PDF try: {pdf_url[:80]}", file=sys.stderr)

            try:
                pdf_resp = session.get(pdf_url, timeout=60)
                data = pdf_resp.content
                if _is_pdf_data(data):
                    with open(output_path, "wb") as f:
                        f.write(data)
                    print(f"  OK {len(data) / 1024:.0f}KB -> {os.path.basename(output_path)}",
                          file=sys.stderr)
                    return True
            except (requests.RequestException, TimeoutError, OSError):
                pass
            break  # Only try the first matching publisher

    # Step 3: Scrape landing page HTML for PDF links
    pdf_links = re.findall(
        rb'href=["\']([^"\']*(?:\.pdf|/pdf/)[^"\']*)["\']',
        landing_html,
        re.IGNORECASE,
    )
    for link_bytes in pdf_links[:5]:
        link = link_bytes.decode("utf-8", errors="ignore")
        if link.startswith("/"):
            parsed = urllib.parse.urlparse(final_url)
            link = f"{parsed.scheme}://{parsed.netloc}{link}"
        elif not link.startswith("http"):
            continue

        print(f"  EZProxy scrape try: {link[:80]}", file=sys.stderr)
        try:
            link_resp = session.get(link, timeout=60)
            data = link_resp.content
            if _is_pdf_data(data):
                with open(output_path, "wb") as f:
                    f.write(data)
                print(f"  OK {len(data) / 1024:.0f}KB -> {os.path.basename(output_path)}",
                      file=sys.stderr)
                return True
        except (requests.RequestException, TimeoutError, OSError):
            pass

    print(f"  EZProxy: no PDF found", file=sys.stderr)
    return False


# ============================================================
# Anna's Archive — MD5 → file (no search)
# ============================================================

def load_aa_config():
    """Load Anna's Archive config (donator key + mirrors)."""
    if not CONFIG_PATH.exists():
        return None
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    if not config.get("donator_key"):
        return None
    return config


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


def aa_fast_download_url(base_url, md5, donator_key,
                         path_index=None, domain_index=None):
    """Get download URL via AA Fast API.

    Returns (download_url, quota_info) tuple.
    quota_info is a dict with downloads_left, downloads_per_day, downloads_done_today.
    Raises AAQuotaExhausted if daily quota is exhausted.
    """
    api_url = (
        f"{base_url}/dyn/api/fast_download.json"
        f"?md5={md5}&key={donator_key}"
    )
    if path_index is not None:
        api_url += f"&path_index={path_index}"
    if domain_index is not None:
        api_url += f"&domain_index={domain_index}"

    try:
        r = requests.get(api_url, headers=HEADERS_BROWSER, timeout=30)
    except requests.RequestException as e:
        print(f"  Fast API request failed: {e}", file=sys.stderr)
        return None, {}

    if r.status_code != 200:
        print(f"  Fast API failed: HTTP {r.status_code}", file=sys.stderr)
        return None, {}

    try:
        data = r.json()
    except json.JSONDecodeError:
        print("  Fast API returned non-JSON response", file=sys.stderr)
        return None, {}

    quota_info = data.get("account_fast_download_info", {})
    if quota_info:
        left = quota_info.get("downloads_left", "?")
        total = quota_info.get("downloads_per_day", "?")
        done = quota_info.get("downloads_done_today", "?")
        print(f"  AA quota: {done}/{total} used, {left} left", file=sys.stderr)

        if left == 0:
            raise AAQuotaExhausted(
                f"AA daily quota exhausted ({done}/{total} used). "
                f"Wait for reset before downloading more books."
            )

    url = data.get("download_url")
    error = data.get("error")
    if not url:
        if error:
            print(f"  Fast API error: {error}", file=sys.stderr)
        else:
            print(f"  No download_url in response", file=sys.stderr)
        return None, quota_info

    if url.startswith("/"):
        url = base_url + url

    return url, quota_info


LIBGEN_MIRRORS = [
    "https://libgen.li",
    "https://libgen.st",
]

# path_index/domain_index combos to try when default AA download fails.
# These switch between different collections and download servers.
AA_FALLBACK_INDICES = [
    (0, 0), (0, 1), (1, 0), (1, 1), (2, 0),
]


def _try_libgen_download(md5, dest):
    """Fallback: download from LibGen.li get.php (no key needed)."""
    for mirror in LIBGEN_MIRRORS:
        url = f"{mirror}/get.php?md5={md5}"
        print(f"  LibGen fallback: {url}", file=sys.stderr)
        try:
            r = requests.get(
                url, headers=HEADERS_BROWSER, stream=True,
                timeout=120, allow_redirects=True,
            )
            if r.status_code != 200:
                print(f"  LibGen HTTP {r.status_code}", file=sys.stderr)
                continue

            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)

            if os.path.getsize(dest) > 10240:
                size_mb = os.path.getsize(dest) / (1024 * 1024)
                print(f"  LibGen OK {size_mb:.1f} MB", file=sys.stderr)
                return True
            else:
                print(f"  LibGen file too small ({os.path.getsize(dest)} bytes)", file=sys.stderr)
                os.remove(dest)
        except requests.RequestException as e:
            print(f"  LibGen failed: {e}", file=sys.stderr)
            if os.path.exists(dest):
                os.remove(dest)
    return False


def download_from_aa(md5, output_dir="sources", filename=None, fmt="pdf"):
    """Download a file from AA by MD5. Returns file path or None.

    Flow: AA Fast API (default) → AA Fast API (path/domain rotation) → LibGen.li
    Raises AAQuotaExhausted if daily download quota is exhausted.
    """
    config = load_aa_config()
    if not config:
        print("Error: AA config not found or missing donator_key", file=sys.stderr)
        print(f"Create: {CONFIG_PATH}", file=sys.stderr)
        return None

    base_url = get_aa_base_url(config)
    if not base_url:
        return None
    print(f"  Mirror: {base_url}", file=sys.stderr)

    title_slug = filename or md5
    os.makedirs(output_dir, exist_ok=True)
    dest = os.path.join(output_dir, f"{title_slug}.{fmt}")

    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        print(f"  File already exists: {dest}", file=sys.stderr)
        return dest

    print(f"  MD5: {md5}", file=sys.stderr)
    key = config["donator_key"]

    # --- Stage 1: AA Fast API (default parameters) ---
    dl_url, quota = aa_fast_download_url(base_url, md5, key)
    # AAQuotaExhausted propagates up if quota == 0

    if dl_url:
        print(f"  Downloading to: {dest}", file=sys.stderr)
        if _stream_download(dl_url, dest, headers=HEADERS_BROWSER):
            size_mb = os.path.getsize(dest) / (1024 * 1024)
            print(f"  Done! {size_mb:.1f} MB -> {dest}", file=sys.stderr)
            return dest
        if os.path.exists(dest):
            os.remove(dest)
        print(f"  Default download failed, trying alternate sources...", file=sys.stderr)

    # --- Stage 2: AA Fast API with path_index/domain_index rotation ---
    for pi, di in AA_FALLBACK_INDICES:
        print(f"  Trying path_index={pi}, domain_index={di}...", file=sys.stderr)
        try:
            dl_url, quota = aa_fast_download_url(base_url, md5, key, pi, di)
        except AAQuotaExhausted:
            raise  # Quota exhausted, stop everything
        if not dl_url:
            continue
        if _stream_download(dl_url, dest, headers=HEADERS_BROWSER):
            size_mb = os.path.getsize(dest) / (1024 * 1024)
            print(f"  Done! {size_mb:.1f} MB -> {dest}", file=sys.stderr)
            return dest
        if os.path.exists(dest):
            os.remove(dest)

    # --- Stage 3: LibGen.li fallback (no key needed) ---
    print(f"  AA exhausted all options, trying LibGen...", file=sys.stderr)
    if _try_libgen_download(md5, dest):
        return dest

    print(f"  All sources failed for MD5 {md5}", file=sys.stderr)
    return None


# ============================================================
# OA / Wayback — DOI → file
# ============================================================

def _get_json_urllib(url, timeout=15):
    """Fetch JSON from URL using urllib."""
    try:
        req = urllib.request.Request(url, headers=HEADERS_API)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return None


def find_oa_url(doi):
    """Find Open Access URL for a DOI via Unpaywall + OpenAlex + S2."""
    if not doi:
        return None

    # 1. Unpaywall
    url = f"https://api.unpaywall.org/v2/{doi}?email=research@example.com"
    data = _get_json_urllib(url)
    if data:
        best = data.get("best_oa_location")
        if best:
            oa_url = best.get("url_for_pdf") or best.get("url")
            if oa_url:
                return oa_url
    time.sleep(DELAY)

    # 2. OpenAlex
    url = f"https://api.openalex.org/works/doi:{doi}?mailto=research@example.com"
    data = _get_json_urllib(url)
    if data:
        oa_url = data.get("open_access", {}).get("oa_url")
        if oa_url:
            return oa_url
    time.sleep(DELAY)

    # 3. Semantic Scholar
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
        f"?fields=openAccessPdf"
    )
    data = _get_json_urllib(url)
    if data:
        oa_pdf = data.get("openAccessPdf")
        if oa_pdf and oa_pdf.get("url"):
            return oa_pdf["url"]

    return None


SCIHUB_MIRRORS = ["https://sci-hub.ru", "https://sci-hub.ren"]


def try_scihub_download(doi, output_path):
    """Try downloading a paper PDF from Sci-Hub by DOI.

    Extracts the PDF URL from <meta name="citation_pdf_url"> tag.
    Tries multiple mirrors. Returns True on success.
    """
    if not doi:
        return False

    for mirror in SCIHUB_MIRRORS:
        try:
            page_url = f"{mirror}/{doi}"
            req = urllib.request.Request(page_url, headers=HEADERS_BROWSER)
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read(50000).decode("utf-8", errors="ignore")

            # Extract PDF URL from <meta name="citation_pdf_url" content="...">
            match = re.search(
                r'citation_pdf_url"\s+content="([^"]+)"', html
            )
            if not match:
                print(f"  Sci-Hub ({mirror}): no PDF link found", file=sys.stderr)
                continue

            pdf_url = match.group(1)
            if pdf_url.startswith("//"):
                pdf_url = "https:" + pdf_url

            # Download the PDF
            pdf_req = urllib.request.Request(pdf_url, headers=HEADERS_BROWSER)
            with urllib.request.urlopen(pdf_req, timeout=60) as pdf_resp:
                data = pdf_resp.read()
                if _is_pdf_data(data):
                    with open(output_path, "wb") as f:
                        f.write(data)
                    print(
                        f"  Sci-Hub OK {len(data) / 1024:.0f}KB -> "
                        f"{os.path.basename(output_path)}",
                        file=sys.stderr,
                    )
                    return True
                else:
                    print(f"  Sci-Hub ({mirror}): not a PDF", file=sys.stderr)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            print(f"  Sci-Hub ({mirror}): {e}", file=sys.stderr)
            continue

    return False


def find_wayback_url(doi):
    """Check Wayback Machine for archived PDF."""
    if not doi:
        return None

    pdf_urls = []
    if doi.startswith("10.1145/"):
        pdf_urls.append(f"https://dl.acm.org/doi/pdf/{doi}")
    elif doi.startswith("10.1007/"):
        pdf_urls.append(f"https://link.springer.com/content/pdf/{doi}.pdf")
    elif doi.startswith("10.1080/") or doi.startswith("10.1177/"):
        pdf_urls.append(f"https://doi.org/{doi}")
    elif doi.startswith("10.1353/"):
        pdf_urls.append(f"https://muse.jhu.edu/pub/{doi.split('/')[-1]}")
    pdf_urls.append(f"https://doi.org/{doi}")

    for url in pdf_urls:
        cdx_url = (
            f"https://web.archive.org/cdx/search/cdx"
            f"?url={urllib.parse.quote(url, safe='')}"
            f"&output=json&limit=1&fl=timestamp,original"
        )
        data = _get_json_urllib(cdx_url)
        if data and len(data) > 1:
            timestamp, original = data[1]
            return f"https://web.archive.org/web/{timestamp}id_/{original}"
        time.sleep(DELAY)

    return None


def download_pdf_from_url(url, output_path, timeout=60):
    """Download a PDF from URL. Returns True on success.

    Auto-injects EZProxy cookie for matching domains.
    Raises EZProxyCookieExpired if response looks like a login page.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/pdf,*/*",
        }
        # Auto-inject EZProxy cookie if URL matches
        ezproxy = load_ezproxy_config()
        if _url_matches_ezproxy(url, ezproxy):
            cookie_name = ezproxy.get("cookie_name", "ezproxy")
            headers["Cookie"] = f"{cookie_name}={ezproxy['cookie']}"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if _is_pdf_data(data):
                with open(output_path, "wb") as f:
                    f.write(data)
                print(f"  OK {len(data) / 1024:.0f}KB -> {os.path.basename(output_path)}",
                      file=sys.stderr)
                return True
            else:
                # Check if this is an EZProxy login page
                lower_data = data[:2000].lower()
                if _url_matches_ezproxy(url, ezproxy) and (
                    b"login" in lower_data or b"auth" in lower_data
                    or b"ezproxy" in lower_data or b"shibboleth" in lower_data
                ):
                    raise EZProxyCookieExpired(
                        f"EZProxy cookie expired. Update: {_EZPROXY_LOCAL}"
                    )
                print(f"  SKIP not-a-pdf ({len(data)} bytes)", file=sys.stderr)
                return False
    except EZProxyCookieExpired:
        raise  # Re-raise, don't swallow
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"  FAIL {e}", file=sys.stderr)
        return False


def download_paper(doi=None, url=None, output_dir="sources", filename=None,
                   retry_wayback=True):
    """Download a paper PDF by DOI or URL. Returns file path or None.

    Cascade: direct URL → OA (Unpaywall/OpenAlex/S2) → Sci-Hub → EZProxy → Wayback
    """
    if filename:
        safe_name = filename
    elif doi:
        safe_name = doi.replace("/", "_").replace(".", "_")
    else:
        safe_name = "paper"

    os.makedirs(output_dir, exist_ok=True)
    dest = os.path.join(output_dir, f"{safe_name}.pdf")

    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        print(f"  EXISTS {dest}", file=sys.stderr)
        return dest

    # 1. Direct URL
    if url:
        print(f"  Direct URL: {url[:80]}", file=sys.stderr)
        if download_pdf_from_url(url, dest):
            return dest
        time.sleep(0.5)

    # 2. OA sources
    if doi:
        print(f"  Searching OA for {doi}...", file=sys.stderr)
        oa_url = find_oa_url(doi)
        if oa_url:
            print(f"  OA: {oa_url[:80]}", file=sys.stderr)
            if download_pdf_from_url(oa_url, dest):
                return dest
            time.sleep(0.5)

    # 3. Sci-Hub
    if doi:
        print(f"  Trying Sci-Hub for {doi}...", file=sys.stderr)
        if try_scihub_download(doi, dest):
            return dest
        time.sleep(0.5)

    # 4. EZProxy (institutional proxy)
    if doi:
        print(f"  Trying EZProxy for {doi}...", file=sys.stderr)
        try:
            if try_ezproxy_download(doi, dest):
                return dest
        except EZProxyCookieExpired:
            print(f"  EZProxy cookie expired, skipping to Wayback...", file=sys.stderr)
        time.sleep(0.5)

    # 5. Wayback
    if doi and retry_wayback:
        print(f"  Searching Wayback for {doi}...", file=sys.stderr)
        wb_url = find_wayback_url(doi)
        if wb_url:
            print(f"  WB: {wb_url[:80]}", file=sys.stderr)
            if download_pdf_from_url(wb_url, dest, timeout=90):
                return dest

    print(f"  Could not download paper", file=sys.stderr)
    return None


# ============================================================
# Batch mode (manifest)
# ============================================================

def batch_download_manifest(manifest_path, retry_wayback=False):
    """Download all metadata_found papers in a manifest."""
    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    pdf_dir = manifest.get("pdf_dir", "/tmp/snowball-pdfs")
    os.makedirs(pdf_dir, exist_ok=True)

    to_process = [
        (k, p) for k, p in manifest["papers"].items()
        if p.get("status") == "metadata_found"
    ]
    print(f"Papers to acquire: {len(to_process)}", file=sys.stderr)

    acquired = 0
    abstract_only = 0

    for key, paper in to_process:
        doi = paper.get("doi", "")
        title = paper.get("title", key)
        print(f"\n[{key}] {title[:60]}", file=sys.stderr)

        safe_key = key.replace("/", "_").replace(".", "_").replace(" ", "_")
        pdf_path = os.path.join(pdf_dir, f"{safe_key}.pdf")

        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000:
            print(f"  EXISTS {pdf_path}", file=sys.stderr)
            paper["pdf_path"] = pdf_path
            paper["status"] = "acquired"
            acquired += 1
            continue

        success = False

        try:
            # 1. Try OA URL from manifest
            oa_url = paper.get("oa_url")
            if oa_url:
                print(f"  OA: {oa_url[:80]}", file=sys.stderr)
                success = download_pdf_from_url(oa_url, pdf_path)
                time.sleep(0.5)

            # 2. Try finding new OA
            if not success and doi:
                new_oa_url = find_oa_url(doi)
                if new_oa_url and new_oa_url != oa_url:
                    print(f"  New OA: {new_oa_url[:80]}", file=sys.stderr)
                    success = download_pdf_from_url(new_oa_url, pdf_path)
                    if success:
                        paper["oa_url"] = new_oa_url
                    time.sleep(0.5)

            # 3. Try Sci-Hub
            if not success and doi:
                print(f"  Trying Sci-Hub for {doi}...", file=sys.stderr)
                success = try_scihub_download(doi, pdf_path)
                time.sleep(0.5)

            # 4. Try EZProxy
            if not success and doi:
                print(f"  Trying EZProxy for {doi}...", file=sys.stderr)
                success = try_ezproxy_download(doi, pdf_path)
                time.sleep(0.5)

            # 5. Try Wayback
            if not success and doi:
                wb_url = paper.get("wayback_url")
                if not wb_url and retry_wayback:
                    print(f"  Wayback search for {doi}...", file=sys.stderr)
                    wb_url = find_wayback_url(doi)
                if wb_url:
                    print(f"  WB: {wb_url[:80]}", file=sys.stderr)
                    success = download_pdf_from_url(wb_url, pdf_path, timeout=90)
                    if success:
                        paper["wayback_url"] = wb_url
                    time.sleep(0.5)

        except EZProxyCookieExpired as e:
            print(f"\n*** STOPPED: {e} ***", file=sys.stderr)
            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            print(f"Progress saved. Acquired so far: {acquired}", file=sys.stderr)
            sys.exit(1)

        if success:
            paper["pdf_path"] = pdf_path
            paper["status"] = "acquired"
            acquired += 1
        else:
            paper["status"] = "abstract_only"
            abstract_only += 1

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\n=== Results ===", file=sys.stderr)
    print(f"Acquired: {acquired}", file=sys.stderr)
    print(f"Abstract-only: {abstract_only}", file=sys.stderr)
    return acquired


# ============================================================
# Utilities
# ============================================================

def slugify(text):
    """Convert text to kebab-case filename."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:80].rstrip("-")


def _stream_download(url, dest_path, headers=None):
    """Stream-download file with progress."""
    r = requests.get(url, headers=headers or HEADERS_BROWSER, stream=True, timeout=120)
    if r.status_code != 200:
        print(f"  Download failed: HTTP {r.status_code}", file=sys.stderr)
        return False

    total = int(r.headers.get("content-length", 0))
    downloaded = 0

    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
                print(
                    f"\r  [{bar}] {pct}% ({downloaded // 1024}KB/{total // 1024}KB)",
                    end="", flush=True, file=sys.stderr,
                )
    print(file=sys.stderr)

    size = os.path.getsize(dest_path)
    if size < 10240:
        print(f"  Warning: file very small ({size} bytes), might not be valid", file=sys.stderr)
        return False

    return True


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Academic file download — pure acquisition by identifier (MD5/DOI/URL)"
    )

    # Input modes
    group = parser.add_argument_group("input (pick one)")
    group.add_argument("--md5", help="AA download by MD5 (needs donator key)")
    group.add_argument("--doi", help="Paper DOI (cascade: OA → EZProxy → Wayback)")
    group.add_argument("--url", help="Direct PDF URL")
    group.add_argument("--manifest", help="Manifest file for batch download")

    # Options
    parser.add_argument("--output-dir", "-o", default="sources", help="Output directory (default: sources)")
    parser.add_argument("--filename", help="Output filename (without extension)")
    parser.add_argument("--format", "-f", default="pdf", help="File format (default: pdf)")
    parser.add_argument("--batch", action="store_true", help="Batch download all metadata_found in manifest")
    parser.add_argument("--retry-wayback", action="store_true", help="Re-check Wayback for papers")

    args = parser.parse_args()

    # Route to appropriate handler
    try:
        if args.manifest and args.batch:
            batch_download_manifest(args.manifest, retry_wayback=args.retry_wayback)
        elif args.md5:
            result = download_from_aa(
                md5=args.md5, output_dir=args.output_dir,
                filename=args.filename, fmt=args.format,
            )
            if result:
                print(result)
            else:
                sys.exit(1)
        elif args.doi or args.url:
            result = download_paper(
                doi=args.doi, url=args.url, output_dir=args.output_dir,
                filename=args.filename, retry_wayback=args.retry_wayback,
            )
            if result:
                print(result)
            else:
                sys.exit(1)
        else:
            parser.error("Need one of: --md5, --doi, --url, or --manifest --batch")
    except AAQuotaExhausted as e:
        print(f"\n*** AA QUOTA EXHAUSTED ***", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print(f"  Stop all book downloads and wait for quota reset.", file=sys.stderr)
        sys.exit(2)
    except EZProxyCookieExpired as e:
        print(f"\n*** EZPROXY COOKIE EXPIRED ***", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print(f"  Update cookie in: {_EZPROXY_LOCAL}", file=sys.stderr)
        print(f"  Login URL: https://login.eux.idm.oclc.org/login", file=sys.stderr)
        print(f"  Stop all paper downloads until cookie is refreshed.", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()

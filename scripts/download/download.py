#!/usr/bin/env python3
"""Unified academic file download — acquisition CLI for agents.

Agent-facing public flow:
    book candidates  -> candidate metadata from Anna's Archive file search
    book fetch       -> download by MD5 to temp + automatic diagnostics
    paper fetch      -> DOI/URL cascade to temp + automatic diagnostics
    accept           -> move accepted temp file into sources/{slug}.{ext}

Usage:
    python3 download.py book candidates --title "..." --author "..." --json
    python3 download.py book fetch --md5 abc123 --slug poggi-durkheim --json
    python3 download.py paper fetch --doi "10.x/y" --slug author-title-2024 --json
    python3 download.py accept --path .quasi/temp/downloads/x.pdf --slug final-slug --json

Batch mode remains for existing manifest-driven maintenance workflows.

Config: all from QUASI_* env vars injected by the PreToolUse hook
(see `scripts/hooks/inject-userconfig.py`). Plugin `userConfig` defines the
values; the hook reads them in its own env and prepends them to qua's
shell command. Sensitive values stay in the system keychain — they only
materialise in the hook+bash subprocess env for one tool call at a time.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT))

import requests
from aa import get_aa_base_url, load_aa_config, search_aa  # noqa: E402
from core import print_json, project_root, resolve_project_path  # noqa: E402

# --- Config ---

_PROJECT_DIR = project_root()  # caller's research project root — output dir, no config
# All credentials come from QUASI_* env vars (injected by PreToolUse hook).

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

DELAY = 10  # Rate limit: minimum 10s between downloads

# Treat these HTTP statuses as transient (worth retrying). Anything else
# (4xx, 410, etc.) is deterministic and propagates immediately.
_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504, 520, 521, 522, 524})


def _is_retryable_http(exc) -> bool:
    code = None
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
    elif isinstance(exc, requests.HTTPError) and getattr(exc, "response", None) is not None:
        code = exc.response.status_code
    return code is not None and code in _RETRYABLE_HTTP_CODES


def _retry(fn, *, attempts=3, base_delay=1.0, label="http"):
    """Run fn() with exponential-backoff retry on transient network errors.

    Retries on connection resets, DNS hiccups, socket timeouts, and
    transient HTTP statuses (429/5xx). 4xx responses and domain-specific
    exceptions (e.g. EZProxyCookieExpired) propagate without retry.
    """
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if not _is_retryable_http(e):
                raise
            last_exc = e
        except requests.HTTPError as e:
            if not _is_retryable_http(e):
                raise
            last_exc = e
        except (
            urllib.error.URLError,
            requests.RequestException,
            TimeoutError,
            ConnectionResetError,
        ) as e:
            last_exc = e
        if i < attempts - 1:
            sleep = base_delay * (2 ** i)
            print(
                f"  retry {label} ({i + 1}/{attempts - 1}): "
                f"{type(last_exc).__name__}: {last_exc}; sleeping {sleep:.1f}s",
                file=sys.stderr,
            )
            time.sleep(sleep)
    raise last_exc


class EZProxyCookieExpired(Exception):
    """Raised when EZProxy returns a login page instead of content."""
    pass


class AAQuotaExhausted(Exception):
    """Raised when AA donator key daily download quota is exhausted."""
    pass


def load_ezproxy_config():
    """Resolve EZProxy cookie config from CookieCloud (in-memory).

    Connection params come from plugin user-config env vars; see cookiecloud.py.
    Returns None when CookieCloud is not configured or unreachable.
    """
    try:
        from cookiecloud import get_ezproxy_config
    except ImportError:
        from .cookiecloud import get_ezproxy_config  # type: ignore
    return get_ezproxy_config(verbose=True)


def _try_ezproxy_with_refresh(doi, output_path):
    """Try EZProxy download; on expiry, invalidate cache + retry once.

    Clears the in-memory CookieCloud cache so the next call re-pulls fresh
    cookies from the server. Re-raises EZProxyCookieExpired if the refreshed
    cookies are also rejected (Chrome side likely hasn't re-logged in yet).
    """
    try:
        return try_ezproxy_download(doi, output_path)
    except EZProxyCookieExpired:
        try:
            from cookiecloud import invalidate_cache, get_ezproxy_config
        except ImportError:
            from .cookiecloud import invalidate_cache, get_ezproxy_config  # type: ignore
        invalidate_cache()
        if get_ezproxy_config():
            print(f"  EZProxy: refreshed via CookieCloud, retrying...", file=sys.stderr)
            return try_ezproxy_download(doi, output_path)
        raise


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
    ("wiley",        "/doi/pdfdirect/{doi}?download=true"),
    ("tandfonline",  "/doi/pdf/{doi}"),
    ("tandfonline",  "/doi/pdf/{doi}?download=true"),
    ("springer",     "/content/pdf/{doi}.pdf"),  # reeder uses /article/{doi}/fulltext.pdf
    ("nature.com",   "/content/pdf/{doi}.pdf"),
    ("uchicago",     "/doi/pdf/{doi}"),
    ("uchicago",     "/doi/pdf/{doi}?download=true"),
    ("uchicago",     "/doi/pdfplus/{doi}"),
    ("uchicago",     "/doi/pdfplus/{doi}?download=true"),
    ("mit.edu",      "/doi/pdf/{doi}"),
    ("mitpress",     "/doi/pdf/{doi}"),
    ("pubsonline.informs", "/doi/pdf/{doi}"),
]

_EPDF_PUBLISHER_PATTERNS = [
    ("uchicago", "/doi/epdf/{doi}"),
    ("tandfonline", "/doi/epdf/{doi}?needAccess=true"),
    ("wiley", "/doi/epdf/{doi}"),
]

_RE_META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_RE_HTML_ATTR = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*([\"'])(.*?)\2""", re.DOTALL)


def _extract_citation_pdf_url(html_bytes):
    text = html_bytes[:200000].decode("utf-8", errors="ignore")
    for tag in _RE_META_TAG.findall(text):
        attrs = {
            name.lower(): html.unescape(value.strip())
            for name, _quote, value in _RE_HTML_ATTR.findall(tag)
        }
        if attrs.get("name", "").lower() == "citation_pdf_url":
            url = attrs.get("content", "").strip()
            if url:
                return url
    return None


def _is_pdf_data(data):
    """Check if raw bytes look like a PDF."""
    return data[:5] == b"%PDF-" or (
        len(data) > 50000 and b"<html" not in data[:1000].lower()
    )


def _extract_pdf_text(pdf_path, max_pages=2, allow_raw_fallback=True):
    """Extract text from first pages of a PDF for verification.

    Tries pdftotext first, falls back to raw byte search.
    Returns lowercase text string.
    """
    # Try pdftotext (poppler)
    try:
        result = subprocess.run(
            ["pdftotext", "-l", str(max_pages), pdf_path, "-"],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.decode("utf-8", errors="ignore").lower()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if not allow_raw_fallback:
        return ""

    # Fallback: search raw PDF bytes for readable text
    try:
        with open(pdf_path, "rb") as f:
            raw = f.read(200_000)  # First ~200KB
        # PDF text is often in parenthesized strings or between BT/ET blocks
        text = raw.decode("latin-1", errors="ignore").lower()
        return text
    except OSError:
        return ""


def _extract_epub_text(epub_path, max_items=3):
    """Extract front text from an EPUB for lightweight book verification."""
    import zipfile
    from xml.etree import ElementTree as ET

    try:
        texts = []
        with zipfile.ZipFile(epub_path) as zf:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            rootfile = container.find(
                ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
            )
            if rootfile is None:
                return ""

            opf_path = rootfile.attrib.get("full-path")
            if not opf_path:
                return ""

            opf_dir = Path(opf_path).parent
            opf = ET.fromstring(zf.read(opf_path))
            ns = {"opf": "http://www.idpf.org/2007/opf"}
            manifest = {
                item.attrib["id"]: item.attrib.get("href", "")
                for item in opf.findall("opf:manifest/opf:item", ns)
            }
            spine = [
                itemref.attrib.get("idref", "")
                for itemref in opf.findall("opf:spine/opf:itemref", ns)
            ]

            for item_id in spine:
                href = manifest.get(item_id)
                if not href:
                    continue
                item_path = (opf_dir / href).as_posix()
                if not item_path.endswith((".xhtml", ".html", ".htm")):
                    continue
                data = zf.read(item_path).decode("utf-8", errors="ignore")
                text = re.sub(r"<[^>]+>", " ", data)
                texts.append(text)
                if len(texts) >= max_items:
                    break
        return " ".join(texts).lower()
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile):
        return ""


_YEAR_RE = r"\b(?:19|20)\d{2}\b"

# Patterns that indicate the year is the *publication* year of this edition.
# Order matters: earlier patterns win when assembling best_guess.
_FIRST_PUBLISHED_PATTERNS = [
    re.compile(r"first\s+published[^.]{0,40}?(" + _YEAR_RE + r")", re.IGNORECASE),
    re.compile(r"first\s+edition[^.]{0,30}?(" + _YEAR_RE + r")", re.IGNORECASE),
    re.compile(r"first\s+english(?:\s+language)?\s+edition[^.]{0,30}?(" + _YEAR_RE + r")", re.IGNORECASE),
    # "Published 2023 by X" / "Published in 2023" — but NOT "Originally published"
    re.compile(r"(?<!ly\s)(?<!originally\s)published\s+(?:in\s+)?(" + _YEAR_RE + r")", re.IGNORECASE),
]

# Patterns that indicate the year is the *copyright* year — often the
# preceding calendar year for press books finalised in Q4.
_COPYRIGHT_PATTERNS = [
    re.compile(r"copyright\s*©?\s*(" + _YEAR_RE + r")", re.IGNORECASE),
    re.compile(r"©\s*(" + _YEAR_RE + r")", re.IGNORECASE),
]

# Patterns that indicate the year is the *original* (pre-translation /
# pre-reissue) year — never the year of *this* edition.
_ORIGINAL_PATTERNS = [
    re.compile(r"originally\s+published[^.]{0,80}?(" + _YEAR_RE + r")", re.IGNORECASE),
    re.compile(r"translated\s+from[^.]{0,80}?(" + _YEAR_RE + r")", re.IGNORECASE),
    re.compile(r"original(?:\s+french|\s+german|\s+spanish|\s+italian)?\s+edition[^.]{0,30}?(" + _YEAR_RE + r")", re.IGNORECASE),
]


def _extract_year_signals(text):
    """Structurally extract year signals from front matter.

    Returns dict with:
      - first_published: int | None — "First published 2023" / "First edition 2023"
      - copyright_year:  int | None — "Copyright 2022"
      - original_year:   int | None — "Originally published in French as ... 2008"
      - other_years:     list[int]  — every 1900-2099 hit, in text order, dedup
      - best_guess:      int | None — first_published > copyright_year > other_years[-1]
                                      (copyright_year+1 prefers the later year when
                                       copyright year sits inside other_years and a
                                       later year is also present — heuristic for
                                       Q4-finalised press books)
      - evidence_text:   short snippet quoting the matched fragment for best_guess
    """
    text = text or ""
    lowered_for_search = text  # patterns are IGNORECASE

    def _first_match(patterns):
        for pat in patterns:
            m = pat.search(lowered_for_search)
            if m:
                return int(m.group(1)), m.group(0)
        return None, None

    first_published, first_published_ctx = _first_match(_FIRST_PUBLISHED_PATTERNS)
    copyright_year, copyright_ctx = _first_match(_COPYRIGHT_PATTERNS)
    original_year, original_ctx = _first_match(_ORIGINAL_PATTERNS)

    # All years in text order, deduped
    raw_years = [int(y) for y in re.findall(_YEAR_RE, text)]
    seen = set()
    other_years: list[int] = []
    for y in raw_years:
        if y in seen:
            continue
        seen.add(y)
        other_years.append(y)

    best_guess = first_published or copyright_year
    evidence = first_published_ctx or copyright_ctx or None

    # Q4-finalised press heuristic: if copyright is in other_years and a
    # strictly later year ≤ copyright+2 also appears (release lag), prefer
    # the later one. Conservative — only nudges by 1-2 years.
    if best_guess == copyright_year and copyright_year is not None:
        candidate = next(
            (y for y in other_years
             if copyright_year < y <= copyright_year + 2 and y not in {original_year}),
            None,
        )
        if candidate is not None:
            best_guess = candidate
            evidence = f"copyright {copyright_year}; release year {candidate} also present in front matter"

    # Final fallback: nothing structurally tagged — take last year in text order
    # (front matter usually leads with original/translation/copyright; the
    # latest year mentioned is most likely the edition year).
    if best_guess is None and other_years:
        best_guess = max(other_years)
        evidence = "fallback: no structural year tag found, using max(other_years)"

    return {
        "first_published": first_published,
        "copyright_year": copyright_year,
        "original_year": original_year,
        "other_years": other_years,
        "best_guess": best_guess,
        "evidence_text": evidence,
    }


def verify_pdf_content(pdf_path, expected_author=None, expected_title=None,
                       min_keyword_matches=2):
    """Verify downloaded PDF matches expected paper.

    Extracts text from first 2 pages and checks for author surname
    and title keywords. Returns True if content matches, False otherwise.
    """
    if not expected_author and not expected_title:
        return True  # Nothing to verify

    text = _extract_pdf_text(pdf_path)
    if not text:
        print(f"  Verify: could not extract text, skipping check", file=sys.stderr)
        return True  # Can't verify, assume OK

    matches = 0
    needed = min_keyword_matches

    # Check author surname
    if expected_author:
        # Extract surname (last word, or first word if Asian name)
        author_lower = expected_author.lower().strip()
        # Try full author string and individual words
        if author_lower in text:
            matches += 2  # Strong signal
            print(f"  Verify: author '{expected_author}' found", file=sys.stderr)
        else:
            # Try surname only (last word for Western names)
            parts = author_lower.split()
            surname = parts[-1] if parts else author_lower
            if len(surname) >= 3 and surname in text:
                matches += 1
                print(f"  Verify: surname '{surname}' found", file=sys.stderr)
            else:
                print(f"  Verify: author '{expected_author}' NOT found", file=sys.stderr)

    # Check title keywords
    if expected_title:
        title_lower = expected_title.lower()
        # Extract meaningful words (skip short/common ones)
        stop_words = {
            "the", "a", "an", "of", "in", "on", "and", "or", "for", "to",
            "is", "are", "was", "with", "from", "by", "at", "as", "its",
            "this", "that", "how", "what", "why", "new", "between",
        }
        words = [w for w in re.findall(r'[a-z]{3,}', title_lower)
                 if w not in stop_words]

        found_words = [w for w in words if w in text]
        if found_words:
            matches += len(found_words)
            print(f"  Verify: title words found: {found_words[:5]}", file=sys.stderr)
        else:
            print(f"  Verify: no title keywords found in PDF", file=sys.stderr)

    if matches >= needed:
        print(f"  Verify: PASS ({matches} matches)", file=sys.stderr)
        return True
    else:
        print(f"  Verify: FAIL ({matches}/{needed} matches) — wrong paper?",
              file=sys.stderr)
        return False


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
        print("  EZProxy: not configured (CookieCloud env vars missing), skipping",
              file=sys.stderr)
        return False

    login_url = config["login_url"]
    session = _build_ezproxy_session(config)

    # Step 1: Follow EZProxy redirect to proxied publisher landing page
    target_url = f"{login_url}https://doi.org/{doi}"
    print(f"  EZProxy: {target_url[:80]}", file=sys.stderr)

    try:
        resp = _retry(
            lambda: session.get(target_url, allow_redirects=True, timeout=30),
            label="EZProxy redirect",
        )
    except (requests.RequestException, TimeoutError, OSError) as e:
        print(f"  EZProxy redirect failed: {e}", file=sys.stderr)
        return False

    final_url = str(resp.url)
    landing_html = resp.content

    # Check for expired session — no redirect means cookie not accepted
    if final_url.startswith(login_url.rstrip("?").rsplit("/", 1)[0]):
        lower_html = landing_html[:2000].lower()
        if b"shibboleth" in lower_html or (b"login" in lower_html and b"password" in lower_html):
            raise EZProxyCookieExpired("EZProxy cookie expired — re-login in Chrome to let CookieCloud sync fresh cookies")
        # Stayed on login page but no explicit auth form — still expired
        if len(resp.history) == 0:
            raise EZProxyCookieExpired("EZProxy cookie not accepted — re-login in Chrome to let CookieCloud sync fresh cookies")

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
                pdf_resp = _retry(
                    lambda: session.get(pdf_url, timeout=60),
                    label=f"EZProxy PDF {publisher_hint}",
                )
                data = pdf_resp.content
                if _is_pdf_data(data):
                    with open(output_path, "wb") as f:
                        f.write(data)
                    print(f"  OK {len(data) / 1024:.0f}KB -> {os.path.basename(output_path)}",
                          file=sys.stderr)
                    return True
            except (requests.RequestException, TimeoutError, OSError):
                pass

    # Step 2.5: Extract citation_pdf_url from landing page meta tags
    _citation_pdf = _extract_citation_pdf_url(landing_html)
    if _citation_pdf:
        if _citation_pdf.startswith("/"):
            parsed = urllib.parse.urlparse(final_url)
            _citation_pdf = f"{parsed.scheme}://{parsed.netloc}{_citation_pdf}"
        print(f"  EZProxy citation_pdf_url: {_citation_pdf[:80]}", file=sys.stderr)
        try:
            pdf_resp = _retry(
                lambda: session.get(_citation_pdf, timeout=60),
                label="EZProxy citation_pdf_url",
            )
            data = pdf_resp.content
            if _is_pdf_data(data):
                with open(output_path, "wb") as f:
                    f.write(data)
                print(f"  OK {len(data) / 1024:.0f}KB -> {os.path.basename(output_path)}",
                      file=sys.stderr)
                return True
        except (requests.RequestException, TimeoutError, OSError):
            pass

    # Step 2.6: Fetch epdf page (embedded PDF viewer) and extract PDF URL
    for publisher_hint, epdf_pattern in _EPDF_PUBLISHER_PATTERNS:
        if publisher_hint in final_url:
            parsed = urllib.parse.urlparse(final_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            epdf_url = base + epdf_pattern.format(doi=doi)
            print(f"  EZProxy epdf: {epdf_url[:80]}", file=sys.stderr)
            try:
                epdf_resp = _retry(
                    lambda: session.get(epdf_url, timeout=30),
                    label=f"EZProxy epdf {publisher_hint}",
                )
                epdf_pdf = _extract_citation_pdf_url(epdf_resp.content)
                if epdf_pdf:
                    if epdf_pdf.startswith("/"):
                        epdf_pdf = base + epdf_pdf
                    print(f"  EZProxy epdf -> PDF: {epdf_pdf[:80]}", file=sys.stderr)
                    pdf_resp = _retry(
                        lambda: session.get(epdf_pdf, timeout=60),
                        label=f"EZProxy epdf-PDF {publisher_hint}",
                    )
                    data = pdf_resp.content
                    if _is_pdf_data(data):
                        with open(output_path, "wb") as f:
                            f.write(data)
                        print(f"  OK {len(data) / 1024:.0f}KB -> {os.path.basename(output_path)}",
                              file=sys.stderr)
                        return True
            except (requests.RequestException, TimeoutError, OSError):
                pass

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
            link_resp = _retry(
                lambda: session.get(link, timeout=60),
                label="EZProxy scrape",
            )
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


def download_from_aa(md5, output_dir="sources", filename=None, fmt="pdf",
                     verify_author=None, verify_title=None):
    """Download a file from AA by MD5. Returns file path or None.

    Flow: AA Fast API (default) → AA Fast API (path/domain rotation) → LibGen.li
    Raises AAQuotaExhausted if daily download quota is exhausted.

    If verify_author/verify_title provided, checks content after download.
    Returns None (and deletes file) if content doesn't match.
    """
    config = load_aa_config()
    if not config:
        print("Error: Anna's Archive donator key not set", file=sys.stderr)
        print("  Run /plugin → Configure options and fill `anna_donator_key`", file=sys.stderr)
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

    def _aa_verify(path):
        """Post-download verification for AA. Returns True if OK."""
        if not verify_author and not verify_title:
            return True
        if verify_pdf_content(path, verify_author, verify_title):
            return True
        print(f"  AA verify: content mismatch, wrong file from AA",
              file=sys.stderr)
        if os.path.exists(path):
            os.remove(path)
        return False

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
            if _aa_verify(dest):
                return dest
            else:
                print(f"  AA content mismatch — file deleted", file=sys.stderr)
                return None  # Don't try other AA sources for same wrong MD5
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
            if _aa_verify(dest):
                return dest
            else:
                print(f"  AA content mismatch — file deleted", file=sys.stderr)
                return None  # Same MD5 = same wrong file
        if os.path.exists(dest):
            os.remove(dest)

    # --- Stage 3: LibGen.li fallback (no key needed) ---
    print(f"  AA exhausted all options, trying LibGen...", file=sys.stderr)
    if _try_libgen_download(md5, dest):
        if _aa_verify(dest):
            return dest
        return None

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
    time.sleep(DELAY)

    # 4. Crossref link field — publisher-registered PDF URLs
    url = f"https://api.crossref.org/works/{doi}"
    data = _get_json_urllib(url, timeout=20)
    if data and data.get("status") == "ok":
        msg = data.get("message") or {}
        for link in msg.get("link") or []:
            ct = (link.get("content-type") or "").lower()
            if ct == "application/pdf" or (
                "pdf" in ct and link.get("intended-application") == "text-mining"
            ):
                pdf_link = link.get("URL")
                if pdf_link:
                    return pdf_link

    return None


# Mirror order matters: sci-hub.ru returns the freshest citation_pdf_url
# meta. sci-hub.st and sci-hub.box mirror the same storage backend.
# sci-hub.ren persistently returns 403 (probed 2026-05); dropped.
SCIHUB_MIRRORS = [
    "https://sci-hub.ru",
    "https://sci-hub.st",
    "https://sci-hub.box",
]


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

            def _fetch_page():
                req = urllib.request.Request(page_url, headers=HEADERS_BROWSER)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return resp.read(50000).decode("utf-8", errors="ignore")

            html = _retry(_fetch_page, label=f"sci-hub {mirror}")

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
            elif pdf_url.startswith("/"):
                pdf_url = mirror + pdf_url

            def _fetch_pdf():
                pdf_req = urllib.request.Request(pdf_url, headers=HEADERS_BROWSER)
                with urllib.request.urlopen(pdf_req, timeout=60) as pdf_resp:
                    return pdf_resp.read()

            data = _retry(_fetch_pdf, label=f"sci-hub PDF {mirror}")
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
    elif doi.startswith("10.1086/"):
        pdf_urls.append(f"https://www.journals.uchicago.edu/doi/pdf/{doi}")
        pdf_urls.append(f"https://www.journals.uchicago.edu/doi/pdf/{doi}?download=true")
    elif doi.startswith(("10.1002/", "10.1111/")):
        pdf_urls.append(f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}")
        pdf_urls.append(f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true")
    elif doi.startswith("10.1093/"):
        pdf_urls.append(f"https://academic.oup.com/doi/pdf/{doi}")
    elif doi.startswith("10.1162/"):
        pdf_urls.append(f"https://direct.mit.edu/doi/pdf/{doi}")
    elif doi.startswith("10.1080/"):
        pdf_urls.append(f"https://www.tandfonline.com/doi/pdf/{doi}")
        pdf_urls.append(f"https://www.tandfonline.com/doi/pdf/{doi}?download=true")
    elif doi.startswith("10.1177/"):
        pdf_urls.append(f"https://journals.sagepub.com/doi/pdf/{doi}")
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

        def _do():
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()

        data = _retry(_do, label=f"GET {url[:60]}")
        if _is_pdf_data(data):
            with open(output_path, "wb") as f:
                f.write(data)
            print(f"  OK {len(data) / 1024:.0f}KB -> {os.path.basename(output_path)}",
                  file=sys.stderr)
            return True
        # Check if this is an EZProxy login page
        lower_data = data[:2000].lower()
        if _url_matches_ezproxy(url, ezproxy) and (
            b"login" in lower_data or b"auth" in lower_data
            or b"ezproxy" in lower_data or b"shibboleth" in lower_data
        ):
            raise EZProxyCookieExpired(
                "EZProxy cookie expired — re-login in Chrome to let CookieCloud sync fresh cookies"
            )
        print(f"  SKIP not-a-pdf ({len(data)} bytes)", file=sys.stderr)
        return False
    except EZProxyCookieExpired:
        raise  # Re-raise, don't swallow
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"  FAIL {e}", file=sys.stderr)
        return False


_PUBLISHER_DIRECT_URLS = [
    ("10.1086/",  "https://www.journals.uchicago.edu/doi/pdf/{doi}"),
    ("10.1086/",  "https://www.journals.uchicago.edu/doi/pdf/{doi}?download=true"),
    ("10.1086/",  "https://www.journals.uchicago.edu/doi/pdfplus/{doi}"),
    ("10.1086/",  "https://www.journals.uchicago.edu/doi/pdfplus/{doi}?download=true"),
    ("10.1080/",  "https://www.tandfonline.com/doi/pdf/{doi}"),
    ("10.1080/",  "https://www.tandfonline.com/doi/pdf/{doi}?download=true"),
    ("10.1177/",  "https://journals.sagepub.com/doi/pdf/{doi}"),
    ("10.1093/",  "https://academic.oup.com/doi/pdf/{doi}"),
    ("10.1002/",  "https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}"),
    ("10.1002/",  "https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true"),
    ("10.1111/",  "https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}"),
    ("10.1111/",  "https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true"),
    ("10.1007/",  "https://link.springer.com/content/pdf/{doi}.pdf"),
    ("10.1038/",  "https://www.nature.com/articles/{suffix}.pdf"),
    ("10.1162/",  "https://direct.mit.edu/doi/pdf/{doi}"),
    ("10.1145/",  "https://dl.acm.org/doi/pdf/{doi}"),
    ("10.1353/",  "https://muse.jhu.edu/article/{suffix}"),
    ("10.1017/",  "https://www.cambridge.org/core/services/aop-cambridge-core/content/view/{doi}"),
    ("10.pubsonline.informs", "https://pubsonline.informs.org/doi/pdf/{doi}"),
]


def _try_publisher_direct(doi, output_path):
    """Try downloading PDF directly from publisher URL (no EZProxy).

    Some publishers allow PDF access from institutional IP ranges or for
    open-access articles without explicit proxy authentication.
    """
    if not doi:
        return False

    suffix = doi.split("/", 1)[-1] if "/" in doi else ""
    for prefix, pattern in _PUBLISHER_DIRECT_URLS:
        if doi.startswith(prefix):
            pdf_url = pattern.format(doi=doi, suffix=suffix)
            print(f"  Publisher direct: {pdf_url[:80]}", file=sys.stderr)
            try:
                def _do():
                    req = urllib.request.Request(pdf_url, headers=HEADERS_BROWSER)
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        return resp.read()

                data = _retry(_do, label=f"publisher-direct {prefix}")
                if _is_pdf_data(data):
                    with open(output_path, "wb") as f:
                        f.write(data)
                    print(
                        f"  Publisher direct OK {len(data) / 1024:.0f}KB -> "
                        f"{os.path.basename(output_path)}",
                        file=sys.stderr,
                    )
                    return True
                else:
                    print(f"  Publisher direct: not a PDF", file=sys.stderr)
            except (urllib.error.URLError, urllib.error.HTTPError,
                    TimeoutError, OSError) as e:
                print(f"  Publisher direct: {e}", file=sys.stderr)
    return False


_TITLE_STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "and", "or", "for", "to",
    "is", "are", "was", "with", "from", "by", "at", "as", "its",
    "this", "that", "how", "what", "why", "new", "between", "not",
})

_DOI_IN_URL_RE = re.compile(r"10\.\d{4,9}/[^\s&?#\"']+")


def _kagi_discover_paper(title, author=None):
    """Search Kagi for paper title; extract DOIs and publisher URLs.

    Returns (doi_candidates, url_candidates) — both lists of strings.
    Silently returns empty if kagi CLI is unavailable.
    """
    kagi_token = os.environ.get("QUASI_KAGI_SESSION_TOKEN")
    if not kagi_token:
        return [], []
    if not shutil.which("kagi"):
        return [], []

    query = title
    if author:
        surname = author.split()[-1] if author else ""
        if surname:
            query = f"{title} {surname}"

    env = dict(os.environ)
    env["KAGI_SESSION_TOKEN"] = kagi_token

    try:
        result = subprocess.run(
            ["kagi", "search", "--format", "json", query],
            capture_output=True, timeout=30, env=env,
        )
        if result.returncode != 0:
            print(f"  Kagi: exit {result.returncode}", file=sys.stderr)
            return [], []
        data = json.loads(result.stdout)
        items = data.get("data", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        print(f"  Kagi: {e}", file=sys.stderr)
        return [], []

    title_lower = title.lower()
    title_words = set(re.findall(r"[a-z]{3,}", title_lower)) - _TITLE_STOP_WORDS

    if not title_words:
        return [], []

    dois: list[str] = []
    urls: list[str] = []
    seen_dois: set[str] = set()

    for item in items:
        item_title = (item.get("title") or "").lower()
        item_url = item.get("url") or ""

        item_words = set(re.findall(r"[a-z]{3,}", item_title)) - _TITLE_STOP_WORDS
        if not item_words:
            continue
        overlap = len(title_words & item_words) / len(title_words)
        if overlap < 0.5:
            continue

        doi_match = _DOI_IN_URL_RE.search(item_url)
        if doi_match:
            found_doi = doi_match.group(0).rstrip(".")
            if found_doi not in seen_dois:
                seen_dois.add(found_doi)
                dois.append(found_doi)

        if item_url and item_url.startswith("http"):
            urls.append(item_url)

    if dois:
        print(f"  Kagi: discovered {len(dois)} DOI(s): {dois[:3]}", file=sys.stderr)
    if urls:
        print(f"  Kagi: discovered {len(urls)} URL(s)", file=sys.stderr)
    return dois, urls


def download_paper(doi=None, url=None, urls=None, output_dir="sources",
                   filename=None, retry_wayback=True,
                   verify_author=None, verify_title=None):
    """Download a paper PDF by DOI or URL. Returns file path or None.

    Cascade:
      Phase 1 (with provided identifiers):
        direct URLs → OA (Unpaywall/OpenAlex/S2/Crossref links)
        → Sci-Hub → Publisher Direct → EZProxy → Wayback
      Phase 2 (recovery — when Phase 1 fails and title available):
        Kagi discovery → retry with discovered DOIs/URLs

    If verify_author/verify_title are provided, each downloaded PDF is checked
    for content match. Mismatches are deleted and the cascade continues.
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

    def _verify_and_accept(path, source_name):
        """Verify downloaded file. Returns True if accepted, False if rejected."""
        if not verify_author and not verify_title:
            return True
        if verify_pdf_content(path, verify_author, verify_title):
            return True
        print(f"  {source_name}: content mismatch, deleting and trying next source",
              file=sys.stderr)
        if os.path.exists(path):
            os.remove(path)
        return False

    # Collect all hint URLs (deduplicated, order-preserving)
    hint_urls: list[str] = []
    _seen_urls: set[str] = set()
    for u in ([url] if url else []) + (urls or []):
        if u and u not in _seen_urls:
            _seen_urls.add(u)
            hint_urls.append(u)

    # --- Phase 1: provided identifiers ---

    # 1. Direct URLs (all hints)
    for hint_url in hint_urls:
        print(f"  Direct URL: {hint_url[:80]}", file=sys.stderr)
        try:
            if download_pdf_from_url(hint_url, dest) and _verify_and_accept(dest, "Direct"):
                return dest
        except EZProxyCookieExpired:
            print(f"  EZProxy cookie expired on hint URL, continuing...", file=sys.stderr)
        time.sleep(0.5)

    # 2. OA sources
    if doi:
        print(f"  Searching OA for {doi}...", file=sys.stderr)
        oa_url = find_oa_url(doi)
        if oa_url:
            print(f"  OA: {oa_url[:80]}", file=sys.stderr)
            if download_pdf_from_url(oa_url, dest) and _verify_and_accept(dest, "OA"):
                return dest
            time.sleep(0.5)

    # 3. Sci-Hub
    if doi:
        print(f"  Trying Sci-Hub for {doi}...", file=sys.stderr)
        if try_scihub_download(doi, dest) and _verify_and_accept(dest, "Sci-Hub"):
            return dest
        time.sleep(0.5)

    # 4. Publisher Direct (construct PDF URL from DOI, no proxy)
    if doi:
        print(f"  Trying publisher direct for {doi}...", file=sys.stderr)
        if _try_publisher_direct(doi, dest) and _verify_and_accept(dest, "Publisher Direct"):
            return dest
        time.sleep(0.5)

    # 5. EZProxy (institutional proxy)
    if doi:
        print(f"  Trying EZProxy for {doi}...", file=sys.stderr)
        try:
            if _try_ezproxy_with_refresh(doi, dest) and _verify_and_accept(dest, "EZProxy"):
                return dest
        except EZProxyCookieExpired:
            print(f"  EZProxy cookie expired, continuing...", file=sys.stderr)
        time.sleep(0.5)

    # 6. Wayback
    if doi and retry_wayback:
        print(f"  Searching Wayback for {doi}...", file=sys.stderr)
        wb_url = find_wayback_url(doi)
        if wb_url:
            print(f"  WB: {wb_url[:80]}", file=sys.stderr)
            if download_pdf_from_url(wb_url, dest, timeout=90) and _verify_and_accept(dest, "Wayback"):
                return dest

    # --- Phase 2: Kagi discovery recovery ---
    # When Phase 1 exhausted all sources, search Kagi by title to discover
    # alternative DOIs and publisher URLs, then retry the cascade with them.
    recovery_title = verify_title or filename
    if recovery_title:
        print(f"  Phase 1 exhausted. Trying Kagi discovery...", file=sys.stderr)
        kagi_dois, kagi_urls = _kagi_discover_paper(recovery_title, verify_author)

        # Try discovered URLs directly
        for kagi_url in kagi_urls:
            if kagi_url in _seen_urls:
                continue
            _seen_urls.add(kagi_url)
            print(f"  Kagi URL: {kagi_url[:80]}", file=sys.stderr)
            try:
                if download_pdf_from_url(kagi_url, dest) and _verify_and_accept(dest, "Kagi URL"):
                    return dest
            except EZProxyCookieExpired:
                pass
            time.sleep(0.5)

        # Try discovered DOIs (different from the original)
        for kagi_doi in kagi_dois:
            if kagi_doi == doi:
                continue
            print(f"  Kagi discovered DOI: {kagi_doi}", file=sys.stderr)

            # OA with new DOI
            oa_url = find_oa_url(kagi_doi)
            if oa_url:
                print(f"  Kagi OA: {oa_url[:80]}", file=sys.stderr)
                if download_pdf_from_url(oa_url, dest) and _verify_and_accept(dest, "Kagi OA"):
                    return dest
                time.sleep(0.5)

            # Sci-Hub with new DOI
            if try_scihub_download(kagi_doi, dest) and _verify_and_accept(dest, "Kagi Sci-Hub"):
                return dest
            time.sleep(0.5)

            # EZProxy with new DOI
            try:
                if _try_ezproxy_with_refresh(kagi_doi, dest) and _verify_and_accept(dest, "Kagi EZProxy"):
                    return dest
            except EZProxyCookieExpired:
                pass

    print(f"  Could not download paper", file=sys.stderr)
    return None


def _stream_download(url, dest_path, headers=None):
    """Stream-download file with progress. Retries the whole transfer on
    transient connection / 5xx errors (chunked stream restarts from byte 0).
    """

    def _do():
        r = requests.get(url, headers=headers or HEADERS_BROWSER,
                         stream=True, timeout=120)
        if r.status_code != 200:
            r.raise_for_status()  # routed through _retry's HTTP code check
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
        return True

    try:
        ok = _retry(_do, label=f"stream {os.path.basename(dest_path)}")
    except urllib.error.HTTPError as e:
        print(f"  Download failed: HTTP {e.code}", file=sys.stderr)
        return False
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", "?")
        print(f"  Download failed: HTTP {status}", file=sys.stderr)
        return False
    except (urllib.error.URLError, requests.RequestException, TimeoutError, OSError) as e:
        print(f"  Download failed: {e}", file=sys.stderr)
        return False

    if not ok:
        return False

    size = os.path.getsize(dest_path)
    if size < 10240:
        print(f"  Warning: file very small ({size} bytes), might not be valid", file=sys.stderr)
        return False

    return True


def _default_temp_dir() -> Path:
    return project_root() / ".quasi" / "temp" / "downloads"


def _download_filename(slug: str, token: str | None = None) -> str:
    if token:
        token = re.sub(r"[^a-zA-Z0-9]+", "", token)[:12]
    return f"{slug}-{token}" if token else slug


def _inspect_downloaded_file(path: Path) -> dict:
    """Return lightweight diagnostics for the downloaded file.

    This is intentionally internal. Fetch always includes these diagnostics, so
    agents should not call a separate inspect command for the same file.
    """

    suffix = path.suffix.lower().lstrip(".") or "unknown"
    front_text = ""
    if suffix == "pdf":
        front_text = _extract_pdf_text(str(path), max_pages=4, allow_raw_fallback=False)
    elif suffix == "epub":
        front_text = _extract_epub_text(path, max_items=4)

    clean_text = (front_text or "").strip()
    if len(clean_text) >= 80:
        readability = "text"
    elif clean_text:
        readability = "weak_text"
    else:
        readability = "unreadable"

    return {
        "format": suffix,
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "readability": readability,
        "front_text": clean_text[:6000] if clean_text else None,
        "year_signals": _extract_year_signals(clean_text) if clean_text else None,
        "fallback_hint": (
            None if readability == "text"
            else "diagnostics are weak; use Read/pdftotext or inspect the first pages manually"
        ),
    }


# ============================================================
# CLI
# ============================================================

def _handle_errors(fn, *args, **kwargs):
    """Run fn, translate domain exceptions to exit codes consistently."""
    try:
        return fn(*args, **kwargs)
    except AAQuotaExhausted as e:
        print(f"\n*** AA QUOTA EXHAUSTED ***", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print(f"  Stop all book downloads and wait for quota reset.", file=sys.stderr)
        sys.exit(2)
    except EZProxyCookieExpired as e:
        print(f"\n*** EZPROXY COOKIE EXPIRED ***", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print(f"  Open any paywalled article in Chrome → SSO → 2FA.", file=sys.stderr)
        print(f"  CookieCloud extension will sync the new cookie automatically.", file=sys.stderr)
        print(f"  Stop all paper downloads until that's done.", file=sys.stderr)
        sys.exit(3)


# ---- subcommand handlers ---------------------------------------------------

def _cmd_book_candidates(args) -> int:
    query = args.query or " ".join(
        part for part in (args.title, args.author, str(args.year or "")) if part
    ).strip()
    if not query:
        print("book candidates: need --query or --title/--author", file=sys.stderr)
        return 2
    result = search_aa(query, fmt=args.format, lang=args.lang, limit=args.limit)
    print_json({
        "status": "ok" if result.get("success") else "failed",
        "kind": "book",
        "query": query,
        "source": result.get("source", "anna_archive"),
        "count": result.get("count", 0),
        "candidates": result.get("results", []),
    })
    return 0 if result.get("success") else 1


def _cmd_book_fetch(args) -> int:
    if not args.md5:
        print("book fetch: need --md5", file=sys.stderr)
        return 2
    if not args.slug:
        print("book fetch: need --slug", file=sys.stderr)
        return 2

    temp_dir = resolve_project_path(args.temp_dir or _default_temp_dir())
    filename = _download_filename(args.slug, args.md5)
    path = _handle_errors(
        download_from_aa,
        md5=args.md5,
        output_dir=str(temp_dir),
        filename=filename,
        fmt=args.format,
    )
    if not path:
        print_json({
            "status": "download_failed",
            "kind": "book",
            "md5": args.md5,
            "reason": "all_sources_failed",
        })
        return 1

    path_obj = Path(path).resolve()
    print_json({
        "status": "ok",
        "kind": "book",
        "md5": args.md5,
        "temp_path": str(path_obj),
        "source": "anna_archive",
        "inspect": _inspect_downloaded_file(path_obj),
    })
    return 0


def _cmd_paper_fetch(args) -> int:
    if not (args.doi or args.url):
        print("paper fetch: need --doi or --url", file=sys.stderr)
        return 2
    if not args.slug:
        print("paper fetch: need --slug", file=sys.stderr)
        return 2

    temp_dir = resolve_project_path(args.temp_dir or _default_temp_dir())
    all_urls = args.url or []
    result = _handle_errors(
        download_paper,
        doi=args.doi, urls=all_urls,
        output_dir=str(temp_dir), filename=args.slug,
        retry_wayback=True,
        verify_title=args.title, verify_author=args.author,
    )
    if result:
        path_obj = Path(result).resolve()
        print_json({
            "status": "ok",
            "kind": "paper",
            "doi": args.doi,
            "urls": all_urls,
            "temp_path": str(path_obj),
            "source": "doi_cascade",
            "inspect": _inspect_downloaded_file(path_obj),
        })
        return 0
    print_json({
        "status": "download_failed",
        "kind": "paper",
        "doi": args.doi,
        "urls": all_urls,
        "reason": "all_sources_failed",
    })
    return 1


def _cmd_accept(args) -> int:
    if not args.path:
        print("accept: need --path", file=sys.stderr)
        return 2
    if not args.slug:
        print("accept: need --slug", file=sys.stderr)
        return 2

    src = resolve_project_path(args.path)
    if not src.exists() or not src.is_file():
        print_json({
            "status": "not_found",
            "path": str(src),
        })
        return 1

    out_dir = resolve_project_path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = (out_dir / f"{args.slug}{src.suffix.lower()}").resolve()

    if src == dest:
        print_json({
            "status": "ok",
            "kind": args.kind,
            "path": str(dest),
            "moved": False,
            "reason": "already_at_destination",
        })
        return 0

    if dest.exists() and not args.overwrite:
        print_json({
            "status": "conflict",
            "kind": args.kind,
            "path": str(dest),
            "temp_path": str(src),
            "reason": "destination_exists",
        })
        return 1

    if dest.exists() and args.overwrite:
        dest.unlink()
    shutil.move(str(src), str(dest))
    print_json({
        "status": "ok",
        "kind": args.kind,
        "path": str(dest),
        "temp_path": str(src),
        "moved": True,
    })
    return 0


# ---- argparse: subcommand structure ----------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quasi-download",
        description="Academic file acquisition for agents.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # book: candidates + fetch.
    p_book = sub.add_parser("book", help="Book acquisition")
    book_sub = p_book.add_subparsers(dest="book_cmd", required=True)

    p_bc = book_sub.add_parser("candidates", help="Find downloadable book candidates")
    p_bc.add_argument("--query", help="Raw AA query")
    p_bc.add_argument("--title", help="Expected title")
    p_bc.add_argument("--author", help="Expected author")
    p_bc.add_argument("--year", type=int, help="Optional year hint")
    p_bc.add_argument("--format", "-f", default="pdf", help="File format (default: pdf)")
    p_bc.add_argument("--lang", help="Language filter, e.g. en")
    p_bc.add_argument("--limit", type=int, default=5)
    p_bc.add_argument("--json", action="store_true", help="Accepted for contract clarity; output is always JSON")
    p_bc.set_defaults(func=_cmd_book_candidates)

    p_bf = book_sub.add_parser("fetch", help="Download one book candidate to temp and diagnose")
    p_bf.add_argument("--md5", required=True, help="Anna's Archive file MD5")
    p_bf.add_argument("--slug", required=True, help="Target work slug for temp filename")
    p_bf.add_argument("--format", "-f", default="pdf", help="File format (default: pdf)")
    p_bf.add_argument("--temp-dir", default=str(_default_temp_dir()),
                      help="Temp output directory (default: .quasi/temp/downloads)")
    p_bf.add_argument("--json", action="store_true", help="Accepted for contract clarity; output is always JSON")
    p_bf.set_defaults(func=_cmd_book_fetch)

    # paper: DOI/URL fetch.
    p_paper = sub.add_parser("paper", help="Paper acquisition")
    paper_sub = p_paper.add_subparsers(dest="paper_cmd", required=True)

    p_pf = paper_sub.add_parser("fetch", help="Download a paper to temp and diagnose")
    p_pf.add_argument("--doi", help="Paper DOI")
    p_pf.add_argument("--url", action="append", help="Direct PDF URL (repeatable)")
    p_pf.add_argument("--title", help="Paper title (enables Kagi recovery)")
    p_pf.add_argument("--author", help="Paper author (improves Kagi recovery)")
    p_pf.add_argument("--slug", required=True, help="Target work slug for temp filename")
    p_pf.add_argument("--retry-wayback", action="store_true",
                      help=argparse.SUPPRESS)  # no-op since cascade always tries Wayback
    p_pf.add_argument("--temp-dir", default=str(_default_temp_dir()),
                      help="Temp output directory (default: .quasi/temp/downloads)")
    p_pf.add_argument("--json", action="store_true", help="Accepted for contract clarity; output is always JSON")
    p_pf.set_defaults(func=_cmd_paper_fetch)

    # accept: move judged temp file into stable sources/{slug}.{ext}.
    p_accept = sub.add_parser("accept", help="Move accepted temp file into sources/{slug}.{ext}")
    p_accept.add_argument("--path", required=True, help="Temp file path returned by fetch")
    p_accept.add_argument("--slug", required=True, help="Final artifact slug")
    p_accept.add_argument("--kind", choices=("book", "paper"), default="book")
    p_accept.add_argument("--output-dir", "-o", default="sources",
                          help="Final output directory (default: sources)")
    p_accept.add_argument("--overwrite", action="store_true")
    p_accept.add_argument("--json", action="store_true", help="Accepted for contract clarity; output is always JSON")
    p_accept.set_defaults(func=_cmd_accept)

    return parser


def main():
    argv = sys.argv[1:]
    parser = _build_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

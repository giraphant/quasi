#!/usr/bin/env python3
"""Unified academic file download — acquisition CLI for agents.

Agent-facing public flow:
    book candidates  -> candidate metadata from Anna's Archive file search
    book fetch       -> download by MD5 to temp + automatic diagnostics
    paper fetch      -> DOI/URL cascade to temp + automatic diagnostics
    paper diagnose   -> one read-only direct or EZProxy access observation
    accept           -> move accepted temp file into sources/{slug}.{ext}

Usage:
    python3 download.py book candidates --title "..." --author "..." --json
    python3 download.py book fetch --md5 abc123 --slug poggi-durkheim --json
    python3 download.py paper fetch --doi "10.x/y" --slug author-title-2024 --json
    python3 download.py paper diagnose --url "https://example.org/article" --json
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
from contextlib import contextmanager
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT))

import requests
from aa import aa_request, get_aa_base_url, load_aa_config, search_aa  # noqa: E402
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
EZPROXY_MIN_INTERVAL = 30  # seconds; global min gap between EZProxy attempts

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


def _quasi_data_dir() -> Path:
    """User-global plugin data dir (matches the bin/quasi-download shim)."""
    return Path(
        os.environ.get("CLAUDE_PLUGIN_DATA")
        or os.path.expanduser("~/.cache/quasi")
    )


def _ezproxy_state_path() -> Path:
    return _quasi_data_dir() / "ezproxy-throttle.state"


def _ezproxy_throttle(state_path=None, interval=None, now=None, sleep=None):
    """Block until >= interval has elapsed since the last EZProxy attempt
    (globally, across all quasi-download processes), then record this attempt.

    Holds an exclusive flock on a user-global state file across the wait, so
    competing processes serialize one interval apart. No-op when interval <= 0
    or fcntl is unavailable. Parameters are injectable for tests; production
    callers pass nothing. Returns seconds waited.
    """
    interval = EZPROXY_MIN_INTERVAL if interval is None else interval
    if interval <= 0:
        return 0.0
    try:
        import fcntl
    except ImportError:
        return 0.0
    now = now or time.time
    sleep = sleep or time.sleep
    sp = Path(state_path) if state_path else _ezproxy_state_path()
    sp.parent.mkdir(parents=True, exist_ok=True)

    waited = 0.0
    with open(sp, "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # blocks -> serializes processes
        try:
            f.seek(0)
            raw = f.read().strip()
            try:
                last = float(raw) if raw else 0.0
            except ValueError:
                last = 0.0
            wait = interval - (now() - last)
            wait = min(interval, wait)  # cap vs corrupted/future timestamp
            if wait > 0:
                print(
                    f"  EZProxy: global rate gate, waiting {wait:.1f}s",
                    file=sys.stderr,
                )
                sleep(wait)
                waited = wait
            f.seek(0)
            f.truncate()
            f.write(str(now()))
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return waited


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


def _with_ezproxy_refresh(attempt):
    """Run one EZProxy attempt; on expiry, invalidate cache + retry once.

    Clears the in-memory CookieCloud cache so the next call re-pulls fresh
    cookies from the server. Re-raises EZProxyCookieExpired if the refreshed
    cookies are also rejected (Chrome side likely hasn't re-logged in yet).
    """
    try:
        return attempt()
    except EZProxyCookieExpired:
        try:
            from cookiecloud import invalidate_cache, get_ezproxy_config
        except ImportError:
            from .cookiecloud import invalidate_cache, get_ezproxy_config  # type: ignore
        invalidate_cache()
        if get_ezproxy_config():
            print(f"  EZProxy: refreshed via CookieCloud, retrying...", file=sys.stderr)
            return attempt()
        raise


def _try_ezproxy_with_refresh(doi, output_path, sciencedirect_urls=None,
                              cell_pdf_urls=None, text_fallback_path=None,
                              expected_author=None, expected_title=None):
    """Try the DOI EZProxy download, refreshing expired cookies once."""
    return _with_ezproxy_refresh(lambda: try_ezproxy_download(
        doi,
        output_path,
        sciencedirect_urls=sciencedirect_urls,
        cell_pdf_urls=cell_pdf_urls,
        text_fallback_path=text_fallback_path,
        expected_author=expected_author,
        expected_title=expected_title,
    ))


def _try_ezproxy_urls_with_refresh(urls, output_path, text_fallback_path=None,
                                   expected_author=None, expected_title=None):
    """Try the URL EZProxy download, refreshing expired cookies once."""
    return _with_ezproxy_refresh(lambda: try_ezproxy_url_download(
        urls,
        output_path,
        text_fallback_path=text_fallback_path,
        expected_author=expected_author,
        expected_title=expected_title,
    ))


def _host_matches_domain(host: str, domain: str) -> bool:
    host = host.lower().strip(".")
    domain = domain.lower().lstrip(".")
    return host == domain or host.endswith(f".{domain}")


def _url_matches_ezproxy(url, ezproxy_config):
    """Check if a URL belongs to the EZProxy domain."""
    if not ezproxy_config:
        return False
    host = urllib.parse.urlparse(url).hostname or ""
    domain = ezproxy_config.get("domain", "")
    if domain and _host_matches_domain(host, domain):
        return True
    for rec in ezproxy_config.get("cookie_records", []):
        if _host_matches_domain(host, rec.get("domain", "")):
            return True
    return False


_EZPROXY_SERVICE_LABELS = ("login", "ezproxy", "proxy")


def _ezproxy_host_suffix(ezproxy_config) -> str:
    """Return the EZProxy hostname-rewriting suffix, e.g. `eux.idm.oclc.org`.

    Prefers the suffix the user's own proxied cookies were issued on, since
    that is observed fact, and falls back to the login host minus its service
    label, which is the OCLC-hosted convention.
    """
    counts: dict[str, int] = {}
    for rec in ezproxy_config.get("cookie_records", []):
        domain = (rec.get("domain") or "").lstrip(".").lower()
        first_label, _, suffix = domain.partition(".")
        if "-" in first_label and "." in suffix:
            counts[suffix] = counts.get(suffix, 0) + 1
    if counts:
        return max(counts, key=lambda suffix: (counts[suffix], -len(suffix)))

    login_host = (
        urllib.parse.urlparse(ezproxy_config.get("login_url", "")).hostname or ""
    ).lower()
    first_label, _, suffix = login_host.partition(".")
    if first_label in _EZPROXY_SERVICE_LABELS and "." in suffix:
        return suffix
    return login_host


def _ezproxy_request_urls(candidate_url, ezproxy_config) -> list[str]:
    """Return the proxy request forms for one candidate URL, best first.

    EZProxy rewrites hostnames (`www.jstor.org` -> `www-jstor-org.<suffix>`)
    and the institutional session cookies ride on those rewritten hosts. The
    `login?url=` form instead needs a live session on the login host itself,
    which a CookieCloud pull does not always carry — a browser that is happily
    reading JSTOR through the proxy can have no login-host cookie at all. So
    the rewritten host is tried first and the login redirect is the fallback.
    """
    if _url_matches_ezproxy(candidate_url, ezproxy_config):
        return [candidate_url]

    parsed = urllib.parse.urlparse(candidate_url)
    host = (parsed.hostname or "").lower()
    suffix = _ezproxy_host_suffix(ezproxy_config)
    forms = []
    if host and suffix and not _host_matches_domain(host, suffix):
        forms.append(urllib.parse.urlunparse((
            parsed.scheme or "https",
            f"{host.replace('.', '-')}.{suffix}",
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )))
    forms.append(f"{ezproxy_config['login_url']}{candidate_url}")
    return forms


def _ezproxy_cookie_header(ezproxy_config, url):
    host = urllib.parse.urlparse(url).hostname or ""
    parts = []
    for rec in ezproxy_config.get("cookie_records", []):
        if _host_matches_domain(host, rec.get("domain", "")):
            parts.append(f"{rec['name']}={rec['value']}")
    if parts:
        return "; ".join(parts)
    if "cookies" in ezproxy_config:
        return "; ".join(
            f"{name}={value}" for name, value in ezproxy_config["cookies"].items()
        )
    cookie_name = ezproxy_config.get("cookie_name", "ezproxy")
    return f"{cookie_name}={ezproxy_config['cookie']}"


def _header_value(headers, name: str) -> str:
    if not headers:
        return ""
    try:
        return headers.get(name, "") or headers.get(name.lower(), "") or ""
    except AttributeError:
        return ""


def _is_cloudflare_challenge(content, headers=None) -> bool:
    lower_html = content[:10000].lower()
    server = _header_value(headers, "server").lower()
    return (
        "cloudflare" in server
        or bool(_header_value(headers, "cf-ray"))
        or b"just a moment" in lower_html
        or b"cf-chl" in lower_html
        or b"challenge-platform" in lower_html
    )


def _is_pdf_response(content, headers=None) -> bool:
    content_type = _header_value(headers, "content-type").lower()
    return "application/pdf" in content_type or _is_pdf_data(content)


def _looks_like_shibboleth_login(content) -> bool:
    lower_html = content[:20000].lower()
    return (
        b"shibboleth authentication request" in lower_html
        or (
            b"shibboleth" in lower_html
            and (b"login" in lower_html or b"password" in lower_html or b"saml" in lower_html)
        )
    )


_DIAGNOSE_BODY_LIMIT = 20_000


def _sanitise_diagnostic_url(url: str | None) -> str | None:
    """Keep only scheme, host, port, and path for diagnostic output."""
    if not url:
        return None
    parsed = urllib.parse.urlparse(str(url))
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = parsed.hostname.lower()
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urllib.parse.urlunparse((
        parsed.scheme.lower(),
        netloc,
        parsed.path or "/",
        "",
        "",
        "",
    ))


def _diagnostic_content_type(headers) -> str | None:
    content_type = _header_value(headers, "content-type").split(";", 1)[0].strip().lower()
    if not content_type or not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", content_type):
        return None
    return content_type


def _classify_diagnostic_response(content, headers, status, final_url, login_url=None) -> str:
    if _is_cloudflare_challenge(content, headers):
        return "cloudflare_challenge"
    if _looks_like_shibboleth_login(content):
        return "shibboleth_login"
    if login_url:
        login_host = urllib.parse.urlparse(login_url).hostname or ""
        final_host = urllib.parse.urlparse(final_url or "").hostname or ""
        if login_host and final_host.lower() == login_host.lower():
            return "ezproxy_login"
    if _is_pdf_response(content, headers):
        return "pdf"
    if status in {401, 403, 451}:
        return "access_denied"
    content_type = _diagnostic_content_type(headers)
    if content_type == "text/html" or content.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        return "html_landing"
    return "other"


def _diagnostic_ezproxy_scope() -> dict | None:
    """Read only the configured proxy domain; never fetch CookieCloud for direct probes."""
    domain = os.environ.get("QUASI_COOKIECLOUD_EZPROXY_DOMAIN", "").strip()
    return {"domain": domain} if domain else None


def _valid_diagnostic_url(url: str) -> bool:
    """Accept only ordinary HTTP(S) URLs and never send userinfo to a server."""
    if not isinstance(url, str) or not url or any(char.isspace() for char in url):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _diagnostic_report(*, requested_url, final_url, mode, status, headers, content,
                       config, ezproxy_scope, proxy_attempted, transport_error=False,
                       unavailable=False) -> dict:
    target_matches_proxy = bool(
        ezproxy_scope and _url_matches_ezproxy(requested_url, ezproxy_scope)
    )
    if unavailable:
        classification = "ezproxy_unavailable"
    elif transport_error:
        classification = "connection_error"
    else:
        classification = _classify_diagnostic_response(
            content,
            headers,
            status,
            final_url,
            config.get("login_url") if config else None,
        )
    return {
        "schema_version": "quasi.download.diagnose/0.1",
        "requested_url": _sanitise_diagnostic_url(requested_url),
        "final_url": _sanitise_diagnostic_url(final_url),
        "mode": mode,
        "http_status": status,
        "content_type": _diagnostic_content_type(headers),
        "classification": classification,
        "retryable": bool(
            transport_error or status in _RETRYABLE_HTTP_CODES
        ) and not unavailable,
        "ezproxy": {
            "configured": bool(ezproxy_scope),
            "target_matches_proxy": target_matches_proxy,
            "attempted": proxy_attempted,
        },
        "wrote_file": False,
    }


def _read_diagnostic_error_body(exc) -> bytes:
    try:
        return exc.read(_DIAGNOSE_BODY_LIMIT)
    except (AttributeError, OSError, ValueError):
        return b""


def _read_diagnostic_response_body(response) -> bytes:
    """Read only a bounded, decoded response prefix from a streamed response."""
    iterator = getattr(response, "iter_content", None)
    if callable(iterator):
        chunks = []
        remaining = _DIAGNOSE_BODY_LIMIT
        try:
            for chunk in iterator(chunk_size=min(8192, remaining)):
                if not chunk:
                    continue
                chunk = bytes(chunk)
                limited = chunk[:remaining]
                chunks.append(limited)
                remaining -= len(limited)
                if remaining <= 0:
                    break
        except (OSError, requests.RequestException, ValueError):
            return b"".join(chunks)
        return b"".join(chunks)

    # Real requests responses provide iter_content(); this fallback keeps the
    # helper compatible with small response doubles used by callers/tests.
    content = getattr(response, "content", b"")
    return bytes(content[:_DIAGNOSE_BODY_LIMIT])


def _close_diagnostic_response(response) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def _diagnose_direct_url(url, ezproxy_scope, timeout):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "application/pdf,*/*",
    }
    request = urllib.request.Request(url, headers=headers)

    try:
        # Deliberately bypass _retry: one diagnostic invocation means one
        # target observation, including for transient response statuses.
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read(_DIAGNOSE_BODY_LIMIT)
            status = getattr(response, "status", None)
            if status is None:
                getcode = getattr(response, "getcode", None)
                status = getcode() if callable(getcode) else None
            return _diagnostic_report(
                requested_url=url,
                final_url=response.geturl(),
                mode="direct",
                status=status,
                headers=response.headers,
                content=content,
                config=None,
                ezproxy_scope=ezproxy_scope,
                proxy_attempted=False,
            )
    except urllib.error.HTTPError as exc:
        return _diagnostic_report(
            requested_url=url,
            final_url=exc.geturl(),
            mode="direct",
            status=exc.code,
            headers=exc.headers,
            content=_read_diagnostic_error_body(exc),
            config=None,
            ezproxy_scope=ezproxy_scope,
            proxy_attempted=False,
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        return _diagnostic_report(
            requested_url=url,
            final_url=None,
            mode="direct",
            status=None,
            headers=None,
            content=b"",
            config=None,
            ezproxy_scope=ezproxy_scope,
            proxy_attempted=False,
            transport_error=True,
        )


def _diagnose_ezproxy_url(url, config, ezproxy_scope, timeout):
    if not config or not config.get("login_url"):
        return _diagnostic_report(
            requested_url=url,
            final_url=None,
            mode="ezproxy",
            status=None,
            headers=None,
            content=b"",
            config=None,
            ezproxy_scope=ezproxy_scope,
            proxy_attempted=False,
            unavailable=True,
        )

    request_url = url if _url_matches_ezproxy(url, config) else f"{config['login_url']}{url}"
    session = _build_ezproxy_session(config)

    # A diagnostic is deliberately state-free: it does not create the shared
    # throttle-state file used to schedule writer-oriented acquisition.
    try:
        # As above, this is a single observation rather than a download retry.
        response = session.get(
            request_url,
            allow_redirects=True,
            timeout=timeout,
            stream=True,
        )
        try:
            return _diagnostic_report(
                requested_url=url,
                final_url=str(response.url),
                mode="ezproxy",
                status=response.status_code,
                headers=getattr(response, "headers", {}),
                content=_read_diagnostic_response_body(response),
                config=config,
                ezproxy_scope=ezproxy_scope,
                proxy_attempted=True,
            )
        finally:
            _close_diagnostic_response(response)
    except (requests.RequestException, TimeoutError, OSError):
        return _diagnostic_report(
            requested_url=url,
            final_url=None,
            mode="ezproxy",
            status=None,
            headers=None,
            content=b"",
            config=config,
            ezproxy_scope=ezproxy_scope,
            proxy_attempted=True,
            transport_error=True,
        )


def diagnose_paper_url(url, *, via_ezproxy=False, timeout=30) -> dict:
    """Observe one URL without writing a source or starting acquisition recovery."""
    if not _valid_diagnostic_url(url):
        raise ValueError("diagnostic URL must be an HTTP(S) URL without userinfo")
    ezproxy_scope = _diagnostic_ezproxy_scope()
    if via_ezproxy:
        config = load_ezproxy_config()
        return _diagnose_ezproxy_url(
            url,
            config,
            ezproxy_scope or config,
            timeout,
        )
    return _diagnose_direct_url(url, ezproxy_scope, timeout)


def _raise_if_ezproxy_login_page(final_url, login_url, content, history_len=0, headers=None):
    if _is_cloudflare_challenge(content, headers):
        return
    login_host = urllib.parse.urlparse(login_url).hostname or ""
    final_host = urllib.parse.urlparse(final_url).hostname or ""
    if login_host and final_host == login_host:
        raise EZProxyCookieExpired("EZProxy cookie not accepted — re-login in Chrome to let CookieCloud sync fresh cookies")
    if _looks_like_shibboleth_login(content):
        raise EZProxyCookieExpired("EZProxy cookie expired — re-login in Chrome to let CookieCloud sync fresh cookies")


# Publisher PDF URL patterns: given a proxied landing page URL,
# match publisher domain hint → construct direct PDF URL.
# Ported from /home/ramu/reeder/src/reeder/fulltext/ezproxy.py
# Keyed by publisher domain, matched through _is_publisher_host, so a proxied
# host needs no separate entry: `pubsonline-informs-org.<proxy>` decodes back
# to `pubsonline.informs.org` before matching. Subdomains match their parent,
# so `academic.oup.com` and `direct.mit.edu` need no entry of their own.
PUBLISHER_PDF_PATTERNS = [
    ("sagepub.com",          "/doi/pdf/{doi}"),
    ("oup.com",              "/doi/pdf/{doi}"),
    ("wiley.com",            "/doi/pdfdirect/{doi}"),
    ("wiley.com",            "/doi/pdfdirect/{doi}?download=true"),
    ("tandfonline.com",      "/doi/pdf/{doi}"),
    ("tandfonline.com",      "/doi/pdf/{doi}?download=true"),
    ("springer.com",         "/content/pdf/{doi}.pdf"),  # reeder uses /article/{doi}/fulltext.pdf
    ("nature.com",           "/content/pdf/{doi}.pdf"),
    ("uchicago.edu",         "/doi/pdf/{doi}"),
    ("uchicago.edu",         "/doi/pdf/{doi}?download=true"),
    ("uchicago.edu",         "/doi/pdfplus/{doi}"),
    ("uchicago.edu",         "/doi/pdfplus/{doi}?download=true"),
    ("mit.edu",              "/doi/pdf/{doi}"),
    ("pubsonline.informs.org", "/doi/pdf/{doi}"),
    ("annualreviews.org",    "/doi/pdf/{doi}"),
]

_EPDF_PUBLISHER_PATTERNS = [
    ("uchicago.edu", "/doi/epdf/{doi}"),
    ("tandfonline.com", "/doi/epdf/{doi}?needAccess=true"),
    ("wiley.com", "/doi/epdf/{doi}"),
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


def _unproxy_host(host: str) -> str:
    """Return the publisher host an EZProxy-rewritten host stands for.

    EZProxy encodes the whole publisher host in one label, dots as dashes:
    `journals.sagepub.com` -> `journals-sagepub-com.<proxy suffix>`. Decoding
    once here means every publisher test below is written against the real
    host, instead of each one hand-listing its own rewritten spellings.
    """
    host = host.lower().strip(".")
    first_label, _, proxy_suffix = host.partition(".")
    if "-" in first_label and _host_matches_domain(proxy_suffix, "oclc.org"):
        return first_label.replace("-", ".")
    return host


def _is_publisher_host(host: str, domain: str) -> bool:
    """Match a publisher domain directly or through EZProxy host rewriting."""
    host = _unproxy_host(host)
    domain = domain.lower().strip(".")
    return host == domain or host.endswith(f".{domain}")


def _is_sciencedirect_host(host: str) -> bool:
    return _is_publisher_host(host, "sciencedirect.com")


def _is_sciencedirect_article_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path.lower()
    return _is_sciencedirect_host(host) and (
        path.startswith("/science/article/pii/")
        or path.startswith("/science/article/abs/pii/")
    )


def _sciencedirect_pdf_urls_from_article_url(url: str) -> list[str]:
    if not _is_sciencedirect_article_url(url):
        return []
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.split("/")
    lowered = [part.lower() for part in parts]
    try:
        pii_index = lowered.index("pii") + 1
    except ValueError:
        return []
    if pii_index >= len(parts) or not parts[pii_index]:
        return []

    article_path = "/".join(parts[:pii_index + 1])
    candidates = [
        urllib.parse.urlunparse((
            parsed.scheme or "https",
            parsed.netloc,
            f"{article_path}/pdfft",
            "",
            "isDTMRedir=true&download=true",
            "",
        )),
        urllib.parse.urlunparse((
            parsed.scheme or "https",
            parsed.netloc,
            f"{article_path}/pdf",
            "",
            "",
            "",
        )),
    ]
    urls = []
    for candidate in candidates:
        if candidate not in urls:
            urls.append(candidate)
    return urls


def _is_cell_host(host: str) -> bool:
    return _is_publisher_host(host, "cell.com")


def _is_cell_url(url: str) -> bool:
    return _is_cell_host(urllib.parse.urlparse(url).hostname or "")


def _cell_pii_from_article_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if not _is_cell_host(host):
        return None

    parts = parsed.path.split("/")
    lowered = [part.lower() for part in parts]
    for segment in ("pdf", "fulltext", "abs"):
        if segment in lowered:
            segment_index = lowered.index(segment)
            if segment_index + 1 < len(parts) and parts[segment_index + 1]:
                return urllib.parse.unquote(parts[segment_index + 1]).removesuffix(".pdf")
    return None


def _normalise_cell_pii(pii: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", pii)


def _cell_pdf_urls_from_article_url(url: str) -> list[str]:
    """Return likely Cell Press PDF URLs for a cell.com article URL."""
    pii = _cell_pii_from_article_url(url)
    if not pii:
        return []

    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.split("/")
    lowered = [part.lower() for part in parts]
    segment_index = next(
        lowered.index(segment)
        for segment in ("pdf", "fulltext", "abs")
        if segment in lowered
    )

    pdf_parts = list(parts)
    pdf_parts[segment_index] = "pdf"
    pdf_parts[segment_index + 1] = f"{urllib.parse.quote(pii, safe='')}.pdf"

    base_pdf = urllib.parse.urlunparse((
        parsed.scheme or "https",
        parsed.netloc,
        "/".join(pdf_parts),
        "",
        "",
        "",
    ))

    show_pdf = urllib.parse.urlunparse((
        parsed.scheme or "https",
        parsed.netloc,
        "/action/showPdf",
        "",
        "pii=" + urllib.parse.quote(pii, safe=""),
        "",
    ))

    urls = []
    for candidate in (show_pdf, base_pdf):
        if candidate not in urls:
            urls.append(candidate)
    return urls


def _cell_pdf_urls_from_pii(pii: str) -> list[str]:
    if not pii:
        return []
    return [
        "https://www.cell.com/action/showPdf?pii="
        + urllib.parse.quote(pii, safe="")
    ]


def _cell_sciencedirect_urls_from_pii(pii: str) -> list[str]:
    pii = _normalise_cell_pii(pii)
    if not pii:
        return []
    return [
        f"https://www.sciencedirect.com/science/article/pii/{pii}",
        f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true",
    ]


def _cell_pdf_urls_from_doi(doi: str) -> list[str]:
    if not doi or not doi.startswith("10.1016/"):
        return []
    pii = doi.split("/", 1)[1]
    pii = re.sub(r"^j\.[^.]+\.", "", pii)
    if not pii.upper().startswith("S"):
        return []
    return _cell_pdf_urls_from_pii(pii)


def _is_cell_article_url(url: str) -> bool:
    return bool(_cell_pdf_urls_from_article_url(url))


def _is_jstor_host(host: str) -> bool:
    return _is_publisher_host(host, "jstor.org")


_JSTOR_STABLE_PATH_RE = re.compile(
    r"^/stable/(?:pdf/|info/)?(.+?)(?:\.pdf)?/?$", re.IGNORECASE
)


def _jstor_stable_id_from_url(url: str) -> str | None:
    """Return the JSTOR stable id for a stable/info/pdf URL, else None.

    Accepts both id forms JSTOR mints — a bare sequence number and a DOI —
    on the public host or on an EZProxy-rewritten one.
    """
    parsed = urllib.parse.urlparse(url)
    if not _is_jstor_host(parsed.hostname or ""):
        return None

    match = _JSTOR_STABLE_PATH_RE.match(parsed.path)
    if not match:
        return None

    stable_id = urllib.parse.unquote(match.group(1)).strip()
    if not stable_id:
        return None
    if "/" in stable_id and not re.match(r"^10\.\d{4,9}/", stable_id):
        return None
    return stable_id


def _jstor_pdf_urls_from_article_url(url: str) -> list[str]:
    """Return the JSTOR PDF URL for a stable article URL, on the same host.

    `acceptTC=1` is load-bearing: without it JSTOR answers the PDF path with
    its terms-of-use interstitial HTML, which reads exactly like a paywall.
    Keeping the caller's netloc means an already-proxied hint stays proxied.
    """
    stable_id = _jstor_stable_id_from_url(url)
    if not stable_id:
        return []

    parsed = urllib.parse.urlparse(url)
    return [
        urllib.parse.urlunparse((
            parsed.scheme or "https",
            parsed.netloc,
            f"/stable/pdf/{urllib.parse.quote(stable_id, safe='./')}.pdf",
            "",
            "acceptTC=1",
            "",
        ))
    ]


def _doi_from_url_path(url: str) -> str | None:
    """Return the DOI a publisher URL carries in its own path, else None."""
    parsed = urllib.parse.urlparse(url)
    match = _DOI_IN_URL_RE.search(urllib.parse.unquote(parsed.path))
    if not match:
        return None
    return match.group(0).rstrip("/").removesuffix(".pdf")


def _publisher_pdf_urls_from_article_url(url: str) -> list[str]:
    """Derive PDF URLs for publishers whose landing URL carries its own DOI.

    Same host-preserving construction the EZProxy landing step performs with
    PUBLISHER_PDF_PATTERNS, reused here so a URL-only request reaches those
    publishers too — `tandfonline.com/doi/abs/10.1080/x` already states the
    DOI that the PDF path needs, with no separate resolution step.
    """
    doi = _doi_from_url_path(url)
    if not doi:
        return []

    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    base = f"{parsed.scheme or 'https'}://{parsed.netloc}"
    urls = []
    for publisher_hint, pattern in PUBLISHER_PDF_PATTERNS:
        if not _is_publisher_host(host, publisher_hint):
            continue
        candidate = base + pattern.format(doi=doi)
        if candidate != url and candidate not in urls:
            urls.append(candidate)
    return urls


def _pdf_urls_from_article_url(url: str) -> list[str]:
    """Every host-preserving URL -> PDF derivation, in one place.

    The cascade needs this answer at three points — caller hints, the EZProxy
    landing page, and Kagi recovery — and each used to carry its own partial
    list of publishers, so a platform added in one place stayed missing in the
    others. Adding a platform is now one entry in one table.
    """
    urls: list[str] = []
    for derive in (
        _cell_pdf_urls_from_article_url,
        _sciencedirect_pdf_urls_from_article_url,
        _jstor_pdf_urls_from_article_url,
        _publisher_pdf_urls_from_article_url,
    ):
        for candidate in derive(url or ""):
            if candidate not in urls:
                urls.append(candidate)
    return urls


def _is_article_html_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    if _is_cell_host(parsed.hostname or ""):
        return "/fulltext/" in path or "/abs/" in path
    if _is_sciencedirect_article_url(url):
        return "/pdfft" not in path and not path.rstrip("/").endswith("/pdf")
    return False


def _is_pdf_data(data):
    """Check if raw bytes look like a PDF."""
    return data[:5] == b"%PDF-" or (
        len(data) > 50000 and b"<html" not in data[:1000].lower()
    )


def _html_to_text(data) -> str:
    text = data.decode("utf-8", errors="ignore")
    text = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|section|article|header|footer|li|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _looks_like_article_text(text, expected_author=None, expected_title=None) -> bool:
    if len(text.strip()) < 500:
        return False
    if expected_title and not _verify_text_content(text, expected_author, expected_title):
        return False
    lower = text.lower()
    markers = [
        "abstract",
        "highlights",
        "references",
        "introduction",
        "keywords",
        "article info",
    ]
    return any(marker in lower for marker in markers)


def _write_text_fallback_from_html(data, output_path, *, headers=None,
                                   expected_author=None, expected_title=None,
                                   source_label="HTML"):
    if _is_pdf_response(data, headers):
        return False
    if _is_cloudflare_challenge(data, headers):
        print(f"  {source_label}: PUBLISHER_CLOUDFLARE_CHALLENGE", file=sys.stderr)
        return False
    if _looks_like_shibboleth_login(data):
        return False
    content_type = _header_value(headers, "content-type").lower()
    if content_type and not any(part in content_type for part in ("html", "text/plain", "text/html")):
        return False

    text = _html_to_text(data)
    if not _looks_like_article_text(text, expected_author, expected_title):
        print(f"  {source_label}: HTML not article-like", file=sys.stderr)
        return False
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
        f.write("\n")
    print(f"  {source_label}: saved text fallback -> {os.path.basename(output_path)}", file=sys.stderr)
    return True


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


_DOI_TEXT_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>)\]},;]+")


def _normalise_doi(doi: str) -> str:
    return doi.strip().lower().rstrip(".,;:!?'\")]}")


def _dois_in_text(text: str) -> set:
    return {_normalise_doi(match) for match in _DOI_TEXT_RE.findall(text)}


def _verify_text_content(text, expected_author=None, expected_title=None,
                         expected_doi=None):
    """Accept extracted source text only on one strong identity proof.

    Either the requested DOI is embedded in the text, or the full normalised
    title appears as a contiguous phrase with the author present. Keyword
    overlap alone is not identity: a same-subfield paper
    contains every title word and cites the expected author, which is exactly
    how a wrong PDF once cleared this check with `status: ok`.
    """
    if not expected_author and not expected_title:
        return True  # Nothing verifiable; DOI absence alone must not reject old scans

    if not text:
        print(f"  Verify: could not extract text, skipping check", file=sys.stderr)
        return True  # Can't verify, assume OK

    text = text.lower()

    if expected_doi:
        wanted_doi = _normalise_doi(expected_doi)
        if wanted_doi in _dois_in_text(text):
            print(f"  Verify: PASS (embedded DOI {wanted_doi})", file=sys.stderr)
            return True

    normalised_text = " ".join(re.findall(r"[a-z0-9]+", text))

    author_found = None
    if expected_author:
        author_lower = expected_author.lower().strip()
        parts = author_lower.split()
        surname = parts[-1] if parts else author_lower
        author_found = author_lower in text or (
            len(surname) >= 3
            and (surname in text or surname in normalised_text)
        )
        if not author_found:
            print(f"  Verify: author '{expected_author}' NOT found", file=sys.stderr)

    if expected_title:
        normalised_title = " ".join(re.findall(r"[a-z0-9]+", expected_title.lower()))
        if not (normalised_title and normalised_title in normalised_text):
            print(f"  Verify: title phrase not found — wrong paper?", file=sys.stderr)
            return False
        if author_found is False:
            print(f"  Verify: title present but author missing — wrong paper?",
                  file=sys.stderr)
            return False
        print(f"  Verify: PASS (title phrase" +
              (" + author" if author_found else "") + ")", file=sys.stderr)
        return True

    if author_found:
        print(f"  Verify: PASS (author only)", file=sys.stderr)
        return True
    return False


def verify_pdf_content(pdf_path, expected_author=None, expected_title=None,
                       expected_doi=None):
    """Verify downloaded PDF matches the expected paper identity.

    Extracts text from the first pages and applies the strong-identity
    contract of `_verify_text_content`.
    """
    text = _extract_pdf_text(pdf_path)
    return _verify_text_content(
        text,
        expected_author,
        expected_title,
        expected_doi=expected_doi,
    )


def verify_source_content(source_path, expected_author=None, expected_title=None,
                          expected_doi=None):
    """Verify downloaded source content, supporting text and PDF sources."""
    path = Path(source_path)
    if path.suffix.lower() == ".txt":
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        return _verify_text_content(
            text,
            expected_author,
            expected_title,
            expected_doi=expected_doi,
        )
    return verify_pdf_content(str(path), expected_author, expected_title,
                              expected_doi=expected_doi)


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

    cookie_records = config.get("cookie_records", [])
    if cookie_records:
        for rec in cookie_records:
            session.cookies.set(
                rec["name"],
                rec["value"],
                domain=rec["domain"],
                path=rec.get("path", "/"),
            )
        return session

    domain = config.get("domain", ".eux.idm.oclc.org")
    cookies = config.get("cookies", {})
    if cookies:
        for name, value in cookies.items():
            session.cookies.set(name, value, domain=domain)
    else:
        cookie_name = config.get("cookie_name", "ezproxy")
        session.cookies.set(cookie_name, config["cookie"], domain=domain)

    return session


def _ezproxy_fetch_candidate(session, config, candidate_url, output_path, label,
                             *, text_fallback_path=None, expected_author=None,
                             expected_title=None):
    """Fetch one candidate URL through the proxy; write output_path on a PDF.

    Returns True on a written PDF, the text path on an accepted text fallback,
    False otherwise. A URL already on the proxy host is requested as-is;
    anything else is wrapped in the EZProxy login redirect.
    """
    login_url = config["login_url"]
    for request_url in _ezproxy_request_urls(candidate_url, config):
        print(f"  EZProxy {label}: {request_url[:80]}", file=sys.stderr)
        try:
            pdf_resp = _retry(
                lambda: session.get(request_url, allow_redirects=True, timeout=60),
                label=f"EZProxy {label}",
            )
            data = pdf_resp.content
            response_headers = getattr(pdf_resp, "headers", {})
            _raise_if_ezproxy_login_page(str(pdf_resp.url), login_url, data, len(pdf_resp.history), response_headers)
            if _is_cloudflare_challenge(data, response_headers):
                print(f"  EZProxy {label}: PUBLISHER_CLOUDFLARE_CHALLENGE", file=sys.stderr)
                return False
            if _is_pdf_response(data, response_headers):
                with open(output_path, "wb") as f:
                    f.write(data)
                print(f"  OK {len(data) / 1024:.0f}KB -> {os.path.basename(output_path)}",
                      file=sys.stderr)
                return True

            meta_pdf = _extract_citation_pdf_url(data)
            if meta_pdf:
                if meta_pdf.startswith("/"):
                    parsed = urllib.parse.urlparse(str(pdf_resp.url))
                    meta_pdf = f"{parsed.scheme}://{parsed.netloc}{meta_pdf}"
                if meta_pdf != candidate_url:
                    return _ezproxy_fetch_candidate(
                        session, config, meta_pdf, output_path,
                        f"{label} citation_pdf_url",
                    )
            if text_fallback_path and _write_text_fallback_from_html(
                data,
                text_fallback_path,
                headers=response_headers,
                expected_author=expected_author,
                expected_title=expected_title,
                source_label=f"EZProxy {label}",
            ):
                return text_fallback_path
        except (requests.RequestException, TimeoutError, OSError):
            pass
    return False


def try_ezproxy_url_download(urls, output_path, text_fallback_path=None,
                             expected_author=None, expected_title=None):
    """Fetch caller-provided publisher URLs through EZProxy.

    The DOI cascade enters the proxy through `login?url=https://doi.org/{doi}`.
    A URL-only request has no such entry, so a gated landing page was only ever
    fetched unauthenticated no matter how good the institutional session was.
    One session and one throttle slot cover every candidate.

    Returns True / the text path on success, False otherwise.
    Raises EZProxyCookieExpired if the session is expired.
    """
    candidates = [u for u in (urls or []) if u]
    if not candidates:
        return False

    config = load_ezproxy_config()
    if not config:
        print("  EZProxy: not configured (CookieCloud env vars missing), skipping",
              file=sys.stderr)
        return False

    _ezproxy_throttle()  # global cross-process rate gate (QUA-50)
    session = _build_ezproxy_session(config)

    for candidate_url in candidates:
        result = _ezproxy_fetch_candidate(
            session, config, candidate_url, output_path, "URL hint",
            text_fallback_path=text_fallback_path if _is_article_html_url(candidate_url) else None,
            expected_author=expected_author,
            expected_title=expected_title,
        )
        if result:
            return result

    print(f"  EZProxy: no PDF found for {len(candidates)} URL hint(s)", file=sys.stderr)
    return False


def try_ezproxy_download(doi, output_path, sciencedirect_urls=None, cell_pdf_urls=None,
                         text_fallback_path=None, expected_author=None,
                         expected_title=None):
    """Download paper via EZProxy: login redirect → publisher PDF pattern → HTML scrape.

    Returns True on success (file written to output_path), False otherwise.
    Raises EZProxyCookieExpired if session is expired.
    """
    config = load_ezproxy_config()
    if not config:
        print("  EZProxy: not configured (CookieCloud env vars missing), skipping",
              file=sys.stderr)
        return False

    _ezproxy_throttle()  # global cross-process rate gate (QUA-50)

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
    _raise_if_ezproxy_login_page(final_url, login_url, landing_html, len(resp.history), getattr(resp, "headers", {}))

    if resp.status_code != 200:
        print(f"  EZProxy: HTTP {resp.status_code}", file=sys.stderr)
        return False

    print(f"  EZProxy landed: {final_url[:80]}", file=sys.stderr)
    if (
        sciencedirect_urls is not None
        and _is_sciencedirect_article_url(final_url)
        and final_url not in sciencedirect_urls
    ):
        sciencedirect_urls.append(final_url)

    def _try_ezproxy_candidate_url(candidate_url, label, allow_text_fallback=False):
        return _ezproxy_fetch_candidate(
            session, config, candidate_url, output_path, label,
            text_fallback_path=text_fallback_path if allow_text_fallback else None,
            expected_author=expected_author,
            expected_title=expected_title,
        )

    for cell_pdf_url in cell_pdf_urls or []:
        result = _try_ezproxy_candidate_url(cell_pdf_url, "Cell PDF")
        if result:
            return result

    for landing_pdf_url in _pdf_urls_from_article_url(final_url):
        result = _try_ezproxy_candidate_url(landing_pdf_url, "landing PDF")
        if result:
            return result

    for sd_url in sciencedirect_urls or []:
        result = _try_ezproxy_candidate_url(sd_url, "ScienceDirect hint", allow_text_fallback=True)
        if result:
            return result
        for sd_pdf_url in _pdf_urls_from_article_url(sd_url):
            result = _try_ezproxy_candidate_url(sd_pdf_url, "hint PDF")
            if result:
                return result

    # Step 2: Try known publisher PDF URL patterns
    final_host = urllib.parse.urlparse(final_url).hostname or ""
    for publisher_hint, pattern in PUBLISHER_PDF_PATTERNS:
        if _is_publisher_host(final_host, publisher_hint):
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
        if _is_publisher_host(final_host, publisher_hint):
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
        r = aa_request("GET", api_url, timeout=30)
    except Exception as e:
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
        if _stream_download(dl_url, dest, headers=HEADERS_BROWSER, requester=aa_request):
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
        if _stream_download(dl_url, dest, headers=HEADERS_BROWSER, requester=aa_request):
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


def _doi_from_cell_pii(pii: str) -> str | None:
    """Resolve an Elsevier/Cell PII to DOI via Crossref alternative-id."""
    normalised = _normalise_cell_pii(pii)
    if not normalised:
        return None
    url = (
        "https://api.crossref.org/works"
        f"?filter=alternative-id:{urllib.parse.quote(normalised, safe='')}"
        "&rows=1"
    )
    data = _get_json_urllib(url)
    for item in (data or {}).get("message", {}).get("items", []):
        doi = item.get("DOI")
        if doi:
            return doi
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
            pdf_link = link.get("URL")
            parsed_path = urllib.parse.urlparse(pdf_link or "").path.lower()
            is_cambridge_pdf_endpoint = (
                urllib.parse.urlparse(pdf_link or "").hostname == "www.cambridge.org"
                and "/core/services/aop-cambridge-core/content/view/" in parsed_path
            )
            if ct == "application/pdf" or (
                "pdf" in ct and link.get("intended-application") == "text-mining"
            ) or parsed_path.endswith(".pdf") or "/pdf" in parsed_path or is_cambridge_pdf_endpoint:
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
    pdf_urls.extend(_cell_pdf_urls_from_doi(doi))
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


def download_pdf_from_url(url, output_path, timeout=60, *, text_fallback_path=None,
                          expected_author=None, expected_title=None):
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
        matches_ezproxy = _url_matches_ezproxy(url, ezproxy)
        if matches_ezproxy:
            headers["Cookie"] = _ezproxy_cookie_header(ezproxy, url)

        def _do():
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), resp.geturl(), resp.headers

        data, final_url, response_headers = _retry(_do, label=f"GET {url[:60]}")
        if _is_pdf_response(data, response_headers):
            with open(output_path, "wb") as f:
                f.write(data)
            print(f"  OK {len(data) / 1024:.0f}KB -> {os.path.basename(output_path)}",
                  file=sys.stderr)
            return True
        if _is_cloudflare_challenge(data, response_headers):
            print("  PUBLISHER_CLOUDFLARE_CHALLENGE", file=sys.stderr)
            return False
        if matches_ezproxy:
            _raise_if_ezproxy_login_page(
                final_url,
                ezproxy.get("login_url", "") if ezproxy else "",
                data,
                headers=response_headers,
            )
        if _is_cell_url(final_url or url):
            meta_pdf = _extract_citation_pdf_url(data)
            if meta_pdf:
                if meta_pdf.startswith("/"):
                    parsed = urllib.parse.urlparse(final_url or url)
                    meta_pdf = f"{parsed.scheme}://{parsed.netloc}{meta_pdf}"
                if meta_pdf not in {url, final_url}:
                    print(f"  Cell citation_pdf_url: {meta_pdf[:80]}", file=sys.stderr)
                    return download_pdf_from_url(
                        meta_pdf,
                        output_path,
                        timeout=timeout,
                        text_fallback_path=text_fallback_path,
                        expected_author=expected_author,
                        expected_title=expected_title,
                    )
        if text_fallback_path and _write_text_fallback_from_html(
            data,
            text_fallback_path,
            headers=response_headers,
            expected_author=expected_author,
            expected_title=expected_title,
            source_label="Direct URL",
        ):
            return text_fallback_path
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
    ("10.1146/",  "https://www.annualreviews.org/doi/pdf/{doi}"),
    ("10.1353/",  "https://muse.jhu.edu/article/{suffix}"),
    ("10.1017/",  "https://www.cambridge.org/core/services/aop-cambridge-core/content/view/{doi}"),
    ("10.1287/", "https://pubsonline.informs.org/doi/pdf/{doi}"),
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

    If verify_author/verify_title are provided, every candidate — including a
    pre-existing temp file — must prove the requested identity (embedded DOI,
    or contiguous title phrase plus author).
    Mismatches are deleted and the cascade continues.
    """
    requested_doi = doi

    if filename:
        safe_name = filename
    elif doi:
        safe_name = doi.replace("/", "_").replace(".", "_")
    else:
        safe_name = "paper"

    os.makedirs(output_dir, exist_ok=True)
    dest = os.path.join(output_dir, f"{safe_name}.pdf")
    text_dest = os.path.join(output_dir, f"{safe_name}.txt")

    def _verify_and_accept(path, source_name):
        """Verify downloaded file. Returns True if accepted, False if rejected."""
        if not verify_author and not verify_title:
            return True
        if verify_source_content(path, verify_author, verify_title,
                                 expected_doi=requested_doi):
            return True
        print(f"  {source_name}: content mismatch, deleting and trying next source",
              file=sys.stderr)
        if os.path.exists(path):
            os.remove(path)
        return False

    # A leftover temp file is a candidate like any other, not proof: a prior
    # run may have parked a wrong-identity PDF here that its caller rejected.
    for existing in (dest, text_dest):
        if os.path.exists(existing) and os.path.getsize(existing) > 1000:
            if _verify_and_accept(existing, "Existing temp"):
                print(f"  EXISTS {existing}", file=sys.stderr)
                return existing

    sciencedirect_urls: list[str] = []

    cell_pdf_urls: list[str] = []
    article_html_urls: list[str] = []

    def _remember_sciencedirect_url(candidate_url: str | None):
        if candidate_url and _is_sciencedirect_article_url(candidate_url) and candidate_url not in sciencedirect_urls:
            sciencedirect_urls.append(candidate_url)

    def _remember_cell_pdf_url(candidate_url: str | None):
        if candidate_url and _is_cell_url(candidate_url) and candidate_url not in cell_pdf_urls:
            cell_pdf_urls.append(candidate_url)

    def _remember_article_html_url(candidate_url: str | None):
        if candidate_url and _is_article_html_url(candidate_url) and candidate_url not in article_html_urls:
            article_html_urls.append(candidate_url)

    # Collect all hint URLs (deduplicated, order-preserving)
    hint_urls: list[str] = []
    _seen_urls: set[str] = set()

    def _add_hint_url(candidate_url: str | None):
        if candidate_url and candidate_url not in _seen_urls:
            _seen_urls.add(candidate_url)
            hint_urls.append(candidate_url)

    seed_urls = ([url] if url else []) + (urls or [])
    # 10.2307 is JSTOR's own DOI prefix; the stable page is deterministic and
    # doi.org resolution adds nothing a DOI-only request can use.
    if doi and doi.startswith("10.2307/"):
        seed_urls.append(
            f"https://www.jstor.org/stable/{doi.split('/', 1)[1]}"
        )

    for u in seed_urls:
        _remember_article_html_url(u)
        _add_hint_url(u)
        for pdf_url in _pdf_urls_from_article_url(u or ""):
            _remember_cell_pdf_url(pdf_url)
            _add_hint_url(pdf_url)
        cell_pii = _cell_pii_from_article_url(u or "")
        if cell_pii:
            for sd_url in _cell_sciencedirect_urls_from_pii(cell_pii):
                _remember_article_html_url(sd_url)
                _add_hint_url(sd_url)

    # --- Phase 1: provided identifiers ---

    # 1. Direct URLs (all hints)
    for hint_url in hint_urls:
        _remember_sciencedirect_url(hint_url)
        print(f"  Direct URL: {hint_url[:80]}", file=sys.stderr)
        try:
            direct_result = download_pdf_from_url(
                hint_url,
                dest,
                text_fallback_path=(
                    text_dest
                    if _is_article_html_url(hint_url)
                    else None
                ),
                expected_author=verify_author,
                expected_title=verify_title,
            )
            if direct_result:
                direct_path = direct_result if isinstance(direct_result, str) else dest
                if _verify_and_accept(direct_path, "Direct"):
                    return direct_path
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

    if not doi:
        for hint_url in hint_urls:
            cell_pii = _cell_pii_from_article_url(hint_url)
            if not cell_pii:
                continue
            resolved_doi = _doi_from_cell_pii(cell_pii)
            if resolved_doi:
                doi = resolved_doi
                print(f"  Cell PII -> DOI: {doi}", file=sys.stderr)
                break

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
            ezproxy_result = _try_ezproxy_with_refresh(
                doi,
                dest,
                sciencedirect_urls=article_html_urls + sciencedirect_urls,
                cell_pdf_urls=cell_pdf_urls,
                text_fallback_path=text_dest,
                expected_author=verify_author,
                expected_title=verify_title,
            )
            if ezproxy_result:
                ezproxy_path = ezproxy_result if isinstance(ezproxy_result, str) else dest
                if _verify_and_accept(ezproxy_path, "EZProxy"):
                    return ezproxy_path
        except EZProxyCookieExpired:
            print(f"  EZProxy cookie expired, continuing...", file=sys.stderr)
        time.sleep(0.5)

    # 5b. EZProxy for the caller's own URLs — the only proxy entry a URL-only
    # request has, and the one that reaches hosts the DOI redirect never lands
    # on. Skip whatever step 5 already wrapped.
    already_proxied = (
        set(cell_pdf_urls) | set(article_html_urls) | set(sciencedirect_urls)
        if doi else set()
    )
    pending_proxy_urls = [u for u in hint_urls if u not in already_proxied]
    if pending_proxy_urls:
        print(f"  Trying EZProxy for {len(pending_proxy_urls)} URL hint(s)...",
              file=sys.stderr)
        try:
            url_proxy_result = _try_ezproxy_urls_with_refresh(
                pending_proxy_urls,
                dest,
                text_fallback_path=text_dest,
                expected_author=verify_author,
                expected_title=verify_title,
            )
            if url_proxy_result:
                url_proxy_path = (
                    url_proxy_result if isinstance(url_proxy_result, str) else dest
                )
                if _verify_and_accept(url_proxy_path, "EZProxy URL"):
                    return url_proxy_path
        except EZProxyCookieExpired:
            print(f"  EZProxy cookie expired on URL hints, continuing...", file=sys.stderr)
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
        kagi_proxy_urls: list[str] = []
        for kagi_url in kagi_urls:
            if kagi_url in _seen_urls:
                continue
            _seen_urls.add(kagi_url)
            kagi_proxy_urls.append(kagi_url)
            _remember_sciencedirect_url(kagi_url)
            print(f"  Kagi URL: {kagi_url[:80]}", file=sys.stderr)
            try:
                if download_pdf_from_url(kagi_url, dest) and _verify_and_accept(dest, "Kagi URL"):
                    return dest
            except EZProxyCookieExpired:
                pass
            time.sleep(0.5)

            for kagi_pdf_url in _pdf_urls_from_article_url(kagi_url):
                if kagi_pdf_url in _seen_urls:
                    continue
                _seen_urls.add(kagi_pdf_url)
                print(f"  Kagi PDF URL: {kagi_pdf_url[:80]}", file=sys.stderr)
                try:
                    if download_pdf_from_url(kagi_pdf_url, dest) and _verify_and_accept(dest, "Kagi PDF URL"):
                        return dest
                except EZProxyCookieExpired:
                    pass
                time.sleep(0.5)

            cell_pii = _cell_pii_from_article_url(kagi_url)
            if cell_pii:
                for sd_url in _cell_sciencedirect_urls_from_pii(cell_pii):
                    if sd_url in _seen_urls:
                        continue
                    _seen_urls.add(sd_url)
                    _remember_sciencedirect_url(sd_url)
                    print(f"  Kagi Cell ScienceDirect URL: {sd_url[:80]}", file=sys.stderr)
                    try:
                        if download_pdf_from_url(sd_url, dest) and _verify_and_accept(dest, "Kagi Cell ScienceDirect URL"):
                            return dest
                    except EZProxyCookieExpired:
                        pass
                    time.sleep(0.5)

        # Discovered URLs through the proxy: the hosts Kagi surfaces for a
        # paywalled paper (JSTOR, Springer, OUP) are exactly the ones a bare
        # fetch cannot reach, and the discovered-DOI branch below already
        # gets this retry.
        if kagi_proxy_urls:
            print(f"  Trying EZProxy for {len(kagi_proxy_urls)} Kagi URL(s)...",
                  file=sys.stderr)
            try:
                kagi_proxy_result = _try_ezproxy_urls_with_refresh(
                    kagi_proxy_urls,
                    dest,
                    text_fallback_path=text_dest,
                    expected_author=verify_author,
                    expected_title=verify_title,
                )
                if kagi_proxy_result:
                    kagi_proxy_path = (
                        kagi_proxy_result
                        if isinstance(kagi_proxy_result, str)
                        else dest
                    )
                    if _verify_and_accept(kagi_proxy_path, "Kagi EZProxy URL"):
                        return kagi_proxy_path
            except EZProxyCookieExpired:
                print(f"  EZProxy cookie expired on Kagi URLs, continuing...",
                      file=sys.stderr)
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

            # Publisher Direct with new DOI
            if _try_publisher_direct(kagi_doi, dest) and _verify_and_accept(dest, "Kagi Publisher Direct"):
                return dest
            time.sleep(0.5)

            # EZProxy with new DOI
            try:
                if _try_ezproxy_with_refresh(kagi_doi, dest, sciencedirect_urls=sciencedirect_urls) and _verify_and_accept(dest, "Kagi EZProxy"):
                    return dest
            except EZProxyCookieExpired:
                pass

    print(f"  Could not download paper", file=sys.stderr)
    return None


def _stream_download(url, dest_path, headers=None, requester=None):
    """Stream-download file with progress. Retries the whole transfer on
    transient connection / 5xx errors (chunked stream restarts from byte 0).
    """

    def _do():
        if requester:
            r = requester("GET", url, timeout=120, stream=True)
        else:
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
    elif suffix == "txt":
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                front_text = f.read(6000)
        except OSError:
            front_text = ""
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


def _cmd_paper_diagnose(args) -> int:
    if args.timeout <= 0:
        print("paper diagnose: --timeout must be positive", file=sys.stderr)
        return 2
    if not _valid_diagnostic_url(args.url):
        print(
            "paper diagnose: --url must be an HTTP(S) URL without userinfo",
            file=sys.stderr,
        )
        return 2
    print_json(diagnose_paper_url(
        args.url,
        via_ezproxy=args.via_ezproxy,
        timeout=args.timeout,
    ))
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


@contextmanager
def _accept_output_lock(destination: Path):
    """Serialize every writer targeting one accepted source path."""
    lock_path = destination.parent / f".{destination.name}.quasi-download.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover - supported plugin hosts are Unix
            raise RuntimeError("accept requires advisory file locking") from exc
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if "fcntl" in locals():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stage_accepted_file(source: Path, destination: Path) -> tuple[Path, str, int]:
    """Copy source bytes into a fsynced sibling stage and return its proof."""
    descriptor, raw_stage = tempfile.mkstemp(
        prefix=f"{destination.name}.quasi-stage-",
        dir=destination.parent,
    )
    stage = Path(raw_stage)
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            while True:
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                writer.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            os.fchmod(writer.fileno(), source.stat().st_mode & 0o777)
            writer.flush()
            os.fsync(writer.fileno())
        return stage, digest.hexdigest(), size
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        stage.unlink(missing_ok=True)
        raise


def _file_proof(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _accept_to_output(
    source: Path,
    destination: Path,
    *,
    kind: str,
    overwrite: bool,
) -> tuple[dict, int]:
    """Publish one accepted source without exposing an unlink/write window."""
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    published = False
    previous_output = destination.exists()
    stage: Path | None = None

    try:
        with _accept_output_lock(destination):
            # Re-observe both refs under the output lock; another accepter may
            # have settled this target while this caller was queued.
            previous_output = destination.exists()
            if source == destination:
                if not source.is_file():
                    return {
                        "status": "not_found",
                        "kind": kind,
                        "path": str(source),
                    }, 1
                sha256, size_bytes = _file_proof(destination)
                return {
                    "status": "ok",
                    "kind": kind,
                    "path": str(destination),
                    "moved": False,
                    "published": True,
                    "source_removed": False,
                    "sha256": sha256,
                    "size_bytes": size_bytes,
                    "reason": "already_at_destination",
                }, 0

            if not source.exists() or not source.is_file():
                return {
                    "status": "not_found",
                    "kind": kind,
                    "path": str(source),
                }, 1

            if previous_output and not overwrite:
                return {
                    "status": "conflict",
                    "kind": kind,
                    "path": str(destination),
                    "temp_path": str(source),
                    "reason": "destination_exists",
                }, 1

            stage, sha256, size_bytes = _stage_accepted_file(
                source,
                destination,
            )
            os.replace(stage, destination)
            stage = None
            published = True
            _fsync_directory(destination.parent)

            source_removed = False
            cleanup_error = None
            try:
                source.unlink()
                source_removed = True
                _fsync_directory(source.parent)
            except OSError as exc:
                # The accepted output is already durable. A leftover fenced
                # temp candidate is cleanup debt, not an uncertain writer.
                cleanup_error = f"{type(exc).__name__}: {exc}"

            payload = {
                "status": "ok",
                "kind": kind,
                "path": str(destination),
                "temp_path": str(source),
                "moved": source_removed,
                "published": True,
                "source_removed": source_removed,
                "sha256": sha256,
                "size_bytes": size_bytes,
            }
            if cleanup_error is not None:
                payload["cleanup_error"] = cleanup_error
            return payload, 0
    except (OSError, RuntimeError) as exc:
        if stage is not None:
            stage.unlink(missing_ok=True)
        payload = {
            "status": "blocked",
            "kind": kind,
            "path": str(destination),
            "temp_path": str(source),
            "reason": "accept_commit_failed",
            "error": f"{type(exc).__name__}: {exc}",
            "published": published,
            "previous_output_preserved": (
                not published and previous_output and destination.exists()
            ),
        }
        if published and destination.is_file():
            sha256, size_bytes = _file_proof(destination)
            payload.update({"sha256": sha256, "size_bytes": size_bytes})
        return payload, 1


def _cmd_accept(args) -> int:
    if not args.path:
        print("accept: need --path", file=sys.stderr)
        return 2
    if not args.slug:
        print("accept: need --slug", file=sys.stderr)
        return 2

    src = resolve_project_path(args.path)
    out_dir = resolve_project_path(args.output_dir)
    dest = (out_dir / f"{args.slug}{src.suffix.lower()}").resolve()
    payload, code = _accept_to_output(
        src,
        dest,
        kind=args.kind,
        overwrite=args.overwrite,
    )
    print_json(payload)
    return code


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

    p_pd = paper_sub.add_parser("diagnose", help="Observe one paper URL without downloading")
    p_pd.add_argument("--url", required=True, help="Paper URL to observe")
    p_pd.add_argument(
        "--via-ezproxy",
        action="store_true",
        help="Use the configured EZProxy session for this one observation",
    )
    p_pd.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    p_pd.add_argument("--json", action="store_true", help="Accepted for contract clarity; output is always JSON")
    p_pd.set_defaults(func=_cmd_paper_diagnose)

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

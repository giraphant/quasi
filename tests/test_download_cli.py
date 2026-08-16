from __future__ import annotations

import io
import json
import importlib.util
import urllib.error
import urllib.parse
import hashlib
import os
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD = PLUGIN_ROOT / "scripts" / "download" / "download.py"
COOKIECLOUD = PLUGIN_ROOT / "scripts" / "download" / "cookiecloud.py"
AA = PLUGIN_ROOT / "scripts" / "download" / "aa.py"
AA_BROWSER = PLUGIN_ROOT / "scripts" / "download" / "aa_browser.py"
AA_HOMEPAGE_HTML = """
<html><head><title>Anna's Archive</title></head>
<body><form action="/search"><input name="q"></form></body></html>
"""


def run_download(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DOWNLOAD), *args],
        cwd=PLUGIN_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_aa_mirror_defaults_follow_stable_runtime_contract():
    mod = _load_module(AA, "aa_mirrors_under_test")

    static_mirrors = mod.STATIC_AA_MIRRORS
    runtime_defaults = mod.DEFAULT_AA_MIRRORS
    assert static_mirrors
    assert len(static_mirrors) == len(set(static_mirrors))
    for url in static_mirrors:
        parsed = urllib.parse.urlsplit(url)
        assert parsed.scheme == "https"
        assert parsed.hostname and parsed.hostname.startswith("annas-archive.")
        assert parsed.hostname.removeprefix("annas-archive.")
    assert runtime_defaults == static_mirrors


def test_aa_wikipedia_infobox_mirror_parser_prefers_url_row():
    mod = _load_module(AA, "aa_wikipedia_parser_under_test")
    html = """
    <table class="infobox">
      <tr><th>Founded</th><td><a href="https://annas-archive.org/old">old</a></td></tr>
      <tr><th>URL</th><td>
        <a href="https://annas-archive.pk/">annas-archive.pk</a>
        <a href="https://annas-archive.gd/">annas-archive.gd</a>
        <a href="https://annas-archive.gl/">annas-archive.gl</a>
      </td></tr>
    </table>
    <a class="external" href="https://annas-archive.org/old">old</a>
    """

    assert mod._mirrors_from_wikipedia_html(html) == [
        "https://annas-archive.pk",
        "https://annas-archive.gd",
        "https://annas-archive.gl",
    ]


def test_aa_slow_partner_parser_preserves_dom_order_and_deduplicates_no_wait():
    mod = _load_module(AA, "aa_slow_partner_order_under_test")
    detail_url = "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef"
    page = """
    <main>
      <div><a href="/slow_download/id/0/5">Slow Partner Server #5</a>
        — no waitlist, but can be very slow</div>
      <div><a href="/slow_download/id/0/6">Slow Partner Server #6</a>
        — no waitlist, but can be very slow</div>
      <div><a href="/slow_download/id/0/5">Slow Partner Server #5</a>
        — no waitlist, duplicate</div>
    </main>
    """

    assert mod.parse_aa_slow_partner_urls(detail_url, page) == [
        "https://annas-archive.pk/slow_download/id/0/5",
        "https://annas-archive.pk/slow_download/id/0/6",
    ]


def test_aa_slow_partner_parser_excludes_waitlist_viewer_and_unsafe_urls():
    mod = _load_module(AA, "aa_slow_partner_filter_under_test")
    detail_url = "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef"
    page = """
    <main>
      <div><a href="/slow_download/id/0/1">Slow Partner Server #1</a>
        — waitlist, but faster</div>
      <div><a href="https://user:secret@example.org/slow_download/id/0/2">Slow Partner Server #2</a>
        — no waitlist</div>
      <div><a href="javascript:alert(1)">Slow Partner Server #3</a>
        — no waitlist</div>
      <div><a href="/viewer/id">After downloading: Open in our viewer</a></div>
    </main>
    """

    assert mod.parse_aa_slow_partner_urls(detail_url, page) == []


def test_aa_slow_partner_parser_requires_detail_origin_with_effective_port():
    mod = _load_module(AA, "aa_slow_partner_origin_under_test")
    detail_url = "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef"
    page = """
    <main>
      <div><a href="/slow_download/id/0/1">Slow Partner Server #1</a>
        — no waitlist</div>
      <div><a href="https://annas-archive.pk:443/slow_download/id/0/2">Slow Partner Server #2</a>
        — no waitlist</div>
      <div><a href="https://files.example/slow_download/id/0/3">Slow Partner Server #3</a>
        — no waitlist</div>
      <div><a href="http://annas-archive.pk/slow_download/id/0/4">Slow Partner Server #4</a>
        — no waitlist</div>
      <div><a href="https://annas-archive.pk:444/slow_download/id/0/5">Slow Partner Server #5</a>
        — no waitlist</div>
      <div><a href="https://annas-archive.pk:0/slow_download/id/0/6">Slow Partner Server #6</a>
        — no waitlist</div>
    </main>
    """

    assert mod.parse_aa_slow_partner_urls(detail_url, page) == [
        "https://annas-archive.pk/slow_download/id/0/1",
        "https://annas-archive.pk:443/slow_download/id/0/2",
    ]


def test_aa_slow_partner_parser_skips_malformed_url_and_continues():
    mod = _load_module(AA, "aa_slow_partner_malformed_under_test")
    detail_url = "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef"
    page = """
    <main>
      <div><a href="https://[broken/slow_download/id/0/1">Slow Partner Server #1</a>
        — no waitlist</div>
      <div><a href="/slow_download/id/0/2">Slow Partner Server #2</a>
        — no waitlist</div>
    </main>
    """

    try:
        result = mod.parse_aa_slow_partner_urls(detail_url, page)
    except ValueError as exc:
        pytest.fail(f"malformed partner URL aborted parsing: {exc}")

    assert result == ["https://annas-archive.pk/slow_download/id/0/2"]


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        (
            '<a href="https://cdn.example.org/download/file.pdf">Download now</a>',
            "https://cdn.example.org/download/file.pdf",
        ),
        (
            '<a download href="https://cdn.example.org/files/book.epub">Download</a>',
            "https://cdn.example.org/files/book.epub",
        ),
        (
            '<script>navigator.clipboard.writeText("https:\\/\\/cdn.example.org\\/book.pdf")</script>',
            "https://cdn.example.org/book.pdf",
        ),
        (
            '<script>window.location.href = "/files/book.pdf"</script>',
            "https://annas-archive.pk/files/book.pdf",
        ),
        (
            '<code>https://cdn.example.org/files/book%20copy.pdf</code>',
            "https://cdn.example.org/files/book%20copy.pdf",
        ),
    ],
)
def test_aa_slow_final_url_parser_supports_approved_shapes(page, expected):
    mod = _load_module(AA, "aa_slow_final_url_parser_under_test")
    partner_url = "https://annas-archive.pk/slow_download/id/0/5"

    assert mod.parse_aa_slow_final_url(partner_url, page) == expected


def test_aa_slow_final_url_parser_rejects_credentials_and_recursive_slow_urls():
    mod = _load_module(AA, "aa_slow_final_url_parser_negative_under_test")
    partner_url = "https://annas-archive.pk/slow_download/id/0/5"

    assert mod.parse_aa_slow_final_url(
        partner_url,
        '<a href="https://user:secret@example.org/file.pdf">Download now</a>',
    ) == ""
    assert mod.parse_aa_slow_final_url(
        partner_url,
        '<a href="/slow_download/id/0/6">Download now</a>',
    ) == ""


@pytest.mark.parametrize(
    "value",
    [
        "https://[broken/file.pdf",
        "https://example.org:not-a-port/file.pdf",
        "https://example.org:99999/file.pdf",
    ],
)
def test_aa_safe_http_url_rejects_malformed_authorities_without_raising(value):
    mod = _load_module(AA, "aa_safe_http_malformed_under_test")

    try:
        result = mod._safe_http_url(value)
    except ValueError as exc:
        pytest.fail(f"malformed authority escaped URL validation: {exc}")

    assert result is False


@pytest.mark.parametrize(
    ("partner_url", "page"),
    [
        (
            "https://annas-archive.pk/slow_download/id/0/5",
            """
            <a href="https://[broken/file.pdf">Download now</a>
            <a href="https://cdn.example.org/book.pdf">Download now</a>
            """,
        ),
        (
            "https://[broken/slow_download/id/0/5",
            '<a href="/files/book.pdf">Download now</a>',
        ),
    ],
)
def test_aa_slow_final_url_parser_contains_urljoin_errors(partner_url, page):
    mod = _load_module(AA, "aa_slow_final_malformed_under_test")

    try:
        result = mod.parse_aa_slow_final_url(partner_url, page)
    except ValueError as exc:
        pytest.fail(f"malformed URL aborted final fallback parsing: {exc}")

    expected = (
        "https://cdn.example.org/book.pdf"
        if partner_url.startswith("https://annas-archive.pk")
        else ""
    )
    assert result == expected


def test_aa_reachability_rejects_live_shape_anna_parking_page(monkeypatch):
    mod = _load_module(AA, "aa_parking_page_under_test")
    calls: list[tuple[str, str, int]] = []

    def fake_request(
        method,
        url,
        *,
        timeout=30,
        stream=False,
        browser_tls=True,
        headers=None,
    ):
        calls.append((method, url, timeout))
        return SimpleNamespace(
            status_code=200,
            text="""
            <html><title>annas-archive.li</title><body>
              <h1>annas-archive.li</h1>
              <p>Find information, resources and relevant links for annas-archive.li.</p>
              <p>This domain may be for sale.</p>
            </body></html>
            """,
        )

    monkeypatch.setattr(mod, "_request", fake_request)

    assert mod._first_reachable_mirror(["https://annas-archive.gd"]) is None
    assert calls == [("GET", "https://annas-archive.gd", 10)]


def test_aa_reachability_scans_large_localised_homepage_for_search_form(monkeypatch):
    mod = _load_module(AA, "aa_large_homepage_under_test")
    homepage = (
        "<html><head><title>Anna’s Archive</title></head><body>"
        + ("<span>language</span>" * 8000)
        + '<form action="/search" method="get"><input name="q"></form>'
        + "</body></html>"
    )

    monkeypatch.setattr(
        mod,
        "_request",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=200, text=homepage),
    )

    assert mod._first_reachable_mirror(["https://annas-archive.pk"]) == (
        "https://annas-archive.pk"
    )


def test_aa_search_reports_ddos_guard_challenge(monkeypatch):
    mod = _load_module(AA, "aa_ddos_guard_under_test")
    challenge = SimpleNamespace(
        status_code=403,
        url="https://annas-archive.pk/search?q=example&check=1",
        headers={"server": "ddos-guard", "content-type": "text/html"},
        text="""
        <html>
          <head><title>DDoS-Guard</title></head>
          <body>Checking your browser before accessing annas-archive.pk.</body>
        </html>
        """,
    )

    monkeypatch.setattr(mod, "load_aa_config", lambda: {"donator_key": "configured"})
    monkeypatch.setattr(
        mod,
        "get_aa_base_url",
        lambda config: "https://annas-archive.pk",
    )
    monkeypatch.setattr(mod, "_request", lambda *args, **kwargs: challenge)
    browser_calls: list[str] = []
    monkeypatch.setattr(
        mod,
        "_fetch_aa_with_browser",
        lambda url: browser_calls.append(url) or "",
        raising=False,
    )

    result = mod.search_aa("example")

    assert result["success"] is False
    assert result["count"] == 0
    assert result["results"] == []
    assert result["error"] == "ddos_guard_challenge"
    assert browser_calls == [
        "https://annas-archive.pk/search?index=&page=1&display=table"
        "&acc=aa_download&acc=external_download&ext=pdf&q=example"
    ]


def test_aa_search_parses_browser_page_after_ddos_guard_challenge(monkeypatch):
    mod = _load_module(AA, "aa_ddos_guard_browser_under_test")
    challenge = SimpleNamespace(
        status_code=403,
        url="https://annas-archive.pk/search?q=example&check=1",
        headers={"server": "ddos-guard", "content-type": "text/html"},
        text="<title>DDoS-Guard</title><body>Checking your browser</body>",
    )
    solved_html = """
    <html><body>
      <a href="/md5/0123456789abcdef0123456789abcdef">Example Book</a>
    </body></html>
    """

    monkeypatch.setattr(mod, "load_aa_config", lambda: {"donator_key": "configured"})
    monkeypatch.setattr(
        mod,
        "get_aa_base_url",
        lambda config: "https://annas-archive.pk",
    )
    monkeypatch.setattr(mod, "_request", lambda *args, **kwargs: challenge)
    browser_calls: list[str] = []
    monkeypatch.setattr(
        mod,
        "_fetch_aa_with_browser",
        lambda url: browser_calls.append(url) or solved_html,
        raising=False,
    )

    result = mod.search_aa("example")

    assert result["success"] is True
    assert result["count"] == 1
    assert result["results"] == [
        {
            "md5": "0123456789abcdef0123456789abcdef",
            "title": "Example Book",
            "author": "",
            "publisher": "",
            "year": "",
            "language": "",
            "format": "",
            "size": "",
        }
    ]
    assert len(browser_calls) == 1


def test_aa_search_combines_multiple_formats_in_one_request(monkeypatch):
    mod = _load_module(AA, "aa_multiple_formats_under_test")
    requested_urls: list[str] = []

    monkeypatch.setattr(mod, "load_aa_config", lambda: {"donator_key": "configured"})
    monkeypatch.setattr(
        mod,
        "get_aa_base_url",
        lambda config: "https://annas-archive.pk",
    )

    def fake_request(_method, url, **_kwargs):
        requested_urls.append(url)
        return SimpleNamespace(
            status_code=200,
            url=url,
            headers={},
            text="<html><body>No files found.</body></html>",
        )

    monkeypatch.setattr(mod, "_request", fake_request)

    result = mod.search_aa("example", fmt=["epub", "pdf"])

    assert result["success"] is True
    assert requested_urls == [
        "https://annas-archive.pk/search?index=&page=1&display=table"
        "&acc=aa_download&acc=external_download&ext=epub&ext=pdf&q=example"
    ]


def test_aa_search_rejects_unrecognised_page_instead_of_reporting_zero(monkeypatch):
    mod = _load_module(AA, "aa_incomplete_search_under_test")
    incomplete_html = """
    <html><head><title>Search results</title></head><body>
      <nav>This navigation shell is deliberately long enough to look loaded.</nav>
      <main><a href="/md5/not-a-real-md5">Results are still loading</a></main>
    </body></html>
    """

    monkeypatch.setattr(mod, "load_aa_config", lambda: {"donator_key": "configured"})
    monkeypatch.setattr(
        mod,
        "get_aa_base_url",
        lambda config: "https://annas-archive.pk",
    )
    monkeypatch.setattr(
        mod,
        "_request",
        lambda _method, url, **_kwargs: SimpleNamespace(
            status_code=200,
            url=url,
            headers={},
            text=incomplete_html,
        ),
    )

    result = mod.search_aa("example")

    assert result == {
        "success": False,
        "source": "anna_archive",
        "count": 0,
        "results": [],
        "error": "aa_search_page_incomplete",
    }


def test_aa_browser_fallback_is_bounded_and_uses_named_temp_output(
    tmp_path,
    monkeypatch,
):
    mod = _load_module(AA, "aa_browser_process_under_test")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/uvx")
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        output_index = command.index("--output") + 1
        output = Path(command[output_index])
        output.write_text("<html><a href='/md5/abc'>book</a></html>", encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    html = mod._fetch_aa_with_browser(
        "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef",
        page_kind="detail",
    )

    assert html == "<html><a href='/md5/abc'>book</a></html>"
    assert observed["command"][:9] == [
        "/usr/bin/uvx",
        "--python",
        "3.12",
        "--from",
        "seleniumbase==4.51.11",
        "--with",
        "python-socks",
        "python",
        str(mod.AA_BROWSER_SCRIPT),
    ]
    assert observed["kwargs"]["timeout"] == mod.AA_BROWSER_PROCESS_TIMEOUT
    assert observed["command"][observed["command"].index("--page-kind") + 1] == "detail"
    assert not list((tmp_path / ".quasi" / "temp").glob("aa-browser-*"))


def test_aa_browser_fallback_fails_closed_without_uvx(monkeypatch):
    mod = _load_module(AA, "aa_browser_no_uvx_under_test")
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser helper must not start without uvx")
        ),
    )

    assert mod._fetch_aa_with_browser("https://annas-archive.pk/search?q=example") == ""


def test_aa_browser_runs_headless_without_virtual_display():
    mod = _load_module(AA_BROWSER, "aa_browser_options_under_test")

    assert mod._browser_options() == {
        "headless": True,
        "headed": False,
        "xvfb": False,
        "sandbox": False,
        "lang": "en",
        "incognito": True,
    }


def test_aa_browser_settles_only_on_valid_results_or_explicit_empty_state():
    mod = _load_module(AA_BROWSER, "aa_browser_settled_page_under_test")
    search_url = "https://annas-archive.pk/search?q=example"

    assert not mod._looks_like_settled_search(
        search_url,
        "Search results " + ("navigation " * 100),
        "<html><body>Search results are loading</body></html>",
    )
    assert not mod._looks_like_settled_search(
        search_url,
        "Search results",
        '<a href="/md5/not-a-real-md5">loading</a>',
    )
    assert mod._looks_like_settled_search(
        search_url,
        "One result",
        '<a href="/md5/0123456789abcdef0123456789abcdef">book</a>',
    )
    assert mod._looks_like_settled_search(
        search_url,
        "No files found.",
        "<main>No files found.</main>",
    )
    assert mod._looks_like_settled_page(
        "detail",
        "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef",
        "Book details are loaded",
        """
        <main><div class="main-inner"><div><div class="md-meta">
        Book details are loaded
        </div></div></div></main>
        """,
    )
    assert not mod._looks_like_settled_page(
        "detail",
        search_url,
        "results",
        '<a href="/md5/0123456789abcdef0123456789abcdef">book</a>',
    )
    slow_url = (
        "https://annas-archive.pk/slow_download/"
        "0123456789abcdef0123456789abcdef/0/0"
    )
    assert mod._looks_like_settled_page(
        "slow",
        slow_url,
        "Download now",
        '<a download href="https://files.example/book.pdf">Download now</a>',
    )
    assert mod._looks_like_settled_page(
        "slow",
        slow_url,
        "Wait 20 seconds",
        '<span class="js-partner-countdown">20</span>',
    )
    assert not mod._looks_like_settled_page(
        "slow",
        slow_url,
        "Loading",
        "<main>Loading</main>",
    )


def test_aa_browser_detail_mode_requires_populated_non_error_main_content():
    mod = _load_module(AA_BROWSER, "aa_browser_detail_content_under_test")
    detail_url = "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef"

    assert not mod._looks_like_settled_page(
        "detail", detail_url, "", "<html><body><main></main></body></html>"
    )
    assert not mod._looks_like_settled_page(
        "detail",
        detail_url,
        "",
        '<main><div class="main-inner"></div></main>',
    )
    assert not mod._looks_like_settled_page(
        "detail",
        detail_url,
        "Loading",
        '<main><div class="main-inner">Loading</div></main>',
    )
    assert not mod._looks_like_settled_page(
        "detail", detail_url, "Book details", "<main><h1>Book details</h1></main>"
    )
    assert not mod._looks_like_settled_page(
        "detail",
        f"https://annas-archive.pk/error{urllib.parse.urlparse(detail_url).path}",
        "A complete-looking error route",
        '<main><div class="main-inner">A complete-looking error route</div></main>',
    )
    assert not mod._looks_like_settled_page(
        "detail",
        detail_url,
        "Internal Server Error",
        '<main><div class="main-inner">Internal Server Error</div></main>',
    )
    assert mod._looks_like_settled_page(
        "detail",
        detail_url,
        "A complete book record without partner links",
        """
        <main><div class="main-inner"><div><div class="md-meta">
        <h1>A complete book record</h1><span>Language: English</span>
        </div></div></div></main>
        """,
    )


@pytest.mark.parametrize(
    ("body", "page"),
    [
        (
            "Download now",
            '<a href="https://files.example/book.pdf">Download now</a>',
        ),
        (
            "Download",
            '<a download href="https://files.example/book.pdf">Download</a>',
        ),
        (
            "Copy link",
            '<script>navigator.clipboard.writeText("https://files.example/book.pdf")</script>',
        ),
        (
            "Preparing download",
            '<script>window.location.href = "https://files.example/book.pdf"</script>',
        ),
        ("https://files.example/book.pdf", "<code>https://files.example/book.pdf</code>"),
        ("https://files.example/book.pdf", "<span>https://files.example/book.pdf</span>"),
        ("Wait 20 seconds", "<main><p>Wait 20 seconds before downloading.</p></main>"),
        ("You are on the waitlist", "<main><p>You are on the waitlist.</p></main>"),
    ],
)
def test_aa_browser_slow_mode_settles_on_parser_shapes_or_explicit_wait(body, page):
    mod = _load_module(AA_BROWSER, "aa_browser_slow_shapes_under_test")
    slow_url = (
        "https://annas-archive.pk/slow_download/"
        "0123456789abcdef0123456789abcdef/0/0"
    )

    assert mod._looks_like_settled_page("slow", slow_url, body, page)


def test_fetch_aa_page_returns_complete_detail_response_without_browser(monkeypatch):
    mod = _load_module(AA, "aa_fetch_detail_http_under_test")
    detail_url = "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef"
    response = SimpleNamespace(
        status_code=200,
        headers={},
        text="<main>Book details are loaded</main>",
        url=detail_url,
    )
    monkeypatch.setattr(mod, "_request", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(
        mod,
        "_fetch_aa_with_browser",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser must not run for a complete HTTP response")
        ),
        raising=False,
    )

    assert mod.fetch_aa_page(detail_url, page_kind="detail") == response.text


def test_fetch_aa_page_uses_detail_browser_after_confirmed_ddos_guard(monkeypatch):
    mod = _load_module(AA, "aa_fetch_detail_browser_under_test")
    detail_url = "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef"
    response = SimpleNamespace(
        status_code=403,
        headers={"server": "ddos-guard"},
        text="Checking your browser with DDoS-Guard challenge",
        url=f"{detail_url}?check=1",
    )
    browser_calls = []
    monkeypatch.setattr(mod, "_request", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(
        mod,
        "_fetch_aa_with_browser",
        lambda url, page_kind="search": browser_calls.append((url, page_kind)) or "<main>detail</main>",
        raising=False,
    )

    assert mod.fetch_aa_page(detail_url, page_kind="detail") == "<main>detail</main>"
    assert browser_calls == [(detail_url, "detail")]


def test_fetch_aa_page_uses_slow_browser_after_anna_403(monkeypatch):
    mod = _load_module(AA, "aa_fetch_slow_browser_under_test")
    slow_url = "https://annas-archive.pk/slow_download/0123456789abcdef0123456789abcdef/0/0"
    response = SimpleNamespace(
        status_code=403,
        headers={},
        text="Forbidden",
        url=slow_url,
    )
    browser_calls = []
    monkeypatch.setattr(mod, "_request", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(
        mod,
        "_fetch_aa_with_browser",
        lambda url, page_kind="search": browser_calls.append((url, page_kind)) or "<main>slow</main>",
        raising=False,
    )

    assert mod.fetch_aa_page(slow_url, page_kind="slow") == "<main>slow</main>"
    assert browser_calls == [(slow_url, "slow")]


def test_fetch_aa_page_returns_empty_for_ordinary_server_error(monkeypatch):
    mod = _load_module(AA, "aa_fetch_error_under_test")
    detail_url = "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef"
    response = SimpleNamespace(
        status_code=500,
        headers={},
        text="Server error",
        url=detail_url,
    )
    monkeypatch.setattr(mod, "_request", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(
        mod,
        "_fetch_aa_with_browser",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser must not run for an ordinary server error")
        ),
        raising=False,
    )

    assert mod.fetch_aa_page(detail_url, page_kind="detail") == ""


def test_aa_request_forwards_headers(monkeypatch):
    mod = _load_module(AA, "aa_request_headers_under_test")
    observed = {}
    referer = "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef"

    def fake_request(method, url, **kwargs):
        observed.update(method=method, url=url, **kwargs)
        return SimpleNamespace(status_code=200, headers={}, text="", url=url)

    monkeypatch.setattr(mod, "_request", fake_request)

    mod.aa_request("GET", "https://files.example/book.pdf", headers={"Referer": referer})

    assert observed["headers"] == {"Referer": referer}


def test_aa_fast_api_recognises_quota_error_from_429_json(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_aa_quota_json_under_test")

    class FakeResponse:
        status_code = 429
        headers = {"content-type": "text/json; charset=utf-8"}

        def json(self):
            return {
                "///download_url": "",
                "download_url": "",
                "error": "No downloads left",
            }

    monkeypatch.setattr(mod, "aa_request", lambda *_args, **_kwargs: FakeResponse())

    with pytest.raises(mod.AAQuotaExhausted, match="No downloads left"):
        mod.aa_fast_download_url(
            "https://annas-archive.pk",
            "0123456789abcdef0123456789abcdef",
            "secret",
        )


def test_aa_quota_exhaustion_skips_fast_rotations_and_tries_libgen(
    tmp_path,
    monkeypatch,
):
    mod = _load_module(DOWNLOAD, "download_aa_quota_fallback_under_test")
    fast_calls: list[tuple] = []
    libgen_calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(mod, "load_aa_config", lambda: {"donator_key": "secret"})
    monkeypatch.setattr(
        mod,
        "get_aa_base_url",
        lambda _config: "https://annas-archive.pk",
    )

    def quota_exhausted(*args):
        fast_calls.append(args)
        raise mod.AAQuotaExhausted("No downloads left")

    def libgen_success(md5, dest, fmt):
        libgen_calls.append((md5, dest, fmt))
        Path(dest).write_bytes(b"%PDF-1.7\n" + b"x" * 12000)
        return True

    monkeypatch.setattr(mod, "aa_fast_download_url", quota_exhausted)
    monkeypatch.setattr(mod, "_try_libgen_download", libgen_success)

    result = mod.download_from_aa(
        "0123456789abcdef0123456789abcdef",
        output_dir=str(tmp_path),
        filename="book",
        fmt="pdf",
    )

    assert result == str(tmp_path / "book.pdf")
    assert len(fast_calls) == 1
    assert libgen_calls == [
        (
            "0123456789abcdef0123456789abcdef",
            str(tmp_path / "book.pdf"),
            "pdf",
        )
    ]


def test_book_fetch_removes_invalid_existing_temp_before_fallback(
    tmp_path,
    monkeypatch,
):
    mod = _load_module(DOWNLOAD, "download_existing_book_temp_under_test")
    dest = tmp_path / "book.pdf"
    dest.write_bytes(b"<html>stale error page</html>" + b" " * 12000)

    monkeypatch.setattr(mod, "load_aa_config", lambda: {"donator_key": "secret"})
    monkeypatch.setattr(
        mod,
        "get_aa_base_url",
        lambda _config: "https://annas-archive.pk",
    )
    monkeypatch.setattr(
        mod,
        "aa_fast_download_url",
        lambda *_args: (_ for _ in ()).throw(
            mod.AAQuotaExhausted("No downloads left")
        ),
    )
    monkeypatch.setattr(mod, "_try_libgen_download", lambda *_args: False)
    monkeypatch.setattr(
        mod,
        "_try_aa_slow_download",
        lambda *_args: False,
        raising=False,
    )

    with pytest.raises(mod.AAQuotaExhausted, match="No downloads left"):
        mod.download_from_aa(
            "0123456789abcdef0123456789abcdef",
            output_dir=str(tmp_path),
            filename="book",
            fmt="pdf",
        )

    assert not dest.exists()


def test_aa_slow_download_uses_each_no_wait_partner_as_referer(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_aa_slow_transport_under_test")
    md5 = "0123456789abcdef0123456789abcdef"
    base_url = "https://annas-archive.pk"
    detail_url = f"{base_url}/md5/{md5}"
    partner_five = f"{base_url}/slow_download/id/0/5"
    partner_six = f"{base_url}/slow_download/id/0/6"
    first_download = "https://cdn.example.org/first.pdf"
    second_download = "https://cdn.example.org/second.pdf"
    dest = tmp_path / "book.pdf"
    import fitz

    document = fitz.open()
    document.new_page().insert_text((72, 72), "valid second partner payload")
    valid_pdf = document.tobytes()
    document.close()
    pages = {
        detail_url: """
        <div><a href="/slow_download/id/0/5">Slow Partner Server #5</a>
        — no waitlist, but can be very slow</div>
        <div><a href="/slow_download/id/0/6">Slow Partner Server #6</a>
        — no waitlist, but can be very slow</div>
        """,
        partner_five: '<a href="https://cdn.example.org/first.pdf">Download now</a>',
        partner_six: '<a href="https://cdn.example.org/second.pdf">Download now</a>',
    }
    observed_referers = []
    observed_downloads = []

    monkeypatch.setattr(
        mod,
        "fetch_aa_page",
        lambda url, *, page_kind: pages[url],
        raising=False,
    )

    def stream_download(url, output_path, *, headers=None, requester=None):
        observed_downloads.append(url)
        observed_referers.append(headers["Referer"])
        Path(output_path).write_bytes(
            b"%PDF-1.7\n" + b"x" * 12000
            if url == first_download
            else valid_pdf
        )
        return True

    monkeypatch.setattr(mod, "_stream_download", stream_download)

    assert mod._try_aa_slow_download(base_url, md5, str(dest), "pdf") is True
    assert observed_downloads == [first_download, second_download]
    assert observed_referers == [partner_five, partner_six]
    assert dest.read_bytes() == valid_pdf


def test_aa_slow_download_removes_undersized_transfer(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_aa_slow_undersized_under_test")
    md5 = "0123456789abcdef0123456789abcdef"
    base_url = "https://annas-archive.pk"
    detail_url = f"{base_url}/md5/{md5}"
    partner_url = f"{base_url}/slow_download/id/0/5"
    download_url = "https://cdn.example.org/undersized.pdf"
    dest = tmp_path / "book.pdf"
    payload = b"%PDF-1.7\n" + b"x" * 100
    pages = {
        detail_url: """
        <div><a href="/slow_download/id/0/5">Slow Partner Server #5</a>
        — no waitlist, but can be very slow</div>
        """,
        partner_url: '<a href="https://cdn.example.org/undersized.pdf">Download now</a>',
    }

    class FakeResponse:
        status_code = 200
        headers = {
            "content-type": "application/pdf",
            "content-length": str(len(payload)),
        }

        def iter_content(self, chunk_size=8192):
            yield payload

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        mod,
        "fetch_aa_page",
        lambda url, *, page_kind: pages[url],
    )
    monkeypatch.setattr(
        mod,
        "aa_request",
        lambda method, url, *, timeout, stream, headers: FakeResponse(),
    )

    assert mod._try_aa_slow_download(base_url, md5, str(dest), "pdf") is False
    assert not dest.exists()


@pytest.mark.parametrize("successful_stage", ["fast", "libgen", "slow"])
def test_book_download_reaches_slow_only_after_fast_and_libgen_fail(
    tmp_path,
    monkeypatch,
    successful_stage,
):
    mod = _load_module(DOWNLOAD, f"download_slow_cascade_{successful_stage}_under_test")
    md5 = "0123456789abcdef0123456789abcdef"
    dest = tmp_path / "book.pdf"
    slow_calls = []
    libgen_calls = []

    monkeypatch.setattr(mod, "load_aa_config", lambda: {"donator_key": "secret"})
    monkeypatch.setattr(mod, "get_aa_base_url", lambda _config: "https://annas-archive.pk")
    monkeypatch.setattr(mod, "AA_FALLBACK_INDICES", ())
    monkeypatch.setattr(
        mod,
        "aa_fast_download_url",
        lambda *_args: (
            ("https://cdn.example.org/fast.pdf", {})
            if successful_stage == "fast"
            else (None, {})
        ),
    )
    monkeypatch.setattr(mod, "_is_valid_book_file", lambda *_args: True)

    def stream_download(_url, output_path, *, headers=None, requester=None):
        Path(output_path).write_bytes(b"fast payload")
        return True

    monkeypatch.setattr(mod, "_stream_download", stream_download)

    def libgen_download(_md5, output_path, _fmt):
        libgen_calls.append(output_path)
        if successful_stage == "libgen":
            Path(output_path).write_bytes(b"libgen payload")
            return True
        return False

    monkeypatch.setattr(mod, "_try_libgen_download", libgen_download)

    def slow_download(*args):
        slow_calls.append(args)
        if successful_stage == "slow":
            Path(args[2]).write_bytes(b"slow payload")
            return True
        return False

    monkeypatch.setattr(mod, "_try_aa_slow_download", slow_download, raising=False)

    assert mod.download_from_aa(
        md5,
        output_dir=str(tmp_path),
        filename="book",
        fmt="pdf",
    ) == str(dest)
    assert len(libgen_calls) == (0 if successful_stage == "fast" else 1)
    assert len(slow_calls) == (1 if successful_stage == "slow" else 0)


def test_book_rotation_quota_still_reaches_fallbacks(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_rotation_quota_slow_fallback_under_test")
    md5 = "0123456789abcdef0123456789abcdef"
    fast_calls = []
    libgen_calls = []
    slow_calls = []

    monkeypatch.setattr(mod, "load_aa_config", lambda: {"donator_key": "secret"})
    monkeypatch.setattr(mod, "get_aa_base_url", lambda _config: "https://annas-archive.pk")
    monkeypatch.setattr(mod, "AA_FALLBACK_INDICES", ((1, 1), (2, 2)))

    def fast_download(*args):
        fast_calls.append(args)
        if len(fast_calls) == 1:
            return None, {}
        raise mod.AAQuotaExhausted("No downloads left")

    monkeypatch.setattr(mod, "aa_fast_download_url", fast_download)
    monkeypatch.setattr(
        mod,
        "_try_libgen_download",
        lambda *args: libgen_calls.append(args) or False,
    )
    monkeypatch.setattr(
        mod,
        "_try_aa_slow_download",
        lambda *args: slow_calls.append(args) or False,
        raising=False,
    )

    with pytest.raises(mod.AAQuotaExhausted, match="No downloads left"):
        mod.download_from_aa(
            md5,
            output_dir=str(tmp_path),
            filename="book",
            fmt="pdf",
        )

    assert [call[3:] for call in fast_calls] == [(), (1, 1)]
    assert len(libgen_calls) == 1
    assert len(slow_calls) == 1


def test_libgen_resolves_ads_page_before_downloading_keyed_url(
    tmp_path,
    monkeypatch,
):
    mod = _load_module(DOWNLOAD, "download_libgen_ads_under_test")
    md5 = "0123456789abcdef0123456789abcdef"
    dest = tmp_path / "book.pdf"
    ads_url = f"https://libgen.li/ads.php?md5={md5}"
    download_url = f"https://libgen.li/get.php?md5={md5}&key=abc123"
    import fitz

    document = fitz.open()
    for page_number in range(40):
        page = document.new_page()
        page.insert_text((72, 72), f"Valid page {page_number} " + "content " * 200)
    pdf_bytes = document.tobytes(deflate=False)
    document.close()
    calls: list[tuple[str, str, bool]] = []

    class FakeResponse:
        def __init__(self, *, url, text="", content=b"", content_type="text/html"):
            self.status_code = 200
            self.url = url
            self.text = text
            self.content = content
            self.headers = {
                "content-type": content_type,
                "content-length": str(len(content)),
            }

        def iter_content(self, chunk_size=8192):
            for start in range(0, len(self.content), chunk_size):
                yield self.content[start:start + chunk_size]

        def raise_for_status(self):
            return None

    def fake_aa_request(method, url, *, timeout=30, stream=False, headers=None):
        calls.append((method, url, stream))
        if url == ads_url:
            return FakeResponse(
                url=ads_url,
                text=(
                    f'<a href="/get.php?md5={md5}&amp;key=abc123">'
                    "<h2>GET</h2></a>"
                ),
            )
        if url == download_url:
            return FakeResponse(
                url=download_url,
                content=pdf_bytes,
                content_type="application/pdf",
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(mod, "aa_request", fake_aa_request)

    assert mod._try_libgen_download(md5, str(dest), "pdf") is True
    assert dest.read_bytes() == pdf_bytes
    assert calls == [
        ("GET", ads_url, False),
        ("GET", download_url, True),
    ]


def test_stream_download_rejects_large_html_and_removes_output(tmp_path):
    mod = _load_module(DOWNLOAD, "download_stream_html_under_test")
    dest = tmp_path / "book.pdf"
    html_bytes = b"<!doctype html><html><body>busy</body></html>" + b" " * 20000

    class FakeResponse:
        status_code = 200
        headers = {
            "content-type": "text/html; charset=utf-8",
            "content-length": str(len(html_bytes)),
        }

        def iter_content(self, chunk_size=8192):
            for start in range(0, len(html_bytes), chunk_size):
                yield html_bytes[start:start + chunk_size]

        def raise_for_status(self):
            return None

    def requester(_method, _url, *, timeout=30, stream=False, headers=None):
        return FakeResponse()

    assert mod._stream_download(
        "https://libgen.li/get.php?md5=x&key=y",
        str(dest),
        requester=requester,
    ) is False
    assert not dest.exists()


def test_stream_download_forwards_partner_referer(tmp_path):
    mod = _load_module(DOWNLOAD, "download_stream_partner_referer_under_test")
    dest = tmp_path / "book.pdf"
    payload = b"%PDF-1.7\n" + b"x" * 12000
    observed_headers = {}

    class FakeResponse:
        status_code = 200
        headers = {
            "content-type": "application/pdf",
            "content-length": str(len(payload)),
        }

        def iter_content(self, chunk_size=8192):
            for start in range(0, len(payload), chunk_size):
                yield payload[start:start + chunk_size]

        def raise_for_status(self):
            return None

    def requester(_method, _url, *, timeout, stream, headers):
        observed_headers.update(headers)
        return FakeResponse()

    assert mod._stream_download(
        "https://cdn.example.org/files/book.pdf",
        str(dest),
        headers={
            **mod.HEADERS_BROWSER,
            "Referer": "https://annas-archive.pk/slow_download/id/0/5",
        },
        requester=requester,
    ) is True
    assert observed_headers["Referer"] == "https://annas-archive.pk/slow_download/id/0/5"


def test_book_file_validator_requires_real_pdf_or_epub_structure(tmp_path):
    mod = _load_module(DOWNLOAD, "download_book_structure_under_test")
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"%PDF-1.7\ntruncated" + b"x" * 12000)
    valid_epub = tmp_path / "valid.epub"
    with zipfile.ZipFile(valid_epub, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles/></container>',
        )
    corrupt_epub = tmp_path / "corrupt.epub"
    with zipfile.ZipFile(corrupt_epub, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")

    assert mod._is_valid_book_file(corrupt_pdf, "pdf") is False
    assert mod._is_valid_book_file(valid_epub, "epub") is True
    assert mod._is_valid_book_file(corrupt_epub, "epub") is False


def test_book_candidates_exposes_aa_failure_code(monkeypatch, capsys):
    mod = _load_module(DOWNLOAD, "download_aa_failure_under_test")
    monkeypatch.setattr(
        mod,
        "search_aa",
        lambda *args, **kwargs: {
            "success": False,
            "source": "anna_archive",
            "count": 0,
            "results": [],
            "error": "ddos_guard_challenge",
        },
    )
    args = SimpleNamespace(
        query="example",
        title=None,
        author=None,
        year=None,
        format="pdf",
        lang=None,
        limit=5,
    )

    exit_code = mod._cmd_book_candidates(args)
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "failed"
    assert payload["count"] == 0
    assert payload["candidates"] == []
    assert payload["error"] == "ddos_guard_challenge"


def test_book_candidates_defaults_to_one_epub_pdf_search(monkeypatch, capsys):
    mod = _load_module(DOWNLOAD, "download_default_formats_under_test")
    calls = []

    def fake_search(query, *, fmt, lang, limit):
        calls.append({"query": query, "fmt": fmt, "lang": lang, "limit": limit})
        return {
            "success": True,
            "source": "anna_archive",
            "count": 0,
            "results": [],
        }

    monkeypatch.setattr(mod, "search_aa", fake_search)
    args = SimpleNamespace(
        query=None,
        title="Example",
        author="Author",
        year=None,
        format=None,
        lang=None,
        limit=5,
    )

    assert mod._cmd_book_candidates(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    assert calls == [
        {
            "query": "Example Author",
            "fmt": ["epub", "pdf"],
            "lang": None,
            "limit": 5,
        }
    ]


def test_book_candidates_accepts_ordered_repeated_format_flags():
    mod = _load_module(DOWNLOAD, "download_repeated_formats_under_test")

    args = mod._build_parser().parse_args(
        [
            "book",
            "candidates",
            "--query",
            "example",
            "--format",
            "epub",
            "--format",
            "pdf",
        ]
    )

    assert args.format == ["epub", "pdf"]


def test_aa_base_url_uses_live_last_good_before_other_discovery(tmp_path, monkeypatch):
    mod = _load_module(AA, "aa_last_good_priority_under_test")
    cache_path = tmp_path / "aa-mirrors.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": mod.WIKIPEDIA_AA_URL,
                "fetched_at": 100.0,
                "mirrors": ["https://annas-archive.wf"],
                "last_good": {
                    "mirror": "https://annas-archive.se",
                    "verified_at": 200.0,
                },
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, str, int]] = []

    def fake_request(
        method,
        url,
        *,
        timeout=30,
        stream=False,
        browser_tls=True,
        headers=None,
    ):
        calls.append((method, url, timeout))
        return SimpleNamespace(status_code=200, text=AA_HOMEPAGE_HTML)

    monkeypatch.setattr(mod, "_aa_mirror_cache_path", lambda: cache_path)
    monkeypatch.setattr(mod, "_request", fake_request)
    monkeypatch.setattr(mod.time, "time", lambda: 300.0)
    monkeypatch.setattr(
        mod,
        "wikipedia_aa_mirrors",
        lambda: (_ for _ in ()).throw(
            AssertionError("Wikipedia must not be queried after a live last-good hit")
        ),
    )

    assert mod.get_aa_base_url({"mirrors": []}) == "https://annas-archive.se"
    assert calls == [("GET", "https://annas-archive.se", 10)]
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["last_good"] == {
        "mirror": "https://annas-archive.se",
        "verified_at": 300.0,
    }
    assert cache["mirrors"] == ["https://annas-archive.wf"]


def test_aa_base_url_prefers_wikipedia_mirror_before_static_seed(tmp_path, monkeypatch):
    mod = _load_module(AA, "aa_wikipedia_priority_under_test")
    cache_path = tmp_path / "aa-mirrors.json"
    calls: list[tuple[str, str, int]] = []

    def fake_request(
        method,
        url,
        *,
        timeout=30,
        stream=False,
        browser_tls=True,
        headers=None,
    ):
        calls.append((method, url, timeout))
        return SimpleNamespace(status_code=200, text=AA_HOMEPAGE_HTML)

    monkeypatch.setattr(mod, "_aa_mirror_cache_path", lambda: cache_path)
    monkeypatch.setattr(mod, "_request", fake_request)
    monkeypatch.setattr(mod.time, "time", lambda: 400.0)
    monkeypatch.setattr(mod, "STATIC_AA_MIRRORS", ["https://annas-archive.gd"])
    monkeypatch.setattr(
        mod,
        "wikipedia_aa_mirrors",
        lambda: ["https://annas-archive.wf"],
    )

    assert mod.get_aa_base_url({"mirrors": []}) == "https://annas-archive.wf"
    assert calls == [("GET", "https://annas-archive.wf", 10)]
    assert json.loads(cache_path.read_text(encoding="utf-8"))["last_good"] == {
        "mirror": "https://annas-archive.wf",
        "verified_at": 400.0,
    }


def test_aa_wikipedia_cache_older_than_seven_days_is_stale(tmp_path, monkeypatch):
    mod = _load_module(AA, "aa_wikipedia_cache_ttl_under_test")
    cache_path = tmp_path / "aa-mirrors.json"
    now = 1_000_000.0
    cache_path.write_text(
        json.dumps(
            {
                "source": mod.WIKIPEDIA_AA_URL,
                "fetched_at": now - (7 * 24 * 60 * 60) - 1,
                "mirrors": ["https://annas-archive.wf"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_aa_mirror_cache_path", lambda: cache_path)

    assert mod._read_cached_wikipedia_mirrors(now=now) == []


def test_aa_last_good_cache_tolerates_missing_field_and_invalid_json(
    tmp_path,
    monkeypatch,
):
    mod = _load_module(AA, "aa_last_good_cache_damage_under_test")
    cache_path = tmp_path / "aa-mirrors.json"
    cache_path.write_text(
        json.dumps(
            {
                "fetched_at": 100.0,
                "mirrors": ["https://annas-archive.wf"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_aa_mirror_cache_path", lambda: cache_path)

    assert mod._read_cached_last_good() is None

    cache_path.write_text("{not-json", encoding="utf-8")

    assert mod._read_cached_last_good() is None


def test_download_help_exposes_agent_contract():
    top = run_download("--help")
    assert top.returncode == 0
    assert "{book,paper,accept}" in top.stdout

    for args in [
        ("book", "candidates", "--help"),
        ("book", "fetch", "--help"),
        ("paper", "fetch", "--help"),
        ("paper", "diagnose", "--help"),
        ("accept", "--help"),
    ]:
        result = run_download(*args)
        assert result.returncode == 0


def test_legacy_flag_mode_is_removed():
    result = run_download("--doi", "10.1/example")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_legacy_batch_mode_is_removed():
    result = run_download("batch", "--manifest", "manifest.json")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_accept_moves_temp_file_to_sources(tmp_path):
    project = tmp_path / "project"
    temp_dir = project / ".quasi" / "temp" / "downloads"
    temp_dir.mkdir(parents=True)
    src = temp_dir / "candidate.pdf"
    src.write_bytes(b"%PDF- test content")

    result = subprocess.run(
        [
            sys.executable,
            str(DOWNLOAD),
            "accept",
            "--path",
            str(src),
            "--slug",
            "author-title-2024",
            "--kind",
            "paper",
            "--json",
        ],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["kind"] == "paper"
    assert payload["moved"] is True
    assert Path(payload["path"]).name == "author-title-2024.pdf"
    assert Path(payload["path"]).exists()
    assert not src.exists()


def test_accept_overwrite_uses_one_sibling_atomic_replace(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_accept_atomic_under_test")
    source_dir = tmp_path / ".quasi" / "temp" / "downloads"
    output_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    src = source_dir / "candidate.pdf"
    dest = output_dir / "author-title-2024.pdf"
    src.write_bytes(b"new generation")
    dest.write_bytes(b"old generation")

    replaced: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def observing_replace(source, target):
        source_path = Path(source)
        target_path = Path(target)
        assert target_path == dest
        assert dest.read_bytes() == b"old generation"
        assert source_path.parent == dest.parent
        assert source_path.name.startswith(f"{dest.name}.quasi-stage-")
        replaced.append((source_path, target_path))
        real_replace(source, target)

    monkeypatch.setattr(mod.os, "replace", observing_replace)
    payload, code = mod._accept_to_output(
        src,
        dest,
        kind="paper",
        overwrite=True,
    )

    assert code == 0
    assert payload["status"] == "ok"
    assert payload["published"] is True
    assert payload["source_removed"] is True
    assert payload["sha256"] == hashlib.sha256(b"new generation").hexdigest()
    assert replaced and dest.read_bytes() == b"new generation"
    assert not src.exists()
    assert not list(output_dir.glob(f"{dest.name}.quasi-stage-*"))


def test_accept_failure_before_replace_preserves_previous_output(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_accept_rollback_under_test")
    source_dir = tmp_path / ".quasi" / "temp" / "downloads"
    output_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    src = source_dir / "candidate.pdf"
    dest = output_dir / "author-title-2024.pdf"
    src.write_bytes(b"new generation")
    dest.write_bytes(b"old generation")

    monkeypatch.setattr(
        mod.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )
    payload, code = mod._accept_to_output(
        src,
        dest,
        kind="paper",
        overwrite=True,
    )

    assert code == 1
    assert payload["status"] == "blocked"
    assert payload["reason"] == "accept_commit_failed"
    assert payload["published"] is False
    assert payload["previous_output_preserved"] is True
    assert src.read_bytes() == b"new generation"
    assert dest.read_bytes() == b"old generation"
    assert not list(output_dir.glob(f"{dest.name}.quasi-stage-*"))


def test_accept_post_replace_fsync_failure_reports_coherent_unknown(
    tmp_path,
    monkeypatch,
):
    mod = _load_module(DOWNLOAD, "download_accept_fsync_under_test")
    source_dir = tmp_path / ".quasi" / "temp" / "downloads"
    output_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    src = source_dir / "candidate.pdf"
    dest = output_dir / "author-title-2024.pdf"
    src.write_bytes(b"new generation")
    dest.write_bytes(b"old generation")

    monkeypatch.setattr(
        mod,
        "_fsync_directory",
        lambda _path: (_ for _ in ()).throw(OSError("directory fsync failed")),
    )
    payload, code = mod._accept_to_output(
        src,
        dest,
        kind="paper",
        overwrite=True,
    )

    assert code == 1
    assert payload["status"] == "blocked"
    assert payload["published"] is True
    assert payload["previous_output_preserved"] is False
    assert payload["sha256"] == hashlib.sha256(b"new generation").hexdigest()
    assert dest.read_bytes() == b"new generation"
    assert src.read_bytes() == b"new generation"


def test_accept_serializes_competing_writers_for_one_output(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_accept_lock_under_test")
    source_dir = tmp_path / ".quasi" / "temp" / "downloads"
    output_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True)
    output_dir.mkdir()
    first = source_dir / "first.pdf"
    second = source_dir / "second.pdf"
    dest = output_dir / "author-title-2024.pdf"
    first.write_bytes(b"first generation")
    second.write_bytes(b"second generation")

    first_inside_replace = threading.Event()
    release_first = threading.Event()
    real_replace = os.replace

    def paused_replace(source, target):
        if not first_inside_replace.is_set():
            first_inside_replace.set()
            assert release_first.wait(timeout=2)
        real_replace(source, target)

    monkeypatch.setattr(mod.os, "replace", paused_replace)
    results: dict[str, tuple[dict, int]] = {}

    def accept(name: str, source: Path) -> None:
        results[name] = mod._accept_to_output(
            source,
            dest,
            kind="paper",
            overwrite=False,
        )

    one = threading.Thread(target=accept, args=("first", first))
    two = threading.Thread(target=accept, args=("second", second))
    one.start()
    assert first_inside_replace.wait(timeout=2)
    two.start()
    time.sleep(0.1)
    assert "second" not in results
    release_first.set()
    one.join(timeout=2)
    two.join(timeout=2)

    assert results["first"][1] == 0
    assert results["second"][1] == 1
    assert results["second"][0]["status"] == "conflict"
    assert dest.read_bytes() == b"first generation"
    assert second.exists()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(path.parent))
    return mod


class _FakeUrlResponse:
    def __init__(self, url, content, *, status=200, headers=None):
        self._url = url
        self._content = content
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size=-1):
        return self._content if size < 0 else self._content[:size]

    def geturl(self):
        return self._url


def test_ezproxy_base_url_normalises_to_login_prefix():
    mod = _load_module(COOKIECLOUD, "cookiecloud_under_test")

    assert mod._ezproxy_login_url("https://ezproxy.example.edu") == (
        "https://ezproxy.example.edu/login?url="
    )
    assert mod._ezproxy_login_url("ezproxy.example.edu/") == (
        "https://ezproxy.example.edu/login?url="
    )


def test_cookiecloud_domain_filter_keeps_parent_and_subdomain_cookies():
    mod = _load_module(COOKIECLOUD, "cookiecloud_domain_filter_under_test")
    data = {
        "cookie_data": {
            "bucket": [
                {"domain": "oclc.org", "name": "root", "value": "r"},
                {"domain": ".idm.oclc.org", "name": "idm", "value": "i"},
                {
                    "domain": "www-tandfonline-com.eux.idm.oclc.org",
                    "name": "tnf",
                    "value": "t",
                },
                {"domain": "example.org", "name": "other", "value": "x"},
            ]
        }
    }

    records = mod._filter_cookie_records(data, "oclc.org")

    assert [(r["domain"], r["name"]) for r in records] == [
        ("oclc.org", "root"),
        ("idm.oclc.org", "idm"),
        ("www-tandfonline-com.eux.idm.oclc.org", "tnf"),
    ]


def test_ezproxy_cookie_header_uses_only_cookies_matching_request_host():
    mod = _load_module(DOWNLOAD, "download_cookie_header_under_test")
    config = {
        "domain": "oclc.org",
        "cookie_records": [
            {"domain": "oclc.org", "name": "root", "value": "r", "path": "/"},
            {"domain": "idm.oclc.org", "name": "idm", "value": "i", "path": "/"},
            {
                "domain": "journals-sagepub-com.eux.idm.oclc.org",
                "name": "sage",
                "value": "s",
                "path": "/",
            },
        ],
    }

    header = mod._ezproxy_cookie_header(
        config,
        "https://www-tandfonline-com.eux.idm.oclc.org/doi/pdf/10.1/example",
    )

    assert header == "root=r; idm=i"


def test_find_oa_url_accepts_crossref_pdf_url_when_content_type_unspecified(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_crossref_pdf_under_test")

    def fake_get_json(url, timeout=10):
        if "api.crossref.org" in url:
            return {
                "status": "ok",
                "message": {
                    "link": [
                        {
                            "content-type": "unspecified",
                            "URL": "http://academic.oup.com/mind/article-pdf/110/438/504/3033370/1100504.pdf",
                        }
                    ]
                },
            }
        return None

    monkeypatch.setattr(mod, "_get_json_urllib", fake_get_json)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    assert mod.find_oa_url("10.1093/mind/110.438.504") == (
        "http://academic.oup.com/mind/article-pdf/110/438/504/3033370/1100504.pdf"
    )


def test_find_oa_url_accepts_cambridge_crossref_content_view_link(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_crossref_cambridge_under_test")

    def fake_get_json(url, timeout=10):
        if "api.crossref.org" in url:
            return {
                "status": "ok",
                "message": {
                    "link": [
                        {
                            "content-type": "unspecified",
                            "URL": "https://www.cambridge.org/core/services/aop-cambridge-core/content/view/S0036930622000394",
                        }
                    ]
                },
            }
        return None

    monkeypatch.setattr(mod, "_get_json_urllib", fake_get_json)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    assert mod.find_oa_url("10.1017/s0036930622000394") == (
        "https://www.cambridge.org/core/services/aop-cambridge-core/content/view/S0036930622000394"
    )


def test_informs_proxied_host_matches_ezproxy_pdf_pattern():
    mod = _load_module(DOWNLOAD, "download_informs_pattern_under_test")
    final_url = "https://pubsonline-informs-org.eux.idm.oclc.org/doi/10.1287/ijoc.2024.0736"

    assert mod._publisher_pdf_urls_from_article_url(final_url) == [
        "https://pubsonline-informs-org.eux.idm.oclc.org/doi/pdf/10.1287/ijoc.2024.0736"
    ]


def test_informs_doi_matches_publisher_direct_pdf_pattern():
    mod = _load_module(DOWNLOAD, "download_informs_direct_under_test")
    doi = "10.1287/ijoc.2024.0736"
    suffix = doi.split("/", 1)[-1]

    urls = [
        pattern.format(doi=doi, suffix=suffix)
        for prefix, pattern in mod._PUBLISHER_DIRECT_URLS
        if doi.startswith(prefix)
    ]

    assert "https://pubsonline.informs.org/doi/pdf/10.1287/ijoc.2024.0736" in urls


def test_annualreviews_doi_has_ezproxy_and_direct_pdf_routes():
    mod = _load_module(DOWNLOAD, "download_annualreviews_routes_under_test")
    doi = "10.1146/annurev-soc-031021-041439"
    final_url = "https://www-annualreviews-org.eux.idm.oclc.org/content/journals/10.1146/annurev-soc-031021-041439"

    proxied = mod._publisher_pdf_urls_from_article_url(final_url)
    direct = [
        pattern.format(doi=doi, suffix=doi.split("/", 1)[-1])
        for prefix, pattern in mod._PUBLISHER_DIRECT_URLS
        if doi.startswith(prefix)
    ]

    assert proxied == [
        "https://www-annualreviews-org.eux.idm.oclc.org/doi/pdf/10.1146/annurev-soc-031021-041439"
    ]
    assert direct == [
        "https://www.annualreviews.org/doi/pdf/10.1146/annurev-soc-031021-041439"
    ]


def test_wiley_legacy_doi_prefers_crossref_pdf_route():
    mod = _load_module(DOWNLOAD, "download_wiley_legacy_routes_under_test")
    doi = "10.1111/j.2041-6962.1988.tb00448.x"
    final_url = (
        "https://onlinelibrary-wiley-com.eux.idm.oclc.org/doi/"
        "10.1111/j.2041-6962.1988.tb00448.x"
    )

    proxied = mod._publisher_pdf_urls_from_article_url(final_url)
    direct = [
        pattern.format(doi=doi, suffix=doi.split("/", 1)[-1])
        for prefix, pattern in mod._PUBLISHER_DIRECT_URLS
        if doi.startswith(prefix)
    ]

    expected = [
        f"https://onlinelibrary.wiley.com/doi/pdf/{doi}",
        f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}",
        f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true",
    ]
    assert proxied == [
        url.replace(
            "onlinelibrary.wiley.com",
            "onlinelibrary-wiley-com.eux.idm.oclc.org",
        )
        for url in expected
    ]
    assert direct == expected


def test_sciencedirect_article_url_detection_accepts_native_and_ezproxy_urls():
    mod = _load_module(DOWNLOAD, "download_sciencedirect_url_under_test")

    assert mod._is_sciencedirect_article_url(
        "https://www.sciencedirect.com/science/article/pii/S0378216626001025"
    )
    assert mod._is_sciencedirect_article_url(
        "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S0378216626001025"
    )
    assert not mod._is_sciencedirect_article_url(
        "https://www.sciencedirect.com/topics/social-sciences/conversation-analysis"
    )
    assert not mod._is_sciencedirect_article_url(
        "https://example.org/science/article/pii/S0378216626001025"
    )
    assert not mod._is_sciencedirect_article_url(
        "https://www-sciencedirect-com.example.org/science/article/pii/S0378216626001025"
    )


def test_sciencedirect_article_url_expands_to_pdf_urls():
    mod = _load_module(DOWNLOAD, "download_sciencedirect_pdf_url_under_test")

    assert mod._sciencedirect_pdf_urls_from_article_url(
        "https://www.sciencedirect.com/science/article/pii/S1364661326001087"
    ) == [
        "https://www.sciencedirect.com/science/article/pii/S1364661326001087/pdfft?isDTMRedir=true&download=true",
        "https://www.sciencedirect.com/science/article/pii/S1364661326001087/pdf",
    ]
    assert mod._sciencedirect_pdf_urls_from_article_url(
        "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S1364661326001087"
    )[0] == (
        "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/"
        "S1364661326001087/pdfft?isDTMRedir=true&download=true"
    )
    assert mod._sciencedirect_pdf_urls_from_article_url(
        "https://www.sciencedirect.com/topics/social-sciences/conversation-analysis"
    ) == []


def test_cell_fulltext_url_expands_to_pdf_urls():
    mod = _load_module(DOWNLOAD, "download_cell_url_under_test")
    fulltext = "https://www.cell.com/trends/cognitive-sciences/fulltext/S1364-6613(26)00108-7"

    assert mod._is_cell_article_url(fulltext)
    assert mod._cell_pdf_urls_from_article_url(fulltext) == [
        "https://www.cell.com/action/showPdf?pii=S1364-6613%2826%2900108-7",
        "https://www.cell.com/trends/cognitive-sciences/pdf/S1364-6613%2826%2900108-7.pdf",
    ]
    assert mod._cell_sciencedirect_urls_from_pii(
        "S1364-6613(26)00108-7"
    ) == [
        "https://www.sciencedirect.com/science/article/pii/S1364661326001087",
        "https://www.sciencedirect.com/science/article/pii/S1364661326001087/pdfft?isDTMRedir=true&download=true",
    ]
    assert mod._cell_pdf_urls_from_article_url(
        "https://www-cell-com.eux.idm.oclc.org/trends/cognitive-sciences/fulltext/S1364-6613(26)00108-7"
    )[1] == (
        "https://www-cell-com.eux.idm.oclc.org/trends/cognitive-sciences/pdf/"
        "S1364-6613%2826%2900108-7.pdf"
    )
    assert mod._cell_pdf_urls_from_article_url(
        "https://www.cell.com/about"
    ) == []


def test_cell_doi_expands_pii_style_suffix_to_show_pdf_url():
    mod = _load_module(DOWNLOAD, "download_cell_doi_under_test")

    assert mod._cell_pdf_urls_from_doi("10.1016/S1364-6613(26)00108-7") == [
        "https://www.cell.com/action/showPdf?pii=S1364-6613%2826%2900108-7"
    ]
    assert mod._cell_pdf_urls_from_doi("10.1016/j.pragma.2026.04.009") == []
    assert mod._cell_pdf_urls_from_doi("10.1287/ijoc.2024.0736") == []


def test_cell_pii_resolves_to_doi_via_crossref(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_cell_pii_doi_under_test")

    def fake_get_json_urllib(url, timeout=15):
        assert "filter=alternative-id:S1364661326001087" in url
        return {"message": {"items": [{"DOI": "10.1016/j.tics.2026.05.002"}]}}

    monkeypatch.setattr(mod, "_get_json_urllib", fake_get_json_urllib)

    assert mod._doi_from_cell_pii("S1364-6613(26)00108-7") == "10.1016/j.tics.2026.05.002"


def test_paper_diagnose_retains_redacted_native_jstor_403(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_jstor_403_diagnose_under_test")
    requested = "https://www.jstor.org/stable/43154235?token=never-print-me"
    seen_headers = []

    def fake_urlopen(request, timeout):
        seen_headers.append(dict(request.header_items()))
        raise urllib.error.HTTPError(
            requested,
            403,
            "Forbidden",
            {"content-type": "text/html"},
            io.BytesIO(b"<html>access denied</html>"),
        )

    monkeypatch.setenv("QUASI_COOKIECLOUD_EZPROXY_DOMAIN", "eux.idm.oclc.org")
    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: (_ for _ in ()).throw(AssertionError("direct probe must not fetch CookieCloud")),
    )
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: (_ for _ in ()).throw(AssertionError("diagnose must not retry")))

    report = mod.diagnose_paper_url(requested)

    assert report == {
        "schema_version": "quasi.download.diagnose/0.1",
        "requested_url": "https://www.jstor.org/stable/43154235",
        "final_url": "https://www.jstor.org/stable/43154235",
        "mode": "direct",
        "http_status": 403,
        "content_type": "text/html",
        "classification": "access_denied",
        "retryable": False,
        "ezproxy": {
            "configured": True,
            "target_matches_proxy": False,
            "attempted": False,
        },
        "wrote_file": False,
    }
    assert "Cookie" not in seen_headers[0]
    assert "never-print-me" not in json.dumps(report)
    assert list(tmp_path.iterdir()) == []


def test_paper_diagnose_classifies_landing_cloudflare_pdf_and_connection_error(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_diagnose_classification_under_test")
    url = "https://www.jstor.org/stable/43154235"

    responses = [
        _FakeUrlResponse(url, b"<html>institution login</html>", headers={"content-type": "text/html"}),
        urllib.error.HTTPError(
            url,
            403,
            "Forbidden",
            {"content-type": "text/html", "cf-ray": "abc", "server": "cloudflare"},
            io.BytesIO(b"<title>Just a moment...</title>"),
        ),
        _FakeUrlResponse(url, b"%PDF-1.7", headers={"content-type": "application/pdf"}),
        urllib.error.URLError("offline"),
    ]

    def fake_urlopen(_request, timeout):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    reports = [mod.diagnose_paper_url(url) for _ in range(4)]

    assert [(report["http_status"], report["classification"]) for report in reports] == [
        (200, "html_landing"),
        (403, "cloudflare_challenge"),
        (200, "pdf"),
        (None, "connection_error"),
    ]
    assert reports[-1]["retryable"] is True
    assert all(report["wrote_file"] is False for report in reports)


def test_paper_diagnose_parser_and_handler_never_start_acquisition(monkeypatch, capsys):
    mod = _load_module(DOWNLOAD, "download_diagnose_command_under_test")
    url = "https://www.jstor.org/stable/43154235?signature=do-not-print"
    args = mod._build_parser().parse_args([
        "paper", "diagnose", "--url", url, "--timeout", "12", "--json",
    ])

    def acquisition_called(*_args, **_kwargs):
        raise AssertionError("diagnostic must not start acquisition")

    monkeypatch.setattr(mod, "download_paper", acquisition_called)
    monkeypatch.setattr(mod, "download_pdf_from_url", acquisition_called)
    monkeypatch.setattr(mod, "load_ezproxy_config", lambda: None)
    monkeypatch.setattr(
        mod.urllib.request,
        "urlopen",
        lambda _request, timeout: _FakeUrlResponse(url, b"<html>landing</html>", headers={"content-type": "text/html"}),
    )

    assert args.func(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["requested_url"] == "https://www.jstor.org/stable/43154235"
    assert payload["classification"] == "html_landing"
    assert payload["wrote_file"] is False
    assert "do-not-print" not in json.dumps(payload)


def test_paper_diagnose_via_ezproxy_redacts_session_data(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_diagnose_ezproxy_under_test")
    url = "https://www.jstor.org/stable/43154235?signature=do-not-print"
    config = {
        "domain": "eux.idm.oclc.org",
        "login_url": "https://login.eux.idm.oclc.org/login?url=",
        "cookie": "never-print-cookie",
    }
    calls = []

    class FakeResponse:
        url = "https://www-jstor-org.eux.idm.oclc.org/stable/43154235?session=do-not-print"
        status_code = 200
        headers = {"content-type": "application/pdf"}
        closed = False

        @property
        def content(self):
            raise AssertionError("diagnostic must stream a bounded response prefix")

        def iter_content(self, *, chunk_size):
            assert chunk_size <= mod._DIAGNOSE_BODY_LIMIT
            yield b"%PDF-1.7"

        def close(self):
            self.closed = True

    response = FakeResponse()

    class FakeSession:
        def get(self, request_url, **kwargs):
            calls.append((request_url, kwargs))
            return response

    monkeypatch.setattr(mod, "load_ezproxy_config", lambda: config)
    monkeypatch.setattr(mod, "_build_ezproxy_session", lambda _config: FakeSession())
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: (_ for _ in ()).throw(AssertionError("diagnose must not retry")))

    report = mod.diagnose_paper_url(url, via_ezproxy=True)

    assert calls == [(
        f"{config['login_url']}{url}",
        {"allow_redirects": True, "timeout": 30, "stream": True},
    )]
    assert response.closed is True
    assert report["mode"] == "ezproxy"
    assert report["classification"] == "pdf"
    assert report["ezproxy"] == {
        "configured": True,
        "target_matches_proxy": False,
        "attempted": True,
    }
    rendered = json.dumps(report)
    assert "never-print-cookie" not in rendered
    assert "do-not-print" not in rendered


def test_paper_diagnose_stream_reader_stays_bounded_for_oversized_chunks():
    mod = _load_module(DOWNLOAD, "download_diagnose_bounded_stream_under_test")

    class OversizedChunkResponse:
        @property
        def content(self):
            raise AssertionError("stream reader must not materialise response.content")

        def iter_content(self, *, chunk_size):
            assert chunk_size <= mod._DIAGNOSE_BODY_LIMIT
            yield b"x" * (mod._DIAGNOSE_BODY_LIMIT + 1)
            raise AssertionError("reader must stop after its bounded prefix")

    content = mod._read_diagnostic_response_body(OversizedChunkResponse())

    assert content == b"x" * mod._DIAGNOSE_BODY_LIMIT


def test_paper_diagnose_observes_retryable_status_once(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_diagnose_no_retry_under_test")
    url = "https://www.jstor.org/stable/43154235"
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        raise urllib.error.HTTPError(
            url,
            503,
            "Service Unavailable",
            {"content-type": "text/html"},
            io.BytesIO(b"<html>try later</html>"),
        )

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: (_ for _ in ()).throw(AssertionError("direct probe must not fetch CookieCloud")),
    )
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: (_ for _ in ()).throw(AssertionError("diagnose must not retry")))

    report = mod.diagnose_paper_url(url)

    assert calls == [(url, 30)]
    assert report["http_status"] == 503
    assert report["classification"] == "html_landing"
    assert report["retryable"] is True


def test_paper_diagnose_direct_never_injects_proxy_cookies(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_diagnose_cookie_boundary_under_test")
    url = "https://www.jstor.org/stable/43154235"
    sent_headers = []

    def fake_urlopen(request, timeout):
        sent_headers.append(dict(request.header_items()))
        return _FakeUrlResponse(url, b"<html>landing</html>", headers={"content-type": "text/html"})

    monkeypatch.setenv("QUASI_COOKIECLOUD_EZPROXY_DOMAIN", "jstor.org")
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)

    report = mod.diagnose_paper_url(url)

    assert report["ezproxy"] == {
        "configured": True,
        "target_matches_proxy": True,
        "attempted": False,
    }
    assert all(name.lower() != "cookie" for name in sent_headers[0])


def test_paper_diagnose_reports_unavailable_ezproxy_without_target_request(monkeypatch):
    mod = _load_module(DOWNLOAD, "download_diagnose_ezproxy_unavailable_under_test")
    url = "https://www.jstor.org/stable/43154235"

    monkeypatch.delenv("QUASI_COOKIECLOUD_EZPROXY_DOMAIN", raising=False)
    monkeypatch.setattr(mod, "load_ezproxy_config", lambda: None)
    monkeypatch.setattr(
        mod,
        "_build_ezproxy_session",
        lambda _config: (_ for _ in ()).throw(AssertionError("no session without config")),
    )

    report = mod.diagnose_paper_url(url, via_ezproxy=True)

    assert report["mode"] == "ezproxy"
    assert report["http_status"] is None
    assert report["classification"] == "ezproxy_unavailable"
    assert report["retryable"] is False
    assert report["ezproxy"] == {
        "configured": False,
        "target_matches_proxy": False,
        "attempted": False,
    }


def test_paper_diagnose_rejects_invalid_or_userinfo_urls(monkeypatch, capsys):
    mod = _load_module(DOWNLOAD, "download_diagnose_invalid_url_under_test")
    monkeypatch.setattr(
        mod,
        "diagnose_paper_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("invalid URLs must not be observed")),
    )

    for url in ("ftp://www.jstor.org/stable/43154235", "https://token@www.jstor.org/stable/43154235"):
        args = mod._build_parser().parse_args(["paper", "diagnose", "--url", url])
        assert args.func(args) == 2
        assert "HTTP(S) URL without userinfo" in capsys.readouterr().err


def test_ezproxy_login_detection_does_not_treat_cloudflare_as_cookie_expired():
    mod = _load_module(DOWNLOAD, "download_cloudflare_detection_under_test")
    cloudflare_html = b"""
    <!DOCTYPE html><html><head><title>Just a moment...</title></head>
    <body><script>window._cf_chl_opt = {}</script></body></html>
    """

    assert mod._is_cloudflare_challenge(
        cloudflare_html,
        {"server": "cloudflare", "cf-ray": "abc"},
    )
    mod._raise_if_ezproxy_login_page(
        "https://www-cell-com.eux.idm.oclc.org/action/showPdf",
        "https://login.eux.idm.oclc.org/login?url=",
        cloudflare_html,
        headers={"server": "cloudflare", "cf-ray": "abc"},
    )


def test_ezproxy_login_detection_raises_for_shibboleth_login():
    mod = _load_module(DOWNLOAD, "download_shibboleth_detection_under_test")
    shib_html = b"""
    <html><head><title>Shibboleth Authentication Request</title></head>
    <body><form><input type="password" name="password"></form></body></html>
    """

    try:
        mod._raise_if_ezproxy_login_page(
            "https://login.eux.idm.oclc.org/login?url=https://www.cell.com/action/showPdf",
            "https://login.eux.idm.oclc.org/login?url=",
            shib_html,
            history_len=0,
        )
    except mod.EZProxyCookieExpired:
        pass
    else:
        raise AssertionError("Shibboleth login page should raise EZProxyCookieExpired")


def test_ezproxy_tries_cell_showpdf_candidate_first(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_cell_ezproxy_candidate_under_test")
    calls: list[str] = []

    class FakeSession:
        headers = {}

        def get(self, url, **kwargs):
            calls.append(url)
            if "doi.org" in url:
                return SimpleNamespace(
                    url="https://www-cell-com.eux.idm.oclc.org/trends/cognitive-sciences/fulltext/S1364-6613(26)00108-7",
                    content=b"<html>landing</html>",
                    status_code=200,
                    history=[object()],
                    headers={},
                )
            return SimpleNamespace(
                url="https://www-cell-com.eux.idm.oclc.org/action/showPdf?pii=S1364-6613%2826%2900108-7",
                content=b"%PDF- cell via ezproxy",
                status_code=200,
                history=[object()],
                headers={"content-type": "application/pdf;charset=UTF-8"},
            )

    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: {"login_url": "https://login.eux.idm.oclc.org/login?url=", "cookie": "x"},
    )
    monkeypatch.setattr(mod, "_build_ezproxy_session", lambda config: FakeSession())
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: None)

    result = mod.try_ezproxy_download(
        "10.1016/j.tics.2026.05.002",
        str(tmp_path / "paper.pdf"),
        cell_pdf_urls=["https://www.cell.com/action/showPdf?pii=S1364-6613%2826%2900108-7"],
    )

    assert result is True
    # The rewritten proxy host is tried before the login redirect: the
    # institutional session cookies live on the rewritten host, not on login.
    assert calls[1] == (
        "https://www-cell-com.eux.idm.oclc.org/action/showPdf"
        "?pii=S1364-6613%2826%2900108-7"
    )
    assert (tmp_path / "paper.pdf").read_bytes().startswith(b"%PDF-")


def test_write_text_fallback_from_article_html(tmp_path):
    mod = _load_module(DOWNLOAD, "download_cell_text_fallback_under_test")
    html = b"""
    <html><body><article>
    <h1>Timescapes of non-human experience</h1>
    <h2>Abstract</h2><p>Timescapes of non-human experience are discussed here.</p>
    <h2>References</h2><p>Reference content.</p>
    </article></body></html>
    """ + b"article text " * 80
    out = tmp_path / "paper.txt"

    assert mod._write_text_fallback_from_html(
        html,
        str(out),
        headers={"content-type": "text/html"},
        expected_title="Timescapes of non-human experience",
    )
    assert "Timescapes of non-human experience" in out.read_text(encoding="utf-8")


def test_download_paper_adds_cell_pdf_hints_before_fetch(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_cell_hints_under_test")
    tried: list[str] = []

    def fake_download_pdf_from_url(url, output_path, timeout=60, **kwargs):
        tried.append(url)
        if "/action/showPdf" in url:
            Path(output_path).write_bytes(b"%PDF- cell")
            return True
        return False

    monkeypatch.setattr(mod, "download_pdf_from_url", fake_download_pdf_from_url)

    result = mod.download_paper(
        url="https://www.cell.com/trends/cognitive-sciences/fulltext/S1364-6613(26)00108-7",
        output_dir=str(tmp_path),
        filename="cell-paper",
    )

    assert result == str(tmp_path / "cell-paper.pdf")
    assert tried == [
        "https://www.cell.com/trends/cognitive-sciences/fulltext/S1364-6613(26)00108-7",
        "https://www.cell.com/action/showPdf?pii=S1364-6613%2826%2900108-7",
    ]


def test_ezproxy_sciencedirect_url_tracking_deduplicates(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_ezproxy_sciencedirect_dedupe_under_test")
    article_url = "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S0378216626001025"

    class FakeResponse:
        url = article_url
        content = b"<html></html>"
        status_code = 200
        history = [object()]

    class FakeSession:
        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: {"login_url": "https://ezproxy.example.edu/login?url=", "cookie": "x"},
    )
    monkeypatch.setattr(mod, "_build_ezproxy_session", lambda config: FakeSession())

    sciencedirect_urls = [article_url]

    assert not mod.try_ezproxy_download(
        "10.1016/j.pragma.2026.04.009",
        str(tmp_path / "paper.pdf"),
        sciencedirect_urls=sciencedirect_urls,
    )
    assert sciencedirect_urls == [article_url]


def test_inspect_downloaded_file_reads_txt_front_text(tmp_path):
    mod = _load_module(DOWNLOAD, "download_text_inspect_under_test")
    text_path = tmp_path / "paper.txt"
    text_path.write_text(
        "Making sense of conduct: A conversation analysis of therapist formulation "
        "in interaction with autistic children\n"
        "Doe and Roe discuss therapist formulation in detail. "
        + "article text " * 120,
        encoding="utf-8",
    )

    inspect = mod._inspect_downloaded_file(text_path)

    assert inspect["format"] == "txt"
    assert inspect["readability"] == "text"
    assert inspect["front_text"].startswith("Making sense of conduct")
    assert inspect["fallback_hint"] is None


def test_verify_source_content_accepts_txt_title_match(tmp_path):
    mod = _load_module(DOWNLOAD, "download_text_verify_under_test")
    text_path = tmp_path / "paper.txt"
    text_path.write_text(
        "Making sense of conduct: A conversation analysis of therapist formulation "
        "in interaction with autistic children\n"
        + "therapist formulation autistic children " * 40,
        encoding="utf-8",
    )

    assert mod.verify_source_content(
        str(text_path),
        expected_title=(
            "Making sense of conduct: A conversation analysis of therapist formulation "
            "in interaction with autistic children"
        ),
    )


def test_verify_source_content_rejects_weak_partial_title_match(tmp_path):
    mod = _load_module(DOWNLOAD, "download_text_verify_weak_title_under_test")
    text_path = tmp_path / "wrong-paper.txt"
    text_path.write_text(
        "Language acquisition across linguistic and cognitive systems\n"
        "Edited by Michèle Kail and Maya Hickmann\n"
        + "language acquisition linguistic cognitive systems " * 40,
        encoding="utf-8",
    )

    assert not mod.verify_source_content(
        str(text_path),
        expected_title=(
            "Some and or in second language acquisition: Exploring linguistic "
            "and cognitive factors"
        ),
    )


def test_verify_source_content_rejects_same_author_related_title(tmp_path):
    mod = _load_module(DOWNLOAD, "download_text_verify_related_title_under_test")
    text_path = tmp_path / "related-paper.txt"
    text_path.write_text(
        "We need to talk about hearer's meaning!\n"
        "Maj-Britt Mosegaard Hansen and Marina Terkourafi\n"
        + "hearer's meaning pragmatic theory speaker intentions " * 40,
        encoding="utf-8",
    )

    assert not mod.verify_source_content(
        str(text_path),
        expected_author="Marina Terkourafi",
        expected_title="Hearer's Meaning 2.0: A reply to Li and Xie (2025)",
    )


def test_accept_moves_temp_text_paper_to_sources(tmp_path):
    project = tmp_path / "project"
    temp_dir = project / ".quasi" / "temp" / "downloads"
    temp_dir.mkdir(parents=True)
    src = temp_dir / "candidate.txt"
    src.write_text("Making sense of conduct\n" + "article text " * 120, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(DOWNLOAD),
            "accept",
            "--path",
            str(src),
            "--slug",
            "making-sense-conduct-2026",
            "--kind",
            "paper",
            "--json",
        ],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["kind"] == "paper"
    assert Path(payload["path"]).name == "making-sense-conduct-2026.txt"
    assert Path(payload["path"]).read_text(encoding="utf-8").startswith("Making sense")


def test_download_paper_stops_after_pdf_sources_fail(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_sciencedirect_no_text_flow_under_test")
    article_url = "https://www-sciencedirect-com.eux.idm.oclc.org/science/article/pii/S0378216626001025"

    monkeypatch.setattr(mod, "download_pdf_from_url", lambda *args, **kwargs: False)
    monkeypatch.setattr(mod, "find_oa_url", lambda doi: None)
    monkeypatch.setattr(mod, "try_scihub_download", lambda *args: False)
    monkeypatch.setattr(mod, "_try_publisher_direct", lambda *args: False)
    monkeypatch.setattr(mod, "find_wayback_url", lambda doi: None)
    monkeypatch.setattr(mod, "_kagi_discover_paper", lambda title, author=None: ([], []))
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)

    def fake_ezproxy(doi, output_path, sciencedirect_urls=None, **kwargs):
        if sciencedirect_urls is not None:
            sciencedirect_urls.append(article_url)
        return False

    monkeypatch.setattr(mod, "_try_ezproxy_with_refresh", fake_ezproxy)

    result = mod.download_paper(
        doi="10.1016/j.pragma.2026.04.009",
        output_dir=str(tmp_path),
        filename="making-sense-conduct-2026",
        verify_title=(
            "Making sense of conduct: A conversation analysis of therapist formulation "
            "in interaction with autistic children"
        ),
    )

    assert result is None
    assert not hasattr(mod, "_dokobot_read_url")
    assert not (tmp_path / "making-sense-conduct-2026.txt").exists()
    assert not (tmp_path / "making-sense-conduct-2026.pdf").exists()


@pytest.mark.parametrize(
    (
        "initial_state",
        "interval",
        "current_time",
        "expected_wait",
        "expected_sleeps",
        "expected_final_state",
    ),
    [
        (None, 30, 1000.0, 0.0, [], "1000.0"),
        ("1000.0", 30, 1005.0, 25.0, [25.0], "1005.0"),
        ("2000.0", 30, 1000.0, 30.0, [30.0], "1000.0"),
        (None, 0, 1000.0, 0.0, [], None),
        ("not-a-number", 30, 1000.0, 0.0, [], "1000.0"),
    ],
    ids=(
        "first-call",
        "remaining-interval",
        "future-capped",
        "zero-noop",
        "corrupt-as-no-prior",
    ),
)
def test_ezproxy_throttle_single_process_cases(
    tmp_path,
    initial_state,
    interval,
    current_time,
    expected_wait,
    expected_sleeps,
    expected_final_state,
):
    mod = _load_module(DOWNLOAD, "download_throttle_single_process_under_test")
    state = tmp_path / "ezproxy-throttle.state"
    if initial_state is not None:
        state.write_text(initial_state)
    recorded: list[float] = []

    waited = mod._ezproxy_throttle(
        state_path=state,
        interval=interval,
        now=lambda: current_time,
        sleep=recorded.append,
    )

    assert waited == expected_wait
    assert recorded == expected_sleeps
    final_state = state.read_text().strip() if state.exists() else None
    assert final_state == expected_final_state


def test_ezproxy_throttle_serializes_across_processes(tmp_path):
    """Real cross-process proof: the exclusive lock is held across the sleep,
    so concurrent processes pass the gate at least one interval apart. A version
    that released the lock before sleeping would let all workers pass nearly
    simultaneously and fail this test."""
    import time

    state = tmp_path / "ezproxy-throttle.state"
    worker = tmp_path / "throttle_worker.py"
    worker.write_text(
        "import sys, time, importlib.util\n"
        "from pathlib import Path\n"
        "path = sys.argv[1]\n"
        "sys.path.insert(0, str(Path(path).parent))\n"
        "spec = importlib.util.spec_from_file_location('dl_worker', path)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "mod._ezproxy_throttle(state_path=sys.argv[2], interval=1.0)\n"
        "sys.stdout.write(repr(time.time()))\n"
    )

    procs = [
        subprocess.Popen(
            [sys.executable, str(worker), str(DOWNLOAD), str(state)],
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    times = sorted(float(p.communicate()[0]) for p in procs)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(g >= 0.8 for g in gaps), (
        f"gate passes too close together (lock not held across sleep?): {gaps}"
    )


def test_try_ezproxy_download_skips_throttle_when_unconfigured(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_ezproxy_unconfigured_under_test")

    calls: list[int] = []
    monkeypatch.setattr(mod, "load_ezproxy_config", lambda: None)
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: calls.append(1))

    out = tmp_path / "out.pdf"
    result = mod.try_ezproxy_download("10.1/example", str(out))

    assert result is False
    assert calls == []  # not configured -> gate never reached


def test_try_ezproxy_download_calls_throttle_when_configured(tmp_path, monkeypatch):
    import requests
    mod = _load_module(DOWNLOAD, "download_ezproxy_configured_under_test")

    calls: list[int] = []
    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: {
            "login_url": "https://ezproxy.example.edu/login?url=",
            "cookie_records": [
                {"name": "a", "value": "b", "domain": "ezproxy.example.edu", "path": "/"}
            ],
        },
    )
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: calls.append(1))

    def _boom(*a, **k):
        raise requests.RequestException("no network in test")

    monkeypatch.setattr(mod, "_retry", _boom)

    out = tmp_path / "out.pdf"
    result = mod.try_ezproxy_download("10.1/example", str(out))

    assert result is False
    assert calls == [1]  # gate reached exactly once when configured


@pytest.mark.parametrize(
    ("article_url", "expected_urls"),
    [
        (
            "https://www.jstor.org/stable/43154235",
            ["https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1"],
        ),
        (
            "https://www.jstor.org/stable/10.1086/691062",
            ["https://www.jstor.org/stable/pdf/10.1086/691062.pdf?acceptTC=1"],
        ),
        (
            "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf"
            "?refreqid=fastly-default%3Aabc&acceptTC=1",
            [
                "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf"
                "?acceptTC=1"
            ],
        ),
        ("https://www.jstor.org/", []),
        ("https://www.sciencedirect.com/stable/43154235", []),
    ],
    ids=(
        "bare-stable-id",
        "doi-stable-id",
        "already-proxied-pdf",
        "root-miss",
        "foreign-host-miss",
    ),
)
def test_jstor_pdf_urls_from_article_url(article_url, expected_urls):
    mod = _load_module(DOWNLOAD, "download_jstor_urls_under_test")

    assert mod._jstor_pdf_urls_from_article_url(article_url) == expected_urls


@pytest.mark.parametrize(
    ("host", "expected_host"),
    [
        (
            "pubsonline-informs-org.eux.idm.oclc.org",
            "pubsonline.informs.org",
        ),
        ("www.jstor.org", "www.jstor.org"),
        ("link-springer.com", "link-springer.com"),
    ],
    ids=("ezproxy-rewritten", "native-host", "real-dash"),
)
def test_unproxy_host(host, expected_host):
    mod = _load_module(DOWNLOAD, "download_unproxy_host_under_test")

    assert mod._unproxy_host(host) == expected_host


@pytest.mark.parametrize(
    ("host", "publisher_domain", "expected"),
    [
        ("www-jstor-org.eux.idm.oclc.org", "jstor.org", True),
        ("academic.oup.com", "oup.com", True),
        ("direct.mit.edu", "mit.edu", True),
        ("notjstor.org", "jstor.org", False),
    ],
    ids=(
        "ezproxy-rewritten",
        "publisher-subdomain",
        "publisher-native",
        "lookalike-miss",
    ),
)
def test_is_publisher_host(host, publisher_domain, expected):
    mod = _load_module(DOWNLOAD, "download_is_publisher_host_under_test")

    assert mod._is_publisher_host(host, publisher_domain) is expected


@pytest.mark.parametrize(
    ("article_url", "expected_doi"),
    [
        (
            "https://www.tandfonline.com/doi/abs/10.1080/00048402.2019.1618352",
            "10.1080/00048402.2019.1618352",
        ),
        ("https://www.jstor.org/stable/43154235", None),
    ],
    ids=("doi-in-path", "no-doi-in-path"),
)
def test_doi_from_url_path(article_url, expected_doi):
    mod = _load_module(DOWNLOAD, "download_doi_from_url_path_under_test")

    assert mod._doi_from_url_path(article_url) == expected_doi


@pytest.mark.parametrize(
    ("article_url", "expected_urls"),
    [
        (
            "https://www.tandfonline.com/doi/abs/10.1080/00048402.2019.1618352",
            [
                "https://www.tandfonline.com/doi/pdf/10.1080/00048402.2019.1618352",
                "https://www.tandfonline.com/doi/pdf/10.1080/00048402.2019.1618352"
                "?download=true",
            ],
        ),
        ("https://example.org/doi/abs/10.1080/00048402.2019.1618352", []),
    ],
    ids=("known-publisher", "unknown-publisher"),
)
def test_publisher_pdf_urls_from_article_url(article_url, expected_urls):
    mod = _load_module(DOWNLOAD, "download_publisher_pdf_urls_under_test")

    assert mod._publisher_pdf_urls_from_article_url(article_url) == expected_urls


@pytest.mark.parametrize(
    ("article_url", "expected", "expected_is_member"),
    [
        (
            "https://www.jstor.org/stable/43154235",
            ["https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1"],
            False,
        ),
        (
            "https://journals.sagepub.com/doi/abs/10.1177/0959354319898450",
            "https://journals.sagepub.com/doi/pdf/10.1177/0959354319898450",
            True,
        ),
        ("", [], False),
    ],
    ids=("jstor-family", "publisher-family", "empty-miss"),
)
def test_pdf_urls_from_article_url(article_url, expected, expected_is_member):
    mod = _load_module(DOWNLOAD, "download_pdf_url_dispatcher_under_test")

    urls = mod._pdf_urls_from_article_url(article_url)
    if expected_is_member:
        assert expected in urls
    else:
        assert urls == expected


def test_ezproxy_request_urls_prefer_rewritten_host_over_login():
    mod = _load_module(DOWNLOAD, "download_ezproxy_request_forms_under_test")
    config = {
        "login_url": "https://login.eux.idm.oclc.org/login?url=",
        "domain": "idm.oclc.org",
        "cookie_records": [
            # The suffix the user's own browsing actually issued cookies on.
            {"name": "UUID", "value": "x",
             "domain": "www-jstor-org.eux.idm.oclc.org", "path": "/"},
            {"name": "_clsk", "value": "y", "domain": "idm.oclc.org", "path": "/"},
        ],
    }

    assert mod._ezproxy_host_suffix(config) == "eux.idm.oclc.org"
    assert mod._ezproxy_request_urls(
        "https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1", config
    ) == [
        "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf?acceptTC=1",
        "https://login.eux.idm.oclc.org/login?url="
        "https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1",
    ]
    # An already-proxied URL is requested as-is, never double-wrapped.
    assert mod._ezproxy_request_urls(
        "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf", config
    ) == ["https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf"]


@pytest.mark.parametrize(
    ("login_url", "expected_suffix"),
    [
        ("https://login.eux.idm.oclc.org/login?url=", "eux.idm.oclc.org"),
        ("https://ezproxy.lib.example.edu/login?url=", "lib.example.edu"),
        ("https://eux.idm.oclc.org/login?url=", "eux.idm.oclc.org"),
    ],
    ids=("login-service-label", "ezproxy-service-label", "bare-host"),
)
def test_ezproxy_host_suffix_falls_back_to_login_host_label(
    login_url,
    expected_suffix,
):
    mod = _load_module(DOWNLOAD, "download_ezproxy_suffix_fallback_under_test")

    assert mod._ezproxy_host_suffix({"login_url": login_url}) == expected_suffix


def test_download_paper_adds_jstor_pdf_hint_before_fetch(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_jstor_hints_under_test")
    tried: list[str] = []

    def fake_download_pdf_from_url(url, output_path, timeout=60, **kwargs):
        tried.append(url)
        if "/stable/pdf/" in url:
            Path(output_path).write_bytes(b"%PDF- jstor")
            return True
        return False

    monkeypatch.setattr(mod, "download_pdf_from_url", fake_download_pdf_from_url)

    result = mod.download_paper(
        url="https://www.jstor.org/stable/43154235",
        output_dir=str(tmp_path),
        filename="jstor-paper",
    )

    assert result == str(tmp_path / "jstor-paper.pdf")
    assert tried == [
        "https://www.jstor.org/stable/43154235",
        "https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1",
    ]


def test_download_paper_routes_url_only_request_through_ezproxy(monkeypatch, tmp_path):
    """A URL-only request must reach the proxy; before this it never did."""
    mod = _load_module(DOWNLOAD, "download_url_only_ezproxy_under_test")
    requested: list[str] = []

    class FakeSession:
        headers: dict = {}

        def get(self, url, **kwargs):
            requested.append(url)
            if "/stable/pdf/" in url:
                return SimpleNamespace(
                    url="https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf",
                    content=b"%PDF- jstor via ezproxy",
                    status_code=200,
                    history=[object()],
                    headers={"content-type": "application/pdf"},
                )
            return SimpleNamespace(
                url="https://www-jstor-org.eux.idm.oclc.org/stable/43154235",
                content=b"<html>paywall</html>",
                status_code=200,
                history=[object()],
                headers={"content-type": "text/html"},
            )

    monkeypatch.setattr(mod, "download_pdf_from_url", lambda *a, **k: False)
    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: {"login_url": "https://login.eux.idm.oclc.org/login?url=", "cookie": "x"},
    )
    monkeypatch.setattr(mod, "_build_ezproxy_session", lambda config: FakeSession())
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: None)

    result = mod.download_paper(
        url="https://www.jstor.org/stable/43154235",
        output_dir=str(tmp_path),
        filename="jstor-paper",
    )

    assert result == str(tmp_path / "jstor-paper.pdf")
    assert requested == [
        "https://www-jstor-org.eux.idm.oclc.org/stable/43154235",
        "https://login.eux.idm.oclc.org/login?url=https://www.jstor.org/stable/43154235",
        "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf?acceptTC=1",
    ]
    assert (tmp_path / "jstor-paper.pdf").read_bytes().startswith(b"%PDF-")


def test_ezproxy_url_download_keeps_already_proxied_url_unwrapped(monkeypatch, tmp_path):
    mod = _load_module(DOWNLOAD, "download_proxied_url_passthrough_under_test")
    proxied = (
        "https://www-jstor-org.eux.idm.oclc.org/stable/pdf/43154235.pdf?acceptTC=1"
    )
    requested: list[str] = []

    class FakeSession:
        def get(self, url, **kwargs):
            requested.append(url)
            return SimpleNamespace(
                url=url,
                content=b"%PDF- already proxied",
                status_code=200,
                history=[object()],
                headers={"content-type": "application/pdf"},
            )

    monkeypatch.setattr(
        mod,
        "load_ezproxy_config",
        lambda: {
            "login_url": "https://login.eux.idm.oclc.org/login?url=",
            "domain": "eux.idm.oclc.org",
            "cookie": "x",
        },
    )
    monkeypatch.setattr(mod, "_build_ezproxy_session", lambda config: FakeSession())
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: None)

    assert mod.try_ezproxy_url_download([proxied], str(tmp_path / "paper.pdf")) is True
    assert requested == [proxied]


def test_try_ezproxy_url_download_skips_throttle_when_unconfigured(tmp_path, monkeypatch):
    mod = _load_module(DOWNLOAD, "download_url_ezproxy_unconfigured_under_test")

    calls: list[int] = []
    monkeypatch.setattr(mod, "load_ezproxy_config", lambda: None)
    monkeypatch.setattr(mod, "_ezproxy_throttle", lambda *a, **k: calls.append(1))

    result = mod.try_ezproxy_url_download(
        ["https://www.jstor.org/stable/43154235"], str(tmp_path / "out.pdf")
    )

    assert result is False
    assert calls == []


# --- paper fetch identity gate ---

# The false-positive shape that once cleared verification with `status: ok`:
# a same-subfield paper contains every title keyword and cites the expected
# author, but is a different work under a different DOI.
_WRONG_PAPER_TEXT = (
    "agent causation is not prior to event causation\n"
    "soo lam wong\n"
    "disputatio, 2021. doi: 10.2478/disp-2021-0008\n"
    "keywords: agent causation, event causation, free action, production\n"
    "randolph clarke argues that agents produce free action by causing events.\n"
)

_RIGHT_PAPER_TEXT = (
    "agent causation and event causation in the production of free action\n"
    "author(s): randolph clarke\n"
    "source: philosophical topics, fall 1996, vol. 24, no. 2, pp. 19-48\n"
)

_CLARKE_IDENTITY = {
    "expected_author": "Randolph Clarke",
    "expected_title": (
        "Agent Causation and Event Causation in the Production of Free Action"
    ),
    "expected_doi": "10.5840/philtopics19962427",
}


def test_verify_rejects_same_subfield_paper_despite_full_keyword_overlap():
    mod = _load_module(DOWNLOAD, "verify_gate_wrong_paper_under_test")
    assert mod._verify_text_content(_WRONG_PAPER_TEXT, **_CLARKE_IDENTITY) is False


def test_verify_accepts_contiguous_title_phrase_with_author():
    mod = _load_module(DOWNLOAD, "verify_gate_right_paper_under_test")
    assert mod._verify_text_content(_RIGHT_PAPER_TEXT, **_CLARKE_IDENTITY) is True


def test_verify_accepts_embedded_requested_doi_without_title_phrase():
    mod = _load_module(DOWNLOAD, "verify_gate_doi_under_test")
    text = "untitled scan cover\nhttps://doi.org/10.5840/philtopics19962427\n"
    assert mod._verify_text_content(text, **_CLARKE_IDENTITY) is True


def test_verify_unextractable_text_still_passes():
    mod = _load_module(DOWNLOAD, "verify_gate_empty_under_test")
    assert mod._verify_text_content("", **_CLARKE_IDENTITY) is True


def test_verify_doi_only_request_keeps_old_scan_flow():
    mod = _load_module(DOWNLOAD, "verify_gate_doi_only_under_test")
    assert mod._verify_text_content(
        "an old scan with no printed doi",
        expected_doi="10.5840/philtopics19962427",
    ) is True


def _stub_paper_network(mod, monkeypatch):
    monkeypatch.setattr(mod, "download_pdf_from_url", lambda *a, **k: False)
    monkeypatch.setattr(mod, "find_oa_url", lambda *a, **k: None)
    monkeypatch.setattr(mod, "try_scihub_download", lambda *a, **k: False)
    monkeypatch.setattr(mod, "_try_publisher_direct", lambda *a, **k: False)
    monkeypatch.setattr(mod, "_try_ezproxy_with_refresh", lambda *a, **k: False)
    monkeypatch.setattr(mod, "_try_ezproxy_urls_with_refresh", lambda *a, **k: False)
    monkeypatch.setattr(mod, "find_wayback_url", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_kagi_discover_paper", lambda *a, **k: ([], []))


def test_download_paper_reverifies_and_deletes_wrong_existing_temp(
    monkeypatch, tmp_path
):
    mod = _load_module(DOWNLOAD, "download_exists_reverify_under_test")
    _stub_paper_network(mod, monkeypatch)
    monkeypatch.setattr(
        mod, "_extract_pdf_text", lambda *a, **k: _WRONG_PAPER_TEXT
    )
    leftover = tmp_path / "clarke-1996.pdf"
    leftover.write_bytes(b"%PDF- wrong paper " + b"x" * 2000)

    result = mod.download_paper(
        doi="10.5840/philtopics19962427",
        output_dir=str(tmp_path),
        filename="clarke-1996",
        verify_author="Randolph Clarke",
        verify_title=(
            "Agent Causation and Event Causation in the Production of Free Action"
        ),
    )

    assert result is None
    assert not leftover.exists()


def test_download_paper_serves_existing_temp_that_proves_identity(
    monkeypatch, tmp_path
):
    mod = _load_module(DOWNLOAD, "download_exists_proven_under_test")

    def _forbidden(*a, **k):
        raise AssertionError("network path must not run for a proven temp file")

    for name in (
        "download_pdf_from_url", "find_oa_url", "try_scihub_download",
        "_try_publisher_direct", "_try_ezproxy_with_refresh",
        "_try_ezproxy_urls_with_refresh", "find_wayback_url",
        "_kagi_discover_paper",
    ):
        monkeypatch.setattr(mod, name, _forbidden)
    monkeypatch.setattr(
        mod, "_extract_pdf_text", lambda *a, **k: _RIGHT_PAPER_TEXT
    )
    existing = tmp_path / "clarke-1996.pdf"
    existing.write_bytes(b"%PDF- right paper " + b"x" * 2000)

    result = mod.download_paper(
        doi="10.5840/philtopics19962427",
        output_dir=str(tmp_path),
        filename="clarke-1996",
        verify_author="Randolph Clarke",
        verify_title=(
            "Agent Causation and Event Causation in the Production of Free Action"
        ),
    )

    assert result == str(existing)


def test_download_paper_derives_jstor_stable_hint_from_jstor_doi(
    monkeypatch, tmp_path
):
    mod = _load_module(DOWNLOAD, "download_jstor_doi_hint_under_test")
    tried: list[str] = []

    def fake_download_pdf_from_url(url, output_path, timeout=60, **kwargs):
        tried.append(url)
        if "/stable/pdf/" in url:
            Path(output_path).write_bytes(b"%PDF- jstor")
            return True
        return False

    monkeypatch.setattr(mod, "download_pdf_from_url", fake_download_pdf_from_url)

    result = mod.download_paper(
        doi="10.2307/43154235",
        output_dir=str(tmp_path),
        filename="jstor-doi-paper",
    )

    assert result == str(tmp_path / "jstor-doi-paper.pdf")
    assert tried == [
        "https://www.jstor.org/stable/43154235",
        "https://www.jstor.org/stable/pdf/43154235.pdf?acceptTC=1",
    ]


def test_download_paper_routes_kagi_discovered_urls_through_ezproxy(
    monkeypatch, tmp_path
):
    mod = _load_module(DOWNLOAD, "download_kagi_ezproxy_under_test")
    _stub_paper_network(mod, monkeypatch)
    discovered = "https://www.jstor.org/stable/43154235"
    monkeypatch.setattr(
        mod, "_kagi_discover_paper", lambda *a, **k: ([], [discovered])
    )
    proxied: list[list[str]] = []

    def fake_proxy_urls(urls, output_path, **kwargs):
        proxied.append(list(urls))
        Path(output_path).write_bytes(b"%PDF- jstor via proxy " + b"x" * 2000)
        return True

    monkeypatch.setattr(mod, "_try_ezproxy_urls_with_refresh", fake_proxy_urls)
    monkeypatch.setattr(
        mod, "_extract_pdf_text", lambda *a, **k: _RIGHT_PAPER_TEXT
    )

    result = mod.download_paper(
        doi="10.5840/philtopics19962427",
        output_dir=str(tmp_path),
        filename="clarke-1996",
        verify_author="Randolph Clarke",
        verify_title=(
            "Agent Causation and Event Causation in the Production of Free Action"
        ),
    )

    assert result == str(tmp_path / "clarke-1996.pdf")
    assert proxied == [[discovered]]

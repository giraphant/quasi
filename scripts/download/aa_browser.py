#!/usr/bin/env python3
"""Bounded Chromium fetch for Anna's Archive DDoS-Guard JS challenge.

This file runs only through ``uvx --from seleniumbase`` after aa.py has
positively identified the challenge. It writes the settled HTML to the exact
output path supplied by its caller and never searches for alternate paths.
"""

from __future__ import annotations

import argparse
import asyncio
import html as html_lib
import re
import sys
import time
import urllib.parse
from contextlib import suppress
from html.parser import HTMLParser
from pathlib import Path

from aa import parse_aa_slow_final_url


DDOS_GUARD_INDICATORS = (
    "ddos-guard",
    "ddos guard",
    "checking your browser before accessing",
    "complete the manual check to continue",
    "could not verify your browser automatically",
)
_VALID_MD5_LINK = re.compile(
    r'''href\s*=\s*["'][^"']*/md5/[A-Fa-f0-9]{32}(?:[/?#][^"']*)?["']''',
)
_DETAIL_PATH = re.compile(r"/md5/[A-Fa-f0-9]{32}/?")
_DETAIL_PLACEHOLDER = re.compile(
    r"^(?:loading\b.*|please\s+wait\b.*|(?:error\s*)?[45]\d\d\b.*|"
    r"(?:internal\s+)?server\s+error\b.*|not\s+found\b.*|forbidden\b.*)$",
    re.IGNORECASE | re.DOTALL,
)
_SLOW_COUNTDOWN = re.compile(
    r"class\s*=\s*[\"'][^\"']*\bjs-partner-countdown\b", re.IGNORECASE
)
_SLOW_EXPLICIT_WAIT = re.compile(
    r"\b(?:waitlist|countdown|wait\s+\d+\s+seconds?)\b", re.IGNORECASE
)


def _is_challenge(title: str, body: str) -> bool:
    page_text = f"{title}\n{body}".lower()
    return any(indicator in page_text for indicator in DDOS_GUARD_INDICATORS)


class _MainInnerTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._div_depth = 0
        self._active_depth = None
        self._hidden_depth = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self._active_depth is not None and tag in {"script", "style", "template", "noscript"}:
            self._hidden_depth += 1
        if tag.lower() != "div":
            return
        self._div_depth += 1
        classes = (dict(attrs).get("class") or "").split()
        if self._active_depth is None and "main-inner" in classes:
            self._active_depth = self._div_depth

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "template", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1
        if tag.lower() != "div":
            return
        if self._active_depth == self._div_depth:
            self._active_depth = None
        self._div_depth = max(0, self._div_depth - 1)

    def handle_data(self, data):
        if self._active_depth is not None and self._hidden_depth == 0:
            self.text.append(data)


def _main_inner_text(page_html: str) -> str:
    parser = _MainInnerTextParser()
    try:
        parser.feed(page_html)
        parser.close()
    except (TypeError, ValueError):
        return ""
    return " ".join(html_lib.unescape(" ".join(parser.text)).split())


def _parse_safe_http_url(value):
    try:
        parsed = urllib.parse.urlparse(str(value or ""))
        parsed.port
    except (TypeError, ValueError):
        return None
    if not (
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    ):
        return None
    return parsed


def _is_detail_url(current_url: str) -> bool:
    parsed = _parse_safe_http_url(current_url)
    return parsed is not None and bool(_DETAIL_PATH.fullmatch(parsed.path))


def _looks_like_settled_page(
    page_kind: str,
    current_url: str,
    body: str,
    html: str,
) -> bool:
    if page_kind == "search":
        return "/search" in current_url and (
            bool(_VALID_MD5_LINK.search(html)) or "no files found." in body.lower()
        )
    if page_kind == "detail":
        if not _is_detail_url(current_url):
            return False
        main_text = _main_inner_text(html)
        return bool(main_text) and not bool(_DETAIL_PLACEHOLDER.fullmatch(main_text))
    if page_kind == "slow":
        parsed = _parse_safe_http_url(current_url)
        return parsed is not None and "/slow_download/" in parsed.path and bool(
            parse_aa_slow_final_url(current_url, html)
            or _SLOW_COUNTDOWN.search(html)
            or _SLOW_EXPLICIT_WAIT.search(body)
        )
    return False


def _looks_like_settled_search(current_url: str, body: str, html: str) -> bool:
    return _looks_like_settled_page("search", current_url, body, html)


async def _read_page(page):
    title = await page.get_title() or ""
    body = await page.evaluate("document.body ? document.body.innerText : ''") or ""
    current_url = await page.get_current_url() or ""
    html = await page.get_page_source() or ""
    return title, body, current_url, html


def _browser_options():
    """Use native headless Chrome; no desktop window or virtual display."""
    return {
        "headless": True,
        "headed": False,
        "xvfb": False,
        "sandbox": False,
        "lang": "en",
        "incognito": True,
    }


async def _fetch(url: str, output: Path, timeout: float, page_kind: str = "search") -> bool:
    from seleniumbase import cdp_driver

    driver = None
    deadline = time.monotonic() + timeout
    try:
        driver = await asyncio.wait_for(
            cdp_driver.start_async(**_browser_options()),
            timeout=min(30.0, timeout),
        )
        remaining = max(1.0, deadline - time.monotonic())
        page = await asyncio.wait_for(driver.get(url), timeout=min(45.0, remaining))

        settled_observations = 0
        while time.monotonic() < deadline:
            try:
                title, body, current_url, html = await _read_page(page)
            except asyncio.TimeoutError:
                settled_observations = 0
                await asyncio.sleep(1.0)
                continue
            if not _is_challenge(title, body) and _looks_like_settled_page(
                page_kind,
                current_url,
                body,
                html,
            ):
                settled_observations += 1
                if settled_observations >= 2:
                    output.write_text(html, encoding="utf-8")
                    return True
            else:
                settled_observations = 0
            await asyncio.sleep(1.0)
        return False
    finally:
        if driver is not None:
            with suppress(Exception):
                driver.stop()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=75.0)
    parser.add_argument("--page-kind", choices=("search", "detail", "slow"), default="search")
    args = parser.parse_args(argv)

    try:
        solved = asyncio.run(
            _fetch(args.url, args.output, max(5.0, args.timeout), args.page_kind)
        )
    except Exception as e:
        print(f"browser challenge failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if not solved:
        print("browser challenge did not resolve before timeout", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

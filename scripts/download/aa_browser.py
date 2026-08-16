#!/usr/bin/env python3
"""Bounded Chromium fetch for Anna's Archive DDoS-Guard JS challenge.

This file runs only through ``uvx --from seleniumbase`` after aa.py has
positively identified the challenge. It writes the settled HTML to the exact
output path supplied by its caller and never searches for alternate paths.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from contextlib import suppress
from pathlib import Path


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
_DETAIL_PATH = re.compile(r"/md5/[A-Fa-f0-9]{32}(?:[/?#]|$)")
_SLOW_DOWNLOAD_LINK = re.compile(r"<a\b[^>]*\bdownload\b", re.IGNORECASE)
_SLOW_COUNTDOWN = re.compile(
    r"class\s*=\s*[\"'][^\"']*\bjs-partner-countdown\b", re.IGNORECASE
)


def _is_challenge(title: str, body: str) -> bool:
    page_text = f"{title}\n{body}".lower()
    return any(indicator in page_text for indicator in DDOS_GUARD_INDICATORS)


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
        return bool(_DETAIL_PATH.search(current_url)) and bool(body.strip() or html.strip())
    if page_kind == "slow":
        return "/slow_download/" in current_url and bool(
            _SLOW_DOWNLOAD_LINK.search(html) or _SLOW_COUNTDOWN.search(html)
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
            title, body, current_url, html = await _read_page(page)
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

"""Douban CN adapter — books only (CJK / Chinese-translation lookup).

Inlined from scripts/search/douban_direct.py and scripts/search/cndouban.py
(Phase 9.1). Standalone files kept until Phase 9.2.

Combines two search paths:
    1. _direct_search_impl  — direct HTTP scraping (no dokobot), from douban_direct.py
    2. _cndouban_works_impl — cndouban lookup wrapper, from cndouban.py
    3. related-version probe — search hit → subject page → other versions

Path selection (internal, caller doesn't specify):
    - For explicit zh/localisation lookup: Doko subject-page enumeration first
      (ISBN/search → subject → other versions → Chinese manifestations),
      with direct/related probe only as fallback.
    - For general metadata lookup: direct path first, then Doko fallback when
      direct returns nothing and the query looks Chinese.
"""

from __future__ import annotations

import gzip
import json
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import search as _s

SUPPORTS = ["book"]
SOURCE_ID = "douban_cn"


# ==================================================================
# Inlined from douban_direct.py
# ==================================================================

_DOUBAN_SEARCH_URL = "https://www.douban.com/search"
_DOUBAN_BOOK_URL = "https://book.douban.com/subject/%s/"
_DOUBAN_BOOK_BASE = "https://book.douban.com/"
_DOUBAN_BOOK_CAT = "1001"
_GOOGLE_SEARCH_URL = "https://www.google.com/search"
_SUBJECT_URL_RE = re.compile(r".*/subject/(\d+)/?")
_WORKS_URL_RE = re.compile(r"https?://book\.douban\.com/works/(\d+)/?")
_ANY_SUBJECT_HREF_RE = re.compile(
    r"""href=["']((?:https?:)?//book\.douban\.com/subject/\d+/?|/subject/\d+/?)["']""",
    re.IGNORECASE,
)
_ANY_WORKS_HREF_RE = re.compile(
    r"""href=["']((?:https?:)?//book\.douban\.com/works/\d+/?|/works/\d+/?)["']""",
    re.IGNORECASE,
)
_ANY_HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)
_DOKO_REF_RE = re.compile(r"^\s*\[(\d+)\]\s+(\S+)\s*$", re.MULTILINE)
_DOKO_INLINE_REF_RE = re.compile(r"\[(\d+)\]")
_DOKO_RATING_RE = re.compile(r"(\d{1,7})\s*人评价")
_VERSION_SECTION_MARKERS = ("这本书的其他版本", "這本書的其他版本", "其他版本", "同一作品")
_SECTION_END_MARKERS = (
    "<h2",
    "</aside",
    '<div id="db-rec-section"',
    '<div class="block5"',
    '<div class="indent"',
)
_DOKO_META_LABELS = (
    "作者", "译者", "出版社", "出版年", "ISBN",
    "页数", "装帧", "定价", "丛书", "原作名",
)
_ZH_PUBLISHER_HINT_RE = re.compile(
    r"(出版社|出版|书店|書店|印书馆|印書館|商务|商務|三联|三聯|人民|"
    r"译林|譯林|中华|中華|中信|上海|北京|浙江|江苏|廣西|广西|"
    r"台湾|臺灣|香港|聯經|时报|時報|麦田|麥田|遠流|天下|大学|大學|群學)"
)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


def _get_headers(cookie: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": _random_ua(),
        "Accept-Encoding": "gzip, deflate",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _dd_fetch(url: str, cookie: str | None = None, timeout: int = 20) -> tuple[bool, str]:
    """HTTP fetch for douban_direct path."""
    try:
        req = urllib.request.Request(url, headers=_get_headers(cookie))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            encoding_header = resp.info().get("Content-Encoding", "")
            raw = resp.read()
            if encoding_header == "gzip":
                raw = gzip.decompress(raw)
            charset = resp.headers.get_content_charset() or "utf-8"
            return True, raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, str(e)


def _is_blocked(html: str) -> bool:
    return "<title>禁止访问</title>" in html or "检测到有异常请求" in html


def _calc_url(href: str) -> str | None:
    """Extract the actual Douban subject URL from a search result redirect link."""
    parsed = urllib.parse.urlparse(href)
    params = dict(urllib.parse.parse_qsl(parsed.query))
    url = urllib.parse.unquote(params.get("url", ""))
    if _SUBJECT_URL_RE.match(url):
        return url
    return None


def _search_book_urls(query: str, limit: int = 5,
                      cookie: str | None = None) -> tuple[list[str], list[str]]:
    """Search Douban for book URLs. Returns (urls, warnings)."""
    params = {"cat": _DOUBAN_BOOK_CAT, "q": query}
    url = _DOUBAN_SEARCH_URL + "?" + urllib.parse.urlencode(params)

    ok, body = _dd_fetch(url, cookie)
    if not ok:
        return [], [f"search-fetch: {body[:120]}"]
    if _is_blocked(body):
        return [], ["search: blocked by Douban (try setting cookie)"]

    book_urls: list[str] = []
    for m in re.finditer(r'href="(https?://www\.douban\.com/link2/\?[^"]+)"', body):
        parsed_url = _calc_url(m.group(1))
        if parsed_url and parsed_url not in book_urls:
            book_urls.append(parsed_url)
            if len(book_urls) >= limit:
                break

    if not book_urls:
        for m in re.finditer(r'href="(https?://book\.douban\.com/subject/\d+/?)"', body):
            u = m.group(1).rstrip("/") + "/"
            if u not in book_urls:
                book_urls.append(u)
                if len(book_urls) >= limit:
                    break

    return book_urls, []


_RE_RATING = re.compile(r'property="v:average"[^>]*>([^<]+)<')
_RE_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")


def _get_text_after_label(html: str, label: str) -> str:
    """Extract text after a <span class="pl"> label like '作者', '出版社', etc."""
    pattern = rf'<span\s+class="pl">\s*{re.escape(label)}\s*[:：]?\s*</span>(.*?)(?:<br\s*/?>|<span\s+class="pl">)'
    m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    block = m.group(1)
    text = re.sub(r"<[^>]+>", " ", block)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("\xa0", " ").strip()
    text = text.strip("/").strip()
    return text


def _get_authors_from_block(html: str, label: str) -> list[str]:
    """Extract author/translator names from their link block."""
    pattern = rf'<span\s+class="pl">\s*{re.escape(label)}\s*</span>(.*?)(?:<br\s*/?>|<span\s+class="pl">)'
    m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    block = m.group(1)
    names = []
    for am in re.finditer(r'<a[^>]+>([^<]+)</a>', block):
        name = unescape(am.group(1).strip())
        if name and ("/author" in block or "/search" in block):
            names.append(name)
    if not names:
        text = unescape(re.sub(r"<[^>]+>", "", block).strip())
        if text:
            names = [n.strip() for n in text.split("/") if n.strip()]
    return names


def _parse_dd_subject_page(html: str, subject_url: str) -> dict | None:
    """Parse a Douban book subject page into metadata dict."""
    title_m = re.search(r"property=['\"]v:itemreviewed['\"][^>]*>([^<]+)<", html)
    title = unescape(title_m.group(1).strip()) if title_m else None
    if not title:
        title_m = re.search(r"<title>([^<]+)</title>", html)
        if title_m:
            title = unescape(title_m.group(1).replace("(豆瓣)", "").strip())
    if not title:
        return None

    id_m = _SUBJECT_URL_RE.match(subject_url)
    subject_id = id_m.group(1) if id_m else ""

    authors = _get_authors_from_block(html, "作者")
    translators = _get_authors_from_block(html, "译者")
    publisher = _get_text_after_label(html, "出版社")
    subtitle = _get_text_after_label(html, "副标题")

    pub_date = _get_text_after_label(html, "出版年")
    year = None
    if pub_date:
        ym = _RE_YEAR.search(pub_date)
        if ym:
            try:
                year = int(ym.group(1))
            except ValueError:
                pass

    isbn = _get_text_after_label(html, "ISBN")
    isbn = re.sub(r"[^0-9X]", "", (isbn or "").upper()) or None

    rating = None
    rm = _RE_RATING.search(html)
    if rm:
        try:
            rating = float(rm.group(1).strip())
        except ValueError:
            pass

    ratings_count = 0
    rcm = re.search(r'property="v:votes"[^>]*>(\d+)<', html)
    if rcm:
        try:
            ratings_count = int(rcm.group(1))
        except ValueError:
            pass

    description = ""
    desc_m = re.search(r'<div\s+id="link-report"[^>]*>.*?<div\s+class="intro"[^>]*>(.*?)</div>',
                       html, re.DOTALL)
    if desc_m:
        description = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip()[:500]

    tags: list[str] = []
    tag_m = re.search(r"criteria\s*=\s*'([^']+)'", html)
    if tag_m:
        tags = [t.replace("7:", "") for t in tag_m.group(1).split("|")
                if t.startswith("7:")]

    series = _get_text_after_label(html, "丛书")
    original_title = _get_text_after_label(html, "原作名")

    cover_url = None
    cover_m = re.search(r'<a\s+class="nbg"[^>]+href="([^"]+)"', html)
    if cover_m:
        cover = cover_m.group(1)
        if not cover.endswith("update_image"):
            cover_url = cover

    isbn_13 = isbn if isbn and len(isbn) == 13 else None
    isbn_10 = isbn if isbn and len(isbn) == 10 else None

    full_title = title
    if subtitle:
        full_title = f"{title}:{subtitle}"

    return {
        "title": full_title,
        "subtitle": subtitle or "",
        "authors": authors,
        "translators": translators,
        "year": year,
        "publisher": publisher,
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "description": description,
        "categories": tags,
        "page_count": None,
        "preview_link": subject_url,
        "douban_subject_id": subject_id,
        "ratings_count": ratings_count,
        "douban_rating": rating,
        "original_title": original_title or "",
        "series": series or "",
        "cover_url": cover_url,
        "source": "Douban (direct)",
    }


def _direct_search_impl(
    query: str,
    limit: int = 5,
    year_from: int | None = None,
    year_to: int | None = None,
    cookie: str | None = None,
) -> dict:
    """Search Douban books via direct HTTP. Returns {success, source, count, results}.

    No dokobot or browser bridge required. May be blocked by Douban
    without a login cookie.
    """
    book_urls, warnings = _search_book_urls(query, limit=min(limit * 2, 10), cookie=cookie)

    if not book_urls:
        return {
            "success": True,
            "source": "Douban (direct)",
            "count": 0,
            "results": [],
            "warnings": warnings,
        }

    results: list[dict] = []
    for url in book_urls:
        time.sleep(random.random() * 0.3 + 0.2)

        ok, body = _dd_fetch(url, cookie)
        if not ok:
            warnings.append(f"subject-fetch {url}: {body[:120]}")
            continue
        if _is_blocked(body):
            warnings.append(f"subject-fetch {url}: blocked")
            continue

        book = _parse_dd_subject_page(body, url)
        if not book:
            continue

        if year_from and book.get("year") and book["year"] < year_from:
            continue
        if year_to and book.get("year") and book["year"] > year_to:
            continue

        results.append(book)
        if len(results) >= limit:
            break

    return {
        "success": True,
        "source": "Douban (direct)",
        "count": len(results),
        "results": results,
        "warnings": warnings,
    }


# ==================================================================
# Inlined from cndouban.py
# ==================================================================

def _has_cjk(s: str) -> bool:
    return any('一' <= c <= '鿿' for c in (s or ""))


def _doko_read(url: str, timeout: int = 60) -> tuple[bool, str]:
    """Invoke `dokobot read --local <url>`; return (success, body)."""
    if not shutil.which("dokobot"):
        return False, "DOKO_NOT_AVAILABLE"

    def _run(args):
        return subprocess.run(
            ["dokobot", "read", *args, url],
            capture_output=True, text=True, timeout=timeout, check=False,
        )

    try:
        r = _run(["--local"])
        if r.returncode != 0 and "bridge" in (r.stderr or "").lower():
            r = _run([])
    except subprocess.TimeoutExpired:
        return False, "DOKO_TIMEOUT"
    except FileNotFoundError:
        return False, "DOKO_NOT_FOUND"

    if r.returncode != 0:
        return False, f"DOKO_ERR rc={r.returncode}: {(r.stderr or '')[:200]}"
    return True, (r.stdout or "")


def _isbn_direct_url(isbn: str) -> str:
    isbn_clean = re.sub(r"[^0-9X]", "", (isbn or "").upper())
    return f"https://book.douban.com/isbn/{isbn_clean}/"


def _cn_search_url(query: str) -> str:
    return ("https://search.douban.com/book/subject_search?"
            + urllib.parse.urlencode({"search_text": query}))


def _google_site_subject_search_url(query: str) -> str:
    return (_GOOGLE_SEARCH_URL + "?"
            + urllib.parse.urlencode({"q": f"site:book.douban.com/subject {query} 豆瓣读书"}))


def _subject_url(subject_id: str) -> str:
    return f"https://book.douban.com/subject/{subject_id}/"


def _works_url(works_id: str) -> str:
    return f"https://book.douban.com/works/{works_id}/"


_RE_SUBJECT_ID = re.compile(r"book\.douban\.com/subject/(\d+)")
_RE_WORKS_ID = re.compile(r"book\.douban\.com/works/(\d+)")

_RE_AUTHOR_CN = re.compile(r"作\s*者[:：]\s*(.+?)(?:\n|$)")
_RE_TRANSLATOR_CN = re.compile(r"译\s*者[:：]\s*(.+?)(?:\n|$)")
_RE_PUBLISHER_CN = re.compile(r"出版社[:：]\s*(.+?)(?:\n|$)")
_RE_PUBLISH_YEAR_CN = re.compile(r"出版年[:：]\s*(\d{4})")
_RE_ISBN_CN = re.compile(r"ISBN[:：]\s*([\dX-]+)")
_RE_ORIGINAL_TITLE_CN = re.compile(r"原作名[:：]\s*(.+?)(?:\n|$)")
_RE_RATINGS_COUNT = re.compile(r"(\d{1,7})\s*人\s*评价")

_RE_PUBLISHER_HINT = re.compile(
    r"([一-鿿　A-Za-z·\s]{2,40}?"
    r"(?:出版社|书店|印书馆|出版|文化|公司|大学|图书|译丛|出版部|事业|集团))"
)
_RE_YEAR_PAREN = re.compile(r"[（(](\d{4})[)）]")


def _grab(rx, body, default=None):
    m = rx.search(body or "")
    if not m:
        return default
    return m.group(1).strip()


def _guess_title_from_subject_page(body: str) -> Optional[str]:
    """Heuristic: first prominent non-boilerplate line from doko-rendered text."""
    boilerplate = {"豆瓣", "豆瓣读书", "登录", "注册", "电影", "音乐", "书籍",
                   "广告", "首页", "更多", "豆品", "导航"}
    for line in (body or "").splitlines()[:30]:
        line = line.strip()
        if not line:
            continue
        if line in boilerplate:
            continue
        if line.startswith("豆瓣") or line.startswith("Sign in"):
            continue
        if len(line) < 2:
            continue
        return line[:200]
    return None


def _parse_cn_subject_page(body: str, subject_id: str) -> dict:
    year_str = _grab(_RE_PUBLISH_YEAR_CN, body)
    year = int(year_str) if year_str and year_str.isdigit() else None
    ratings_m = _RE_RATINGS_COUNT.search(body or "")
    ratings_count = int(ratings_m.group(1)) if ratings_m else 0

    return {
        "douban_id": subject_id,
        "douban_url": _subject_url(subject_id),
        "title": _guess_title_from_subject_page(body),
        "author": _grab(_RE_AUTHOR_CN, body),
        "translator": _grab(_RE_TRANSLATOR_CN, body),
        "publisher": _grab(_RE_PUBLISHER_CN, body),
        "year": year,
        "isbn": _grab(_RE_ISBN_CN, body),
        "original_title": _grab(_RE_ORIGINAL_TITLE_CN, body),
        "ratings_count": ratings_count,
    }


def _extract_works_id(body: str) -> Optional[str]:
    m = _RE_WORKS_ID.search(body or "")
    return m.group(1) if m else None


def _extract_manifestations_from_works_page(body: str) -> list[dict]:
    """Pull (subject_id, publisher_hint, year_hint) tuples from a works page."""
    out: list[dict] = []
    seen: set[str] = set()
    lines = (body or "").splitlines()
    for i, line in enumerate(lines):
        m = _RE_SUBJECT_ID.search(line)
        if not m:
            continue
        sid = m.group(1)
        if sid in seen:
            continue
        seen.add(sid)
        ctx = "\n".join(lines[max(0, i - 3):i + 1])
        pub_match = _RE_PUBLISHER_HINT.search(ctx)
        publisher = pub_match.group(1).strip() if pub_match else None
        year_match = _RE_YEAR_PAREN.search(ctx)
        year = int(year_match.group(1)) if year_match else None
        out.append({
            "subject_id": sid,
            "publisher_hint": publisher,
            "year_hint": year,
        })
    return out


def _reverse_from_slug(slug: str) -> dict:
    """Best-effort split of `{author}-{title-words}-{year}` style slugs."""
    parts = (slug or "").split("-")
    result: dict = {}
    if len(parts) >= 3 and parts[-1].isdigit() and len(parts[-1]) == 4:
        result["year"] = int(parts[-1])
        result["author"] = parts[0]
        result["title"] = " ".join(parts[1:-1])
    return result


def _find_cndouban(*, isbn: Optional[str] = None,
                   title: Optional[str] = None,
                   author: Optional[str] = None,
                   year: Optional[int] = None,
                   slug: Optional[str] = None) -> dict:
    """Core cndouban pipeline. Returns structured result dict."""
    diagnostics = {"routing": [], "doko_calls": 0, "warnings": []}

    if slug and not (title and author):
        rev = _reverse_from_slug(slug)
        title = title or rev.get("title")
        author = author or rev.get("author")
        year = year or rev.get("year")

    if not (isbn or title or author):
        return {
            "status": "error",
            "primary_subject": None,
            "translations": [],
            "diagnostics": {**diagnostics,
                            "warnings": ["no inputs (need isbn, title+author, or slug)"]},
        }

    # ----- Step 1: locate primary Douban subject -----
    primary_subject = None
    primary_body = None

    if isbn:
        diagnostics["routing"].append("isbn-direct")
        diagnostics["doko_calls"] += 1
        ok, body = _doko_read(_isbn_direct_url(isbn))
        if ok:
            sid = _RE_SUBJECT_ID.search(body)
            if sid:
                primary_subject = sid.group(1)
                primary_body = body
        else:
            diagnostics["warnings"].append(f"isbn-direct: {body[:120]}")

    if primary_subject is None and (title or author):
        q = " ".join(filter(None, [
            title,
            author,
            str(year) if year else None,
        ]))
        diagnostics["routing"].append("google-site-title-author")
        urls, warnings = _google_site_subject_urls(q, limit=5)
        diagnostics["warnings"].extend(warnings)
        for url in urls:
            cand = _subject_id_from_url(url)
            if not cand:
                continue
            diagnostics["doko_calls"] += 1
            ok2, body2 = _doko_read(_subject_url(cand))
            if ok2:
                primary_subject = cand
                primary_body = body2
                break
            diagnostics["warnings"].append(f"subject-fetch {cand}: {body2[:120]}")

    if primary_subject is None and title and author:
        q = f"{title} {author}"
        diagnostics["routing"].append("search-title-author")
        diagnostics["doko_calls"] += 1
        ok, body = _doko_read(_cn_search_url(q))
        if ok:
            sid = _RE_SUBJECT_ID.search(body)
            if sid:
                cand = sid.group(1)
                diagnostics["doko_calls"] += 1
                ok2, body2 = _doko_read(_subject_url(cand))
                if ok2:
                    primary_subject = cand
                    primary_body = body2
                else:
                    diagnostics["warnings"].append(f"subject-fetch {cand}: {body2[:120]}")
        else:
            diagnostics["warnings"].append(f"search-title-author: {body[:120]}")

    if primary_subject is None and author:
        diagnostics["routing"].append("search-author-only")
        diagnostics["doko_calls"] += 1
        ok, body = _doko_read(_cn_search_url(author))
        if ok:
            sid = _RE_SUBJECT_ID.search(body)
            if sid:
                cand = sid.group(1)
                diagnostics["doko_calls"] += 1
                ok2, body2 = _doko_read(_subject_url(cand))
                if ok2:
                    primary_subject = cand
                    primary_body = body2
                else:
                    diagnostics["warnings"].append(f"subject-fetch {cand}: {body2[:120]}")
        else:
            diagnostics["warnings"].append(f"search-author: {body[:120]}")

    if primary_subject is None:
        return {
            "status": "no-douban-entry",
            "primary_subject": None,
            "translations": [],
            "diagnostics": diagnostics,
        }

    primary_meta = _parse_cn_subject_page(primary_body, primary_subject)

    # ----- Step 2: related-version links from the primary subject page -----
    manifestations: list[dict] = []
    related_urls = _extract_related_version_urls_from_doko(
        primary_body,
        current_url=_subject_url(primary_subject),
    )
    if related_urls:
        diagnostics["routing"].append("related-version-links")
        for url in related_urls:
            sid = _subject_id_from_url(url)
            if sid:
                manifestations.append({
                    "subject_id": sid,
                    "publisher_hint": None,
                    "year_hint": None,
                })

    if not manifestations:
        manifestations = [{
            "subject_id": primary_subject,
            "publisher_hint": primary_meta.get("publisher"),
            "year_hint": primary_meta.get("year"),
        }]
        diagnostics["warnings"].append("related-version links absent — using primary subject only")

    # ----- Step 3: filter Chinese candidates -----
    chinese_candidates = [m for m in manifestations
                          if _has_cjk(m.get("publisher_hint") or "")]
    unknown_candidates = [m for m in manifestations
                          if not (m.get("publisher_hint") or "")]

    if _has_cjk(primary_meta.get("publisher") or ""):
        if not any(m["subject_id"] == primary_subject for m in chinese_candidates):
            chinese_candidates.append({
                "subject_id": primary_subject,
                "publisher_hint": primary_meta.get("publisher"),
                "year_hint": primary_meta.get("year"),
            })

    if not chinese_candidates and not unknown_candidates:
        return {
            "status": "no-translations",
            "primary_subject": {
                "douban_id": primary_subject,
                "douban_url": _subject_url(primary_subject),
                "title_on_douban": primary_meta.get("title"),
                "year_on_douban": primary_meta.get("year"),
            },
            "translations": [],
            "diagnostics": diagnostics,
        }

    # ----- Step 4: scrape each Chinese candidate for full metadata -----
    translations: list[dict] = []
    candidate_pool: list[dict] = []
    seen_candidate_ids: set[str] = set()
    for cand in chinese_candidates + unknown_candidates:
        sid = cand["subject_id"]
        if sid in seen_candidate_ids:
            continue
        seen_candidate_ids.add(sid)
        candidate_pool.append(cand)

    for cand in candidate_pool:
        sid = cand["subject_id"]
        if sid == primary_subject:
            if _is_chinese_like_record(primary_meta):
                translations.append(primary_meta)
            continue
        diagnostics["doko_calls"] += 1
        ok, body = _doko_read(_subject_url(sid))
        if not ok:
            diagnostics["warnings"].append(f"candidate {sid}: {body[:120]}")
            continue
        parsed = _parse_cn_subject_page(body, sid)
        if cand.get("publisher_hint") or _is_chinese_like_record(parsed):
            translations.append(parsed)

    translations.sort(key=lambda t: t.get("ratings_count") or 0, reverse=True)

    return {
        "status": "ok" if translations else "no-translations",
        "primary_subject": {
            "douban_id": primary_subject,
            "douban_url": _subject_url(primary_subject),
            "title_on_douban": primary_meta.get("title"),
            "year_on_douban": primary_meta.get("year"),
        },
        "translations": translations,
        "diagnostics": diagnostics,
    }


def _cndouban_works_impl(args_namespace) -> dict:
    """Run the cndouban pipeline and return the result dict directly.

    Formerly run_cndouban in cndouban.py, which printed JSON to stdout.
    Refactored to return a dict so callers get structured data without
    stdout redirection.
    """
    return _find_cndouban(
        isbn=args_namespace.isbn,
        title=args_namespace.title,
        author=args_namespace.author,
        year=args_namespace.year,
        slug=args_namespace.slug,
    )


# ==================================================================
# Related-version probe: search hit → subject → other versions
# ==================================================================

def _normalise_subject_url(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = urllib.parse.urljoin(_DOUBAN_BOOK_BASE, url)
    m = re.search(r"(https?://book\.douban\.com/subject/\d+)/?", url)
    return f"{m.group(1)}/" if m else url


def _normalise_works_url(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = urllib.parse.urljoin(_DOUBAN_BOOK_BASE, url)
    m = re.search(r"(https?://book\.douban\.com/works/\d+)/?", url)
    return f"{m.group(1)}/" if m else url


def _subject_id_from_url(url: str) -> str:
    m = _SUBJECT_URL_RE.match(_normalise_subject_url(url))
    return m.group(1) if m else ""


def _version_section_snippets(html: str) -> list[str]:
    snippets = []
    for marker in _VERSION_SECTION_MARKERS:
        start = (html or "").find(marker)
        if start < 0:
            continue
        search_from = start + len(marker)
        end = len(html)
        for end_marker in _SECTION_END_MARKERS:
            pos = html.find(end_marker, search_from)
            if pos > search_from:
                end = min(end, pos)
        snippets.append(html[start:end])
    return snippets


def _extract_related_version_urls(html: str, current_url: str | None = None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    current = _normalise_subject_url(current_url or "")
    for snippet in _version_section_snippets(html):
        for m in _ANY_SUBJECT_HREF_RE.finditer(snippet):
            url = _normalise_subject_url(m.group(1))
            if not _subject_id_from_url(url):
                continue
            if current and url == current:
                continue
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def _decode_douban_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc == "www.douban.com" and parsed.path.startswith("/link2/"):
        params = dict(urllib.parse.parse_qsl(parsed.query))
        return urllib.parse.unquote(params.get("url", "")) or url
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        params = dict(urllib.parse.parse_qsl(parsed.query))
        return urllib.parse.unquote(params.get("q") or params.get("url") or "") or url
    return url


def _extract_google_subject_urls(body: str, limit: int = 5) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for m in _ANY_HREF_RE.finditer(body or ""):
        href = unescape(m.group(1)).replace("&amp;", "&")
        if href.startswith("/url?"):
            href = urllib.parse.urljoin(_GOOGLE_SEARCH_URL, href)
        decoded = _decode_douban_url(href)
        sm = re.search(r"https?://book\.douban\.com/subject/\d+/?", decoded)
        if not sm:
            continue
        url = _normalise_subject_url(sm.group(0))
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _google_site_subject_urls(query: str, limit: int = 5) -> tuple[list[str], list[str]]:
    """Find Douban subject URLs via Google HTTP. Never invokes Doko."""
    url = _google_site_subject_search_url(query)
    ok, body = _dd_fetch(url, timeout=15)
    warnings: list[str] = []
    if ok:
        urls = _extract_google_subject_urls(body, limit=limit)
        if urls:
            return urls, warnings
        warnings.append("google-site-fetch: no subject urls")
    else:
        warnings.append(f"google-site-fetch: {body[:120]}")
    return [], warnings


def _parse_doko_references(body: str) -> dict[str, str]:
    return {m.group(1): _decode_douban_url(m.group(2)) for m in _DOKO_REF_RE.finditer(body or "")}


def _doko_version_windows(body: str) -> list[str]:
    windows = []
    for marker in _VERSION_SECTION_MARKERS:
        start = (body or "").find(marker)
        if start < 0:
            continue
        window = body[start:start + 3000]
        sep = window.find("\n---", len(marker))
        if sep > 0:
            window = window[:sep]
        windows.append(window)
    return windows


def _extract_related_version_urls_from_doko(body: str, current_url: str | None = None) -> list[str]:
    refs = _parse_doko_references(body)
    urls: list[str] = []
    seen: set[str] = set()
    current = _normalise_subject_url(current_url or "")
    for window in _doko_version_windows(body):
        for ref_id in _DOKO_INLINE_REF_RE.findall(window):
            url = _normalise_subject_url(refs.get(ref_id, ""))
            if not _subject_id_from_url(url):
                continue
            if current and url == current:
                continue
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def _extract_subject_urls_anywhere(html: str, current_url: str | None = None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    current = _normalise_subject_url(current_url or "")
    for m in _ANY_SUBJECT_HREF_RE.finditer(html or ""):
        url = _normalise_subject_url(m.group(1))
        if not _subject_id_from_url(url):
            continue
        if current and url == current:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _extract_subject_urls_from_doko(body: str, current_url: str | None = None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    current = _normalise_subject_url(current_url or "")
    for url in _parse_doko_references(body).values():
        url = _normalise_subject_url(url)
        if not _subject_id_from_url(url):
            continue
        if current and url == current:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _grab_doko_meta(body: str, label: str) -> str:
    label_alt = "|".join(re.escape(item) for item in _DOKO_META_LABELS)
    pattern = rf"{re.escape(label)}\s*[:：]\s*(.*?)(?=(?:{label_alt})\s*[:：]|\n|$)"
    m = re.search(pattern, body or "", re.DOTALL)
    if not m:
        return ""
    value = re.sub(r"\[\d+\]", "", m.group(1))
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip("/")


def _parse_doko_subject_page(body: str, url: str) -> dict | None:
    title = ""
    m = re.search(r"^#\s+(.+?)\s+\(豆瓣\)\s*$", body or "", re.MULTILINE)
    if m:
        title = m.group(1).strip()
    if not title:
        m = re.search(r"\*\*(.+?)\*\*", body or "")
        if m:
            title = m.group(1).strip()
    if not title:
        return None

    author = _grab_doko_meta(body, "作者")
    translator = _grab_doko_meta(body, "译者")
    publisher = _grab_doko_meta(body, "出版社")
    year_str = _grab_doko_meta(body, "出版年")
    isbn = _grab_doko_meta(body, "ISBN")
    isbn_clean = re.sub(r"[^0-9X]", "", (isbn or "").upper())
    original_title = _grab_doko_meta(body, "原作名")
    ratings_m = _DOKO_RATING_RE.search(body or "")

    return {
        "title": title,
        "authors": [author] if author else [],
        "translators": [translator] if translator else [],
        "publisher": publisher or "",
        "year": int(year_str[:4]) if year_str[:4].isdigit() else None,
        "isbn_13": isbn_clean if len(isbn_clean) == 13 else None,
        "isbn_10": isbn_clean if len(isbn_clean) == 10 else None,
        "ratings_count": int(ratings_m.group(1)) if ratings_m else 0,
        "douban_subject_id": _subject_id_from_url(url),
        "douban_url": _normalise_subject_url(url),
        "original_title": original_title or "",
    }


def _is_chinese_like_record(raw: dict) -> bool:
    title = raw.get("title") or ""
    publisher = raw.get("publisher") or ""
    translators = " ".join(raw.get("translators") or ([raw.get("translator")] if raw.get("translator") else []))
    authors = " ".join(raw.get("authors") or ([raw.get("author")] if raw.get("author") else []))
    if _ZH_PUBLISHER_HINT_RE.search(publisher):
        return True
    if translators and _has_cjk(translators):
        return True
    return _has_cjk(title) and (_has_cjk(publisher) or _has_cjk(authors))


def _fetch_subject_for_related(url: str) -> tuple[dict | None, list[str]]:
    ok, body = _dd_fetch(url)
    if ok and not _is_blocked(body):
        return (
            _parse_dd_subject_page(body, url),
            _extract_related_version_urls(body, current_url=url),
        )

    ok, body = _doko_read(url)
    if ok:
        return (
            _parse_doko_subject_page(body, url),
            _extract_related_version_urls_from_doko(body, current_url=url),
        )
    return None, []


def _related_version_search(query: _s.BookQuery, direct_hits: list[dict]) -> list[dict]:
    seed_urls = []
    for hit in direct_hits:
        url = hit.get("douban_url") or hit.get("preview_link")
        if url and _subject_id_from_url(url):
            seed_urls.append(_normalise_subject_url(url))

    if not seed_urls:
        q_text = " ".join(filter(None, [query.isbn, query.title, query.author, query.query]))
        if q_text:
            seed_urls, _ = _google_site_subject_urls(q_text, limit=query.limit)
        if not seed_urls and q_text:
            ok, body = _doko_read(_cn_search_url(q_text))
            if ok:
                seed_urls = _extract_subject_urls_from_doko(body)[:query.limit]

    related_urls: list[str] = []
    seen_urls: set[str] = set(seed_urls)
    for seed_url in seed_urls[:query.limit]:
        _, seed_related = _fetch_subject_for_related(seed_url)
        for url in seed_related:
            if url not in seen_urls:
                seen_urls.add(url)
                related_urls.append(url)

    out: list[dict] = []
    seen_ids: set[str] = set()
    for url in related_urls:
        raw, _ = _fetch_subject_for_related(url)
        if not raw or not _is_chinese_like_record(raw):
            continue
        sid = raw.get("douban_subject_id") or raw.get("douban_id") or _subject_id_from_url(url)
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        out.append(raw)
        if len(out) >= query.limit:
            break
    out.sort(key=lambda r: r.get("ratings_count") or 0, reverse=True)
    return out


# ==================================================================
# Adapter glue: normalise + search wrappers
# ==================================================================

def _has_cjk_str(s: str | None) -> bool:
    return bool(s) and any("一" <= c <= "鿿" for c in s)


def _normalise(raw: dict) -> dict:
    b = _s.BookRecord().to_dict()
    isbn = re.sub(r"[^0-9X]", "", (raw.get("isbn") or "").upper()) or None
    b["title"]          = raw.get("title", "") or ""
    b["authors"]        = raw.get("authors") or ([raw.get("author")] if raw.get("author") else [])
    b["translators"]    = ([raw.get("translator")] if raw.get("translator") else []) \
                          or (raw.get("translators") or [])
    b["original_title"] = raw.get("original_title", "") or ""
    b["year"]           = raw.get("year")
    b["publisher"]      = raw.get("publisher", "") or ""
    b["isbn_13"]        = raw.get("isbn_13") or (isbn if isbn and len(isbn) == 13 else None)
    b["isbn_10"]        = raw.get("isbn_10") or (isbn if isbn and len(isbn) == 10 else None)
    b["language"]       = "zh"
    b["ratings"]        = {"count": raw.get("ratings_count"),
                           "average": raw.get("douban_rating")}
    b["preview_link"]   = raw.get("douban_url", "") or raw.get("preview_link", "") or ""
    b["source_ids"]["douban_cn"] = raw.get("douban_subject_id") or raw.get("douban_id")
    b["_sources"] = [SOURCE_ID]
    return b


def _direct_search(query: _s.BookQuery) -> list[dict]:
    """Wrap _direct_search_impl with our query dataclass."""
    q_text = " ".join(filter(None, [
        query.isbn, query.title, query.author, query.query,
    ]))
    if not q_text:
        return []
    try:
        result = _direct_search_impl(q_text, limit=query.limit)
        return (result.get("results") if isinstance(result, dict) else result) or []
    except Exception:
        return []


def _cndouban_works_page(query: _s.BookQuery) -> list[dict]:
    """Wrap _cndouban_works_impl (subject-page localisation via dokobot)."""
    payload = _cndouban_works_payload(query)
    return payload.get("translations") or []


def _cndouban_works_payload(query: _s.BookQuery) -> dict:
    """Run Doko subject-page lookup and keep diagnostics for caller decisions."""
    import argparse
    args = argparse.Namespace(
        isbn=query.isbn, title=query.title, author=query.author,
        slug=None, year=query.year_from,
    )
    try:
        return _cndouban_works_impl(args)
    except Exception as exc:
        return {
            "status": "error",
            "translations": [],
            "diagnostics": {"warnings": [f"{type(exc).__name__}: {exc}"]},
        }


def _doko_unavailable_from_payload(payload: dict) -> str | None:
    diagnostics = payload.get("diagnostics") or {}
    warnings = diagnostics.get("warnings") or []
    for warning in warnings:
        if "DOKO_" in str(warning) or "No local bridge" in str(warning) or "API key required" in str(warning):
            return str(warning)
    return None


def _wants_chinese_versions(query: _s.BookQuery) -> bool:
    return (query.subject or "").lower() in {
        "zh", "cn", "chinese", "translation", "translations", "cndouban",
    }


def search_book(query: _s.BookQuery) -> _s.AdapterResult:
    if not any([query.isbn, query.title, query.author, query.query, query.subject]):
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No query")
    wants_zh = _wants_chinese_versions(query)

    if wants_zh:
        # Localisation lookup starts with direct ISBN / Google site discovery,
        # leaving Douban's own search endpoint as the last fallback.
        payload = _cndouban_works_payload(query)
        works = payload.get("translations") or []
        if not works:
            works = _related_version_search(query, [])
        if not works:
            direct = _direct_search(query)
            works = _related_version_search(query, direct) if direct else []
        if not works:
            doko_error = _doko_unavailable_from_payload(payload)
            if doko_error:
                return _s.AdapterResult(source=SOURCE_ID, success=False, error=doko_error)
        all_raw = works
    else:
        direct = _direct_search(query)
        works = []
        if not direct and _has_cjk_str(query.author):
            works = _cndouban_works_page(query)
        all_raw = direct + works

    if not all_raw:
        return _s.AdapterResult(source=SOURCE_ID, success=True, entries=[])
    return _s.AdapterResult(source=SOURCE_ID, success=True,
                            entries=[_normalise(e) for e in all_raw[:query.limit]])

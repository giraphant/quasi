"""Douban CN adapter — books only (CJK / Chinese-translation lookup).

Two paths share this module:

  1. `_direct_search_impl` — direct HTTP scraping of search.douban.com for
     general metadata queries (no Doko, no Kagi). Used when the caller is
     looking up a Chinese-authored book by its Chinese title/author.

  2. `_zh_localisation_search` — Chinese-edition discovery for an English
     book. Asks Kagi (`site:book.douban.com/subject {q}`), filters results
     to canonical subject URLs, fetches each via direct HTTP, parses with
     BeautifulSoup, and keeps only Chinese-language editions.

Path selection (caller doesn't need to specify):
  - `subject ∈ {zh, cn, chinese, translation, translations, cndouban}` →
    localisation path
  - otherwise → direct search path (with localisation as a CJK-author
    fallback when the direct search returns nothing)
"""

from __future__ import annotations

import gzip
import json
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))

import search as _s

SUPPORTS = ["book"]
SOURCE_ID = "douban_cn"


# ==================================================================
# Constants
# ==================================================================

_DOUBAN_SEARCH_URL = "https://www.douban.com/search"
_DOUBAN_BOOK_URL = "https://book.douban.com/subject/%s/"
_DOUBAN_BOOK_BASE = "https://book.douban.com/"
_DOUBAN_BOOK_CAT = "1001"

_SUBJECT_URL_RE = re.compile(r".*/subject/(\d+)/?")

# Strict canonical-subject regex used for filtering Kagi results.
# Accepts `/subject/{digits}/`, `/subject/{digits}//`, and the same with
# an optional query string. Rejects any extra path segment such as
# `/comments`, `/blockquotes`, `/doulists`, `/reviews/123`, etc.
_RE_DOUBAN_SUBJECT_CLEAN = re.compile(
    r"^https?://book\.douban\.com/subject/(\d+)/*(?:\?[^#]*)?$"
)

# ISBN agency prefixes that identify a Chinese-language edition:
#   978-7-xxx     — mainland China
#   978-957/986-x — Taiwan
#   978-988/962-x — Hong Kong
# Cleaner than a publisher whitelist (which would never keep up with the
# long tail of independent / academic presses).
_ZH_ISBN_PREFIXES = ("9787", "978957", "978986", "978988", "978962")

# Other Asian-CJK-language ISBN prefixes — explicitly NOT Chinese. Without
# this the kanji-only Japanese titles / kanji translator names slip past
# the generic CJK check (e.g. 伴侶種宣言 / 永野 文香 from a JP edition).
_NON_ZH_ASIAN_ISBN_PREFIXES = ("9784", "97889", "97811", "978604")

# Kana / Hangul ranges — presence in title / publisher / translator means
# it's clearly not Chinese.
_KANA_HANGUL_RE = re.compile(r"[぀-ゟ゠-ヿᄀ-ᇿ㄰-㆏가-힯]")

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
    """HTTP fetch. Returns (success, body-or-error-string)."""
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
    return ("<title>禁止访问</title>" in html
            or "检测到有异常请求" in html
            or "sec.douban.com" in (html or "")[:2000])


def _has_cjk(s: str | None) -> bool:
    return any("一" <= c <= "鿿" for c in (s or ""))


# ==================================================================
# Direct search path (general metadata)
# ==================================================================

def _calc_url(href: str) -> str | None:
    """Extract the actual Douban subject URL from a search redirect link."""
    parsed = urllib.parse.urlparse(href)
    params = dict(urllib.parse.parse_qsl(parsed.query))
    url = urllib.parse.unquote(params.get("url", ""))
    if _SUBJECT_URL_RE.match(url):
        return url
    return None


def _search_book_urls(query: str, limit: int = 5,
                      cookie: str | None = None) -> tuple[list[str], list[str]]:
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
    pattern = rf'<span\s+class="pl">\s*{re.escape(label)}\s*[:：]?\s*</span>(.*?)(?:<br\s*/?>|<span\s+class="pl">)'
    m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    block = m.group(1)
    text = re.sub(r"<[^>]+>", " ", block)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("\xa0", " ").strip()
    return text.strip("/").strip()


def _get_authors_from_block(html: str, label: str) -> list[str]:
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
    """Search Douban books via direct HTTP. May be blocked without a cookie."""
    book_urls, warnings = _search_book_urls(query, limit=min(limit * 2, 10), cookie=cookie)
    if not book_urls:
        return {"success": True, "source": "Douban (direct)",
                "count": 0, "results": [], "warnings": warnings}

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

    return {"success": True, "source": "Douban (direct)",
            "count": len(results), "results": results, "warnings": warnings}


# ==================================================================
# Localisation path: Kagi → subject URLs → BeautifulSoup → Chinese filter
# ==================================================================

def _compact_external_book_query(
    *, title: str | None = None, author: str | None = None,
    query: str | None = None, year: int | None = None,
    max_title_tokens: int = 6, max_author_tokens: int = 4,
) -> str:
    """Build a compact Kagi-friendly query string.

    - flattens whitespace
    - drops subtitle after `:` / `：`
    - limits title and author token count
    """
    parts: list[str] = []
    if title:
        head = re.split(r"[:：]", title, maxsplit=1)[0]
        tokens = re.split(r"\s+", head.strip())[:max_title_tokens]
        if tokens:
            parts.append(" ".join(tokens))
    if author:
        tokens = re.split(r"\s+", author.strip())[:max_author_tokens]
        if tokens:
            parts.append(" ".join(tokens))
    if query and not (title or author):
        parts.append(query.strip())
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _kagi_subject_urls(query: str, limit: int = 10) -> tuple[list[str], list[str]]:
    """Run `kagi search site:book.douban.com/subject {query}`.

    Returns (canonical_subject_urls, warnings). The strict regex filter
    drops any URL with extra path segments after the subject id.
    """
    cmd = ["kagi", "search", "--format", "json",
           f"site:book.douban.com/subject {query}"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20, check=False,
        )
    except FileNotFoundError:
        return [], ["kagi-search: kagi CLI not on PATH"]
    except subprocess.TimeoutExpired:
        return [], ["kagi-search: timeout"]
    except Exception as exc:
        return [], [f"kagi-search: {type(exc).__name__}: {exc}"]

    if result.returncode != 0:
        return [], [f"kagi-search: rc={result.returncode}: "
                    f"{(result.stderr or result.stdout)[:160]}"]

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return [], ["kagi-search: non-json output"]

    urls: list[str] = []
    seen: set[str] = set()
    for item in payload.get("data", []):
        raw = item.get("url", "") if isinstance(item, dict) else ""
        if not isinstance(raw, str):
            continue
        # Normalise `/subject/ID//` → `/subject/ID/` before matching.
        cleaned = re.sub(r"(/subject/\d+)/+", r"\1/", raw)
        m = _RE_DOUBAN_SUBJECT_CLEAN.match(cleaned)
        if not m:
            continue
        canonical = f"https://book.douban.com/subject/{m.group(1)}/"
        if canonical in seen:
            continue
        seen.add(canonical)
        urls.append(canonical)
        if len(urls) >= limit:
            break
    return urls, []


def _fetch_subject_via_bs4(url: str, cookie: str | None = None) -> dict | None:
    """Pull a Douban subject page via direct HTTP, parse with BeautifulSoup.

    Returns a raw record dict, or None if the page can't be fetched / is
    blocked / has no parseable title.
    """
    ok, body = _dd_fetch(url, cookie)
    if not ok or _is_blocked(body):
        return None

    soup = BeautifulSoup(body, "html.parser")
    sid_m = _SUBJECT_URL_RE.match(url)
    subject_id = sid_m.group(1) if sid_m else ""

    h1 = soup.find("span", property="v:itemreviewed")
    title = h1.get_text(strip=True) if h1 else ""
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = re.sub(r"\s*\(豆瓣\)\s*$", "", h1.get_text(strip=True))
    if not title:
        return None

    info = soup.find("div", id="info")
    rec: dict = {
        "douban_subject_id": subject_id,
        "douban_url": f"https://book.douban.com/subject/{subject_id}/",
        "title": title,
        "subtitle": "",
        "authors": [],
        "translators": [],
        "publisher": "",
        "year": None,
        "isbn_13": None,
        "isbn_10": None,
        "original_title": "",
        "ratings_count": 0,
        "douban_rating": None,
        "series": "",
    }
    if not info:
        return rec

    info_text = info.get_text("\n", strip=True)
    labels = ("作者", "译者", "出版社", "出版年", "ISBN",
              "原作名", "页数", "装帧", "定价", "丛书", "副标题")
    label_alt = "|".join(re.escape(item) for item in labels)

    def grab(label: str) -> str:
        m = re.search(
            rf"{re.escape(label)}\s*[:：]\s*(.+?)(?=\n(?:{label_alt})\s*[:：]|\n\n|$)",
            info_text,
            re.DOTALL,
        )
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    author_raw = grab("作者")
    translator_raw = grab("译者")
    publisher = grab("出版社")
    year_raw = grab("出版年")
    isbn = re.sub(r"[^0-9X]", "", grab("ISBN").upper())
    original_title = grab("原作名")
    subtitle = grab("副标题")
    series = grab("丛书")

    rec["subtitle"] = subtitle
    rec["series"] = series
    rec["original_title"] = original_title
    rec["publisher"] = publisher

    if author_raw:
        rec["authors"] = [a.strip() for a in re.split(r"\s*/\s*", author_raw) if a.strip()]
    if translator_raw:
        rec["translators"] = [t.strip() for t in re.split(r"\s*/\s*", translator_raw) if t.strip()]
    if year_raw:
        ym = re.search(r"((?:19|20)\d{2})", year_raw)
        if ym:
            try:
                rec["year"] = int(ym.group(1))
            except ValueError:
                pass
    if isbn:
        if len(isbn) == 13:
            rec["isbn_13"] = isbn
        elif len(isbn) == 10:
            rec["isbn_10"] = isbn

    rating_node = soup.find("strong", property="v:average")
    if rating_node:
        try:
            rec["douban_rating"] = float(rating_node.get_text(strip=True))
        except ValueError:
            pass
    votes_node = soup.find("span", property="v:votes")
    if votes_node:
        try:
            rec["ratings_count"] = int(votes_node.get_text(strip=True))
        except ValueError:
            pass

    if subtitle:
        rec["title"] = f"{title}:{subtitle}"
    return rec


def _is_chinese_edition(rec: dict) -> bool:
    """Decide whether a parsed Douban subject record is Chinese-language.

    Order matters:
      1. ISBN agency prefix is decisive — CN/TW/HK accept; JP/KR/VN reject.
      2. Kana or Hangul anywhere ⇒ reject (catches kanji-only JP titles).
      3. CJK in publisher | translator (non-empty AND CJK) | title ⇒ accept.
      4. Otherwise reject. A non-CJK translator (e.g. "Laurence Brottier"
         on a French edition) is not evidence of a Chinese edition.
    """
    title = rec.get("title", "") or ""
    publisher = rec.get("publisher", "") or ""
    translators = " ".join(
        t for t in (rec.get("translators") or []) if t
    )

    isbn = rec.get("isbn_13") or rec.get("isbn_10") or ""
    isbn_digits = re.sub(r"[^0-9]", "", isbn)
    if isbn_digits.startswith(_ZH_ISBN_PREFIXES):
        return True
    if isbn_digits.startswith(_NON_ZH_ASIAN_ISBN_PREFIXES):
        return False

    blob = f"{title} {publisher} {translators}"
    if _KANA_HANGUL_RE.search(blob):
        return False

    if _has_cjk(publisher):
        return True
    if translators.strip() and _has_cjk(translators):
        return True
    if _has_cjk(title):
        return True
    return False


def _zh_localisation_search(query: _s.BookQuery) -> tuple[list[dict], list[str]]:
    """Top-level Chinese-edition discovery via Kagi → BeautifulSoup.

    Returns (chinese_records, warnings). Chinese records are sorted by
    ratings_count desc (so the most-read edition surfaces first).
    """
    warnings: list[str] = []
    q = _compact_external_book_query(
        title=query.title, author=query.author,
        query=query.query, year=query.year_from,
    )
    if not q and query.isbn:
        q = query.isbn
    if not q:
        return [], ["zh-localisation: no usable query"]

    urls, kagi_warnings = _kagi_subject_urls(q, limit=max(query.limit, 10))
    warnings.extend(kagi_warnings)
    if not urls:
        return [], warnings

    out: list[dict] = []
    seen_ids: set[str] = set()
    for url in urls:
        time.sleep(random.random() * 0.3 + 0.2)
        rec = _fetch_subject_via_bs4(url)
        if rec is None:
            warnings.append(f"subject-fetch failed: {url}")
            continue
        if not _is_chinese_edition(rec):
            continue
        sid = rec.get("douban_subject_id") or ""
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        out.append(rec)

    out.sort(key=lambda r: r.get("ratings_count") or 0, reverse=True)
    return out, warnings


# ==================================================================
# Adapter glue: normalise + search wrappers
# ==================================================================

def _normalise(raw: dict) -> dict:
    b = _s.BookRecord().to_dict()
    b["title"]          = raw.get("title", "") or ""
    b["authors"]        = raw.get("authors") or []
    b["translators"]    = raw.get("translators") or []
    b["original_title"] = raw.get("original_title", "") or ""
    b["year"]           = raw.get("year")
    b["publisher"]      = raw.get("publisher", "") or ""
    b["isbn_13"]        = raw.get("isbn_13")
    b["isbn_10"]        = raw.get("isbn_10")
    b["language"]       = "zh"
    b["ratings"]        = {"count": raw.get("ratings_count"),
                           "average": raw.get("douban_rating")}
    b["preview_link"]   = raw.get("douban_url", "") or raw.get("preview_link", "") or ""
    b["source_ids"]["douban_cn"] = raw.get("douban_subject_id")
    b["_sources"] = [SOURCE_ID]
    return b


def _direct_search(query: _s.BookQuery) -> list[dict]:
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


def _wants_chinese_versions(query: _s.BookQuery) -> bool:
    return (query.subject or "").lower() in {
        "zh", "cn", "chinese", "translation", "translations", "cndouban",
    }


def search_book(query: _s.BookQuery) -> _s.AdapterResult:
    if not any([query.isbn, query.title, query.author, query.query, query.subject]):
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No query")

    if _wants_chinese_versions(query):
        translations, warnings = _zh_localisation_search(query)
        if not translations:
            return _s.AdapterResult(source=SOURCE_ID, success=True, entries=[])
        return _s.AdapterResult(
            source=SOURCE_ID, success=True,
            entries=[_normalise(e) for e in translations[:query.limit]],
        )

    direct = _direct_search(query)
    if not direct:
        return _s.AdapterResult(source=SOURCE_ID, success=True, entries=[])
    return _s.AdapterResult(
        source=SOURCE_ID, success=True,
        entries=[_normalise(e) for e in direct[:query.limit]],
    )

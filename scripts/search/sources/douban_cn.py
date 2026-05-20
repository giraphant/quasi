"""Douban CN adapter — books only.

Single discovery path: Kagi `site:book.douban.com/subject` query → strict
canonical-URL regex → direct HTTP + BeautifulSoup parse of each subject
page → optional Chinese-edition filter.

Why Kagi only: Douban's own `search.douban.com` endpoint rate-limits
aggressively and degrades silently. Kagi's index of Douban subject pages
is good enough that the Chinese edition of a translated English book
usually appears in the top 5–10 hits when querying by English title.
When it doesn't, that's accepted as a known coverage limit — there is no
search.douban.com fallback.
"""

from __future__ import annotations

import gzip
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))

import search as _s

SUPPORTS = ["book"]
SOURCE_ID = "douban_cn"


# ==================================================================
# Constants
# ==================================================================

_SUBJECT_URL_RE = re.compile(r".*/subject/(\d+)/?")

# Canonical-subject regex used for filtering Kagi results. Accepts the
# bare subject page in any form Kagi/Douban hand us: `/subject/{id}`,
# `/subject/{id}/`, `/subject/{id}//` (double-slash cruft),
# `/subject/{id}/?_dtcc=1` (Kagi tracking suffix), `/subject/{id}#frag`,
# etc — all normalise to `/subject/{id}/`. Rejects child paths like
# `/comments`, `/blockquotes`, `/doulists`, `/annotation`, `/offers`,
# `/buylinks`, `/reviews/...`.
_RE_DOUBAN_SUBJECT_CLEAN = re.compile(
    r"^https?://book\.douban\.com/subject/(\d+)/*(?:\?[^#]*)?(?:#.*)?$"
)

# ISBN agency prefixes that identify a Chinese-language edition:
#   978-7-xxx     — mainland China
#   978-957/986-x — Taiwan
#   978-988/962-x — Hong Kong
# Cleaner than a publisher whitelist (which would never keep up with the
# long tail of independent / academic presses).
_ZH_ISBN_PREFIXES = ("9787", "978957", "978986", "978988", "978962")

# Other Asian-CJK-language ISBN prefixes — explicitly NOT Chinese.
# Without this the kanji-only Japanese titles / kanji translator names
# slip past the generic CJK check (e.g. 伴侶種宣言 / 永野 文香 JP).
_NON_ZH_ASIAN_ISBN_PREFIXES = ("9784", "97889", "97811", "978604")

# Kana / Hangul ranges — presence in title / publisher / translator means
# it's clearly not Chinese.
_KANA_HANGUL_RE = re.compile(r"[぀-ゟ゠-ヿᄀ-ᇿ㄰-㆏가-힯]")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

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
# Kagi discovery
# ==================================================================

def _normalise_query_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _quote_phrase(value: str) -> str:
    value = _normalise_query_text(value).replace('"', "")
    return f'"{value}"' if value else ""


def _title_head(title: str) -> str:
    return _normalise_query_text(re.split(r"[:：]", title, maxsplit=1)[0])


def _author_tail(author: str) -> str:
    parts = re.split(r"\s+", _normalise_query_text(author))
    return parts[-1] if parts else ""


def _dedupe_keep_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        item = _normalise_query_text(item)
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _clean_cli_text(value: str) -> str:
    return _ANSI_RE.sub("", value or "").strip()


def _external_book_queries(
    *, title: str | None = None, author: str | None = None,
    query: str | None = None, isbn: str | None = None,
) -> list[str]:
    """Build ordered Kagi query variants for Douban subject discovery.

    Chinese editions often do not contain the romanised author name, so the
    first passes search by exact original title and Douban metadata hints.
    Author-qualified variants are fallbacks, not the primary query.
    """
    title_norm = _normalise_query_text(title)
    author_norm = _normalise_query_text(author)
    query_norm = _normalise_query_text(query)
    isbn_norm = _normalise_query_text(isbn)

    variants: list[str] = []
    if title_norm:
        quoted_title = _quote_phrase(title_norm)
        variants.extend([
            quoted_title,
            f"{quoted_title} 原作名",
            f"{quoted_title} 译者",
        ])
        head = _title_head(title_norm)
        if head and head != title_norm:
            quoted_head = _quote_phrase(head)
            variants.extend([
                quoted_head,
                f"{quoted_head} 原作名",
                f"{quoted_head} 译者",
            ])
        if author_norm:
            variants.extend([
                f"{quoted_title} {_quote_phrase(author_norm)}",
                f"{quoted_title} {_author_tail(author_norm)}",
                f"{title_norm} {author_norm}",
                _quote_phrase(author_norm),
                author_norm,
            ])
    elif query_norm:
        variants.extend([
            _quote_phrase(query_norm),
            f"{_quote_phrase(query_norm)} 原作名",
            query_norm,
        ])

    # ISBN is only useful as a Douban search term when it's the *Chinese*
    # edition's ISBN. The caller usually passes the original-language ISBN,
    # which Douban doesn't index — Kagi then falls back to popular unrelated
    # Chinese books for that variant. Only fire the ISBN variant when we
    # have nothing else to go on.
    if isbn_norm and not title_norm and not query_norm:
        variants.append(isbn_norm)

    return _dedupe_keep_order(variants)


def _compact_external_book_query(
    *, title: str | None = None, author: str | None = None,
    query: str | None = None, year: int | None = None,
) -> str:
    """Return the first Kagi query variant.

    Kept for tests and callers that want to inspect the primary query.
    """
    del year
    variants = _external_book_queries(title=title, author=author, query=query)
    return variants[0] if variants else ""


def _canonical_subject_url(raw: str) -> str | None:
    """Return canonical `/subject/<digits>/` URL, rejecting child pages."""
    if not isinstance(raw, str):
        return None
    m = _RE_DOUBAN_SUBJECT_CLEAN.fullmatch(raw.strip())
    if not m:
        return None
    return f"https://book.douban.com/subject/{m.group(1)}/"


def _kagi_env() -> dict[str, str]:
    env = os.environ.copy()
    token = os.environ.get("QUASI_KAGI_SESSION_TOKEN", "").strip()
    if token:
        env["KAGI_SESSION_TOKEN"] = token
    return env


def _cjk_dominant(s: str) -> bool:
    """Whether the string is majority CJK (vs Latin letters). Used as a
    cheap "this is a Chinese-edition Douban page" signal on Kagi's
    returned page-title, before we spend an HTTP fetch on it."""
    if not s:
        return False
    cjk = sum(1 for ch in s if "一" <= ch <= "鿿")
    latin = sum(1 for ch in s if ch.isascii() and ch.isalpha())
    return cjk > latin


def _kagi_subject_urls(query: str, limit: int = 20) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Run `kagi search site:book.douban.com/subject {query}`.

    Returns ([(canonical_url, page_title, snippet), ...], warnings). The
    canonical-URL filter normalises subject-page cruft (`//`, `?_dtcc=1`,
    `#frag`) and rejects child paths (`/comments`, `/blockquotes`, etc.).
    The Kagi page-title is preserved so callers can pre-filter (e.g.
    CJK-dominant) without spending a fetch.
    """
    cmd = ["kagi", "search", "--format", "json",
           f"site:book.douban.com/subject {query}"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20, check=False,
            env=_kagi_env(),
        )
    except FileNotFoundError:
        return [], ["kagi-search: kagi CLI not on PATH"]
    except subprocess.TimeoutExpired:
        return [], ["kagi-search: timeout"]
    except Exception as exc:
        return [], [f"kagi-search: {type(exc).__name__}: {exc}"]

    if result.returncode != 0:
        return [], [f"kagi-search: rc={result.returncode}: "
                    f"{_clean_cli_text(result.stderr or result.stdout)[:160]}"]

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return [], ["kagi-search: non-json output"]

    items: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        raw = item.get("url", "")
        if not isinstance(raw, str):
            continue
        canonical = _canonical_subject_url(raw)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        title = item.get("title", "") if isinstance(item.get("title"), str) else ""
        snippet = item.get("snippet", "") if isinstance(item.get("snippet"), str) else ""
        items.append((canonical, title, snippet))
        if len(items) >= limit:
            break
    return items, []


# ==================================================================
# Subject-page parser (BeautifulSoup against #info block)
# ==================================================================

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
            rf"(?:^|\n){re.escape(label)}\s*[:：]?\s*(.+?)(?=\n(?:{label_alt})\s*[:：]?|\n\n|$)",
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


def _strip_douban_title(value: str) -> str:
    return re.sub(r"\s*\(豆瓣\)\s*$", "", _normalise_query_text(value))


def _parse_kagi_snippet_record(url: str, kagi_title: str, snippet: str) -> dict | None:
    sid_m = _SUBJECT_URL_RE.match(url)
    subject_id = sid_m.group(1) if sid_m else ""
    title = _strip_douban_title(kagi_title)
    text = _normalise_query_text(snippet)
    if not text:
        return None
    if not title:
        title = re.split(r"\s+(?:作者|译者|出版社|出版年|ISBN|原作名)\s*[:：]", text, maxsplit=1)[0].strip()
    if not title:
        return None

    labels = ("作者", "译者", "出版社", "出品方", "出版年", "ISBN", "页数", "装帧", "定价", "原作名", "豆瓣评分")
    label_alt = "|".join(re.escape(item) for item in labels)

    def grab(label: str) -> str:
        m = re.search(
            rf"(?:^|\s){re.escape(label)}\s*[:：]?\s*(.+?)(?=\s(?:{label_alt})\s*[:：]?|$)",
            text,
            re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    rec: dict = {
        "douban_subject_id": subject_id,
        "douban_url": f"https://book.douban.com/subject/{subject_id}/" if subject_id else url,
        "title": title,
        "subtitle": "",
        "authors": [],
        "translators": [],
        "publisher": grab("出版社"),
        "year": None,
        "isbn_13": None,
        "isbn_10": None,
        "original_title": grab("原作名"),
        "ratings_count": 0,
        "douban_rating": None,
        "series": "",
    }

    author_raw = grab("作者")
    translator_raw = grab("译者")
    if author_raw:
        rec["authors"] = [a.strip() for a in re.split(r"\s*/\s*", author_raw) if a.strip()]
    if translator_raw:
        rec["translators"] = [t.strip() for t in re.split(r"\s*/\s*", translator_raw) if t.strip()]

    year_raw = grab("出版年")
    ym = re.search(r"((?:19|20)\d{2})", year_raw)
    if ym:
        rec["year"] = int(ym.group(1))

    isbn = re.sub(r"[^0-9X]", "", grab("ISBN").upper())
    if len(isbn) == 13:
        rec["isbn_13"] = isbn
    elif len(isbn) == 10:
        rec["isbn_10"] = isbn

    rating = re.search(r"豆瓣评分\s*([0-9](?:\.[0-9])?)", text)
    if rating:
        rec["douban_rating"] = float(rating.group(1))
    count = re.search(r"([0-9][0-9,]*)\s*人评价", text)
    if count:
        rec["ratings_count"] = int(count.group(1).replace(",", ""))
    return rec


def _is_chinese_edition(rec: dict) -> bool:
    """Decide whether a parsed Douban subject record is Chinese-language.

    Order matters:
      1. ISBN agency prefix is decisive — CN/TW/HK accept; JP/KR/VN reject.
      2. Kana or Hangul anywhere ⇒ reject (catches kanji-only JP titles).
      3. CJK in publisher | translator (non-empty AND CJK) | title ⇒ accept.
      4. Otherwise reject. The `authors` field is intentionally NOT used —
         Douban often lists a parallel Chinese transliteration of the
         author name on English-edition pages too (e.g. "Sara Ahmed /
         萨拉·艾哈迈德"), so author-CJK is not evidence of a Chinese
         edition.
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


# ==================================================================
# Top-level Kagi-driven search
# ==================================================================

def _kagi_book_search(
    query: _s.BookQuery, *, cjk_title_only: bool = False,
) -> tuple[list[dict], list[str]]:
    """Single discovery path: Kagi → canonical URLs → bs4 fetch.

    Returns (records, warnings). Records are the raw parsed dicts (one per
    successfully fetched subject page); ordering matches Kagi's result
    ranking. Chinese-edition filtering is the caller's responsibility.

    When `cjk_title_only=True`, Kagi hits whose page title is Latin-
    dominant are skipped before the HTTP fetch — drops English-edition
    Douban pages cheaply when the caller is doing zh-localisation.
    """
    warnings: list[str] = []
    queries = _external_book_queries(
        title=query.title, author=query.author,
        query=query.query, isbn=query.isbn,
    )
    if not queries:
        return [], ["kagi-book-search: no usable query"]

    url_limit = max(query.limit, 20)
    candidates: list[tuple[str, str, str]] = []
    seen_urls: set[str] = set()
    for q in queries:
        found, kagi_warnings = _kagi_subject_urls(q, limit=url_limit)
        warnings.extend(kagi_warnings)
        for url, kagi_title, snippet in found:
            if cjk_title_only and not _cjk_dominant(kagi_title):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append((url, kagi_title, snippet))
        if len(candidates) >= url_limit:
            break
    if not candidates:
        return [], warnings

    out: list[dict] = []
    seen: set[str] = set()
    for url, kagi_title, snippet in candidates:
        time.sleep(random.random() * 0.3 + 0.2)
        rec = _fetch_subject_via_bs4(url)
        if rec is None:
            rec = _parse_kagi_snippet_record(url, kagi_title, snippet)
        if rec is None:
            warnings.append(f"subject-fetch failed: {url}")
            continue
        sid = rec.get("douban_subject_id") or ""
        if sid in seen:
            continue
        seen.add(sid)
        out.append(rec)
    return out, warnings


def _zh_localisation_search(query: _s.BookQuery) -> tuple[list[dict], list[str]]:
    """Return Chinese-edition records from the Kagi-driven book search.

    Two-stage filter:
      1. Pre-fetch — `_kagi_book_search(..., cjk_title_only=True)` drops
         Kagi hits whose page title is Latin-dominant (typically the
         English-edition Douban page). Saves HTTP fetches.
      2. Post-fetch — `_is_chinese_edition` accepts any record whose
         publisher / translator / ISBN agency / title indicate a
         Chinese-language book.

    No "is this the translation of *this specific* book" check — that
    disambiguation is the caller agent's job. The bin returns the small
    set of Chinese-book candidates Kagi surfaced for the query.
    """
    records, warnings = _kagi_book_search(query, cjk_title_only=True)
    records = [r for r in records if _is_chinese_edition(r)]
    records.sort(key=lambda r: r.get("ratings_count") or 0, reverse=True)
    return records, warnings


# ==================================================================
# Adapter glue
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
    b["language"]       = "zh" if _is_chinese_edition(raw) else None
    b["ratings"]        = {"count": raw.get("ratings_count"),
                           "average": raw.get("douban_rating")}
    b["preview_link"]   = raw.get("douban_url", "") or raw.get("preview_link", "") or ""
    b["source_ids"]["douban_cn"] = raw.get("douban_subject_id")
    b["_sources"] = [SOURCE_ID]
    return b


def _wants_chinese_versions(query: _s.BookQuery) -> bool:
    return (query.subject or "").lower() in {
        "zh", "cn", "chinese", "translation", "translations", "cndouban",
    }


def search_book(query: _s.BookQuery) -> _s.AdapterResult:
    if not any([query.isbn, query.title, query.author, query.query, query.subject]):
        return _s.AdapterResult(source=SOURCE_ID, success=False, error="No query")

    if _wants_chinese_versions(query):
        records, warnings = _zh_localisation_search(query)
    else:
        records, warnings = _kagi_book_search(query)
    if not records:
        warnings = _dedupe_keep_order(warnings)
        if warnings:
            return _s.AdapterResult(
                source=SOURCE_ID,
                success=False,
                error="; ".join(warnings),
            )
        return _s.AdapterResult(source=SOURCE_ID, success=True, entries=[])
    return _s.AdapterResult(
        source=SOURCE_ID, success=True,
        entries=[_normalise(e) for e in records[:query.limit]],
    )

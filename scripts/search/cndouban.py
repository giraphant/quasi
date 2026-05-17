"""quasi-search cndouban — find Chinese editions of a foreign book on Douban.

Pure-mechanical bin. Pipeline:
  1. Locate primary Douban subject page via 3-path fallback:
     - book.douban.com/isbn/{isbn}     (direct, when ISBN known)
     - search.douban.com/book/subject_search?search_text={title}+{author}
     - search.douban.com/book/subject_search?search_text={author}
  2. Extract works_id from primary subject page → fetch works page.
  3. Enumerate all manifestations; filter Chinese editions by CJK publisher.
  4. Scrape each Chinese candidate for full metadata.
  5. Sort by ratings_count desc; return structured JSON.

No LLM judgment lives here. The agent reads stdout JSON and decides
what to write to frontmatter / translations.json.

All Douban requests go via `dokobot read --local`, reusing the same
subprocess pattern as `_search_google_books_via_doko` in search.py.

Output JSON contract:
    {
      "status": "ok" | "no-douban-entry" | "no-translations" | "error",
      "primary_subject": {                    # null when status=no-douban-entry
        "douban_id": str,
        "douban_url": str,
        "title_on_douban": str,
        "year_on_douban": int | null,
      },
      "translations": [                        # may be empty
        {
          "douban_id": str,
          "douban_url": str,
          "title": str,
          "author": str | null,
          "translator": str | null,
          "publisher": str | null,
          "year": int | null,
          "isbn": str | null,
          "original_title": str | null,
          "ratings_count": int,
        }, ...
      ],
      "diagnostics": {
        "routing": ["isbn-direct" | "search-title-author" | "search-author-only" | "works-page", ...],
        "doko_calls": int,
        "warnings": [str, ...],
      },
    }
"""

import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from typing import Optional


# ---------- helpers ----------

def _has_cjk(s: str) -> bool:
    return any('一' <= c <= '鿿' for c in (s or ""))


def _doko_read(url: str, timeout: int = 60) -> tuple[bool, str]:
    """Invoke `dokobot read --local <url>`; return (success, body).

    Mirrors the fallback in _search_google_books_via_doko: --local first;
    if the bridge isn't installed, retry without --local.
    """
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


# ---------- URL builders ----------

def _isbn_direct_url(isbn: str) -> str:
    isbn_clean = re.sub(r"[^0-9X]", "", (isbn or "").upper())
    return f"https://book.douban.com/isbn/{isbn_clean}/"


def _search_url(query: str) -> str:
    return ("https://search.douban.com/book/subject_search?"
            + urllib.parse.urlencode({"search_text": query}))


def _subject_url(subject_id: str) -> str:
    return f"https://book.douban.com/subject/{subject_id}/"


def _works_url(works_id: str) -> str:
    return f"https://book.douban.com/works/{works_id}/"


# ---------- regexes ----------

_RE_SUBJECT_ID = re.compile(r"book\.douban\.com/subject/(\d+)")
_RE_WORKS_ID = re.compile(r"book\.douban\.com/works/(\d+)")

# Subject-page metadata labels (Douban uses ' : ' or ' ：' separator)
_RE_AUTHOR = re.compile(r"作\s*者[:：]\s*(.+?)(?:\n|$)")
_RE_TRANSLATOR = re.compile(r"译\s*者[:：]\s*(.+?)(?:\n|$)")
_RE_PUBLISHER = re.compile(r"出版社[:：]\s*(.+?)(?:\n|$)")
_RE_PUBLISH_YEAR = re.compile(r"出版年[:：]\s*(\d{4})")
_RE_ISBN = re.compile(r"ISBN[:：]\s*([\dX-]+)")
_RE_ORIGINAL_TITLE = re.compile(r"原作名[:：]\s*(.+?)(?:\n|$)")
_RE_RATINGS_COUNT = re.compile(r"(\d{1,7})\s*人\s*评价")

# Publisher heuristic for works-page (no clean structure — scan nearby text)
_RE_PUBLISHER_HINT = re.compile(
    r"([一-鿿　A-Za-z·\s]{2,40}?"
    r"(?:出版社|书店|印书馆|出版|文化|公司|大学|图书|译丛|出版部|事业|集团))"
)
_RE_YEAR_PAREN = re.compile(r"[（(](\d{4})[)）]")


# ---------- parsers ----------

def _grab(rx, body, default=None):
    m = rx.search(body or "")
    if not m:
        return default
    return m.group(1).strip()


def _guess_title_from_subject_page(body: str) -> Optional[str]:
    """Heuristic: H1 / page header usually renders as the first prominent line.

    Doko strips most markup; the title typically appears within the first
    ~10 non-trivial lines. Skip site chrome ('豆瓣读书', '登录', etc.).
    """
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
        # Skip pure ascii navigation links
        if len(line) < 2:
            continue
        return line[:200]
    return None


def _parse_subject_page(body: str, subject_id: str) -> dict:
    year_str = _grab(_RE_PUBLISH_YEAR, body)
    year = int(year_str) if year_str and year_str.isdigit() else None
    ratings_m = _RE_RATINGS_COUNT.search(body or "")
    ratings_count = int(ratings_m.group(1)) if ratings_m else 0

    return {
        "douban_id": subject_id,
        "douban_url": _subject_url(subject_id),
        "title": _guess_title_from_subject_page(body),
        "author": _grab(_RE_AUTHOR, body),
        "translator": _grab(_RE_TRANSLATOR, body),
        "publisher": _grab(_RE_PUBLISHER, body),
        "year": year,
        "isbn": _grab(_RE_ISBN, body),
        "original_title": _grab(_RE_ORIGINAL_TITLE, body),
        "ratings_count": ratings_count,
    }


def _extract_works_id(body: str) -> Optional[str]:
    m = _RE_WORKS_ID.search(body or "")
    return m.group(1) if m else None


def _extract_manifestations_from_works_page(body: str) -> list[dict]:
    """Pull (subject_id, publisher_hint, year_hint) tuples from a works page.

    The page text isn't strictly structured, so we scan for each subject_id
    URL and look at the surrounding 3 lines for publisher + year hints.
    """
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
        # Context window: 3 lines before through this line
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


# ---------- slug reverse derivation ----------

def _reverse_from_slug(slug: str) -> dict:
    """Best-effort split of `{author}-{title-words}-{year}` style slugs.

    Returns dict with whatever could be parsed: author_surname, title_words, year.
    Caller can fall back to direct args when slug doesn't disambiguate cleanly.
    """
    parts = (slug or "").split("-")
    result: dict = {}
    if len(parts) >= 3 and parts[-1].isdigit() and len(parts[-1]) == 4:
        result["year"] = int(parts[-1])
        result["author"] = parts[0]
        result["title"] = " ".join(parts[1:-1])
    return result


# ---------- main pipeline ----------

def find_cndouban(*, isbn: Optional[str] = None,
                  title: Optional[str] = None,
                  author: Optional[str] = None,
                  year: Optional[int] = None,
                  slug: Optional[str] = None) -> dict:
    diagnostics = {"routing": [], "doko_calls": 0, "warnings": []}

    if slug and not (title and author):
        rev = _reverse_from_slug(slug)
        title = title or rev.get("title")
        author = author or rev.get("author")
        year = year or rev.get("year")

    # Bail fast if no inputs
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

    # Path A: ISBN-direct (book.douban.com/isbn/X redirects to subject page)
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

    # Path B: search by title + author
    if primary_subject is None and title and author:
        q = f"{title} {author}"
        diagnostics["routing"].append("search-title-author")
        diagnostics["doko_calls"] += 1
        ok, body = _doko_read(_search_url(q))
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

    # Path C: search by author only
    if primary_subject is None and author:
        diagnostics["routing"].append("search-author-only")
        diagnostics["doko_calls"] += 1
        ok, body = _doko_read(_search_url(author))
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

    primary_meta = _parse_subject_page(primary_body, primary_subject)

    # ----- Step 2: works-page enumeration -----
    manifestations: list[dict] = []
    works_id = _extract_works_id(primary_body)
    if works_id:
        diagnostics["routing"].append("works-page")
        diagnostics["doko_calls"] += 1
        ok, body = _doko_read(_works_url(works_id))
        if ok:
            manifestations = _extract_manifestations_from_works_page(body)
        else:
            diagnostics["warnings"].append(f"works-page {works_id}: {body[:120]}")

    if not manifestations:
        # Fallback: treat primary subject as the only manifestation
        manifestations = [{
            "subject_id": primary_subject,
            "publisher_hint": primary_meta.get("publisher"),
            "year_hint": primary_meta.get("year"),
        }]
        diagnostics["warnings"].append("works-page absent — using primary subject only")

    # ----- Step 3: filter Chinese candidates -----
    chinese_candidates = [m for m in manifestations
                          if _has_cjk(m.get("publisher_hint") or "")]

    # If the primary subject itself has a CJK publisher and it's not already in
    # the chinese_candidates list, add it (works-page sometimes omits the canonical entry).
    if _has_cjk(primary_meta.get("publisher") or ""):
        if not any(m["subject_id"] == primary_subject for m in chinese_candidates):
            chinese_candidates.append({
                "subject_id": primary_subject,
                "publisher_hint": primary_meta.get("publisher"),
                "year_hint": primary_meta.get("year"),
            })

    if not chinese_candidates:
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
    for cand in chinese_candidates:
        sid = cand["subject_id"]
        if sid == primary_subject:
            # Reuse cached primary body
            translations.append(primary_meta)
            continue
        diagnostics["doko_calls"] += 1
        ok, body = _doko_read(_subject_url(sid))
        if not ok:
            diagnostics["warnings"].append(f"candidate {sid}: {body[:120]}")
            continue
        translations.append(_parse_subject_page(body, sid))

    # Sort by ratings_count desc (constraint-friendly default)
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


# ---------- CLI hook called by quasi-search dispatcher ----------

def run_cndouban(args) -> int:
    result = find_cndouban(
        isbn=args.isbn,
        title=args.title,
        author=args.author,
        year=args.year,
        slug=args.slug,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Exit 0 for any well-formed outcome (ok / no-douban-entry / no-translations).
    # Exit 1 only on hard error (bad inputs, unhandled exception).
    return 0 if result["status"] != "error" else 1

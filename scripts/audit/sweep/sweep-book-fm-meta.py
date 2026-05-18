#!/usr/bin/env python3
"""
用 Crossref works API 为 vault/books/*/00-overview.md 补 publisher / isbn / doi / source。

策略:
  - 只补「字段缺失或为空」的项,绝不覆盖已有非空值
  - 用清洗后 title + 第一作者姓查询;首次失败时把 ": Subtitle" 截掉再试
  - filter type:book,monograph,edited-book,reference-book
  - 候选按 (title 重叠度, |year差|) 综合排序,最佳候选拿 publisher/ISBN/DOI
  - 写回 publisher (str), isbn (first 13-digit if any), doi (str), source: book

依赖: 标准库 + pyyaml
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

import yaml


FM_RE = re.compile(r"\A(---\n)(.*?)(\n---\n?)", re.DOTALL)
UA = "bts-vault-meta-fix/0.2 (mailto:yanyu.zhou@warwick.ac.uk)"
CR_URL = "https://api.crossref.org/works"

BOOK_TYPES = {
    "book", "monograph", "edited-book", "reference-book", "book-set", "book-series",
    "book-track", "book-part", "book-section", "book-chapter",
}


def http_get_json(url: str, timeout: int = 25, retries: int = 2) -> dict:
    last = ""
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            last = str(e)
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    return {"__error__": last}


def normalize_tokens(s: str) -> set[str]:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return {t for t in s.split() if len(t) > 2 and t not in {
        "the", "and", "for", "with", "from", "into", "about", "this", "that", "are", "edition",
    }}


def title_overlap(a: str, b: str) -> float:
    """Coverage of the SHORTER side. Lets 'A: B' (fm) match 'A' (CR) when only A is the canonical title."""
    ta, tb = normalize_tokens(a), normalize_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def query_crossref(title: str, author_last: str) -> list[dict]:
    params = {
        "query.title": title,
        "rows": 8,
        "select": "DOI,title,subtitle,author,publisher,ISBN,issued,type",
    }
    if author_last:
        params["query.author"] = author_last
    url = f"{CR_URL}?{urllib.parse.urlencode(params)}"
    data = http_get_json(url)
    if "__error__" in data:
        return []
    items = data.get("message", {}).get("items", []) or []
    # post-filter to book-ish types (Crossref's server-side multi-type filter is unreliable)
    return [it for it in items if it.get("type") in BOOK_TYPES]


def best_candidate(items: list[dict], fm_title: str, fm_year: int | None) -> dict | None:
    scored = []
    for idx, it in enumerate(items):
        cr_title = (it.get("title") or [""])[0]
        cr_sub = (it.get("subtitle") or [""])[0]
        full = (cr_title + " " + cr_sub).strip()
        ov = title_overlap(fm_title, full)
        if ov < 0.55:
            continue
        cr_year = (it.get("issued", {}).get("date-parts") or [[None]])[0][0]
        year_gap = abs((cr_year or 0) - (fm_year or 0)) if fm_year and cr_year else 9999
        has_pub = 1 if it.get("publisher") else 0
        # idx is a stable tie-breaker so that scored.sort() never compares dicts
        scored.append((-ov, year_gap, -has_pub, idx, it))
    scored.sort()
    return scored[0][4] if scored else None


def first_author_last(authors_field) -> str:
    if isinstance(authors_field, list) and authors_field:
        a = str(authors_field[0]).strip()
    elif authors_field:
        a = str(authors_field).strip()
    else:
        return ""
    # take last whitespace-separated token as surname
    parts = a.split()
    return parts[-1] if parts else a


def truncate_at_colon(title: str) -> str | None:
    if ":" in title:
        return title.split(":", 1)[0].strip()
    return None


def pick_isbn(isbns: list[str]) -> str | None:
    if not isbns:
        return None
    # prefer ISBN-13
    for x in isbns:
        digits = re.sub(r"[^0-9]", "", x)
        if len(digits) == 13:
            return digits
    digits = re.sub(r"[^0-9X]", "", isbns[0].upper())
    return digits or None


def parse_fm_block(text: str):
    m = FM_RE.match(text)
    if not m:
        return None
    open_, block, close = m.group(1), m.group(2), m.group(3)
    rest = text[m.end():]
    try:
        data = yaml.safe_load(block) or {}
        if not isinstance(data, dict):
            return None
    except yaml.YAMLError:
        return None
    return open_, block, close, rest, data


def is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    if isinstance(v, list) and not v:
        return True
    return False


def replace_or_insert(block: str, key: str, value_inline: str) -> str:
    pat = re.compile(rf"^({re.escape(key)}):[ \t]*.*$", re.MULTILINE)
    new_line = f"{key}: {value_inline}"
    new_block, n = pat.subn(new_line, block, count=1)
    if n == 0:
        new_block = block.rstrip("\n") + f"\n{new_line}"
    return new_block


def render_str(s: str) -> str:
    if any(c in s for c in [":", "#", "'", '"']) or s != s.strip():
        return yaml.safe_dump(s, default_style="'", allow_unicode=True).strip()
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--misses", default="reports/book-meta-misses.txt")
    ap.add_argument("--hits", default="reports/book-meta-hits.tsv")
    ap.add_argument("--start-from", default="")
    args = ap.parse_args()

    files = sorted(pathlib.Path("vault/books").glob("*/00-overview.md"))
    if args.start_from:
        files = [f for f in files if f.parent.name >= args.start_from]
    if args.limit:
        files = files[: args.limit]

    pathlib.Path(args.misses).parent.mkdir(parents=True, exist_ok=True)
    misses_fh = open(args.misses, "a", encoding="utf-8")
    hits_fh = open(args.hits, "a", encoding="utf-8")

    looked = matched = updated = missed = skipped_full = skipped_bad = 0

    for fp in files:
        slug = fp.parent.name
        text = fp.read_text(encoding="utf-8")
        parsed = parse_fm_block(text)
        if not parsed:
            skipped_bad += 1
            continue
        open_, block, close, rest, data = parsed

        need_pub = is_empty(data.get("publisher"))
        need_isbn = is_empty(data.get("isbn"))
        need_doi = is_empty(data.get("doi"))
        need_src = is_empty(data.get("source"))

        if not (need_pub or need_isbn or need_doi or need_src):
            skipped_full += 1
            continue

        title = str(data.get("title") or "").strip()
        author_last = first_author_last(data.get("authors"))
        try:
            fm_year = int(data.get("year")) if data.get("year") else None
        except (TypeError, ValueError):
            fm_year = None

        if not title:
            missed += 1
            misses_fh.write(f"{slug}\tno-title\n")
            continue

        looked += 1
        items = query_crossref(title, author_last)
        best = best_candidate(items, title, fm_year)
        # fallback: drop subtitle if no match
        if not best:
            short = truncate_at_colon(title)
            if short and short.lower() != title.lower():
                time.sleep(args.sleep)
                items = query_crossref(short, author_last)
                best = best_candidate(items, title, fm_year)
        time.sleep(args.sleep)

        if not best:
            missed += 1
            misses_fh.write(f"{slug}\tno-match\ttitle={title}\tauthor={author_last}\n")
            print(f"  MISS  {slug}")
            continue

        matched += 1
        cr_title = (best.get("title") or [""])[0]
        cr_year = (best.get("issued", {}).get("date-parts") or [[None]])[0][0]
        pub = best.get("publisher") or ""
        isbn = pick_isbn(best.get("ISBN") or [])
        doi = best.get("DOI") or ""

        new_block = block
        diffs = []
        if need_pub and pub:
            new_block = replace_or_insert(new_block, "publisher", render_str(pub))
            diffs.append(f"publisher={pub}")
        if need_isbn and isbn:
            new_block = replace_or_insert(new_block, "isbn", render_str(isbn))
            diffs.append(f"isbn={isbn}")
        if need_doi and doi:
            new_block = replace_or_insert(new_block, "doi", render_str(doi))
            diffs.append(f"doi={doi}")
        if need_src:
            new_block = replace_or_insert(new_block, "source", "book")
            diffs.append("source=book")

        hits_fh.write(f"{slug}\t{cr_year}\t{pub}\t{isbn or ''}\t{doi}\n")
        if not diffs:
            print(f"  POOR  {slug}  matched but no new fields")
            continue

        updated += 1
        print(f"  OK    {slug}  ::  {', '.join(diffs)[:140]}")

        if args.write:
            fp.write_text(open_ + new_block + close + rest, encoding="utf-8")

    misses_fh.close()
    hits_fh.close()

    print(f"\n=== summary ===")
    print(f"  looked up   : {looked}")
    print(f"  matched     : {matched}")
    print(f"  updated     : {updated}")
    print(f"  missed      : {missed}")
    print(f"  skipped full: {skipped_full}")
    print(f"  skipped bad : {skipped_bad}")
    print(f"  mode        : {'WRITE' if args.write else 'DRY-RUN'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
对 Crossref 未命中的书 (reports/book-meta-misses.txt 列出的 slug) 用 OpenLibrary 兜底。

OpenLibrary 对学术专著 metadata 较差(publisher/isbn 常缺),
但对非英语书与编著的 ISBN/出版社命中可能比 Crossref 好,值得作 secondary source。

匹配条件: title overlap >= 0.55 (短侧覆盖率),year ±2 优先
写回: publisher (str) / isbn (str) / source: book —— 仍只补缺失字段,不覆盖

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
OL_URL = "https://openlibrary.org/search.json"


def http_get_json(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"__error__": str(e)}


def normalize_tokens(s: str) -> set[str]:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return {t for t in s.split() if len(t) > 2 and t not in {
        "the", "and", "for", "with", "from", "into", "about", "this", "that", "are",
    }}


def title_overlap(a: str, b: str) -> float:
    ta, tb = normalize_tokens(a), normalize_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def query_ol(title: str, author: str) -> list[dict]:
    params = {"title": title, "limit": 5, "fields": "title,subtitle,first_publish_year,author_name,publisher,isbn"}
    if author:
        params["author"] = author
    url = f"{OL_URL}?{urllib.parse.urlencode(params)}"
    data = http_get_json(url)
    if "__error__" in data:
        return []
    return data.get("docs", []) or []


def best(items: list[dict], fm_title: str, fm_year: int | None) -> dict | None:
    scored = []
    for idx, d in enumerate(items):
        full = (d.get("title", "") + " " + (d.get("subtitle") or "")).strip()
        ov = title_overlap(fm_title, full)
        if ov < 0.55:
            continue
        year = d.get("first_publish_year")
        gap = abs((year or 0) - (fm_year or 0)) if fm_year and year else 9999
        has_pub = 1 if d.get("publisher") else 0
        has_isbn = 1 if d.get("isbn") else 0
        scored.append((-ov, gap, -(has_pub + has_isbn), idx, d))
    scored.sort()
    return scored[0][4] if scored else None


def first_author_last(authors) -> str:
    if isinstance(authors, list) and authors:
        a = str(authors[0])
    elif authors:
        a = str(authors)
    else:
        return ""
    p = a.strip().split()
    return p[-1] if p else a


def parse_fm(text: str):
    m = FM_RE.match(text)
    if not m:
        return None
    open_, block, close = m.group(1), m.group(2), m.group(3)
    rest = text[m.end():]
    try:
        d = yaml.safe_load(block) or {}
        if not isinstance(d, dict):
            return None
    except yaml.YAMLError:
        return None
    return open_, block, close, rest, d


def is_empty(v) -> bool:
    if v is None: return True
    if isinstance(v, str) and not v.strip(): return True
    if isinstance(v, list) and not v: return True
    return False


def replace_or_insert(block: str, key: str, value: str) -> str:
    pat = re.compile(rf"^({re.escape(key)}):[ \t]*.*$", re.MULTILINE)
    new = f"{key}: {value}"
    nb, n = pat.subn(new, block, count=1)
    if n == 0:
        nb = block.rstrip("\n") + f"\n{new}"
    return nb


def render_str(s: str) -> str:
    if any(c in s for c in [":", "#", "'", '"']) or s != s.strip():
        return yaml.safe_dump(s, default_style="'", allow_unicode=True).strip()
    return s


def pick_isbn(isbns: list[str]) -> str | None:
    for x in isbns or []:
        digits = re.sub(r"[^0-9]", "", str(x))
        if len(digits) == 13:
            return digits
    if isbns:
        return re.sub(r"[^0-9X]", "", str(isbns[0]).upper()) or None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--misses-in", default="reports/book-meta-misses.txt")
    ap.add_argument("--misses-out", default="reports/book-meta-misses-after-ol.txt")
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    slugs = []
    misses_path = pathlib.Path(args.misses_in)
    if not misses_path.exists():
        print(f"No misses file at {misses_path}")
        return 0
    for line in misses_path.read_text(encoding="utf-8").splitlines():
        slug = line.split("\t", 1)[0].strip()
        if slug:
            slugs.append(slug)
    if args.limit:
        slugs = slugs[: args.limit]

    pathlib.Path(args.misses_out).parent.mkdir(parents=True, exist_ok=True)
    out_fh = open(args.misses_out, "w", encoding="utf-8")

    looked = matched = updated = still = 0

    for slug in slugs:
        fp = pathlib.Path("vault/books") / slug / "00-overview.md"
        if not fp.exists():
            continue
        parsed = parse_fm(fp.read_text(encoding="utf-8"))
        if not parsed:
            continue
        open_, block, close, rest, data = parsed

        need_pub = is_empty(data.get("publisher"))
        need_isbn = is_empty(data.get("isbn"))
        need_src = is_empty(data.get("source"))
        if not (need_pub or need_isbn or need_src):
            continue

        title = str(data.get("title") or "").strip()
        author_last = first_author_last(data.get("authors"))
        try:
            yr = int(data.get("year")) if data.get("year") else None
        except (TypeError, ValueError):
            yr = None
        if not title:
            still += 1; out_fh.write(f"{slug}\tno-title\n"); continue

        looked += 1
        items = query_ol(title, author_last)
        b = best(items, title, yr)
        if not b:
            # try title-only
            short = title.split(":", 1)[0].strip()
            if short and short.lower() != title.lower():
                time.sleep(args.sleep)
                items = query_ol(short, author_last)
                b = best(items, title, yr)
        time.sleep(args.sleep)

        if not b:
            still += 1
            out_fh.write(f"{slug}\tol-no-match\ttitle={title}\n")
            print(f"  STILL MISS  {slug}")
            continue

        matched += 1
        pubs = b.get("publisher") or []
        isbn = pick_isbn(b.get("isbn") or [])
        ol_year = b.get("first_publish_year")

        new_block = block
        diffs = []
        if need_pub and pubs:
            new_block = replace_or_insert(new_block, "publisher", render_str(str(pubs[0])))
            diffs.append(f"publisher={pubs[0]}")
        if need_isbn and isbn:
            new_block = replace_or_insert(new_block, "isbn", render_str(isbn))
            diffs.append(f"isbn={isbn}")
        if need_src:
            new_block = replace_or_insert(new_block, "source", "book")
            diffs.append("source=book")

        if not diffs:
            still += 1
            out_fh.write(f"{slug}\tol-matched-no-fields\tol_year={ol_year}\n")
            continue

        updated += 1
        print(f"  OL OK       {slug}  ::  {', '.join(diffs)[:140]}")
        if args.write:
            fp.write_text(open_ + new_block + close + rest, encoding="utf-8")

    out_fh.close()
    print(f"\n=== summary ===")
    print(f"  looked       : {looked}")
    print(f"  OL matched   : {matched}")
    print(f"  OL updated   : {updated}")
    print(f"  still missing: {still}")
    print(f"  mode         : {'WRITE' if args.write else 'DRY-RUN'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

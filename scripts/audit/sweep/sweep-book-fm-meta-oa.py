#!/usr/bin/env python3
"""
OpenAlex + Crossref-DOI 兜底 — 处理 Crossref title search 和 AA 都没能补上的剩余书。

为什么这条路有用:
  - OpenAlex 索引覆盖跟 Crossref 不完全重叠,尤其对学术 monographs / chapter-level
  - OA 自己的 venue/publisher 字段脏(常把 chapter 写到完全无关的期刊里),
    所以**不要直接信 OA 的 venue/publisher**
  - 但 OA 经常能返回 DOI;只要拿到 DOI,就回查 Crossref `/works/<doi>` 拿权威 publisher

流程:
  1. 扫 vault/books,找仍缺 publisher 的 slug
  2. OpenAlex search → 候选(title overlap ≥ 0.55, year ±2 优先)
  3. 候选有 DOI → Crossref `/works/<doi>` 拿 publisher/ISBN/年份
  4. 写回 publisher / isbn / doi / source

不覆盖任何已有非空字段。
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
UA = "bts-vault-meta-fix/0.3 (mailto:yanyu.zhou@warwick.ac.uk)"


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
                time.sleep(1.0 * (attempt + 1))
    return {"__error__": last}


def normalize_tokens(s: str) -> set[str]:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return {t for t in s.split() if len(t) > 2 and t not in {
        "the", "and", "for", "with", "from", "into", "about", "this", "that", "are", "edition",
    }}


def title_overlap(a: str, b: str) -> float:
    ta, tb = normalize_tokens(a), normalize_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def search_openalex(title: str, author: str = "") -> list[dict]:
    """Return OA works candidates. Filter by type=book-ish."""
    q = title
    if author:
        q = f"{title} {author}"
    p = {
        "search": q,
        "per_page": 8,
        "select": "id,doi,title,publication_year,type,authorships",
        "mailto": "yanyu.zhou@warwick.ac.uk",
    }
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(p)
    data = http_get_json(url)
    if "__error__" in data:
        return []
    out = []
    for w in data.get("results", []) or []:
        t = (w.get("type") or "").lower()
        if t not in {"book", "book-chapter", "monograph", "edited-book", "reference-book", "book-set"}:
            # OA sometimes uses 'book-section' too; keep broadly inclusive
            if "book" not in t:
                continue
        out.append(w)
    return out


def query_crossref_doi(doi: str) -> dict | None:
    """Fetch full Crossref record for a DOI."""
    if not doi:
        return None
    doi = doi.replace("https://doi.org/", "").lstrip("/")
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}?mailto=yanyu.zhou@warwick.ac.uk"
    data = http_get_json(url)
    if "__error__" in data or "message" not in data:
        return None
    return data["message"]


def best_oa(items: list[dict], fm_title: str, fm_year: int | None) -> dict | None:
    scored = []
    for idx, w in enumerate(items):
        ov = title_overlap(fm_title, w.get("title", ""))
        if ov < 0.55:
            continue
        ry = w.get("publication_year")
        gap = abs((ry or 0) - (fm_year or 0)) if fm_year and ry else 9999
        has_doi = 1 if w.get("doi") else 0
        scored.append((-ov, gap, -has_doi, idx, w))
    scored.sort()
    return scored[0][4] if scored else None


def pick_isbn13(isbns: list[str]) -> str | None:
    for x in isbns or []:
        digits = re.sub(r"[^0-9]", "", x)
        if len(digits) == 13:
            return digits
    if isbns:
        return re.sub(r"[^0-9X]", "", str(isbns[0]).upper()) or None
    return None


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
    s = s.strip()
    if any(c in s for c in [":", "#", "'", '"']):
        return yaml.safe_dump(s, default_style="'", allow_unicode=True).strip()
    return s


def first_author_last(authors) -> str:
    if isinstance(authors, list) and authors:
        a = str(authors[0])
    elif authors:
        a = str(authors)
    else:
        return ""
    p = a.strip().split()
    return p[-1] if p else a


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--misses-out", default="reports/book-meta-misses-after-oa.txt")
    args = ap.parse_args()

    files = sorted(pathlib.Path("vault/books").glob("*/00-overview.md"))
    todo = []
    for fp in files:
        parsed = parse_fm(fp.read_text(encoding="utf-8"))
        if not parsed:
            continue
        _, _, _, _, d = parsed
        if is_empty(d.get("publisher")) or is_empty(d.get("isbn")) or is_empty(d.get("doi")):
            todo.append(fp)
    if args.limit:
        todo = todo[: args.limit]

    pathlib.Path(args.misses_out).parent.mkdir(parents=True, exist_ok=True)
    miss_fh = open(args.misses_out, "w", encoding="utf-8")

    print(f"  candidates: {len(todo)}", flush=True)
    looked = matched_oa = matched_cr = updated = still = 0

    for fp in todo:
        slug = fp.parent.name
        parsed = parse_fm(fp.read_text(encoding="utf-8"))
        if not parsed:
            continue
        open_, block, close, rest, data = parsed

        need_pub = is_empty(data.get("publisher"))
        need_isbn = is_empty(data.get("isbn"))
        need_doi = is_empty(data.get("doi"))
        need_src = is_empty(data.get("source"))

        title = str(data.get("title") or "").strip()
        author_last = first_author_last(data.get("authors"))
        try:
            fm_year = int(data.get("year")) if data.get("year") else None
        except (TypeError, ValueError):
            fm_year = None
        if not title:
            still += 1
            miss_fh.write(f"{slug}\tno-title\n"); miss_fh.flush()
            continue

        looked += 1
        oa_items = search_openalex(title, author_last)
        time.sleep(args.sleep)
        best = best_oa(oa_items, title, fm_year)

        doi = ""
        pub = ""
        isbn = None
        if best:
            matched_oa += 1
            doi = (best.get("doi") or "").replace("https://doi.org/", "").lstrip("/")

        # if we got a DOI, query Crossref for authoritative publisher/ISBN
        cr = None
        if doi:
            cr = query_crossref_doi(doi)
            time.sleep(args.sleep)
        if cr:
            matched_cr += 1
            pub = (cr.get("publisher") or "").strip()
            isbn = pick_isbn13(cr.get("ISBN") or [])
            if not doi:
                doi = (cr.get("DOI") or "").strip()

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

        if not diffs:
            still += 1
            miss_fh.write(f"{slug}\toa-no-doi-or-cr-empty\toa_doi={doi}\n"); miss_fh.flush()
            print(f"  OA MISS  {slug}", flush=True)
            continue

        updated += 1
        print(f"  OA OK    {slug}  ::  {', '.join(diffs)[:160]}", flush=True)
        if args.write:
            fp.write_text(open_ + new_block + close + rest, encoding="utf-8")

    miss_fh.close()
    print(f"\n=== summary ===")
    print(f"  todo            : {len(todo)}")
    print(f"  looked up       : {looked}")
    print(f"  OA matched      : {matched_oa}")
    print(f"  CR (via DOI)    : {matched_cr}")
    print(f"  updated         : {updated}")
    print(f"  still           : {still}")
    print(f"  mode            : {'WRITE' if args.write else 'DRY-RUN'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

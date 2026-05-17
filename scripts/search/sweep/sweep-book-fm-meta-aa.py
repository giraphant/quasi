#!/usr/bin/env python3
"""
Anna's Archive 兜底 — 对 vault/books/*/00-overview.md 中仍缺 publisher 的书,
通过 `quasi-search books --source aa --json` 取 md5 与 publisher,
必要时再抓 `/md5/<hash>` 详情页解析 metadata-comments 中的 JSON 拿 ISBN/publisher。

工作流:
  1. 自动扫描 vault/books,找仍缺 publisher 或 isbn 的 slug
  2. 对每个: quasi-search aa → 取最佳候选 (year ±2)
  3. 拿 publisher (取多版本叠加字符串第一段) + year + md5
  4. 如果 publisher 仍空 或 isbn 缺,curl 详情页拿结构化 JSON
  5. 写回 frontmatter (publisher / isbn / source: book)

写入只补缺失字段,绝不覆盖已有非空值。

依赖: 标准库 + pyyaml + quasi-search (plugin) 在 PATH
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.request

import yaml


FM_RE = re.compile(r"\A(---\n)(.*?)(\n---\n?)", re.DOTALL)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X) BTS-Research/1.0"


def is_empty(v) -> bool:
    if v is None: return True
    if isinstance(v, str) and not v.strip(): return True
    if isinstance(v, list) and not v: return True
    return False


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


def normalize_pub(raw: str) -> str:
    """AA 的 publisher 单元格是多个版本叠加,取第一段(去掉年份/数字尾巴)。"""
    if not raw:
        return ""
    first = raw.split(",")[0].strip()
    # strip trailing year-ish tokens like "2018", "United Kingdom"
    first = re.sub(r"\s*\d{4}.*$", "", first).strip()
    return first


def normalize_tokens(s: str) -> set[str]:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return {t for t in s.split() if len(t) > 2 and t not in {
        "the", "and", "for", "with", "from", "into", "about", "this", "that", "are",
    }}


def title_match(fm_title: str, ol_title: str, threshold: float = 0.55) -> bool:
    a, b = normalize_tokens(fm_title), normalize_tokens(ol_title)
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= threshold


def query_aa(title: str, author: str, limit: int = 5, timeout: int = 60) -> list[dict]:
    """Invoke quasi-search wrapper so plugin hook injects QUASI_ANNA_DONATOR_KEY."""
    cmd = ["quasi-search", "books", "--source", "aa", title, "--limit", str(limit), "--json"]
    if author:
        cmd += ["--author", author]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return []
    out = r.stdout
    # quasi-search prints status text before the JSON array; find the first '['
    i = out.find("[")
    if i < 0:
        return []
    try:
        data = json.loads(out[i:])
    except json.JSONDecodeError:
        return []
    if not data:
        return []
    return data[0].get("results", []) or []


def fetch_aa_md5_meta(md5: str, mirrors: list[str], timeout: int = 25) -> dict:
    """Scrape /md5/<hash> page; extract metadata-comments JSON {publisher,isbns,...}."""
    for base in mirrors:
        url = f"{base}/md5/{md5}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                html = r.read().decode("utf-8", errors="ignore")
        except Exception:
            continue
        # find every `metadata comments` block — its body is one of the
        # subsequent `<div class="mb-1">...</div>` siblings
        out = {}
        # Look for JSON blobs containing "publisher" and "isbns"
        for m in re.finditer(r'\{[^{}]*"publisher"\s*:\s*"([^"]+)"[^{}]*\}', html):
            blob = m.group(0)
            # unescape HTML entities
            blob = blob.replace("&#34;", '"').replace("&quot;", '"').replace("&amp;", "&")
            try:
                # try parse again after unescape
                m2 = re.search(r'"publisher"\s*:\s*"([^"]+)"', blob)
                if m2:
                    out.setdefault("publisher", m2.group(1).strip())
                m3 = re.search(r'"isbns"\s*:\s*\[([^\]]+)\]', blob)
                if m3:
                    isbns = re.findall(r'"([0-9Xx]+)"', m3.group(1))
                    if isbns:
                        out.setdefault("isbns", isbns)
                break
            except Exception:
                continue
        # ISBN-13 in dedicated tabs
        if "isbns" not in out:
            m4 = re.findall(r'>ISBN-13</span>\s*<span[^>]*>([\d-]+)', html)
            if m4:
                out["isbns"] = [re.sub(r"-", "", x) for x in m4]
        # Alternative publisher (first one)
        if "publisher" not in out:
            m5 = re.search(r'>Alternative publisher</div>\s*<div class="mb-1">([^<]+)</div>', html)
            if m5:
                out["publisher"] = m5.group(1).strip()
        return out
    return {}


def pick_isbn13(isbns: list[str]) -> str | None:
    for x in isbns or []:
        digits = re.sub(r"[^0-9]", "", x)
        if len(digits) == 13:
            return digits
    if isbns:
        return re.sub(r"[^0-9X]", "", str(isbns[0]).upper()) or None
    return None


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
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--start-from", default="")
    ap.add_argument("--misses-out", default="reports/book-meta-misses-after-aa.txt")
    ap.add_argument("--mirrors", default="https://annas-archive.gl,https://annas-archive.pk,https://annas-archive.gd")
    args = ap.parse_args()

    mirrors = [m.strip().rstrip("/") for m in args.mirrors.split(",") if m.strip()]

    files = sorted(pathlib.Path("vault/books").glob("*/00-overview.md"))
    if args.start_from:
        files = [f for f in files if f.parent.name >= args.start_from]
    # filter to those still needing publisher / isbn / source
    todo = []
    for fp in files:
        parsed = parse_fm(fp.read_text(encoding="utf-8"))
        if not parsed:
            continue
        _, _, _, _, d = parsed
        if is_empty(d.get("publisher")) or is_empty(d.get("isbn")) or is_empty(d.get("source")):
            todo.append(fp)
    if args.limit:
        todo = todo[: args.limit]

    pathlib.Path(args.misses_out).parent.mkdir(parents=True, exist_ok=True)
    miss_fh = open(args.misses_out, "w", encoding="utf-8")

    print(f"  candidates: {len(todo)}", flush=True)

    looked = 0
    matched = 0
    updated = 0
    still = 0

    for fp in todo:
        slug = fp.parent.name
        parsed = parse_fm(fp.read_text(encoding="utf-8"))
        if not parsed:
            continue
        open_, block, close, rest, data = parsed

        need_pub = is_empty(data.get("publisher"))
        need_isbn = is_empty(data.get("isbn"))
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
        results = query_aa(title, author_last)
        # filter by title match + year proximity
        cands = []
        for idx, r in enumerate(results):
            if not title_match(title, r.get("title", "")):
                continue
            try:
                ry = int(re.match(r"\d{4}", str(r.get("year","")).strip()).group(0))
            except Exception:
                ry = None
            gap = abs((ry or 0) - (fm_year or 0)) if fm_year and ry else 9999
            has_pub = 1 if r.get("publisher") else 0
            cands.append((gap, -has_pub, idx, r))
        cands.sort()
        time.sleep(args.sleep)

        if not cands:
            still += 1
            miss_fh.write(f"{slug}\taa-no-match\ttitle={title[:80]}\n"); miss_fh.flush()
            print(f"  AA MISS  {slug}", flush=True)
            continue

        matched += 1
        _, _, _, best = cands[0]
        md5 = best.get("md5", "")
        pub = normalize_pub(best.get("publisher") or "")
        isbn = None  # AA table doesn't usually expose ISBN in the JSON results

        # if we still need pub or isbn, fetch the md5 detail page
        if (need_pub and not pub) or need_isbn:
            if md5:
                detail = fetch_aa_md5_meta(md5, mirrors)
                if not pub:
                    pub = normalize_pub(detail.get("publisher", ""))
                if not isbn:
                    isbn = pick_isbn13(detail.get("isbns") or [])
                time.sleep(args.sleep)

        new_block = block
        diffs = []
        if need_pub and pub:
            new_block = replace_or_insert(new_block, "publisher", render_str(pub))
            diffs.append(f"publisher={pub}")
        if need_isbn and isbn:
            new_block = replace_or_insert(new_block, "isbn", render_str(isbn))
            diffs.append(f"isbn={isbn}")
        if need_src:
            new_block = replace_or_insert(new_block, "source", "book")
            diffs.append("source=book")

        if not diffs:
            still += 1
            miss_fh.write(f"{slug}\taa-matched-no-fields\tmd5={md5}\n"); miss_fh.flush()
            print(f"  AA POOR  {slug}", flush=True)
            continue

        updated += 1
        print(f"  AA OK    {slug}  ::  {', '.join(diffs)[:160]}", flush=True)
        if args.write:
            fp.write_text(open_ + new_block + close + rest, encoding="utf-8")

    miss_fh.close()

    print(f"\n=== summary ===")
    print(f"  todo (need pub/isbn/source): {len(todo)}")
    print(f"  looked up : {looked}")
    print(f"  matched   : {matched}")
    print(f"  updated   : {updated}")
    print(f"  still     : {still}")
    print(f"  mode      : {'WRITE' if args.write else 'DRY-RUN'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

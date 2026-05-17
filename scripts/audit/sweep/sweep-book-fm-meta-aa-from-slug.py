#!/usr/bin/env python3
"""
AA 兜底第二轮 — 对仍缺 publisher 的书,用 **slug** 反构 title 来查询。

为什么有效:
  - 第一轮 AA 用 frontmatter title 查询失败,原因常是 title 已被翻译成中文 /
    或带 "(eds., year)" 这类括号备注,搜索引擎匹配不到原书
  - slug (kebab-case) 已经是 `{author}-{title-slug}-{year}` 这种规整形式,
    去掉首段作者前缀和末段年份后,中间就是干净的英文 title 关键词
  - 例: `latour-never-been-modern-1993` -> query `never been modern` + author `Latour` -> AA 一发命中

流程跟 sweep-book-fm-meta-aa.py 相同,只把 search query 从 fm.title 换成 slug-derived。
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
    if not raw:
        return ""
    # AA gives "Boston, Beacon Press, 2018Beacon Press..." style — try to find a Press-like token
    # First: prefer chunks containing Press|Books|Publishing|Verlag|Editions|University Press
    chunks = re.split(r"[,;]|(?<=[a-z]) (?=[A-Z][a-z]+ (?:Press|Publishing|Books|Verlag|Editions|University))", raw)
    presslike = [c.strip() for c in chunks if re.search(r"\b(Press|Publishing|Books|Verlag|Editions|University|Imprint|Routledge|Bloomsbury|Wiley|Sage|Polity|Springer|Palgrave|Penguin|Random|Norton|Beacon|Viking|Knopf|Vintage)\b", c, re.I)]
    if presslike:
        # take shortest non-empty (avoids "London ; New York : Routledge" → prefer "Routledge")
        presslike.sort(key=len)
        return re.sub(r"\s+", " ", presslike[0]).strip()
    # fallback: first comma-segment minus trailing year/number
    first = raw.split(",")[0].strip()
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


def author_match(needle: str, haystack: str) -> bool:
    """needle is the author surname (e.g. 'birkhead'), haystack is AA's author cell."""
    if not needle:
        return True  # nothing to verify against
    h = (haystack or "").lower()
    n = needle.lower().strip()
    return n in h


def query_aa(title: str, author: str, limit: int = 5, timeout: int = 60) -> list[dict]:
    cmd = ["quasi-search", "books", "--source", "aa", title, "--limit", str(limit), "--json"]
    if author:
        cmd += ["--author", author]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return []
    out = r.stdout
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
    for base in mirrors:
        url = f"{base}/md5/{md5}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                html = r.read().decode("utf-8", errors="ignore")
        except Exception:
            continue
        out = {}
        for m in re.finditer(r'\{[^{}]*"publisher"\s*:\s*"([^"]+)"[^{}]*\}', html):
            blob = m.group(0).replace("&#34;", '"').replace("&quot;", '"').replace("&amp;", "&")
            mp = re.search(r'"publisher"\s*:\s*"([^"]+)"', blob)
            if mp:
                out.setdefault("publisher", mp.group(1).strip())
            mi = re.search(r'"isbns"\s*:\s*\[([^\]]+)\]', blob)
            if mi:
                isbns = re.findall(r'"([0-9Xx]+)"', mi.group(1))
                if isbns:
                    out.setdefault("isbns", isbns)
            break
        if "isbns" not in out:
            m4 = re.findall(r'>ISBN-13</span>\s*<span[^>]*>([\d-]+)', html)
            if m4:
                out["isbns"] = [re.sub(r"-", "", x) for x in m4]
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


def slug_to_title(slug: str) -> tuple[str, str, int | None]:
    """`atanasoski-vora-surrogate-humanity-2019` -> (title='surrogate humanity', author='atanasoski', year=2019).

    Strategy: strip trailing 4-digit year; take first hyphen-segment as author surname
    (or first two for double-author slugs like atanasoski-vora-).  Rest is title."""
    parts = slug.split("-")
    year = None
    if parts and re.fullmatch(r"\d{4}", parts[-1]):
        year = int(parts[-1])
        parts = parts[:-1]
    # the author prefix is 1-2 short tokens at the start (common surnames are 1 word)
    # heuristic: take parts[0] as author surname; if parts[1] also looks like a surname
    # (single word, not a stopword), keep title starting from parts[2]
    author = parts[0] if parts else ""
    title_start = 1
    stopwords = {"the", "a", "an", "and", "of", "in", "on", "from", "for", "to", "with"}
    if len(parts) >= 3 and len(parts[1]) >= 3 and parts[1].lower() not in stopwords and parts[1].isalpha():
        # could be two-author slug; can't tell from slug alone, but trying both queries below
        pass
    title = " ".join(parts[title_start:])
    return title.strip(), author, year


def first_author_from_fm(authors) -> str:
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
    ap.add_argument("--sleep", type=float, default=0.4)
    ap.add_argument("--mirrors", default="https://annas-archive.gl,https://annas-archive.pk,https://annas-archive.gd")
    ap.add_argument("--misses-out", default="reports/book-meta-misses-after-aa-slug.txt")
    args = ap.parse_args()

    mirrors = [m.strip().rstrip("/") for m in args.mirrors.split(",") if m.strip()]

    files = sorted(pathlib.Path("vault/books").glob("*/00-overview.md"))
    todo = []
    for fp in files:
        parsed = parse_fm(fp.read_text(encoding="utf-8"))
        if not parsed:
            continue
        _, _, _, _, d = parsed
        if is_empty(d.get("publisher")) or is_empty(d.get("isbn")):
            todo.append(fp)
    if args.limit:
        todo = todo[: args.limit]

    pathlib.Path(args.misses_out).parent.mkdir(parents=True, exist_ok=True)
    miss_fh = open(args.misses_out, "w", encoding="utf-8")

    print(f"  candidates: {len(todo)}", flush=True)
    looked = matched = updated = still = 0

    for fp in todo:
        slug = fp.parent.name
        parsed = parse_fm(fp.read_text(encoding="utf-8"))
        if not parsed:
            continue
        open_, block, close, rest, data = parsed

        need_pub = is_empty(data.get("publisher"))
        need_isbn = is_empty(data.get("isbn"))
        need_src = is_empty(data.get("source"))
        if not (need_pub or need_isbn):
            continue

        slug_title, slug_author, slug_year = slug_to_title(slug)
        fm_year = slug_year
        try:
            if data.get("year"):
                fm_year = int(data.get("year"))
        except (TypeError, ValueError):
            pass

        # prefer fm author when present (more reliable surname), fall back to slug author
        author_last = first_author_from_fm(data.get("authors")) or slug_author

        if not slug_title:
            still += 1
            miss_fh.write(f"{slug}\tno-title-from-slug\n"); miss_fh.flush()
            continue

        looked += 1
        results = query_aa(slug_title, author_last)
        cands = []
        for idx, r in enumerate(results):
            if not title_match(slug_title, r.get("title", "")):
                continue
            # author name (or slug surname token) must appear in the AA author cell
            slug_surname = slug.split("-", 1)[0]  # 'birkhead-the-red-canary-...' -> 'birkhead'
            if not (author_match(author_last, r.get("author", "")) or author_match(slug_surname, r.get("author", ""))):
                continue
            try:
                ry = int(re.match(r"\d{4}", str(r.get("year","")).strip()).group(0))
            except Exception:
                ry = None
            # require year ±3 when both are known (allows reprints / paperback editions)
            if fm_year and ry and abs(ry - fm_year) > 3:
                continue
            gap = abs((ry or 0) - (fm_year or 0)) if fm_year and ry else 9999
            has_pub = 1 if r.get("publisher") else 0
            cands.append((gap, -has_pub, idx, r))
        cands.sort()
        time.sleep(args.sleep)

        if not cands:
            still += 1
            miss_fh.write(f"{slug}\taa-no-match\tquery=\"{slug_title}\" author={author_last}\n"); miss_fh.flush()
            print(f"  AA MISS  {slug}  (q={slug_title!r})", flush=True)
            continue

        matched += 1
        _, _, _, best = cands[0]
        md5 = best.get("md5", "")
        pub = normalize_pub(best.get("publisher") or "")
        isbn = None

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
        print(f"  AA OK    {slug}  ::  q={slug_title!r}  ->  {', '.join(diffs)[:140]}", flush=True)
        if args.write:
            fp.write_text(open_ + new_block + close + rest, encoding="utf-8")

    miss_fh.close()
    print(f"\n=== summary ===")
    print(f"  candidates : {len(todo)}")
    print(f"  looked up  : {looked}")
    print(f"  matched    : {matched}")
    print(f"  updated    : {updated}")
    print(f"  still      : {still}")
    print(f"  mode       : {'WRITE' if args.write else 'DRY-RUN'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

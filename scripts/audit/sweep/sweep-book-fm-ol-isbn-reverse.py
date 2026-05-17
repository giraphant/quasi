#!/usr/bin/env python3
"""
OL ISBN reverse lookup — 用已知 ISBN 反查 OpenLibrary 拿权威 publisher,清洗 vault publisher 字段。

策略(保守):
  - 已有 publisher **看起来不对**才替换:city-only / 含年份前缀 / 过长 / 含明显 garbage
  - 已有 publisher **看起来对**保留不动(避免引入新 noise)
  - OL 返回 ISBN-not-found 标记 review(可能 ISBN 错配)
  - OL 返回 title 跟 vault title 完全 mismatch → 标记 review(ISBN 错配错书)
  - 输出 3 个 review 文件: garbage-fixed.tsv / isbn-notfound.tsv / title-mismatch.tsv
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
UA = "bts-vault-meta-fix/0.4 (mailto:yanyu.zhou@warwick.ac.uk)"

# A publisher string is "garbage" if it looks like one of these
CITY_WORDS = {
    "boston","berkeley","cambridge","london","new york","chicago","philadelphia",
    "oxford","princeton","stanford","manchester","edinburgh","dublin","amsterdam",
    "paris","tokyo","munich","berlin","vienna","sydney","toronto","montreal",
    "bingley","bristol","durham","ithaca","indianapolis","minneapolis","atlanta",
    "los angeles","san francisco","washington","baltimore","seattle","portland",
}


def is_garbage_publisher(pub: str) -> tuple[bool, str]:
    """Only flag for OL-replacement when we have no useful info locally.
    For locally-cleanable noise (imprint-phrase, semicolon-joined, year-prefix,
    too-long, city-prefix), prefer local clean over OL replace, because
    OL tends to collapse imprints to parent groups (worse than what we have)."""
    if not pub:
        return True, "empty"
    p = pub.strip()
    pl = p.lower()
    if pl in CITY_WORDS:
        return True, "city-only"
    return False, ""


def clean_publisher_locally(p: str) -> str:
    """Salvage useful publisher name from AA-style noisy strings:
       'Routledge is an imprint of T&F'   -> 'Routledge'
       'MIT Press; The MIT Press'         -> 'MIT Press'
       'Berkeley : University of California Press' -> 'University of California Press'
       '1999Macmillan Publishers Limited...' -> 'Macmillan Publishers Limited'
       'X, United Kingdom, 2018'          -> 'X'
    """
    if not p:
        return p
    s = p.strip()
    # 'X is an imprint of Y' -> X
    m = re.match(r"^(.+?)\s+is\s+(?:an\s+)?imprint\b", s, re.I)
    if m:
        s = m.group(1).strip()
    # 'This X imprint is published by Y' -> X
    m = re.match(r"^This\s+(.+?)\s+Imprint\s+Is\s+Published\s+By\s+(.+)$", s, re.I)
    if m:
        # prefer the imprint, not the parent
        s = m.group(1).strip()
    # 'Berkeley : University of California Press' -> 'University of California Press'
    m = re.match(r"^(?:Boston|Berkeley|Cambridge|London|New York|Chicago|Philadelphia|Bingley|Bristol|Durham|Ithaca)\s*:\s*(.+)$", s)
    if m:
        s = m.group(1).strip()
    # leading year prefix '1999Macmillan...' -> 'Macmillan...'
    s = re.sub(r"^\d{4}(?=[A-Z])", "", s)
    # multi-publisher 'A; B; C' -> first chunk
    if ";" in s:
        s = s.split(";")[0].strip()
    # 'X, United Kingdom, 2018' -> 'X'
    parts = s.split(",")
    if len(parts) > 1:
        # drop trailing chunks that are pure year or territory
        clean_parts = []
        for c in parts:
            cs = c.strip()
            if re.match(r"^\d{4}$", cs): break
            if re.match(r"^(United Kingdom|United States|United States and Canada|Ireland|Germany|France)\b", cs): break
            clean_parts.append(cs)
        if clean_parts:
            s = ", ".join(clean_parts).strip()
    # final length sanity
    if len(s) > 80:
        # take everything up to the first comma
        s = s.split(",")[0].strip()
    return s.strip()


def normalize_tokens(s: str) -> set[str]:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return {t for t in s.split() if len(t) > 2 and t not in {
        "the","and","for","with","from","into","about","this","that","are",
        "edition","new","second","first","third","revised","book","books",
    }}


def title_match(fm_title: str, ol_title: str, threshold: float = 0.5) -> bool:
    a, b = normalize_tokens(fm_title), normalize_tokens(ol_title)
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= threshold


def ol_isbn(isbn: str, timeout: int = 20) -> dict:
    url = f"https://openlibrary.org/isbn/{isbn}.json"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"__notfound__": True}
        return {"__err__": str(e)}
    except Exception as e:
        return {"__err__": str(e)}


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
    new_line = f"{key}: {value}"
    nb, n = pat.subn(new_line, block, count=1)
    if n == 0:
        nb = block.rstrip("\n") + f"\n{new_line}"
    return nb


def render_str(s: str) -> str:
    s = s.strip()
    if any(c in s for c in [":", "#", "'", '"']):
        return yaml.safe_dump(s, default_style="'", allow_unicode=True).strip()
    return s


def pick_ol_publisher(publishers: list[str]) -> str:
    """OL gives a list; prefer the shortest non-imprint that contains Press/Publishing/Books."""
    if not publishers:
        return ""
    pubs = [p.strip() for p in publishers if p and p.strip()]
    if not pubs:
        return ""
    # rank: prefer one with Press/Publishing/Books/Verlag, shortest first
    pubs.sort(key=lambda p: (
        0 if re.search(r"\b(Press|Publishing|Books|Verlag|Editions)\b", p, re.I) else 1,
        len(p),
    ))
    return pubs[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reports-dir", default="reports")
    ap.add_argument("--force-all", action="store_true",
                    help="Replace publisher even when it doesn't look like garbage. Default: only fix garbage.")
    args = ap.parse_args()

    rpd = pathlib.Path(args.reports_dir); rpd.mkdir(parents=True, exist_ok=True)
    f_fixed = open(rpd / "ol-publisher-fixed.tsv", "w", encoding="utf-8")
    f_notfound = open(rpd / "ol-isbn-notfound.tsv", "w", encoding="utf-8")
    f_mismatch = open(rpd / "ol-title-mismatch.tsv", "w", encoding="utf-8")
    f_fixed.write("slug\tisbn\told_publisher\tnew_publisher\treason\n")
    f_notfound.write("slug\tisbn\tcur_publisher\tcur_title\n")
    f_mismatch.write("slug\tisbn\tvault_title\tol_title\tcur_publisher\tol_publisher\n")

    files = sorted(pathlib.Path("vault/books").glob("*/00-overview.md"))
    if args.limit:
        files = files[: args.limit]

    looked = local_cleaned = ol_fixed = unchanged = nf = mismatch = skip = 0

    for fp in files:
        slug = fp.parent.name
        text = fp.read_text(encoding="utf-8")
        parsed = parse_fm(text)
        if not parsed:
            skip += 1; continue
        open_, block, close, rest, data = parsed

        cur_pub = (data.get("publisher") or "").strip()
        vault_title = (data.get("title") or "").strip()

        # 1. local clean first — fixes most AA-noise without any network call
        locally_cleaned = clean_publisher_locally(cur_pub)
        new_pub = locally_cleaned if locally_cleaned and locally_cleaned != cur_pub else None

        # 2. if still garbage (city-only / empty) AND we have an ISBN, ask OL
        candidate = new_pub if new_pub else cur_pub
        is_garbage, reason = is_garbage_publisher(candidate)

        isbn = str(data.get("isbn") or "").strip().replace("-", "")
        has_isbn = bool(re.match(r"^\d{10}(\d{3})?$", isbn))

        if is_garbage and has_isbn:
            looked += 1
            j = ol_isbn(isbn)
            time.sleep(args.sleep)
            if j.get("__notfound__"):
                nf += 1
                f_notfound.write(f"{slug}\t{isbn}\t{cur_pub}\t{vault_title}\n"); f_notfound.flush()
            elif "__err__" not in j:
                ol_title = (j.get("title") or "").strip()
                ol_pubs = j.get("publishers") or []
                ol_pub = pick_ol_publisher(ol_pubs)
                if vault_title and ol_title and not title_match(vault_title, ol_title):
                    mismatch += 1
                    f_mismatch.write(f"{slug}\t{isbn}\t{vault_title}\t{ol_title}\t{cur_pub}\t{ol_pub}\n"); f_mismatch.flush()
                elif ol_pub:
                    new_pub = ol_pub
                    reason_used = "OL-isbn-reverse"

        if not new_pub or new_pub.strip().lower() == cur_pub.strip().lower():
            unchanged += 1
            continue

        # apply fix
        new_block = replace_or_insert(block, "publisher", render_str(new_pub))
        if new_block == block:
            unchanged += 1
            continue

        used_ol = locally_cleaned != new_pub
        if used_ol:
            ol_fixed += 1
            f_fixed.write(f"{slug}\t{isbn}\t{cur_pub}\t{new_pub}\tOL-isbn-reverse\n"); f_fixed.flush()
            print(f"  OL-FIX  {slug}  {cur_pub!r:<35}  ->  {new_pub!r}", flush=True)
        else:
            local_cleaned += 1
            f_fixed.write(f"{slug}\t-\t{cur_pub}\t{new_pub}\tlocal-clean\n"); f_fixed.flush()
            print(f"  LOCAL   {slug}  {cur_pub!r:<50}  ->  {new_pub!r}", flush=True)

        if args.write:
            fp.write_text(open_ + new_block + close + rest, encoding="utf-8")

    f_fixed.close(); f_notfound.close(); f_mismatch.close()

    print(f"\n=== summary ===")
    print(f"  local-cleaned    : {local_cleaned}")
    print(f"  OL-fixed (city)  : {ol_fixed}")
    print(f"  OL looked up     : {looked}")
    print(f"  OL not found     : {nf}   (review: {rpd}/ol-isbn-notfound.tsv)")
    print(f"  OL title mismatch: {mismatch}   (review: {rpd}/ol-title-mismatch.tsv)")
    print(f"  unchanged        : {unchanged}")
    print(f"  skipped (no fm)  : {skip}")
    print(f"  mode             : {'WRITE' if args.write else 'DRY-RUN'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

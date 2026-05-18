#!/usr/bin/env python3
"""
**终极兜底** — 直接用本地 `sources/<slug>.pdf` 的 MD5 查 AA 详情页拿 publisher/ISBN。

为什么这条路最稳:
  - 用户的 vault 是从 AA 下载来的,sources/ 下的 PDF 哈希 = AA 数据库的 MD5
  - 不走任何 search/match — 是同一份文件,metadata 100% 是这本书的
  - 不需要 donator key,/md5/<hash> 页面是公开的

流程:
  1. 扫 vault/books,找仍缺 publisher 的 slug
  2. 找 sources/<slug>.{pdf,epub} 文件,计算 MD5
  3. curl https://annas-archive.gl/md5/<hash>
  4. 解析 "metadata comments" 里的 JSON: {"publisher":"...","isbns":[...]}
  5. 写回 frontmatter
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
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


def normalize_pub(raw: str) -> str:
    if not raw:
        return ""
    chunks = re.split(r"[,;]", raw)
    presslike = [c.strip() for c in chunks if re.search(
        r"\b(Press|Publishing|Books|Verlag|Editions|Imprint|Routledge|Bloomsbury|Wiley|Sage|Polity|Springer|Palgrave|Penguin|Random|Norton|Beacon|Viking|Knopf|Vintage|Belknap|Harvard|Columbia|Princeton|Oxford|Cambridge|MIT|Duke|Stanford|Minnesota|Chicago|California|Yale|Cornell)\b", c, re.I)]
    if presslike:
        presslike.sort(key=len)
        return re.sub(r"\s+", " ", presslike[0]).strip()
    first = raw.split(",")[0].strip()
    first = re.sub(r"\s*\d{4}.*$", "", first).strip()
    return first


def md5_of(path: pathlib.Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def fetch_aa_md5(md5: str, mirrors: list[str], timeout: int = 30) -> dict:
    for base in mirrors:
        url = f"{base}/md5/{md5}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                final_url = r.geturl()
                html = r.read().decode("utf-8", errors="ignore")
        except Exception:
            continue
        # AA 301-redirects unknown md5s to /search?q=md5:<hash>
        if "/search" in final_url and "md5%3A" in final_url or "/search" in final_url and "md5:" in final_url:
            return {"__notfound__": True}
        if "Sorry, the page you were looking for could not be found" in html or "is not found in our database" in html:
            return {"__notfound__": True}

        out: dict = {}
        # primary: metadata-comments JSON {"publisher":"...","isbns":[...]}
        for m in re.finditer(r'\{[^{}]*"publisher"\s*:\s*"([^"]+)"[^{}]*\}', html):
            blob = m.group(0).replace("&#34;", '"').replace("&quot;", '"').replace("&amp;", "&")
            mp = re.search(r'"publisher"\s*:\s*"([^"]+)"', blob)
            if mp and "publisher" not in out:
                out["publisher"] = mp.group(1).strip()
            mi = re.search(r'"isbns"\s*:\s*\[([^\]]+)\]', blob)
            if mi and "isbns" not in out:
                isbns = re.findall(r'"([0-9Xx]+)"', mi.group(1))
                if isbns:
                    out["isbns"] = isbns
            if "publisher" in out and "isbns" in out:
                break

        # secondary: ISBN-13 chips (already on the page)
        if "isbns" not in out:
            m4 = re.findall(r'>ISBN-13</span>\s*<span[^>]*>([\d-]+)', html)
            if m4:
                out["isbns"] = [re.sub(r"-", "", x) for x in m4]

        # tertiary: Alternative publisher block (first one is usually the canonical edition's)
        if "publisher" not in out:
            m5 = re.search(r'>Alternative publisher</div>\s*<div class="mb-1">([^<]+)</div>', html)
            if m5:
                out["publisher"] = m5.group(1).strip()

        # year hints
        m6 = re.search(r'>Alternative edition</div>\s*<div class="mb-1">([^<]+)</div>', html)
        if m6:
            ym = re.search(r"\b(19\d{2}|20\d{2})\b", m6.group(1))
            if ym:
                out["year"] = int(ym.group(1))
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


def find_source_file(slug: str) -> pathlib.Path | None:
    for ext in (".pdf", ".epub"):
        p = pathlib.Path("sources") / f"{slug}{ext}"
        if p.exists():
            return p
    # also try with the editor-prefix variant (e.g. alaimo-hekman-...)
    matches = list(pathlib.Path("sources").glob(f"{slug}.*"))
    return matches[0] if matches else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--mirrors", default="https://annas-archive.gl,https://annas-archive.pk,https://annas-archive.gd")
    ap.add_argument("--misses-out", default="reports/book-meta-misses-after-md5.txt")
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
            src = find_source_file(fp.parent.name)
            if src:
                todo.append((fp, src))
    if args.limit:
        todo = todo[: args.limit]

    pathlib.Path(args.misses_out).parent.mkdir(parents=True, exist_ok=True)
    miss_fh = open(args.misses_out, "w", encoding="utf-8")

    print(f"  candidates (have source file + missing pub/isbn): {len(todo)}", flush=True)
    looked = found = updated = notfound = empty = 0

    for fp, src in todo:
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

        looked += 1
        md5 = md5_of(src)
        meta = fetch_aa_md5(md5, mirrors)
        time.sleep(args.sleep)

        if meta.get("__notfound__"):
            notfound += 1
            miss_fh.write(f"{slug}\taa-md5-notfound\tmd5={md5}\tsrc={src.name}\n"); miss_fh.flush()
            print(f"  MD5 NF   {slug}  md5={md5[:12]}…  ({src.name})", flush=True)
            continue
        if not meta:
            miss_fh.write(f"{slug}\taa-md5-no-response\tmd5={md5}\n"); miss_fh.flush()
            print(f"  MD5 ERR  {slug}  md5={md5[:12]}…", flush=True)
            continue

        pub = normalize_pub(meta.get("publisher") or "")
        isbn = pick_isbn13(meta.get("isbns") or [])

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
            empty += 1
            miss_fh.write(f"{slug}\taa-md5-empty-meta\tmd5={md5}\n"); miss_fh.flush()
            print(f"  MD5 EMP  {slug}  md5={md5[:12]}…  meta={meta}", flush=True)
            continue

        found += 1
        updated += 1
        print(f"  MD5 OK   {slug}  ::  {', '.join(diffs)[:140]}", flush=True)
        if args.write:
            fp.write_text(open_ + new_block + close + rest, encoding="utf-8")

    miss_fh.close()
    print(f"\n=== summary ===")
    print(f"  candidates    : {len(todo)}")
    print(f"  looked up     : {looked}")
    print(f"  found+updated : {updated}")
    print(f"  notfound      : {notfound}")
    print(f"  empty meta    : {empty}")
    print(f"  mode          : {'WRITE' if args.write else 'DRY-RUN'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

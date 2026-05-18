#!/usr/bin/env python3
"""
清洗 vault/books/*/00-overview.md 的 frontmatter:
  - title:   剥掉 markdown 强调、剥掉前缀作者名、剥掉外层引号、剥掉 "— 书籍概览" 后缀
  - authors: 解开 [[slug|Name]] wikilink, 输出为干净的 YAML flow list

策略: 用 yaml.safe_load 解析 frontmatter 拿到结构化值,但**只在原文里替换 title:/authors: 这两行**,
其他字段一行不动 —— 把 diff 控制到最小,不引入 year 引号、source 空值之类的无意义改动。

干跑 (默认): 只打印将要修改的样本和总数
写入: --write
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml


FM_RE = re.compile(r"\A(---\n)(.*?)(\n---\n?)", re.DOTALL)
WIKILINK = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]|\[\[([^\]]+)\]\]")


def strip_wikilink(s: str) -> str:
    def repl(m: re.Match) -> str:
        return m.group(2) or m.group(3) or ""
    return WIKILINK.sub(repl, s)


def clean_authors(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [str(x) for x in value]
    else:
        items = [str(value)]
    out: list[str] = []
    for raw in items:
        s = strip_wikilink(str(raw)).strip().strip("'\"").strip()
        if s:
            out.append(s)
    return out


def clean_title(raw, authors_clean: list[str]) -> str:
    if raw is None:
        return ""
    t = str(raw).strip()
    t = strip_wikilink(t)
    t = re.sub(r"\*+([^*]+)\*+", r"\1", t)
    if authors_clean:
        a = authors_clean[0]
        if a and t.lower().startswith(a.lower() + ","):
            t = t[len(a) + 1 :].lstrip()
    t = re.sub(r"\s*(?:\(\d{4}\)\s*)?[—\-]\s*书籍?概览\s*$", "", t)
    return t.strip()


def render_authors_inline(authors: list[str]) -> str:
    parts = []
    for a in authors:
        if any(c in a for c in [",", ":", "#", "[", "]", "'", '"']):
            parts.append(yaml.safe_dump(a, default_style="'", allow_unicode=True).strip())
        else:
            parts.append(a)
    return "[" + ", ".join(parts) + "]"


def render_title_inline(title: str) -> str:
    if any(c in title for c in [":", "#"]) or title != title.strip():
        return yaml.safe_dump(title, default_style="'", allow_unicode=True).strip()
    return title


def replace_field_line(fm_block: str, key: str, new_value_inline: str) -> tuple[str, bool]:
    """Replace the line `key: ...` in fm_block. YAML flow-list values that wrap
    onto a second line are not used in this vault, so single-line replacement is safe."""
    pat = re.compile(rf"^({re.escape(key)}):[ \t]*.*$", re.MULTILINE)
    new_line = f"{key}: {new_value_inline}"
    new_block, n = pat.subn(new_line, fm_block, count=1)
    return new_block, n > 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--show", type=int, default=15)
    args = ap.parse_args()

    files = sorted(pathlib.Path("vault/books").glob("*/00-overview.md"))
    if args.limit:
        files = files[: args.limit]

    changed = 0
    skipped = 0
    shown = 0

    for fp in files:
        text = fp.read_text(encoding="utf-8")
        m = FM_RE.match(text)
        if not m:
            skipped += 1
            continue
        fm_open, fm_block, fm_close = m.group(1), m.group(2), m.group(3)
        rest = text[m.end():]

        try:
            data = yaml.safe_load(fm_block) or {}
            if not isinstance(data, dict):
                skipped += 1
                continue
        except yaml.YAMLError:
            skipped += 1
            continue

        old_authors_raw = data.get("authors")
        old_title_raw = data.get("title")

        new_authors = clean_authors(old_authors_raw)
        new_title = clean_title(old_title_raw, new_authors)

        # detect actual changes
        old_authors_list = (
            old_authors_raw if isinstance(old_authors_raw, list)
            else [old_authors_raw] if old_authors_raw else []
        )
        authors_changed = new_authors and new_authors != old_authors_list
        title_changed = new_title and new_title != (str(old_title_raw).strip() if old_title_raw else "")

        if not (authors_changed or title_changed):
            continue

        new_block = fm_block
        if authors_changed:
            new_block, ok = replace_field_line(new_block, "authors", render_authors_inline(new_authors))
            if not ok:
                # field absent — append before end
                new_block = new_block.rstrip("\n") + f"\nauthors: {render_authors_inline(new_authors)}"
        if title_changed:
            new_block, ok = replace_field_line(new_block, "title", render_title_inline(new_title))
            if not ok:
                new_block = new_block.rstrip("\n") + f"\ntitle: {render_title_inline(new_title)}"

        if new_block == fm_block:
            continue

        changed += 1
        if shown < args.show:
            print(f"--- {fp.parent.name}")
            if title_changed:
                print(f"   title  : {old_title_raw!r}")
                print(f"        -> {new_title!r}")
            if authors_changed:
                print(f"   authors: {old_authors_raw!r}")
                print(f"        -> {new_authors!r}")
            shown += 1

        if args.write:
            fp.write_text(fm_open + new_block + fm_close + rest, encoding="utf-8")

    print(f"\nfiles changed: {changed}    skipped (bad frontmatter): {skipped}")
    print(f"mode: {'WRITE' if args.write else 'DRY-RUN — re-run with --write to apply'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

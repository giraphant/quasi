#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vault resolve —— 判断候选 work 是否已在 vault,slug 漂移也能认出来。

批量处理(author / topic)前必须知道"这本书/这篇论文是不是已经做过了",否则会
重复获取 + 破坏性重 extract。只比对 slug 是不够的:同一本书,搜索这次生成
``fourcade-economists-and-societies-2010``,vault 里却是
``fourcade-economists-societies-2009``(连接词 + 年份漂移)—— 精确路径检查判它
"没做过",于是造出重复条目。

所以做两级匹配:
  1. exact  —— 产物路径直接存在(``match: "slug"``)
  2. 标识符 —— ISBN(书,归一化成 ISBN-13)/ DOI(论文,小写去 doi.org 前缀)命中
               vault frontmatter,返回**vault 里真实的 slug**(``match: "isbn"|"doi"``)

调用方拿 ``vault_slug`` 去读已有产物(不是候选自己的 slug),漂移就不会变成重复。

用法::

    quasi-helpers vault resolve --items-file items.json
    quasi-helpers vault resolve --items-file -   # stdin(书名带撇号时比 --items-json 安全)
    quasi-helpers vault resolve --items-json '[{"kind":"book","slug":"x","isbn":"9780226185903"}]'

每项 ``{kind: "book"|"paper", slug, isbn?, doi?}``;输出
``{"resolved":[{kind, slug, vault_slug, path, match}], "scanned": {...}}``,
未命中的 ``vault_slug``/``path``/``match`` 均为 ``null``。只读,不写任何文件。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT))

from core import print_json, project_root, read_frontmatter  # noqa: E402
from scripts.localise.localise import normalise_isbn  # noqa: E402


def normalise_doi(raw: Any) -> str | None:
    """DOI 比较键:小写、去 doi.org / dx.doi.org / doi: 前缀。无法用时 None。"""
    if raw in (None, "", [], {}):
        return None
    if isinstance(raw, list):
        for item in raw:
            value = normalise_doi(item)
            if value:
                return value
        return None
    text = str(raw).strip().lower()
    text = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    return text or None


def _product_path(root: Path, kind: str, slug: str) -> Path:
    return (root / "vault" / "books" / slug / "00-overview.md" if kind == "book"
            else root / "vault" / "papers" / f"{slug}.md")


def _index(root: Path, kind: str) -> dict[str, str]:
    """vault 扫一遍 → {标识符: slug}。先出现的胜出(同一标识符多条目时保持确定)。"""
    field, norm = ("isbn", normalise_isbn) if kind == "book" else ("doi", normalise_doi)
    if kind == "book":
        pairs = ((p.parent.name, p) for p in sorted((root / "vault" / "books").glob("*/00-overview.md")))
    else:
        pairs = ((p.stem, p) for p in sorted((root / "vault" / "papers").glob("*.md")))

    out: dict[str, str] = {}
    for slug, path in pairs:
        try:
            fm = read_frontmatter(path).frontmatter or {}
        except OSError:
            continue
        key = norm(fm.get(field))
        if key:
            out.setdefault(key, slug)
    return out


def resolve(root: Path, items: list[dict]) -> dict:
    indexes: dict[str, dict[str, str]] = {}
    resolved = []

    for item in items:
        kind = (item.get("kind") or "book").strip()
        slug = (item.get("slug") or "").strip()
        if kind not in ("book", "paper") or not slug:
            resolved.append({"kind": kind, "slug": slug, "vault_slug": None,
                             "path": None, "match": None, "error": "kind must be book|paper and slug non-empty"})
            continue

        # 1. 精确路径
        if _product_path(root, kind, slug).is_file():
            resolved.append({"kind": kind, "slug": slug, "vault_slug": slug,
                             "path": str(_product_path(root, kind, slug).relative_to(root)), "match": "slug"})
            continue

        # 2. 标识符(懒建索引:没有可用标识符的 item 不触发全 vault 扫描)
        field, norm = ("isbn", normalise_isbn) if kind == "book" else ("doi", normalise_doi)
        key = norm(item.get(field))
        hit = None
        if key:
            if kind not in indexes:
                indexes[kind] = _index(root, kind)
            hit = indexes[kind].get(key)

        resolved.append({
            "kind": kind, "slug": slug,
            "vault_slug": hit,
            "path": str(_product_path(root, kind, hit).relative_to(root)) if hit else None,
            "match": field if hit else None,
        })

    return {"resolved": resolved,
            "scanned": {k: len(v) for k, v in indexes.items()}}


def _load_items(args: argparse.Namespace) -> list[dict]:
    if args.items_json:
        raw = args.items_json
    elif args.items_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.items_file).read_text(encoding="utf-8")
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError("items must be a JSON array")
    return items


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="quasi-helpers vault resolve", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--items-json", help='JSON array of {kind, slug, isbn?, doi?}')
    src.add_argument("--items-file", help="path to that JSON array, or - for stdin")
    args = ap.parse_args(argv)

    try:
        items = _load_items(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: cannot read items: {exc}", file=sys.stderr)
        return 2

    print_json(resolve(project_root(), items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

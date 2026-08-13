#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vault resolve —— 判断候选 work 是否已在 vault,slug 漂移也能认出来。

批量处理(author / topic)前必须知道"这本书/这篇论文是不是已经做过了",否则会
重复获取 + 破坏性重 extract。只比对 slug 是不够的:同一本书,搜索这次生成
``fourcade-economists-and-societies-2010``,vault 里却是
``fourcade-economists-societies-2009``(连接词 + 年份漂移)—— 精确路径检查判它
"没做过",于是造出重复条目。

所以做三级匹配:
  1. exact  —— 产物路径直接存在(``match: "slug"``)
  2. 标识符 —— ISBN(书,归一化成 ISBN-13)/ DOI(论文,小写去 doi.org 前缀)命中
               vault frontmatter,返回**vault 里真实的 slug**(``match: "isbn"|"doi"``)
  3. 标题+作者姓 —— vault 条目本身就没有 ISBN/DOI 时唯一的兜底(全库约 9% 的书没
               ``isbn``、7% 的论文没 ``doi``,前两级对它们必然 miss)。要求标题键
               **唯一**命中且候选作者姓与 vault 条目作者有交集(``match: "title"``)。

第三级刻意保守:误判(把没做过的当成做过)会**静默丢掉**一部作品,漏判只是多一条重复
条目 —— 看得见、可合并。所以标题键撞到多条就直接拒绝匹配,不猜。

调用方拿 ``vault_slug`` 去读已有产物(不是候选自己的 slug),漂移就不会变成重复。

用法::

    quasi-helpers vault resolve --items-file items.json
    quasi-helpers vault resolve --items-file -   # stdin(书名带撇号时比 --items-json 安全)
    quasi-helpers vault resolve --items-json '[{"kind":"book","slug":"x","isbn":"9780226185903"}]'

每项 ``{kind: "book"|"paper"|"talk"|"author", slug, isbn?, doi?, title?, authors?}``;输出
``{"resolved":[{kind, slug, vault_slug, path, match}], "scanned": {...}}``,
未命中的 ``vault_slug``/``path``/``match`` 均为 ``null``。只读,不写任何文件。
``talk`` 与 ``author`` 只做 exact slug/path 观察,不参与书/论文的 identifier/title 索引。
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT))

from scripts.core import print_json, project_root, read_frontmatter  # noqa: E402
from scripts.localise.localise import normalise_isbn  # noqa: E402
from scripts.webpage.webarchive import collision_slug, normalize_web_url, read_webarchive  # noqa: E402


WEBPAGE_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")


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


def title_keys(raw: Any) -> list[str]:
    """标题比较键:完整标题 + 去副标题(首个冒号之前)。标点当空白、去冠词、小写。

    两个键都进索引也都用于查找 —— 副标题在候选侧和 vault 侧经常一有一无
    (``Sorting Things Out`` vs ``Sorting Things Out: Classification and Its
    Consequences``)。返回列表里第 0 项是完整键,之后的是去副标题键(标题本来就没
    副标题时只有一项)。
    """
    if raw in (None, "", [], {}):
        return []
    keys = []
    for text in (str(raw), re.split(r"[:：]", str(raw), 1)[0]):
        norm = re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", text.lower())).strip()
        norm = re.sub(r"^(the|a|an)\s+", "", norm)
        if norm and norm not in keys:
            keys.append(norm)
    return keys


def surnames(raw: Any) -> set[str]:
    """作者姓集合。``Bowker, Geoffrey C.`` 与 ``Geoffrey C. Bowker`` 都归到 ``bowker``:
    有逗号取逗号前的末词,没逗号取整串末词(``José van Dijck`` / ``van Dijck, José`` → ``dijck``)。
    """
    items = raw if isinstance(raw, list) else [raw]
    out: set[str] = set()
    for item in items:
        if not item:
            continue
        parts = re.sub(r"[^\w\s]+", " ", str(item).split(",")[0]).split()
        if parts:
            out.add(parts[-1].lower())
    return out


def _product_path(root: Path, kind: str, slug: str) -> Path:
    if kind == "book":
        return root / "vault" / "books" / slug / "00-overview.md"
    if kind == "paper":
        return root / "vault" / "papers" / f"{slug}.md"
    if kind == "talk":
        return root / "vault" / "talks" / slug / "talk.md"
    return root / "vault" / "authors" / f"{slug}.md"


def _product_state(root: Path, path: Path) -> str:
    """Return safe|missing|unsafe without following product-path symlinks."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return "unsafe"

    current = root
    for part in relative.parts[:-1]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "unsafe"
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            return "unsafe"

    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unsafe"
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        return "unsafe"

    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return "unsafe"
    return "safe"


def _directory_state(root: Path, path: Path) -> str:
    """Return safe|missing|unsafe for a directory without following symlinks."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return "unsafe"

    current = root
    for part in relative.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "unsafe"
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            return "unsafe"
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return "unsafe"
    return "safe"


def _webpage_owners(root: Path) -> tuple[dict[str, list[tuple[str, Path]]], dict[str, str]]:
    """Read only safe Webpage directories into normalized URL ownership rows."""
    directory = root / "vault" / "webpages"
    if _directory_state(root, directory) != "safe":
        return {}, {}
    by_url: dict[str, list[tuple[str, Path]]] = {}
    slug_urls: dict[str, str] = {}
    try:
        entries = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError:
        return {}, {}
    for entry in entries:
        slug = entry.name
        if WEBPAGE_SLUG.fullmatch(slug) is None or _directory_state(root, entry) != "safe":
            continue
        canonical = entry / "webpage.md"
        snapshot = entry / "snapshot.webarchive"
        url: str | None = None
        evidence: Path | None = None
        if _product_state(root, canonical) == "safe":
            try:
                raw = (read_frontmatter(canonical).frontmatter or {}).get("url")
                url = normalize_web_url(raw) if isinstance(raw, str) else None
            except (OSError, ValueError):
                url = None
            if url:
                evidence = canonical
        if url is None and _product_state(root, snapshot) == "safe":
            try:
                url = read_webarchive(snapshot).url
            except (OSError, ValueError):
                url = None
            if url:
                evidence = snapshot
        if url is not None and evidence is not None:
            by_url.setdefault(url, []).append((slug, evidence))
            slug_urls[slug] = url
    return by_url, slug_urls


def _webpage_row(
    *,
    slug: str,
    vault_slug: str | None,
    path: Path | None,
    root: Path,
    suggested_slug: str | None,
    error: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "kind": "webpage",
        "slug": slug,
        "vault_slug": vault_slug,
        "path": str(path.relative_to(root)) if path is not None else None,
        "match": "url" if vault_slug is not None else None,
        "suggested_slug": suggested_slug,
    }
    if error is not None:
        row["error"] = error
    return row


def _resolve_webpage(root: Path, item: dict[str, Any], slug: str) -> dict[str, Any]:
    raw_url = item.get("url")
    try:
        url = normalize_web_url(raw_url) if isinstance(raw_url, str) else None
    except ValueError as exc:
        return _webpage_row(
            slug=slug, vault_slug=None, path=None, root=root, suggested_slug=None,
            error=str(exc),
        )
    if url is None:
        return _webpage_row(
            slug=slug, vault_slug=None, path=None, root=root, suggested_slug=None,
            error="webpage url must be a non-empty string",
        )

    by_url, slug_urls = _webpage_owners(root)
    owners = by_url.get(url, [])
    if len(owners) > 1:
        return _webpage_row(
            slug=slug, vault_slug=None, path=None, root=root, suggested_slug=None,
            error="multiple webpage owners have the same URL",
        )
    if owners:
        owner_slug, evidence = owners[0]
        return _webpage_row(
            slug=slug, vault_slug=owner_slug, path=evidence, root=root,
            suggested_slug=owner_slug,
        )

    if slug in slug_urls and slug_urls[slug] != url:
        suggestion = collision_slug(slug, url)
        suggested_path = root / "vault" / "webpages" / suggestion
        if _directory_state(root, suggested_path) != "missing":
            return _webpage_row(
                slug=slug, vault_slug=None, path=None, root=root, suggested_slug=None,
                error="hash-suffixed webpage slug is already occupied",
            )
        return _webpage_row(
            slug=slug, vault_slug=None, path=None, root=root, suggested_slug=suggestion,
        )
    return _webpage_row(
        slug=slug, vault_slug=None, path=None, root=root, suggested_slug=slug,
    )


def _index(root: Path, kind: str) -> tuple[dict[str, str], dict[str, list[tuple[str, set[str], bool]]]]:
    """vault 扫一遍 → ({标识符: slug}, {标题键: [(slug, 作者姓, 是否去副标题键)]})。一趟扫盘建两个索引。

    标识符索引先出现的胜出(同一标识符多条目时保持确定);标题索引保留全部条目,
    由查找端判歧义。
    """
    field, norm = ("isbn", normalise_isbn) if kind == "book" else ("doi", normalise_doi)
    if kind == "book":
        pairs = ((p.parent.name, p) for p in sorted((root / "vault" / "books").glob("*/00-overview.md")))
    else:
        pairs = ((p.stem, p) for p in sorted((root / "vault" / "papers").glob("*.md")))

    idents: dict[str, str] = {}
    titles: dict[str, list[tuple[str, set[str], bool]]] = {}
    for slug, path in pairs:
        if _product_state(root, path) != "safe":
            continue
        try:
            fm = read_frontmatter(path).frontmatter or {}
        except OSError:
            continue
        key = norm(fm.get(field))
        if key:
            idents.setdefault(key, slug)
        who = surnames(fm.get("authors"))
        for i, tkey in enumerate(title_keys(fm.get("title"))):
            titles.setdefault(tkey, []).append((slug, who, i > 0))
    return idents, titles


def _title_hit(titles: dict[str, list[tuple[str, set[str], bool]]], item: dict) -> str | None:
    """标题键唯一命中 + 作者姓有交集才算数。歧义或作者对不上一律 None(宁漏勿误)。

    两边都是"去副标题键"时拒绝:那意味着两个标题都有副标题、且副标题不同(否则完整键
    早就命中了)—— 同一作者的多卷本正是这种形状(``Musik und Mathematik. Band 1:
    Aphrodite`` vs ``… Band 1: Eros``),认成同一部会静默丢掉其中一卷。
    """
    who = surnames(item.get("authors") or item.get("author"))
    if not who:
        return None
    for i, key in enumerate(title_keys(item.get("title"))):
        entries = titles.get(key) or []
        if len(entries) == 1 and entries[0][1] & who and not (i > 0 and entries[0][2]):
            return entries[0][0]
    return None


def resolve(root: Path, items: list[dict]) -> dict:
    indexes: dict[str, tuple[dict[str, str], dict[str, list[tuple[str, set[str], bool]]]]] = {}
    resolved = []

    for item in items:
        kind = (item.get("kind") or "book").strip()
        slug = (item.get("slug") or "").strip()
        if kind not in ("book", "paper", "talk", "author", "webpage") or not slug:
            resolved.append({"kind": kind, "slug": slug, "vault_slug": None,
                             "path": None, "match": None,
                             "error": "kind must be book|paper|talk|author|webpage and slug non-empty"})
            continue

        if kind == "webpage":
            resolved.append(_resolve_webpage(root, item, slug))
            continue

        # 1. 精确路径。Agent 后续会写这些 lexical paths，所以 symlink/non-regular
        # targets and symlinked ancestors must fail closed rather than count as existence.
        product = _product_path(root, kind, slug)
        product_state = _product_state(root, product)
        if product_state == "safe":
            resolved.append({"kind": kind, "slug": slug, "vault_slug": slug,
                             "path": str(product.relative_to(root)), "match": "slug"})
            continue
        if product_state == "unsafe":
            resolved.append({"kind": kind, "slug": slug, "vault_slug": None,
                             "path": None, "match": None,
                             "error": "product path or ancestor is symlink/non-regular"})
            continue

        # Talk and Author are not identifier-addressable works here. Their
        # canonical exact paths are the only safe resolver signal.
        if kind in ("talk", "author"):
            resolved.append({"kind": kind, "slug": slug, "vault_slug": None,
                             "path": None, "match": None})
            continue

        # 2/3. 标识符 → 标题+作者姓(懒建索引:两者都无可用输入的 item 不触发全 vault 扫描)
        field, norm = ("isbn", normalise_isbn) if kind == "book" else ("doi", normalise_doi)
        key = norm(item.get(field))
        titled = bool(title_keys(item.get("title")) and surnames(item.get("authors") or item.get("author")))
        hit, how = None, None
        if key or titled:
            if kind not in indexes:
                indexes[kind] = _index(root, kind)
            idents, titles = indexes[kind]
            hit = idents.get(key) if key else None
            how = field if hit else None
            if not hit and titled:
                hit = _title_hit(titles, item)
                how = "title" if hit else None
            if hit and _product_state(
                root,
                _product_path(root, kind, hit),
            ) != "safe":
                resolved.append({
                    "kind": kind, "slug": slug,
                    "vault_slug": None, "path": None, "match": None,
                    "error": "resolved product path is symlink/non-regular",
                })
                continue

        resolved.append({
            "kind": kind, "slug": slug,
            "vault_slug": hit,
            "path": str(_product_path(root, kind, hit).relative_to(root)) if hit else None,
            "match": how,
        })

    return {"resolved": resolved,
            "scanned": {k: {"identifiers": len(v[0]), "titles": len(v[1])} for k, v in indexes.items()}}


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
    src.add_argument("--items-json", help='JSON array of {kind, slug, isbn?, doi?, title?, authors?}')
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

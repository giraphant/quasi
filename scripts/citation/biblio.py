#!/usr/bin/env python3
"""Scan vault/{papers,books}/** frontmatter into a single biblio.json.

The biblio is the *single source of truth* for citation resolution downstream:

    parse.py     extracts (Author, Year) keys from drafts
    biblio.py    builds biblio.json from vault frontmatter             ← this file
    resolve.py   reads parse.json + biblio.json to produce manifest.json
    emit_bib.py  reads biblio.json + manifest → references.bib

This is exposed through `quasi-helpers citation biblio`; audit remains a
typecheck-only agent-facing command.

Vault layout (observed in bts/):
    vault/papers/{author-slug}-{title-words}-{year}.md
    vault/books/{author-slug}-{title-words}-{year}/00-overview.md

Frontmatter conventions:
    paper:  title / author / year / doi / journal / themes / rating / source
    book:   title / author / year / publisher / isbn / themes / rating / category
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT))

from core import read_frontmatter as core_read_frontmatter  # noqa: E402


PAPERS_GLOB = "vault/papers/*.md"
BOOKS_OVERVIEW_GLOB = "vault/books/*/00-overview.md"

_YEAR_TAIL_RE = re.compile(r"-(\d{4})$")


# ---- frontmatter parsing -----------------------------------------------------

def read_frontmatter(path: Path) -> dict[str, Any]:
    try:
        doc = core_read_frontmatter(path)
    except OSError:
        return {}
    return doc.frontmatter or {}


def _first_author_field(fm: dict) -> str:
    """Return first author entry from either `author` (singular) or `authors`
    (plural list) frontmatter field. vault 实际两种都在用."""
    a = fm.get("author")
    if not a:
        a = fm.get("authors")
    if isinstance(a, list):
        a = a[0] if a else ""
    return a if isinstance(a, str) else ""


def author_display(fm: dict) -> str:
    """Best-effort author display from frontmatter (handles wikilinks)."""
    s = _first_author_field(fm).strip()
    if not s:
        return ""
    m = re.match(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", s)
    if m:
        return m.group(2) or m.group(1)
    return s.strip('"')


def author_slug_from_fm(fm: dict) -> str:
    """Pull author slug from wikilink form `[[slug|Display]]` if present."""
    s = _first_author_field(fm).strip()
    m = re.match(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", s)
    return m.group(1) if m else ""


def parse_slug(slug_with_year: str) -> tuple[str, int | None]:
    """`russell-..-1951` → ('russell-..', 1951). No trailing year → (whole, None)."""
    m = _YEAR_TAIL_RE.search(slug_with_year)
    if not m:
        return slug_with_year, None
    year = int(m.group(1))
    body = slug_with_year[: m.start()]
    return body, year


def author_slug_from_filename(slug_with_year: str) -> str:
    """First segment before first '-' inside slug body.

    For multi-word author slugs (e.g. `costanza-chock-`, `garland-thomson-`,
    `fausto-sterling-`), this returns just the first word — but biblio also
    stores the full body for fuzzy matching.
    """
    body, _ = parse_slug(slug_with_year)
    return body.split("-")[0] if body else ""


def author_slug_full_body(slug_with_year: str) -> str:
    """The full body (sans year) = full multi-word author slug + title slug.

    e.g. `fausto-sterling-five-sexes-revisited-2000` →
         `fausto-sterling-five-sexes-revisited`
    """
    body, _ = parse_slug(slug_with_year)
    return body


# ---- per-entry schema check --------------------------------------------------

REQUIRED_PAPER = ["title", "year", "doi"]
REQUIRED_BOOK = ["title", "year", "publisher", "isbn"]
# Author is required but lives in either `author` or `authors` — checked
# separately via `_first_author_field`.


@dataclass
class Issue:
    code: str
    detail: str


def check_entry(kind: str, slug_with_year: str, fm: dict) -> list[Issue]:
    """Lint a vault entry's frontmatter against schema + slug consistency."""
    issues: list[Issue] = []

    required = REQUIRED_PAPER if kind == "paper" else REQUIRED_BOOK
    missing = [f for f in required if not fm.get(f)]
    if not _first_author_field(fm):
        missing.append("author/authors")
    if missing:
        issues.append(Issue(
            code="missing-required",
            detail=f"frontmatter 缺字段: {', '.join(missing)}",
        ))

    _, slug_year = parse_slug(slug_with_year)
    fm_year = fm.get("year")
    if slug_year and fm_year:
        try:
            fm_year_int = int(fm_year)
        except (ValueError, TypeError):
            fm_year_int = None
        if fm_year_int and fm_year_int != slug_year:
            issues.append(Issue(
                code="slug-year-mismatch",
                detail=f"slug 年 {slug_year} 跟 frontmatter year {fm_year_int} 不一致",
            ))

    fm_slug = author_slug_from_fm(fm)
    if fm_slug:
        body_slug = author_slug_full_body(slug_with_year)
        # 仅当 fm 里的 wikilink slug 是单 token 时校验(多 token 作者难校验)
        if "-" not in fm_slug and not body_slug.startswith(fm_slug + "-") \
                and body_slug != fm_slug:
            issues.append(Issue(
                code="author-slug-mismatch",
                detail=f"wikilink author '{fm_slug}' 跟文件名 author 段不一致",
            ))

    title = fm.get("title")
    if isinstance(title, str) and re.search(r"\(\d{4}\)|by\s+", title, re.IGNORECASE):
        issues.append(Issue(
            code="title-has-noise",
            detail="title 字段疑似含年份/作者杂质(应只放标题正文)",
        ))

    return issues


# ---- scan --------------------------------------------------------------------

@dataclass
class Entry:
    slug: str                            # vault slug (incl. year)
    kind: str                            # paper | book
    path: str                            # relative to project_root
    author_slug: str                     # first-word author slug, for indexing
    author_slug_body: str                # full body before year (multi-word author + title slug)
    year: int | None                     # canonical year (slug year or fm.year)
    title: str
    author: str
    doi: str
    journal: str
    publisher: str
    isbn: str
    fm: dict                             # full frontmatter (透传)
    issues: list[dict] = field(default_factory=list)


def _entry_year(slug_year: int | None, fm: dict) -> int | None:
    if slug_year:
        return slug_year
    try:
        return int(fm["year"]) if fm.get("year") else None
    except (ValueError, TypeError):
        return None


def _build_entry(kind: str, slug_with_year: str, path: Path, project_root: Path) -> Entry:
    fm = read_frontmatter(path)
    body, slug_year = parse_slug(slug_with_year)
    issues = check_entry(kind, slug_with_year, fm)

    # Prefer fm.author wikilink slug for indexing (handles multi-word author
    # slugs like `agard-jones`, `costanza-chock`, `fausto-sterling`).
    # Falls back to first hyphen segment if no wikilink in frontmatter.
    fm_slug = author_slug_from_fm(fm)
    if fm_slug:
        author_slug = fm_slug
    else:
        author_slug = body.split("-")[0] if body else ""

    return Entry(
        slug=slug_with_year,
        kind=kind,
        path=str(path.relative_to(project_root)),
        author_slug=author_slug,
        author_slug_body=body,
        year=_entry_year(slug_year, fm),
        title=str(fm.get("title") or ""),
        author=author_display(fm),
        doi=str(fm.get("doi") or ""),
        journal=str(fm.get("journal") or ""),
        publisher=str(fm.get("publisher") or ""),
        isbn=str(fm.get("isbn") or ""),
        fm=fm,
        issues=[{"code": i.code, "detail": i.detail} for i in issues],
    )


def author_slug_indexes(body: str) -> list[str]:
    """All plausible author-slug prefixes of a body, for lookup indexing.

    vault 命名规范是 `{author-slug}-{title-words}-{year}`, 但 author-slug
    可能含连字符 (agard-jones / fausto-sterling / costanza-chock). 边界无法
    机械确定, 所以同时索引 first 1/2/3 hyphen segments. 罕见的 4+ segment
    作者会漏命中 (acceptable trade-off).
    """
    if not body:
        return []
    parts = body.split("-")
    out = [parts[0]]
    if len(parts) >= 2:
        out.append("-".join(parts[:2]))
    if len(parts) >= 3:
        out.append("-".join(parts[:3]))
    return out


def scan_vault(project_root: Path) -> dict:
    """Walk vault, build biblio dict."""
    entries: dict[str, Entry] = {}
    by_author_year: dict[str, list[str]] = defaultdict(list)
    by_author: dict[str, list[str]] = defaultdict(list)
    counts = {"papers": 0, "books": 0, "with_issues": 0}

    def _index_entry(e: Entry) -> None:
        keys = set()
        if e.author_slug:
            keys.add(e.author_slug)
        for k in author_slug_indexes(e.author_slug_body):
            keys.add(k)
        for k in keys:
            by_author[k].append(e.slug)
            if e.year:
                by_author_year[f"{k}|{e.year}"].append(e.slug)

    for p in sorted(project_root.glob(PAPERS_GLOB)):
        slug = p.stem
        e = _build_entry("paper", slug, p, project_root)
        entries[slug] = e
        counts["papers"] += 1
        if e.issues:
            counts["with_issues"] += 1
        _index_entry(e)

    for p in sorted(project_root.glob(BOOKS_OVERVIEW_GLOB)):
        slug = p.parent.name
        e = _build_entry("book", slug, p, project_root)
        entries[slug] = e
        counts["books"] += 1
        if e.issues:
            counts["with_issues"] += 1
        _index_entry(e)

    return {
        "version": "0.1.0",
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "vault_root": str(project_root),
        "entries": {slug: _entry_dict(e) for slug, e in entries.items()},
        "by_author_year": dict(by_author_year),
        "by_author": dict(by_author),
        "summary": {
            "total": len(entries),
            **counts,
        },
    }


def _entry_dict(e: Entry) -> dict:
    d = e.__dict__.copy()
    return d


# ---- entrypoint --------------------------------------------------------------

def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Scan vault/{papers,books}/** frontmatter into biblio.json.")
    ap.add_argument("--project-root", help="Vault root (default $CLAUDE_PROJECT_DIR / cwd)")
    ap.add_argument("-o", "--output", required=True, help="biblio.json output path")
    ap.add_argument("--report-issues", action="store_true",
                    help="Print entries with issues to stderr")
    args = ap.parse_args(argv)

    root = args.project_root or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    root_path = Path(root).resolve()

    biblio = scan_vault(root_path)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(biblio, ensure_ascii=False, indent=2), encoding="utf-8")

    s = biblio["summary"]
    print(f"scanned {root_path}:")
    print(f"  total           {s['total']}")
    print(f"  papers          {s['papers']}")
    print(f"  books           {s['books']}")
    print(f"  with-issues     {s['with_issues']}")
    print(f"\nwrote {out}")

    if args.report_issues and s["with_issues"]:
        print("\nentries with issues:", file=sys.stderr)
        for slug, e in biblio["entries"].items():
            if e["issues"]:
                print(f"  {slug}", file=sys.stderr)
                for issue in e["issues"]:
                    print(f"    [{issue['code']}] {issue['detail']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

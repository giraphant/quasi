#!/usr/bin/env python3
"""Citation extraction from quasi draft markdown.

Two passes:

1. **Structured pass** — known citation grammars yield (authors, year, kind, mentions).
2. **Loose pass** — a deliberately over-permissive regex finds *any* paren-pair
   containing a 4-digit year with an author-shaped token. We compare counts:
   `loose_count - structured_count` shows what the strict parser missed.

The loose pass is a *sanity check*, not a fallback. Draft gets accepted only if
the gap is empty (or the user accepts the listed gaps).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from slug import AuthorToken, parse_author_token


# ---- regexes -----------------------------------------------------------------

# Citation block: paren (中/英,可混搭) containing one or more `Authors, Year` units
# separated by ';' / '；'. Permits optional prefix keywords (参见 / 例如 / 另见 / cf.).
_OPEN  = r"[（(]"
_CLOSE = r"[）)]"
_PREFIX_RE = r"(?:参见|例如|另见|cf\.?|see)\s*"

# Single (author, year) unit:
#   authors:  any run of letters/CJK/space/'.&/-'/'’' up to a (,/，/space) then 4-digit year
#   year:     YYYY, optionally followed by a/b/c suffix (Ahmed, 2010a)
_UNIT = re.compile(
    r"""
    (?P<authors>
        [^（()）,，；;]+?          # author chunk: lazy, no parens/commas/semicolons
    )
    \s*[,，]?\s*                    # optional comma between authors and year
    (?P<year>\d{4})(?P<suffix>[a-z]?)\b
    """,
    re.VERBOSE,
)

_CITATION_BLOCK = re.compile(
    rf"""
    {_OPEN}
    \s*(?:{_PREFIX_RE})?
    (?P<body>
        [^（()）]{{1,400}}?         # content inside parens (no nesting)
    )
    {_CLOSE}
    """,
    re.VERBOSE,
)

# Loose scan: a paren (中/英,可混搭,允许方向反向) containing a 4-digit year.
# 故意宽松,用于校验结构化解析的覆盖率。
_LOOSE = re.compile(
    rf"""
    [（(]                            # 任意左括号
    (?P<inside>
        [^（()）]{{0,300}}?
        \d{{4}}
        [^（()）]{{0,40}}?
    )
    [）)]                            # 任意右括号
    """,
    re.VERBOSE,
)

# Heuristic: must look like a citation (contain a letter sequence ≥3 OR a CJK char)
_AUTHOR_SHAPE = re.compile(r"[A-Za-z]{3,}|[㐀-鿿]{2,}")


# ---- data types --------------------------------------------------------------

@dataclass
class Mention:
    """A single occurrence of a citation in source text."""
    file: str
    line: int
    snippet: str           # the paren expression itself
    context: str           # the sentence/paragraph the citation lived in


@dataclass
class Citation:
    """One (authors, year) tuple, deduped across the draft."""
    key: str                              # stable id, e.g. "ahmed-2010"
    authors_raw: str                      # the author chunk as written
    author: AuthorToken                   # parsed first-author view
    year: int
    year_suffix: str = ""                 # 'a' / 'b' if present, else ''
    kind: str = "parenthetical"           # parenthetical | narrative
    mentions: list[Mention] = field(default_factory=list)


# ---- structured pass ---------------------------------------------------------

def _shape_ok(text: str) -> bool:
    return bool(_AUTHOR_SHAPE.search(text))


def _split_units(body: str) -> list[tuple[str, int, str]]:
    """Inside one paren block, split on ';' / '；' and parse each as a unit."""
    out = []
    for chunk in re.split(r"[;；]", body):
        chunk = chunk.strip()
        if not chunk or not _shape_ok(chunk):
            continue
        m = _UNIT.search(chunk)
        if not m:
            continue
        authors = m.group("authors").strip(" ,，")
        year = int(m.group("year"))
        suffix = m.group("suffix") or ""
        if not _shape_ok(authors):
            continue
        out.append((authors, year, suffix))
    return out


def _line_for(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _context_for(text: str, pos: int, end: int, max_chars: int = 240) -> str:
    """Return the surrounding sentence/paragraph for a span."""
    para_start = text.rfind("\n", 0, pos)
    para_end   = text.find("\n", end)
    if para_start < 0: para_start = 0
    if para_end < 0:   para_end = len(text)
    chunk = text[para_start:para_end].strip()
    if len(chunk) <= max_chars:
        return chunk
    # Trim around the citation
    local = max(0, pos - para_start - max_chars // 2)
    return chunk[local:local + max_chars].strip()


def _key_for(token: AuthorToken, year: int, suffix: str) -> str:
    base = token.slug or "unknown"
    return f"{base}-{year}{suffix}"


def parse_text(text: str, file_label: str) -> tuple[dict[str, Citation], list[dict]]:
    """Run structured pass over one draft's text.

    Returns (citations_by_key, structured_spans).
    structured_spans = [{"start", "end", "raw"}, ...] — used to compute the
    gap against the loose pass.
    """
    citations: dict[str, Citation] = {}
    spans: list[dict] = []

    for block in _CITATION_BLOCK.finditer(text):
        body = block.group("body")
        units = _split_units(body)
        if not units:
            continue
        snippet = block.group(0)
        line = _line_for(text, block.start())
        context = _context_for(text, block.start(), block.end())
        spans.append({"start": block.start(), "end": block.end(), "raw": snippet})

        for authors_raw, year, suffix in units:
            token = parse_author_token(authors_raw)
            key = _key_for(token, year, suffix)
            cit = citations.get(key)
            if cit is None:
                cit = Citation(
                    key=key, authors_raw=authors_raw, author=token,
                    year=year, year_suffix=suffix, kind="parenthetical",
                )
                citations[key] = cit
            cit.mentions.append(Mention(
                file=file_label, line=line, snippet=snippet, context=context,
            ))

    return citations, spans


# ---- loose pass --------------------------------------------------------------

def loose_scan(text: str) -> list[dict]:
    """Find anything that looks like a paren-with-year. For validation only."""
    hits = []
    for m in _LOOSE.finditer(text):
        inside = m.group("inside")
        if not _shape_ok(inside):
            continue
        hits.append({
            "start": m.start(), "end": m.end(),
            "raw": m.group(0),
            "line": _line_for(text, m.start()),
        })
    return hits


def validate_coverage(
    structured_spans: list[dict],
    loose_hits: list[dict],
) -> list[dict]:
    """Find loose hits not covered by any structured span. Each = a parser miss."""
    misses = []
    for hit in loose_hits:
        covered = any(
            s["start"] <= hit["start"] and hit["end"] <= s["end"]
            for s in structured_spans
        )
        if not covered:
            misses.append(hit)
    return misses


# ---- entrypoint --------------------------------------------------------------

def parse_files(paths: list[Path], project_root: Path) -> dict:
    """Parse one or more draft files; merge into a single citation set."""
    all_citations: dict[str, Citation] = {}
    all_spans: list[tuple[str, list[dict]]] = []
    all_loose: list[tuple[str, list[dict]]] = []

    for p in paths:
        text = p.read_text(encoding="utf-8")
        label = str(p.relative_to(project_root)) if p.is_absolute() else str(p)
        cits, spans = parse_text(text, label)
        loose = loose_scan(text)

        all_spans.append((label, spans))
        all_loose.append((label, loose))

        for key, cit in cits.items():
            existing = all_citations.get(key)
            if existing is None:
                all_citations[key] = cit
            else:
                existing.mentions.extend(cit.mentions)

    # Per-file validation report
    validation = []
    structured_total = 0
    loose_total = 0
    miss_total = 0
    for (label, spans), (_, loose) in zip(all_spans, all_loose):
        misses = validate_coverage(spans, loose)
        validation.append({
            "file": label,
            "structured_count": len(spans),
            "loose_count": len(loose),
            "misses": misses,
        })
        structured_total += len(spans)
        loose_total += len(loose)
        miss_total += len(misses)

    return {
        "summary": {
            "files": len(paths),
            "unique_citations": len(all_citations),
            "structured_spans": structured_total,
            "loose_spans": loose_total,
            "uncovered_spans": miss_total,
        },
        "citations": [_serialize(c) for c in all_citations.values()],
        "validation": validation,
    }


def _serialize(c: Citation) -> dict:
    d = asdict(c)
    # AuthorToken is already a dataclass; asdict recurses, good.
    return d


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Parse citations from a draft.")
    ap.add_argument("paths", nargs="+", help="Draft .md files or directories")
    ap.add_argument("--project-root", required=True,
                    help="Vault root (for relative file labels)")
    ap.add_argument("-o", "--output", required=True, help="parse.json path")
    args = ap.parse_args(argv)

    root = Path(args.project_root).resolve()
    paths: list[Path] = []
    for p in args.paths:
        path = Path(p).resolve()
        if path.is_dir():
            paths.extend(sorted(path.rglob("*.md")))
        elif path.is_file():
            paths.append(path)
        else:
            print(f"warn: skip non-existent {p}", file=sys.stderr)
    if not paths:
        print("error: no draft files found", file=sys.stderr)
        return 2

    result = parse_files(paths, root)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    s = result["summary"]
    print(f"parsed {s['files']} file(s):")
    print(f"  unique citations:  {s['unique_citations']}")
    print(f"  structured spans:  {s['structured_spans']}")
    print(f"  loose spans:       {s['loose_spans']}")
    print(f"  uncovered spans:   {s['uncovered_spans']}")
    if s["uncovered_spans"]:
        print("\nuncovered (loose-only) spans — first 10:")
        for v in result["validation"]:
            for m in v["misses"][:10]:
                print(f"  {v['file']}:{m['line']}  {m['raw']}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

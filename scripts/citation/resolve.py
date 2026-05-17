#!/usr/bin/env python3
"""Resolve draft citations against the biblio (NOT the live vault).

Input:
    parse.json    output of parse.py (draft citations with mentions)
    biblio.json   output of biblio.py (vault frontmatter view)

Output:
    manifest.json with per-citation status:
        single-hit    exactly one biblio entry matched
        multi-hit     ≥2 biblio entries matched
        miss          no match in any tier

Each entry records which `tier` produced the match:
    1  strict (author_slug + year exact)
    2  author-only fallback (same author_slug, any year — catches slug year typos)
    3  fuzzy author (Levenshtein ≤ 2) + year ±3 (catches surname typos / reprints)
    4  no match → miss

Tier ladder runs only as far as needed: tier 1 hit short-circuits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


# ---- Levenshtein (tier-3 fuzzy author) ---------------------------------------

def _levenshtein(a: str, b: str, cap: int = 3) -> int:
    """Iterative Levenshtein distance with early exit at `cap`.

    Returns `cap + 1` once the running minimum exceeds `cap`, so callers can
    use `<= 2` as a hard threshold without paying for distant strings.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            v = min(ins, dele, sub)
            cur.append(v)
            if v < row_min:
                row_min = v
        if row_min > cap:
            return cap + 1
        prev = cur
    return prev[-1]


# ---- tier lookup -------------------------------------------------------------

def _lookup_tier1(biblio: dict, author_slug: str, year: int) -> list[str]:
    return list(biblio["by_author_year"].get(f"{author_slug}|{year}", []))


def _lookup_tier2(biblio: dict, author_slug: str) -> list[str]:
    return list(biblio["by_author"].get(author_slug, []))


def _lookup_tier3(biblio: dict, author_slug: str, year: int,
                  year_window: int = 3, edit_cap: int = 2) -> list[tuple[str, int, int]]:
    """Return (vault_slug, edit_distance, year_offset) for fuzzy hits.

    Edit distance ≤ `edit_cap` AND |target_year - cand_year| ≤ `year_window`.
    """
    out: list[tuple[str, int, int]] = []
    for cand_slug_first, cand_slugs in biblio["by_author"].items():
        if cand_slug_first == author_slug:
            continue  # tier 2 territory
        d = _levenshtein(author_slug, cand_slug_first, cap=edit_cap)
        if d > edit_cap:
            continue
        for slug in cand_slugs:
            ce = biblio["entries"].get(slug)
            if not ce or not ce.get("year"):
                continue
            yo = abs(int(ce["year"]) - year)
            if yo <= year_window:
                out.append((slug, d, yo))
    return out


# ---- classification ----------------------------------------------------------

def _candidate_dict(slug: str, biblio: dict, tier: int,
                    edit_distance: int = 0, year_offset: int = 0) -> dict:
    e = biblio["entries"].get(slug, {})
    return {
        "slug": slug,
        "kind": e.get("kind", ""),
        "path": e.get("path", ""),
        "title": e.get("title", ""),
        "author": e.get("author", ""),
        "year": e.get("year"),
        "doi": e.get("doi", ""),
        "tier": tier,
        "edit_distance": edit_distance,
        "year_offset": year_offset,
        "issues": e.get("issues", []),
    }


def _classify(candidates: list[dict]) -> str:
    if not candidates:
        return "miss"
    if len(candidates) == 1:
        return "single-hit"
    return "multi-hit"


def resolve_one(citation: dict, biblio: dict) -> dict:
    """One citation through the tier ladder.

    citation: parse.py output entry (key/authors_raw/author/year/...).
    """
    author = citation["author"]
    author_slug = author["slug"]
    year = citation["year"]
    is_cjk = author.get("is_cjk", False)

    # Tier 1 — strict
    t1_slugs = _lookup_tier1(biblio, author_slug, year)
    if not t1_slugs and author_slug.endswith("-"):
        # et_al artefact: try without trailing '-'
        t1_slugs = _lookup_tier1(biblio, author_slug.rstrip("-"), year)
    if t1_slugs:
        candidates = [_candidate_dict(s, biblio, tier=1) for s in t1_slugs]
        return {
            "status": _classify(candidates),
            "tier": 1,
            "candidates": candidates,
        }

    # Tier 2 — author-only (any year)
    t2_slugs = _lookup_tier2(biblio, author_slug)
    if not t2_slugs and author_slug.endswith("-"):
        t2_slugs = _lookup_tier2(biblio, author_slug.rstrip("-"))
    if t2_slugs:
        candidates = []
        for s in t2_slugs:
            ce = biblio["entries"].get(s, {})
            cand_year = ce.get("year") or 0
            yo = abs(int(cand_year) - year) if cand_year else 999
            candidates.append(_candidate_dict(s, biblio, tier=2, year_offset=yo))
        return {
            "status": _classify(candidates),
            "tier": 2,
            "candidates": candidates,
        }

    # Tier 3 — fuzzy author + year window (English authors only; CJK skipped)
    if not is_cjk:
        t3 = _lookup_tier3(biblio, author_slug, year)
        if t3:
            candidates = [
                _candidate_dict(s, biblio, tier=3, edit_distance=d, year_offset=yo)
                for s, d, yo in t3
            ]
            return {
                "status": _classify(candidates),
                "tier": 3,
                "candidates": candidates,
            }

    # Tier 4 — true miss
    return {
        "status": "miss",
        "tier": 4,
        "candidates": [],
    }


def resolve_citations(parse_data: dict, biblio: dict) -> dict:
    entries = []
    counts: dict[str, int] = {}
    tier_counts: dict[int, int] = {}

    for cit in parse_data["citations"]:
        res = resolve_one(cit, biblio)
        counts[res["status"]] = counts.get(res["status"], 0) + 1
        tier_counts[res["tier"]] = tier_counts.get(res["tier"], 0) + 1

        entries.append({
            "key": cit["key"],
            "authors_raw": cit["authors_raw"],
            "first_surname": cit["author"]["first_surname"],
            "slug": cit["author"]["slug"],
            "year": cit["year"],
            "year_suffix": cit["year_suffix"],
            "is_cjk": cit["author"]["is_cjk"],
            "et_al": cit["author"]["et_al"],
            "extra_surnames": cit["author"]["extra_surnames"],
            "mentions": cit["mentions"],
            "status": res["status"],
            "tier": res["tier"],
            "candidates": res["candidates"],
        })

    return {
        "summary": {
            "total": len(entries),
            **counts,
            "tier_breakdown": tier_counts,
        },
        "entries": entries,
        "parse_summary": parse_data.get("summary", {}),
        "parse_validation": parse_data.get("validation", []),
        "biblio_version": biblio.get("version"),
        "biblio_generated_at": biblio.get("generated_at"),
    }


# ---- entrypoint --------------------------------------------------------------

def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Resolve draft citations against biblio.json.")
    ap.add_argument("parse_json", help="Output of parse.py")
    ap.add_argument("--biblio", required=True,
                    help="Output of biblio.py (vault frontmatter view)")
    ap.add_argument("-o", "--output", required=True, help="manifest.json output")
    args = ap.parse_args(argv)

    parse_data = json.loads(Path(args.parse_json).read_text(encoding="utf-8"))
    biblio = json.loads(Path(args.biblio).read_text(encoding="utf-8"))

    result = resolve_citations(parse_data, biblio)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    s = result["summary"]
    print(f"resolved {s['total']} citation(s) against biblio ({biblio['summary']['total']} entries):")
    for k in ["single-hit", "multi-hit", "miss"]:
        if k in s:
            print(f"  {k:14s}  {s[k]}")
    print(f"  tier breakdown: {s['tier_breakdown']}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

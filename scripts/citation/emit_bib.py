#!/usr/bin/env python3
"""Emit references.bib from biblio.json + the citation keys a draft actually uses.

Inputs:
    biblio.json          all vault entries (output of biblio.py)
    manifest.json        which citation keys this draft uses (output of resolve.py)
    decisions.json       (optional) user-picked bib_source per key
                         (output of review.html "导出 JSON")

If decisions.json is given, each entry's `bib_source` tells which vault slug
to pull for that citation key. Otherwise we fall back to the first candidate
in the manifest entry, or skip with a TODO comment if there are none.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


# ---- BibTeX field helpers ----------------------------------------------------

def _esc(s) -> str:
    s = str(s) if s is not None else ""
    return s.replace("{", "\\{").replace("}", "\\}").replace("&", "\\&")


def _author_clean(author: str) -> str:
    """Strip wikilink form `[[slug|Display]]` to just Display."""
    s = str(author or "")
    if s.startswith("[[") and s.endswith("]]"):
        body = s[2:-2]
        if "|" in body:
            return body.split("|", 1)[1]
        return body
    return s


def _bibtype(kind: str) -> str:
    return {"paper": "article", "book": "book"}.get(kind, "misc")


def render_entry(key: str, vault_entry: dict) -> str:
    """One biblio entry → one BibTeX record."""
    kind = vault_entry.get("kind", "")
    bibtype = _bibtype(kind)
    author = _author_clean(vault_entry.get("author") or "")
    title = vault_entry.get("title") or ""
    year = vault_entry.get("year") or ""

    fields = [
        f"  author = {{{_esc(author)}}}",
        f"  title  = {{{_esc(title)}}}",
        f"  year   = {{{year}}}",
    ]
    if vault_entry.get("doi"):
        fields.append(f"  doi    = {{{_esc(vault_entry['doi'])}}}")
    if vault_entry.get("journal"):
        fields.append(f"  journal= {{{_esc(vault_entry['journal'])}}}")
    if vault_entry.get("publisher"):
        fields.append(f"  publisher= {{{_esc(vault_entry['publisher'])}}}")
    if vault_entry.get("isbn"):
        fields.append(f"  isbn   = {{{_esc(vault_entry['isbn'])}}}")

    return f"@{bibtype}{{{key},\n" + ",\n".join(fields) + "\n}\n"


def render_skeleton(key: str, authors_raw: str, year, note: str) -> str:
    """A TODO placeholder when no vault entry resolves cleanly."""
    return (f"% TODO: {authors_raw}, {year} — {note}\n"
            f"@misc{{{key},\n"
            f"  author = {{{_esc(authors_raw)}}},\n"
            f"  year   = {{{year}}},\n"
            f"  note   = {{TODO: {_esc(note)}}}\n}}\n")


# ---- main --------------------------------------------------------------------

def _pick_vault_slug(entry: dict, decisions: dict | None) -> tuple[str, str]:
    """Returns (vault_slug or "", reason).

    Priority:
      1. decisions[key].bib_source = "vault:<slug>" → that slug
      2. decisions[key].bib_source = "new:<slug>"  → ("", "new-entry-pending")
      3. manifest entry single-hit → first candidate
      4. manifest entry multi-hit → first candidate (warn)
      5. miss → ("", "missing-from-vault")
    """
    key = entry["key"]
    if decisions:
        d = decisions.get(key, {})
        src = d.get("bib_source") or ""
        if src.startswith("vault:"):
            return src[len("vault:"):], "user-picked"
        if src.startswith("new:"):
            return "", "new-entry-pending"
    status = entry.get("status", "")
    cands = entry.get("candidates") or []
    if status == "single-hit" and cands:
        return cands[0]["slug"], "single-hit"
    if status == "multi-hit" and cands:
        return cands[0]["slug"], "multi-hit-first"
    if status == "miss":
        return "", "missing-from-vault"
    return "", "no-candidate"


def emit_bib(manifest: dict, biblio: dict,
             decisions: dict | None) -> tuple[str, dict]:
    """Render BibTeX text + summary dict (counts per outcome)."""
    out = []
    counts = {"emitted": 0, "skeleton": 0, "new_pending": 0}

    biblio_entries = biblio.get("entries", {})

    for entry in manifest["entries"]:
        key = entry["key"]
        vault_slug, reason = _pick_vault_slug(entry, decisions)
        if vault_slug and vault_slug in biblio_entries:
            out.append(render_entry(key, biblio_entries[vault_slug]))
            counts["emitted"] += 1
        elif reason == "new-entry-pending":
            out.append(render_skeleton(
                key, entry.get("authors_raw", ""), entry.get("year", ""),
                "new-entry-pending (run /quasi:process-book to add)"))
            counts["new_pending"] += 1
        else:
            out.append(render_skeleton(
                key, entry.get("authors_raw", ""), entry.get("year", ""), reason))
            counts["skeleton"] += 1

    return "\n".join(out), counts


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Emit references.bib from biblio + manifest (+ decisions).")
    ap.add_argument("manifest", help="Output of resolve.py")
    ap.add_argument("--biblio", required=True, help="Output of biblio.py")
    ap.add_argument("--decisions", help="Optional decisions.json (user picks)")
    ap.add_argument("-o", "--output", required=True, help=".bib output path")
    args = ap.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    biblio = json.loads(Path(args.biblio).read_text(encoding="utf-8"))
    decisions = None
    if args.decisions:
        decisions = json.loads(Path(args.decisions).read_text(encoding="utf-8"))

    text, counts = emit_bib(manifest, biblio, decisions)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    print(f"emitted {counts['emitted']} entries"
          + (f" / {counts['skeleton']} skeleton" if counts["skeleton"] else "")
          + (f" / {counts['new_pending']} new-pending" if counts["new_pending"] else ""))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

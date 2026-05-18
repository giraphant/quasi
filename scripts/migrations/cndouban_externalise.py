#!/usr/bin/env python3
"""One-shot migration: move `cndouban` from book frontmatter → external translations.json.

Reads:
  $CLAUDE_PROJECT_DIR/vault/books/**/00-overview.md  (cndouban field in frontmatter)
  $CLAUDE_PROJECT_DIR/.quasi/audit/translations.json (may be absent / v1 flat / v2)

Writes:
  $CLAUDE_PROJECT_DIR/.quasi/audit/translations.json (v2: by_book + by_douban_id)
  vault/books/{slug}/00-overview.md (strips the `cndouban:` line from frontmatter)

Semantics carry over:
  cndouban: []        → by_book[slug] = {verdict: "none",  douban_ids: []}
  cndouban: [id,...]  → by_book[slug] = {verdict: "found", douban_ids: [...]}
  cndouban: null      → ignored (treat as "not yet queried" — no by_book entry)
  field absent        → ignored

Idempotent: re-running on an already-migrated vault touches nothing
(no cndouban fields to strip; by_book entries unchanged).

Usage:
  python scripts/migrations/cndouban_externalise.py [--dry-run] [--path PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(
    os.environ.get("QUA_PROJECT_ROOT")
    or os.environ.get("CLAUDE_PROJECT_DIR")
    or os.getcwd()
).resolve()

FM_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$")
CNDOUBAN_LINE_RE = re.compile(
    r"^cndouban:[ \t]*(?:\[[^\]]*\]|null|~|)[ \t]*(?:\r?\n|\Z)",
    re.MULTILINE,
)


def _load_existing_translations(path: Path) -> dict:
    if not path.exists():
        return {"version": 2, "by_book": {}, "by_douban_id": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  WARN: failed to parse {path}: {exc}; starting fresh", file=sys.stderr)
        return {"version": 2, "by_book": {}, "by_douban_id": {}}
    if not isinstance(data, dict):
        return {"version": 2, "by_book": {}, "by_douban_id": {}}
    if data.get("version") == 2 and "by_book" in data and "by_douban_id" in data:
        return data
    # v1 flat: every key looks like a douban id mapping to a metadata dict
    by_douban_id = {
        k: v for k, v in data.items()
        if isinstance(v, dict) and k.isdigit()
    }
    return {"version": 2, "by_book": {}, "by_douban_id": by_douban_id}


def _parse_cndouban_field(text: str) -> tuple[bool, list[int] | None]:
    """Return (field_present, value).

    value is the parsed int list, or None for `cndouban: null` / `cndouban:` (empty).
    """
    import yaml  # local import keeps script invocable without venv check
    m = FM_RE.match(text)
    if not m:
        return False, None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return False, None
    if not isinstance(fm, dict) or "cndouban" not in fm:
        return False, None
    raw = fm.get("cndouban")
    if raw is None:
        return True, None
    if isinstance(raw, list):
        ids: list[int] = []
        for x in raw:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                continue
        return True, ids
    return True, None


def _strip_cndouban_line(text: str) -> str:
    m = FM_RE.match(text)
    if not m:
        return text
    fm_text = m.group(1)
    body = m.group(2)
    new_fm = CNDOUBAN_LINE_RE.sub("", fm_text)
    if new_fm == fm_text:
        return text
    new_fm = new_fm.rstrip("\n")
    return f"---\n{new_fm}\n---\n{body}"


def _slug_for_overview(path: Path) -> str | None:
    parts = path.parts
    try:
        i = parts.index("books")
        return parts[i + 1]
    except (ValueError, IndexError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(prog="cndouban-externalise")
    ap.add_argument(
        "--path",
        default="vault/books",
        help="Subtree to scan (default vault/books, resolved relative to $CLAUDE_PROJECT_DIR)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    target = Path(args.path)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    target = target.resolve()

    if not target.exists():
        print(f"error: path does not exist: {target}", file=sys.stderr)
        return 2

    translations_path = PROJECT_ROOT / ".quasi" / "audit" / "translations.json"
    translations = _load_existing_translations(translations_path)

    today = date.today().isoformat()
    overviews = list(target.rglob("00-overview.md"))
    migrated = 0
    stripped = 0
    skipped_no_field = 0
    skipped_null = 0

    for overview in overviews:
        slug = _slug_for_overview(overview)
        if not slug:
            continue
        text = overview.read_text(encoding="utf-8")
        present, ids = _parse_cndouban_field(text)
        if not present:
            skipped_no_field += 1
            continue
        if ids is None:
            # cndouban: null — semantically "not yet queried", drop the field
            # but don't fabricate a by_book entry. local-agent will pick it up
            # on the next pass since by_book[slug] is absent.
            skipped_null += 1
            new_text = _strip_cndouban_line(text)
            if new_text != text and not args.dry_run:
                overview.write_text(new_text, encoding="utf-8")
                stripped += 1
            elif new_text != text:
                stripped += 1
            continue

        verdict = "found" if ids else "none"
        existing = translations["by_book"].get(slug, {})
        translations["by_book"][slug] = {
            "checked_at": existing.get("checked_at", today),
            "verdict": verdict,
            "douban_ids": ids,
        }
        migrated += 1

        new_text = _strip_cndouban_line(text)
        if new_text != text and not args.dry_run:
            overview.write_text(new_text, encoding="utf-8")
            stripped += 1
        elif new_text != text:
            stripped += 1

    if not args.dry_run:
        translations_path.parent.mkdir(parents=True, exist_ok=True)
        translations_path.write_text(
            json.dumps(translations, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}scanned: {len(overviews)} overviews")
    print(f"{prefix}migrated to by_book: {migrated}")
    print(f"{prefix}null fields cleaned (no by_book entry): {skipped_null}")
    print(f"{prefix}frontmatter lines stripped: {stripped}")
    print(f"{prefix}skipped (no cndouban field): {skipped_no_field}")
    if not args.dry_run:
        print(f"wrote {translations_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

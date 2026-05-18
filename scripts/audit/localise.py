"""quasi-audit localise — agent-callable helpers for local-agent.

Two verbs, both operating on `.quasi/audit/translations.json`:

    scan   enumerate book overviews under PATH, return per-book frontmatter
           fields needed for the cndouban search, and whether the book has
           already been localised (by_book[slug] exists).

    write  merge one book's localise result into translations.json:
           - by_book[slug] := {checked_at, verdict, douban_ids}
           - by_douban_id[id] := {...metadata...} (only if results non-empty;
             first_seen preserved on existing keys)
           Handles v1-flat → v2 migration on first write to a v1 cache.

The audit runner does NOT read translations.json — that decoupling stands.
These verbs live under `quasi-audit` purely as the natural home for small
vault-touching helpers; semantically they are local-agent's own tools.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

FM_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$")


def _project_root() -> Path:
    return Path(
        os.environ.get("QUA_PROJECT_ROOT")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    ).resolve()


def _translations_path(project_root: Path) -> Path:
    return project_root / ".quasi" / "audit" / "translations.json"


def _load_translations(path: Path) -> dict:
    """Load translations cache; migrate v1 flat shape on the fly."""
    if not path.exists():
        return {"version": 2, "by_book": {}, "by_douban_id": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 2, "by_book": {}, "by_douban_id": {}}
    if not isinstance(data, dict):
        return {"version": 2, "by_book": {}, "by_douban_id": {}}
    if data.get("version") == 2 and "by_book" in data and "by_douban_id" in data:
        data.setdefault("by_book", {})
        data.setdefault("by_douban_id", {})
        return data
    by_douban_id = {
        k: v for k, v in data.items()
        if isinstance(v, dict) and k.isdigit()
    }
    return {"version": 2, "by_book": {}, "by_douban_id": by_douban_id}


def _slug_for_overview(path: Path) -> str | None:
    parts = path.parts
    try:
        i = parts.index("books")
        return parts[i + 1]
    except (ValueError, IndexError):
        return None


def _parse_frontmatter(text: str) -> dict | None:
    import yaml
    m = FM_RE.match(text)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def _enumerate_overviews(target: Path) -> list[Path]:
    if target.is_file() and target.name == "00-overview.md":
        return [target]
    if target.is_dir():
        return sorted(target.rglob("00-overview.md"))
    return []


def _cmd_scan(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="quasi-audit localise scan",
        description="Enumerate book overviews + report localise state.",
    )
    ap.add_argument("--path", default="vault/books",
                    help="File or directory (default vault/books, "
                         "resolved relative to $CLAUDE_PROJECT_DIR)")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON (default: text)")
    args = ap.parse_args(argv)

    project_root = _project_root()
    target = Path(args.path)
    if not target.is_absolute():
        target = project_root / target
    target = target.resolve()

    if not target.exists():
        print(f"error: path does not exist: {target}", file=sys.stderr)
        return 2

    translations = _load_translations(_translations_path(project_root))
    by_book = translations.get("by_book", {})

    books: list[dict] = []
    for overview in _enumerate_overviews(target):
        slug = _slug_for_overview(overview)
        if not slug:
            continue
        fm = _parse_frontmatter(overview.read_text(encoding="utf-8"))
        if fm is None:
            books.append({
                "slug": slug,
                "path": str(overview.resolve()),
                "has_entry": slug in by_book,
                "title": None,
                "authors": [],
                "year": None,
                "isbn": None,
                "skip_reason": "frontmatter unreadable",
            })
            continue
        authors = fm.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        books.append({
            "slug": slug,
            "path": str(overview.resolve()),
            "has_entry": slug in by_book,
            "title": fm.get("title"),
            "authors": authors if isinstance(authors, list) else [],
            "year": fm.get("year"),
            "isbn": fm.get("isbn"),
        })

    summary = {
        "path": str(target),
        "translations_cache": str(_translations_path(project_root)),
        "total": len(books),
        "already_localised": sum(1 for b in books if b["has_entry"]),
        "pending": sum(1 for b in books if not b["has_entry"]),
        "books": books,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"scan: {summary['total']} books at {target}")
        print(f"  already localised: {summary['already_localised']}")
        print(f"  pending:          {summary['pending']}")
    return 0


def _coerce_douban_ids(results: list[dict]) -> list[int]:
    ids: list[int] = []
    for r in results:
        raw = r.get("douban_id")
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


def _merge_by_douban_id(
    by_douban_id: dict,
    results: list[dict],
    today: str,
) -> int:
    """Merge each result; preserve first_seen; update last_seen + non-null fields."""
    written = 0
    for r in results:
        raw_id = r.get("douban_id")
        if raw_id is None:
            continue
        key = str(raw_id)
        existing = by_douban_id.get(key, {})
        merged = dict(existing)
        for field, value in r.items():
            if value in (None, "", []):
                continue
            merged[field] = value
        merged["douban_id"] = key
        merged["first_seen"] = existing.get("first_seen", today)
        merged["last_seen"] = today
        by_douban_id[key] = merged
        written += 1
    return written


def _cmd_write(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="quasi-audit localise write",
        description="Merge one book's localise result into translations.json.",
    )
    ap.add_argument("--slug", required=True, help="Vault book slug")
    ap.add_argument(
        "--results-json",
        default="[]",
        help='JSON array of result dicts (douban_id required per entry); '
             'pass "[]" to mark verdict=none',
    )
    ap.add_argument(
        "--results-file",
        help="Alternative to --results-json; path to a file containing the JSON array",
    )
    ap.add_argument("--checked-at", default=None,
                    help="Override checked_at (default today, YYYY-MM-DD)")
    args = ap.parse_args(argv)

    if args.results_file:
        raw = Path(args.results_file).read_text(encoding="utf-8")
    else:
        raw = args.results_json
    try:
        results = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: --results-json is not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(results, list):
        print("error: --results-json must be a JSON array", file=sys.stderr)
        return 2

    today = args.checked_at or date.today().isoformat()
    project_root = _project_root()
    cache_path = _translations_path(project_root)
    translations = _load_translations(cache_path)

    by_book = translations.setdefault("by_book", {})
    by_douban_id = translations.setdefault("by_douban_id", {})

    douban_ids = _coerce_douban_ids(results)
    verdict = "found" if douban_ids else "none"
    by_book[args.slug] = {
        "checked_at": today,
        "verdict": verdict,
        "douban_ids": douban_ids,
    }
    metadata_written = _merge_by_douban_id(by_douban_id, results, today) if results else 0

    translations["version"] = 2
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(translations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "slug": args.slug,
        "verdict": verdict,
        "douban_ids": douban_ids,
        "metadata_entries_written": metadata_written,
        "translations_cache": str(cache_path),
    }, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    """Entry point. argv is the list AFTER `quasi-audit localise`."""
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage:\n"
            "  quasi-audit localise scan  [--path FILE_OR_DIR] [--json]\n"
            "  quasi-audit localise write --slug SLUG "
            "(--results-json '[...]' | --results-file PATH) [--checked-at YYYY-MM-DD]"
        )
        return 0
    verb = argv[0]
    rest = argv[1:]
    if verb == "scan":
        return _cmd_scan(rest)
    if verb == "write":
        return _cmd_write(rest)
    print(f"quasi-audit localise: unknown verb: {verb}", file=sys.stderr)
    return 2

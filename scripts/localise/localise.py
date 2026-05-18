#!/usr/bin/env python3
"""quasi-helpers localise — deterministic Chinese-edition cache helpers.

This helper is scale-facing, not agent-facing. Top-level skills call it around
search-agent / quasi-search output:

    scan   enumerate book overviews and report ISBN-keyed localise state
    write  merge one search result's zh candidates into .quasi/localise/cndouban.json

The cache is keyed by the original book's normalized ISBN-13. Slugs and paths
are stored only as snapshots so book renames do not define identity.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT))

from core import print_json, project_root, read_frontmatter, resolve_project_path, write_json  # noqa: E402


def normalise_isbn(raw: Any) -> str | None:
    """Return an ISBN-13 key with no punctuation, or None if unusable."""
    if raw in (None, "", [], {}):
        return None
    if isinstance(raw, list):
        for item in raw:
            value = normalise_isbn(item)
            if value:
                return value
        return None
    cleaned = re.sub(r"[^0-9Xx]", "", str(raw)).upper()
    if len(cleaned) == 13:
        return cleaned
    if len(cleaned) == 10:
        return _isbn10_to_13(cleaned)
    return None


def _isbn10_to_13(isbn10: str) -> str:
    stem = "978" + isbn10[:9]
    total = sum((1 if i % 2 == 0 else 3) * int(ch) for i, ch in enumerate(stem))
    check = (10 - (total % 10)) % 10
    return f"{stem}{check}"


def _cache_path(root: Path) -> Path:
    return root / ".quasi" / "localise" / "cndouban.json"


def _empty_cache() -> dict:
    return {"version": 1, "by_isbn": {}, "by_douban_id": {}}


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return _empty_cache()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_cache()
    if not isinstance(data, dict):
        return _empty_cache()
    data.setdefault("version", 1)
    data.setdefault("by_isbn", {})
    data.setdefault("by_douban_id", {})
    if not isinstance(data["by_isbn"], dict) or not isinstance(data["by_douban_id"], dict):
        return _empty_cache()
    return data


def _slug_for_overview(path: Path) -> str | None:
    parts = path.parts
    try:
        return parts[parts.index("books") + 1]
    except (ValueError, IndexError):
        return path.parent.name if path.name == "00-overview.md" else None


def _enumerate_overviews(target: Path) -> list[Path]:
    if target.is_file() and target.name == "00-overview.md":
        return [target]
    if target.is_dir():
        return sorted(target.rglob("00-overview.md"))
    return []


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _coerce_people(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in re.split(r"\s*/\s*", value) if part.strip()]
    return []


def _book_snapshot(path_arg: str | None, root: Path) -> dict | None:
    if not path_arg:
        return None
    path = resolve_project_path(path_arg, root)
    doc = read_frontmatter(path)
    fm = doc.frontmatter or {}
    return {
        "slug": _slug_for_overview(path),
        "path": _relpath(path, root),
        "title": fm.get("title"),
        "authors": _coerce_people(fm.get("authors")),
        "year": fm.get("year"),
        "isbn": normalise_isbn(fm.get("isbn")),
    }


def _cmd_scan(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="quasi-helpers localise scan",
        description="Enumerate book overviews and report ISBN-keyed cndouban cache state.",
    )
    ap.add_argument("--path", default="vault/books", help="File or directory, project-relative by default")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = ap.parse_args(argv)

    root = project_root()
    target = resolve_project_path(args.path, root)
    if not target.exists():
        print(f"error: path does not exist: {target}", file=sys.stderr)
        return 2

    cache = _load_cache(_cache_path(root))
    by_isbn = cache.get("by_isbn", {})
    books: list[dict] = []
    isbn_to_slugs: dict[str, list[str]] = defaultdict(list)

    for overview in _enumerate_overviews(target):
        slug = _slug_for_overview(overview)
        doc = read_frontmatter(overview)
        if doc.frontmatter is None:
            books.append({
                "slug": slug,
                "path": _relpath(overview, root),
                "isbn": None,
                "has_entry": False,
                "skip_reason": "frontmatter unreadable",
            })
            continue

        fm = doc.frontmatter
        isbn = normalise_isbn(fm.get("isbn"))
        if isbn:
            isbn_to_slugs[isbn].append(slug or _relpath(overview, root))
        entry = by_isbn.get(isbn) if isbn else None
        books.append({
            "slug": slug,
            "path": _relpath(overview, root),
            "title": fm.get("title"),
            "authors": _coerce_people(fm.get("authors")),
            "year": fm.get("year"),
            "isbn": isbn,
            "has_entry": bool(entry),
            "status": entry.get("status") if isinstance(entry, dict) else None,
            "skip_reason": None if isbn else "missing isbn",
        })

    duplicate_isbns = {k: v for k, v in isbn_to_slugs.items() if len(v) > 1}
    summary = {
        "path": str(target),
        "cache": str(_cache_path(root)),
        "total": len(books),
        "with_isbn": sum(1 for item in books if item.get("isbn")),
        "missing_isbn": sum(1 for item in books if not item.get("isbn")),
        "already_localised": sum(1 for item in books if item.get("has_entry")),
        "pending": sum(1 for item in books if item.get("isbn") and not item.get("has_entry")),
        "duplicate_isbn_keys": len(duplicate_isbns),
        "duplicates": duplicate_isbns,
        "books": books,
    }

    if args.json:
        print_json(summary)
    else:
        print(f"localise scan: {summary['total']} books at {target}")
        print(f"  with isbn:          {summary['with_isbn']}")
        print(f"  missing isbn:       {summary['missing_isbn']}")
        print(f"  already localised:  {summary['already_localised']}")
        print(f"  pending:            {summary['pending']}")
        print(f"  duplicate isbn key: {summary['duplicate_isbn_keys']}")
    return 0


def _load_json_file(path_arg: str, root: Path) -> Any:
    path = resolve_project_path(path_arg, root)
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_candidates(payload: Any) -> tuple[str | None, list[dict]]:
    if isinstance(payload, list):
        return None, payload
    if not isinstance(payload, dict):
        return None, []
    localisations = payload.get("localisations") or {}
    zh = localisations.get("zh") if isinstance(localisations, dict) else None
    if isinstance(zh, dict):
        candidates = zh.get("candidates") or []
        return zh.get("status"), candidates if isinstance(candidates, list) else []
    candidates = payload.get("candidates") or payload.get("results") or []
    return payload.get("status"), candidates if isinstance(candidates, list) else []


def _candidate_id(raw: dict) -> str | None:
    douban_id = raw.get("douban_id")
    if not douban_id and isinstance(raw.get("source_ids"), dict):
        douban_id = raw["source_ids"].get("douban_cn")
    if not douban_id and isinstance(raw.get("id"), str):
        match = re.match(r"^douban_cn:(\d+)$", raw["id"])
        if match:
            douban_id = match.group(1)
    if douban_id in (None, ""):
        return None
    return str(douban_id)


def _normalise_candidate(raw: dict) -> dict | None:
    douban_id = _candidate_id(raw)
    if not douban_id:
        return None
    authors = _coerce_people(raw.get("authors") or raw.get("author"))
    translators = _coerce_people(raw.get("translators") or raw.get("translator"))
    ratings = raw.get("ratings") if isinstance(raw.get("ratings"), dict) else {}
    return {
        "douban_id": douban_id,
        "source": "douban_cn",
        "title": raw.get("title"),
        "author": raw.get("author") or " / ".join(authors),
        "authors": authors,
        "translator": raw.get("translator") or " / ".join(translators),
        "translators": translators,
        "publisher": raw.get("publisher"),
        "year": raw.get("year"),
        "isbn": normalise_isbn(raw.get("isbn") or raw.get("isbn_13") or raw.get("isbn_10")),
        "original_title": raw.get("original_title"),
        "ratings_count": raw.get("ratings_count") or ratings.get("count"),
        "douban_url": raw.get("douban_url") or raw.get("preview_link"),
    }


def _merge_book_snapshot(books: list[dict], snapshot: dict | None) -> list[dict]:
    if not snapshot:
        return books
    key = snapshot.get("path") or snapshot.get("slug")
    out = []
    replaced = False
    for item in books:
        item_key = item.get("path") or item.get("slug")
        if item_key == key:
            out.append(snapshot)
            replaced = True
        else:
            out.append(item)
    if not replaced:
        out.append(snapshot)
    return out


def _cmd_write(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="quasi-helpers localise write",
        description="Merge zh localisations from a search result into .quasi/localise/cndouban.json.",
    )
    ap.add_argument("--isbn", help="Original book ISBN; normalized to ISBN-13")
    ap.add_argument("--book-path", help="Book overview path; used for ISBN fallback and book snapshot")
    ap.add_argument("--search-result-file", help="JSON search/search-agent result containing localisations.zh.candidates")
    ap.add_argument("--candidates-file", help="JSON array of already curated cndouban candidates")
    ap.add_argument("--candidates-json", help="JSON array of already curated cndouban candidates")
    ap.add_argument("--checked-at", default=None, help="Override checked_at date (YYYY-MM-DD)")
    args = ap.parse_args(argv)

    root = project_root()
    snapshot = _book_snapshot(args.book_path, root)
    isbn = normalise_isbn(args.isbn) or (snapshot or {}).get("isbn")
    if not isbn:
        print("error: missing usable original ISBN (pass --isbn or --book-path with isbn frontmatter)", file=sys.stderr)
        return 2

    payload_sources = [args.search_result_file, args.candidates_file, args.candidates_json]
    if sum(1 for item in payload_sources if item) != 1:
        print("error: pass exactly one of --search-result-file, --candidates-file, --candidates-json", file=sys.stderr)
        return 2

    if args.search_result_file:
        status, raw_candidates = _extract_candidates(_load_json_file(args.search_result_file, root))
    elif args.candidates_file:
        status, raw_candidates = _extract_candidates(_load_json_file(args.candidates_file, root))
    else:
        status, raw_candidates = _extract_candidates(json.loads(args.candidates_json or "[]"))

    if status == "error":
        print("error: search result localisations.zh.status=error; not writing cache", file=sys.stderr)
        return 1

    candidates: list[dict] = []
    skipped = 0
    seen: set[str] = set()
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        candidate = _normalise_candidate(raw)
        if not candidate:
            skipped += 1
            continue
        if candidate["douban_id"] in seen:
            continue
        seen.add(candidate["douban_id"])
        candidates.append(candidate)

    today = args.checked_at or date.today().isoformat()
    cache_path = _cache_path(root)
    cache = _load_cache(cache_path)
    by_isbn = cache.setdefault("by_isbn", {})
    by_douban_id = cache.setdefault("by_douban_id", {})

    ids = [candidate["douban_id"] for candidate in candidates]
    current = by_isbn.get(isbn, {})
    if not isinstance(current, dict):
        current = {}
    current["checked_at"] = today
    current["status"] = "found" if ids else "none"
    current["language"] = "zh"
    current["books"] = _merge_book_snapshot(current.get("books") or [], snapshot)
    current["cndouban_ids"] = ids
    current.setdefault("selected_id", None)
    by_isbn[isbn] = current

    metadata_written = 0
    for candidate in candidates:
        key = candidate["douban_id"]
        existing = by_douban_id.get(key, {})
        if not isinstance(existing, dict):
            existing = {}
        merged = dict(existing)
        for field_name, value in candidate.items():
            if value in (None, "", [], {}):
                continue
            merged[field_name] = value
        merged["douban_id"] = key
        merged["first_seen"] = existing.get("first_seen", today)
        merged["last_seen"] = today
        by_douban_id[key] = merged
        metadata_written += 1

    cache["version"] = 1
    write_json(cache_path, cache)
    print_json({
        "isbn": isbn,
        "status": current["status"],
        "cndouban_ids": ids,
        "metadata_entries_written": metadata_written,
        "skipped_candidates": skipped,
        "cache": str(cache_path),
    })
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage:\n"
            "  quasi-helpers localise scan  [--path FILE_OR_DIR] [--json]\n"
            "  quasi-helpers localise write [--isbn ISBN] [--book-path OVERVIEW] "
            "(--search-result-file PATH | --candidates-file PATH | --candidates-json JSON)"
        )
        return 0
    verb = argv[0]
    rest = argv[1:]
    if verb == "scan":
        return _cmd_scan(rest)
    if verb == "write":
        return _cmd_write(rest)
    print(f"quasi-helpers localise: unknown verb: {verb}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

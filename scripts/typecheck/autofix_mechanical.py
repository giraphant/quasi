#!/usr/bin/env python3
"""Pure-mechanical autofix for quasi-vault drift.

Only operations with **zero judgment** live here. Everything that requires
context, content understanding, or policy decisions is handed off to the
typecheck-agent LLM.

Operations performed:

Frontmatter:
  - type alias rename     (`paper-analysis` → `paper`, etc., by lookup table)
  - field rename          (`tags`→`themes`, `paper_title`→`title`, etc.)
  - `author` (singular string) → `authors` (1-element list)
  - rating ★→int          (`"★★★"` → `3`, by char count)
  - year str→int          (`"2010"` → `2010`)
  - chapter `source`→`book` (slug derived from file path)
  - drop orphan fields    (hard-coded blacklist)
  - author.title→name     (field rename)
  - themes string→list    (`"STS"` → `["STS"]`)

Body:
  - H2 alias rename       (`核心引用文献` → `核心引用`, by alias table)

NOT performed here (typecheck-agent handles via LLM):
  - multi-author splitting        ("Foo, Bar" → ["Foo", "Bar"] needs judgment)
  - paper.source → journal/book?  (depends on what source actually is)
  - global heading-level bump     (may break legit nested ## / ### structure)
  - deleting `价值评估` / `相关引用`(content deletion is policy not mechanics)
  - `关键概念` paragraph → table  (content rewrite)
  - filling truly missing H2s     (content generation)
  - unknown_h2 disposition        (keep / rename / merge / delete = judgment)

Usage:
  python autofix_mechanical.py --path PATH [--write]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

import yaml  # noqa: E402

from core import project_root  # noqa: E402
from schemas import (  # noqa: E402
    BodySchema,
    TYPE_REGISTRY,
    canonical_type,
    schema_for_type,
)


PROJECT_ROOT = project_root()


def reorder_frontmatter(fm: dict, type_name: str) -> dict:
    """Reorder frontmatter dict by canonical field order from Pydantic schema.

    Pydantic preserves field declaration order in `model_fields`, so this is
    purely cosmetic — it doesn't drop or transform any value. Unknown fields
    are appended at the end in their original encounter order.
    """
    pair = TYPE_REGISTRY.get(type_name)
    if not pair:
        return fm
    schema_cls, _ = pair
    canonical = list(schema_cls.model_fields.keys())
    out: dict = {}
    for key in canonical:
        if key in fm:
            out[key] = fm[key]
    for key in fm:
        if key not in out:
            out[key] = fm[key]
    return out


# Force lists to flow style (`[a, b]`) so single-author / themes arrays
# stay on one line. Dicts (the frontmatter itself) stay in block style.
def _represent_list_flow(dumper, data):
    return dumper.represent_sequence(
        "tag:yaml.org,2002:seq", data, flow_style=True
    )


yaml.SafeDumper.add_representer(list, _represent_list_flow)


VAULT_DEFAULT = PROJECT_ROOT / "vault"

FM_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$")
ANY_H_RE = re.compile(r"^(#{1,6})(\s+)(.+?)\s*$")


# ─── frontmatter fixes ─────────────────────────────────────────


# Fields whose names get renamed.
FIELD_RENAMES = {
    "tags": "themes",
    "paper_title": "title",
    "book_title": "title",
    "chapter_title": "title",
    "book_year": "year",
    "book_author": "authors",
    "chapter-author": "authors",
    "score": "rating",
}

# Orphan fields to drop on sight (one-off LLM noise).
ORPHAN_FIELDS = {
    "has-profile",
    "has-overview",
    "selective_reading",
    "selection_note",
    "scope_note",
    "source_file",
    "source_note",
    "source_type",
    "structure",
    "version",
    "supersedes",
    "overall_rating",
    "avg_relevance",
    "confidence",
    "analyzed",
    "analyzed_chapters",
    "processed_chapters",
    "total_chapters",
    "chapters_total",
    "chapters_available",
    "chapters_in_vault",
    "chapters_in_volume",
    "chapters_selected",
    "chapters_missing",
    "chapters_analyzed",
    "slug",
    "status",
    "slot",
    "relevance",
    "chapter",
    "chapter_label",
    "terminal",
    "reviewed_book",
    "reviewed_author",
    "word_count_est",
    "concepts",
    "round",
    "source_type",
    "topic",
    "topics",
    "editors",
    "edition",
    "note",
    "notes",
    "publisher",  # only for chapter — handled type-specifically below
    "volume",
    "pages",
    "citations",
    "translators",
    "date",  # paper.date: ambiguous, drop conservatively (LLM agent can decide better)
    "paper_title",
    "authors",  # only if `authors` is duplicate of `author` — handled below
    "tags",
}


def stars_to_int(s: str) -> int | None:
    n = s.count("★")
    return n if 1 <= n <= 5 else None


def normalize_year(v):
    if isinstance(v, int):
        return v if 1500 <= v <= 2030 else None
    if isinstance(v, str):
        s = v.strip()
        if re.fullmatch(r"\d{4}", s):
            n = int(s)
            return n if 1500 <= n <= 2030 else None
        return None
    return None


def slug_from_path(path: Path) -> str | None:
    """For chapter files at vault/books/<slug>/chXX-*.md, return <slug>."""
    parts = path.parts
    try:
        i = parts.index("books")
        return parts[i + 1]
    except (ValueError, IndexError):
        return None


def fix_frontmatter(fm: dict, raw_type: str | None, file_path: Path) -> tuple[dict, list[str]]:
    """Return (new_fm, list_of_changes)."""
    changes: list[str] = []
    out = dict(fm)

    # 1. Canonicalize type.
    canon = canonical_type(raw_type)
    if canon and raw_type != canon:
        out["type"] = canon
        changes.append(f"type: {raw_type!r} → {canon!r}")
    elif canon:
        out["type"] = canon

    # 2. Apply field renames.
    for old, new in FIELD_RENAMES.items():
        if old in out and old != new:
            # Don't overwrite if new field already populated meaningfully.
            if new in out and out[new] not in (None, "", [], {}):
                # Drop old, keep new.
                del out[old]
                changes.append(f"drop {old} (conflict with {new})")
            else:
                out[new] = out.pop(old)
                changes.append(f"rename {old} → {new}")

    # 3. authors normalization: must be a non-empty list of strings.
    #    Only book/chapter/paper have `authors`. `author` type schema uses `name`
    #    (the person *is* the entity); their old `author` field is redundant.
    if canon == "author":
        if "author" in out:
            del out["author"]
            changes.append("drop redundant author field (author type uses 'name')")
        if "authors" in out:
            del out["authors"]
            changes.append("drop authors (author type uses 'name')")
    elif "author" in out:
        # book / chapter / paper: promote singular `author` → `authors`.
        if "authors" in out and out["authors"]:
            del out["author"]
            changes.append("drop author (authors already present)")
        else:
            out["authors"] = out.pop("author")
            changes.append("rename author → authors")
    if "authors" in out:
        v = out["authors"]
        if v is None:
            del out["authors"]
            changes.append("drop authors (null)")
        elif isinstance(v, str):
            out["authors"] = [v]
            changes.append("wrap authors in list")
        elif isinstance(v, list):
            cleaned = [s for s in v if isinstance(s, str) and s.strip()]
            if cleaned != v:
                out["authors"] = cleaned
                changes.append("strip empty authors")

    # 4. Rating: ★ string → int.
    if "rating" in out:
        v = out["rating"]
        if isinstance(v, str):
            n = stars_to_int(v)
            if n is not None:
                out["rating"] = n
                changes.append(f"rating {v!r} → {n}")
            else:
                del out["rating"]
                changes.append(f"drop unparseable rating {v!r}")
        elif v is None:
            del out["rating"]
            changes.append("drop null rating")

    # 5. Year: string → int.
    if "year" in out:
        v = out["year"]
        n = normalize_year(v)
        if n is None:
            del out["year"]
            if v is not None:
                changes.append(f"drop unparseable year {v!r}")
        elif n != v:
            out["year"] = n
            changes.append(f"year {v!r} → {n}")

    # 6. chapter: source → book (slug).
    if canon == "chapter":
        slug = slug_from_path(file_path)
        if slug:
            if out.get("book") != slug:
                out["book"] = slug
                changes.append(f"set book = {slug!r} (from path)")
            if "source" in out:
                del out["source"]
                changes.append("drop source (replaced by book)")

    # 7. (REMOVED) paper.source → journal — agent's job:
    #    source could be a journal or a book title (anthology paper).
    #    Mechanical rename would mistag ~140 anthology papers as journal articles.

    # 8. Drop orphan fields (BUT keep `publisher` for book).
    orphans_to_drop = set(ORPHAN_FIELDS)
    if canon == "book":
        # book really wants publisher and edition kept (publisher in SPEC; edition deleted per SPEC v0.2)
        orphans_to_drop.discard("publisher")
        # edition stays in orphans (we removed it from book SPEC)
    if canon == "chapter":
        # chapter wants `book` field (already set above)
        orphans_to_drop.discard("editors")  # if present, harmless drop ok
    for field in list(out.keys()):
        if field in orphans_to_drop and field not in ("type", "title", "authors", "year",
                                                       "themes", "rating", "book", "journal",
                                                       "publisher", "doi", "isbn", "category",
                                                       "name"):
            del out[field]
            changes.append(f"drop orphan {field}")

    # 9. author type: rename `title` → `name`.
    if canon == "author" and "title" in out:
        if "name" not in out:
            out["name"] = out.pop("title")
            changes.append("rename title → name (author)")
        else:
            del out["title"]
            changes.append("drop title (name already set)")

    # 10. Themes: if string, wrap in list.
    if "themes" in out:
        v = out["themes"]
        if isinstance(v, str):
            out["themes"] = [v]
            changes.append("wrap themes in list")
        elif v is None:
            out["themes"] = []
            changes.append("themes null → []")

    return out, changes


# ─── body fixes ────────────────────────────────────────────────


def rename_h2_aliases(body: str, body_schema: BodySchema) -> tuple[str, list[str]]:
    """Rewrite H2 alias headings to canonical names."""
    changes: list[str] = []
    out_lines: list[str] = []
    in_code = False
    for line in body.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
            out_lines.append(line); continue
        if in_code:
            out_lines.append(line); continue
        m = re.match(r"^## (?!#)(.+?)\s*$", line)
        if not m:
            out_lines.append(line); continue
        h2 = m.group(1).strip()
        section = body_schema.section_by_h2(h2)
        if section and section.h2 != h2:
            out_lines.append(f"## {section.h2}")
            changes.append(f"H2 rename: {h2!r} → {section.h2!r}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines), changes


# ─── file pipeline ─────────────────────────────────────────────


def fix_file(path: Path) -> tuple[str, list[str]] | None:
    """Process one file. Returns (new_text, changes) or None if no changes.

    Reassembles the file and compares to original. If reassembled text differs,
    write it — this catches both schema fixes AND pure YAML format normalization
    (e.g. block-form lists → flow-form). Idempotent: files already canonical
    are skipped.
    """
    original_text = path.read_text(encoding="utf-8")
    m = FM_RE.match(original_text)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    body = m.group(2)
    raw_type = fm.get("type")
    canon = canonical_type(raw_type)
    if canon is None:
        return None  # unknown / no type: skip

    new_fm, fm_changes = fix_frontmatter(fm, raw_type, path)
    body_changes: list[str] = []

    schemas = schema_for_type(raw_type)
    if schemas:
        _, body_schema = schemas
        body, alias_changes = rename_h2_aliases(body, body_schema)
        body_changes.extend(alias_changes)

    # Reorder by schema canonical key order (cosmetic).
    new_fm = reorder_frontmatter(new_fm, canon)

    # Reassemble with canonical YAML form (flow-style lists, schema-ordered keys,
    # no line wrapping so long arrays stay on one line).
    new_fm_yaml = yaml.safe_dump(
        new_fm,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=4096,
    ).strip()
    new_text = f"---\n{new_fm_yaml}\n---\n{body}"

    if new_text == original_text:
        return None  # already canonical, no write

    all_changes = fm_changes + body_changes
    if not all_changes:
        # Schema-level no change, but text differs → pure YAML format
        # normalization (e.g. block-form lists → flow-form).
        all_changes = ["normalize yaml format"]

    return new_text, all_changes


# ─── CLI ──────────────────────────────────────────────────────


def collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix == ".md" else []
    return [
        p for p in target.rglob("*.md")
        if not any(part.startswith(".") for part in p.relative_to(target).parts)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(VAULT_DEFAULT),
                        help="File or directory to fix (default: $CLAUDE_PROJECT_DIR/vault)")
    parser.add_argument("--write", action="store_true",
                        help="Actually write changes (default: dry-run)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N files modified (0 = no limit)")
    args = parser.parse_args()

    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        print(f"error: path does not exist: {target}", file=sys.stderr)
        sys.exit(2)

    files = collect_files(target)
    if not files:
        print("no .md files found"); return

    mode = "WRITE" if args.write else "DRY-RUN"
    print(f"[{mode}] scanning {len(files)} files under {target}")

    modified = 0
    change_kind_counter: Counter[str] = Counter()
    for path in files:
        result = fix_file(path)
        if result is None:
            continue
        new_text, changes = result
        modified += 1
        for c in changes:
            # Bucket changes by first word for summary.
            kind = c.split(":")[0].split("(")[0].split("→")[0].strip().split()[0]
            change_kind_counter[kind] += 1
        if args.write:
            path.write_text(new_text, encoding="utf-8")

        if args.limit and modified >= args.limit:
            print(f"stopping at limit ({args.limit})")
            break

    print(f"\n{mode}: {modified}/{len(files)} files would change" if not args.write
          else f"\n{mode}: {modified}/{len(files)} files written")
    print("\nchange categories:")
    for kind, n in change_kind_counter.most_common(20):
        print(f"  {kind:20} {n}")
    if not args.write:
        print("\nrun again with --write to apply")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Type-check every typed file in $CLAUDE_PROJECT_DIR/vault against quasi SPEC schemas.

Read-only. Outputs (written under $CLAUDE_PROJECT_DIR):
  $CLAUDE_PROJECT_DIR/.quasi/typecheck-report.md    — human-readable summary
  $CLAUDE_PROJECT_DIR/.quasi/typecheck-results.json — full per-file detail (for autofix)

Usage:
  # Standalone, from inside a vault project:
  python "$CLAUDE_PLUGIN_ROOT/scripts/typecheck/typecheck.py" [--path PATH]

  # PATH defaults to "vault" (i.e. $CLAUDE_PROJECT_DIR/vault).
  # PATH can be a single file or a subtree.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Locate the plugin root (this script lives at quasi/scripts/typecheck/typecheck.py).
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT))

# Vault root = $CLAUDE_PROJECT_DIR (the user's project, where they invoke from).
# Priority: explicit QUA_PROJECT_ROOT override > Claude Code's CLAUDE_PROJECT_DIR > cwd.
PROJECT_ROOT = Path(
    os.environ.get("QUA_PROJECT_ROOT")
    or os.environ.get("CLAUDE_PROJECT_DIR")
    or os.getcwd()
).resolve()

import yaml  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from schemas import (  # noqa: E402
    BodySchema,
    canonical_type,
    schema_for_type,
)


VAULT_DEFAULT = PROJECT_ROOT / "vault"
OUT_DIR = PROJECT_ROOT / ".quasi"


# ─── frontmatter / body parsing ────────────────────────────────

FM_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$")
H2_RE = re.compile(r"^## (?!#)(.+?)\s*$")
H3_RE = re.compile(r"^### (?!#)")
ANY_H_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def split_frontmatter(text: str) -> tuple[dict | None, str]:
    m = FM_RE.match(text)
    if not m:
        return None, text
    try:
        fm = yaml.safe_load(m.group(1))
        if not isinstance(fm, dict):
            return None, m.group(2)
        return fm, m.group(2)
    except yaml.YAMLError:
        return None, m.group(2)


def extract_h2_sections(body: str) -> list[tuple[str, list[str]]]:
    """Return list of (heading, lines_under_heading_until_next_h2)."""
    sections: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    in_code = False
    for line in body.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
            if current is not None:
                current[1].append(line)
            continue
        if not in_code:
            m = H2_RE.match(line)
            if m:
                if current is not None:
                    sections.append(current)
                current = (m.group(1).strip(), [])
                continue
        if current is not None:
            current[1].append(line)
    if current is not None:
        sections.append(current)
    return sections


def extract_all_headings(body: str) -> list[tuple[int, str]]:
    """Return list of (level, heading_text) for all H1..H6 in body, ignoring code blocks."""
    out: list[tuple[int, str]] = []
    in_code = False
    for line in body.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = ANY_H_RE.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2).strip()))
    return out


def detect_global_level_drift(body: str) -> int | None:
    """Detect if entire doc is shifted down a level (no H2 at all, but H3+ present).

    Returns:
        the *offset* needed to bring sections up to H2 level (1 = bump all by one,
        i.e. ### → ##; 2 = bump by two, i.e. #### → ##), or None if no global drift.
    """
    headings = extract_all_headings(body)
    if not headings:
        return None
    levels = [lvl for lvl, _ in headings]
    has_h2 = 2 in levels
    if has_h2:
        return None
    min_level = min(levels)
    if min_level <= 2:
        return None
    # Whole doc starts at H3 or lower. Offset = min_level - 2.
    return min_level - 2


# ─── block kind detection ─────────────────────────────────────


def detect_kind(lines: list[str]) -> str:
    """Detect dominant block kind under one H2 section.

    Returns one of:
      paragraph / bullet-list / numbered-list / table / blockquote-list /
      definition-list / mixed / empty / h3
    """
    has_h3 = any(H3_RE.match(line) for line in lines if line.strip())

    cleaned = [
        line.strip()
        for line in lines
        if line.strip() and not re.match(r"^#{3,}\s", line.strip())
    ]
    if not cleaned and has_h3:
        return "h3"
    if not cleaned:
        return "empty"

    counts: Counter[str] = Counter()
    in_code = False
    for line in cleaned:
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if re.match(r"^[-*]\s+", line):
            counts["bullet-list"] += 1
        elif re.match(r"^\d+\.\s+", line):
            counts["numbered-list"] += 1
        elif line.startswith("|") and line.endswith("|") and "|" in line[1:]:
            counts["table"] += 1
        elif line.startswith(">"):
            counts["blockquote-list"] += 1
        elif re.match(r"^\*\*[^*]{2,40}\*\*[::]", line):
            counts["definition-list"] += 1
        else:
            counts["paragraph"] += 1

    if has_h3:
        return "h3"
    if not counts:
        return "empty"
    total = sum(counts.values())
    top_kind, top_count = counts.most_common(1)[0]
    if top_count / total < 0.6:
        return "mixed"
    return top_kind


# ─── body schema validation ───────────────────────────────────


def check_body(body: str, body_schema: BodySchema) -> list[dict]:
    violations: list[dict] = []

    # ─── Global heading-level drift: entire doc shifted down ─────
    global_offset = detect_global_level_drift(body)
    if global_offset:
        violations.append({
            "kind": "global_heading_level_drift",
            "offset": global_offset,
            "fix": f"bump all headings up by {global_offset} level(s)",
        })
        # Don't try further section-level checks if doc is wholesale-shifted;
        # autofix will fix the level first, then re-run typecheck.
        return violations

    found_sections = extract_h2_sections(body)
    found_canonical: set[str] = set()

    for h2, lines in found_sections:
        section = body_schema.section_by_h2(h2)
        if section is None:
            violations.append({"kind": "unknown_h2", "h2": h2})
            continue
        found_canonical.add(section.h2)
        if section.h2 != h2:
            violations.append({"kind": "h2_alias", "from": h2, "to": section.h2})

        detected = detect_kind(lines)
        expected = section.kind
        is_h3_kind = expected in ("h3-project-tabs", "h3-sections")

        if is_h3_kind:
            if detected != "h3":
                violations.append({
                    "kind": "block_kind_mismatch",
                    "h2": section.h2,
                    "expected": expected,
                    "detected": detected,
                })
        elif detected not in (expected, "empty"):
            violations.append({
                "kind": ("block_kind_mismatch_soft" if detected == "mixed"
                         else "block_kind_mismatch"),
                "h2": section.h2,
                "expected": expected,
                "detected": detected,
            })

    # ─── Heading-level-drift for individual required H2s ──────
    # When required H2 is missing at H2 level, check if it appears at H3/H4
    # (with canonical name or any alias) — that's recoverable mechanically.
    all_headings = extract_all_headings(body)
    h3_h4_index: dict[str, int] = {}    # heading text → level (only H3/H4)
    for lvl, txt in all_headings:
        if lvl in (3, 4):
            h3_h4_index.setdefault(txt, lvl)

    def in_h3_h4(section_obj) -> int | None:
        if section_obj.h2 in h3_h4_index:
            return h3_h4_index[section_obj.h2]
        for alias in section_obj.aliases:
            if isinstance(alias, str) and alias in h3_h4_index:
                return h3_h4_index[alias]
            if hasattr(alias, "match"):
                for txt in h3_h4_index:
                    if alias.match(txt):
                        return h3_h4_index[txt]
        return None

    for sec in body_schema.sections:
        if not sec.required or sec.h2 in found_canonical:
            continue
        deeper_level = in_h3_h4(sec)
        if deeper_level is not None:
            violations.append({
                "kind": "heading_level_drift",
                "h2": sec.h2,
                "found_at_level": deeper_level,
                "fix": f"promote H{deeper_level} → H2",
            })
        else:
            violations.append({"kind": "missing_required_h2", "h2": sec.h2})

    return violations


# ─── per-file check ────────────────────────────────────────────


def check_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    try:
        rel = str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        rel = str(path)

    result: dict = {
        "path": rel,
        "type": None,
        "frontmatter_errors": [],
        "body_violations": [],
    }

    if fm is None:
        result["frontmatter_errors"].append({"type": "no_frontmatter"})
        return result

    raw_type = fm.get("type")
    canon = canonical_type(raw_type)
    result["type"] = canon

    if canon is None:
        result["frontmatter_errors"].append({
            "type": "unknown_type",
            "raw_type": raw_type,
        })
        return result

    if raw_type != canon:
        result["type_rename"] = {"from": raw_type, "to": canon}

    schemas = schema_for_type(raw_type)
    if not schemas:
        return result
    fm_schema, body_schema = schemas

    normalized_fm = dict(fm)
    normalized_fm["type"] = canon

    try:
        fm_schema.model_validate(normalized_fm)
    except ValidationError as e:
        result["frontmatter_errors"] = e.errors()

    result["body_violations"] = check_body(body, body_schema)
    return result


# ─── report rendering ──────────────────────────────────────────


TYPE_ORDER = ["author", "book", "chapter", "paper", "unknown"]


def build_report(stats: dict, total_files: int) -> str:
    lines = [
        "# quasi-vault typecheck report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}Z",
        f"Total files scanned: {total_files}",
        "",
        "Per-type summary(clean = 0 frontmatter errors + 0 body violations + no type rename):",
        "",
        "| Type | Total | Clean | Type rename | FM errors | Body violations |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for t in TYPE_ORDER:
        s = stats.get(t)
        if not s:
            continue
        lines.append(
            f"| `{t}` | {s['total']} | {s['clean']} "
            f"({s['clean'] / s['total'] * 100:.0f}%) "
            f"| {s['type_rename_needed']} "
            f"| {s['fm_errors_total']} | {s['body_errors_total']} |"
        )
    lines.append("")

    for t in TYPE_ORDER:
        s = stats.get(t)
        if not s or s["total"] == 0:
            continue
        lines.append(f"## `{t}` — {s['total']} files")
        lines.append("")

        if s["error_counts"]:
            lines.append("### Top frontmatter error types")
            lines.append("")
            for k, n in s["error_counts"].most_common(15):
                lines.append(f"- `{k}`: {n}")
            lines.append("")

        if s["body_violation_counts"]:
            lines.append("### Top body violation types")
            lines.append("")
            for k, n in s["body_violation_counts"].most_common(15):
                lines.append(f"- `{k}`: {n}")
            lines.append("")

        if s["missing_required_h2"]:
            lines.append("### TRULY missing required H2(占该 type 文件比例)")
            lines.append("")
            for h2, n in s["missing_required_h2"].most_common(20):
                pct = n / s["total"] * 100
                lines.append(f"- `## {h2}` 缺失: {n} 个 ({pct:.0f}%)")
            lines.append("")

        if s["heading_drift"]:
            lines.append("### Heading-level drift(H3/H4 应提升到 H2)")
            lines.append("")
            for h2, n in s["heading_drift"].most_common(20):
                pct = n / s["total"] * 100
                lines.append(f"- `## {h2}` 在 H3/H4: {n} 个 ({pct:.0f}%) — 机械可修")
            lines.append("")

        if s["unknown_h2"]:
            lines.append("### Top unknown H2(数十种漂移别名)")
            lines.append("")
            for h2, n in s["unknown_h2"].most_common(20):
                lines.append(f"- `## {h2}` × {n}")
            lines.append("")

    return "\n".join(lines)


# ─── main ──────────────────────────────────────────────────────


def collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix == ".md" else []
    files: list[Path] = []
    for p in target.rglob("*.md"):
        rel_parts = p.relative_to(target).parts if p.is_relative_to(target) else p.parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        files.append(p)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        default=str(VAULT_DEFAULT),
        help="File or directory to typecheck (default: $CLAUDE_PROJECT_DIR/vault)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-type summary (still writes report files)",
    )
    args = parser.parse_args()

    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        print(f"error: path does not exist: {target}", file=sys.stderr)
        sys.exit(2)

    files = collect_files(target)
    if not args.quiet:
        rel = (target.relative_to(PROJECT_ROOT) if target.is_relative_to(PROJECT_ROOT) else target)
        print(f"scanning {len(files)} md files under {rel}...")

    results: list[dict] = []
    stats: dict[str, dict] = defaultdict(lambda: {
        "total": 0,
        "clean": 0,
        "fm_errors_total": 0,
        "body_errors_total": 0,
        "type_rename_needed": 0,
        "error_counts": Counter(),
        "body_violation_counts": Counter(),
        "missing_required_h2": Counter(),
        "heading_drift": Counter(),
        "unknown_h2": Counter(),
    })

    for path in files:
        r = check_file(path)
        results.append(r)

        t = r["type"] or "unknown"
        s = stats[t]
        s["total"] += 1

        if r["frontmatter_errors"]:
            s["fm_errors_total"] += len(r["frontmatter_errors"])
            for err in r["frontmatter_errors"]:
                s["error_counts"][err.get("type", "?")] += 1
        if r["body_violations"]:
            s["body_errors_total"] += len(r["body_violations"])
            for v in r["body_violations"]:
                s["body_violation_counts"][v["kind"]] += 1
                if v["kind"] == "missing_required_h2":
                    s["missing_required_h2"][v["h2"]] += 1
                elif v["kind"] == "heading_level_drift":
                    s["heading_drift"][v["h2"]] += 1
                elif v["kind"] == "unknown_h2":
                    s["unknown_h2"][v["h2"]] += 1
        if r.get("type_rename"):
            s["type_rename_needed"] += 1
        if (
            not r["frontmatter_errors"]
            and not r["body_violations"]
            and not r.get("type_rename")
        ):
            s["clean"] += 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "typecheck-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str)
    )
    report = build_report(stats, len(files))
    (OUT_DIR / "typecheck-report.md").write_text(report)

    if not args.quiet:
        print(f"\nresults: {len(results)} files checked")
        for t in TYPE_ORDER:
            s = stats.get(t)
            if not s:
                continue
            clean_pct = (s["clean"] / s["total"] * 100) if s["total"] else 0
            print(
                f"  {t:10} {s['total']:6}  "
                f"clean: {s['clean']:6} ({clean_pct:4.0f}%)  "
                f"fm_err: {s['fm_errors_total']:6}  "
                f"body_err: {s['body_errors_total']:6}  "
                f"type_rename: {s['type_rename_needed']:6}"
            )
        rel_out = OUT_DIR.relative_to(PROJECT_ROOT) if OUT_DIR.is_relative_to(PROJECT_ROOT) else OUT_DIR
        print(f"\nreport → {rel_out / 'typecheck-report.md'}")
        print(f"detail → {rel_out / 'typecheck-results.json'}")

    # Exit code: 0 if all clean, 1 if any violations (CI / agent decision).
    has_violations = any(
        s["fm_errors_total"] + s["body_errors_total"] + s["type_rename_needed"] > 0
        for s in stats.values()
    )
    sys.exit(1 if has_violations else 0)


if __name__ == "__main__":
    main()

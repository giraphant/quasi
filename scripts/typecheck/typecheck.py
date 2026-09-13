#!/usr/bin/env python3
"""Type-check Markdown files against quasi's executable schemas.

The standalone command writes its named report artifacts under
``$CLAUDE_PROJECT_DIR/.quasi/audit``. Library callers can use
``evaluate_typecheck()`` or ``run_typecheck(write_report=False)`` for a strict
no-write path.

Usage:
  # Standalone, from inside a vault project:
  python "$CLAUDE_PLUGIN_ROOT/scripts/typecheck/typecheck.py" [--path PATH]

  # PATH defaults to "vault" (i.e. $CLAUDE_PROJECT_DIR/vault).
  # PATH can be a single file or a subtree.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Locate roots (this script lives at quasi/scripts/typecheck/typecheck.py).
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

import yaml  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from scripts.core import project_root  # noqa: E402
from schemas import (  # noqa: E402
    TYPE_REGISTRY,
    BodySchema,
    canonical_type,
    deprecated_canonical_type,
    schema_for_type,
)


PROJECT_ROOT = project_root()
VAULT_DEFAULT = PROJECT_ROOT / "vault"
OUT_DIR = PROJECT_ROOT / ".quasi" / "audit"


# ─── frontmatter / body parsing ────────────────────────────────

FM_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$")
H2_RE = re.compile(r"^## (?!#)(.+?)\s*$")
H3_RE = re.compile(r"^### (?!#)")
ANY_H_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def fence_open_marker(line: str) -> tuple[str, int] | None:
    match = FENCE_OPEN_RE.match(line.rstrip("\r\n"))
    if not match:
        return None
    marker = match.group(1)
    return marker[0], len(marker)


def is_fence_close(line: str, fence_char: str, fence_len: int) -> bool:
    return re.match(rf"^ {{0,3}}{re.escape(fence_char)}{{{fence_len},}}\s*$", line.rstrip("\r\n")) is not None


def split_frontmatter(text: str) -> tuple[dict | None, str, dict[str, Any] | None]:
    """Split a Markdown document without collapsing distinct YAML failures."""
    match = FM_RE.match(text)
    if not match:
        return None, text, {
            "type": "missing_frontmatter",
            "loc": [],
            "msg": "document has no YAML frontmatter",
        }

    body = match.group(2)
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        message = str(exc).splitlines()[0] if str(exc) else "invalid YAML frontmatter"
        return None, body, {
            "type": "invalid_yaml",
            "loc": [],
            "msg": message,
        }

    if not isinstance(frontmatter, dict):
        return None, body, {
            "type": "frontmatter_not_mapping",
            "loc": [],
            "msg": "YAML frontmatter must be a mapping",
        }

    return frontmatter, body, None


def extract_h2_sections(body: str) -> list[tuple[str, list[str]]]:
    """Return list of (heading, lines_under_heading_until_next_h2)."""
    sections: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    fence_char = ""
    fence_len = 0
    for line in body.split("\n"):
        if fence_char:
            if current is not None:
                current[1].append(line)
            if is_fence_close(line, fence_char, fence_len):
                fence_char = ""
                fence_len = 0
            continue

        marker = fence_open_marker(line)
        if marker:
            fence_char, fence_len = marker
            if current is not None:
                current[1].append(line)
            continue

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
    fence_char = ""
    fence_len = 0
    for line in body.split("\n"):
        if fence_char:
            if is_fence_close(line, fence_char, fence_len):
                fence_char = ""
                fence_len = 0
            continue
        marker = fence_open_marker(line)
        if marker:
            fence_char, fence_len = marker
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
    fence_char = ""
    fence_len = 0
    for line in cleaned:
        if fence_char:
            if is_fence_close(line, fence_char, fence_len):
                fence_char = ""
                fence_len = 0
            continue
        marker = fence_open_marker(line)
        if marker:
            fence_char, fence_len = marker
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


def check_body(body: str, body_schema: BodySchema) -> tuple[list[dict], list[dict]]:
    """Return blocking violations and non-blocking body warnings separately."""
    violations: list[dict] = []
    warnings: list[dict] = []
    if not body_schema.sections:
        return violations, warnings

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
        return violations, warnings

    found_sections = extract_h2_sections(body)
    found_canonical: set[str] = set()

    for h2, lines in found_sections:
        section = body_schema.section_by_h2(h2)
        if section is None:
            diagnostic = {"kind": "unknown_h2", "h2": h2}
            if body_schema.strict:
                violations.append(diagnostic)
            else:
                warnings.append(diagnostic)
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
        elif expected == "freeform":
            if detected == "empty":
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

    return violations, warnings


# ─── per-file check ────────────────────────────────────────────


def check_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    fm, body, parse_error = split_frontmatter(text)
    try:
        rel = str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        rel = str(path)

    result: dict = {
        "path": rel,
        "type": None,
        "frontmatter_errors": [],
        "body_violations": [],
        "body_warnings": [],
    }

    if parse_error is not None:
        result["frontmatter_errors"].append(parse_error)
        return result

    assert fm is not None
    raw_type = fm.get("type")
    if raw_type is None:
        result["frontmatter_errors"].append({
            "type": "missing_type",
            "loc": ["type"],
            "msg": "frontmatter is missing the type field",
        })
        return result
    if not isinstance(raw_type, str):
        result["frontmatter_errors"].append({
            "type": "unknown_type",
            "loc": ["type"],
            "msg": "frontmatter type must be a canonical string",
            "raw_type": str(raw_type),
            "python_type": type(raw_type).__name__,
        })
        return result

    canon = canonical_type(raw_type)
    result["type"] = canon

    if canon is None:
        deprecated = deprecated_canonical_type(raw_type)
        if deprecated:
            result["type"] = deprecated
            result["frontmatter_errors"].append({
                "type": "deprecated_type",
                "loc": ["type"],
                "msg": f"frontmatter type {raw_type!r} is deprecated; use {deprecated!r}",
                "raw_type": raw_type,
                "canonical_type": deprecated,
            })
        else:
            result["frontmatter_errors"].append({
                "type": "unknown_type",
                "loc": ["type"],
                "msg": f"unknown frontmatter type: {raw_type!r}",
                "raw_type": raw_type,
            })
        return result

    schemas = schema_for_type(canon)
    if not schemas:
        return result
    fm_schema, body_schema = schemas

    normalized_fm = dict(fm)
    normalized_fm["type"] = canon

    try:
        fm_schema.model_validate(normalized_fm)
    except ValidationError as exc:
        result["frontmatter_errors"] = json.loads(exc.json(include_url=False))

    violations, warnings = check_body(body, body_schema)
    result["body_violations"] = violations
    result["body_warnings"] = warnings
    return result


# ─── report rendering ──────────────────────────────────────────


TYPECHECK_VERSION = "quasi-typecheck.results.v1"
TYPE_ORDER = [*TYPE_REGISTRY, "unknown"]


def build_report(stats: dict, total_files: int) -> str:
    lines = [
        "# quasi-vault typecheck report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
        f"Total files scanned: {total_files}",
        "",
        "Per-type summary(clean = 0 frontmatter errors + 0 blocking body violations):",
        "",
        "| Type | Total | Clean | FM errors | Body violations | Body warnings |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for t in TYPE_ORDER:
        s = stats.get(t)
        if not s:
            continue
        clean_pct = (s["clean"] / s["total"] * 100) if s["total"] else 0
        lines.append(
            f"| `{t}` | {s['total']} | {s['clean']} "
            f"({clean_pct:.0f}%) "
            f"| {s['fm_errors_total']} | {s['body_errors_total']} "
            f"| {s['body_warnings_total']} |"
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

        if s["body_warning_counts"]:
            lines.append("### Top non-blocking body warnings")
            lines.append("")
            for k, n in s["body_warning_counts"].most_common(15):
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
            lines.append("### Top unknown H2 (warning unless BodySchema.strict=true)")
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
    for p in sorted(target.rglob("*.md")):
        rel_parts = p.relative_to(target).parts if p.is_relative_to(target) else p.parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        files.append(p)
    return files


def _empty_stats() -> dict[str, Any]:
    return {
        "total": 0,
        "clean": 0,
        "fm_errors_total": 0,
        "body_errors_total": 0,
        "body_warnings_total": 0,
        "type_rename_needed": 0,
        "error_counts": Counter(),
        "body_violation_counts": Counter(),
        "body_warning_counts": Counter(),
        "missing_required_h2": Counter(),
        "heading_drift": Counter(),
        "unknown_h2": Counter(),
    }


def evaluate_typecheck(target: Path) -> dict[str, Any]:
    """Evaluate *target* entirely in memory without creating report artifacts."""
    target = Path(target).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(target)

    files = collect_files(target)
    results: list[dict[str, Any]] = []
    stats = {type_name: _empty_stats() for type_name in TYPE_ORDER}

    for path in files:
        result = check_file(path)
        results.append(result)

        type_name = result["type"] if result["type"] in TYPE_REGISTRY else "unknown"
        type_stats = stats[type_name]
        type_stats["total"] += 1

        frontmatter_errors = result.get("frontmatter_errors") or []
        type_stats["fm_errors_total"] += len(frontmatter_errors)
        for error in frontmatter_errors:
            type_stats["error_counts"][error.get("type", "?")] += 1

        body_violations = result.get("body_violations") or []
        type_stats["body_errors_total"] += len(body_violations)
        for violation in body_violations:
            kind = violation["kind"]
            type_stats["body_violation_counts"][kind] += 1
            if kind == "missing_required_h2":
                type_stats["missing_required_h2"][violation["h2"]] += 1
            elif kind == "heading_level_drift":
                type_stats["heading_drift"][violation["h2"]] += 1
            elif kind == "unknown_h2":
                type_stats["unknown_h2"][violation["h2"]] += 1

        body_warnings = result.get("body_warnings") or []
        type_stats["body_warnings_total"] += len(body_warnings)
        for warning in body_warnings:
            kind = warning["kind"]
            type_stats["body_warning_counts"][kind] += 1
            if kind == "unknown_h2":
                type_stats["unknown_h2"][warning["h2"]] += 1

        if result.get("type_rename"):
            type_stats["type_rename_needed"] += 1
        if not frontmatter_errors and not body_violations and not result.get("type_rename"):
            type_stats["clean"] += 1

    has_violations = any(
        type_stats["fm_errors_total"]
        + type_stats["body_errors_total"]
        + type_stats["type_rename_needed"]
        > 0
        for type_stats in stats.values()
    )
    return {
        "target": target,
        "files": files,
        "results": results,
        "stats": stats,
        "has_violations": has_violations,
    }


def _counter_payload(counter: Counter) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def build_results_payload(
    evaluation: dict[str, Any],
    *,
    requested_path: str,
) -> dict[str, Any]:
    """Build the stable stdout JSON contract for a no-write typecheck report."""
    stats = evaluation["stats"]
    type_payload: dict[str, Any] = {}
    for type_name in TYPE_ORDER:
        type_stats = stats[type_name]
        type_payload[type_name] = {
            "total": type_stats["total"],
            "clean": type_stats["clean"],
            "frontmatter_errors": type_stats["fm_errors_total"],
            "body_violations": type_stats["body_errors_total"],
            "body_warnings": type_stats["body_warnings_total"],
            "error_counts": _counter_payload(type_stats["error_counts"]),
            "body_violation_counts": _counter_payload(type_stats["body_violation_counts"]),
            "body_warning_counts": _counter_payload(type_stats["body_warning_counts"]),
        }

    all_stats = list(stats.values())
    files_with_errors = sum(
        1
        for result in evaluation["results"]
        if result.get("frontmatter_errors")
        or result.get("body_violations")
        or result.get("type_rename")
    )
    return {
        "version": TYPECHECK_VERSION,
        "status": "dirty" if evaluation["has_violations"] else "clean",
        "target": {
            "requested": requested_path,
            "resolved": str(evaluation["target"]),
            "exists": True,
        },
        "summary": {
            "files_checked": len(evaluation["results"]),
            "files_clean": sum(item["clean"] for item in all_stats),
            "files_with_errors": files_with_errors,
            "frontmatter_errors": sum(item["fm_errors_total"] for item in all_stats),
            "body_violations": sum(item["body_errors_total"] for item in all_stats),
            "body_warnings": sum(item["body_warnings_total"] for item in all_stats),
        },
        "types": type_payload,
        "files": evaluation["results"],
    }


def missing_path_payload(target: Path, *, requested_path: str) -> dict[str, Any]:
    return {
        "version": TYPECHECK_VERSION,
        "status": "error",
        "target": {
            "requested": requested_path,
            "resolved": str(target),
            "exists": False,
        },
        "error": f"path does not exist: {target}",
    }


def run_typecheck(
    target: Path,
    *,
    quiet: bool = False,
    write_report: bool = True,
    results_path: Path | None = None,
) -> int:
    """Run local typecheck, writing only outputs explicitly enabled by the caller.

    ``write_report=False`` with no ``results_path`` is a strict no-write path.
    Returns 0 when no blocking violation remains, 1 when dirty, and 2 when the
    target does not exist. Non-strict body warnings never affect the exit code.
    """
    target = Path(target).expanduser().resolve()
    if not target.exists():
        print(f"error: path does not exist: {target}", file=sys.stderr)
        return 2

    evaluation = evaluate_typecheck(target)
    files = evaluation["files"]
    stats = evaluation["stats"]
    if not quiet:
        rel = target.relative_to(PROJECT_ROOT) if target.is_relative_to(PROJECT_ROOT) else target
        print(f"scanning {len(files)} md files under {rel}...")

    result_output: Path | None = None
    if results_path is not None:
        result_output = Path(results_path).expanduser().resolve()
    elif write_report:
        result_output = OUT_DIR / "typecheck-results.json"

    if result_output is not None:
        result_output.parent.mkdir(parents=True, exist_ok=True)
        result_output.write_text(
            json.dumps(evaluation["results"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if write_report:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        report = build_report(stats, len(files))
        (OUT_DIR / "typecheck-report.md").write_text(
            report + "\n",
            encoding="utf-8",
        )

    if not quiet:
        print(f"\nresults: {len(evaluation['results'])} files checked")
        for type_name in TYPE_ORDER:
            type_stats = stats[type_name]
            clean_pct = (
                type_stats["clean"] / type_stats["total"] * 100
                if type_stats["total"]
                else 0
            )
            print(
                f"  {type_name:10} {type_stats['total']:6}  "
                f"clean: {type_stats['clean']:6} ({clean_pct:4.0f}%)  "
                f"fm_err: {type_stats['fm_errors_total']:6}  "
                f"body_err: {type_stats['body_errors_total']:6}  "
                f"body_warn: {type_stats['body_warnings_total']:6}"
            )
        rel_out = OUT_DIR.relative_to(PROJECT_ROOT) if OUT_DIR.is_relative_to(PROJECT_ROOT) else OUT_DIR
        if write_report:
            print(f"\nreport → {rel_out / 'typecheck-report.md'}")
        if result_output is not None:
            try:
                detail_output = result_output.relative_to(PROJECT_ROOT)
            except ValueError:
                detail_output = result_output
            print(f"detail → {detail_output}")

    return 1 if evaluation["has_violations"] else 0


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

    sys.exit(run_typecheck(Path(args.path), quiet=args.quiet, write_report=True))


if __name__ == "__main__":
    main()

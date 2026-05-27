#!/usr/bin/env python3
"""field_distribution — read-only frontmatter field distribution audit for agents."""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

VERSION = "quasi-audit.frontmatter-fields.v1"

FM_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---")

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ROOT = _PLUGIN_ROOT / "scripts"
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from schemas.registry import canonical_type, deprecated_canonical_type  # noqa: E402


def iter_markdown(target: Path) -> list[Path]:
    """Return Markdown files under *target*.

    If *target* is a file, return ``[target]`` only when its suffix is ``.md``.
    If *target* is a directory, recursively collect ``.md`` files while
    skipping dot-directories.
    """
    if target.is_file():
        return [target] if target.suffix == ".md" else []

    files: list[Path] = []
    for entry in sorted(target.rglob("*.md")):
        if any(part.startswith(".") for part in entry.relative_to(target).parts):
            continue
        files.append(entry)
    return files


def parse_frontmatter(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Parse YAML frontmatter from a Markdown file.

    Returns ``(data, None)`` on success, or ``(None, error_tag)`` on failure.
    *error_tag* is one of ``"missing_frontmatter"``,
    ``"frontmatter_not_mapping"``, or the first line of a YAML error message.
    """
    text = path.read_text(encoding="utf-8")
    match = FM_RE.match(text)
    if not match:
        return (None, "missing_frontmatter")

    fm_text = match.group(1)
    try:
        data = yaml.safe_load(fm_text)
    except yaml.YAMLError as e:
        error_str = str(e)
        first_line = error_str.splitlines()[0] if error_str else "yaml parse error"
        return (None, first_line)

    if not isinstance(data, dict):
        return (None, "frontmatter_not_mapping")

    return (data, None)


def bucket_for_type(raw_type: Any) -> tuple[str, dict[str, Any] | None]:
    """Classify *raw_type* into a canonical bucket name and optional problem info.

    * canonical type      → ``(canonical_name, None)``
    * deprecated alias    → ``(deprecated_canonical_name, {problem, raw_type, canonical_type})``
    * missing (None)     → ``("_missing_type", {problem: "missing_type"})``
    * non-string/unknown → ``("_unknown_type", {problem, raw_type, python_type})``
    """
    # Guard: None and non-string types must be handled before registry helpers,
    # which assume hashable string inputs.
    if raw_type is None:
        return ("_missing_type", {"problem": "missing_type"})

    if not isinstance(raw_type, str):
        return ("_unknown_type", {
            "problem": "unknown_type",
            "raw_type": str(raw_type),
            "python_type": type(raw_type).__name__,
        })

    canon = canonical_type(raw_type)
    if canon:
        return (canon, None)

    dep = deprecated_canonical_type(raw_type)
    if dep:
        return (dep, {
            "problem": "deprecated_type",
            "raw_type": raw_type,
            "canonical_type": dep,
        })

    return ("_unknown_type", {
        "problem": "unknown_type",
        "raw_type": raw_type,
        "python_type": type(raw_type).__name__,
    })


def _rel_path(path: Path, root: Path) -> str:
    """Return *path* relative to *root*, falling back to ``str(path)``."""
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def audit_path(
    target: Path,
    *,
    root: Path,
    requested_path: str,
    example_limit: int = 5,
) -> dict[str, Any]:
    """Audit frontmatter field distribution across all Markdown files under *target*."""
    files = iter_markdown(target)

    summary: dict[str, int] = {
        "files_scanned": len(files),
        "frontmatter_files": 0,
        "missing_frontmatter": 0,
        "invalid_frontmatter": 0,
        "missing_type": 0,
        "unknown_type": 0,
        "deprecated_type": 0,
    }

    types: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"files": 0, "fields": defaultdict(lambda: {"count": 0, "examples": []})}  # type: ignore[arg-type]
    )
    problems: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for file in files:
        fm_data, error = parse_frontmatter(file)

        if error == "missing_frontmatter":
            summary["missing_frontmatter"] += 1
            problems["missing_frontmatter"].append({"path": _rel_path(file, root)})
            continue

        summary["frontmatter_files"] += 1

        if error is not None:
            summary["invalid_frontmatter"] += 1
            problems["invalid_frontmatter"].append({
                "path": _rel_path(file, root),
                "error": error,
            })
            continue

        # Valid frontmatter dict
        raw_type = fm_data.get("type")
        bucket_name, problem_info = bucket_for_type(raw_type)

        if problem_info is not None:
            problem_type = problem_info["problem"]
            summary[problem_type] += 1
            entry: dict[str, Any] = {"path": _rel_path(file, root)}
            if "raw_type" in problem_info:
                entry["raw_type"] = problem_info["raw_type"]
            if "canonical_type" in problem_info:
                entry["canonical_type"] = problem_info["canonical_type"]
            if "python_type" in problem_info:
                entry["python_type"] = problem_info["python_type"]
            problems[problem_type].append(entry)

        # Increment type-bucket file count and field counts
        types[bucket_name]["files"] += 1
        rel = _rel_path(file, root)
        for field_key in fm_data:
            types[bucket_name]["fields"][field_key]["count"] += 1
            types[bucket_name]["fields"][field_key]["examples"].append(rel)

    # Compute coverage and cap examples per field
    for type_name, type_data in types.items():
        file_count = type_data["files"]
        for field_name, field_data in type_data["fields"].items():
            field_data["coverage"] = round(field_data["count"] / file_count, 4)
            field_data["examples"] = field_data["examples"][:example_limit]

    # Build plain-dict types section
    types_plain: dict[str, Any] = {}
    for type_name, type_data in types.items():
        fields_plain: dict[str, Any] = {}
        for field_name, field_data in type_data["fields"].items():
            fields_plain[field_name] = dict(field_data)
        types_plain[type_name] = {"files": type_data["files"], "fields": fields_plain}

    # Cap problem lists
    problems_plain: dict[str, list[dict[str, Any]]] = {}
    for prob_name, prob_list in problems.items():
        problems_plain[prob_name] = prob_list[:example_limit]

    return {
        "version": VERSION,
        "target": {
            "requested": requested_path,
            "resolved": str(target),
            "exists": target.exists(),
        },
        "summary": summary,
        "types": types_plain,
        "problems": problems_plain,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render an audit report dict as Markdown."""
    lines: list[str] = []

    lines.append("# Frontmatter field distribution")
    lines.append("")

    if "error" in report:
        lines.append("## Error")
        lines.append("")
        lines.append(str(report["error"]))
        return "\n".join(lines)

    lines.append("## Summary")
    lines.append("")

    summary = report["summary"]
    for key in (
        "files_scanned",
        "frontmatter_files",
        "missing_frontmatter",
        "invalid_frontmatter",
        "missing_type",
        "unknown_type",
        "deprecated_type",
    ):
        lines.append(f"- `{key}`: {summary[key]}")

    lines.append("")

    types = report.get("types", {})
    for type_name in sorted(types):
        type_data = types[type_name]
        lines.append(f"## Type: {type_name}")
        lines.append("")
        lines.append(f"Files: {type_data['files']}")
        lines.append("")

        fields = type_data.get("fields", {})
        if fields:
            lines.append("| Field | Count | Coverage | Examples |")
            lines.append("|---|---|---|---|")
            for field_name in sorted(fields):
                fd = fields[field_name]
                coverage_pct = fd["coverage"] * 100
                examples_html = "<br>".join(f"`{ex}`" for ex in fd["examples"])
                lines.append(
                    f"| `{field_name}` | {fd['count']} | {coverage_pct:.1f}% | {examples_html} |"
                )
        lines.append("")

    problems = report.get("problems", {})
    if problems:
        lines.append("## Problems")
        lines.append("")
        for prob_name in sorted(problems):
            prob_list = problems[prob_name]
            if not prob_list:
                continue
            lines.append(f"### {prob_name}")
            lines.append("")
            for entry in prob_list:
                lines.append(f"- {entry['path']}")
            lines.append("")

    return "\n".join(lines)


def error_payload(target: Path, requested_path: str) -> dict[str, Any]:
    """Build a minimal error report for a missing *target*."""
    return {
        "version": VERSION,
        "target": {
            "requested": requested_path,
            "resolved": str(target),
            "exists": target.exists(),
        },
        "error": f"path does not exist: {target}",
    }


def print_report(report: dict[str, Any], output_format: str, *, out: Any = sys.stdout) -> None:
    """Write *report* to *out* in the given *output_format* (``"json"`` or ``"markdown"``)."""
    if output_format == "json":
        json.dump(report, out, ensure_ascii=False, indent=2)
        out.write("\n")
    elif output_format == "markdown":
        out.write(render_markdown(report))
        out.write("\n")
    else:
        raise ValueError(f"unknown output_format: {output_format!r}")


def run_fields_report(
    *,
    requested_path: str,
    target: Path,
    root: Path,
    output_format: str,
    example_limit: int = 5,
    out: Any = sys.stdout,
) -> int:
    """Entry point: audit *target* and print the report.

    Returns 0 on success, 2 when *target* does not exist.
    """
    if not target.exists():
        payload = error_payload(target, requested_path)
        print_report(payload, output_format, out=out)
        return 2

    report = audit_path(
        target,
        root=root,
        requested_path=requested_path,
        example_limit=example_limit,
    )
    print_report(report, output_format, out=out)
    return 0

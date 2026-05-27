#!/usr/bin/env python3
"""quasi-audit — diagnostic-first vault audit for agents."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from core import load_script_module, print_json, project_root, resolve_project_path  # noqa: E402

FM_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$")
FLOW_ARRAY_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*\[[^\]]*\]\s*(?:#.*)?$")
CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
ASCII_QUOTE_PAIR_RE = re.compile(r'(?<!\\)"([^"\n]{1,200})(?<!\\)"')
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)[^\n]*?(?<!`)\1(?!`)")
LINK_TARGET_RE = re.compile(r"\]\([^\n)]*\)")
WIKI_LINK_RE = re.compile(r"\[\[[^\]\n]*\]\]")
SENTENCE_BOUNDARY_RE = re.compile(r"[。！？!?\n]")


def _project_root() -> Path:
    return project_root()


def _resolve_target(path_arg: str, root: Path) -> Path:
    return resolve_project_path(path_arg, root)


def _load(module_name: str, relative_path: str):
    return load_script_module(module_name, PLUGIN_ROOT / relative_path)


def _rel_path(path: Path, root: Path) -> str:
    path = path.resolve()
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _result_rel_path(path_value: str, root: Path) -> str:
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    return _rel_path(path, root)


def _line_column_for(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    line_start = text.rfind("\n", 0, offset) + 1
    return line, offset - line_start + 1


def _split_frontmatter_text(text: str) -> tuple[str | None, str, int]:
    match = FM_RE.match(text)
    if not match:
        return None, text, 0
    return match.group(1), match.group(2), match.start(2)


def _extract_yaml_field_block(frontmatter: str | None, field: str) -> str:
    if frontmatter is None:
        return ""
    lines = frontmatter.splitlines()
    out: list[str] = []
    collecting = False
    for line in lines:
        if line.startswith(f"{field}:"):
            collecting = True
            out.append(line)
            continue
        if collecting:
            if line.startswith(" ") or line.startswith("-") or not line.strip():
                out.append(line)
                continue
            break
    return "\n".join(out)


def _base_diag(
    *,
    rel_path: str,
    diag_id: str,
    pass_name: str,
    severity: str,
    status: str,
    message: str,
    action: str,
    location: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    diag: dict[str, Any] = {
        "id": diag_id,
        "pass": pass_name,
        "severity": severity,
        "status": status,
        "message": message,
        "action": action,
        "path": rel_path,
    }
    if location:
        diag["location"] = location
    diag.update({k: v for k, v in extra.items() if v not in (None, "")})
    return diag


def _frontmatter_flow_array_diagnostics(path: Path, before: str, after: str, root: Path) -> list[dict[str, Any]]:
    before_fm, _, _ = _split_frontmatter_text(before)
    after_fm, _, _ = _split_frontmatter_text(after)
    if before_fm is None:
        return []

    diagnostics: list[dict[str, Any]] = []
    rel_path = _rel_path(path, root)
    match = FM_RE.match(before)
    fm_offset = match.start(1) if match else 0
    offset = fm_offset
    for raw_line in before_fm.splitlines():
        field_match = FLOW_ARRAY_RE.match(raw_line.strip())
        if field_match:
            field = field_match.group(1)
            line, column = _line_column_for(before, offset + raw_line.find(field))
            diagnostics.append(_base_diag(
                rel_path=rel_path,
                diag_id=f"frontmatter.{field}.flow_array",
                pass_name="frontmatter_schema",
                severity="warning",
                status="auto_fixed",
                message=f"{field} must use block-form array",
                action="none",
                location={"line": line, "column": column, "field": field},
                before=raw_line.strip(),
                after=_extract_yaml_field_block(after_fm, field),
            ))
        offset += len(raw_line) + 1
    return diagnostics


def _mechanical_change_diagnostics(path: Path, changes: list[str], before: str, after: str, root: Path) -> list[dict[str, Any]]:
    diagnostics = _frontmatter_flow_array_diagnostics(path, before, after, root)
    rel_path = _rel_path(path, root)
    has_flow_diag = bool(diagnostics)
    for change in changes:
        if change == "normalize yaml format" and has_flow_diag:
            continue
        if change.startswith("H2 rename:"):
            diagnostics.append(_base_diag(
                rel_path=rel_path,
                diag_id="body.h2_alias.auto_fixed",
                pass_name="body_schema",
                severity="warning",
                status="auto_fixed",
                message=change,
                action="none",
            ))
        elif change.startswith("type:"):
            diagnostics.append(_base_diag(
                rel_path=rel_path,
                diag_id="frontmatter.type.canonicalized",
                pass_name="frontmatter_schema",
                severity="warning",
                status="auto_fixed",
                message=change,
                action="none",
            ))
        elif change == "normalize yaml format":
            diagnostics.append(_base_diag(
                rel_path=rel_path,
                diag_id="frontmatter.yaml.normalized",
                pass_name="frontmatter_schema",
                severity="info",
                status="auto_fixed",
                message="frontmatter YAML normalized to canonical block style",
                action="none",
            ))
        else:
            diagnostics.append(_base_diag(
                rel_path=rel_path,
                diag_id="frontmatter.mechanical_fix",
                pass_name="frontmatter_schema",
                severity="warning",
                status="auto_fixed",
                message=change,
                action="none",
            ))
    return diagnostics


def _run_mechanical_autofix(autofix_mod, target: Path, root: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], set[str], list[Path]]:
    files = autofix_mod.collect_files(target)
    modified_paths: set[str] = set()
    diagnostics_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    change_counts: Counter[str] = Counter()

    for path in files:
        before = path.read_text(encoding="utf-8")
        result = autofix_mod.fix_file(path)
        if result is None:
            continue
        after, changes = result
        path.write_text(after, encoding="utf-8")
        rel_path = _rel_path(path, root)
        modified_paths.add(rel_path)
        diagnostics_by_path[rel_path].extend(
            _mechanical_change_diagnostics(path, changes, before, after, root)
        )
        for change in changes:
            kind = change.split(":")[0].split("(")[0].split("→")[0].strip().split()[0]
            change_counts[kind] += 1

    return {
        "files_scanned": len(files),
        "files_modified": len(modified_paths),
        "change_counts": dict(change_counts),
    }, diagnostics_by_path, modified_paths, files


def _blank_preserving_newlines(text: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in text)


def _mask_pattern(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda match: _blank_preserving_newlines(match.group(0)), text)


def _mask_fenced_code(text: str) -> str:
    output: list[str] = []
    fence_char = ""
    fence_len = 0
    opener_re = re.compile(r"^ {0,3}(`{3,}|~{3,})")

    for line in text.splitlines(True):
        if fence_char:
            output.append(_blank_preserving_newlines(line))
            stripped = line.rstrip("\r\n")
            closer_re = re.compile(rf"^ {{0,3}}{re.escape(fence_char)}{{{fence_len},}}\s*$")
            if closer_re.match(stripped):
                fence_char = ""
                fence_len = 0
            continue

        match = opener_re.match(line.rstrip("\r\n"))
        if match:
            marker = match.group(1)
            fence_char = marker[0]
            fence_len = len(marker)
            output.append(_blank_preserving_newlines(line))
            continue

        output.append(line)

    return "".join(output)


def _mask_indented_code(text: str) -> str:
    output: list[str] = []
    for line in text.splitlines(True):
        if line.startswith("    ") or line.startswith("\t"):
            output.append(_blank_preserving_newlines(line))
        else:
            output.append(line)
    return "".join(output)


def _mask_markdown_non_body(text: str) -> str:
    masked = _mask_fenced_code(text)
    masked = _mask_indented_code(masked)
    masked = _mask_pattern(masked, INLINE_CODE_RE)
    masked = _mask_pattern(masked, LINK_TARGET_RE)
    masked = _mask_pattern(masked, WIKI_LINK_RE)
    return masked


def _sentence_context(text: str, start: int, end: int) -> str:
    left = start
    while left > 0 and not SENTENCE_BOUNDARY_RE.match(text[left - 1]):
        left -= 1
    right = end
    while right < len(text) and not SENTENCE_BOUNDARY_RE.match(text[right]):
        right += 1
    if right < len(text):
        right += 1
    return " ".join(text[left:right].strip().split())


def _quote_replacement(original: str) -> str:
    return "「" + original[1:-1] + "」"


def _quote_style_autofix_file(path: Path, root: Path) -> tuple[str | None, list[dict[str, Any]]]:
    text = path.read_text(encoding="utf-8")
    frontmatter, body, body_offset = _split_frontmatter_text(text)
    masked = _mask_markdown_non_body(body)
    rel_path = _rel_path(path, root)
    replacements: list[tuple[int, int, str]] = []
    diagnostics: list[dict[str, Any]] = []

    for match in ASCII_QUOTE_PAIR_RE.finditer(masked):
        original = body[match.start():match.end()]
        if not CJK_RE.search(original):
            continue
        replacement = _quote_replacement(original)
        full_start = body_offset + match.start()
        line, column = _line_column_for(text, full_start)
        before_context = _sentence_context(body, match.start(), match.end())
        after_context = before_context.replace(original, replacement, 1)
        diagnostics.append(_base_diag(
            rel_path=rel_path,
            diag_id="quote.cjk_ascii_quote",
            pass_name="quote_style",
            severity="warning",
            status="auto_fixed",
            message="CJK text was wrapped in ASCII double quotes",
            action="none",
            location={"line": line, "column": column},
            before=original,
            after=replacement,
            before_context=before_context,
            after_context=after_context,
        ))
        replacements.append((match.start(), match.end(), replacement))

    if not replacements:
        return None, []

    new_body = body
    for start, end, replacement in reversed(replacements):
        new_body = new_body[:start] + replacement + new_body[end:]
    if frontmatter is None:
        return new_body, diagnostics
    return text[:body_offset] + new_body, diagnostics


def _run_quote_style_autofix(files: list[Path], root: Path) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    diagnostics_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    modified_paths: set[str] = set()
    for path in files:
        result, diagnostics = _quote_style_autofix_file(path, root)
        if result is None:
            continue
        path.write_text(result, encoding="utf-8")
        rel_path = _rel_path(path, root)
        modified_paths.add(rel_path)
        diagnostics_by_path[rel_path].extend(diagnostics)
    return diagnostics_by_path, modified_paths


def _frontmatter_error_action(err: dict[str, Any]) -> tuple[str, str]:
    loc = err.get("loc") or []
    field = loc[0] if loc else None
    if err.get("type") == "missing" and field in {"year", "publisher", "journal", "doi", "isbn"}:
        return "needs_external_evidence", "run_quasi_search"
    if err.get("type") == "missing":
        return "human_review", "human_review"
    return "human_review", "human_review"


def _body_violation_action(violation: dict[str, Any]) -> tuple[str, str, str]:
    kind = violation.get("kind", "body_violation")
    if (
        kind == "block_kind_mismatch"
        and violation.get("h2") == "关键概念"
        and violation.get("expected") == "table"
        and violation.get("detected") in {"definition-list", "paragraph"}
    ):
        return "agent_fixable", "rewrite_section_shape_preserving_content", "error"
    if kind == "missing_required_h2":
        return "agent_fixable", "insert_required_stub", "error"
    if kind in {"heading_level_drift", "global_heading_level_drift", "h2_alias"}:
        return "agent_fixable", "normalize_heading_level", "warning"
    return "human_review", "human_review", "warning"


def _typecheck_diagnostics(results: list[dict[str, Any]], root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str | None]]:
    diagnostics_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    detected_types: dict[str, str | None] = {}

    for result in results:
        rel_path = _result_rel_path(result["path"], root)
        detected_types[rel_path] = result.get("type")

        for err in result.get("frontmatter_errors") or []:
            loc = err.get("loc") or []
            field = loc[0] if loc else None
            status, action = _frontmatter_error_action(err)
            diagnostics_by_path[rel_path].append(_base_diag(
                rel_path=rel_path,
                diag_id=f"frontmatter.{field or 'document'}.{err.get('type', 'error')}",
                pass_name="frontmatter_schema",
                severity="error",
                status=status,
                message=err.get("msg", "frontmatter validation failed"),
                action=action,
                location={"field": field} if field else None,
                raw_error=err,
            ))

        if result.get("type_rename"):
            rename = result["type_rename"]
            diagnostics_by_path[rel_path].append(_base_diag(
                rel_path=rel_path,
                diag_id="frontmatter.type.alias",
                pass_name="frontmatter_schema",
                severity="warning",
                status="agent_fixable",
                message=f"type should be renamed from {rename.get('from')} to {rename.get('to')}",
                action="rewrite_field",
                location={"field": "type"},
                before=rename.get("from"),
                after=rename.get("to"),
            ))

        for violation in result.get("body_violations") or []:
            kind = violation.get("kind", "body_violation")
            h2 = violation.get("h2")
            status, action, severity = _body_violation_action(violation)
            diagnostics_by_path[rel_path].append(_base_diag(
                rel_path=rel_path,
                diag_id=f"body.{h2 or 'document'}.{kind}",
                pass_name="body_schema",
                severity=severity,
                status=status,
                message=json.dumps(violation, ensure_ascii=False, sort_keys=True),
                action=action,
                location={"h2": h2} if h2 else None,
                violation=violation,
            ))

    return diagnostics_by_path, detected_types


def _merge_diagnostics(*items: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        for path, diagnostics in item.items():
            merged[path].extend(diagnostics)
    return merged


def _build_payload(
    *,
    requested_target: str,
    target: Path,
    root: Path,
    results: list[dict[str, Any]],
    diagnostics_by_path: dict[str, list[dict[str, Any]]],
    detected_types: dict[str, str | None],
    modified_paths: set[str],
    fix_counts: dict[str, int],
) -> dict[str, Any]:
    files_payload: list[dict[str, Any]] = []
    all_diagnostics: list[dict[str, Any]] = []
    result_paths = {_result_rel_path(result["path"], root) for result in results}
    for rel_path in sorted(set(diagnostics_by_path) | result_paths):
        diagnostics = diagnostics_by_path.get(rel_path, [])
        if not diagnostics:
            continue
        all_diagnostics.extend(diagnostics)
        files_payload.append({
            "path": rel_path,
            "detected_type": detected_types.get(rel_path),
            "diagnostics": diagnostics,
        })

    auto_fixed = sum(1 for diag in all_diagnostics if diag["status"] == "auto_fixed")
    agent_fixable = sum(1 for diag in all_diagnostics if diag["status"] == "agent_fixable")
    needs_external_evidence = sum(1 for diag in all_diagnostics if diag["status"] == "needs_external_evidence")
    human_required = sum(1 for diag in all_diagnostics if diag["status"] == "human_review")
    by_pass = Counter(diag["pass"] for diag in all_diagnostics)
    status = "clean" if agent_fixable == 0 and needs_external_evidence == 0 and human_required == 0 else "dirty"

    return {
        "version": "quasi-audit.diagnostics.v1",
        "status": status,
        "target": {
            "requested": requested_target,
            "resolved": str(target),
            "exists": target.exists(),
        },
        "summary": {
            "files_checked": len(results),
            "files_modified": len(modified_paths),
            "files_with_diagnostics": len(files_payload),
            "diagnostics_total": len(all_diagnostics),
            "auto_fixed": auto_fixed,
            "agent_fixable": agent_fixable,
            "needs_external_evidence": needs_external_evidence,
            "human_required": human_required,
            "by_pass": dict(by_pass),
            "fix_counts": fix_counts,
        },
        "files": files_payload,
        "artifacts": {
            "typecheck_results": ".quasi/audit/typecheck-results.json",
        },
    }


def _run_audit(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="quasi-audit",
        description="Run diagnostic-first vault audit for agents.",
    )
    ap.add_argument("--path", default="vault", help="File or directory to audit")
    ap.add_argument("--report", choices=["fields"], help="Run an explicit read-only report instead of the default diagnostic audit")
    ap.add_argument("--format", choices=["markdown", "json"], help="Output format for --report fields")
    args = ap.parse_args(argv)

    if args.format is not None and args.report is None:
        ap.error("--format requires --report fields")

    root = _project_root()
    target = _resolve_target(args.path, root)

    if args.report == "fields":
        fd_mod = _load("quasi_audit_field_distribution_run", "scripts/audit/field_distribution.py")
        return fd_mod.run_fields_report(
            requested_path=args.path,
            target=target,
            root=root,
            output_format=args.format or "markdown",
        )

    if not target.exists():
        print_json({
            "version": "quasi-audit.diagnostics.v1",
            "status": "error",
            "target": {
                "requested": args.path,
                "resolved": str(target),
                "exists": False,
            },
            "error": f"path does not exist: {target}",
        })
        return 2

    autofix_mod = _load("quasi_audit_autofix_run", "scripts/typecheck/autofix_mechanical.py")
    fix_result, mechanical_diags, mechanical_modified, files = _run_mechanical_autofix(
        autofix_mod,
        target,
        root,
    )
    quote_diags, quote_modified = _run_quote_style_autofix(files, root)

    typecheck_mod = _load("quasi_audit_typecheck_run", "scripts/typecheck/typecheck.py")
    typecheck_mod.run_typecheck(target, quiet=True, write_report=False)
    results_path = typecheck_mod.OUT_DIR / "typecheck-results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    typecheck_diags, detected_types = _typecheck_diagnostics(results, root)

    diagnostics_by_path = _merge_diagnostics(mechanical_diags, quote_diags, typecheck_diags)
    modified_paths = mechanical_modified | quote_modified
    fix_counts = dict(fix_result["change_counts"])
    if quote_modified:
        fix_counts["quote_style"] = sum(len(items) for items in quote_diags.values())

    payload = _build_payload(
        requested_target=args.path,
        target=target,
        root=root,
        results=results,
        diagnostics_by_path=diagnostics_by_path,
        detected_types=detected_types,
        modified_paths=modified_paths,
        fix_counts=fix_counts,
    )
    print_json(payload)
    return 0 if payload["status"] == "clean" else 1


def main(argv: list[str] | None = None) -> int:
    return _run_audit(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())

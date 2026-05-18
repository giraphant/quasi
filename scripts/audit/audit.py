#!/usr/bin/env python3
"""quasi-audit — agent-facing vault typecheck wrapper.

Single contract:

    quasi-audit --path PATH

The command always runs mechanical autofix, then typecheck, then classifies
residual issues for audit-agent. Stdout is always JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from core import load_script_module, print_json, project_root, resolve_project_path  # noqa: E402

def _project_root() -> Path:
    return project_root()


def _resolve_target(path_arg: str, project_root: Path) -> Path:
    return resolve_project_path(path_arg, project_root)


def _load(module_name: str, relative_path: str):
    """Load a sibling script file as a module without touching sys.path globally."""
    return load_script_module(module_name, PLUGIN_ROOT / relative_path)


def _abs_result_path(path_value: str, project_root: Path) -> str:
    path = Path(path_value)
    if not path.is_absolute():
        path = project_root / path
    return str(path.resolve())


def _violation_count(result: dict) -> int:
    return (
        len(result.get("frontmatter_errors") or [])
        + len(result.get("body_violations") or [])
        + (1 if result.get("type_rename") else 0)
    )


def _run_mechanical_autofix(autofix_mod, target: Path) -> dict:
    files = autofix_mod.collect_files(target)
    modified = 0
    change_counts: Counter[str] = Counter()
    for path in files:
        result = autofix_mod.fix_file(path)
        if result is None:
            continue
        new_text, changes = result
        path.write_text(new_text, encoding="utf-8")
        modified += 1
        for change in changes:
            kind = change.split(":")[0].split("(")[0].split("→")[0].strip().split()[0]
            change_counts[kind] += 1
    return {
        "files_scanned": len(files),
        "files_modified": modified,
        "change_counts": dict(change_counts),
    }


def _classify_results(results: list[dict], project_root: Path) -> tuple[list[dict], list[dict]]:
    """Split residual local-audit issues into agent-editable vs escalated."""
    llm_editable: list[dict] = []
    escalated: list[dict] = []
    for result in results:
        path = _abs_result_path(result["path"], project_root)

        for err in result.get("frontmatter_errors") or []:
            loc = err.get("loc") or []
            field = loc[0] if loc else None
            if err.get("type") == "missing" and field in ("publisher", "isbn", "doi"):
                continue
            if err.get("type") == "missing" and field:
                escalated.append({
                    "path": path,
                    "kind": "missing_required_field",
                    "reason": f"{field} is missing; requires metadata backfill or manual review",
                    "suggested_action": f"run metadata backfill or fill {field} manually",
                })
            else:
                escalated.append({
                    "path": path,
                    "kind": err.get("type", "frontmatter_error"),
                    "reason": err.get("msg", "frontmatter validation failed"),
                    "suggested_action": "manual review",
                })

        if result.get("type_rename"):
            tr = result["type_rename"]
            escalated.append({
                "path": path,
                "kind": "type_rename",
                "reason": f"type should be renamed from {tr.get('from')} to {tr.get('to')}",
                "suggested_action": "run quasi-audit --path <target>",
            })

        for violation in result.get("body_violations") or []:
            kind = violation.get("kind", "body_violation")
            if (
                kind == "block_kind_mismatch"
                and violation.get("h2") == "关键概念"
                and violation.get("expected") == "table"
                and violation.get("detected") == "definition-list"
            ):
                llm_editable.append({
                    "path": path,
                    "kind": kind,
                    "h2": violation.get("h2"),
                    "expected": violation.get("expected"),
                    "detected": violation.get("detected"),
                    "reason": "关键概念 section is definition-list and can be reformatted as table",
                })
            elif kind == "missing_required_h2":
                h2 = violation.get("h2", "?")
                escalated.append({
                    "path": path,
                    "kind": kind,
                    "reason": f"missing whole section {h2}; would require content generation",
                    "suggested_action": "rerun process-book or manually add the missing section",
                })
            else:
                escalated.append({
                    "path": path,
                    "kind": kind,
                    "reason": json.dumps(violation, ensure_ascii=False, sort_keys=True),
                    "suggested_action": "agent review",
                })

    return llm_editable, escalated


def _run_audit(argv: list[str]) -> int:
    """Mechanical autofix + typecheck + residual issue classification."""
    ap = argparse.ArgumentParser(
        prog="quasi-audit",
        description="Run mechanical autofix, typecheck, and emit audit-agent JSON.",
    )
    ap.add_argument("--path", default="vault", help="File or directory to audit")
    args = ap.parse_args(argv)

    root = _project_root()
    target = _resolve_target(args.path, root)
    if not target.exists():
        print_json({
            "status": "error",
            "path": str(target),
            "error": f"path does not exist: {target}",
        })
        return 2

    autofix_mod = _load(
        "quasi_audit_autofix_run",
        "scripts/typecheck/autofix_mechanical.py",
    )
    fix_result = _run_mechanical_autofix(autofix_mod, target)

    typecheck_mod = _load(
        "quasi_audit_typecheck_run",
        "scripts/typecheck/typecheck.py",
    )
    typecheck_mod.run_typecheck(target, quiet=True, write_report=False)
    results_path = typecheck_mod.OUT_DIR / "typecheck-results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))

    remaining = sum(_violation_count(r) for r in results)
    files_with_violations = sum(1 for r in results if _violation_count(r) > 0)
    llm_editable, escalated = _classify_results(results, root)
    status = "clean" if remaining == 0 else "partial"
    summary = {
        "status": status,
        "path": str(target),
        "files_checked": len(results),
        "files_with_violations": files_with_violations,
        "files_modified": fix_result["files_modified"],
        "remaining_violations": remaining,
        "fix_counts": fix_result["change_counts"],
        "llm_editable": llm_editable,
        "escalated": escalated,
        "artifacts": {
            "typecheck_results": ".quasi/audit/typecheck-results.json",
        },
    }

    print_json(summary)
    return 0 if status == "clean" else 1


def main(argv: list[str] | None = None) -> int:
    return _run_audit(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())

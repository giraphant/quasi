#!/usr/bin/env python3
"""quasi-audit — vault audit dispatcher.

Subcommands (each delegates to an existing scripts/* module):

    run       local audit transaction harness (fix/check + state + JSON)
    check     scripts/typecheck/typecheck.py            (vault schema validation)
    fix       scripts/typecheck/autofix_mechanical.py   (mechanical drift fixes)
    emit-bib  scripts/citation/biblio.scan_vault()      (vault → biblio.json)

This file is the L0 entry point for everything in the "vault consistency"
capability domain. agent-side, audit-agent invokes via the quasi-audit shim;
the dispatcher then routes to the appropriate worker module.

Rationale (see plugins/quasi/docs/LAYERS.md):
    - typecheck + autofix-mechanical + (vault-level) biblio emit are all
      forms of "is the vault internally consistent?"
    - they were three separate bins (quasi-typecheck, quasi-autofix-mechanical,
      quasi-citation biblio). this dispatcher unifies them under quasi-audit.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def _project_root() -> Path:
    return Path(
        os.environ.get("QUA_PROJECT_ROOT")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    ).resolve()


def _resolve_target(path_arg: str, project_root: Path) -> Path:
    target = Path(path_arg).expanduser()
    if not target.is_absolute():
        target = project_root / target
    return target.resolve()


def _load(module_name: str, relative_path: str) -> ModuleType:
    """Load a sibling script file as a module without touching sys.path globally."""
    target = PLUGIN_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {target}")
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec so @dataclass and other introspection
    # (which calls sys.modules.get(cls.__module__)) sees the module.
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _delegate(module_name: str, relative_path: str, subcmd: str) -> int:
    """Munge argv so the delegated script sees a clean argv and call its main()."""
    rest = sys.argv[2:]
    sys.argv = [f"quasi-audit {subcmd}", *rest]
    mod = _load(module_name, relative_path)
    main = getattr(mod, "main", None)
    if main is None:
        print(f"error: {relative_path} has no main()", file=sys.stderr)
        return 2
    rc = main()
    return int(rc) if isinstance(rc, int) else 0


def _cmd_emit_bib() -> int:
    """Vault-level biblio emit. Wraps scripts/citation/biblio.scan_vault."""
    import argparse

    ap = argparse.ArgumentParser(
        prog="quasi-audit emit-bib",
        description="Scan vault frontmatter → biblio.json (single source of truth).",
    )
    ap.add_argument(
        "--project-root",
        help="Vault root (default $CLAUDE_PROJECT_DIR / cwd)",
    )
    ap.add_argument(
        "-o", "--output", required=True,
        help="Output biblio.json path",
    )
    args = ap.parse_args(sys.argv[2:])

    biblio_mod = _load("quasi_audit_biblio", "scripts/citation/biblio.py")
    root_str = (
        args.project_root
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    )
    root = Path(root_str).resolve()

    result = biblio_mod.scan_vault(root)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    s = result["summary"]
    print(
        f"biblio: {s['total']} entries "
        f"(papers {s['papers']}, books {s['books']}, "
        f"with-issues {s['with_issues']})"
    )
    print(f"wrote {out}")
    return 0


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
                "suggested_action": "run quasi-audit run --mode fix",
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


def _slug_for_metadata(path: Path, canon_type: str) -> str:
    parts = path.parts
    if canon_type == "book":
        try:
            return parts[parts.index("books") + 1]
        except (ValueError, IndexError):
            return path.parent.name
    return path.stem


def _missing_value(fm: dict, field: str) -> bool:
    value = fm.get(field)
    return value is None or value == "" or value == []


def _scan_needs_backfill(target: Path, typecheck_mod) -> list[dict]:
    """Find deterministic metadata gaps for the separate backfill workflow."""
    needs: list[dict] = []
    for path in typecheck_mod.collect_files(target):
        text = path.read_text(encoding="utf-8")
        fm, _body = typecheck_mod.split_frontmatter(text)
        if not isinstance(fm, dict):
            continue
        canon = typecheck_mod.canonical_type(fm.get("type"))
        if canon == "book":
            missing: list[str] = []
            for field in ("publisher", "isbn"):
                if _missing_value(fm, field):
                    missing.append(field)
            if "cndouban" not in fm or fm.get("cndouban") is None:
                missing.append("cndouban")
            if missing:
                required = {"publisher"}
                qualifier = "" if required.intersection(missing) else "optional "
                needs.append({
                    "path": str(path.resolve()),
                    "slug": _slug_for_metadata(path, canon),
                    "type": canon,
                    "missing": missing,
                    "reason": f"missing {qualifier}metadata fields: {', '.join(missing)}",
                })
        elif canon == "paper":
            missing = [field for field in ("doi",) if _missing_value(fm, field)]
            if missing:
                needs.append({
                    "path": str(path.resolve()),
                    "slug": _slug_for_metadata(path, canon),
                    "type": canon,
                    "missing": missing,
                    "reason": f"missing optional metadata fields: {', '.join(missing)}",
                })

    return needs


def _write_state(project_root: Path, target: Path, mode: str, summary: dict) -> Path:
    state_path = project_root / ".quasi" / "audit" / "audit-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "version": 1,
        "last_audited_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "vault_root": str(target),
        "clean": summary["status"] == "clean",
        "checks": {
            "local": {
                "ran": True,
                "mode": mode,
                "files_checked": summary["files_checked"],
                "files_with_violations": summary["files_with_violations"],
                "files_modified": summary["files_modified"],
                "remaining_violations": summary["remaining_violations"],
            },
            "online": {"ran": False, "strategies": [], "review_files": []},
        },
        "metadata": {
            "complete": not summary.get("needs_backfill"),
            "needs_backfill": summary.get("needs_backfill", []),
        },
        "notes": "local audit run",
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state_path


def _cmd_run() -> int:
    """Local audit transaction harness: mechanical fix/check + state + JSON."""
    ap = argparse.ArgumentParser(
        prog="quasi-audit run",
        description="Run the local audit transaction and emit an agent-readable JSON summary.",
    )
    ap.add_argument("--path", default="vault", help="File or directory to audit")
    ap.add_argument("--mode", choices=["check", "fix"], default="fix")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    ap.add_argument("--limit", type=int, default=0, help="Limit mechanical fixes in fix mode")
    args = ap.parse_args(sys.argv[2:])

    project_root = _project_root()
    target = _resolve_target(args.path, project_root)
    if not target.exists():
        print(f"error: path does not exist: {target}", file=sys.stderr)
        return 2

    fix_result = {"files_scanned": 0, "files_modified": 0, "change_counts": {}}
    if args.mode != "check":
        autofix_mod = _load(
            "quasi_audit_autofix_run",
            "scripts/typecheck/autofix_mechanical.py",
        )
        result = autofix_mod.run_autofix(target, write=True, limit=args.limit)
        fix_result = {
            "files_scanned": result.files_scanned,
            "files_modified": result.files_modified,
            "change_counts": result.change_counts,
        }

    typecheck_mod = _load(
        "quasi_audit_typecheck_run",
        "scripts/typecheck/typecheck.py",
    )
    typecheck_mod.run_typecheck(target, quiet=True, write_report=False)
    results_path = typecheck_mod.OUT_DIR / "typecheck-results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))

    remaining = sum(_violation_count(r) for r in results)
    files_with_violations = sum(1 for r in results if _violation_count(r) > 0)
    llm_editable, escalated = _classify_results(results, project_root)
    needs_backfill = _scan_needs_backfill(target, typecheck_mod)
    status = "clean" if remaining == 0 else "partial"
    summary = {
        "status": status,
        "path": str(target),
        "mode": args.mode,
        "files_checked": len(results),
        "files_with_violations": files_with_violations,
        "files_modified": fix_result["files_modified"],
        "remaining_violations": remaining,
        "fix_counts": fix_result["change_counts"],
        "llm_editable": llm_editable,
        "needs_backfill": needs_backfill,
        "escalated": escalated,
        "artifacts": {
            "typecheck_results": ".quasi/audit/typecheck-results.json",
            "state": ".quasi/audit/audit-state.json",
        },
    }
    _write_state(project_root, target, args.mode, summary)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"audit run: {status}; {len(results)} files checked; "
            f"{fix_result['files_modified']} modified; {remaining} remaining violations"
        )
    return 0 if status == "clean" else 1


def _print_help() -> int:
    sys.stdout.write(__doc__ or "")
    sys.stdout.write(
        "\n"
        "Usage:\n"
        "  quasi-audit run       [--path FILE_OR_DIR] [--mode check|fix] [--json]\n"
        "  quasi-audit check     [--path FILE_OR_DIR] [--quiet]\n"
        "  quasi-audit fix       [--path FILE_OR_DIR] [--write] [--limit N]\n"
        "  quasi-audit emit-bib  -o PATH [--project-root DIR]\n"
        "  quasi-audit backfill  --strategy STRATEGY [-- ARGS_TO_SWEEP_SCRIPT...]\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is not None:
        sys.argv = ["quasi-audit", *argv]

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        return _print_help()

    subcmd = sys.argv[1]

    if subcmd == "run":
        return _cmd_run()
    if subcmd == "check":
        return _delegate(
            "quasi_audit_check",
            "scripts/typecheck/typecheck.py",
            "check",
        )
    if subcmd == "fix":
        return _delegate(
            "quasi_audit_fix",
            "scripts/typecheck/autofix_mechanical.py",
            "fix",
        )
    if subcmd == "emit-bib":
        return _cmd_emit_bib()

    if subcmd == "backfill":
        import argparse as _ap
        _STRATEGIES = [
            "auto", "clean", "crossref", "aa-title", "aa-md5",
            "aa-from-slug", "openalex", "ol-search", "ol-isbn-reverse",
        ]
        bp = _ap.ArgumentParser(
            prog="quasi-audit backfill",
            description="Run vault metadata backfill sweep scripts.",
        )
        bp.add_argument(
            "--strategy",
            required=True,
            choices=_STRATEGIES,
            help="Backfill strategy (or 'auto' to run the default chain)",
        )
        bp.add_argument(
            "extra",
            nargs=_ap.REMAINDER,
            help="Extra args forwarded to the sweep script (use -- to separate)",
        )
        bargs = bp.parse_args(sys.argv[2:])
        from backfill import run_backfill
        extra = bargs.extra or []
        if extra and extra[0] == "--":
            extra = extra[1:]
        sys.exit(run_backfill(bargs.strategy, extra))

    print(f"quasi-audit: unknown subcommand: {subcmd}", file=sys.stderr)
    _print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

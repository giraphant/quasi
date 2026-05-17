#!/usr/bin/env python3
"""quasi-audit — vault audit dispatcher.

Subcommands (each delegates to an existing scripts/* module):

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

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


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


def _print_help() -> int:
    sys.stdout.write(__doc__ or "")
    sys.stdout.write(
        "\n"
        "Usage:\n"
        "  quasi-audit check     [--path FILE_OR_DIR] [--quiet]\n"
        "  quasi-audit fix       [--path FILE_OR_DIR] [--write] [--limit N]\n"
        "  quasi-audit emit-bib  -o PATH [--project-root DIR]\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is not None:
        sys.argv = ["quasi-audit", *argv]

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        return _print_help()

    subcmd = sys.argv[1]

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

    print(f"quasi-audit: unknown subcommand: {subcmd}", file=sys.stderr)
    _print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

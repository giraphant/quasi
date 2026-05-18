#!/usr/bin/env python3
"""quasi-citation — citation pipeline for quasi drafts.

Subcommands (each is a discrete step; orchestration lives in the wrap-up skill,
NOT in this CLI):

    biblio       scan vault → biblio.json
    parse        draft.md → parse.json (citations + mentions)
    resolve      parse.json + biblio.json → manifest.json (single/multi/miss)
    render       manifest.json (+ verdicts/) → review.html
    emit-bib     manifest.json + biblio.json (+ decisions.json) → references.bib

Conventions:
    project root  = $CLAUDE_PROJECT_DIR (or --project-root)
    intermediates = {root}/.quasi/citation/{draft-stem}/
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow direct `python citation.py` invocation as well as via shim.
sys.path.insert(0, str(Path(__file__).parent))

import biblio as biblio_mod        # noqa: E402
import parse as parse_mod          # noqa: E402
import resolve as resolve_mod      # noqa: E402
import render as render_mod        # noqa: E402
import emit_bib as emit_bib_mod    # noqa: E402


def _project_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def _resolve_draft_paths(input_paths: list[str], root: Path) -> list[Path]:
    out: list[Path] = []
    for p in input_paths:
        path = (root / p).resolve() if not Path(p).is_absolute() else Path(p)
        if path.is_dir():
            out.extend(sorted(path.rglob("*.md")))
        elif path.is_file():
            out.append(path)
        else:
            print(f"warn: skip non-existent {p}", file=sys.stderr)
    return out


def _json_dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ---- subcommands -------------------------------------------------------------

def cmd_biblio(args) -> int:
    root = _project_root(args.project_root)
    out = Path(args.output)
    biblio = biblio_mod.scan_vault(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json_dump(biblio), encoding="utf-8")
    s = biblio["summary"]
    print(f"biblio: {s['total']} entries "
          f"(papers {s['papers']}, books {s['books']}, "
          f"with-issues {s['with_issues']})")
    print(f"wrote {out}")
    return 0


def cmd_parse(args) -> int:
    root = _project_root(args.project_root)
    paths = _resolve_draft_paths(args.paths, root)
    if not paths:
        print("error: no draft files found", file=sys.stderr)
        return 2
    data = parse_mod.parse_files(paths, root)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json_dump(data), encoding="utf-8")
    s = data["summary"]
    print(f"parsed {s['files']} file(s): "
          f"{s['unique_citations']} unique, "
          f"{s['structured_spans']} spans, "
          f"{s['uncovered_spans']} uncovered")
    print(f"wrote {out}")
    return 0


def cmd_resolve(args) -> int:
    parse_data = json.loads(Path(args.parse_json).read_text(encoding="utf-8"))
    biblio = json.loads(Path(args.biblio).read_text(encoding="utf-8"))
    manifest = resolve_mod.resolve_citations(parse_data, biblio)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json_dump(manifest), encoding="utf-8")
    s = manifest["summary"]
    parts = [f"total {s['total']}"]
    for k in ("single-hit", "multi-hit", "miss"):
        if k in s:
            parts.append(f"{k} {s[k]}")
    print("  " + " · ".join(parts))
    print(f"wrote {out}")
    return 0


def cmd_render(args) -> int:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    verdicts_dir = Path(args.verdicts) if args.verdicts else None
    text = render_mod.render_html(manifest, verdicts_dir, args.source_label)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


def cmd_emit_bib(args) -> int:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    biblio = json.loads(Path(args.biblio).read_text(encoding="utf-8"))
    decisions = None
    if args.decisions:
        decisions = json.loads(Path(args.decisions).read_text(encoding="utf-8"))
    text, counts = emit_bib_mod.emit_bib(manifest, biblio, decisions)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"emitted {counts['emitted']} entries"
          + (f" / {counts['skeleton']} skeleton" if counts["skeleton"] else "")
          + (f" / {counts['new_pending']} new-pending" if counts["new_pending"] else ""))
    print(f"wrote {out}")
    return 0


# ---- main --------------------------------------------------------------------

def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="quasi-citation",
        description="Citation pipeline for quasi drafts. "
                    "Orchestration lives in the wrap-up skill, not in this CLI.")
    ap.add_argument("--project-root", help="Vault root (default $CLAUDE_PROJECT_DIR / cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_bib = sub.add_parser("biblio", help="Scan vault → biblio.json")
    p_bib.add_argument("-o", "--output", required=True)
    p_bib.set_defaults(func=cmd_biblio)

    p_parse = sub.add_parser("parse", help="Extract citations → parse.json")
    p_parse.add_argument("paths", nargs="+")
    p_parse.add_argument("-o", "--output", required=True)
    p_parse.set_defaults(func=cmd_parse)

    p_res = sub.add_parser("resolve", help="parse.json + biblio.json → manifest.json")
    p_res.add_argument("parse_json")
    p_res.add_argument("--biblio", required=True, help="biblio.json (from `biblio`)")
    p_res.add_argument("-o", "--output", required=True)
    p_res.set_defaults(func=cmd_resolve)

    p_ren = sub.add_parser("render", help="manifest.json (+ verdicts/) → review HTML")
    p_ren.add_argument("manifest")
    p_ren.add_argument("--verdicts", help="Directory of batch-*.json verdicts")
    p_ren.add_argument("-o", "--output", required=True, help="review HTML path")
    p_ren.add_argument("--source-label", default="draft")
    p_ren.set_defaults(func=cmd_render)

    p_eb = sub.add_parser("emit-bib", help="biblio + manifest (+ decisions) → references.bib")
    p_eb.add_argument("manifest")
    p_eb.add_argument("--biblio", required=True)
    p_eb.add_argument("--decisions", help="Optional decisions.json from review HTML export")
    p_eb.add_argument("-o", "--output", required=True)
    p_eb.set_defaults(func=cmd_emit_bib)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

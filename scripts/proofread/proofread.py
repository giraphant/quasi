#!/usr/bin/env python3
"""quasi-proofread — orchestration helpers for the proofread-agent.

The agent does the actual editing. This script provides the deterministic
pieces around it:

    split           draft.md → sections.json      (主进程 dispatch 时用)
    merge-records   sidecar/*.records.md → 合并到 draft 末尾 <!-- proofread:* --> 块
    cleanup         审完后从 draft 删除整个记录块(保留正文)

No "run" subcommand — agent dispatch happens in the Claude main loop, this
Python script can't summon agents. The wrap-up skill (or any main loop) calls
split → dispatches agents → calls merge-records → (审完触发) cleanup.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


# ---- section splitting -------------------------------------------------------

# We split on H2 (##) by default. H3 (###) can be either subordinated to its
# parent H2 or split out — controlled by --depth. Default keeps H3 inside.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class Section:
    id: str               # filename-safe, NN-slug
    heading: str          # raw heading text
    level: int            # 1..6
    start_line: int       # 1-indexed, inclusive (heading line)
    end_line: int         # 1-indexed, inclusive (last line of section body)


def _slug(s: str, maxlen: int = 40) -> str:
    """Stable filename-safe slug from a heading. Keeps CJK as-is."""
    s = re.sub(r"\s+", "-", s.strip())
    # Drop characters that are unsafe in filenames; keep CJK + alnum + hyphen
    s = re.sub(r"[\\/:*?\"<>|`#]+", "", s)
    s = s.strip("-")
    return s[:maxlen] or "section"


def split_sections(text: str, depth: int = 2) -> list[Section]:
    """Walk the markdown and slice at heading levels ≤ depth.

    Lines before the first qualifying heading become a synthetic
    `00-preamble` section so nothing gets dropped.
    """
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []  # (line_idx_0, level, text)
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        if level <= depth:
            headings.append((i, level, m.group(2)))

    sections: list[Section] = []

    # Preamble (anything before first heading)
    first_idx = headings[0][0] if headings else len(lines)
    if first_idx > 0 and any(line.strip() for line in lines[:first_idx]):
        sections.append(Section(
            id="00-preamble",
            heading="(preamble)",
            level=0,
            start_line=1,
            end_line=first_idx,
        ))

    for k, (idx, level, htext) in enumerate(headings):
        end = headings[k + 1][0] - 1 if k + 1 < len(headings) else len(lines) - 1
        nn = f"{k + 1:02d}"
        sections.append(Section(
            id=f"{nn}-{_slug(htext)}",
            heading=htext,
            level=level,
            start_line=idx + 1,        # convert to 1-indexed inclusive
            end_line=end + 1,
        ))

    return sections


def cmd_split(args) -> int:
    draft = Path(args.draft).resolve()
    text = draft.read_text(encoding="utf-8")
    sections = split_sections(text, depth=args.depth)

    out = {
        "draft": str(draft),
        "total_lines": len(text.splitlines()),
        "depth": args.depth,
        "sections": [asdict(s) for s in sections],
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"split into {len(sections)} section(s) (depth={args.depth}):")
    for s in sections:
        n = s.end_line - s.start_line + 1
        print(f"  {s.id:50s}  L{s.start_line:>4}-{s.end_line:<4} ({n} lines)")
    print(f"\nwrote {out_path}")
    return 0



# Records block markers — used by init and cleanup to locate the block.
_RECORDS_START = "<!-- proofread:start -->"
_RECORDS_END = "<!-- proofread:end -->"
_RECORDS_HEADING = "## 校对记录（审完整段删除）"


def ensure_records_block(draft: Path) -> bool:
    """Make sure the draft has an empty records block at the very end.
    Returns True if a block was added, False if one already existed.
    """
    text = draft.read_text(encoding="utf-8")
    if _RECORDS_START in text and _RECORDS_END in text:
        return False
    sep = "" if text.endswith("\n") else "\n"
    block = (f"{sep}\n\n"
             f"{_RECORDS_START}\n"
             f"{_RECORDS_HEADING}\n\n"
             f"{_RECORDS_END}\n")
    draft.write_text(text + block, encoding="utf-8")
    return True


def cmd_init(args) -> int:
    draft = Path(args.draft).resolve()
    if not draft.is_file():
        print(f"error: draft not found: {draft}", file=sys.stderr)
        return 2
    if ensure_records_block(draft):
        print(f"  inited records block in {draft.name}")
    else:
        print(f"  records block already exists in {draft.name}")
    return 0


# ---- cleanup (delete records block post-review) ------------------------------

def remove_records_block(draft: Path) -> bool:
    """从 draft 文件删除 <!-- proofread:start --> ... <!-- proofread:end --> 块。
    返回 True 表示删除了块,False 表示没找到块(无操作)。
    """
    text = draft.read_text(encoding="utf-8")
    start_idx = text.find(_RECORDS_START)
    if start_idx < 0:
        return False
    end_idx = text.find(_RECORDS_END, start_idx)
    if end_idx < 0:
        # 异常状态:有 start 没 end,只删到 start 之前
        new_text = text[:start_idx].rstrip() + "\n"
    else:
        end_idx += len(_RECORDS_END)
        new_text = (text[:start_idx].rstrip()
                    + text[end_idx:].lstrip())
        if not new_text.endswith("\n"):
            new_text += "\n"
    draft.write_text(new_text, encoding="utf-8")
    return True


def cmd_cleanup(args) -> int:
    targets: list[Path] = []
    for p in args.paths:
        path = Path(p).resolve()
        if path.is_dir():
            targets.extend(sorted(path.rglob("*.md")))
        elif path.is_file():
            targets.append(path)
        else:
            print(f"warn: skip non-existent {p}", file=sys.stderr)
    if not targets:
        print("error: no markdown files found", file=sys.stderr)
        return 2
    n_cleaned = 0
    for draft in targets:
        if remove_records_block(draft):
            n_cleaned += 1
            print(f"  cleaned {draft.relative_to(Path.cwd()) if draft.is_relative_to(Path.cwd()) else draft}")
    print(f"\ncleaned {n_cleaned}/{len(targets)} file(s)")
    return 0


# ---- entrypoint --------------------------------------------------------------

def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="quasi-proofread",
        description="Section splitting + post-review cleanup. "
                    "The proofread-agent edits draft in-place — no sidecars.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_split = sub.add_parser("split", help="draft.md → sections.json")
    p_split.add_argument("draft")
    p_split.add_argument("--depth", type=int, default=3,
                         help="Split at heading levels ≤ depth (default 3 — "
                              "## draft title + ### sections)")
    p_split.add_argument("-o", "--output", required=True)
    p_split.set_defaults(func=cmd_split)

    p_init = sub.add_parser(
        "init",
        help="确保 draft 末尾有空的 <!-- proofread:start --> 块(供 agent 追加)")
    p_init.add_argument("draft", help="draft 文件绝对或相对路径")
    p_init.set_defaults(func=cmd_init)

    p_cleanup = sub.add_parser(
        "cleanup",
        help="审阅完成后,从 draft 删除整个 <!-- proofread:start --> ... "
             "<!-- proofread:end --> 块(可批量传目录)")
    p_cleanup.add_argument("paths", nargs="+",
                           help="draft 文件或目录")
    p_cleanup.set_defaults(func=cmd_cleanup)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

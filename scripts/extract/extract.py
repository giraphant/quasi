#!/usr/bin/env python3
"""quasi-extract — file → MD pipeline.

This is the unified extraction entrypoint. Worker scripts stay as sibling
implementation files, but callers route through this file via bin/quasi-extract.

    epub   process_epub.py        EPUB → chapter md
    ocr    ocr_pdf.sh             PDF → searchable PDF (OCR)
    split  split_chapters.py      PDF → per-chapter files (by TOC / pages)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


HELP = """\
quasi-extract — file → MD pipeline.

Usage:
  quasi-extract epub  SOURCE_EPUB CHAPTERS_DIR
  quasi-extract ocr   INPUT.pdf [OUTPUT.pdf] [LANGUAGE]
  quasi-extract split INPUT.pdf --output-dir DIR
                                [--max-chapters N]
                                [--chapters JSON]
                                [--pages RANGE --title T]

Each subcommand has its own --help with full args:
  quasi-extract epub --help
  quasi-extract ocr --help
  quasi-extract split --help
"""


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        sys.stdout.write(HELP)
        return 0

    here = Path(__file__).resolve().parent
    subcmd, rest = sys.argv[1], sys.argv[2:]
    if subcmd == "epub":
        return subprocess.call([sys.executable, str(here / "process_epub.py"), *rest])
    if subcmd == "ocr":
        return subprocess.call(["bash", str(here / "ocr_pdf.sh"), *rest])
    if subcmd == "split":
        return subprocess.call([sys.executable, str(here / "split_chapters.py"), *rest])

    print(f"quasi-extract: unknown subcommand: {subcmd}", file=sys.stderr)
    print("valid subcommands: epub | ocr | split", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

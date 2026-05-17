#!/usr/bin/env python3
"""quasi-extract — file → MD pipeline.

Subcommands (each is dispatched by the bin/quasi-extract shim to a
sibling worker, so this file exists only for `--help` discoverability):

    epub   process_epub.py        EPUB → chapter md
    ocr    ocr_pdf.sh             PDF → searchable PDF (OCR)
    split  split_chapters.py      PDF → per-chapter files (by TOC / pages)
"""
from __future__ import annotations

import sys


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
    # Subcommand dispatch happens in the bin/quasi-extract bash shim
    # (cheaper than re-execing python for OCR which is a bash script).
    # If someone runs this python file directly with a subcmd, route them.
    print(
        f"quasi-extract: invoke via bin/quasi-extract shim, not this script "
        f"directly (subcommand {sys.argv[1]!r} not handled here).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())

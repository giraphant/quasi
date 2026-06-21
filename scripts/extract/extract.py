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
  quasi-extract ocr   INPUT.pdf [OUTPUT.pdf] [LANGUAGE] [--engine dsocr2|tesseract]
  quasi-extract split INPUT.pdf --output-dir DIR
                                [--max-chapters N]
                                [--chapters JSON]
                                [--pages RANGE --title T]

Each subcommand has its own --help with full args:
  quasi-extract epub --help
  quasi-extract ocr --help
  quasi-extract split --help
"""


def _run_ocr(here: Path, rest: list[str]) -> int:
    """Dispatch `quasi-extract ocr` to an OCR engine.

    `--engine dsocr2` (default, DeepSeek-OCR-2 via mlx-vlm) | `tesseract`
    (ocrmypdf). dsocr2 auto-falls-back to tesseract if it is unavailable or
    fails, so OCR still works on machines without MLX or the model.
    """
    engine = "dsocr2"
    positional: list[str] = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--engine":
            if i + 1 >= len(rest):
                print("quasi-extract ocr: --engine requires a value (dsocr2|tesseract)", file=sys.stderr)
                return 2
            engine = rest[i + 1]
            i += 2
        elif a.startswith("--engine="):
            engine = a.split("=", 1)[1]
            i += 1
        elif a in ("-h", "--help"):
            print("Usage: quasi-extract ocr INPUT.pdf [OUTPUT.pdf] [LANGUAGE] [--engine dsocr2|tesseract]")
            print("Default engine: dsocr2 (DeepSeek-OCR-2). Falls back to tesseract if unavailable.")
            return 0
        else:
            positional.append(a)
            i += 1

    if engine not in ("dsocr2", "tesseract"):
        print(f"quasi-extract ocr: unknown engine '{engine}' (expected dsocr2|tesseract)", file=sys.stderr)
        return 2

    if engine == "tesseract":
        return subprocess.call(["bash", str(here / "ocr_pdf.sh"), *positional])

    # dsocr2 needs an explicit output path (ocr_pdf.sh auto-generates one).
    if len(positional) < 2:
        if not positional:
            print("Usage: quasi-extract ocr INPUT.pdf [OUTPUT.pdf] [LANGUAGE] [--engine dsocr2|tesseract]", file=sys.stderr)
            return 2
        stem = positional[0][: -len(".pdf")] if positional[0].lower().endswith(".pdf") else positional[0]
        positional.append(f"{stem}_ocr.pdf")

    rc = subprocess.call([sys.executable, str(here / "ocr_dsocr2.py"), *positional])
    if rc == 0:
        return 0
    sys.stderr.write("[extract] DS OCR2 unavailable/failed; falling back to tesseract.\n")
    return subprocess.call(["bash", str(here / "ocr_pdf.sh"), *positional])


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        sys.stdout.write(HELP)
        return 0

    here = Path(__file__).resolve().parent
    subcmd, rest = sys.argv[1], sys.argv[2:]
    if subcmd == "epub":
        return subprocess.call([sys.executable, str(here / "process_epub.py"), *rest])
    if subcmd == "ocr":
        return _run_ocr(here, rest)
    if subcmd == "split":
        return subprocess.call([sys.executable, str(here / "split_chapters.py"), *rest])

    print(f"quasi-extract: unknown subcommand: {subcmd}", file=sys.stderr)
    print("valid subcommands: epub | ocr | split", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

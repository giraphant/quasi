#!/usr/bin/env python3
"""Detect silently under-translated BabelDOC output.

Both quasi translate backends can return a structurally perfect bilingual PDF —
right page count, exit 0, not one warning — that is missing most of its body
text. It happens when the source PDF's text layer is fragmented enough that
BabelDOC's layout model stops recognising paragraphs as translatable blocks, so
it leaves them as untouched scan. The page-count gate cannot see it.

Measured across three healthy runs and one bad one, translated Han characters
per source Latin letter separates them cleanly: 0.30-0.36 on every healthy page,
0.15 median (0.01 at worst) on a book that came out only 43% translated.

Run it only on a PDF whose ToUnicode CMap is already repaired: an unrepaired book
extracts as mojibake in the CJK extension-A block, which this counter deliberately
does not count, so a healthy 400-page book scores 0.17. Run tounicode.py first when
auditing an old file by hand; both backends already call these two in that order.
"""

from __future__ import annotations

import statistics
import sys
import tempfile
from pathlib import Path

import pymupdf

# Healthy pages sat at 0.30-0.36 across three books; the half-translated one had
# a 0.15 median. 0.22 leaves room on both sides. Retune here if a font stack or
# a language pair moves it.
MIN_MEDIAN = 0.22
# Under this a page is a figure, a plate or a title and its ratio is noise.
MIN_SOURCE_CHARS = 200
# One or two measurable pages establish nothing.
MIN_PAGES = 3


def _latin(text: str) -> int:
    return sum(c.isascii() and c.isalpha() for c in text)


def _han(text: str) -> int:
    return sum("一" <= c <= "鿿" for c in text)


def page_ratios(pdf_path: Path) -> list[tuple[int, float]]:
    """(book page number, translated Han per source Latin letter) for each spread.

    The dual PDF alternates original/translated, so pages 2i and 2i+1 are the two
    sides of one book page. Pages carrying too little source text are dropped
    rather than scored — a plate would otherwise read as a translation failure.
    """
    doc = pymupdf.open(str(pdf_path))
    try:
        ratios = []
        for i in range(0, len(doc) - 1, 2):
            source = _latin(doc[i].get_text())
            if source < MIN_SOURCE_CHARS:
                continue
            ratios.append((i // 2 + 1, _han(doc[i + 1].get_text()) / source))
    finally:
        doc.close()
    return ratios


def check(pdf_path: Path, *, target_language: str = "zh-CN") -> dict[str, object]:
    """Report whether an alternating bilingual PDF carries a full translation."""
    if not target_language.lower().startswith("zh"):
        # The ratio counts Han characters, so kana, hangul and Latin targets would
        # all score zero. ponytail: recalibrate per language if one gets used.
        return {"ok": True, "detail": f"coverage check skipped: target {target_language} is not Chinese"}

    ratios = page_ratios(pdf_path)
    if len(ratios) < MIN_PAGES:
        return {
            "ok": True,
            "detail": f"coverage check skipped: only {len(ratios)} page(s) carry enough source text",
        }

    median = statistics.median(ratio for _, ratio in ratios)
    worst = ", ".join(f"p{page}={ratio:.2f}" for page, ratio in sorted(ratios, key=lambda pr: pr[1])[:5])
    if median >= MIN_MEDIAN:
        return {
            "ok": True,
            "median": median,
            "detail": f"coverage {median:.2f} over {len(ratios)} pages (weakest {worst})",
        }
    return {
        "ok": False,
        "median": median,
        "detail": (
            f"Under-translated: {median:.2f} Chinese characters per source letter over "
            f"{len(ratios)} pages, expected at least {MIN_MEDIAN:.2f}. BabelDOC skipped body "
            f"text it did not recognise as paragraphs, which usually means the source's own "
            f"text layer is fragmented. Weakest pages: {worst}. Re-OCR the source with "
            f"`quasi-extract ocr SRC OUT --layout` and translate that instead. "
            f"Output kept at {pdf_path}."
        ),
    }


def build_dual(path: Path, translated: list[str]) -> Path:
    """A minimal alternating dual PDF: one full English page per translated page."""
    doc = pymupdf.open()
    box = pymupdf.Rect(20, 20, 400, 700)
    for han in translated:
        doc.new_page().insert_textbox(box, "the shape of actions " * 20, fontsize=9)
        doc.new_page().insert_textbox(box, han, fontsize=9, fontname="china-s")
    doc.save(str(path))
    doc.close()
    return path


def demo() -> None:
    """Self-check: a healthy book passes, a mostly-skipped one does not."""
    full = "行动的形状是什么样的 " * 12
    with tempfile.TemporaryDirectory() as tmp:
        good = build_dual(Path(tmp) / "good.pdf", [full] * 4)
        # One dead page out of four must NOT fail the book — the gate is a median,
        # so a stray figure page cannot reject an otherwise complete translation.
        assert check(good)["ok"]
        assert page_ratios(build_dual(Path(tmp) / "one.pdf", [full] * 3 + [""]))[3][1] == 0.0
        assert check(Path(tmp) / "one.pdf")["ok"]

        bad = build_dual(Path(tmp) / "bad.pdf", [full] + [""] * 3)
        assert not check(bad)["ok"]
        # Same document, non-Chinese target: Han counting says nothing, so no verdict.
        assert check(bad, target_language="fr")["ok"]
        # Too short to conclude anything either way.
        assert check(build_dual(Path(tmp) / "short.pdf", ["", ""]))["ok"]
    print("ok")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv == ["--self-check"]:
        demo()
        raise SystemExit(0)
    if not argv:
        print("usage: coverage.py FILE.pdf [FILE.pdf ...] | --self-check", file=sys.stderr)
        raise SystemExit(2)
    failed = 0
    for target in argv:
        report = check(Path(target))
        failed += not report["ok"]
        print(f"{target}: {report['detail']}")
    raise SystemExit(1 if failed else 0)

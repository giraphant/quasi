#!/usr/bin/env python3
"""Detect silently under-translated BabelDOC output.

Both quasi translate backends can return a structurally perfect bilingual PDF —
right page count, exit 0, not one warning — that is missing most of its body
text. It happens when the source PDF's text layer is fragmented enough that
BabelDOC's layout model stops recognising paragraphs as translatable blocks, so
it leaves them as untouched scan. The page-count gate cannot see it.

Translated Han characters per source Latin letter flags large omissions, but
bibliographies, indexes and endnotes can legitimately retain much English.
Exclude sections supported by the source's outline or bounded note headings;
never infer a page's kind from a low translation ratio. This tests body coverage,
not the quality or completeness of the excluded reference material.

Run it only on a PDF whose ToUnicode CMap is already repaired: an unrepaired book
extracts as mojibake in the CJK extension-A block, which this counter deliberately
does not count, so a healthy 400-page book scores 0.17. Run tounicode.py first when
auditing an old file by hand; both backends already call these two in that order.
"""

from __future__ import annotations

import re
import statistics
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf

# Keep the body threshold: the old 0.22 admitted an incomplete 0.23 translation.
MIN_MEDIAN = 0.30
# A healthy median can hide many effectively untranslated body pages. These
# thresholds apply only to the measurable source pages, never plates/titles.
NEAR_ZERO_RATIO = 0.05
MAX_NEAR_ZERO_FRACTION = 0.10
# Under this a page is a figure, a plate or a title and its ratio is noise.
MIN_SOURCE_CHARS = 200
# One or two measurable pages establish nothing.
MIN_PAGES = 3


def _latin(text: str) -> int:
    return sum(c.isascii() and c.isalpha() for c in text)


def _han(text: str) -> int:
    return sum("一" <= c <= "鿿" for c in text)


@dataclass(frozen=True)
class Section:
    # One-based source-book pages, stop exclusive (not dual PDF page numbers).
    start: int
    stop: int
    kind: str
    evidence: str


def _section_kind(title: str) -> str | None:
    title = " ".join(title.casefold().split()).strip(" .:")
    if title in {"bibliography", "selected bibliography", "references", "works cited"}:
        return "references"
    if title in {"index", "general index", "subject index", "name index", "index of names"}:
        return "index"
    if title in {"notes", "endnotes", "end notes", "chapter notes"}:
        return "notes"
    return None


def _source_sections(doc: pymupdf.Document, source_text: list[str]) -> list[Section]:
    """Conservative source-only evidence; ambiguous outlines exempt nothing.

    Explicit reference sections end at the next sibling/ancestor bookmark.
    Unbookmarked Notes headings need numbered entries 1 and 2, and a later
    bookmark to bound their continuation. Their opening page stays measurable:
    it may still contain the end of the chapter's body.
    """
    toc = doc.get_toc()
    if not toc or any(
        not 1 <= page <= 2 * len(source_text) or level < 1 for level, _, page in toc
    ):
        return []
    outline = [(level, title, (page + 1) // 2) for level, title, page in toc]
    if any(a[2] > b[2] for a, b in zip(outline, outline[1:])):
        return []
    sections = []
    for i, (level, title, start) in enumerate(outline):
        kind = _section_kind(title)
        if kind is None:
            continue
        stop = next(
            (page for next_level, _, page in outline[i + 1:] if next_level <= level),
            len(source_text) + 1,
        )
        # A bookmark can target the bottom of a mixed body/reference page.
        # Uncertain extraction order also errs toward retaining that page.
        lines = source_text[start - 1].splitlines()
        for j, line in enumerate(lines):
            if _section_kind(line) == kind:
                if _latin("\n".join(lines[:j])) >= MIN_SOURCE_CHARS:
                    start += 1
                break
        if start < stop:
            sections.append(Section(start, stop, kind, f"outline {title!r}"))

    boundaries = sorted({page for _, _, page in outline})
    for page, text in enumerate(source_text, 1):
        if any(section.start <= page < section.stop for section in sections):
            continue
        # No inferred range without both a containing section and a known end.
        if page < boundaries[0]:
            continue
        stop = next((boundary for boundary in boundaries if boundary > page), None)
        if stop is None or stop <= page + 1:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if _section_kind(line) != "notes":
                continue
            numbers = re.findall(r"^\s*(\d{1,3})[.)]\s+\S", "\n".join(lines[i + 1:]), re.M)
            if numbers[:2] == ["1", "2"]:
                sections.append(Section(page + 1, stop, "notes", f"numbered Notes heading p{page}"))
                break
    return sorted(sections, key=lambda section: section.start)


def _measure(pdf_path: Path) -> tuple[list[tuple[int, float]], list[Section]]:
    with pymupdf.open(str(pdf_path)) as doc:
        source_text = []
        ratios = []
        for i in range(0, len(doc) - 1, 2):
            # OCR content streams need not follow visual reading order. Use
            # positioned blocks for headings, preserving the original counter.
            # Full sorted-text reconstruction is needlessly costly on books.
            source_text.append("\n".join(
                block[4] for block in doc[i].get_text("blocks", sort=True) if block[6] == 0
            ))
            source = _latin(doc[i].get_text())
            if source >= MIN_SOURCE_CHARS:
                ratios.append((i // 2 + 1, _han(doc[i + 1].get_text()) / source))
        return ratios, _source_sections(doc, source_text)


def page_ratios(pdf_path: Path) -> list[tuple[int, float]]:
    """Unfiltered (book page, translated Han per source Latin letter) pairs.

    The dual PDF alternates original/translated, so pages 2i and 2i+1 are the two
    sides of one book page. Pages carrying too little source text are dropped
    rather than scored — a plate would otherwise read as a translation failure.
    """
    return _measure(pdf_path)[0]


def _body_ratios(
    ratios: list[tuple[int, float]], sections: list[Section],
) -> tuple[list[tuple[int, float]], str]:
    excluded = {
        page: next((s for s in sections if s.start <= page < s.stop), None)
        for page, _ in ratios
    }
    body = [(page, ratio) for page, ratio in ratios if excluded[page] is None]
    if len(body) == len(ratios):
        return ratios, ""
    # Exemptions must not turn an otherwise measurable failure into abstention.
    if len(body) < MIN_PAGES:
        return ratios, (
            f" Section exclusions not applied: only {len(body)} body page(s) remain; "
            "using all measurable pages."
        )
    evidence = "; ".join(
        f"p{s.start}-{s.stop - 1} {s.kind} ({s.evidence})"
        for s in sections if s in excluded.values()
    )
    raw_median = statistics.median(ratio for _, ratio in ratios)
    return body, (
        f" Body scope: excluded {len(ratios) - len(body)}/{len(ratios)} measurable "
        f"reference pages; unfiltered median {raw_median:.3f}; {evidence}. "
        "Excluded sections are not translation-validated."
    )


def check(pdf_path: Path, *, target_language: str = "zh-CN") -> dict[str, object]:
    """Report whether an alternating bilingual PDF carries a full translation."""
    if not target_language.lower().startswith("zh"):
        # The ratio counts Han characters, so kana, hangul and Latin targets would
        # all score zero. ponytail: recalibrate per language if one gets used.
        return {
            "ok": True,
            "signal": "not_applicable",
            "median": None,
            "measured_pages": 0,
            "minimum_median": MIN_MEDIAN,
            "weakest": [],
            "detail": f"coverage check skipped: target {target_language} is not Chinese",
        }

    ratios, sections = _measure(pdf_path)
    ratios, scope = _body_ratios(ratios, sections)
    if len(ratios) < MIN_PAGES:
        return {
            "ok": True,
            "signal": "insufficient_evidence",
            "median": None,
            "measured_pages": len(ratios),
            "minimum_median": MIN_MEDIAN,
            "weakest": [
                {"page": page, "ratio": ratio}
                for page, ratio in sorted(ratios, key=lambda item: item[1])[:5]
            ],
            "detail": f"coverage check skipped: only {len(ratios)} page(s) carry enough source text{scope}",
        }

    median = statistics.median(ratio for _, ratio in ratios)
    weakest = [
        {"page": page, "ratio": ratio}
        for page, ratio in sorted(ratios, key=lambda item: item[1])[:5]
    ]
    worst = ", ".join(f"p{item['page']}={item['ratio']:.2f}" for item in weakest)
    near_zero = sum(ratio < NEAR_ZERO_RATIO for _, ratio in ratios)
    near_zero_fraction = near_zero / len(ratios)
    distribution = (
        f"near-zero (<{NEAR_ZERO_RATIO:.2f}) pages {near_zero}/{len(ratios)} "
        f"({near_zero_fraction:.1%}; maximum {MAX_NEAR_ZERO_FRACTION:.1%})"
    )
    if median >= MIN_MEDIAN and near_zero_fraction <= MAX_NEAR_ZERO_FRACTION:
        return {
            "ok": True,
            "signal": "pass",
            "median": median,
            "measured_pages": len(ratios),
            "minimum_median": MIN_MEDIAN,
            "weakest": weakest,
            "detail": f"coverage {median:.3f} over {len(ratios)} pages; {distribution} (weakest {worst}).{scope}",
        }
    reasons = []
    if median < MIN_MEDIAN:
        reasons.append(f"median {median:.3f} is below {MIN_MEDIAN:.2f}")
    if near_zero_fraction > MAX_NEAR_ZERO_FRACTION:
        reasons.append(f"near-zero page fraction {near_zero_fraction:.1%} exceeds {MAX_NEAR_ZERO_FRACTION:.1%}")
    return {
        "ok": False,
        "signal": "under_translated",
        "median": median,
        "measured_pages": len(ratios),
        "minimum_median": MIN_MEDIAN,
        "weakest": weakest,
        "detail": (
            f"Coverage below threshold: {'; '.join(reasons)}. "
            f"Median {median:.3f} Chinese characters per source Latin letter over "
            f"{len(ratios)} measurable pages; {distribution}. This can indicate skipped body "
            f"text, fragmented source paragraphs, or unclassified reference material. "
            f"Weakest pages: {worst}. "
            f"Inspect these pages; if the source text layer is fragmented, re-OCR with "
            f"`quasi-extract ocr SRC OUT --layout` and translate that instead. "
            f"Output kept at {pdf_path}.{scope}"
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
        assert check(good)["ok"]
        # An isolated body-page omission may pass, but not more than 10%.
        assert page_ratios(build_dual(Path(tmp) / "one.pdf", [full] * 9 + [""]))[9][1] == 0.0
        assert check(Path(tmp) / "one.pdf")["ok"]
        assert not check(build_dual(Path(tmp) / "many.pdf", [full] * 8 + [""] * 2))["ok"]

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

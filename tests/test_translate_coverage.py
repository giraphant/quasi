"""Unit tests for the under-translation gate.

The gate exists because BabelDOC returns a structurally perfect bilingual PDF —
right page count, exit 0 — when it skips body text it did not recognise as
paragraphs. The interesting part is that it must reject a book that came out
half-translated without rejecting one that merely has a plate in it.
"""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from translate import coverage  # noqa: E402

FULL = "行动的形状是什么样的 " * 12


def test_self_check():
    coverage.demo()


def test_a_single_dead_page_does_not_reject_the_book(tmp_path):
    # Real books carry plates and part-title pages; a mean would let one drag the
    # whole run under the threshold.
    pdf = coverage.build_dual(tmp_path / "one-dead.pdf", [FULL] * 3 + [""])

    assert coverage.page_ratios(pdf)[3][1] == 0.0
    report = coverage.check(pdf)
    assert report["ok"]
    assert report["signal"] == "pass"


def test_mostly_skipped_book_is_rejected(tmp_path):
    pdf = coverage.build_dual(tmp_path / "bad.pdf", [FULL] + [""] * 3)
    report = coverage.check(pdf)

    assert not report["ok"]
    assert report["signal"] == "under_translated"
    assert report["measured_pages"] == 4
    assert report["minimum_median"] == coverage.MIN_MEDIAN
    # The message has to name the fix, not just the symptom.
    assert "--layout" in str(report["detail"])


def test_non_chinese_target_has_no_verdict(tmp_path):
    """Counting Han characters says nothing about a French translation."""
    pdf = coverage.build_dual(tmp_path / "bad.pdf", [FULL] + [""] * 3)

    assert coverage.check(pdf, target_language="fr")["signal"] == "not_applicable"
    assert not coverage.check(pdf, target_language="zh-TW")["ok"]


def test_too_few_measurable_pages_abstains(tmp_path):
    """A two-page extract cannot establish a baseline, so it must not fail one."""
    report = coverage.check(coverage.build_dual(tmp_path / "short.pdf", ["", ""]))
    assert report["ok"]
    assert report["signal"] == "insufficient_evidence"
    assert report["measured_pages"] == 2


def test_both_backends_measure_after_repairing_tounicode():
    """Order is load-bearing, and getting it wrong rejects healthy books.

    An unrepaired BabelDOC book extracts as mojibake in the CJK extension-A block,
    which the counter does not count: a real 368-page translation scored 0.17 before
    repair and 0.31 after.
    """
    for name in ("pdf2zh_translate.py", "immersive_translate.py"):
        source = (PLUGIN_ROOT / "scripts" / "translate" / name).read_text()
        assert source.index("repair_tounicode(outputs") < source.index("check_coverage(outputs"), name

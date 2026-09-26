"""Unit tests for the under-translation gate.

The gate exists because BabelDOC returns a structurally perfect bilingual PDF —
right page count, exit 0 — when it skips body text it did not recognise as
paragraphs. The interesting part is that it must reject a book that came out
half-translated without rejecting one that merely has a plate in it.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from translate import coverage  # noqa: E402

FULL = "行动的形状是什么样的 " * 12


def test_a_single_dead_page_does_not_reject_the_book(tmp_path):
    # Exactly 10% near-zero body pages remains within the chosen allowance.
    pdf = coverage.build_dual(tmp_path / "one-dead.pdf", [FULL] * 9 + [""])

    assert coverage.page_ratios(pdf)[9][1] == 0.0
    report = coverage.check(pdf)
    assert report["ok"]
    assert report["signal"] == "pass"


def test_healthy_median_cannot_hide_many_untranslated_body_pages(tmp_path):
    pdf = coverage.build_dual(tmp_path / 'hidden-gaps.pdf', [FULL] * 8 + [''] * 2)
    report = coverage.check(pdf)
    assert report['median'] >= coverage.MIN_MEDIAN
    assert report['signal'] == 'under_translated'
    assert not report['ok']
    assert '2/10' in report['detail'] and '20.0%' in report['detail']


def test_old_point_23_translation_is_rejected(tmp_path):
    pdf = coverage.build_dual(tmp_path / 'old-pass.pdf', ['中' * 78] * 4)
    report = coverage.check(pdf)
    assert report['median'] == pytest.approx(.23, abs=.005)
    assert not report['ok'] and report['signal'] == 'under_translated'
    assert report['minimum_median'] == .30


@pytest.mark.parametrize(('ratios', 'passes'), [
    ([.30] * 10, True),
    ([.299] * 10, False),
    ([.35] * 9 + [0.0], True),
    ([.35] * 89 + [.049] * 11, False),
    ([.35] * 8 + [.05] * 2, True),
])
def test_coverage_threshold_boundaries(monkeypatch, ratios, passes):
    monkeypatch.setattr(coverage, '_measure', lambda _: (list(enumerate(ratios, 1)), []))
    report = coverage.check(Path('assigned.pdf'))
    assert report['ok'] is passes


def test_low_text_plates_are_excluded_from_near_zero_denominator(tmp_path):
    pdf = coverage.build_dual(tmp_path / 'with-plates.pdf', [FULL] * 3)
    with coverage.pymupdf.open(pdf) as document:
        for _ in range(7):
            document.new_page().insert_text((20, 20), 'Plate', fontsize=9)
            document.new_page()
        document.saveIncr()
    report = coverage.check(pdf)
    assert report['measured_pages'] == 3 and report['ok']
    assert '0/3' in report['detail']


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


def _book(tmp_path, translated, toc, *, headings=(), translated_side=False):
    pdf = coverage.build_dual(tmp_path / "sections.pdf", translated)
    with coverage.pymupdf.open(pdf) as doc:
        doc.set_toc([
            [level, title, 2 * page - (0 if translated_side else 1)]
            for level, title, page in toc
        ])
        for page, text, side in headings:
            doc[2 * (page - 1) + side].insert_text((20, 500), text, fontsize=9)
        doc.saveIncr()
    return pdf


@pytest.mark.parametrize("translated_side", [False, True])
def test_reference_heavy_book_keeps_body_threshold(tmp_path, translated_side):
    pdf = _book(tmp_path, [FULL] * 4 + [""] * 6, [
        [1, "Body", 1], [1, "Bibliography", 5], [1, "Index", 9],
    ], translated_side=translated_side)
    report = coverage.check(pdf)
    assert report["ok"] and report["measured_pages"] == 4
    assert report["minimum_median"] == .30
    assert "excluded 6/10" in report["detail"]
    assert "p5-8 references" in report["detail"] and "p9-10 index" in report["detail"]
    assert "0/4" in report["detail"]


def test_reference_section_ends_at_sibling_not_its_children(tmp_path):
    pdf = _book(tmp_path, [FULL] * 6 + [""] * 4 + [FULL] * 2, [
        [1, "Chapter 1", 1], [2, "References", 7], [3, "Primary sources", 8],
        [1, "Chapter 2", 9],
    ])
    report = coverage.check(pdf)
    assert not report["ok"] and report["measured_pages"] == 10
    assert "2/10" in report["detail"]
    assert {item["page"] for item in report["weakest"]}.issuperset({9, 10})
    assert not {item["page"] for item in report["weakest"]}.intersection({7, 8})


@pytest.mark.parametrize("title", ["Notes", "References"])
def test_bookmarked_mixed_opening_page_stays_scored(tmp_path, title):
    pdf = _book(tmp_path, [FULL] * 3 + [""] * 4, [[1, "Body", 1], [1, title, 4]],
                headings=[(4, f"{title}\n1. First citation.\n2. Second citation.", 0)])
    report = coverage.check(pdf)
    assert not report["ok"] and report["measured_pages"] == 4
    assert report["weakest"][0]["page"] == 4
    assert "p5-7" in report["detail"]


@pytest.mark.parametrize("title", ["Notes on Method", "Index of Economic Activity", "References in Fiction"])
def test_words_in_body_titles_do_not_exempt_chapters(tmp_path, title):
    pdf = _book(tmp_path, [FULL] * 3 + [""] * 4, [[1, "Body", 1], [1, title, 4]])
    report = coverage.check(pdf)
    assert not report["ok"] and report["measured_pages"] == 7


def test_unbookmarked_numbered_notes_keep_mixed_page_and_stop_at_next_section(tmp_path):
    pdf = _book(tmp_path, [FULL] * 3 + [""] * 4 + [FULL] * 3, [
        [1, "Chapter 1", 1], [1, "Chapter 2", 7],
    ], headings=[(3, "Notes\n1. First citation.\n2. Second citation.", 0)])
    report = coverage.check(pdf)
    assert not report["ok"] and report["measured_pages"] == 7
    assert "p4-6 notes (numbered Notes heading p3)" in report["detail"]
    assert "1/7" in report["detail"]
    assert report["weakest"][0]["page"] == 7


@pytest.mark.parametrize(("heading", "side", "has_end"), [
    ("Notes", 0, True),  # No numbered entries to support the heading.
    ("Notes\n3. A point.\n4. Another point.", 0, True),
    ("Notes\n1. First citation.\n2. Second citation.", 1, True),  # Target is not evidence.
    ("Notes\n1. First citation.\n2. Second citation.", 0, False),  # Unbounded.
])
def test_ambiguous_notes_stay_measurable(tmp_path, heading, side, has_end):
    toc = [[1, "Chapter 1", 1]] + ([[1, "Chapter 2", 7]] if has_end else [])
    pdf = _book(tmp_path, [FULL] * 3 + [""] * 4, toc, headings=[(3, heading, side)])
    report = coverage.check(pdf)
    assert not report["ok"] and report["measured_pages"] == 7


def test_numbered_notes_without_an_outline_do_not_hide_later_body(tmp_path):
    pdf = _book(tmp_path, [FULL] * 3 + [""] * 4, [], headings=[
        (3, "Notes\n1. First citation.\n2. Second citation.", 0),
    ])
    assert coverage.check(pdf)["measured_pages"] == 7


def test_reference_exclusion_does_not_turn_failure_into_insufficient_evidence(tmp_path):
    pdf = _book(tmp_path, [FULL] * 2 + [""] * 5, [[1, "Body", 1], [1, "References", 3]])
    report = coverage.check(pdf)
    assert not report["ok"] and report["signal"] == "under_translated"
    assert report["measured_pages"] == 7
    assert "exclusions not applied" in report["detail"]


@pytest.mark.parametrize(("dead", "passes"), [(1, True), (2, False)])
def test_ten_percent_allowance_uses_remaining_body_pages(tmp_path, dead, passes):
    pdf = _book(tmp_path, [FULL] * (10 - dead) + [""] * (dead + 10), [
        [1, "Body", 1], [1, "References", 11],
    ])
    report = coverage.check(pdf)
    assert report["ok"] is passes and report["measured_pages"] == 10
    assert f"{dead}/10" in report["detail"]


def test_bad_body_is_not_rescued_by_reference_exclusion(tmp_path):
    pdf = _book(tmp_path, ["中" * 78] * 4 + [""] * 4, [[1, "Body", 1], [1, "References", 5]])
    report = coverage.check(pdf)
    assert not report["ok"] and report["median"] == pytest.approx(.23, abs=.005)
    assert report["measured_pages"] == 4


def test_out_of_order_outline_is_not_used_for_exclusions(tmp_path):
    pdf = _book(tmp_path, [FULL] * 3 + [""] * 4, [
        [1, "Body", 1], [1, "References", 4], [1, "Later body", 2],
    ])
    report = coverage.check(pdf)
    assert not report["ok"] and report["measured_pages"] == 7


def test_outline_destination_without_a_page_is_not_an_exemption(tmp_path):
    pdf = _book(tmp_path, [FULL] * 3 + [""] * 4, [])
    with coverage.pymupdf.open(pdf) as doc:
        doc.set_toc([[1, "Body", 1], [1, "References", -1]])
        doc.saveIncr()
    assert coverage.check(pdf)["measured_pages"] == 7


def test_dangling_odd_page_does_not_supply_a_section_destination(tmp_path):
    pdf = _book(tmp_path, [FULL] * 3, [])
    with coverage.pymupdf.open(pdf) as doc:
        doc.new_page()
        doc.set_toc([[1, "References", 7]])
        doc.saveIncr()
    assert coverage.check(pdf)["measured_pages"] == 3


def _first_named_call(function: ast.FunctionDef, name: str) -> ast.Call:
    calls: list[ast.Call] = []
    pending = list(function.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
        ):
            calls.append(node)
        pending.extend(ast.iter_child_nodes(node))
    assert calls, f"{function.name} must call {name}"
    return min(calls, key=lambda call: (call.lineno, call.col_offset))


def test_translation_paths_measure_after_repairing_the_same_candidate():
    """Order is load-bearing, and getting it wrong rejects healthy books.

    An unrepaired BabelDOC book extracts as mojibake in the CJK extension-A block,
    which the counter does not count: a real 368-page translation scored 0.17 before
    repair and 0.31 after.
    """
    targets = (
        ("scripts/translate/pdf2zh_translate.py", "translate_slug"),
        ("scripts/translate/immersive_translate.py", "translate_slug"),
        ("scripts/translate/translate_commit.py", "run_transaction"),
    )
    for relative, function_name in targets:
        tree = ast.parse((PLUGIN_ROOT / relative).read_text(encoding="utf-8"))
        function = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == function_name
            ),
            None,
        )
        assert function is not None, f"{relative}: missing {function_name}"
        repair = _first_named_call(function, "repair_tounicode")
        coverage_call = _first_named_call(function, "check_coverage")

        assert repair.lineno < coverage_call.lineno, relative
        assert repair.args and coverage_call.args, relative
        assert ast.dump(repair.args[0]) == ast.dump(coverage_call.args[0]), relative

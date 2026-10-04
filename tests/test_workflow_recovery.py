"""Recovery must finish known work without weakening the final quality gate."""
from __future__ import annotations

import pytest

from test_material_plans import (
    analyse_complete,
    audit_complete,
    book_synthesise_complete,
    canonical_book_input,
    canonical_input,
    chapter_output_observation_mismatch,
    chapter_repair_complete,
    prepare_complete,
    run_book,
    run_paper,
)


@pytest.mark.parametrize("after_semantic_repair", [False, True])
def test_paper_accepts_audit_that_validated_its_mechanical_fixes(after_semantic_repair):
    target = "vault/papers/exact-paper.md"
    outputs = [prepare_complete()]
    if after_semantic_repair:
        outputs += [
            audit_complete(escalated=[{
                "path": target, "kind": "missing-section", "reason": "Analysis absent.",
            }]),
            analyse_complete("repair"),
        ]
    outputs.append(audit_complete(mutated_paths=[target]))
    report = run_paper(
        canonical_input(source=True, prepared=True, canonical=True, admitted=True),
        outputs,
    )
    assert report["result"]["terminal"] == "complete"
    assert len(report["calls"]) == len(outputs)
    assert report["remaining"] == 0


def test_book_repairs_every_flagged_owner_before_final_audit():
    overview = "vault/books/exact-book/00-overview.md"
    opening = "vault/books/exact-book/ch01-opening.md"
    closing = "vault/books/exact-book/ch02-closing.md"
    diagnostics = [
        {"path": overview, "kind": "missing-section", "reason": "Overview incomplete."},
        {"path": closing, "kind": "missing-section", "reason": "Closing analysis missing."},
        {"path": opening, "kind": "missing-section", "reason": "Opening analysis missing."},
        {"path": opening, "kind": "citation", "reason": "Opening quotation needs source."},
    ]
    report = run_book(
        canonical_book_input(manifest=True, chapter_inputs=(True, True), chapter_outputs=(True, True)),
        [audit_complete(escalated=diagnostics), chapter_repair_complete(),
         chapter_repair_complete(), book_synthesise_complete("repair"), audit_complete()],
    )
    assert report["result"]["terminal"] == "complete"
    requests = [call["request"] for call in report["calls"]]
    assert [request["operation"] for request in requests] == [
        "book.audit", "chapter.analyse", "chapter.analyse", "book.synthesise", "book.audit",
    ]
    for request, path in zip(requests[1:4], [opening, closing, overview]):
        assert request["repair_diagnostics"] == [d for d in diagnostics if d["path"] == path]
    assert [request["pass"] for request in (requests[0], requests[-1])] == [1, 2]
    assert report["remaining"] == 0


def test_book_stops_between_repairs_if_a_writer_disappears():
    paths = ["vault/books/exact-book/ch01-opening.md", "vault/books/exact-book/ch02-closing.md"]
    report = run_book(
        canonical_book_input(manifest=True, chapter_inputs=(True, True), chapter_outputs=(True, True)),
        [audit_complete(escalated=[{"path": p, "kind": "missing-section", "reason": "Incomplete."} for p in paths]),
         "__throw__", chapter_repair_complete(), audit_complete()],
    )
    assert report["result"]["issue"]["code"] == "workflow.unknown_outcome"
    assert len(report["calls"]) == 2
    assert report["remaining"] == 2


@pytest.mark.parametrize("other", ["__throw__", "__failed__"])
def test_book_known_stale_observation_cannot_hide_other_chapter_failure(other):
    failure = {
        "terminal": {
            "status": "failed",
            "issue": {"code": "chapter.analysis_failed", "operation": "chapter.analyse",
                      "summary": "Source cannot support this analysis.", "user_question": None, "retryable": False},
            "action": "create", "write_state": "not_written",
        },
    }
    report = run_book(
        canonical_book_input(manifest=True, chapter_inputs=(True, True), chapter_outputs=(False, False)),
        [chapter_output_observation_mismatch(), failure if other == "__failed__" else other],
    )
    assert len(report["settled"]) == 2
    assert report["result"]["issue"]["code"] == (
        "chapter.analysis_failed" if other == "__failed__" else "workflow.unknown_outcome"
    )
    assert report["result"]["terminal"] != "needs_observation"

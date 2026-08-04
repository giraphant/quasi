from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from workflow_test_support import run_workflow_export


INPUT_MODULE = "scripts/workflows/shared/material-input.mts"
RESULT_MODULE = "scripts/workflows/shared/material-result.mts"
PAPER_CONTRACT_MODULE = "scripts/workflows/contracts/paper.mts"
SEARCH_CONTRACT_MODULE = "scripts/workflows/contracts/search.mts"
BOOK_CONTRACT_MODULE = "scripts/workflows/contracts/book.mts"
TRANSLATION_CONTRACT_MODULE = "scripts/workflows/contracts/translation.mts"

PAPER_IDENTITY = {
    "slug": "exact-paper",
    "title": "Exact Paper",
    "authors": ["Ada Example"],
    "year": 2024,
    "doi": "10.1000/exact",
    "oa_url": "https://example.test/exact.pdf",
    "url": "https://example.test/exact",
    "journal": "Exact Joins",
    "confidence": "high",
}

BOOK_IDENTITY = {
    "slug": "exact-book",
    "title": "Exact Book",
    "authors": ["Ada Example"],
    "year": 2024,
    "isbn": "9780000000000",
    "publisher": "Exact Press",
    "category": "monograph",
    "confidence": "high",
}

PAPER_OBSERVATION = {
    "schema_version": "quasi.status/0.2",
    "kind": "paper",
    "slug": "exact-paper",
    "identity": None,
    "facts": {
        "kind": "paper",
        "source": {
            "path": "sources/exact-paper.pdf",
            "present": False,
            "usable": False,
        },
        "prepared": [
            {
                "path": "processing/papers/exact-paper/source.txt",
                "present": False,
                "usable": False,
            },
            {
                "path": "processing/papers/exact-paper/ocr.txt",
                "present": False,
                "usable": False,
            },
        ],
        "canonical": {
            "path": "vault/papers/exact-paper.md",
            "present": False,
            "usable": False,
        },
    },
}


BOOK_OBSERVATION = {
    "schema_version": "quasi.status/0.2",
    "kind": "book",
    "slug": "request-book-1",
    "identity": None,
    "facts": {
        "kind": "book",
        "sources": [],
        "manifest": {
            "path": "processing/chapters/request-book-1/manifest.json",
            "present": False,
            "usable": False,
            "valid": False,
        },
        "chapters": [],
        "overview": {
            "path": "vault/books/request-book-1/overview.md",
            "present": False,
            "usable": False,
        },
    },
}


def translation_observation(target_language: str) -> dict[str, Any]:
    target = target_language.lower()
    return {
        "schema_version": "quasi.status/0.2",
        "kind": "translation",
        "slug": "exact-paper",
        "identity": None,
        "facts": {
            "kind": "translation",
            "target_language": target_language,
            "source": {
                "path": "sources/exact-paper.pdf",
                "present": True,
                "usable": True,
            },
            "output": {
                "path": f"processing/translations/exact-paper-{target}.pdf",
                "present": False,
                "usable": False,
            },
            "manifest": {
                "path": (
                    f"processing/translations/exact-paper-{target}.manifest.json"
                ),
                "present": False,
                "usable": False,
            },
        },
    }


def valid_input() -> dict[str, Any]:
    return {
        "seed": {
            "state": "canonical",
            "material_slug": "exact-paper",
            "identity": deepcopy(PAPER_IDENTITY),
        },
        "observation": deepcopy(PAPER_OBSERVATION),
        "options": {},
    }


def parse_paper(value: Any) -> dict[str, Any]:
    return run_workflow_export(
        PAPER_CONTRACT_MODULE,
        "parsePaperRunInput",
        value,
    )


def parse_book(value: Any) -> dict[str, Any]:
    return run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookRunInput",
        value,
    )


def assert_parsed_seed(
    value: dict[str, Any],
    kind: str,
    observation_key: str,
) -> None:
    module = PAPER_CONTRACT_MODULE if kind == "paper" else BOOK_CONTRACT_MODULE
    parser = "parsePaperRunInput" if kind == "paper" else "parseBookRunInput"
    result = run_workflow_export(module, parser, value)
    assert result == {
        "ok": True,
        "value": {
            "seed": value["seed"],
            "observations": {
                "__map_entries__": [[observation_key, value["observation"]]]
            },
            "options": value["options"],
            "userDecision": None,
        },
    }


def assert_invalid_input(
    result: dict[str, Any],
    requested_slug: str | None,
    kind: str = "paper",
) -> None:
    assert result == {
        "ok": False,
        "result": {
            "schema_version": "quasi.material.result/0.1",
            "material": {
                "requested": {"kind": kind, "slug": requested_slug},
                "canonical": None,
            },
            "terminal": "blocked",
            "issue": {
                "code": "material.invalid_input",
                "operation": None,
                "summary": "Material Workflow input is invalid.",
                "retryable": False,
                "observation_request": None,
            },
        },
    }


@pytest.mark.parametrize("value", [None, [], "paper", 42])
def test_non_object_input_blocks_before_dispatch(value: Any):
    assert_invalid_input(parse_paper(value), None)


def test_canonical_seed_missing_full_identity_blocks_before_dispatch():
    value = valid_input()
    del value["seed"]["identity"]

    assert_invalid_input(parse_paper(value), "exact-paper")


def test_canonical_seed_with_malformed_identity_slug_blocks_before_dispatch():
    value = valid_input()
    value["seed"]["identity"]["slug"] = "Not/A-Slug"

    assert_invalid_input(parse_paper(value), "exact-paper")


def test_missing_observation_blocks_before_dispatch():
    value = valid_input()
    del value["observation"]

    assert_invalid_input(parse_paper(value), "exact-paper")


def test_strict_canonical_seed_builds_one_sparse_observation_map():
    assert_parsed_seed(valid_input(), "paper", "paper:exact-paper")


def test_minimal_paper_doi_seed_preserves_provisional_identity():
    value = {
        "seed": {
            "state": "provisional",
            "requested_slug": "request-paper-1",
            "hints": {"doi": "10.1000/provisional"},
        },
        "observation": {
            **deepcopy(PAPER_OBSERVATION),
            "slug": "request-paper-1",
        },
        "options": {},
    }

    assert_parsed_seed(value, "paper", "paper:request-paper-1")


def test_minimal_book_isbn_seed_preserves_provisional_identity():
    value = {
        "seed": {
            "state": "provisional",
            "requested_slug": "request-book-1",
            "hints": {"isbn": "9780000000000"},
        },
        "observation": deepcopy(BOOK_OBSERVATION),
        "options": {},
    }

    assert_parsed_seed(value, "book", "book:request-book-1")


@pytest.mark.parametrize(
    ("kind", "seed", "observation"),
    [
        (
            "paper",
            {"state": "provisional", "requested_slug": "request-paper-1", "hints": {}},
            {**deepcopy(PAPER_OBSERVATION), "slug": "request-paper-1"},
        ),
        (
            "book",
            {"state": "provisional", "requested_slug": "request-book-1", "hints": {}},
            BOOK_OBSERVATION,
        ),
    ],
)
def test_provisional_seed_requires_one_search_anchor(
    kind: str,
    seed: dict[str, Any],
    observation: dict[str, Any],
):
    value = {"seed": seed, "observation": observation, "options": {}}

    result = parse_paper(value) if kind == "paper" else parse_book(value)

    requested_slug = seed["requested_slug"]
    assert_invalid_input(result, requested_slug, kind)


def test_provisional_observation_binds_to_requested_slug():
    value = {
        "seed": {
            "state": "provisional",
            "requested_slug": "request-paper-1",
            "hints": {"title": "A provisional paper"},
        },
        "observation": deepcopy(PAPER_OBSERVATION),
        "options": {},
    }

    assert_invalid_input(parse_paper(value), "request-paper-1")


def test_canonical_observation_binds_to_material_slug():
    value = valid_input()
    value["seed"]["material_slug"] = "owned-paper"

    assert_invalid_input(parse_paper(value), "owned-paper")


def test_owner_drift_keeps_material_slug_separate_from_identity_slug():
    value = valid_input()
    value["seed"]["material_slug"] = "owned-paper"
    value["observation"]["slug"] = "owned-paper"
    value["observation"]["identity"] = {
        "title": PAPER_IDENTITY["title"],
        "authors": PAPER_IDENTITY["authors"],
        "year": PAPER_IDENTITY["year"],
    }
    value["observation"]["facts"]["canonical"] = {
        "path": "vault/papers/owned-paper.md",
        "present": True,
        "usable": True,
    }

    parsed = parse_paper(value)
    assert parsed["ok"] is True
    assert parsed["value"]["seed"]["material_slug"] == "owned-paper"
    assert parsed["value"]["seed"]["identity"]["slug"] == "exact-paper"

    result = run_workflow_export(
        RESULT_MODULE,
        "completeMaterialResult",
        {
            "material": {
                "requested": {"kind": "paper", "slug": "owned-paper"},
                "canonical": {"kind": "paper", "slug": "owned-paper"},
            }
        },
        [{"role": "canonical", "path": "vault/papers/owned-paper.md"}],
        None,
    )

    assert result["material"]["canonical"]["slug"] == "owned-paper"


def test_owner_drift_rejects_an_empty_status_query_echo():
    value = valid_input()
    value["seed"]["material_slug"] = "owned-paper"
    value["observation"]["slug"] = "owned-paper"

    assert_invalid_input(parse_paper(value), "owned-paper")


def test_unknown_seed_key_blocks_before_dispatch():
    value = valid_input()
    value["seed"]["cursor"] = "hidden-state"

    assert_invalid_input(parse_paper(value), "exact-paper")


@pytest.mark.parametrize(
    ("observation_kind", "observation_slug"),
    [("book", "exact-paper"), ("paper", "other-paper")],
)
def test_observation_identity_mismatch_has_no_dispatchable_value(
    observation_kind: str,
    observation_slug: str,
):
    value = valid_input()
    value["observation"]["kind"] = observation_kind
    value["observation"]["slug"] = observation_slug

    result = parse_paper(value)

    assert_invalid_input(result, "exact-paper")
    assert "value" not in result


def test_translation_target_mismatch_has_no_dispatchable_value():
    observation = translation_observation("fr-FR")
    result = run_workflow_export(
        INPUT_MODULE,
        "sparseObservations",
        [
            {
                "route": {
                    "kind": "translation",
                    "slug": "exact-paper",
                    "target_language": "zh-CN",
                },
                "observation": observation,
            }
        ],
    )

    assert result is None


def test_translation_observation_missing_target_has_no_dispatchable_value():
    observation = translation_observation("zh-CN")
    del observation["facts"]["target_language"]

    result = run_workflow_export(
        INPUT_MODULE,
        "sparseObservations",
        [
            {
                "route": {
                    "kind": "translation",
                    "slug": "exact-paper",
                    "target_language": "zh-CN",
                },
                "observation": observation,
            }
        ],
    )

    assert result is None


def test_translation_observation_rejects_noncanonical_target_tag():
    observation = translation_observation("zh-cn")

    result = run_workflow_export(
        INPUT_MODULE,
        "sparseObservations",
        [
            {
                "route": {
                    "kind": "translation",
                    "slug": "exact-paper",
                    "target_language": "zh-CN",
                },
                "observation": observation,
            }
        ],
    )

    assert result is None


def test_non_translation_observation_rejects_target_field():
    observation = deepcopy(PAPER_OBSERVATION)
    observation["target_language"] = "zh-CN"

    result = run_workflow_export(
        INPUT_MODULE,
        "sparseObservations",
        [
            {
                "route": {"kind": "paper", "slug": "exact-paper"},
                "observation": observation,
            }
        ],
    )

    assert result is None


def test_translation_observation_key_uses_normalized_full_target_tag():
    observation = translation_observation("zh-CN")

    result = run_workflow_export(
        INPUT_MODULE,
        "sparseObservations",
        [
            {
                "route": {
                    "kind": "translation",
                    "slug": "exact-paper",
                    "target_language": "zh-CN",
                },
                "observation": observation,
            }
        ],
    )

    assert result == {
        "__map_entries__": [
            ["translation:paper:exact-paper:zh-CN", observation]
        ]
    }


def test_sparse_observations_rejects_duplicate_keys():
    row = {
        "route": {"kind": "paper", "slug": "exact-paper"},
        "observation": deepcopy(PAPER_OBSERVATION),
    }

    result = run_workflow_export(INPUT_MODULE, "sparseObservations", [row, row])

    assert result is None


def test_shared_parser_rejects_universal_context_bag():
    value = valid_input()
    value["context"] = {"selected_input": "sources/exact-paper.pdf"}

    assert_invalid_input(parse_paper(value), "exact-paper")


@pytest.mark.parametrize("options", [None, [], "all"])
def test_shared_parser_rejects_non_object_options(options: Any):
    value = valid_input()
    value["options"] = options

    assert_invalid_input(parse_paper(value), "exact-paper")


def test_decision_applies_only_to_matching_next_operation_and_fresh_state():
    decision = {
        "material_key": "book:exact-book",
        "operation": "book.acquire",
        "value": book_year_decision("use-recommended-year"),
    }

    matching = run_workflow_export(
        INPUT_MODULE,
        "decisionForOperation",
        decision,
        "book:exact-book",
        "book.acquire",
        False,
    )
    wrong_material = run_workflow_export(
        INPUT_MODULE,
        "decisionForOperation",
        decision,
        "book:other-book",
        "book.acquire",
        False,
    )
    wrong_operation = run_workflow_export(
        INPUT_MODULE,
        "decisionForOperation",
        decision,
        "book:exact-book",
        "book.prepare",
        False,
    )
    stale = run_workflow_export(
        INPUT_MODULE,
        "decisionForOperation",
        decision,
        "book:exact-book",
        "book.acquire",
        True,
    )

    assert matching == decision["value"]
    assert wrong_material is None
    assert wrong_operation is None
    assert stale is None


def test_translation_decision_value_keeps_its_evidence_binding():
    translation_value = {
        "candidates_fingerprint": "a" * 64,
        "source_path": "sources/exact-paper.pdf",
    }

    assert run_workflow_export(
        TRANSLATION_CONTRACT_MODULE,
        "parseTranslationSourceDecisionValue",
        translation_value,
    ) == translation_value


def identity_conflict_receipt() -> dict[str, Any]:
    candidates = [
        {"kind": "paper", "identity": deepcopy(PAPER_IDENTITY)},
        {"kind": "book", "identity": deepcopy(BOOK_IDENTITY)},
    ]
    return {
        "operation": "material.search",
        "material_key": "paper:request-paper-1",
        "kind": "paper",
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": "material.identity_conflict",
                "operation": "material.search",
                "summary": "The evidence supports two work types.",
                "user_question": "Is this the article or the book?",
                "retryable": False,
            },
            "candidates": candidates,
            "conflicts": ["publication_type"],
        },
    }


def test_identity_conflict_gate_binds_the_stamped_owner_and_closed_evidence():
    receipt = identity_conflict_receipt()

    gate = run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictGate",
        receipt,
        "paper",
    )

    assert gate == {
        "kind": "identity_conflict",
        "operation": "material.search",
        "material_key": "paper:request-paper-1",
        "question": "Is this the article or the book?",
        "candidates": receipt["terminal"]["candidates"],
        "conflicts": ["publication_type"],
    }


def test_book_search_gate_rejects_a_paper_candidate():
    receipt = identity_conflict_receipt()
    receipt["kind"] = "book"
    receipt["material_key"] = "book:request-book-1"

    assert run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictGate",
        receipt,
        "book",
    ) is None


def test_identity_conflict_decision_echoes_gate_and_selects_a_member():
    receipt = identity_conflict_receipt()
    gate = run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictGate",
        receipt,
        "paper",
    )
    value = {
        "candidates": deepcopy(gate["candidates"]),
        "conflicts": deepcopy(gate["conflicts"]),
        "selected_candidate": deepcopy(gate["candidates"][1]),
    }

    assert run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictDecisionValue",
        value,
        gate,
    ) == value

    changed_echo = deepcopy(value)
    changed_echo["conflicts"] = ["title"]
    assert run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictDecisionValue",
        changed_echo,
        gate,
    ) is None

    foreign_selection = deepcopy(value)
    foreign_selection["selected_candidate"]["identity"]["slug"] = "other-book"
    assert run_workflow_export(
        SEARCH_CONTRACT_MODULE,
        "parseIdentityConflictDecisionValue",
        foreign_selection,
        gate,
    ) is None


def book_year_evidence(
    verdict: str,
    *,
    slug_year: int = 2024,
) -> dict[str, Any]:
    recommended_year = {
        "MATCH": slug_year,
        "MISMATCH": 2025,
        "AMBIGUOUS": None,
    }[verdict]
    return {
        "slug_year": slug_year,
        "source_years": {"publisher": 2025, "catalogue": 2025},
        "pdf_signals": {
            "first_published": 2025,
            "copyright_year": 2025,
            "original_year": None,
            "other_years": [2024],
        },
        "recommended_year": recommended_year,
        "recommendation_reason": "Publisher and catalogue evidence agree.",
        "verdict": verdict,
    }


def book_year_decision(action: str) -> dict[str, Any]:
    verdict = "AMBIGUOUS" if action == "accept-current" else "MISMATCH"
    return {
        "current_identity": deepcopy(BOOK_IDENTITY),
        "tmp_path": ".quasi/temp/downloads/exact-book.pdf",
        "year_evidence": book_year_evidence(verdict),
        "action": action,
    }


@pytest.mark.parametrize("action", ["accept-current", "use-recommended-year"])
def test_book_year_decision_preserves_all_four_bound_values(action: str):
    value = book_year_decision(action)

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookYearDecisionValue",
        value,
    ) == value


@pytest.mark.parametrize(
    ("verdict", "action"),
    [
        ("MATCH", "accept-current"),
        ("MATCH", "use-recommended-year"),
        ("AMBIGUOUS", "use-recommended-year"),
    ],
)
def test_book_year_decision_rejects_actions_without_a_prior_gate(
    verdict: str,
    action: str,
):
    value = book_year_decision(action)
    value["year_evidence"] = book_year_evidence(verdict)

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookYearDecisionValue",
        value,
    ) is None


def test_book_year_decision_binds_evidence_to_current_identity_year():
    value = book_year_decision("accept-current")
    value["year_evidence"] = book_year_evidence("AMBIGUOUS", slug_year=2023)

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookYearDecisionValue",
        value,
    ) is None


def book_year_receipt(
    verdict: str,
    *,
    material_key: str = "book:owned-book",
) -> dict[str, Any]:
    issue_code = {
        "MATCH": "book.year_mismatch",
        "MISMATCH": "book.year_mismatch",
        "AMBIGUOUS": "book.year_ambiguous",
    }[verdict]
    proposed_actions = (
        ["accept-current", "use-recommended-year"]
        if verdict == "MISMATCH"
        else ["accept-current"]
    )
    return {
        "operation": "book.acquire",
        "material_key": material_key,
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": issue_code,
                "operation": "book.acquire",
                "summary": "The source year needs a user decision.",
                "user_question": "Which publication year should be retained?",
                "retryable": False,
            },
            "tmp_path": ".quasi/temp/downloads/exact-book.pdf",
            "year_evidence": book_year_evidence(verdict),
            "proposed_actions": proposed_actions,
        },
    }


@pytest.mark.parametrize(
    ("verdict", "proposed_actions"),
    [
        ("MISMATCH", ["accept-current", "use-recommended-year"]),
        ("AMBIGUOUS", ["accept-current"]),
    ],
)
def test_book_year_gate_keeps_owner_key_separate_from_identity_slug(
    verdict: str,
    proposed_actions: list[str],
):
    receipt = book_year_receipt(verdict)

    gate = run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookYearGate",
        receipt,
        BOOK_IDENTITY,
    )

    assert gate == {
        "kind": "book_year",
        "operation": "book.acquire",
        "material_key": "book:owned-book",
        "current_identity": BOOK_IDENTITY,
        "question": "Which publication year should be retained?",
        "tmp_path": ".quasi/temp/downloads/exact-book.pdf",
        "year_evidence": receipt["terminal"]["year_evidence"],
        "proposed_actions": proposed_actions,
    }


@pytest.mark.parametrize("mutation", ["verdict", "issue", "actions"])
def test_book_year_gate_rejects_verdict_issue_action_incoherence(mutation: str):
    receipt = book_year_receipt("MISMATCH")
    terminal = receipt["terminal"]
    if mutation == "verdict":
        terminal["year_evidence"] = book_year_evidence("MATCH")
    elif mutation == "issue":
        terminal["issue"]["code"] = "book.year_ambiguous"
    else:
        terminal["proposed_actions"] = ["accept-current"]

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookYearGate",
        receipt,
        BOOK_IDENTITY,
    ) is None


def book_structure_candidates() -> list[dict[str, Any]]:
    return [
        {
            "key": "frontmatter-separate",
            "label": "Keep front matter separate",
            "summary": "The introduction starts after the preface.",
            "chapter_count": 3,
            "chapters": [
                {"title": "Preface", "start": 1, "end": 8},
                {"title": "Introduction", "start": 9, "end": 30},
                {"title": "Argument", "start": 31, "end": 70},
            ],
        },
        {
            "key": "frontmatter-combined",
            "label": "Combine front matter",
            "summary": "The preface belongs with the introduction.",
            "chapter_count": 2,
            "chapters": [
                {"title": "Preface and Introduction", "start": 1, "end": 30},
                {"title": "Argument", "start": 31, "end": 70},
            ],
        },
    ]


def book_structure_receipt() -> dict[str, Any]:
    return {
        "operation": "book.prepare",
        "material_key": "book:exact-book",
        "format": "pdf",
        "selected_source": "sources/exact-book.pdf",
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": "book.chapter_structure_ambiguous",
                "operation": "book.prepare",
                "summary": "Two coherent chapter structures remain.",
                "user_question": "Which chapter structure should be used?",
                "retryable": False,
            },
            "source_path": "sources/exact-book.pdf",
            "candidates": book_structure_candidates(),
            "conflicts": ["chapter_boundaries", "included_material"],
        },
    }


def test_book_structure_gate_is_a_complete_manual_split_choice():
    receipt = book_structure_receipt()

    gate = run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStructureGate",
        receipt,
    )

    assert gate == {
        "kind": "book_structure",
        "operation": "book.prepare",
        "material_key": "book:exact-book",
        "question": "Which chapter structure should be used?",
        "source_path": "sources/exact-book.pdf",
        "candidates": receipt["terminal"]["candidates"],
        "conflicts": ["chapter_boundaries", "included_material"],
    }


@pytest.mark.parametrize("mutation", ["duplicate_key", "count", "overlap", "conflict"])
def test_book_structure_gate_rejects_incoherent_cross_field_evidence(
    mutation: str,
):
    receipt = book_structure_receipt()
    terminal = receipt["terminal"]
    if mutation == "duplicate_key":
        terminal["candidates"][1]["key"] = terminal["candidates"][0]["key"]
    elif mutation == "count":
        terminal["candidates"][0]["chapter_count"] = 2
    elif mutation == "overlap":
        terminal["candidates"][0]["chapters"][1]["start"] = 8
    else:
        terminal["conflicts"] = ["chapter_boundaries", "chapter_boundaries"]

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStructureGate",
        receipt,
    ) is None


def test_book_structure_decision_echoes_gate_and_selects_a_member():
    receipt = book_structure_receipt()
    gate = run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStructureGate",
        receipt,
    )
    value = {
        "source_path": gate["source_path"],
        "candidates": deepcopy(gate["candidates"]),
        "conflicts": deepcopy(gate["conflicts"]),
        "selected_candidate": deepcopy(gate["candidates"][0]),
    }

    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStructureDecisionValue",
        value,
        gate,
    ) == value

    value["source_path"] = "sources/another-book.pdf"
    assert run_workflow_export(
        BOOK_CONTRACT_MODULE,
        "parseBookStructureDecisionValue",
        value,
        gate,
    ) is None


def translation_gate_receipt(kind: str) -> dict[str, Any]:
    source_candidate = {
        "path": "sources/exact-paper.pdf",
        "sha256": "a" * 64,
        "size": 1234,
        "pages": 10,
    }
    if kind == "source_selection":
        issue_code = "translation.source_selection_required"
        missing_fields = []
        candidates = [
            source_candidate,
            {
                **source_candidate,
                "path": "sources/exact-paper-alt.pdf",
                "sha256": "b" * 64,
            },
        ]
        candidates_fingerprint = "f" * 64
        question = "Which source should be translated?"
    else:
        issue_code = "translation.configuration_required"
        missing_fields = ["translate_api_key", "translate_model"]
        candidates = []
        candidates_fingerprint = None
        question = "Which translation configuration should be used?"
    return {
        "operation": "translation.prepare",
        "material_key": "translation:paper:exact-paper:zh-CN",
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": issue_code,
                "operation": "translation.prepare",
                "summary": "Translation needs one user decision.",
                "user_question": question,
                "retryable": False,
            },
            "gate": {
                "kind": kind,
                "missing_fields": missing_fields,
                "candidates": candidates,
                "candidates_fingerprint": candidates_fingerprint,
            },
        },
    }


@pytest.mark.parametrize(
    ("receipt_kind", "material_gate_kind"),
    [
        ("source_selection", "translation_source"),
        ("configuration_required", "translation_configuration"),
    ],
)
def test_translation_gate_maps_each_exact_receipt_arm(
    receipt_kind: str,
    material_gate_kind: str,
):
    receipt = translation_gate_receipt(receipt_kind)

    gate = run_workflow_export(
        TRANSLATION_CONTRACT_MODULE,
        "parseTranslationGate",
        receipt,
    )

    assert gate == {
        "kind": material_gate_kind,
        "operation": "translation.prepare",
        "material_key": "translation:paper:exact-paper:zh-CN",
        "question": receipt["terminal"]["issue"]["user_question"],
        "missing_fields": receipt["terminal"]["gate"]["missing_fields"],
        "candidates": receipt["terminal"]["gate"]["candidates"],
        "candidates_fingerprint": receipt["terminal"]["gate"][
            "candidates_fingerprint"
        ],
    }


def test_translation_gate_rejects_issue_and_gate_kind_mismatch():
    receipt = translation_gate_receipt("source_selection")
    receipt["terminal"]["issue"][
        "code"
    ] = "translation.configuration_required"

    assert run_workflow_export(
        TRANSLATION_CONTRACT_MODULE,
        "parseTranslationGate",
        receipt,
    ) is None


def test_complete_material_result_exposes_only_the_closed_public_shape():
    base = {
        "material": {
            "requested": {"kind": "paper", "slug": "exact-paper"},
            "canonical": {"kind": "paper", "slug": "exact-paper"},
        },
        "receipts": [{"legacy_sentinel": "must-not-cross-public-boundary"}],
    }
    artifacts = [{"role": "canonical", "path": "vault/papers/exact-paper.md"}]

    result = run_workflow_export(
        RESULT_MODULE,
        "completeMaterialResult",
        base,
        artifacts,
        None,
    )

    assert result == {
        "schema_version": "quasi.material.result/0.1",
        "material": base["material"],
        "terminal": "complete",
        "issue": None,
        "artifacts": artifacts,
        "next": None,
    }


def test_topic_incomplete_result_has_only_closed_pending_rows():
    base = {
        "material": {
            "requested": {"kind": "topic", "slug": "exact-topic"},
            "canonical": {"kind": "topic", "slug": "exact-topic"},
        },
    }
    issue = {
        "code": "topic.round_limit",
        "operation": None,
        "summary": "The bounded round ended with unseen work.",
        "retryable": False,
        "observation_request": None,
    }
    artifacts = [
        {"role": "outline", "path": "vault/topics/exact-topic/outline.md"},
        {"role": "overview", "path": "vault/topics/exact-topic/overview.md"},
        {"role": "resources", "path": "vault/topics/exact-topic/resources.md"},
    ]
    pending = [
        {
            "kind": "material",
            "material_kind": "paper",
            "requested_slug": "next-paper",
            "subq": "sq-1",
            "role": "counterpoint",
            "fingerprint": "f-1",
        },
        {
            "kind": "webcard",
            "card_slug": "next-card",
            "subq": "sq-2",
            "fingerprint": "f-2",
        },
    ]

    result = run_workflow_export(
        RESULT_MODULE,
        "incompleteTopicMaterialResult",
        base,
        issue,
        artifacts,
        pending,
    )

    assert result == {
        "schema_version": "quasi.material.result/0.1",
        **base,
        "terminal": "incomplete",
        "issue": issue,
        "artifacts": artifacts,
        "pending_work": pending,
    }


@pytest.mark.parametrize("terminal", ["blocked", "failed"])
def test_stopped_material_result_has_closed_terminal_constructor(terminal: str):
    base = {
        "material": {
            "requested": {"kind": "talk", "slug": "exact-talk"},
            "canonical": None,
        },
    }
    issue = {
        "code": "material.stopped",
        "operation": "talk.prepare",
        "summary": "The material stopped.",
        "retryable": False,
        "observation_request": None,
    }

    result = run_workflow_export(
        RESULT_MODULE,
        f"{terminal}MaterialResult",
        base,
        issue,
    )

    assert result == {
        "schema_version": "quasi.material.result/0.1",
        **base,
        "terminal": terminal,
        "issue": issue,
    }

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from workflow_test_support import run_workflow_export


INPUT_MODULE = "scripts/workflows/shared/material-input.mts"
RESULT_MODULE = "scripts/workflows/shared/material-result.mts"

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

PAPER_OBSERVATION = {
    "schema_version": "quasi.status/0.1",
    "kind": "paper",
    "slug": "exact-paper",
    "stages": [
        {"stage": "acquire", "complete": False, "evidence": []},
        {"stage": "prepare", "complete": False, "evidence": []},
        {"stage": "analyse", "complete": False, "evidence": []},
    ],
    "next_stage": "acquire",
    "refs": {"outputs": ["sources/exact-paper.pdf"]},
}


def valid_input() -> dict[str, Any]:
    return {
        "identity": deepcopy(PAPER_IDENTITY),
        "observation": deepcopy(PAPER_OBSERVATION),
        "options": {},
    }


def parse_paper(value: Any) -> dict[str, Any]:
    return run_workflow_export(INPUT_MODULE, "parseLeafMaterialInput", value, "paper")


def assert_invalid_input(result: dict[str, Any], requested_slug: str | None) -> None:
    assert result == {
        "ok": False,
        "result": {
            "schema_version": "quasi.material.result/0.1",
            "material": {
                "requested": {"kind": "paper", "slug": requested_slug},
                "canonical": None,
            },
            "receipts": [],
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


def test_missing_identity_blocks_before_dispatch():
    value = valid_input()
    del value["identity"]

    assert_invalid_input(parse_paper(value), None)


def test_malformed_slug_blocks_before_dispatch():
    value = valid_input()
    value["identity"]["slug"] = "Not/A-Slug"

    assert_invalid_input(parse_paper(value), None)


def test_missing_observation_blocks_before_dispatch():
    value = valid_input()
    del value["observation"]

    assert_invalid_input(parse_paper(value), "exact-paper")


def test_valid_material_envelope_builds_one_sparse_observation_map():
    result = parse_paper(valid_input())

    assert result == {
        "ok": True,
        "value": {
            "identity": PAPER_IDENTITY,
            "observations": {
                "__map_entries__": [["paper:exact-paper", PAPER_OBSERVATION]]
            },
            "options": {},
            "userDecision": None,
        },
    }


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
    observation = {
        "schema_version": "quasi.status/0.1",
        "kind": "translation",
        "slug": "exact-paper",
        "target_language": "fr-FR",
        "stages": [
            {"stage": "acquire", "complete": True, "evidence": ["sources/exact-paper.pdf"]},
            {"stage": "prepare", "complete": False, "evidence": []},
        ],
        "next_stage": "prepare",
        "refs": {"source": "sources/exact-paper.pdf", "derivatives": []},
    }
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
    observation = {
        "schema_version": "quasi.status/0.1",
        "kind": "translation",
        "slug": "exact-paper",
        "stages": [
            {"stage": "acquire", "complete": True, "evidence": ["sources/exact-paper.pdf"]},
            {"stage": "prepare", "complete": False, "evidence": []},
        ],
        "next_stage": "prepare",
        "refs": {"source": "sources/exact-paper.pdf", "derivatives": []},
    }

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
    observation = {
        "schema_version": "quasi.status/0.1",
        "kind": "translation",
        "slug": "exact-paper",
        "target_language": "zh-cn",
        "stages": [
            {"stage": "acquire", "complete": True, "evidence": ["sources/exact-paper.pdf"]},
            {"stage": "prepare", "complete": False, "evidence": []},
        ],
        "next_stage": "prepare",
        "refs": {"source": "sources/exact-paper.pdf", "derivatives": []},
    }

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
    observation = {
        "schema_version": "quasi.status/0.1",
        "kind": "translation",
        "slug": "exact-paper",
        "target_language": "zh-CN",
        "stages": [
            {"stage": "acquire", "complete": True, "evidence": ["sources/exact-paper.pdf"]},
            {"stage": "prepare", "complete": False, "evidence": []},
        ],
        "next_stage": "prepare",
        "refs": {"source": "sources/exact-paper.pdf", "derivatives": []},
    }

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
        "value": {
            "tmp_path": ".quasi/temp/exact-book.pdf",
            "year_evidence": {"recommended_year": 2020},
            "action": "use-recommended-year",
        },
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


def test_gate_decision_values_keep_their_evidence_bindings():
    book_value = {
        "tmp_path": ".quasi/temp/exact-book.pdf",
        "year_evidence": {"recommended_year": 2020},
        "action": "accept-current",
    }
    translation_value = {
        "candidates_fingerprint": "a" * 64,
        "source_path": "sources/exact-paper.pdf",
    }

    assert run_workflow_export(
        INPUT_MODULE,
        "parseBookYearDecisionValue",
        book_value,
    ) == book_value
    assert run_workflow_export(
        INPUT_MODULE,
        "parseTranslationSourceDecisionValue",
        translation_value,
    ) == translation_value


def test_complete_material_result_preserves_closed_host_envelope():
    base = {
        "material": {
            "requested": {"kind": "paper", "slug": "exact-paper"},
            "canonical": {"kind": "paper", "slug": "exact-paper"},
        },
        "receipts": [{"terminal": {"status": "complete", "issue": None}}],
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
        **base,
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
        "receipts": [],
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
        "receipts": [],
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

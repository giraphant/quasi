from __future__ import annotations

from typing import Any

import pytest

from test_material_plans import (
    AUTHOR_SEED,
    audit_complete,
    author_discovery_complete,
    author_observation,
    author_resolve_complete,
    book_identity,
    canonical_book_input,
    canonical_input,
    canonical_talk_input,
    canonical_translation_input,
    translation_complete,
)
from test_topic_plan import recall_complete, topic_input
from workflow_test_support import (
    run_generated_workflow,
    run_workflow_entry,
    workflow_bundle_inputs,
)


ENTRIES = ("paper", "book", "talk", "translation", "author", "topic")


def _entry_input(entry: str) -> dict[str, Any]:
    if entry == "paper":
        return canonical_input(canonical=True, admitted=True)
    if entry == "book":
        return canonical_book_input(
            manifest=True,
            chapter_inputs=(True, True),
            chapter_outputs=(True, True),
        )
    if entry == "talk":
        return canonical_talk_input(canonical=True)
    if entry == "translation":
        return canonical_translation_input()
    if entry == "author":
        return {
            "seed": AUTHOR_SEED,
            "observation": author_observation(),
            "options": {},
        }
    return topic_input()


def _abi_case(entry: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    value = _entry_input(entry)
    if entry in {"paper", "book", "talk"}:
        return value, [audit_complete()]
    if entry == "translation":
        return value, [translation_complete()]
    if entry == "author":
        book = {"kind": "book", **book_identity("book-one", "Book One")}
        return value, [
            author_discovery_complete([book]),
            author_discovery_complete([]),
            author_resolve_complete([book]),
        ]
    value["options"]["maxRounds"] = 0
    return value, [recall_complete()]


@pytest.mark.parametrize("entry", ENTRIES)
def test_named_entries_reject_unknown_input_before_agent_dispatch(entry: str) -> None:
    value = _entry_input(entry)
    value["cursor"] = "hidden-state"

    report = run_workflow_entry(entry, value)

    assert report["agentCalls"] == 0
    assert report["value"]["terminal"] == "blocked"
    assert report["value"]["issue"]["code"] == "material.invalid_input"


@pytest.mark.parametrize(
    ("entry", "catalogs", "rows", "contracts"),
    [
        ("paper", {"paper"}, {"paper", "search"}, {"paper", "book", "search"}),
        ("book", {"book"}, {"book", "search"}, {"book", "paper", "search"}),
        ("talk", {"talk"}, {"talk"}, {"talk"}),
        ("translation", {"translation"}, {"translation"}, {"translation"}),
        (
            "author",
            {"author", "paper", "book"},
            {"author", "paper", "book", "search"},
            {"author", "paper", "book", "search"},
        ),
        (
            "topic",
            {"topic", "paper", "book", "talk"},
            {"topic", "paper", "book", "talk", "search"},
            {"topic", "paper", "book", "talk", "search"},
        ),
    ],
)
def test_named_entries_import_only_their_composed_operation_domains(
    entry: str,
    catalogs: set[str],
    rows: set[str],
    contracts: set[str],
) -> None:
    inputs = workflow_bundle_inputs(f"scripts/workflows/{entry}.entry.mts")
    catalog_prefix = "scripts/workflows/operations/catalogs/"
    row_prefix = "scripts/workflows/operations/rows/"
    contract_prefix = "scripts/workflows/contracts/"

    assert {
        item.removeprefix(catalog_prefix).removesuffix(".mts")
        for item in inputs
        if item.startswith(catalog_prefix)
    } == catalogs
    assert {
        item.removeprefix(row_prefix).removesuffix(".mts")
        for item in inputs
        if item.startswith(row_prefix)
    } == rows
    assert {
        item.removeprefix(contract_prefix).removesuffix(".mts")
        for item in inputs
        if item.startswith(contract_prefix)
    } == contracts
    assert "scripts/workflows/shared/dispatch-prepared.mts" in inputs


@pytest.mark.parametrize("entry", ENTRIES)
def test_generated_named_workflow_returns_its_source_entry_result(entry: str) -> None:
    value, outputs = _abi_case(entry)

    source = run_workflow_entry(entry, value, outputs)
    generated = run_generated_workflow(entry, value, outputs)

    assert generated == source

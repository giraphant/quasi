from __future__ import annotations

import json
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
    chapter_complete,
    chapter_output_observation_mismatch,
    prepare_complete,
    provisional_input,
    search_webpage_redirect,
    translation_complete,
)
from test_topic_plan import recall_complete, topic_input
from test_webpage_plan import (
    SLUG as WEBPAGE_SLUG,
    audit_complete as webpage_audit_complete,
    canonical_webpage_input,
    identify_complete as webpage_identify_complete,
    provisional_webpage_input,
)
from workflow_test_support import (
    ROOT,
    run_generated_workflow,
    run_workflow_entry,
    workflow_bundle_inputs,
)


ENTRIES = (
    "archive",
    "paper",
    "book",
    "talk",
    "translation",
    "author",
    "topic",
    "webpage",
)


def _entry_input(entry: str) -> dict[str, Any]:
    if entry == "archive":
        from test_archive_plan import archive_input
        return archive_input(usable=True, topics=["exact-topic"])
    if entry == "paper":
        return canonical_input(
            source=True,
            prepared=True,
            canonical=True,
            admitted=True,
        )
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
    if entry == "webpage":
        return canonical_webpage_input(snapshot=True, prepared=True, canonical=True)
    return topic_input()


def _abi_case(entry: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    value = _entry_input(entry)
    if entry == "paper":
        return value, [prepare_complete(), audit_complete()]
    if entry in {"book", "talk", "archive"}:
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
    if entry == "webpage":
        return value, [webpage_audit_complete()]
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
        (
            "paper",
            {"paper"},
            {"paper", "search", "ocr-generation"},
            {"paper", "book", "search", "ocr-generation"},
        ),
        (
            "book",
            {"book"},
            {"book", "search", "ocr-generation"},
            {"book", "paper", "search", "ocr-generation"},
        ),
        ("talk", {"talk"}, {"talk"}, {"talk"}),
        ("translation", {"translation"}, {"translation"}, {"translation"}),
        (
            "author",
            {"author", "paper", "book"},
            {"author", "paper", "book", "search", "ocr-generation"},
            {"author", "paper", "book", "search", "ocr-generation"},
        ),
        (
            "topic",
            {"topic", "paper", "book", "talk", "archive"},
            {"topic", "paper", "book", "talk", "search", "ocr-generation", "archive"},
            {"topic", "paper", "book", "talk", "search", "ocr-generation", "archive"},
        ),
        ("archive", {"archive"}, {"archive"}, {"archive"}),
        ("webpage", {"webpage"}, {"webpage"}, {"webpage"}),
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


@pytest.mark.parametrize("entry", ENTRIES)
def test_generated_named_workflow_accepts_one_json_string_transport_layer(
    entry: str,
) -> None:
    value, outputs = _abi_case(entry)

    direct = run_generated_workflow(entry, value, outputs)
    encoded = run_generated_workflow(entry, json.dumps(value), outputs)

    assert encoded == direct


@pytest.mark.parametrize("transport", ("malformed", "double_encoded"))
def test_generated_named_workflow_rejects_invalid_string_transports(
    transport: str,
) -> None:
    value: str = "{"
    if transport == "double_encoded":
        value = json.dumps(json.dumps(_entry_input("paper")))

    report = run_generated_workflow("paper", value)

    assert report["agentCalls"] == 0
    assert report["value"]["terminal"] == "blocked"
    assert report["value"]["issue"]["code"] == "material.invalid_input"


# The Workflow sandbox has no web-platform globals. A generated entry that reaches
# for one throws where the host cannot report it, so every material's web input
# collapses into `material.invalid_input` before any agent is dispatched.
ABSENT_SANDBOX_GLOBALS = (
    "new URL(",
    "globalThis.URL",
    "URLSearchParams",
    "TextEncoder",
    "TextDecoder",
    "structuredClone",
    "queueMicrotask",
    "fetch(",
    "require(",
    "process.env",
)


@pytest.mark.parametrize("entry", ENTRIES)
def test_generated_named_workflow_reaches_for_no_absent_sandbox_global(
    entry: str,
) -> None:
    source = (ROOT / ("deprecated/workflows" if entry == "topic" else "workflows") / f"{entry}.mjs").read_text()

    assert [name for name in ABSENT_SANDBOX_GLOBALS if name in source] == []


def test_generated_webpage_identifies_a_provisional_url_without_a_url_global() -> None:
    report = run_generated_workflow(
        "webpage",
        provisional_webpage_input(),
        [webpage_identify_complete()],
    )

    assert report["agentCalls"] == 1
    assert report["value"]["terminal"] == "needs_observation"
    assert report["value"]["routes"] == [
        {"kind": "webpage", "slug": WEBPAGE_SLUG}
    ]


def test_generated_paper_routes_a_web_article_without_a_url_global() -> None:
    report = run_generated_workflow(
        "paper",
        provisional_input(),
        [search_webpage_redirect()],
    )

    assert report["value"]["terminal"] == "complete"
    assert report["value"]["next"] == {
        "kind": "webpage",
        "url": "https://example.org/essay",
    }


def test_generated_book_recovers_the_qualified_chapter_observation_mismatch() -> None:
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(False, False),
    )
    report = run_generated_workflow(
        "book",
        value,
        [chapter_output_observation_mismatch(), chapter_complete()],
    )

    assert report["value"]["terminal"] == "needs_observation"
    assert report["value"]["routes"] == [
        {"kind": "book", "slug": "exact-book"}
    ]

from __future__ import annotations

from copy import deepcopy

import pytest

from workflow_test_support import run_generated_workflow, run_workflow_entry
from test_material_plans import audit_complete

SLUG = "apple-iphone-repair"
URL = "https://support.example.org/repair"
IDENTITY = {"slug": SLUG, "title": "iPhone repair manual", "kind": "document", "url": URL}
PATH = f"vault/archives/{SLUG}/archive.md"
COMPLETE = {"terminal": {"status": "complete", "issue": None}}


def archive_observation(*, usable=False, topics=None):
    return {
        "schema_version": "quasi.status/0.2", "kind": "archive", "slug": SLUG,
        "identity": {"type": "archive", "title": IDENTITY["title"], "kind": "document", "url": URL,
                     "created": "2026-09-21", "topics": topics or []} if usable else None,
        "facts": {"kind": "archive", "canonical": {"path": PATH, "present": usable, "usable": usable}},
    }


def archive_input(*, usable=False, topics=None):
    return {"seed": {"state": "canonical", "material_slug": SLUG, "identity": deepcopy(IDENTITY)},
            "observation": archive_observation(usable=usable, topics=topics), "options": {"topics": ["exact-topic"]}}


def test_generated_archive_identify_collect_observe_audit():
    initial = run_generated_workflow("archive", {"seed": {"state": "provisional", "url": URL}, "observation": None, "options": {"topics": ["exact-topic"]}}, [{**COMPLETE, "identity": IDENTITY}])
    result = initial["value"]
    assert result["terminal"] == "needs_observation"
    assert result["routes"] == [{"kind": "archive", "slug": SLUG}]
    resume = result["resume_seed"]
    assert resume["options"] == {"topics": ["exact-topic"]}
    written = run_generated_workflow("archive", {"seed": resume["seed"], "options": resume["options"], "observation": archive_observation()}, [COMPLETE])
    assert written["value"]["terminal"] == "needs_observation"
    assert written["agentCalls"] == 1
    completed = run_generated_workflow("archive", archive_input(usable=True, topics=["exact-topic"]), [audit_complete()])
    assert completed["value"]["terminal"] == "complete"
    assert completed["value"]["artifacts"] == [{"role": "canonical", "path": PATH}]


def test_archive_membership_merge_and_conflicting_owner_stop():
    value = archive_input(usable=True, topics=["older-topic"])
    result = run_workflow_entry("archive", value, [COMPLETE])
    assert result["value"]["terminal"] == "needs_observation"
    assert result["agentCalls"] == 1
    value["observation"]["identity"]["url"] = "https://other.example.org/"
    result = run_workflow_entry("archive", value)
    assert result["agentCalls"] == 0
    assert result["value"]["issue"]["code"] == "archive.identity_conflict"


def test_archive_unknown_writer_outcome_stops_without_replay():
    result = run_workflow_entry("archive", archive_input(), [None])
    assert result["agentCalls"] == 1
    assert result["value"]["terminal"] == "blocked"


@pytest.mark.parametrize("change", ["path", "kind", "cursor"])
def test_archive_rejects_invalid_envelope_before_dispatch(change):
    value = archive_input()
    if change == "path": value["observation"]["facts"]["canonical"]["path"] = "vault/webpages/x/webpage.md"
    if change == "kind": value["seed"]["identity"]["kind"] = "pdf"
    if change == "cursor": value["cursor"] = "hidden-state"
    result = run_workflow_entry("archive", value)
    assert result["agentCalls"] == 0
    assert result["value"]["issue"]["code"] == "material.invalid_input"

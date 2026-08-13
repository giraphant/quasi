from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from typing import Any

import pytest

from test_material_plans import PLAN_HARNESS
from workflow_test_support import ROOT


SLUG = "example-org-page"
URL = "https://example.org/page"
IDENTITY = {
    "slug": SLUG,
    "title": "Read-only title",
    "url": URL,
    "site": "Read-only site",
}


def artifact(path: str, usable: bool) -> dict[str, Any]:
    return {"path": path, "present": usable, "usable": usable}


def webpage_observation(
    *,
    snapshot: bool = False,
    prepared: bool = False,
    canonical: bool = False,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed_identity = identity
    if observed_identity is None and (snapshot or canonical):
        observed_identity = deepcopy(IDENTITY)
    return {
        "schema_version": "quasi.status/0.2",
        "kind": "webpage",
        "slug": SLUG,
        "identity": observed_identity,
        "facts": {
            "kind": "webpage",
            "snapshot": artifact(
                f"vault/webpages/{SLUG}/snapshot.webarchive", snapshot
            ),
            "prepared": artifact(
                f"processing/webpages/{SLUG}/source.md", prepared
            ),
            "canonical": artifact(
                f"vault/webpages/{SLUG}/webpage.md", canonical
            ),
            "captured_at": "2026-08-13T12:34:56Z" if snapshot else None,
        },
    }


def provisional_webpage_input(url: str = URL) -> dict[str, Any]:
    return {
        "seed": {"state": "provisional", "url": url},
        "observation": None,
        "options": {},
    }


def canonical_webpage_input(
    *,
    snapshot: bool = False,
    prepared: bool = False,
    canonical: bool = False,
) -> dict[str, Any]:
    return {
        "seed": {
            "state": "canonical",
            "material_slug": SLUG,
            "identity": deepcopy(IDENTITY),
        },
        "observation": webpage_observation(
            snapshot=snapshot,
            prepared=prepared,
            canonical=canonical,
        ),
        "options": {},
    }


def identify_complete(
    *, slug: str = SLUG, owner_slug: str | None = None
) -> dict[str, Any]:
    identity = {**deepcopy(IDENTITY), "slug": owner_slug or slug}
    return {
        "identity": identity,
        "local_owner": (
            {
                "slug": owner_slug,
                "path": f"vault/webpages/{owner_slug}/webpage.md",
            }
            if owner_slug is not None
            else None
        ),
        "terminal": {"status": "complete", "issue": None},
    }


def capture_complete() -> dict[str, Any]:
    return {
        "title": "Title from capture",
        "site": "Captured site",
        "captured_at": "2026-08-13T12:34:56Z",
        "sha256": "a" * 64,
        "size": 512,
        "terminal": {"status": "complete", "issue": None},
    }


def prepare_complete() -> dict[str, Any]:
    return {
        "source_sha256": "b" * 64,
        "source_size": 256,
        "terminal": {"status": "complete", "issue": None},
    }


def analyse_complete(action: str = "create") -> dict[str, Any]:
    return {
        "terminal": {
            "status": "complete",
            "issue": None,
            "action": action,
        },
    }


def audit_complete(
    *, escalated: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    diagnostics = escalated or []
    return {
        "remaining_violations": len(diagnostics),
        "escalated": diagnostics,
        "mutated_paths": [],
        "terminal": {"status": "complete", "issue": None},
    }


def failed_receipt(operation: str) -> dict[str, Any]:
    return {
        "title": "Read-only title",
        "site": "Read-only site",
        "captured_at": "2026-08-13T12:34:56Z",
        "sha256": "a" * 64,
        "size": 512,
        "terminal": {
            "status": "failed",
            "issue": {
                "code": "webpage.test_failure",
                "operation": operation,
                "summary": "The exact operation failed.",
                "user_question": None,
                "retryable": True,
            },
        }
    }


def run_webpage(value: dict[str, Any], outputs: list[Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            PLAN_HARNESS,
            json.dumps({"kind": "webpage", "input": value, "outputs": outputs}),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def operation_names(report: dict[str, Any]) -> list[str]:
    return [call["request"]["operation"] for call in report["calls"]]


def test_webpage_identify_requests_first_exact_observation() -> None:
    report = run_webpage(
        provisional_webpage_input(),
        [identify_complete(slug=SLUG)],
    )

    assert operation_names(report) == ["webpage.identify"]
    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [{"kind": "webpage", "slug": SLUG}]
    assert report["result"]["resume_seed"] == {
        "route": {"kind": "webpage", "slug": SLUG},
        "seed": {
            "state": "canonical",
            "material_slug": SLUG,
            "identity": IDENTITY,
        },
        "options": {},
    }


def test_webpage_identify_reuses_same_url_local_owner_route() -> None:
    owner_slug = "saved-example-page"
    report = run_webpage(
        provisional_webpage_input(),
        [identify_complete(owner_slug=owner_slug)],
    )

    assert report["result"]["routes"] == [
        {"kind": "webpage", "slug": owner_slug}
    ]
    assert report["result"]["resume_seed"]["seed"]["identity"] == {
        **IDENTITY,
        "slug": owner_slug,
    }


def test_webpage_empty_status_runs_linear_pipeline() -> None:
    report = run_webpage(
        canonical_webpage_input(),
        [capture_complete(), prepare_complete(), analyse_complete(), audit_complete()],
    )

    assert operation_names(report) == [
        "webpage.capture",
        "webpage.prepare",
        "webpage.analyse",
        "webpage.audit",
    ]
    assert report["pipelineCalls"] == 0
    assert report["result"]["terminal"] == "complete"
    analyse_request = report["calls"][2]["request"]
    assert analyse_request["identity"] == {
        **IDENTITY,
        "title": "Title from capture",
        "site": "Captured site",
    }
    assert analyse_request["captured_at"] == "2026-08-13T12:34:56Z"
    assert report["result"]["artifacts"] == [
        {
            "role": "snapshot",
            "path": f"vault/webpages/{SLUG}/snapshot.webarchive",
        },
        {
            "role": "normalized_text",
            "path": f"processing/webpages/{SLUG}/source.md",
        },
        {
            "role": "canonical",
            "path": f"vault/webpages/{SLUG}/webpage.md",
        },
    ]


def test_webpage_new_snapshot_invalidates_an_older_prepared_projection() -> None:
    report = run_webpage(
        canonical_webpage_input(prepared=True, canonical=True),
        [
            capture_complete(),
            prepare_complete(),
            analyse_complete("repair"),
            audit_complete(),
        ],
    )

    assert operation_names(report) == [
        "webpage.capture",
        "webpage.prepare",
        "webpage.analyse",
        "webpage.audit",
    ]
    prepare_request = report["calls"][1]["request"]
    assert prepare_request["output_observation"] == {
        "path": f"processing/webpages/{SLUG}/source.md",
        "present": True,
        "usable": False,
    }
    assert report["calls"][2]["request"]["mode"] == "repair"
    assert report["result"]["terminal"] == "complete"


@pytest.mark.parametrize(
    ("input_value", "outputs", "expected_operations"),
    [
        (
            canonical_webpage_input(snapshot=True),
            [prepare_complete(), analyse_complete(), audit_complete()],
            ["webpage.prepare", "webpage.analyse", "webpage.audit"],
        ),
        (
            canonical_webpage_input(snapshot=True, prepared=True),
            [prepare_complete(), analyse_complete(), audit_complete()],
            ["webpage.prepare", "webpage.analyse", "webpage.audit"],
        ),
        (
            canonical_webpage_input(snapshot=True, prepared=True, canonical=True),
            [audit_complete()],
            ["webpage.audit"],
        ),
        (
            canonical_webpage_input(snapshot=True, canonical=True),
            [prepare_complete(), audit_complete()],
            ["webpage.prepare", "webpage.audit"],
        ),
    ],
    ids=["snapshot", "prepared-reconcile", "canonical", "missing-projection"],
)
def test_webpage_durable_progress_selects_first_incomplete_stage(
    input_value: dict[str, Any],
    outputs: list[Any],
    expected_operations: list[str],
) -> None:
    report = run_webpage(input_value, outputs)

    assert operation_names(report) == expected_operations
    assert report["result"]["terminal"] == "complete"


@pytest.mark.parametrize(
    ("outputs", "expected_operation"),
    [
        (["__null__"], "webpage.capture"),
        ([capture_complete(), "__null__"], "webpage.prepare"),
        (
            [capture_complete(), prepare_complete(), "__null__"],
            "webpage.analyse",
        ),
    ],
)
def test_webpage_writer_ambiguity_requests_exact_observation(
    outputs: list[Any], expected_operation: str
) -> None:
    report = run_webpage(canonical_webpage_input(), outputs)

    assert operation_names(report)[-1] == expected_operation
    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [{"kind": "webpage", "slug": SLUG}]


def test_webpage_schema_valid_failure_passes_through() -> None:
    report = run_webpage(
        canonical_webpage_input(),
        [failed_receipt("webpage.capture")],
    )

    assert report["result"]["terminal"] == "failed"
    assert report["result"]["issue"]["code"] == "webpage.test_failure"
    assert "routes" not in report["result"]


def test_webpage_audit_repairs_analyse_owner_once_and_reaudits() -> None:
    diagnostic = {
        "path": f"vault/webpages/{SLUG}/webpage.md",
        "kind": "missing-section",
        "reason": "Summary is incomplete.",
    }
    report = run_webpage(
        canonical_webpage_input(snapshot=True, prepared=True, canonical=True),
        [
            audit_complete(escalated=[diagnostic]),
            prepare_complete(),
            analyse_complete("repair"),
            audit_complete(),
        ],
    )

    assert operation_names(report) == [
        "webpage.audit",
        "webpage.prepare",
        "webpage.analyse",
        "webpage.audit",
    ]
    assert report["calls"][2]["request"]["mode"] == "repair"
    assert report["calls"][2]["request"]["repair_diagnostics"] == [diagnostic]
    assert report["calls"][3]["request"]["pass"] == 2
    assert report["result"]["terminal"] == "complete"


def test_webpage_audit_rejects_a_foreign_repair_target() -> None:
    report = run_webpage(
        canonical_webpage_input(snapshot=True, prepared=True, canonical=True),
        [
            audit_complete(
                escalated=[
                    {
                        "path": "vault/webpages/other-page/webpage.md",
                        "kind": "missing-section",
                        "reason": "Foreign page.",
                    }
                ]
            )
        ],
    )

    assert operation_names(report) == ["webpage.audit"]
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.owner_ambiguity"


def test_webpage_second_dirty_audit_exhausts_the_single_repair() -> None:
    diagnostic = {
        "path": f"vault/webpages/{SLUG}/webpage.md",
        "kind": "missing-section",
        "reason": "Summary is incomplete.",
    }
    report = run_webpage(
        canonical_webpage_input(snapshot=True, prepared=True, canonical=True),
        [
            audit_complete(escalated=[diagnostic]),
            prepare_complete(),
            analyse_complete("repair"),
            audit_complete(escalated=[diagnostic]),
        ],
    )

    assert operation_names(report) == [
        "webpage.audit",
        "webpage.prepare",
        "webpage.analyse",
        "webpage.audit",
    ]
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.repair_exhausted"

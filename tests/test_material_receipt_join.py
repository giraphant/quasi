from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
MEMBER = ROOT / "scripts" / "workflows" / "materials" / "member.mjs"
INGRESS = ROOT / "scripts" / "workflows" / "materials" / "ingress.mjs"


def run_join(mode: str, payload: dict[str, Any]) -> Any:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = f"""
import {{
  projectChildMaterialResult,
  strictChildResult,
}} from {json.dumps(MEMBER.as_uri())}
import {{ normaliseMaterialRequest }} from {json.dumps(INGRESS.as_uri())}
const [mode, payload] = [process.argv[1], JSON.parse(process.argv[2])]
const value = mode === "project"
  ? projectChildMaterialResult(
      payload.result,
      normaliseMaterialRequest(payload.kind, payload.request),
    )
  : strictChildResult(payload.result, payload.demand)
process.stdout.write(JSON.stringify(value))
"""
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            script,
            mode,
            json.dumps(payload),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def paper_request(slug: str, title: str) -> dict[str, Any]:
    return {
        "slug": slug,
        "title": title,
        "authors": ["Ada Example"],
        "year": 2024,
        "doi": f"10.1000/{slug}",
        "journal": "Journal of Exact Joins",
    }


def paper_result(slug: str, title: str) -> dict[str, Any]:
    request = paper_request(slug, title)
    identity = {
        "slug": slug,
        "title": title,
        "authors": request["authors"],
        "year": 2024,
        "doi": request["doi"],
        "oa_url": None,
        "url": None,
        "journal": request["journal"],
        "confidence": "high",
    }
    search = {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "material.search",
        "stage": "Search",
        "material_key": f"paper:{slug}",
        "effect": "readonly",
        "attempt": 1,
        "kind": "paper",
        "identity": identity,
        "local_owner": None,
        "confidence": "high",
        "observations": [
            {
                "source": "fixture",
                "query": title,
                "summary": "exact identity",
            }
        ],
        "terminal": {"status": "complete", "issue": None},
    }
    canonical = f"vault/papers/{slug}.md"
    return {
        "slug": slug,
        "status": "ok",
        "material_receipt": {
            "schema_version": "quasi.material-loop.receipt/0.2",
            "material_key": f"paper:{slug}",
            "kind": "paper",
            "id": slug,
            "status": "complete",
            "disposition": "created",
            "stage": "audit",
            "artifacts": [
                {
                    "role": "canonical",
                    "path": canonical,
                    "exists": True,
                    "usable": True,
                    "producer": "paper.analyse",
                }
            ],
            "operations": [{"key": "paper.synthetic"}],
            "audit": {
                "schema_version": "quasi.operation.paper.audit.receipt/0.2",
                "key": "paper.audit",
                "effect": "writer",
                "status": "clean",
                "attempt": 1,
                "target_path": canonical,
                "artifact_roles": ["canonical"],
                "pass": 1,
                "remaining_violations": 0,
                "escalated": [],
                "mutated_paths": [],
                "failure": None,
            },
            "freshness": {
                "observation": "unknown",
                "basis": "operation-receipts-and-final-audit",
            },
            "warnings": [],
            "failure": None,
            "user_gate": None,
            "resume": None,
        },
        "ingress_receipt": {
            "schema_version": "quasi.material-ingress.receipt/0.2",
            "request_key": f"paper:{slug}",
            "kind": "paper",
            "status": "resolved",
            "stage": "search",
            "request": {
                "slug": slug,
                "title": title,
                "authors": request["authors"],
                "year": 2024,
                "doi": request["doi"],
                "oa_url": None,
                "url": None,
                "journal": request["journal"],
            },
            "operations": [search],
            "identity": {
                "slug": slug,
                "meta": {
                    "title": title,
                    "authors": request["authors"],
                    "year": 2024,
                    "doi": request["doi"],
                    "oa_url": None,
                    "url": None,
                    "journal": request["journal"],
                    "confidence": "verified",
                },
            },
            "failure": None,
            "user_gate": None,
            "resume": None,
        },
    }


def complete_book_result(slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    demand = {
        "material_key": f"book:{slug}",
        "kind": "book",
        "id": slug,
        "title": "Exact Book",
    }
    root = f"vault/books/{slug}"
    result = {
        "slug": slug,
        "status": "ok",
        "material_receipt": {
            "schema_version": "quasi.material-loop.receipt/0.2",
            "material_key": demand["material_key"],
            "kind": "book",
            "id": slug,
            "status": "complete",
            "disposition": "created",
            "stage": "audit",
            "artifacts": [
                {
                    "role": "canonical",
                    "path": f"{root}/00-overview.md",
                    "exists": True,
                    "usable": None,
                    "producer": "book.synthesise",
                },
                {
                    "role": "chapter_canonical",
                    "path": f"{root}/ch01-opening.md",
                    "exists": True,
                    "usable": None,
                    "producer": "chapter.analyse",
                },
            ],
            "operations": [{"key": "book.synthetic"}],
            "audit": [
                {
                    "schema_version": "quasi.operation.book.audit.receipt/0.1",
                    "key": "book.audit",
                    "effect": "writer",
                    "status": "clean",
                    "attempt": 1,
                    "target_path": root,
                    "remaining_violations": 0,
                    "escalated": [],
                    "mutated_paths": [],
                }
            ],
            "freshness": {
                "observation": "unknown",
                "basis": "operation-receipts-and-final-audit",
            },
            "warnings": [],
            "failure": None,
            "user_gate": None,
            "expected_slots": ["01"],
            "present_slots": ["01"],
            "missing_slots": [],
            "resume": None,
        },
    }
    return result, demand


def paper_gate_result(slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    issue = {
        "code": "paper.source_choice_required",
        "operation": "paper.prepare",
        "summary": "Two exact source generations remain plausible.",
        "user_question": "Which source generation is authoritative?",
        "retryable": False,
    }
    operation = {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "paper.prepare",
        "stage": "Prepare",
        "material_key": f"paper:{slug}",
        "effect": "writer",
        "attempt": 1,
        "source_path": f"sources/{slug}.pdf",
        "selected_input": None,
        "artifacts": [],
        "steps": [],
        "diagnostics": [],
        "terminal": {
            "status": "needs_input",
            "issue": issue,
        },
    }
    gate = {
        "schema_version": "quasi.user-gate.stage/0.1",
        "operation_key": "paper.prepare",
        "kind": "stage_needs_input",
        "issue": issue,
        "candidates": [],
        "conflicts": [],
        "question": issue["user_question"],
    }
    result = {
        "slug": slug,
        "material_receipt": {
            "schema_version": "quasi.material-loop.receipt/0.2",
            "material_key": f"paper:{slug}",
            "kind": "paper",
            "id": slug,
            "status": "needs_input",
            "disposition": None,
            "stage": "prepare",
            "artifacts": [],
            "operations": [operation],
            "audit": None,
            "freshness": {
                "observation": "unknown",
                "basis": "operation-receipts-and-final-audit",
            },
            "warnings": [],
            "failure": {
                "code": issue["code"],
                "operation_key": "paper.prepare",
                "outcome": "known",
                "retryable": False,
                "message": issue["summary"],
            },
            "user_gate": gate,
            "resume": {
                "operation_key": "paper.user-gate",
                "stage": "prepare",
            },
        },
    }
    demand = {
        "material_key": f"paper:{slug}",
        "kind": "paper",
        "id": slug,
        "title": "Gate Paper",
    }
    return result, demand


def test_batch_projection_binds_the_exact_request_and_search_proof() -> None:
    exact = paper_result("paper-one", "Paper One")
    payload = {
        "kind": "paper",
        "request": paper_request("paper-one", "Paper One"),
        "result": exact,
    }
    assert run_join("project", payload)["id"] == "paper-one"

    swapped = copy.deepcopy(payload)
    swapped["request"] = paper_request("paper-two", "Paper Two")
    assert run_join("project", swapped) is None

    no_search = copy.deepcopy(payload)
    no_search["result"]["ingress_receipt"]["operations"] = []
    assert run_join("project", no_search) is None


def test_batch_projection_distinguishes_invalid_search_from_owner_mismatch(
) -> None:
    slug = "paper-one"
    request = paper_request(slug, "Paper One")
    base = paper_result(slug, "Paper One")

    invalid_search = copy.deepcopy(base)
    invalid_search.pop("material_receipt")
    search = invalid_search["ingress_receipt"]["operations"][0]
    search["identity"] = None
    search["local_owner"] = None
    search["confidence"] = "low"
    invalid_search["ingress_receipt"].update(
        {
            "status": "failed",
            "stage": "search",
            "identity": None,
            "failure": {
                "code": "material.search_receipt_invalid",
                "operation_key": "material.search",
                "outcome": "known",
                "retryable": False,
                "message": (
                    "Search did not return the exact identity contract"
                ),
            },
            "resume": None,
        }
    )
    projected = run_join(
        "project",
        {"kind": "paper", "request": request, "result": invalid_search},
    )
    assert projected["status"] == "failed"
    assert projected["issue"]["code"] == "material.search_receipt_invalid"

    false_owner_mismatch = copy.deepcopy(base)
    false_owner_mismatch.pop("material_receipt")
    false_owner_mismatch["ingress_receipt"].update(
        {
            "status": "failed",
            "stage": "resolve",
            "identity": None,
            "failure": {
                "code": "material.search_owner_mismatch",
                "operation_key": "material.search",
                "outcome": "known",
                "retryable": False,
                "message": (
                    "Search did not resolve the selected canonical slug"
                ),
            },
            "resume": None,
        }
    )
    assert run_join(
        "project",
        {
            "kind": "paper",
            "request": request,
            "result": false_owner_mismatch,
        },
    ) is None

    real_owner_mismatch = copy.deepcopy(false_owner_mismatch)
    real_owner_mismatch["ingress_receipt"]["operations"][0][
        "local_owner"
    ] = {
        "identity_slug": "different-paper",
        "vault_slug": None,
        "path": None,
        "match": None,
    }
    projected = run_join(
        "project",
        {
            "kind": "paper",
            "request": request,
            "result": real_owner_mismatch,
        },
    )
    assert projected["status"] == "failed"
    assert projected["issue"]["code"] == "material.search_owner_mismatch"


def test_paper_identity_conflict_and_blocked_resume_are_exact() -> None:
    slug = "paper-one"
    request = paper_request(slug, "Paper One")
    conflict = paper_result(slug, "Paper One")
    conflict["status"] = "blocked"
    conflict["material_receipt"] = {
        "schema_version": "quasi.material-loop.receipt/0.2",
        "material_key": f"paper:{slug}",
        "kind": "paper",
        "id": slug,
        "status": "blocked",
        "disposition": None,
        "stage": "identity",
        "artifacts": [],
        "operations": [],
        "audit": None,
        "freshness": {
            "observation": "unknown",
            "basis": "operation-receipts-and-final-audit",
        },
        "warnings": [],
        "failure": {
            "code": "paper.identity_conflict",
            "operation_key": "paper.identity",
            "outcome": "known",
            "retryable": False,
            "message": "conflicting paper identity for one material key",
        },
        "user_gate": None,
        "resume": None,
    }
    projected = run_join(
        "project",
        {"kind": "paper", "request": request, "result": conflict},
    )
    assert projected["status"] == "blocked"
    assert projected["resume"] is None

    impossible_resume = copy.deepcopy(conflict)
    impossible_resume["material_receipt"]["stage"] = "prepare"
    impossible_resume["material_receipt"]["operations"] = [
        {"key": "paper.synthetic"}
    ]
    impossible_resume["material_receipt"]["resume"] = {
        "operation_key": "evil.resume"
    }
    assert run_join(
        "project",
        {
            "kind": "paper",
            "request": request,
            "result": impossible_resume,
        },
    ) is None


def test_book_join_rejects_foreign_or_unusable_canonical_artifacts() -> None:
    result, demand = complete_book_result("exact-book")
    assert run_join("strict", {"result": result, "demand": demand})

    foreign = copy.deepcopy(result)
    foreign["material_receipt"]["artifacts"][1]["path"] = (
        "vault/books/other-book/ch01-opening.md"
    )
    assert run_join("strict", {"result": foreign, "demand": demand}) is None

    unusable = copy.deepcopy(result)
    unusable["material_receipt"]["artifacts"][1]["usable"] = False
    assert run_join("strict", {"result": unusable, "demand": demand}) is None

    unusable_overview = copy.deepcopy(result)
    unusable_overview["material_receipt"]["artifacts"][0]["usable"] = False
    assert (
        run_join("strict", {"result": unusable_overview, "demand": demand})
        is None
    )

    suffixed_slot = copy.deepcopy(result)
    suffixed_slot["material_receipt"]["expected_slots"] = ["01a"]
    suffixed_slot["material_receipt"]["present_slots"] = ["01a"]
    suffixed_slot["material_receipt"]["artifacts"][1]["path"] = (
        "vault/books/exact-book/ch01a-opening.md"
    )
    assert run_join(
        "strict", {"result": suffixed_slot, "demand": demand}
    )

    duplicate_slug = copy.deepcopy(result)
    duplicate_slug["material_receipt"]["expected_slots"] = ["01", "02"]
    duplicate_slug["material_receipt"]["present_slots"] = ["01", "02"]
    duplicate_slug["material_receipt"]["artifacts"].append(
        {
            "role": "chapter_canonical",
            "path": "vault/books/exact-book/ch02-opening.md",
            "exists": True,
            "usable": None,
            "producer": "chapter.analyse",
        }
    )
    assert run_join(
        "strict", {"result": duplicate_slug, "demand": demand}
    ) is None


def test_stage_user_gate_must_echo_the_correlated_operation() -> None:
    result, demand = paper_gate_result("gate-paper")
    assert run_join("strict", {"result": result, "demand": demand})

    mutated = copy.deepcopy(result)
    mutated["material_receipt"]["user_gate"]["candidates"] = [
        {"path": "sources/foreign.pdf"}
    ]
    assert run_join("strict", {"result": mutated, "demand": demand}) is None

    foreign = copy.deepcopy(result)
    foreign["material_receipt"]["operations"][0]["material_key"] = (
        "paper:other-paper"
    )
    assert run_join("strict", {"result": foreign, "demand": demand}) is None

    split_issue = copy.deepcopy(result)
    split_issue["material_receipt"]["failure"]["code"] = (
        "paper.unrelated_failure"
    )
    assert (
        run_join("strict", {"result": split_issue, "demand": demand})
        is None
    )

    foreign_resume = copy.deepcopy(result)
    foreign_resume["material_receipt"]["resume"] = {
        "operation_key": "paper.user-gate",
        "stage": "audit",
    }
    assert (
        run_join("strict", {"result": foreign_resume, "demand": demand})
        is None
    )

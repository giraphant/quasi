from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from typing import Any

import pytest

from workflow_test_support import ROOT


PLAN_HARNESS = r"""
import { resolve } from "node:path";
import { build } from "esbuild";

const root = process.cwd();
const config = JSON.parse(process.argv[1]);

async function load(source) {
  const built = await build({
    absWorkingDir: root,
    bundle: true,
    entryPoints: [resolve(root, source)],
    format: "esm",
    legalComments: "none",
    logLevel: "silent",
    platform: "node",
    target: ["es2022"],
    treeShaking: true,
    write: false,
  });
  const code = built.outputFiles[0].text;
  return import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
}

const plan = await load("scripts/workflows/plans/paper.mts");
const contract = await load("scripts/workflows/contracts/paper.mts");
const parsed = contract.parsePaperRunInput(config.input);
if (!parsed.ok) throw new Error("test input did not parse");

const calls = [];
const outputs = [...config.outputs];
let pipelineCalls = 0;
const runtime = {
  agent: async (prompt, options) => {
    const start = prompt.indexOf("{");
    const request = JSON.parse(prompt.slice(start));
    calls.push({ request, options });
    const output = outputs.shift();
    if (output === "__throw__") throw new Error("agent disappeared");
    return output === "__null__" ? null : output;
  },
  pipeline: async (items, worker) => {
    pipelineCalls += 1;
    return Promise.all(items.map(worker));
  },
};

const result = await plan.runPaperPlan(runtime, parsed.value);
process.stdout.write(JSON.stringify({
  result,
  calls,
  pipelineCalls,
  remaining: outputs.length,
}));
"""


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


def paper_observation(
    slug: str,
    *,
    source: bool = False,
    prepared: bool = False,
    canonical: bool = False,
    admitted: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "quasi.status/0.2",
        "kind": "paper",
        "slug": slug,
        "identity": (
            {
                "title": PAPER_IDENTITY["title"],
                "authors": PAPER_IDENTITY["authors"],
                "year": PAPER_IDENTITY["year"],
            }
            if admitted
            else None
        ),
        "facts": {
            "kind": "paper",
            "source": {
                "path": f"sources/{slug}.pdf",
                "present": source,
                "usable": source,
            },
            "prepared": [
                {
                    "path": f"processing/papers/{slug}/source.txt",
                    "present": prepared,
                    "usable": prepared,
                },
                {
                    "path": f"processing/papers/{slug}/ocr.txt",
                    "present": False,
                    "usable": False,
                },
            ],
            "canonical": {
                "path": f"vault/papers/{slug}.md",
                "present": canonical,
                "usable": canonical,
            },
        },
    }


def provisional_input() -> dict[str, Any]:
    return {
        "seed": {
            "state": "provisional",
            "requested_slug": "request-paper",
            "hints": {"doi": "10.1000/exact"},
        },
        "observation": paper_observation("request-paper"),
        "options": {},
    }


def canonical_input(
    *,
    material_slug: str = "exact-paper",
    source: bool = False,
    prepared: bool = False,
    canonical: bool = False,
    admitted: bool = False,
) -> dict[str, Any]:
    return {
        "seed": {
            "state": "canonical",
            "material_slug": material_slug,
            "identity": deepcopy(PAPER_IDENTITY),
        },
        "observation": paper_observation(
            material_slug,
            source=source,
            prepared=prepared,
            canonical=canonical,
            admitted=admitted,
        ),
        "options": {},
    }


def identity_decision(selected: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        {"kind": "paper", "identity": deepcopy(PAPER_IDENTITY)},
        {"kind": "book", "identity": deepcopy(BOOK_IDENTITY)},
    ]
    return {
        "material_key": "paper:request-paper",
        "operation": "material.search",
        "value": {
            "candidates": candidates,
            "conflicts": ["publication_type"],
            "selected_candidate": deepcopy(selected),
        },
    }


def search_needs_input() -> dict[str, Any]:
    return {
        "identity": None,
        "local_owner": None,
        "confidence": "low",
        "observations": [],
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": "material.identity_conflict",
                "operation": "material.search",
                "summary": "Choose the publication type.",
                "user_question": "Is this the paper or the book?",
                "retryable": False,
            },
            "candidates": [
                {"kind": "paper", "identity": deepcopy(PAPER_IDENTITY)},
                {"kind": "book", "identity": deepcopy(BOOK_IDENTITY)},
            ],
            "conflicts": ["publication_type"],
        },
    }


def search_complete(
    identity: dict[str, Any] = PAPER_IDENTITY,
    *,
    owner_slug: str | None = None,
) -> dict[str, Any]:
    owner = (
        {
            "identity_slug": identity["slug"],
            "vault_slug": owner_slug,
            "path": f"vault/papers/{owner_slug}.md",
            "match": "doi",
        }
        if owner_slug is not None
        else None
    )
    return {
        "identity": deepcopy(identity),
        "local_owner": owner,
        "confidence": identity["confidence"],
        "observations": [],
        "terminal": {"status": "complete", "issue": None},
    }


def acquire_complete() -> dict[str, Any]:
    return {
        "write_state": "written",
        "identity_verified": True,
        "attempts": [],
        "terminal": {
            "status": "complete",
            "issue": None,
            "disposition": "created",
            "source": "publisher",
        },
    }


def prepare_complete(slug: str = "exact-paper") -> dict[str, Any]:
    selected = f"processing/papers/{slug}/source.txt"
    return {
        "selected_input": selected,
        "artifacts": [
            {
                "role": "normalized_text",
                "path": selected,
                "exists": True,
                "usable": True,
            }
        ],
        "steps": [],
        "diagnostics": [],
        "terminal": {"status": "complete", "issue": None},
    }


def analyse_complete(action: str = "create") -> dict[str, Any]:
    return {
        "artifact_roles": ["canonical"],
        "terminal": {"status": "complete", "issue": None, "action": action},
    }


def audit_complete(
    *,
    escalated: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    diagnostics = escalated or []
    return {
        "remaining_violations": len(diagnostics),
        "escalated": diagnostics,
        "mutated_paths": [],
        "terminal": {"status": "complete", "issue": None},
    }


def run_paper(value: dict[str, Any], outputs: list[Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            PLAN_HARNESS,
            json.dumps({"input": value, "outputs": outputs}),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_paper_provisional_happy_path_carries_prepare_selected_input() -> None:
    report = run_paper(
        provisional_input(),
        [
            search_complete(),
            acquire_complete(),
            prepare_complete(),
            analyse_complete(),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
        "paper.acquire",
        "paper.prepare",
        "paper.analyse",
        "paper.audit",
    ]
    assert report["calls"][3]["request"]["input"] == {
        "role": "normalized_text",
        "path": "processing/papers/exact-paper/source.txt",
    }
    assert report["result"]["terminal"] == "complete"
    assert report["result"]["artifacts"] == [
        {
            "role": "canonical",
            "path": report["calls"][-1]["request"]["target"]["path"],
        }
    ]
    assert "receipts" not in report["result"]
    assert report["pipelineCalls"] == 0


def test_paper_admitted_canonical_starts_at_audit_and_ignores_stale_search_decision() -> None:
    value = canonical_input(canonical=True, admitted=True)
    value["userDecision"] = {
        "material_key": "paper:exact-paper",
        "operation": "material.search",
        "value": {"stale": True},
    }

    report = run_paper(value, [audit_complete()])

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "paper.audit"
    ]
    assert report["result"]["terminal"] == "complete"


def test_paper_search_lifts_only_the_typed_identity_gate() -> None:
    report = run_paper(provisional_input(), [search_needs_input()])

    assert report["result"]["terminal"] == "needs_input"
    assert report["result"]["gate"] == {
        "kind": "identity_conflict",
        "operation": "material.search",
        "material_key": "paper:request-paper",
        "question": "Is this the paper or the book?",
        "candidates": [
            {"kind": "paper", "identity": PAPER_IDENTITY},
            {"kind": "book", "identity": BOOK_IDENTITY},
        ],
        "conflicts": ["publication_type"],
    }


def test_paper_same_kind_decision_runs_one_owner_reconcile_search_under_gate_key() -> None:
    selected = {"kind": "paper", "identity": deepcopy(PAPER_IDENTITY)}
    value = provisional_input()
    value["userDecision"] = identity_decision(selected)

    report = run_paper(
        value,
        [search_complete(owner_slug="owned-paper"), audit_complete()],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
        "paper.audit",
    ]
    search_request = report["calls"][0]["request"]
    assert search_request["material_key"] == "paper:request-paper"
    assert search_request["requested_slug"] == "exact-paper"
    assert search_request["identity_decision"] == value["userDecision"]["value"]
    assert report["result"]["material"]["canonical"] == {
        "kind": "paper",
        "slug": "owned-paper",
    }


def test_paper_book_decision_returns_typed_next_without_dispatch() -> None:
    selected = {"kind": "book", "identity": deepcopy(BOOK_IDENTITY)}
    value = provisional_input()
    value["userDecision"] = identity_decision(selected)

    report = run_paper(value, [])

    assert report["calls"] == []
    assert report["result"]["terminal"] == "complete"
    assert report["result"]["artifacts"] == []
    assert report["result"]["next"] == selected


def test_paper_matching_but_incoherent_decision_stops_before_dispatch() -> None:
    value = provisional_input()
    value["userDecision"] = identity_decision(
        {
            "kind": "paper",
            "identity": {**deepcopy(PAPER_IDENTITY), "slug": "other-paper"},
        }
    )

    report = run_paper(value, [])

    assert report["calls"] == []
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.incoherent_gate"


def test_paper_prepared_resume_reconciles_prepare_to_rebuild_selected_input() -> None:
    report = run_paper(
        canonical_input(
            source=True,
            prepared=True,
            canonical=True,
            admitted=False,
        ),
        [
            search_complete(),
            prepare_complete(),
            analyse_complete("repair"),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
        "paper.prepare",
        "paper.analyse",
        "paper.audit",
    ]
    assert report["calls"][2]["request"]["input"]["path"] == (
        "processing/papers/exact-paper/source.txt"
    )
    assert report["calls"][2]["request"]["mode"] == "repair"


def test_paper_existing_canonical_reconciles_prepare_then_repairs_once() -> None:
    diagnostic = {
        "path": "vault/papers/exact-paper.md",
        "kind": "missing-section",
        "reason": "The Analysis section is absent.",
    }
    report = run_paper(
        canonical_input(canonical=True, admitted=True),
        [
            audit_complete(escalated=[diagnostic]),
            prepare_complete(),
            analyse_complete("repair"),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "paper.audit",
        "paper.prepare",
        "paper.analyse",
        "paper.audit",
    ]
    assert report["calls"][2]["request"]["mode"] == "repair"
    assert report["calls"][2]["request"]["repair_diagnostics"] == [diagnostic]
    assert report["calls"][3]["request"]["pass"] == 2
    assert report["result"]["terminal"] == "complete"


def test_paper_second_audit_escalation_stops_as_repair_exhausted() -> None:
    diagnostic = {
        "path": "vault/papers/exact-paper.md",
        "kind": "missing-section",
        "reason": "The Analysis section is absent.",
    }
    report = run_paper(
        canonical_input(canonical=True, admitted=True),
        [
            audit_complete(escalated=[diagnostic]),
            prepare_complete(),
            analyse_complete("repair"),
            audit_complete(escalated=[diagnostic]),
        ],
    )

    assert len(report["calls"]) == 4
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.repair_exhausted"


def test_paper_unknown_writer_stops_without_later_dispatch() -> None:
    report = run_paper(
        provisional_input(),
        [search_complete(), "__throw__"],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "material.search",
        "paper.acquire",
    ]
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.unknown_outcome"


def test_paper_foreign_audit_path_stops_without_repair_dispatch() -> None:
    report = run_paper(
        canonical_input(canonical=True, admitted=True),
        [
            audit_complete(
                escalated=[
                    {
                        "path": "vault/papers/other-paper.md",
                        "kind": "missing-section",
                        "reason": "The Analysis section is absent.",
                    }
                ]
            )
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "paper.audit"
    ]
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.owner_ambiguity"

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "pi-runner.mjs"
WORKFLOW = ROOT / "workflows" / "process-material.mjs"

NODE_HARNESS = r"""
import { createRunner } from __RUNNER_URI__
const config = JSON.parse(process.argv[1])
const indexes = new Map()
const trace = []
const missing = []
const invokeAgent = async ({ definition, prompt, options }) => {
  const label = options.label || definition.name
  const occurrence = indexes.get(label) || 0
  indexes.set(label, occurrence + 1)
  trace.push({
    label,
    occurrence: occurrence + 1,
    agent_type: options.agentType || definition.name,
    phase: options.phase || null,
    prompt: String(prompt),
    schema: options.schema || null,
  })
  const step = config.responses[label]?.[occurrence]
  if (step === undefined) {
    missing.push(`${label}#${occurrence + 1}`)
    return null
  }
  if (step?.throw) throw new Error(step.throw)
  return JSON.parse(JSON.stringify(step?.result ?? step))
}
const runner = createRunner({
  pluginRoot: config.plugin_root,
  projectCwd: config.project_cwd,
  concurrency: 4,
  timeoutMs: 5000,
  invokeAgent,
  log: () => {},
})
const result = await runner.runFile(config.workflow, config.args)
const unused = Object.fromEntries(
  Object.entries(config.responses)
    .map(([label, steps]) => [label, steps.length - (indexes.get(label) || 0)])
    .filter(([, count]) => count !== 0)
)
process.stdout.write(JSON.stringify({ result, trace, missing, unused }))
"""


def run_paper(
    tmp_path: Path,
    slug: str,
    responses: dict[str, list[Any]],
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = NODE_HARNESS.replace("__RUNNER_URI__", json.dumps(RUNNER.as_uri()))
    config = {
        "plugin_root": str(ROOT),
        "project_cwd": str(tmp_path),
        "workflow": str(WORKFLOW),
        "args": {
            "kind": "paper",
            "slug": slug,
            "meta": {
                "title": "A Verified Paper",
                "authors": ["Ada Example"],
                "year": 2024,
                "journal": "Journal of Examples",
                "doi": "10.1000/example",
            },
        },
        "responses": responses,
    }
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, json.dumps(config)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["missing"] == [], report
    assert report["unused"] == {}, report
    return report


def paths(slug: str) -> dict[str, str]:
    return {
        "source": f"sources/{slug}.pdf",
        "text": f"processing/papers/{slug}/source.txt",
        "ocr": f"processing/papers/{slug}/ocr.pdf",
        "ocr_text": f"processing/papers/{slug}/ocr.txt",
        "canonical": f"vault/papers/{slug}.md",
    }


def search(slug: str) -> dict[str, Any]:
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "material.search",
        "stage": "Search",
        "material_key": f"paper:{slug}",
        "effect": "readonly",
        "attempt": 1,
        "kind": "paper",
        "identity": {
            "slug": slug,
            "title": "A Verified Paper",
            "authors": ["Ada Example"],
            "year": 2024,
            "doi": "10.1000/example",
            "oa_url": None,
            "url": None,
            "journal": "Journal of Examples",
            "confidence": "high",
        },
        "local_owner": {
            "identity_slug": slug,
            "vault_slug": None,
            "path": None,
            "match": None,
        },
        "confidence": "high",
        "observations": [
            {"source": "crossref", "query": "10.1000/example", "summary": "exact"}
        ],
        "terminal": {"status": "complete", "issue": None},
    }


def acquire(slug: str) -> dict[str, Any]:
    return {
        "schema_version": "quasi.operation.paper.acquire.receipt/0.2",
        "key": "paper.acquire",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "material_key": f"paper:{slug}",
        "kind": "paper",
        "slug": slug,
        "output_path": paths(slug)["source"],
        "artifact_roles": ["source"],
        "disposition": "created",
        "write_state": "written",
        "identity_verified": True,
        "source": "doi_cascade",
        "doi": "10.1000/example",
        "failure_reason": None,
        "attempts": [],
        "failure": None,
    }


def stage_issue(
    operation: str,
    code: str,
    *,
    question: str | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    return {
        "code": code,
        "operation": operation,
        "summary": "The specialist could not establish readable text",
        "user_question": question,
        "retryable": retryable,
    }


def prepare(
    slug: str,
    *,
    status: str = "complete",
    selected: str | None = None,
) -> dict[str, Any]:
    p = paths(slug)
    completed = status == "complete"
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "paper.prepare",
        "stage": "Prepare",
        "material_key": f"paper:{slug}",
        "effect": "writer",
        "attempt": 1,
        "source_path": p["source"],
        "selected_input": selected or p["text"] if completed else None,
        "artifacts": (
            [
                {
                    "role": "normalized_text",
                    "path": selected or p["text"],
                    "exists": True,
                    "usable": True,
                }
            ]
            if completed
            else []
        ),
        "steps": [
            {
                "capability": "quasi-extract text",
                "outcome": "created" if completed else "failed",
                "summary": "Read representative beginning, middle, and end",
            }
        ],
        "diagnostics": [] if completed else ["body text remained unreadable"],
        "terminal": {
            "status": status,
            "issue": (
                None
                if completed
                else stage_issue(
                    "paper.prepare",
                    "paper.text_not_readable",
                    question=(
                        "Can you provide another source PDF?"
                        if status == "needs_input"
                        else None
                    ),
                )
            ),
        },
    }


def analyse(slug: str, input_path: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "quasi.operation.paper.analyse.receipt/0.1",
        "key": "paper.analyse",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "input_path": input_path or paths(slug)["text"],
        "output_path": paths(slug)["canonical"],
        "artifact_roles": ["canonical"],
        "action": "create",
        "failure": None,
    }


def audit(
    slug: str,
    *,
    status: str = "clean",
    pass_number: int = 1,
) -> dict[str, Any]:
    escalated: list[dict[str, str]] = []
    remaining = 0
    if status == "partial":
        remaining = 1
        escalated = [
            {
                "path": paths(slug)["canonical"],
                "kind": "schema",
                "reason": "missing exact section",
            }
        ]
    return {
        "schema_version": "quasi.operation.paper.audit.receipt/0.2",
        "key": "paper.audit",
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "target_path": paths(slug)["canonical"],
        "artifact_roles": ["canonical"],
        "pass": pass_number,
        "remaining_violations": remaining,
        "escalated": escalated,
        "mutated_paths": [],
        "failure": None,
    }


def base(slug: str) -> dict[str, list[Any]]:
    return {
        f"{slug}:search": [search(slug)],
        f"{slug}:acquire": [acquire(slug)],
        f"{slug}:prepare": [prepare(slug)],
        f"{slug}:analyse": [analyse(slug)],
        f"{slug}:audit": [audit(slug)],
    }


def labels(report: dict[str, Any]) -> list[str]:
    return [entry["label"] for entry in report["trace"]]


def test_paper_happy_path_is_one_prepare_stage(tmp_path: Path) -> None:
    slug = "paper-stage-happy"
    report = run_paper(tmp_path, slug, base(slug))

    assert report["result"]["status"] == "ok"
    assert labels(report) == [
        f"{slug}:search",
        f"{slug}:acquire",
        f"{slug}:prepare",
        f"{slug}:analyse",
        f"{slug}:audit",
    ]
    assert [entry["phase"] for entry in report["trace"]] == [
        "Search",
        "Acquire",
        "Prepare",
        "Analyse",
        "Audit",
    ]
    receipt = report["result"]["material_receipt"]
    assert receipt["status"] == "complete"
    assert receipt["user_gate"] is None
    assert [item.get("operation", item.get("key")) for item in receipt["operations"]] == [
        "paper.acquire",
        "paper.prepare",
        "paper.analyse",
        "paper.audit",
    ]
    assert receipt["operations"][0] == acquire(slug)
    assert receipt["operations"][-1] == receipt["audit"] == audit(slug)
    assert "per_item" not in report["trace"][1]["schema"]["properties"]


def test_prepare_prompt_gives_goal_capabilities_and_exact_refs(tmp_path: Path) -> None:
    slug = "paper-stage-envelope"
    report = run_paper(tmp_path, slug, base(slug))
    call = next(item for item in report["trace"] if item["label"] == f"{slug}:prepare")
    request = json.loads(call["prompt"])

    assert call["agent_type"] == "quasi:extract-agent"
    assert request["objective"].startswith("Produce one readable")
    assert request["refs"]["source"] == paths(slug)["source"]
    assert request["capabilities"] == [
        "quasi-extract text INPUT OUTPUT --json",
        "quasi-extract ocr INPUT OUTPUT --no-clobber --json",
        "Read exact normalized text artifacts",
    ]


def test_prepare_can_select_ocr_recovery_without_graph_ocr_branch(tmp_path: Path) -> None:
    slug = "paper-stage-ocr"
    responses = base(slug)
    responses[f"{slug}:prepare"] = [
        prepare(slug, selected=paths(slug)["ocr_text"])
    ]
    responses[f"{slug}:analyse"] = [analyse(slug, paths(slug)["ocr_text"])]
    report = run_paper(tmp_path, slug, responses)

    assert report["result"]["status"] == "ok"
    assert not any(label.endswith(":ocr") for label in labels(report))
    analysis_prompt = next(
        item["prompt"]
        for item in report["trace"]
        if item["label"] == f"{slug}:analyse"
    )
    analysis_request = json.loads(analysis_prompt[analysis_prompt.index("{") :])
    assert analysis_request["input"]["path"] == paths(slug)["ocr_text"]


@pytest.mark.parametrize("status", ["needs_input", "failed"])
def test_prepare_terminal_stops_before_analysis(
    tmp_path: Path,
    status: str,
) -> None:
    slug = f"paper-stage-{status.replace('_', '-')}"
    responses = {
        f"{slug}:search": [search(slug)],
        f"{slug}:acquire": [acquire(slug)],
        f"{slug}:prepare": [prepare(slug, status=status)],
    }
    report = run_paper(tmp_path, slug, responses)

    expected = "needs_input" if status == "needs_input" else "analyse_failed"
    assert report["result"]["status"] == expected
    assert labels(report)[-1] == f"{slug}:prepare"
    assert report["result"]["material_receipt"]["failure"]["code"] == (
        "paper.text_not_readable"
    )
    if status == "needs_input":
        assert report["result"]["material_receipt"]["user_gate"] == {
            "schema_version": "quasi.user-gate.stage/0.1",
            "operation_key": "paper.prepare",
            "kind": "stage_needs_input",
            "issue": prepare(slug, status=status)["terminal"]["issue"],
            "candidates": [],
            "conflicts": [],
            "question": "Can you provide another source PDF?",
        }
    else:
        assert report["result"]["material_receipt"]["user_gate"] is None


@pytest.mark.parametrize("stage_reply", [None, {"status": "complete"}])
def test_prepare_unknown_or_malformed_blocks_without_replay(
    tmp_path: Path,
    stage_reply: Any,
) -> None:
    slug = "paper-stage-unknown"
    responses = {
        f"{slug}:search": [search(slug)],
        f"{slug}:acquire": [acquire(slug)],
        f"{slug}:prepare": [stage_reply],
    }
    report = run_paper(tmp_path, slug, responses)

    assert report["result"]["status"] == "blocked"
    assert labels(report).count(f"{slug}:prepare") == 1
    assert report["result"]["material_receipt"]["resume"] == {
        "operation_key": "paper.reconcile"
    }


def test_prepare_complete_requires_usable_selected_artifact(tmp_path: Path) -> None:
    slug = "paper-stage-unproved"
    bad = prepare(slug)
    bad["artifacts"][0]["usable"] = False
    responses = {
        f"{slug}:search": [search(slug)],
        f"{slug}:acquire": [acquire(slug)],
        f"{slug}:prepare": [bad],
    }
    report = run_paper(tmp_path, slug, responses)

    assert report["result"]["status"] == "blocked"
    assert report["result"]["material_receipt"]["failure"]["code"] == (
        "paper.writer_receipt_mismatch"
    )


def test_audit_routes_one_exact_analysis_repair(tmp_path: Path) -> None:
    slug = "paper-stage-audit-repair"
    responses = base(slug)
    responses[f"{slug}:audit"] = [
        audit(slug, status="partial"),
        audit(slug, pass_number=2),
    ]
    repaired = analyse(slug)
    repaired["action"] = "repair"
    responses[f"{slug}:analyse"] = [analyse(slug), repaired]
    report = run_paper(tmp_path, slug, responses)

    assert report["result"]["status"] == "ok"
    assert labels(report).count(f"{slug}:analyse") == 2
    assert labels(report).count(f"{slug}:audit") == 2
    assert report["result"]["material_receipt"]["disposition"] == "repaired"


def test_audit_mechanical_mutation_is_one_direct_repaired_receipt(
    tmp_path: Path,
) -> None:
    slug = "paper-stage-audit-mechanical-repair"
    responses = base(slug)
    repaired_audit = audit(slug)
    repaired_audit["mutated_paths"] = [paths(slug)["canonical"]]
    responses[f"{slug}:audit"] = [repaired_audit]
    report = run_paper(tmp_path, slug, responses)

    receipt = report["result"]["material_receipt"]
    assert receipt["status"] == "complete"
    assert receipt["disposition"] == "repaired"
    assert receipt["operations"][-1] == receipt["audit"] == repaired_audit


def test_analysis_unknown_is_one_writer_call(tmp_path: Path) -> None:
    slug = "paper-stage-analysis-unknown"
    responses = base(slug)
    responses[f"{slug}:analyse"] = [None]
    responses.pop(f"{slug}:audit")
    report = run_paper(tmp_path, slug, responses)

    assert report["result"]["status"] == "blocked"
    assert labels(report).count(f"{slug}:analyse") == 1
    assert not any(label.endswith(":audit") for label in labels(report))

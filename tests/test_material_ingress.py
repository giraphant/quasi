from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "workflows" / "process-material.entry.mjs"

NODE_HARNESS = r"""
import { run } from __ENTRY__

const config = JSON.parse(process.argv[1])
const trace = []
const indexes = new Map()
const primitives = {
  agent: async (prompt, options) => {
    trace.push({
      label: options.label,
      phase: options.phase,
      agentType: options.agentType,
      prompt: String(prompt),
      schema: options.schema,
    })
    const steps = config.responses[options.label] || []
    const index = indexes.get(options.label) || 0
    indexes.set(options.label, index + 1)
    if (index >= steps.length)
      throw new Error(`unexpected agent call ${options.label} #${index + 1}`)
    return steps[index]
  },
  parallel: tasks => Promise.all(tasks.map(task => Promise.resolve().then(task))),
  phase: () => {},
  log: () => {},
}
const result = await run(primitives, config.args)
const unused = Object.fromEntries(
  Object.entries(config.responses)
    .map(([label, steps]) => [label, steps.length - (indexes.get(label) || 0)])
    .filter(([, count]) => count !== 0)
)
process.stdout.write(JSON.stringify({ result, trace, unused }))
"""


def run_ingress(
    tmp_path: Path,
    args: dict[str, Any],
    responses: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = NODE_HARNESS.replace("__ENTRY__", json.dumps(ENTRY.as_uri()))
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            script,
            json.dumps({"args": args, "responses": responses}),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["unused"] == {}, report
    return report


SLUG = "example-a-safety-paper-2024"
KEY = f"paper:{SLUG}"


def paper_request() -> dict[str, Any]:
    return {
        "kind": "paper",
        "request": {
            "title": "A Safety Paper",
            "authors": ["Ada Example"],
            "year": 2024,
            "doi": "10.1000/safety",
        },
    }


def search_receipt(
    *,
    status: str = "complete",
    owner: str | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    issue = None
    identity: dict[str, Any] | None = {
        "slug": SLUG,
        "title": "A Safety Paper",
        "authors": ["Ada Example"],
        "year": 2024,
        "doi": "10.1000/safety",
        "oa_url": None,
        "url": None,
        "journal": "Safety Studies",
        "confidence": "high",
    }
    confidence = "high"
    local_owner: dict[str, Any] | None = {
        "requested_slug": SLUG,
        "vault_slug": owner,
        "path": f"vault/papers/{owner}.md" if owner else None,
        "match": "doi" if owner else None,
    }
    if status != "complete":
        identity = None
        confidence = "low"
        local_owner = None
        issue = {
            "code": "material.identity_not_resolved",
            "operation": "material.search",
            "summary": "Structured providers and stable pages did not establish one identity",
            "user_question": (
                "Which DOI or stable journal page identifies this paper?"
                if status == "needs_input"
                else None
            ),
            "retryable": retryable,
        }
    return {
        "schema_version": "quasi.stage.receipt/0.1",
        "operation": "material.search",
        "stage": "Search",
        "material_key": KEY,
        "effect": "readonly",
        "status": status,
        "attempt": 1,
        "kind": "paper",
        "identity": identity,
        "local_owner": local_owner,
        "confidence": confidence,
        "observations": [
            {
                "source": "crossref",
                "query": "10.1000/safety",
                "summary": "No exact record" if status != "complete" else "Exact DOI record",
            }
        ],
        "issue": issue,
    }


def download_failed(slug: str) -> dict[str, Any]:
    return {
        "acquired": 0,
        "failed": 1,
        "per_item": [
            {
                "kind": "paper",
                "slug": slug,
                "status": "download_failed",
                "disposition": None,
                "identity_verified": False,
                "source": None,
                "doi": "10.1000/safety",
                "failure_reason": "not available",
                "attempts": [
                    {"source": "oa", "status": "failed", "error": "404"}
                ],
            }
        ],
    }


def test_search_stage_owns_investigation_and_local_resolution(
    tmp_path: Path,
) -> None:
    responses = {
        f"{SLUG}:search": [search_receipt()],
        f"{SLUG}:acquire": [download_failed(SLUG)],
    }
    report = run_ingress(tmp_path, paper_request(), responses)

    assert report["result"]["status"] == "download_failed"
    assert report["result"]["ingress_receipt"]["status"] == "resolved"
    assert [
        (call["label"], call["phase"], call["agentType"])
        for call in report["trace"]
    ] == [
        (f"{SLUG}:search", "Search", "quasi:metadata-agent"),
        (f"{SLUG}:acquire", "Acquire", "quasi:download-agent"),
    ]
    prompt = json.loads(report["trace"][0]["prompt"])
    assert prompt["objective"].startswith("Establish the most defensible")
    assert len(prompt["capabilities"]) == 3
    assert "number and order" in prompt["method"]


def test_search_complete_may_select_exact_existing_owner(tmp_path: Path) -> None:
    owner = "example-safety-paper-2023"
    responses = {
        f"{SLUG}:search": [search_receipt(owner=owner)],
        f"{owner}:acquire": [download_failed(owner)],
    }
    report = run_ingress(tmp_path, paper_request(), responses)

    assert report["result"]["slug"] == owner
    assert report["result"]["ingress_receipt"]["identity"]["slug"] == owner


@pytest.mark.parametrize("retryable", [False, True])
def test_schema_valid_search_failure_is_not_reclassified_as_invalid(
    tmp_path: Path,
    retryable: bool,
) -> None:
    responses = {
        f"{SLUG}:search": [
            search_receipt(status="failed", retryable=retryable)
        ],
    }
    report = run_ingress(tmp_path, paper_request(), responses)

    assert report["result"]["status"] == "metadata_failed"
    ingress = report["result"]["ingress_receipt"]
    assert ingress["failure"]["code"] == "material.identity_not_resolved"
    assert ingress["failure"]["retryable"] is retryable
    assert "receipt_invalid" not in ingress["failure"]["code"]


def test_search_needs_input_preserves_specialist_question(tmp_path: Path) -> None:
    responses = {
        f"{SLUG}:search": [search_receipt(status="needs_input")],
    }
    report = run_ingress(tmp_path, paper_request(), responses)

    assert report["result"]["status"] == "needs_input"
    ingress = report["result"]["ingress_receipt"]
    assert ingress["stage"] == "search"
    assert "Which DOI" in ingress["failure"]["message"]


def test_malformed_search_receipt_stops_before_acquire(tmp_path: Path) -> None:
    responses = {
        f"{SLUG}:search": [{"status": "complete"}],
    }
    report = run_ingress(tmp_path, paper_request(), responses)

    assert report["result"]["status"] == "metadata_failed"
    assert report["result"]["ingress_receipt"]["failure"]["code"] == (
        "material.search_receipt_invalid"
    )
    assert all(not call["label"].endswith(":acquire") for call in report["trace"])


def test_invalid_raw_request_starts_no_agent(tmp_path: Path) -> None:
    report = run_ingress(
        tmp_path,
        {"kind": "book", "request": {"title": ""}},
        {},
    )
    assert report["result"]["status"] == "needs_input"
    assert report["trace"] == []

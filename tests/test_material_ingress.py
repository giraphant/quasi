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
        [node, "--input-type=module", "-e", script, json.dumps({
            "args": args,
            "responses": responses,
        })],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["unused"] == {}, report
    return report


def lookup_receipt(
    operation: str,
    request_key: str,
    kind: str,
    requested_slug: str,
    *,
    vault_slug: str | None = None,
) -> dict[str, Any]:
    path = (
        f"vault/books/{vault_slug}/00-overview.md"
        if kind == "book" and vault_slug
        else f"vault/papers/{vault_slug}.md"
        if vault_slug
        else "__none__"
    )
    return {
        "schema_version": f"quasi.operation.{operation}.receipt/0.2",
        "key": operation,
        "effect": "readonly",
        "status": "succeeded",
        "attempt": 1,
        "request_key": request_key,
        "kind": kind,
        "requested_slug": requested_slug,
        "vault_slug": vault_slug or "__none__",
        "path": path,
        "match": "doi" if kind == "paper" and vault_slug else "isbn"
        if vault_slug
        else "none",
        "failure": None,
    }


def paper_query() -> dict[str, Any]:
    return {
        "slug": None,
        "title": "A Safety Paper",
        "authors": ["Ada Example"],
        "year": 2024,
        "doi": "10.1000/safety",
        "oa_url": None,
        "url": None,
        "journal": None,
    }


def paper_search(
    query: dict[str, Any],
    *,
    slug: str = "example-a-safety-paper-2024",
) -> dict[str, Any]:
    return {
        "schema_version": "quasi.operation.material.search.receipt/0.1",
        "key": "material.search",
        "effect": "readonly",
        "status": "succeeded",
        "attempt": 1,
        "request_key": "paper:example-a-safety-paper-2024",
        "kind": "paper",
        "query": query,
        "picked": {
            "slug": slug,
            "title": "A Safety Paper",
            "authors": ["Ada Example"],
            "year": 2024,
            "doi": "10.1000/safety",
            "oa_url": None,
            "url": None,
            "journal": "Safety Studies",
            "confidence": "high",
        },
        "confidence": "high",
        "sources_hit": ["crossref"],
        "conflicts": [],
        "notes": "DOI match",
        "failure": None,
    }


def paper_download_failed(slug: str) -> dict[str, Any]:
    return {
        "acquired": 0,
        "failed": 1,
        "per_item": [{
            "kind": "paper",
            "slug": slug,
            "status": "download_failed",
            "disposition": None,
            "identity_verified": False,
            "source": None,
            "doi": "10.1000/safety",
            "failure_reason": "not available",
            "attempts": [{"source": "oa", "status": "failed", "error": "404"}],
        }],
    }


def test_title_request_runs_recall_search_resolve_before_acquire(
    tmp_path: Path,
) -> None:
    slug = "example-a-safety-paper-2024"
    key = f"paper:{slug}"
    responses = {
        f"{slug}:recall": [
            lookup_receipt("material.recall", key, "paper", slug),
        ],
        f"{slug}:search": [paper_search(paper_query())],
        f"{slug}:resolve": [
            lookup_receipt("material.resolve", key, "paper", slug),
        ],
        f"{slug}:acquire": [paper_download_failed(slug)],
    }

    report = run_ingress(
        tmp_path,
        {
            "kind": "paper",
            "request": {
                "title": "A Safety Paper",
                "authors": ["Ada Example"],
                "year": 2024,
                "doi": "10.1000/safety",
            },
        },
        responses,
    )

    assert report["result"]["status"] == "download_failed"
    assert report["result"]["slug"] == slug
    assert report["result"]["ingress_receipt"]["status"] == "resolved"
    assert [
        (call["label"], call["phase"], call["agentType"])
        for call in report["trace"]
    ] == [
        (f"{slug}:recall", "Recall", "quasi:metadata-agent"),
        (f"{slug}:search", "Search", "quasi:metadata-agent"),
        (f"{slug}:resolve", "Search", "quasi:metadata-agent"),
        (f"{slug}:acquire", "Acquire", "quasi:download-agent"),
    ]
    assert "quasi-helpers vault resolve --items-file -" in report["trace"][0]["prompt"]
    assert "quasi-search paper" in report["trace"][1]["prompt"]


def test_lookup_miss_sentinels_are_normalised_before_search(
    tmp_path: Path,
) -> None:
    slug = "example-a-safety-paper-2024"
    key = f"paper:{slug}"
    recall = lookup_receipt(
        "material.recall",
        key,
        "paper",
        slug,
    )
    responses = {
        f"{slug}:recall": [recall],
        f"{slug}:search": [paper_search(paper_query())],
        f"{slug}:resolve": [
            lookup_receipt("material.resolve", key, "paper", slug),
        ],
        f"{slug}:acquire": [paper_download_failed(slug)],
    }

    report = run_ingress(
        tmp_path,
        {
            "kind": "paper",
            "request": {
                "title": "A Safety Paper",
                "authors": ["Ada Example"],
                "year": 2024,
                "doi": "10.1000/safety",
            },
        },
        responses,
    )

    assert report["result"]["status"] == "download_failed"
    normalised = report["result"]["ingress_receipt"]["operations"][0]
    assert normalised["vault_slug"] is None
    assert normalised["path"] is None
    assert normalised["match"] is None
    assert [call["phase"] for call in report["trace"]] == [
        "Recall",
        "Search",
        "Search",
        "Acquire",
    ]


def test_verified_identity_resolves_to_existing_canonical_owner(
    tmp_path: Path,
) -> None:
    searched = "example-a-safety-paper-2024"
    existing = "example-safety-paper-2023"
    key = f"paper:{searched}"
    responses = {
        f"{searched}:recall": [
            lookup_receipt("material.recall", key, "paper", searched),
        ],
        f"{searched}:search": [paper_search(paper_query(), slug=searched)],
        f"{searched}:resolve": [
            lookup_receipt(
                "material.resolve",
                key,
                "paper",
                searched,
                vault_slug=existing,
            ),
        ],
        f"{existing}:acquire": [paper_download_failed(existing)],
    }

    report = run_ingress(
        tmp_path,
        {
            "kind": "paper",
            "request": {
                "title": "A Safety Paper",
                "authors": ["Ada Example"],
                "year": 2024,
                "doi": "10.1000/safety",
            },
        },
        responses,
    )

    assert report["result"]["slug"] == existing
    identity = report["result"]["ingress_receipt"]["identity"]
    assert identity["slug"] == existing
    assert report["trace"][-1]["label"] == f"{existing}:acquire"


def test_unresolved_metadata_becomes_user_gate_without_acquire(
    tmp_path: Path,
) -> None:
    slug = "example-a-safety-paper-2024"
    key = f"paper:{slug}"
    query = paper_query()
    failed_search = {
        **paper_search(query),
        "status": "failed",
        "picked": None,
        "confidence": "low",
        "failure": {
            "code": "material.identity_not_resolved",
            "operation_key": "material.search",
            "outcome": "known",
            "retryable": False,
            "message": "no complete identity",
        },
    }
    responses = {
        f"{slug}:recall": [
            lookup_receipt("material.recall", key, "paper", slug),
        ],
        f"{slug}:search": [failed_search],
    }

    report = run_ingress(
        tmp_path,
        {
            "kind": "paper",
            "request": {
                "title": "A Safety Paper",
                "authors": ["Ada Example"],
                "year": 2024,
                "doi": "10.1000/safety",
            },
        },
        responses,
    )

    assert report["result"]["status"] == "needs_input"
    assert report["result"]["ingress_receipt"]["stage"] == "search"
    assert [call["phase"] for call in report["trace"]] == ["Recall", "Search"]


@pytest.mark.parametrize("bad_stage", ["recall", "search"])
def test_malformed_readonly_receipt_fails_before_writers(
    tmp_path: Path,
    bad_stage: str,
) -> None:
    slug = "example-a-safety-paper-2024"
    key = f"paper:{slug}"
    responses: dict[str, list[dict[str, Any]]] = {
        f"{slug}:recall": [
            {"status": "succeeded"}
            if bad_stage == "recall"
            else lookup_receipt("material.recall", key, "paper", slug),
        ],
    }
    if bad_stage == "search":
        responses[f"{slug}:search"] = [{"status": "succeeded"}]

    report = run_ingress(
        tmp_path,
        {
            "kind": "paper",
            "request": {
                "title": "A Safety Paper",
                "authors": ["Ada Example"],
                "year": 2024,
                "doi": "10.1000/safety",
            },
        },
        responses,
    )

    assert report["result"]["status"] == "metadata_failed"
    assert all(
        not call["label"].endswith(":acquire")
        for call in report["trace"]
    )


def test_invalid_raw_request_starts_no_agent(tmp_path: Path) -> None:
    report = run_ingress(
        tmp_path,
        {"kind": "book", "request": {"title": ""}},
        {},
    )

    assert report["result"]["status"] == "needs_input"
    assert report["result"]["ingress_receipt"]["failure"]["code"] == (
        "material.request_invalid"
    )
    assert report["trace"] == []

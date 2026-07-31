from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "workflows" / "process-material.entry.mjs"
BATCH = ROOT / "scripts" / "workflows" / "materials" / "batch.mjs"

NODE_HARNESS = r"""
import { run } from __ENTRY__

const config = JSON.parse(process.argv[1])
const indexes = new Map()
const trace = []
let clock = 0
let searchesStarted = 0
let releaseSearches
const searchesReady = new Promise(resolve => { releaseSearches = resolve })

const primitives = {
  agent: async (prompt, options) => {
    const label = options.label
    const index = indexes.get(label) || 0
    indexes.set(label, index + 1)
    const call = {
      label,
      occurrence: index + 1,
      phase: options.phase,
      agent_type: options.agentType,
      start: ++clock,
      end: null,
    }
    trace.push(call)
    if (config.search_barrier && label.endsWith(":search")) {
      searchesStarted += 1
      if (searchesStarted === config.search_barrier) releaseSearches()
      await searchesReady
    }
    const steps = config.responses[label] || []
    if (index >= steps.length)
      throw new Error(`unexpected agent call ${label} #${index + 1}`)
    call.end = ++clock
    return JSON.parse(JSON.stringify(steps[index]))
  },
  parallel: tasks => Promise.all(
    tasks.map(task => Promise.resolve().then(task))
  ),
  phase: () => {},
  log: () => {},
}

const result = await run(primitives, config.args)
const unused = Object.fromEntries(
  Object.entries(config.responses)
    .map(([label, steps]) => [
      label,
      steps.length - (indexes.get(label) || 0),
    ])
    .filter(([, count]) => count !== 0)
)
process.stdout.write(JSON.stringify({ result, trace, unused }))
"""


def run_batch(
    tmp_path: Path,
    args: dict[str, Any],
    responses: dict[str, list[dict[str, Any]]],
    *,
    search_barrier: int = 0,
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
            json.dumps({
                "args": args,
                "responses": responses,
                "search_barrier": search_barrier,
            }),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["unused"] == {}, report
    return report


def test_batch_complete_summary_preserves_input_order() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = f"""
import {{ processMaterialBatch }} from {json.dumps(BATCH.as_uri())}
const runtime = {{
  parallel: tasks => Promise.all(tasks.map(task => task())),
  log: () => {{}},
}}
const items = [
  {{ kind: "paper", slug: "paper-one" }},
  {{ kind: "book", slug: "book-two" }},
]
const result = await processMaterialBatch(runtime, items, async item => ({{
  slug: item.slug,
  status: "ok",
  material_receipt: {{
    schema_version: "quasi.material-loop.receipt/0.1",
    material_key: `${{item.kind}}:${{item.slug}}`,
    kind: item.kind,
    id: item.slug,
    status: "complete",
  }},
}}))
console.log(JSON.stringify(result))
"""
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "ok"
    assert result["batch_receipt"]["status"] == "complete"
    assert result["batch_receipt"]["counts"] == {
        "complete": 2,
        "needs_input": 0,
        "blocked": 0,
        "failed": 0,
    }
    assert [
        item["result"]["slug"] for item in result["results"]
    ] == ["paper-one", "book-two"]


def paper_request(title: str = "Parallel Paper") -> dict[str, Any]:
    return {
        "kind": "paper",
        "request": {
            "title": title,
            "authors": ["Ada Example"],
            "year": 2024,
            "doi": "10.1000/parallel",
        },
    }


def book_request() -> dict[str, Any]:
    return {
        "kind": "book",
        "request": {
            "title": "Parallel Book",
            "authors": ["Ben Writer"],
            "year": 2023,
            "isbn": "9780000000002",
        },
    }


def failed_search(
    request_key: str,
    kind: str,
    query: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "quasi.stage.receipt/0.1",
        "operation": "material.search",
        "stage": "Search",
        "material_key": request_key,
        "effect": "readonly",
        "status": "failed",
        "attempt": 1,
        "kind": kind,
        "identity": None,
        "local_owner": None,
        "confidence": "low",
        "observations": [{
            "source": "structured providers",
            "query": query["title"],
            "summary": "No defensible identity was established.",
        }],
        "issue": {
            "code": "material.identity_not_resolved",
            "operation": "material.search",
            "summary": "no complete identity",
            "user_question": None,
            "retryable": False,
        },
    }


def paper_query() -> dict[str, Any]:
    return {
        "slug": None,
        "title": "Parallel Paper",
        "authors": ["Ada Example"],
        "year": 2024,
        "doi": "10.1000/parallel",
        "oa_url": None,
        "url": None,
        "journal": None,
    }


def book_query() -> dict[str, Any]:
    return {
        "slug": None,
        "title": "Parallel Book",
        "authors": ["Ben Writer"],
        "year": 2023,
        "isbn": "9780000000002",
        "publisher": None,
        "category": None,
        "format": None,
    }


def successful_paper_search(
    request_key: str,
    slug: str,
) -> dict[str, Any]:
    query = paper_query()
    return {
        "schema_version": "quasi.stage.receipt/0.1",
        "operation": "material.search",
        "stage": "Search",
        "material_key": request_key,
        "effect": "readonly",
        "status": "complete",
        "attempt": 1,
        "kind": "paper",
        "identity": {
            "slug": slug,
            "title": query["title"],
            "authors": query["authors"],
            "year": query["year"],
            "doi": query["doi"],
            "oa_url": None,
            "url": None,
            "journal": "Parallel Studies",
            "confidence": "high",
        },
        "local_owner": {
            "requested_slug": slug,
            "vault_slug": None,
            "path": None,
            "match": None,
        },
        "confidence": "high",
        "observations": [{
            "source": "Crossref",
            "query": query["doi"],
            "summary": "DOI and bibliographic fields agree.",
        }],
        "issue": None,
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
            "doi": "10.1000/parallel",
            "failure_reason": "not available",
            "attempts": [{
                "source": "oa",
                "status": "failed",
                "error": "404",
            }],
        }],
    }


def test_batch_is_one_parallel_run_with_ordered_item_progress(
    tmp_path: Path,
) -> None:
    paper_slug = "example-parallel-paper-2024"
    book_slug = "writer-parallel-book-2023"
    responses = {
        f"{paper_slug}:search": [
            failed_search(
                f"paper:{paper_slug}",
                "paper",
                paper_query(),
            ),
        ],
        f"{book_slug}:search": [
            failed_search(
                f"book:{book_slug}",
                "book",
                book_query(),
            ),
        ],
    }
    report = run_batch(
        tmp_path,
        {
            "kind": "batch",
            "items": [paper_request(), book_request()],
        },
        responses,
        search_barrier=2,
    )

    result = report["result"]
    assert result["status"] == "failed"
    assert result["batch_receipt"] == {
        "schema_version": "quasi.collection.material-batch.receipt/0.1",
        "status": "failed",
        "total": 2,
        "counts": {
            "complete": 0,
            "needs_input": 0,
            "blocked": 0,
            "failed": 2,
        },
        "items": result["batch_receipt"]["items"],
        "failure": None,
    }
    assert [
        (item["index"], item["kind"], item["status"])
        for item in result["results"]
    ] == [
        (0, "paper", "failed"),
        (1, "book", "failed"),
    ]
    search_calls = [
        call for call in report["trace"]
        if call["label"].endswith(":search")
    ]
    assert len(search_calls) == 2
    assert max(call["start"] for call in search_calls) < min(
        call["end"] for call in search_calls
    )


def test_invalid_batch_item_does_not_stop_valid_sibling(
    tmp_path: Path,
) -> None:
    slug = "example-parallel-paper-2024"
    responses = {
        f"{slug}:search": [
            failed_search(
                f"paper:{slug}",
                "paper",
                paper_query(),
            ),
        ],
    }
    report = run_batch(
        tmp_path,
        {
            "kind": "batch",
            "items": [
                {"kind": "talk", "slug": "not-a-material"},
                paper_request(),
            ],
        },
        responses,
    )

    assert report["result"]["status"] == "failed"
    assert report["result"]["batch_receipt"]["counts"] == {
        "complete": 0,
        "needs_input": 0,
        "blocked": 0,
        "failed": 2,
    }
    assert [
        item["status"]
        for item in report["result"]["results"]
    ] == ["failed", "failed"]
    assert all(
        call["label"].startswith(slug)
        for call in report["trace"]
    )


def test_duplicate_batch_requests_share_one_material_loop(
    tmp_path: Path,
) -> None:
    slug = "example-parallel-paper-2024"
    key = f"paper:{slug}"
    responses = {
        f"{slug}:search": [
            successful_paper_search(key, slug),
        ],
        f"{slug}:acquire": [paper_download_failed(slug)],
    }
    report = run_batch(
        tmp_path,
        {
            "kind": "batch",
            "items": [paper_request(), paper_request()],
        },
        responses,
    )

    assert report["result"]["status"] == "failed"
    assert report["result"]["batch_receipt"]["counts"]["failed"] == 2
    for suffix in ("search", "acquire"):
        assert sum(
            call["label"] == f"{slug}:{suffix}"
            for call in report["trace"]
        ) == 1
    assert [
        item["result"]["slug"]
        for item in report["result"]["results"]
    ] == [slug, slug]

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
const items = [
  {{ kind: "paper", request: {{
    slug: "paper-one",
    title: "Paper One",
    authors: ["Ada Example"],
    year: 2024,
    doi: "10.1000/paper-one",
    journal: "Example Journal",
  }} }},
  {{ kind: "book", request: {{
    slug: "book-two",
    title: "Book Two",
    authors: ["Ben Example"],
    year: 2023,
    isbn: "9780000000002",
    publisher: "Example Press",
    category: "monograph",
  }} }},
]
const metaByKey = new Map(items.map(item => [
  `${{item.kind}}:${{item.request.slug}}`,
  item.request,
]))
const runtime = {{
  parallel: tasks => Promise.all(tasks.map(task => task())),
  log: () => {{}},
  operate: async (_prompt, _options, spec) => {{
    const {{ kind, slug }} = spec.context
    const meta = metaByKey.get(`${{kind}}:${{slug}}`)
    const canonical = kind === "paper"
      ? `vault/papers/${{slug}}.md`
      : `vault/books/${{slug}}/00-overview.md`
    const stages = kind === "paper"
      ? [
          {{ stage: "acquire", complete: true, evidence: [`sources/${{slug}}.pdf`] }},
          {{ stage: "prepare", complete: true, evidence: [`processing/papers/${{slug}}/source.txt`] }},
          {{ stage: "analyse", complete: true, evidence: [canonical] }},
          {{ stage: "audit", complete: null, evidence: [] }},
        ]
      : [
          {{ stage: "acquire", complete: true, evidence: [`sources/${{slug}}.epub`] }},
          {{ stage: "prepare", complete: true, evidence: [`processing/chapters/${{slug}}/manifest.json`, `processing/chapters/${{slug}}/01.txt`] }},
          {{ stage: "analyse", complete: true, evidence: [`vault/books/${{slug}}/ch01-example.md`] }},
          {{ stage: "synthesise", complete: true, evidence: [canonical] }},
          {{ stage: "audit", complete: null, evidence: [] }},
        ]
    return {{
      edge: "ok",
      receipt: {{
        oracle: {{
          schema_version: "quasi.status/0.1",
          kind,
          slug,
          stages,
          next_stage: null,
          refs: {{}},
          identity: {{
            title: meta.title,
            authors: meta.authors,
            year: meta.year,
          }},
        }},
      }},
    }}
  }},
}}
const strictResult = item => {{
  const slug = item.request.slug
  const identity = item.kind === "paper" ? {{
    slug,
    title: item.request.title,
    authors: item.request.authors,
    year: item.request.year,
    doi: item.request.doi,
    oa_url: null,
    url: null,
    journal: item.request.journal,
    confidence: "high",
  }} : {{
    slug,
    title: item.request.title,
    authors: item.request.authors,
    year: item.request.year,
    isbn: item.request.isbn,
    publisher: item.request.publisher,
    category: item.request.category,
    confidence: "high",
  }}
  const search = {{
    schema_version: "quasi.stage.receipt/0.2",
    operation: "material.search",
    stage: "Search",
    material_key: `${{item.kind}}:${{slug}}`,
    effect: "readonly",
    attempt: 1,
    kind: item.kind,
    identity,
    local_owner: null,
    confidence: "high",
    observations: [{{
      source: "fixture",
      query: item.request.title,
      summary: "exact identity",
    }}],
    terminal: {{ status: "complete", issue: null }},
  }}
  const canonical = item.kind === "paper"
    ? `vault/papers/${{slug}}.md`
    : `vault/books/${{slug}}/00-overview.md`
  const audit = item.kind === "paper"
    ? {{
        schema_version: "quasi.stage.receipt/0.2",
        operation: "paper.audit",
        stage: "Audit",
        material_key: `paper:${{slug}}`,
        effect: "writer",
        attempt: 1,
        target_path: canonical,
        artifact_roles: ["canonical"],
        pass: 1,
        remaining_violations: 0,
        escalated: [],
        mutated_paths: [],
        terminal: {{ status: "complete", issue: null }},
      }}
    : [{{
        schema_version: "quasi.stage.receipt/0.2",
        operation: "book.audit",
        stage: "Audit",
        material_key: `book:${{slug}}`,
        effect: "writer",
        attempt: 1,
        target_path: `vault/books/${{slug}}`,
        pass: 1,
        remaining_violations: 0,
        escalated: [],
        mutated_paths: [],
        terminal: {{ status: "complete", issue: null }},
      }}]
  const artifacts = [{{
    role: "canonical",
    path: canonical,
    exists: true,
    usable: true,
    producer: item.kind === "paper"
      ? "paper.analyse"
      : "book.synthesise",
  }}]
  if (item.kind === "book") artifacts.push({{
    role: "chapter_canonical",
    path: `vault/books/${{slug}}/ch01-example.md`,
    exists: true,
    usable: true,
    producer: "chapter.analyse",
  }})
  return {{
    slug,
    // Deliberately contradictory: Batch admission is MaterialReceipt-owned.
    status: "legacy-status-must-not-control-the-batch",
    private_child_state: {{ must_not_escape: true }},
    material_receipt: {{
      schema_version: "quasi.material-loop.receipt/0.2",
      material_key: `${{item.kind}}:${{slug}}`,
      kind: item.kind,
      id: slug,
      status: "complete",
      disposition: "created",
      stage: "audit",
      artifacts,
      operations: [{{ key: `${{item.kind}}.analyse` }}],
      audit,
      freshness: {{
        observation: "unknown",
        basis: "operation-receipts-and-final-audit",
      }},
      warnings: [],
      failure: null,
      user_gate: null,
      resume: null,
      ...(item.kind === "book" ? {{
        expected_slots: ["01"],
        present_slots: ["01"],
        missing_slots: [],
      }} : {{}}),
    }},
    ingress_receipt: {{
      schema_version: "quasi.material-ingress.receipt/0.2",
      request_key: `${{item.kind}}:${{slug}}`,
      kind: item.kind,
      status: "resolved",
      stage: "search",
      request: item.kind === "paper" ? {{
        slug,
        title: item.request.title,
        authors: item.request.authors,
        year: item.request.year,
        doi: item.request.doi,
        oa_url: null,
        url: null,
        journal: item.request.journal,
      }} : {{
        slug,
        title: item.request.title,
        authors: item.request.authors,
        year: item.request.year,
        isbn: item.request.isbn,
        publisher: item.request.publisher,
        category: item.request.category,
        format: null,
      }},
      operations: [search],
      identity: {{
        slug,
        meta: item.kind === "paper" ? {{
          title: identity.title,
          authors: identity.authors,
          year: identity.year,
          doi: identity.doi,
          oa_url: identity.oa_url,
          url: identity.url,
          journal: identity.journal,
          confidence: "verified",
        }} : {{
          title: identity.title,
          authors: identity.authors,
          year: identity.year,
          isbn: identity.isbn,
          publisher: identity.publisher,
          category: identity.category,
          format: null,
          confidence: "verified",
        }},
      }},
      failure: null,
      user_gate: null,
      resume: null,
    }},
  }}
}}
const result = await processMaterialBatch(runtime, items, async item => ({{
  ...strictResult(item),
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
    assert "results" not in result
    assert [
        item["id"] for item in result["batch_receipt"]["items"]
    ] == ["paper-one", "book-two"]
    assert [
        item["canonical_artifacts"][0]["path"]
        for item in result["batch_receipt"]["items"]
    ] == [
        "vault/papers/paper-one.md",
        "vault/books/book-two/00-overview.md",
    ]
    assert [
        artifact["path"]
        for artifact in result["batch_receipt"]["items"][1][
            "canonical_artifacts"
        ]
    ] == [
        "vault/books/book-two/00-overview.md",
        "vault/books/book-two/ch01-example.md",
    ]
    assert all(
        item["issue"] is None
        and item["user_gate"] is None
        and item["resume"] is None
        for item in result["batch_receipt"]["items"]
    )


def test_batch_rejects_incomplete_child_receipt() -> None:
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
  {{ kind: "paper", slug: "paper-two" }},
]
const result = await processMaterialBatch(runtime, items, async item => ({{
  slug: item.slug,
  status: "ok",
  material_receipt: {{
    schema_version: "quasi.material-loop.receipt/0.2",
    material_key: `paper:${{item.slug}}`,
    kind: "paper",
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
    assert result["status"] == "blocked"
    assert result["batch_receipt"]["counts"]["blocked"] == 2
    assert all(
        item["issue"] is not None
        for item in result["batch_receipt"]["items"]
    )


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
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "material.search",
        "stage": "Search",
        "material_key": request_key,
        "effect": "readonly",
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
        "terminal": {
            "status": "failed",
            "issue": {
                "code": "material.identity_not_resolved",
                "operation": "material.search",
                "summary": "no complete identity",
                "user_question": None,
                "retryable": False,
            },
        },
    }


def needs_input_search(
    request_key: str,
    query: dict[str, Any],
) -> dict[str, Any]:
    candidate = {
        "slug": "different-parallel-paper-2024",
        "title": query["title"],
        "authors": ["Bea Different"],
        "year": query["year"],
        "doi": query["doi"],
        "oa_url": None,
        "url": None,
        "journal": "Parallel Studies",
        "confidence": "high",
    }
    receipt = failed_search(request_key, "paper", query)
    receipt["terminal"] = {
        "status": "needs_input",
        "issue": {
            "code": "material.identity_conflict",
            "operation": "material.search",
            "summary": "The title resolves to a different author.",
            "user_question": "Use the evidence-backed candidate?",
            "retryable": False,
        },
        "candidates": [candidate],
        "conflicts": ["authors"],
    }
    return receipt


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


def book_year_decision() -> dict[str, Any]:
    return {
        "action": "use-recommended-year",
        "tmp_path": ".quasi/temp/downloads/year-book-candidate.epub",
        "year_evidence": {
            "slug_year": 2020,
            "source_years": {"catalog": 2021, "copyright": 2021},
            "pdf_signals": {
                "first_published": 2021,
                "copyright_year": 2021,
                "original_year": None,
                "other_years": [],
            },
            "recommended_year": 2021,
            "recommendation_reason": "two independent signals agree",
            "verdict": "MISMATCH",
        },
    }


def successful_book_search(
    request_key: str,
    slug: str,
    year: int,
) -> dict[str, Any]:
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "material.search",
        "stage": "Search",
        "material_key": request_key,
        "effect": "readonly",
        "attempt": 1,
        "kind": "book",
        "identity": {
            "slug": slug,
            "title": "Year Book",
            "authors": ["Bea Writer"],
            "year": year,
            "isbn": "9780000000002",
            "publisher": "Example Press",
            "category": "monograph",
            "confidence": "high",
        },
        "local_owner": None,
        "confidence": "high",
        "observations": [{
            "source": "publisher",
            "query": "9780000000002",
            "summary": "Exact edition identity.",
        }],
        "terminal": {"status": "complete", "issue": None},
    }


def successful_paper_search(
    request_key: str,
    slug: str,
) -> dict[str, Any]:
    query = paper_query()
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "material.search",
        "stage": "Search",
        "material_key": request_key,
        "effect": "readonly",
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
            "identity_slug": slug,
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
        "terminal": {"status": "complete", "issue": None},
    }


def paper_download_failed(slug: str) -> dict[str, Any]:
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "paper.acquire",
        "stage": "Acquire",
        "material_key": f"paper:{slug}",
        "effect": "writer",
        "attempt": 1,
        "output_path": f"sources/{slug}.pdf",
        "doi": "10.1000/parallel",
        "disposition": None,
        "write_state": "not_written",
        "identity_verified": False,
        "source": None,
        "attempts": [{
            "source": "oa",
            "status": "failed",
            "error": "404",
        }],
        "terminal": {
            "status": "failed",
            "issue": {
                "code": "paper.download_failed",
                "operation": "paper.acquire",
                "summary": "not available",
                "user_question": None,
                "retryable": False,
            },
        },
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
    assert result["batch_receipt"]["status"] == "failed"
    assert result["batch_receipt"]["total"] == 2
    assert result["batch_receipt"]["counts"]["failed"] == 2
    assert [
        (item["index"], item["kind"], item["status"])
        for item in result["batch_receipt"]["items"]
    ] == [
        (0, "paper", "failed"),
        (1, "book", "failed"),
    ]
    assert all(
        item["canonical_artifacts"] == []
        and item["issue"] is not None
        for item in result["batch_receipt"]["items"]
    )
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
        for item in report["result"]["batch_receipt"]["items"]
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
        item["id"]
        for item in report["result"]["batch_receipt"]["items"]
    ] == [slug, slug]
    assert all(
        item["canonical_artifacts"] == []
        and item["issue"] is not None
        for item in report["result"]["batch_receipt"]["items"]
    )


def test_batch_preserves_typed_user_gate_without_raw_child_result(
    tmp_path: Path,
) -> None:
    paper_slug = "example-parallel-paper-2024"
    book_slug = "writer-parallel-book-2023"
    responses = {
        f"{paper_slug}:search": [
            needs_input_search(
                f"paper:{paper_slug}",
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
    assert "results" not in result
    assert result["status"] == "partial"
    assert result["batch_receipt"]["counts"] == {
        "complete": 0,
        "needs_input": 1,
        "blocked": 0,
        "failed": 1,
    }
    gate_item = result["batch_receipt"]["items"][0]
    assert gate_item["status"] == "needs_input"
    assert gate_item["canonical_artifacts"] == []
    assert gate_item["issue"] is not None
    gate = gate_item["user_gate"]
    assert gate["question"] == "Use the evidence-backed candidate?"
    assert gate["conflicts"] == ["authors"]
    assert gate["candidates"][0]["slug"] == "different-parallel-paper-2024"


def test_batch_admits_invalid_book_year_decision_as_user_gate(
    tmp_path: Path,
) -> None:
    paper_slug = "example-parallel-paper-2024"
    responses = {
        f"{paper_slug}:search": [
            failed_search(
                f"paper:{paper_slug}",
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
                {
                    "kind": "book",
                    "slug": "invalid-year-book-2020",
                    "request": {
                        "title": "Invalid Year Book",
                        "authors": ["Bea Writer"],
                        "year": 2020,
                        "isbn": "9780000000002",
                    },
                    "year_decision": {"action": "not-a-decision"},
                },
                paper_request(),
            ],
        },
        responses,
    )

    first = report["result"]["batch_receipt"]["items"][0]
    assert first["status"] == "needs_input"
    assert first["issue"] is not None
    assert first["user_gate"]["question"]


def test_batch_admits_search_bound_book_year_decision_conflict(
    tmp_path: Path,
) -> None:
    book_slug = "year-book-2020"
    paper_slug = "example-parallel-paper-2024"
    responses = {
        f"{book_slug}:search": [
            successful_book_search(
                f"book:{book_slug}",
                "year-book-2019",
                2019,
            ),
        ],
        f"{paper_slug}:search": [
            failed_search(
                f"paper:{paper_slug}",
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
                {
                    "kind": "book",
                    "slug": book_slug,
                    "request": {
                        "title": "Year Book",
                        "authors": ["Bea Writer"],
                        "year": 2020,
                        "isbn": "9780000000002",
                    },
                    "year_decision": book_year_decision(),
                },
                paper_request(),
            ],
        },
        responses,
    )

    first = report["result"]["batch_receipt"]["items"][0]
    assert first["status"] == "needs_input"
    assert first["issue"] is not None
    assert first["user_gate"]["question"]

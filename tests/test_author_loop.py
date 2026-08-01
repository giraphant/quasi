"""Strict module/mock tests for the Author collection loop.

These tests execute ``scripts/workflows/collections/author.mjs::processAuthor`` with
the real shared runtime, a scripted ``agent`` primitive, and injected Book /
Paper child-loop stubs.  They are deliberately not Claude Workflow, Pi, Codex,
filesystem, or network end-to-end tests.

The collection contract frozen here is:

* discovery and membership resolution are bounded read-only Operations;
* only exact, complete child MaterialReceipts enter the Author corpus;
* synthesis and audit are single-invocation writers whose unknown outcomes
  block instead of replaying;
* the Author owns one exact output path and writer safety boundaries.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
AUTHOR_MODULE = PLUGIN_ROOT / "scripts/workflows" / "collections" / "author.mjs"
RUNTIME_MODULE = PLUGIN_ROOT / "scripts/workflows" / "runtime.mjs"

MATERIAL_RECEIPT_VERSION = "quasi.material-loop.receipt/0.2"


NODE_HARNESS = r"""
import { processAuthor } from __AUTHOR_URI__
import { createRuntime } from __RUNTIME_URI__

const config = JSON.parse(process.argv[1])
const trace = []
const phases = []
const logs = []
const missing = []
const indexes = new Map()
const barriers = new Map()
const childMeta = new Map()
let clock = 0

function clone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value))
}

function balancedObject(text, start) {
  let depth = 0
  let quoted = false
  let escaped = false
  for (let index = start; index < text.length; index++) {
    const char = text[index]
    if (quoted) {
      if (escaped) escaped = false
      else if (char === "\\") escaped = true
      else if (char === '"') quoted = false
      continue
    }
    if (char === '"') {
      quoted = true
      continue
    }
    if (char === "{") depth++
    if (char === "}") {
      depth--
      if (depth === 0) return text.slice(start, index + 1)
    }
  }
  return null
}

function parseRequest(prompt) {
  const text = String(prompt)
  const fenced = [...text.matchAll(/```json\s*([\s\S]*?)```/g)]
  for (const match of fenced) {
    try {
      const parsed = JSON.parse(match[1])
      if (parsed && typeof parsed === "object") return parsed
    } catch {}
  }
  for (let index = 0; index < text.length; index++) {
    if (text[index] !== "{") continue
    const candidate = balancedObject(text, index)
    if (!candidate) continue
    try {
      const parsed = JSON.parse(candidate)
      if (
        parsed &&
        typeof parsed === "object" &&
        (
          parsed.operation ||
          parsed.collection_key ||
          parsed.schema_version
        )
      ) return parsed
    } catch {}
  }
  return null
}

function operationOf(prompt, request) {
  if (request?.operation) return String(request.operation)
  const match = String(prompt).match(/^operation:\s*([^\s]+)\s*$/m)
  return match ? match[1] : null
}

function admissionProbe(request, meta) {
  const { kind, slug } = request
  const canonical = kind === "paper"
    ? `vault/papers/${slug}.md`
    : `vault/books/${slug}/00-overview.md`
  const stages = kind === "paper"
    ? [
        { stage: "acquire", complete: true, evidence: [`sources/${slug}.pdf`] },
        { stage: "prepare", complete: true, evidence: [`processing/papers/${slug}/source.txt`] },
        { stage: "analyse", complete: true, evidence: [canonical] },
        { stage: "audit", complete: null, evidence: [] },
      ]
    : [
        { stage: "acquire", complete: true, evidence: [`sources/${slug}.epub`] },
        { stage: "prepare", complete: true, evidence: [`processing/chapters/${slug}/manifest.json`, `processing/chapters/${slug}/01.txt`] },
        { stage: "analyse", complete: true, evidence: [`vault/books/${slug}/ch01-example.md`] },
        { stage: "synthesise", complete: true, evidence: [canonical] },
        { stage: "audit", complete: null, evidence: [] },
      ]
  return {
    schema_version: "quasi.stage.receipt/0.2",
    operation: "member.admission-probe",
    stage: "Audit",
    material_key: `${kind}:${slug}`,
    effect: "readonly",
    attempt: 1,
    oracle: {
      schema_version: "quasi.status/0.1",
      kind,
      slug,
      stages,
      next_stage: null,
      refs: {},
      identity: {
        title: meta.title,
        authors: meta.authors,
        year: meta.year,
      },
    },
    terminal: { status: "complete", issue: null },
  }
}

async function waitAtBarrier(step) {
  if (!step.barrier) return
  const name = String(step.barrier.name)
  const size = Number(step.barrier.size)
  const rank = Number(step.barrier.rank)
  let group = barriers.get(name)
  if (!group) {
    group = { size, arrivals: [] }
    barriers.set(name, group)
  }
  if (group.size !== size)
    throw new Error(`barrier ${name} size mismatch`)
  await new Promise(resolve => {
    group.arrivals.push({ rank, resolve })
    if (group.arrivals.length === group.size) {
      const ordered = [...group.arrivals].sort(
        (left, right) => left.rank - right.rank
      )
      ordered.forEach((arrival, index) =>
        setTimeout(arrival.resolve, index * 5)
      )
    }
  })
}

async function scriptedStep(route, step, call) {
  if (!step) {
    missing.push(call.id)
    call.end = ++clock
    return null
  }
  await waitAtBarrier(step)
  call.end = ++clock
  if (step.throw) throw new Error(String(step.throw))
  return clone(step.result)
}

async function agent(prompt, options = {}) {
  const label = options.label || options.agentType || "agent"
  const request = parseRequest(prompt)
  const operation = operationOf(prompt, request)
  const route = operation || label
  const occurrence = indexes.get(route) || 0
  indexes.set(route, occurrence + 1)
  const call = {
    id: `${route}#${occurrence + 1}`,
    type: "agent",
    route,
    occurrence: occurrence + 1,
    operation,
    label,
    phase: options.phase || null,
    agent_type: options.agentType || null,
    prompt: String(prompt),
    request,
    schema: options.schema || null,
    start: ++clock,
    end: null,
  }
  trace.push(call)
  const steps = config.responses[route]
  if (route === "member.admission-probe" && !steps) {
    call.end = ++clock
    return admissionProbe(
      request,
      childMeta.get(`${request.kind}:${request.slug}`),
    )
  }
  return scriptedStep(route, steps && steps[occurrence], call)
}

async function child(kind, slug, meta, opts) {
  const route = `${kind}:${slug}`
  const occurrence = indexes.get(route) || 0
  indexes.set(route, occurrence + 1)
  const call = {
    id: `${route}#${occurrence + 1}`,
    type: "child",
    route,
    occurrence: occurrence + 1,
    kind,
    slug,
    meta: clone(meta),
    opts: clone(opts || {}),
    start: ++clock,
    end: null,
  }
  trace.push(call)
  childMeta.set(route, clone(meta))
  const steps = config.children[route]
  return scriptedStep(route, steps && steps[occurrence], call)
}

const primitives = {
  agent,
  parallel: tasks =>
    Promise.all(tasks.map(task => Promise.resolve().then(task))),
  phase: name => phases.push(String(name)),
  log: message => logs.push(String(message)),
}
const runtime = createRuntime(primitives)
const materials = {
  processBook: (slug, meta, opts) => child("book", slug, meta, opts),
  processPaper: (slug, meta, opts) => child("paper", slug, meta, opts),
}

const requests = config.requests || [{
  name: config.name,
  meta: config.meta,
}]
const results = config.parallel_requests
  ? await Promise.all(
      requests.map(request =>
        processAuthor(runtime, materials, request.name, request.meta)
      )
    )
  : await processAuthor(
      runtime,
      materials,
      requests[0].name,
      requests[0].meta,
    )

const unused = {}
for (const [route, steps] of Object.entries({
  ...config.responses,
  ...config.children,
})) {
  const count = steps.length - (indexes.get(route) || 0)
  if (count !== 0) unused[route] = count
}
process.stdout.write(JSON.stringify({
  result: results,
  trace,
  phases,
  logs,
  missing,
  unused,
}))
"""


def reply(
    result: Any,
    *,
    barrier: tuple[str, int, int] | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {"result": result}
    if barrier is not None:
        name, size, rank = barrier
        step["barrier"] = {"name": name, "size": size, "rank": rank}
    return step


def run_author(
    tmp_path: Path,
    *,
    name: str = "ada-example",
    meta: dict[str, Any] | None = None,
    responses: dict[str, list[dict[str, Any]]] | None = None,
    children: dict[str, list[dict[str, Any]]] | None = None,
    requests: list[dict[str, Any]] | None = None,
    parallel_requests: bool = False,
    allow_unused: bool = False,
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = NODE_HARNESS.replace(
        "__AUTHOR_URI__", json.dumps(AUTHOR_MODULE.as_uri())
    ).replace("__RUNTIME_URI__", json.dumps(RUNTIME_MODULE.as_uri()))
    config = {
        "name": name,
        "meta": meta or author_meta(),
        "responses": responses or {},
        "children": children or {},
        "requests": requests,
        "parallel_requests": parallel_requests,
    }
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, json.dumps(config)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["missing"] == [], report
    if not allow_unused:
        assert report["unused"] == {}, report
    return report


def author_meta(**overrides: Any) -> dict[str, Any]:
    value = {
        "full_name": "Ada Example",
        "topic": "reliable academic systems",
        "maxBooks": 1,
        "maxPapers": 1,
    }
    value.update(overrides)
    return value


def book_candidate(
    slug: str = "example-reliable-monograph-2025",
) -> dict[str, Any]:
    return {
        "kind": "book",
        "slug": slug,
        "title": "Reliable Monograph",
        "authors": ["Ada Example"],
        "year": 2025,
        "isbn": "9780000000002",
        "publisher": "Example University Press",
        "category": "monograph",
        "confidence": "high",
    }


def paper_candidate(
    slug: str = "example-reliable-paper-2026",
) -> dict[str, Any]:
    return {
        "kind": "paper",
        "slug": slug,
        "title": "Reliable Paper",
        "authors": ["Ada Example"],
        "year": 2026,
        "doi": "10.5555/reliable",
        "oa_url": None,
        "url": None,
        "journal": "Journal of Exact Contracts",
        "confidence": "high",
    }


def discovery_receipt(
    name: str,
    kind: str,
    candidates: list[dict[str, Any]],
    *,
    count: int | None = None,
    topic: str = "reliable academic systems",
) -> dict[str, Any]:
    key = f"author.discover-{kind}s"
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": key,
        "stage": "Search",
        "material_key": f"author:{name}",
        "effect": "readonly",
        "attempt": 1,
        "collection_key": f"author:{name}",
        "kind": kind,
        "full_name": "Ada Example",
        "topic": topic,
        "count": len(candidates) if count is None else count,
        "candidates": candidates,
        "terminal": {"status": "complete", "issue": None},
    }


def resolver_receipt(
    name: str,
    demands: list[dict[str, Any]],
    *,
    output_exists: bool = False,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = rows
    if resolved is None:
        resolved = [
            {
                "kind": demand["kind"],
                "requested_slug": demand["slug"],
                "vault_slug": None,
                "path": None,
                "match": None,
            }
            for demand in demands
        ]
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "author.resolve-membership",
        "stage": "Search",
        "material_key": f"author:{name}",
        "effect": "readonly",
        "attempt": 1,
        "collection_key": f"author:{name}",
        "output_path": f"vault/authors/{name}.md",
        "output_exists": output_exists,
        "requests": [
            {"kind": demand["kind"], "slug": demand["slug"]} for demand in demands
        ],
        "resolved": resolved,
        "terminal": {"status": "complete", "issue": None},
    }


def canonical_path(kind: str, slug: str) -> str:
    if kind == "book":
        return f"vault/books/{slug}/00-overview.md"
    return f"vault/papers/{slug}.md"


def child_result(
    kind: str,
    slug: str,
    terminal: str = "complete",
    *,
    material_key: str | None = None,
    artifact_path: str | None = None,
    year_warning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failure = None
    resume = None
    if terminal != "complete":
        outcome = "unknown" if terminal == "blocked" else "known"
        failure = {
            "code": f"{kind}.synthetic_{terminal}",
            "operation_key": f"{kind}.synthetic",
            "outcome": outcome,
            "retryable": False,
        }
        if terminal == "blocked":
            resume = {"operation_key": f"{kind}.reconcile"}
    canonical = artifact_path or canonical_path(kind, slug)
    audit = (
        {
            "schema_version": "quasi.stage.receipt/0.2",
            "operation": "paper.audit",
            "stage": "Audit",
            "material_key": f"paper:{slug}",
            "effect": "writer",
            "attempt": 1,
            "target_path": canonical_path(kind, slug),
            "artifact_roles": ["canonical"],
            "pass": 1,
            "remaining_violations": 0,
            "escalated": [],
            "mutated_paths": [],
            "terminal": {"status": "complete", "issue": None},
        }
        if kind == "paper" and terminal == "complete"
        else (
            [
                {
                    "schema_version": "quasi.stage.receipt/0.2",
                    "operation": "book.audit",
                    "stage": "Audit",
                    "material_key": f"book:{slug}",
                    "effect": "writer",
                    "attempt": 1,
                    "target_path": f"vault/books/{slug}",
                    "pass": 1,
                    "remaining_violations": 0,
                    "escalated": [],
                    "mutated_paths": [],
                    "terminal": {"status": "complete", "issue": None},
                }
            ]
            if terminal == "complete"
            else ([] if kind == "book" else None)
        )
    )
    receipt = {
        "schema_version": MATERIAL_RECEIPT_VERSION,
        "material_key": material_key or f"{kind}:{slug}",
        "kind": kind,
        "id": slug,
        "status": terminal,
        "disposition": "created" if terminal == "complete" else None,
        "stage": "audit" if terminal == "complete" else "synthetic",
        "artifacts": (
            [
                {
                    "role": "canonical",
                    "path": canonical,
                    "exists": True,
                    "usable": True if kind == "paper" else None,
                    "producer": (
                        "paper.analyse"
                        if kind == "paper"
                        else "book.synthesise"
                    ),
                },
                *(
                    [
                        {
                            "role": "chapter_canonical",
                            "path": f"vault/books/{slug}/ch01-example.md",
                            "exists": True,
                            "usable": None,
                            "producer": "chapter.analyse",
                        }
                    ]
                    if kind == "book"
                    else []
                ),
            ]
            if terminal == "complete"
            else []
        ),
        "operations": (
            [{"key": f"{kind}.synthetic-operation"}]
            if terminal == "complete"
            else []
        ),
        "audit": audit,
        "freshness": {
            "observation": "unknown",
            "basis": "operation-receipts-and-final-audit",
        },
        "warnings": [],
        "failure": failure,
        "user_gate": None,
        "resume": resume,
    }
    if kind == "book" and terminal == "complete":
        receipt.update(
            {
                "expected_slots": ["01"],
                "present_slots": ["01"],
                "missing_slots": [],
            }
        )
        if year_warning is not None:
            receipt["operations"].insert(
                0,
                {
                    "schema_version": "quasi.stage.receipt/0.2",
                    "operation": "book.acquire",
                    "stage": "Acquire",
                    "material_key": material_key or f"book:{slug}",
                    "effect": "writer",
                    "attempt": 1,
                    "output_path": f"sources/{slug}.epub",
                    "allowed_output_paths": [
                        f"sources/{slug}.epub",
                        f"sources/{slug}.pdf",
                    ],
                    "disposition": "reused",
                    "write_state": "not_written",
                    "identity_verified": True,
                    "format": "epub",
                    "tmp_path": None,
                    "source": "existing_file",
                    "isbn": "9780000000002",
                    "year_evidence": year_warning,
                    "attempts": [],
                    "terminal": {"status": "complete", "issue": None},
                },
            )
    result = {
        "slug": slug,
        "status": "ok" if terminal == "complete" else terminal,
        "material_receipt": receipt,
    }
    return result


def synthesis_receipt(
    name: str,
    members: list[tuple[str, str]],
    *,
    action: str = "create",
    status: str = "succeeded",
    output_path: str | None = None,
) -> dict[str, Any]:
    input_keys = [f"{kind}:{slug}" for kind, slug in members]
    input_paths = [canonical_path(kind, slug) for kind, slug in members]
    terminal_status = "complete" if status == "succeeded" else status
    outcome = "unknown" if terminal_status == "blocked" else "known"
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "author.synthesise",
        "stage": "Synthesise",
        "material_key": f"author:{name}",
        "effect": "writer",
        "attempt": 1,
        "input_material_keys": input_keys,
        "input_paths": input_paths,
        "output_path": output_path or f"vault/authors/{name}.md",
        "artifact_roles": ["canonical"],
        "materials_analyzed": len(members),
        "terminal": {
            "status": terminal_status,
            "issue": (
                None
                if terminal_status == "complete"
                else {
                    "code": "author.synthesise_failed",
                    "operation": "author.synthesise",
                    "summary": "Author Synthesise did not complete",
                    "user_question": None,
                    "retryable": False,
                }
            ),
            "action": action,
        },
    }


def audit_receipt(
    name: str,
    *,
    status: str = "clean",
    escalated: list[dict[str, str]] | None = None,
    mutated_paths: list[str] | None = None,
    target_path: str | None = None,
    pass_number: int = 1,
) -> dict[str, Any]:
    diagnostics = escalated or []
    terminal_status = "complete" if status in {"clean", "partial"} else "failed"
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "author.audit",
        "stage": "Audit",
        "material_key": f"author:{name}",
        "effect": "writer",
        "attempt": 1,
        "target_path": target_path or f"vault/authors/{name}.md",
        "artifact_roles": ["canonical"],
        "pass": pass_number,
        "remaining_violations": len(diagnostics),
        "escalated": diagnostics,
        "mutated_paths": mutated_paths or [],
        "terminal": {
            "status": terminal_status,
            "issue": (
                None
                if terminal_status == "complete"
                else {
                    "code": "author.audit_failed",
                    "operation": "author.audit",
                    "summary": "Author Audit did not complete",
                    "user_question": None,
                    "retryable": False,
                }
            ),
        },
    }


def base_responses(
    name: str = "ada-example",
    *,
    books: list[dict[str, Any]] | None = None,
    papers: list[dict[str, Any]] | None = None,
    resolver: dict[str, Any] | None = None,
    synthesis: list[dict[str, Any]] | None = None,
    audit: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    selected_books = [book_candidate()] if books is None else books
    selected_papers = [paper_candidate()] if papers is None else papers
    demands = [*selected_books, *selected_papers]
    return {
        "author.discover-books": [
            reply(discovery_receipt(name, "book", selected_books))
        ],
        "author.discover-papers": [
            reply(discovery_receipt(name, "paper", selected_papers))
        ],
        "author.resolve-membership": [
            reply(resolver or resolver_receipt(name, demands))
        ],
        "author.synthesise": synthesis
        or [
            reply(
                synthesis_receipt(
                    name,
                    [
                        *(("book", item["slug"]) for item in selected_books),
                        *(("paper", item["slug"]) for item in selected_papers),
                    ],
                )
            )
        ],
        "author.audit": audit or [reply(audit_receipt(name))],
    }


def base_children(
    *,
    books: list[dict[str, Any]] | None = None,
    papers: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    selected_books = [book_candidate()] if books is None else books
    selected_papers = [paper_candidate()] if papers is None else papers
    return {
        **{
            f"book:{item['slug']}": [reply(child_result("book", item["slug"]))]
            for item in selected_books
        },
        **{
            f"paper:{item['slug']}": [reply(child_result("paper", item["slug"]))]
            for item in selected_papers
        },
    }


def calls(report: dict[str, Any], route: str) -> list[dict[str, Any]]:
    return [call for call in report["trace"] if call["route"] == route]


def collection(result: dict[str, Any]) -> dict[str, Any]:
    return result["collection_receipt"]




@pytest.mark.parametrize(
    ("name", "meta"),
    [
        ("../escape", author_meta()),
        ("Ada Example", author_meta()),
        ("ada-example", author_meta(full_name="", maxBooks=1, maxPapers=0)),
        ("ada-example", author_meta(full_name="A" * 121, maxBooks=1, maxPapers=0)),
        ("ada-example", author_meta(maxBooks=-1, maxPapers=1)),
        ("ada-example", author_meta(maxBooks=1.5, maxPapers=1)),
        ("ada-example", author_meta(maxBooks=6, maxPapers=0)),
        ("ada-example", author_meta(maxBooks=0, maxPapers=11)),
        ("ada-example", author_meta(maxBooks=0, maxPapers=0)),
    ],
)
def test_invalid_identity_or_budget_starts_no_agents(
    tmp_path: Path,
    name: str,
    meta: dict[str, Any],
) -> None:
    report = run_author(tmp_path, name=name, meta=meta)

    assert report["trace"] == []
    assert report["result"]["status"] == "blocked"
    assert collection(report["result"])["status"] == "blocked"


def test_zero_book_budget_is_preserved_and_does_not_start_book_search(
    tmp_path: Path,
) -> None:
    name = "ada-example"
    paper = paper_candidate()
    responses = {
        "author.discover-papers": [
            reply(discovery_receipt(name, "paper", [paper], count=1))
        ],
        "author.resolve-membership": [reply(resolver_receipt(name, [paper]))],
        "author.synthesise": [
            reply(synthesis_receipt(name, [("paper", paper["slug"])]))
        ],
        "author.audit": [reply(audit_receipt(name))],
    }
    children = {f"paper:{paper['slug']}": [reply(child_result("paper", paper["slug"]))]}
    report = run_author(
        tmp_path,
        name=name,
        meta=author_meta(maxBooks=0, maxPapers=1),
        responses=responses,
        children=children,
    )
    assert calls(report, "author.discover-books") == []
    assert len(calls(report, "author.discover-papers")) == 1
    result = report["result"]
    assert result["status"] == "ok"
    assert result["books"] == 0
    assert result["papers"] == 1
    assert collection(result)["status"] == "complete"




def test_resolver_correlates_slug_drift_dedupes_and_preserves_order(
    tmp_path: Path,
) -> None:
    name = "ada-example"
    first = book_candidate("example-work-first-discovery-2025")
    drift = book_candidate("example-work-historical-slug-2025")
    paper = paper_candidate()
    canonical_book = "example-work-canonical-2025"
    rows = [
        {
            "kind": "book",
            "requested_slug": first["slug"],
            "vault_slug": canonical_book,
            "path": canonical_path("book", canonical_book),
            "match": "isbn",
        },
        {
            "kind": "book",
            "requested_slug": drift["slug"],
            "vault_slug": canonical_book,
            "path": canonical_path("book", canonical_book),
            "match": "isbn",
        },
        {
            "kind": "paper",
            "requested_slug": paper["slug"],
            "vault_slug": paper["slug"],
            "path": canonical_path("paper", paper["slug"]),
            "match": "doi",
        },
    ]
    responses = base_responses(
        name,
        books=[first, drift],
        papers=[paper],
        resolver=resolver_receipt(
            name,
            [first, drift, paper],
            rows=rows,
        ),
        synthesis=[
            reply(
                synthesis_receipt(
                    name,
                    [
                        ("book", canonical_book),
                        ("paper", paper["slug"]),
                    ],
                )
            )
        ],
    )
    children = {
        f"book:{canonical_book}": [reply(child_result("book", canonical_book))],
        f"paper:{paper['slug']}": [reply(child_result("paper", paper["slug"]))],
    }
    report = run_author(
        tmp_path,
        name=name,
        meta=author_meta(maxBooks=2, maxPapers=1),
        responses=responses,
        children=children,
    )
    assert len(calls(report, f"book:{canonical_book}")) == 1
    assert report["result"]["book_slugs"] == [canonical_book]


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [
            {
                "kind": "paper",
                "requested_slug": "foreign-paper-2020",
                "vault_slug": None,
                "path": None,
                "match": None,
            }
        ],
        [
            {
                "kind": "book",
                "requested_slug": "example-reliable-monograph-2025",
                "vault_slug": None,
                "path": None,
                "match": None,
            },
            {
                "kind": "book",
                "requested_slug": "example-reliable-monograph-2025",
                "vault_slug": None,
                "path": None,
                "match": None,
            },
        ],
    ],
)
def test_malformed_or_uncorrelated_resolver_rows_fail_closed(
    tmp_path: Path,
    rows: list[dict[str, Any]],
) -> None:
    name = "ada-example"
    book = book_candidate()
    responses = {
        "author.discover-books": [reply(discovery_receipt(name, "book", [book]))],
        "author.resolve-membership": [reply(resolver_receipt(name, [book], rows=rows))],
    }
    report = run_author(
        tmp_path,
        name=name,
        meta=author_meta(maxBooks=1, maxPapers=0),
        responses=responses,
    )
    result = report["result"]
    assert result["status"] == "blocked"
    assert not any(call["type"] == "child" for call in report["trace"])
    assert calls(report, "author.synthesise") == []






def test_author_rejects_child_receipt_with_foreign_identity(
    tmp_path: Path,
) -> None:
    name = "ada-example"
    paper = paper_candidate()
    child = child_result(
        "paper",
        paper["slug"],
        material_key="paper:foreign",
    )
    responses = {
        "author.discover-papers": [reply(discovery_receipt(name, "paper", [paper]))],
        "author.resolve-membership": [reply(resolver_receipt(name, [paper]))],
    }
    report = run_author(
        tmp_path,
        name=name,
        meta=author_meta(maxBooks=0, maxPapers=1),
        responses=responses,
        children={f"paper:{paper['slug']}": [reply(child)]},
    )

    assert report["result"]["status"] == "all_failed"
    assert collection(report["result"])["status"] == "failed"
    assert calls(report, "author.synthesise") == []


def test_author_uses_disk_probe_instead_of_receipt_artifact_claim(
    tmp_path: Path,
) -> None:
    name = "ada-example"
    paper = paper_candidate()
    responses = {
        "author.discover-papers": [
            reply(discovery_receipt(name, "paper", [paper]))
        ],
        "author.resolve-membership": [
            reply(resolver_receipt(name, [paper]))
        ],
        "author.synthesise": [
            reply(synthesis_receipt(name, [("paper", paper["slug"])]))
        ],
        "author.audit": [reply(audit_receipt(name))],
    }
    child = child_result(
        "paper",
        paper["slug"],
        artifact_path="vault/papers/foreign.md",
    )

    report = run_author(
        tmp_path,
        name=name,
        meta=author_meta(maxBooks=0, maxPapers=1),
        responses=responses,
        children={f"paper:{paper['slug']}": [reply(child)]},
    )

    assert report["result"]["status"] == "ok"
    probes = calls(report, "member.admission-probe")
    assert len(probes) == 1
    assert probes[0]["phase"] == "Audit"
    assert probes[0]["request"]["command"] == (
        "quasi-status --kind paper "
        f"--slug {paper['slug']} --json --identity"
    )
    synthesis = calls(report, "author.synthesise")[0]
    assert synthesis["request"]["input_paths"] == [
        canonical_path("paper", paper["slug"])
    ]


def test_mixed_child_outcomes_synthesise_only_complete_members_and_are_partial(
    tmp_path: Path,
) -> None:
    name = "ada-example"
    book = book_candidate("example-reliable-monograph-2024")
    book["year"] = 2024
    good = paper_candidate("example-good-paper-2026")
    blocked = paper_candidate("example-blocked-paper-2025")
    responses = base_responses(
        name,
        books=[book],
        papers=[good, blocked],
        synthesis=[
            reply(
                synthesis_receipt(
                    name,
                    [("book", book["slug"]), ("paper", good["slug"])],
                )
            )
        ],
    )
    children = {
        f"book:{book['slug']}": [
            reply(
                child_result(
                    "book",
                    book["slug"],
                    year_warning={
                        "slug_year": 2024,
                        "source_years": {
                            "catalog": 2025,
                            "copyright": 2025,
                        },
                        "pdf_signals": {
                            "first_published": 2025,
                            "copyright_year": 2025,
                            "original_year": None,
                            "other_years": [],
                        },
                        "recommended_year": 2025,
                        "recommendation_reason": (
                            "two independent edition signals agree"
                        ),
                        "verdict": "MISMATCH",
                    },
                )
            )
        ],
        f"paper:{good['slug']}": [reply(child_result("paper", good["slug"]))],
        f"paper:{blocked['slug']}": [
            reply(child_result("paper", blocked["slug"], "blocked"))
        ],
    }
    report = run_author(
        tmp_path,
        name=name,
        meta=author_meta(maxBooks=1, maxPapers=2),
        responses=responses,
        children=children,
    )
    receipt = collection(report["result"])
    assert receipt["status"] == "partial"
    inputs = calls(report, "author.synthesise")[0]["request"]["input_material_keys"]
    assert inputs == [f"book:{book['slug']}", f"paper:{good['slug']}"]
    assert f"paper:{blocked['slug']}" not in inputs


def test_all_failed_children_skip_synthesis_and_audit(
    tmp_path: Path,
) -> None:
    name = "ada-example"
    book = book_candidate()
    paper = paper_candidate()
    responses = {
        "author.discover-books": [reply(discovery_receipt(name, "book", [book]))],
        "author.discover-papers": [reply(discovery_receipt(name, "paper", [paper]))],
        "author.resolve-membership": [reply(resolver_receipt(name, [book, paper]))],
    }
    children = {
        f"book:{book['slug']}": [reply(child_result("book", book["slug"], "failed"))],
        f"paper:{paper['slug']}": [
            reply(child_result("paper", paper["slug"], "blocked"))
        ],
    }
    report = run_author(
        tmp_path,
        name=name,
        responses=responses,
        children=children,
    )
    result = report["result"]
    assert result["status"] == "all_failed"
    assert result["tried"] == 2
    assert collection(result)["status"] == "failed"
    assert calls(report, "author.synthesise") == []
    assert calls(report, "author.audit") == []




@pytest.mark.parametrize(
    ("writer", "case"),
    [
        ("author.synthesise", "unknown"),
        ("author.audit", "unknown"),
        ("author.audit", "unproven"),
    ],
)
def test_writer_unknown_or_unproven_is_called_once_then_blocks(
    tmp_path: Path,
    writer: str,
    case: str,
) -> None:
    name = "ada-example"
    bad_receipt: dict[str, Any] | None = None
    if case == "unproven":
        bad_receipt = audit_receipt(name)
        # The receipt has the host-valid shape but cannot prove a clean audit.
        bad_receipt["remaining_violations"] = 1
    responses = base_responses(name)
    responses[writer] = [reply(bad_receipt)]
    if writer == "author.synthesise":
        responses.pop("author.audit")
    report = run_author(
        tmp_path,
        name=name,
        responses=responses,
        children=base_children(),
    )
    result = report["result"]
    assert result["status"] == "blocked"
    assert len(calls(report, writer)) == 1
    if writer == "author.synthesise":
        assert calls(report, "author.audit") == []


def test_synthesis_known_failure_stops_without_replay(
    tmp_path: Path,
) -> None:
    name = "ada-example"
    failed = synthesis_receipt(
        name,
        [
            ("book", book_candidate()["slug"]),
            ("paper", paper_candidate()["slug"]),
        ],
        status="failed",
    )
    responses = base_responses(name)
    responses["author.synthesise"] = [reply(failed)]
    responses.pop("author.audit")

    report = run_author(
        tmp_path,
        name=name,
        responses=responses,
        children=base_children(),
    )

    result = report["result"]
    assert result["status"] == "synth_failed"
    assert len(calls(report, "author.synthesise")) == 1
    assert calls(report, "author.audit") == []






@pytest.mark.parametrize(
    ("escalated", "mutated"),
    [
        (
            [
                {
                    "path": "vault/papers/foreign.md",
                    "kind": "foreign_owner",
                    "reason": "outside Author output",
                }
            ],
            [],
        ),
        ([], ["vault/books/foreign/00-overview.md"]),
    ],
)
def test_foreign_audit_paths_never_guess_a_producer(
    tmp_path: Path,
    escalated: list[dict[str, str]],
    mutated: list[str],
) -> None:
    name = "ada-example"
    responses = base_responses(
        name,
        audit=[
            reply(
                audit_receipt(
                    name,
                    status="partial" if escalated else "clean",
                    escalated=escalated,
                    mutated_paths=mutated,
                )
            )
        ],
    )
    report = run_author(
        tmp_path,
        name=name,
        responses=responses,
        children=base_children(),
    )
    assert len(calls(report, "author.synthesise")) == 1
    assert len(calls(report, "author.audit")) == 1
    result = report["result"]
    assert result["status"] == "audit_escalated"


def test_same_runtime_identical_requests_share_one_author_promise(
    tmp_path: Path,
) -> None:
    name = "ada-example"
    report = run_author(
        tmp_path,
        name=name,
        responses=base_responses(name),
        children=base_children(),
        requests=[
            {"name": name, "meta": author_meta()},
            {"name": name, "meta": author_meta()},
        ],
        parallel_requests=True,
    )
    first, second = report["result"]
    assert first == second
    assert len(calls(report, "author.synthesise")) == 1
    assert len(calls(report, "author.audit")) == 1




def test_same_runtime_conflicting_author_identity_blocks_before_second_writer(
    tmp_path: Path,
) -> None:
    name = "ada-example"
    report = run_author(
        tmp_path,
        name=name,
        responses=base_responses(name),
        children=base_children(),
        requests=[
            {"name": name, "meta": author_meta()},
            {
                "name": name,
                "meta": author_meta(topic="conflicting topic"),
            },
        ],
        parallel_requests=True,
    )
    statuses = [result["status"] for result in report["result"]]
    assert statuses.count("ok") == 1
    assert statuses.count("blocked") == 1
    assert len(calls(report, "author.synthesise")) == 1
    assert len(calls(report, "author.audit")) == 1

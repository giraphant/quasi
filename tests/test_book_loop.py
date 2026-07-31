"""Book Stage-Pipeline contract tests with scripted Agents."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "scripts" / "workflows" / "materials" / "book.mjs"
RUNTIME = ROOT / "scripts" / "workflows" / "runtime.mjs"

NODE_HARNESS = r"""
import { processBook } from __BOOK_URI__
import { createRuntime } from __RUNTIME_URI__
const config = JSON.parse(process.argv[1])
const trace = []
const phases = []
const indexes = new Map()
const barriers = new Map()
let clock = 0

function parseRequest(prompt) {
  const text = String(prompt)
  const fenced = text.match(/```json\s*([\s\S]*?)```/)
  if (fenced) {
    try { return JSON.parse(fenced[1]) } catch {}
  }
  const start = text.indexOf("{")
  if (start < 0) return null
  try { return JSON.parse(text.slice(start)) } catch { return null }
}
function routeFor(request, label) {
  const operation = request?.operation || label
  const slot = request?.identity?.chapter_slot || null
  const mode = request?.mode || null
  const candidates = [
    slot && mode && `${operation}:${slot}:${mode}`,
    slot && `${operation}:${slot}`,
    mode && `${operation}:${mode}`,
    operation,
    label,
  ].filter(Boolean)
  return candidates.find(key => key in config.responses) || candidates[0]
}
async function waitBarrier(step) {
  if (!step?.barrier) return
  const { name, size, rank } = step.barrier
  let group = barriers.get(name)
  if (!group) {
    group = []
    barriers.set(name, group)
  }
  await new Promise(resolve => {
    group.push({ rank, resolve })
    if (group.length === size)
      for (const entry of [...group].sort((a, b) => a.rank - b.rank))
        setTimeout(entry.resolve, entry.rank * 2)
  })
}
async function agent(prompt, options = {}) {
  const label = options.label || options.agentType || "agent"
  const request = parseRequest(prompt)
  const route = routeFor(request, label)
  const occurrence = indexes.get(route) || 0
  indexes.set(route, occurrence + 1)
  const call = {
    route,
    occurrence: occurrence + 1,
    operation: request?.operation || null,
    slot: request?.identity?.chapter_slot || null,
    label,
    phase: options.phase || null,
    agent_type: options.agentType || null,
    request,
    schema: options.schema || null,
    start: ++clock,
    end: null,
  }
  trace.push(call)
  const step = config.responses[route]?.[occurrence]
  if (step === undefined) {
    call.end = ++clock
    return null
  }
  await waitBarrier(step)
  call.end = ++clock
  if (step?.throw) throw new Error(step.throw)
  return JSON.parse(JSON.stringify(step?.result ?? step))
}
const primitives = {
  agent,
  parallel: tasks => Promise.all(tasks.map(task => Promise.resolve().then(task))),
  phase: value => phases.push(String(value)),
  log: () => {},
}
const runtime = createRuntime(primitives)
const requests = config.requests || [{ slug: config.slug, meta: config.meta }]
const result = config.parallel_requests
  ? await Promise.all(requests.map(item => processBook(runtime, item.slug, item.meta)))
  : await processBook(runtime, requests[0].slug, requests[0].meta)
const unused = Object.fromEntries(
  Object.entries(config.responses)
    .map(([route, values]) => [route, values.length - (indexes.get(route) || 0)])
    .filter(([, count]) => count !== 0)
)
process.stdout.write(JSON.stringify({ result, trace, phases, unused }))
"""


def reply(result: Any, *, barrier: tuple[str, int, int] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"result": result}
    if barrier:
        name, size, rank = barrier
        value["barrier"] = {"name": name, "size": size, "rank": rank}
    return value


def run_book(
    tmp_path: Path,
    slug: str,
    responses: dict[str, list[Any]],
    *,
    meta: dict[str, Any] | None = None,
    requests: list[dict[str, Any]] | None = None,
    parallel_requests: bool = False,
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = (
        NODE_HARNESS.replace("__BOOK_URI__", json.dumps(BOOK.as_uri()))
        .replace("__RUNTIME_URI__", json.dumps(RUNTIME.as_uri()))
    )
    config = {
        "slug": slug,
        "meta": meta or book_meta(),
        "responses": responses,
        "requests": requests,
        "parallel_requests": parallel_requests,
    }
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, json.dumps(config)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["unused"] == {}, report
    return report


def book_meta(**overrides: Any) -> dict[str, Any]:
    value = {
        "title": "A Stage-Oriented Book",
        "authors": ["Ada Example"],
        "year": 2026,
        "publisher": "Example University Press",
        "isbn": "9780000000002",
        "category": "monograph",
        "format": "epub",
        "confidence": "verified",
    }
    value.update(overrides)
    return value


def paths(slug: str, extension: str = "epub") -> dict[str, str]:
    root = f"processing/chapters/{slug}"
    return {
        "source": f"sources/{slug}.{extension}",
        "root": root,
        "text": f"{root}/source.txt",
        "ocr": f"{root}/ocr.pdf",
        "ocr_text": f"{root}/ocr.txt",
        "manifest": f"{root}/manifest.json",
        "overview": f"vault/books/{slug}/00-overview.md",
    }


def chapters(slug: str) -> list[dict[str, Any]]:
    return [
        {
            "slot": "01",
            "title": "Alpha: Stable Inputs",
            "filename": "01_Alpha_Stable_Inputs.txt",
            "slug": "alpha-stable-inputs",
            "word_count": 800,
            "start_page": 1,
            "end_page": 10,
        },
        {
            "slot": "02",
            "title": "Beta: Joined Results",
            "filename": "02_Beta_Joined_Results.txt",
            "slug": "beta-joined-results",
            "word_count": 900,
            "start_page": 11,
            "end_page": 20,
        },
    ]


def chapter_input(slug: str, item: dict[str, Any]) -> str:
    return f"{paths(slug)['root']}/{item['filename']}"


def chapter_output(slug: str, item: dict[str, Any]) -> str:
    return f"vault/books/{slug}/ch{item['slot']}-{item['slug']}.md"


def year_evidence() -> dict[str, Any]:
    return {
        "slug_year": 2026,
        "source_years": {"catalog": 2026, "copyright": 2026},
        "pdf_signals": {
            "first_published": 2026,
            "copyright_year": 2026,
            "original_year": None,
            "other_years": [],
        },
        "recommended_year": 2026,
        "recommendation_reason": "two independent signals agree",
        "verdict": "MATCH",
    }


def acquire(slug: str, extension: str = "epub") -> dict[str, Any]:
    return {
        "acquired": 1,
        "failed": 0,
        "per_item": [
            {
                "kind": "book",
                "slug": slug,
                "status": "ok",
                "disposition": "reused",
                "identity_verified": True,
                "format": extension,
                "path": paths(slug, extension)["source"],
                "source": "existing_file",
                "isbn": "9780000000002",
                "year_evidence": year_evidence(),
                "attempts": [],
            }
        ],
    }


def issue(
    status: str,
    *,
    question: str | None = None,
) -> dict[str, Any] | None:
    if status == "complete":
        return None
    return {
        "code": "book.chapter_set_unavailable",
        "operation": "book.prepare",
        "summary": "The source did not yield a coherent chapter set",
        "user_question": question,
        "retryable": False,
    }


def prepare(
    slug: str,
    *,
    extension: str = "epub",
    status: str = "complete",
    members: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    p = paths(slug, extension)
    rows = members if members is not None else chapters(slug)
    complete = status == "complete"
    artifacts = []
    if complete:
        artifacts.append(
            {
                "role": "chapter_manifest",
                "path": p["manifest"],
                "exists": True,
                "usable": True,
            }
        )
        artifacts.extend(
            {
                "role": "normalized_chapter",
                "path": chapter_input(slug, row),
                "exists": True,
                "usable": True,
            }
            for row in rows
        )
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "book.prepare",
        "stage": "Prepare",
        "material_key": f"book:{slug}",
        "effect": "writer",
        "attempt": 1,
        "format": extension,
        "output_dir": p["root"],
        "selected_source": p["source"] if complete else None,
        "normalized_path": None,
        "manifest_path": p["manifest"],
        "manifest_fingerprint": "a" * 64 if complete else None,
        "mode": extension if complete else None,
        "disposition": "reused" if complete else None,
        "chapter_count": len(rows) if complete else 0,
        "chapters": rows if complete else [],
        "artifacts": artifacts,
        "steps": [
            {
                "capability": f"quasi-extract {extension}",
                "outcome": "reused" if complete else "failed",
                "summary": "Inspected the committed manifest and chapter boundaries",
            }
        ],
        "diagnostics": [] if complete else ["no stable chapter boundaries"],
        "terminal": {
            "status": status,
            "issue": issue(
                status,
                question=(
                    "Which of the two observed tables of contents should define the book?"
                    if status == "needs_input"
                    else None
                ),
            ),
        },
    }


def analyse(
    slug: str,
    slot: str,
    *,
    status: str = "succeeded",
    action: str = "create",
) -> dict[str, Any]:
    row = next(item for item in chapters(slug) if item["slot"] == slot)
    failed = status == "failed"
    return {
        "schema_version": "quasi.operation.chapter.analyse.receipt/0.1",
        "key": "chapter.analyse",
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "input_path": chapter_input(slug, row),
        "output_path": chapter_output(slug, row),
        "artifact_roles": ["chapter_canonical"],
        "action": action,
        "write_state": "not_written" if failed or action == "reconciled" else "written",
        "failure": (
            {
                "code": "book.chapter_analysis_failed",
                "operation_key": "chapter.analyse",
                "outcome": "known",
                "retryable": True,
            }
            if failed
            else None
        ),
    }


def synthesis(slug: str, *, action: str = "create") -> dict[str, Any]:
    rows = chapters(slug)
    return {
        "schema_version": "quasi.operation.book.synthesise.receipt/0.1",
        "key": "book.synthesise",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "input_paths": [chapter_output(slug, row) for row in rows],
        "output_path": paths(slug)["overview"],
        "artifact_roles": ["canonical"],
        "action": action,
        "chapters_analyzed": len(rows),
        "failure": None,
    }


def audit(
    slug: str,
    *,
    status: str = "clean",
    diagnostics: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    escalated = diagnostics or []
    return {
        "schema_version": "quasi.operation.book.audit.receipt/0.1",
        "key": "book.audit",
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "target_path": f"vault/books/{slug}",
        "remaining_violations": len(escalated),
        "escalated": escalated,
        "mutated_paths": [],
    }


def happy(slug: str, *, barrier: bool = False) -> dict[str, list[Any]]:
    return {
        "book.acquire": [reply(acquire(slug))],
        "book.prepare": [reply(prepare(slug))],
        "chapter.analyse:01": [
            reply(analyse(slug, "01"), barrier=("fanout", 2, 1) if barrier else None)
        ],
        "chapter.analyse:02": [
            reply(analyse(slug, "02"), barrier=("fanout", 2, 0) if barrier else None)
        ],
        "book.synthesise": [reply(synthesis(slug))],
        "book.audit": [reply(audit(slug))],
    }


def operations(report: dict[str, Any]) -> list[str | None]:
    return [entry["operation"] for entry in report["trace"]]


def test_book_happy_path_is_prepare_then_parallel_analysis_join(
    tmp_path: Path,
) -> None:
    slug = "book-stage-happy"
    report = run_book(tmp_path, slug, happy(slug, barrier=True))

    assert report["result"]["status"] == "ok"
    assert report["result"]["material_receipt"]["status"] == "complete"
    assert operations(report) == [
        "book.acquire",
        "book.prepare",
        "chapter.analyse",
        "chapter.analyse",
        "book.synthesise",
        "book.audit",
    ]
    analyses = [item for item in report["trace"] if item["operation"] == "chapter.analyse"]
    synthesis_call = next(item for item in report["trace"] if item["operation"] == "book.synthesise")
    assert max(item["start"] for item in analyses) < min(item["end"] for item in analyses)
    assert max(item["end"] for item in analyses) < synthesis_call["start"]
    assert report["phases"] == [
        "Acquire",
        "Prepare",
        "Analyse",
        "Synthesise",
        "Audit",
    ]


def test_book_prepare_envelope_gives_specialist_all_exact_capabilities(
    tmp_path: Path,
) -> None:
    slug = "book-stage-envelope"
    report = run_book(tmp_path, slug, happy(slug))
    call = next(item for item in report["trace"] if item["operation"] == "book.prepare")

    assert call["agent_type"] == "quasi:extract-agent"
    assert call["request"]["refs"]["manifest"] == paths(slug)["manifest"]
    assert call["request"]["output_limit"] == {"max_chapters": 150}
    assert any("--pages" in item for item in call["request"]["capabilities"])
    assert not any(item["operation"] in {"chapter.plan", "chapter.extract"} for item in report["trace"])


@pytest.mark.parametrize("status", ["needs_input", "failed"])
def test_book_prepare_terminal_stops_before_fanout(
    tmp_path: Path,
    status: str,
) -> None:
    slug = f"book-stage-{status.replace('_', '-')}"
    responses = {
        "book.acquire": [reply(acquire(slug))],
        "book.prepare": [reply(prepare(slug, status=status))],
    }
    report = run_book(tmp_path, slug, responses)

    assert report["result"]["status"] == (
        "needs_input" if status == "needs_input" else "extract_failed"
    )
    assert operations(report) == ["book.acquire", "book.prepare"]
    assert report["result"]["material_receipt"]["failure"]["code"] == (
        "book.chapter_set_unavailable"
    )


@pytest.mark.parametrize("value", [None, {"status": "complete"}])
def test_book_prepare_unknown_or_malformed_blocks_once(
    tmp_path: Path,
    value: Any,
) -> None:
    slug = "book-stage-unknown"
    responses = {
        "book.acquire": [reply(acquire(slug))],
        "book.prepare": [reply(value)],
    }
    report = run_book(tmp_path, slug, responses)

    assert report["result"]["status"] == "blocked"
    assert operations(report).count("book.prepare") == 1
    assert report["result"]["material_receipt"]["resume"] == {
        "operation_key": "book.reconcile"
    }


def test_prepare_complete_reproves_every_manifest_chapter(tmp_path: Path) -> None:
    slug = "book-stage-unproved-member"
    bad = prepare(slug)
    bad["artifacts"] = bad["artifacts"][:-1]
    responses = {
        "book.acquire": [reply(acquire(slug))],
        "book.prepare": [reply(bad)],
    }
    report = run_book(tmp_path, slug, responses)

    assert report["result"]["status"] == "blocked"
    assert report["result"]["material_receipt"]["failure"]["code"] == (
        "book.writer_receipt_mismatch"
    )


def test_epub_prepare_accepts_exact_manifest_titles_with_tabs(
    tmp_path: Path,
) -> None:
    slug = "book-stage-epub-tab-title"
    rows = chapters(slug)
    rows[0]["title"] = "1\tArtificial Communication? Algorithms as Partners"
    receipt = prepare(slug, members=rows)
    receipt["normalized_path"] = paths(slug)["text"]
    receipt["artifacts"].extend(
        [
            {
                "role": "normalized_document",
                "path": paths(slug)["text"],
                "exists": False,
                "usable": None,
            },
            {
                "role": "recovery_source",
                "path": paths(slug)["ocr"],
                "exists": False,
                "usable": None,
            },
        ]
    )
    responses = happy(slug)
    responses["book.prepare"] = [reply(receipt)]
    report = run_book(tmp_path, slug, responses)

    assert report["result"]["status"] == "ok"
    assert report["result"]["material_receipt"]["status"] == "complete"


def test_known_missing_chapter_refills_only_that_member(tmp_path: Path) -> None:
    slug = "book-stage-refill"
    responses = happy(slug)
    responses["chapter.analyse:02"] = [
        reply(analyse(slug, "02", status="failed")),
        reply(analyse(slug, "02")),
    ]
    report = run_book(tmp_path, slug, responses)

    assert report["result"]["status"] == "ok"
    assert operations(report).count("chapter.analyse") == 3
    slots = [item["slot"] for item in report["trace"] if item["operation"] == "chapter.analyse"]
    assert slots == ["01", "02", "02"]


def test_unknown_chapter_writer_never_replays_or_synthesises(tmp_path: Path) -> None:
    slug = "book-stage-chapter-unknown"
    responses = happy(slug)
    responses["chapter.analyse:02"] = [reply(None)]
    responses.pop("book.synthesise")
    responses.pop("book.audit")
    report = run_book(tmp_path, slug, responses)

    assert report["result"]["status"] == "blocked"
    assert operations(report).count("chapter.analyse") == 2
    assert "book.synthesise" not in operations(report)


def test_audit_foreign_target_fails_before_repair(tmp_path: Path) -> None:
    slug = "book-stage-owner"
    responses = happy(slug)
    responses["book.audit"] = [
        reply(
            audit(
                slug,
                status="partial",
                diagnostics=[
                    {
                        "path": "vault/papers/foreign.md",
                        "kind": "schema",
                        "reason": "foreign target",
                    }
                ],
            )
        )
    ]
    report = run_book(tmp_path, slug, responses)

    assert report["result"]["status"] == "audit_escalated"
    assert report["result"]["material_receipt"]["failure"]["code"] == (
        "book.repair_owner_unknown"
    )
    assert operations(report).count("book.audit") == 1


def test_exact_overview_diagnostic_routes_synthesis_repair_then_reaudit(
    tmp_path: Path,
) -> None:
    slug = "book-stage-audit-repair"
    responses = happy(slug)
    responses["book.audit"] = [
        reply(
            audit(
                slug,
                status="partial",
                diagnostics=[
                    {
                        "path": paths(slug)["overview"],
                        "kind": "schema",
                        "reason": "missing section",
                    }
                ],
            )
        ),
        reply(audit(slug)),
    ]
    responses["book.synthesise"] = [
        reply(synthesis(slug)),
        reply(synthesis(slug, action="repair")),
    ]
    report = run_book(tmp_path, slug, responses)

    assert report["result"]["status"] == "ok"
    assert operations(report).count("book.synthesise") == 2
    assert operations(report).count("book.audit") == 2
    assert report["result"]["material_receipt"]["disposition"] == "repaired"


def test_same_runtime_coalesces_identical_identity(tmp_path: Path) -> None:
    slug = "book-stage-coalesce"
    meta = book_meta()
    report = run_book(
        tmp_path,
        slug,
        happy(slug),
        requests=[{"slug": slug, "meta": meta}, {"slug": slug, "meta": meta}],
        parallel_requests=True,
    )

    assert report["result"][0] == report["result"][1]
    assert operations(report).count("book.prepare") == 1

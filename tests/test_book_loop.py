"""Module/mock contract tests for the Book v0.1 state machine.

These tests execute ``scripts/workflows/materials/book.mjs::processBook`` with the
real shared runtime and a scripted ``agent`` primitive.  They are not Pi or
Claude Workflow end-to-end tests: no model, network, or user vault is involved.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable
import zipfile

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BOOK_MODULE = PLUGIN_ROOT / "scripts/workflows" / "materials" / "book.mjs"
RUNTIME_MODULE = PLUGIN_ROOT / "scripts/workflows" / "runtime.mjs"
ENTRY_MODULE = PLUGIN_ROOT / "scripts/workflows" / "process-material.entry.mjs"
BUNDLE_MODULE = PLUGIN_ROOT / "workflows" / "process-material.mjs"
EPUB_BUILDER = (
    PLUGIN_ROOT / "tests" / "fixtures" / "make_synthetic_book.py"
)

MATERIAL_RECEIPT_VERSION = "quasi.material-loop.receipt/0.1"
_UNSET = object()


NODE_HARNESS = r"""
import { processBook } from __BOOK_URI__
import { createRuntime } from __RUNTIME_URI__
import { run as runWorkflow } from __ENTRY_URI__
import { readFile } from "node:fs/promises"

const config = JSON.parse(process.argv[1])
const trace = []
const phases = []
const logs = []
const missing = []
const indexes = new Map()
const barriers = new Map()
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
          parsed.material_key ||
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

function slotOf(prompt, request) {
  const candidates = [
    request?.slot,
    request?.chapter?.slot,
    request?.member?.slot,
    request?.input?.slot,
    request?.output?.slot,
    request?.diagnostic?.slot,
    request?.identity?.chapter_slot,
  ]
  for (const value of candidates) {
    if (value !== undefined && value !== null && String(value))
      return String(value)
  }
  const match = String(prompt).match(/^slot:\s*"?([^"\s]+)"?\s*$/m)
  if (match) return match[1]
  const commandMatch = String(prompt).match(/--slot\s+'([^']+)'/)
  return commandMatch ? commandMatch[1] : null
}

function modeOf(prompt, request) {
  if (request?.mode) return String(request.mode)
  const match = String(prompt).match(/^mode:\s*([^\s]+)\s*$/m)
  return match ? match[1] : null
}

function configuredRoute(operation, slot, mode, label) {
  const candidates = [
    slot && mode && `${operation}:${slot}:${mode}`,
    slot && `${operation}:${slot}`,
    mode && `${operation}:${mode}`,
    operation,
    label,
  ].filter(Boolean)
  return candidates.find(candidate =>
    Object.prototype.hasOwnProperty.call(config.responses, candidate)
  ) || candidates[0]
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
      for (const arrival of [...group.arrivals].sort(
        (left, right) => left.rank - right.rank
      )) {
        const index = [...group.arrivals]
          .sort((left, right) => left.rank - right.rank)
          .indexOf(arrival)
        setTimeout(arrival.resolve, index * 5)
      }
    }
  })
}

async function agent(prompt, options = {}) {
  const label = options.label || options.agentType || "agent"
  const request = parseRequest(prompt)
  const operation = operationOf(prompt, request)
  const slot = slotOf(prompt, request)
  const mode = modeOf(prompt, request)
  const route = configuredRoute(operation, slot, mode, label)
  const occurrence = indexes.get(route) || 0
  indexes.set(route, occurrence + 1)
  const call = {
    id: `${route}#${occurrence + 1}`,
    route,
    occurrence: occurrence + 1,
    operation,
    slot,
    mode,
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
  const step = steps && steps[occurrence]
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

const primitives = {
  agent,
  parallel: tasks =>
    Promise.all(tasks.map(task => Promise.resolve().then(task))),
  phase: name => phases.push(String(name)),
  log: message => logs.push(String(message)),
}
const runtime = createRuntime(primitives)
async function invokeWorkflow(args) {
  if (!config.bundle_path) return runWorkflow(primitives, args)
  const source = await readFile(config.bundle_path, "utf8")
  const body = source.replace(
    /^export\s+const\s+meta\s*=/m,
    "const meta ="
  )
  const AsyncFunction = Object.getPrototypeOf(
    async function () {}
  ).constructor
  const bundled = new AsyncFunction(
    "agent",
    "parallel",
    "phase",
    "log",
    "args",
    body,
  )
  return bundled(agent, primitives.parallel, primitives.phase, primitives.log, args)
}

let results
if (config.entry_requests) {
  const entryResults = []
  for (const args of config.entry_requests)
    entryResults.push(await invokeWorkflow(args))
  results = entryResults.length === 1 ? entryResults[0] : entryResults
} else {
  const requests = config.requests || [{
    slug: config.slug,
    meta: config.meta,
    opts: config.opts || {},
  }]
  results = config.parallel_requests
    ? await Promise.all(
        requests.map(request =>
          processBook(
            runtime,
            request.slug,
            request.meta,
            request.opts || {},
          )
        )
      )
    : await processBook(
        runtime,
        requests[0].slug,
        requests[0].meta,
        requests[0].opts || {},
      )
}

const unused = Object.fromEntries(
  Object.entries(config.responses)
    .map(([route, steps]) => [
      route,
      steps.length - (indexes.get(route) || 0),
    ])
    .filter(([, count]) => count !== 0)
)
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


def run_book_module(
    tmp_path: Path,
    *,
    slug: str,
    responses: dict[str, list[dict[str, Any]]],
    meta: dict[str, Any] | None = None,
    requests: list[dict[str, Any]] | None = None,
    parallel_requests: bool = False,
    allow_unused: bool = False,
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = (
        NODE_HARNESS.replace("__BOOK_URI__", json.dumps(BOOK_MODULE.as_uri()))
        .replace("__RUNTIME_URI__", json.dumps(RUNTIME_MODULE.as_uri()))
        .replace("__ENTRY_URI__", json.dumps(ENTRY_MODULE.as_uri()))
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


def run_book_entry(
    tmp_path: Path,
    *,
    entry_requests: list[dict[str, Any]],
    responses: dict[str, list[dict[str, Any]]],
    bundle: bool = False,
    allow_unused: bool = False,
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = (
        NODE_HARNESS.replace("__BOOK_URI__", json.dumps(BOOK_MODULE.as_uri()))
        .replace("__RUNTIME_URI__", json.dumps(RUNTIME_MODULE.as_uri()))
        .replace("__ENTRY_URI__", json.dumps(ENTRY_MODULE.as_uri()))
    )
    config = {
        "entry_requests": entry_requests,
        "responses": responses,
        "bundle_path": str(BUNDLE_MODULE) if bundle else None,
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


def book_meta(**overrides: Any) -> dict[str, Any]:
    value = {
        "title": "A Strict Synthetic Book",
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


def book_paths(slug: str, *, extension: str = "epub") -> dict[str, str]:
    return {
        "source": f"sources/{slug}.{extension}",
        "source_text": f"processing/chapters/{slug}/source.txt",
        "ocr": f"processing/chapters/{slug}/ocr.pdf",
        "ocr_text": f"processing/chapters/{slug}/ocr.txt",
        "chapters_dir": f"processing/chapters/{slug}",
        "manifest": f"processing/chapters/{slug}/manifest.json",
        "book_dir": f"vault/books/{slug}",
        "overview": f"vault/books/{slug}/00-overview.md",
    }


def year_evidence(year: int = 2026) -> dict[str, Any]:
    return {
        "slug_year": year,
        "source_years": {
            "catalog": year,
            "copyright": year,
        },
        "pdf_signals": {
            "first_published": year,
            "copyright_year": year,
            "original_year": None,
            "other_years": [],
        },
        "recommended_year": year,
        "recommendation_reason": "two exact sources agree",
        "verdict": "MATCH",
    }


def year_mismatch_evidence(
    year: int = 2026,
    recommended: int = 2025,
) -> dict[str, Any]:
    return {
        "slug_year": year,
        "source_years": {
            "catalog": recommended,
            "copyright": recommended,
        },
        "pdf_signals": {
            "first_published": recommended,
            "copyright_year": recommended,
            "original_year": None,
            "other_years": [],
        },
        "recommended_year": recommended,
        "recommendation_reason": "two exact sources prove another edition",
        "verdict": "MISMATCH",
    }


def year_ambiguous_evidence(year: int = 2026) -> dict[str, Any]:
    return {
        "slug_year": year,
        "source_years": {
            "catalog": 2025,
            "copyright": 2024,
        },
        "pdf_signals": {
            "first_published": None,
            "copyright_year": None,
            "original_year": None,
            "other_years": [],
        },
        "recommended_year": None,
        "recommendation_reason": "observed years have no unique winner",
        "verdict": "AMBIGUOUS",
    }


def year_gate_receipt(
    slug: str,
    *,
    evidence: dict[str, Any] | None = None,
    status: str = "year_mismatch",
) -> dict[str, Any]:
    prior_evidence = evidence or year_mismatch_evidence()
    return {
        "acquired": 0,
        "failed": 1,
        "per_item": [
            {
                "kind": "book",
                "slug": slug,
                "status": status,
                "disposition": None,
                "identity_verified": True,
                "format": None,
                "attempts": [
                    {
                        "source": "catalog",
                        "status": "downloaded",
                        "error": None,
                    }
                ],
                "tmp_path": (
                    f".quasi/temp/downloads/{slug}-prior.epub"
                ),
                "year_evidence": prior_evidence,
            }
        ],
    }


def accepted_year_decision_receipt(
    slug: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    receipt = download_receipt(slug)
    receipt["per_item"][0]["disposition"] = "created"
    receipt["per_item"][0]["source"] = "prior_temp_accept"
    receipt["per_item"][0]["year_evidence"] = evidence
    receipt["per_item"][0]["attempts"] = [
        {
            "source": "prior_temp_accept",
            "status": "ok",
            "error": None,
        }
    ]
    return receipt


def chapter_members(slug: str) -> list[dict[str, Any]]:
    paths = book_paths(slug)
    return [
        {
            "slot": "01",
            "filename": "01_Alpha_Stable_Inputs.txt",
            "slug": "alpha-stable-inputs",
            "title": "Alpha: Stable Inputs",
            "word_count": 800,
            "start_page": 1,
            "end_page": 10,
            "input_path": (
                f"{paths['chapters_dir']}/01_Alpha_Stable_Inputs.txt"
            ),
            "output_path": (
                f"{paths['book_dir']}/ch01-alpha-stable-inputs.md"
            ),
        },
        {
            "slot": "02",
            "filename": "02_Beta_Parallel_Chapters.txt",
            "slug": "beta-parallel-chapters",
            "title": "Beta: Parallel Chapters",
            "word_count": 900,
            "start_page": 11,
            "end_page": 20,
            "input_path": (
                f"{paths['chapters_dir']}/02_Beta_Parallel_Chapters.txt"
            ),
            "output_path": (
                f"{paths['book_dir']}/ch02-beta-parallel-chapters.md"
            ),
        },
        {
            "slot": "03",
            "filename": "03_Gamma_Audit_and_Repair.txt",
            "slug": "gamma-audit-and-repair",
            "title": "Gamma: Audit and Repair",
            "word_count": 1000,
            "start_page": 21,
            "end_page": 30,
            "input_path": (
                f"{paths['chapters_dir']}/03_Gamma_Audit_and_Repair.txt"
            ),
            "output_path": (
                f"{paths['book_dir']}/ch03-gamma-audit-and-repair.md"
            ),
        },
    ]


def manifest_members(slug: str) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in member.items()
            if key not in {"input_path", "output_path"}
        }
        for member in chapter_members(slug)
    ]


def download_receipt(
    slug: str,
    *,
    extension: str = "epub",
    status: str = "ok",
) -> dict[str, Any]:
    succeeded = status == "ok"
    item: dict[str, Any] = {
        "kind": "book",
        "slug": slug,
        "status": status,
        "disposition": "reused" if succeeded else None,
        "identity_verified": succeeded,
        "format": extension if succeeded else None,
        "attempts": [],
    }
    if succeeded:
        item.update(
            {
                "path": book_paths(slug, extension=extension)["source"],
                "source": "existing_file",
                "isbn": "9780000000002",
                "year_evidence": year_evidence(),
            }
        )
    else:
        item.update(
            {
                "failure_reason": "no exact edition was acquired",
                "attempts": [
                    {
                        "source": "catalog",
                        "status": "failed",
                        "error": "not available",
                    }
                ],
            }
        )
    return {
        "acquired": 1 if succeeded else 0,
        "failed": 0 if succeeded or status == "blocked" else 1,
        "per_item": [item],
    }


def text_extract_receipt(
    input_path: str,
    output_path: str,
) -> dict[str, Any]:
    return {
        "schema_version": "quasi.operation.document.extract-text.receipt/0.1",
        "key": "document.extract-text",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "input_path": input_path,
        "output_path": output_path,
        "artifact_roles": ["normalized_text"],
        "exit": 0,
        "exists": True,
        "size": 22000,
        "chars": 20000,
        "non_whitespace_chars": 18000,
        "pages": 24,
        "text_pages": 24,
        "failure": None,
    }


def readability_receipt(input_path: str, signal: str) -> dict[str, Any]:
    return {
        "schema_version": (
            "quasi.operation.document.assess-readability.receipt/0.1"
        ),
        "key": "document.assess-readability",
        "effect": "readonly",
        "status": "succeeded",
        "attempt": 1,
        "input_path": input_path,
        "artifact_roles": ["normalized_text"],
        "signal": signal,
        "diagnostics": [],
        "failure": None,
    }


def ocr_receipt(slug: str) -> dict[str, Any]:
    paths = book_paths(slug, extension="pdf")
    return {
        "schema_version": "quasi.operation.document.ocr.receipt/0.1",
        "key": "document.ocr",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "input_path": paths["source"],
        "output_path": paths["ocr"],
        "artifact_roles": ["recovery_source"],
        "exit": 0,
        "exists": True,
        "size": 120000,
        "failure": None,
    }


def plan_receipt(
    slug: str,
    *,
    input_path: str | None = None,
    normalized_path: str | None | object = _UNSET,
    mode: str = "manual",
) -> dict[str, Any]:
    paths = book_paths(slug, extension="pdf")
    return {
        "schema_version": "quasi.operation.chapter.plan.receipt/0.1",
        "key": "chapter.plan",
        "effect": "readonly",
        "status": "succeeded",
        "attempt": 1,
        "input_path": input_path or paths["source"],
        "normalized_path": (
            paths["source_text"]
            if normalized_path is _UNSET
            else normalized_path
        ),
        "artifact_roles": ["chapter_plan"],
        "mode": mode,
        "chapters": [
            {
                "title": member["title"],
                "start": member["start_page"],
                "end": member["end_page"],
            }
            for member in manifest_members(slug)
        ],
        "diagnostics": [],
        "failure": None,
    }


def chapter_extract_receipt(
    slug: str,
    *,
    input_path: str | None = None,
    mode: str = "epub",
    disposition: str = "created",
    generation: int = 1,
    members: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    paths = book_paths(
        slug,
        extension=(
            "epub"
            if (input_path or "").endswith(".epub") or mode == "epub"
            else "pdf"
        ),
    )
    chapters = members if members is not None else manifest_members(slug)
    return {
        "schema_version": "quasi.operation.chapter.extract.receipt/0.1",
        "key": "chapter.extract",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "input_path": input_path or paths["source"],
        "output_path": paths["chapters_dir"],
        "artifact_roles": ["chapter_manifest", "normalized_chapter"],
        "mode": mode,
        "disposition": disposition,
        "exit": 0,
        "manifest_path": paths["manifest"],
        "manifest_exists": True,
        "request_fingerprint": f"request-{generation}",
        "manifest_fingerprint": f"manifest-{generation}",
        "chapter_count": len(chapters),
        "chapters": chapters,
        "skipped": [],
        "removed_files": [],
        "limit": {"max_chapters": 150, "exceeded": False},
        "previous_manifest_preserved": generation > 1,
        "failure": None,
    }


def boundary_receipt(
    slug: str,
    signal: str = "ready",
    *,
    generation: int = 1,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    paths = book_paths(slug)
    members = manifest_members(slug)
    normalized_diagnostics = []
    for item in diagnostics or []:
        slot = item.get("slot")
        member = next(
            (candidate for candidate in members if candidate["slot"] == slot),
            None,
        )
        normalized_diagnostics.append(
            {
                "path": item["path"],
                "kind": item["kind"],
                "reason": item["reason"],
                "slot": slot,
                "title": item.get(
                    "title", member["title"] if member else None
                ),
                "start_page": item.get(
                    "start_page", member["start_page"] if member else None
                ),
                "end_page": item.get(
                    "end_page", member["end_page"] if member else None
                ),
            }
        )
    return {
        "schema_version": (
            "quasi.operation.chapter.assess-boundaries.receipt/0.1"
        ),
        "key": "chapter.assess-boundaries",
        "effect": "readonly",
        "status": "succeeded",
        "attempt": 1,
        "manifest_path": paths["manifest"],
        "input_paths": [
            f"{paths['chapters_dir']}/{member['filename']}"
            for member in members
        ],
        "artifact_roles": ["chapter_manifest", "normalized_chapter"],
        "signal": signal,
        "diagnostics": normalized_diagnostics,
        "failure": None,
    }


def chapter_analyse_receipt(
    slug: str,
    slot: str,
    *,
    action: str = "create",
    status: str = "succeeded",
) -> dict[str, Any]:
    member = next(
        item for item in chapter_members(slug) if item["slot"] == slot
    )
    failure = None
    if status == "failed":
        failure = {
            "code": "book.chapter_analysis_failed",
            "operation_key": "chapter.analyse",
            "outcome": "known",
            "retryable": True,
        }
    return {
        "schema_version": "quasi.operation.chapter.analyse.receipt/0.1",
        "key": "chapter.analyse",
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "input_path": member["input_path"],
        "output_path": member["output_path"],
        "artifact_roles": ["chapter_canonical"],
        "action": action,
        "write_state": (
            "written"
            if status == "succeeded" and action != "reconciled"
            else "not_written"
        ),
        "failure": failure,
    }


def chapter_repair_receipt(
    slug: str,
    slot: str,
    *,
    generation: int,
    input_path: str | None = None,
) -> dict[str, Any]:
    member = next(
        item for item in manifest_members(slug) if item["slot"] == slot
    )
    paths = book_paths(slug)
    return {
        "schema_version": "quasi.operation.chapter.extract.receipt/0.1",
        "key": "chapter.extract",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "input_path": input_path or paths["source"],
        "output_path": paths["chapters_dir"],
        "artifact_roles": ["chapter_manifest", "normalized_chapter"],
        "mode": "repair",
        "disposition": "repaired",
        "exit": 0,
        "manifest_path": paths["manifest"],
        "manifest_exists": True,
        "request_fingerprint": f"repair-request-{slot}-{generation}",
        "manifest_fingerprint": f"manifest-{generation}",
        "chapter_count": 3,
        "chapters": manifest_members(slug),
        "skipped": [],
        "removed_files": [],
        "limit": {"max_chapters": 150, "exceeded": False},
        "previous_manifest_preserved": True,
        "failure": None,
    }


def synthesis_receipt(
    slug: str,
    *,
    action: str = "create",
    present_slots: list[str] | None = None,
) -> dict[str, Any]:
    paths = book_paths(slug)
    slots = present_slots or ["01", "02", "03"]
    members = [
        member
        for member in chapter_members(slug)
        if member["slot"] in slots
    ]
    return {
        "schema_version": "quasi.operation.book.synthesise.receipt/0.1",
        "key": "book.synthesise",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "input_paths": [member["output_path"] for member in members],
        "output_path": paths["overview"],
        "artifact_roles": ["canonical"],
        "action": action,
        "chapters_analyzed": len(members),
        "failure": None,
    }


def audit_receipt(
    slug: str,
    *,
    status: str = "clean",
    diagnostics: list[dict[str, str]] | None = None,
    mutated_paths: list[str] | None = None,
) -> dict[str, Any]:
    escalated = diagnostics or []
    return {
        "schema_version": "quasi.operation.book.audit.receipt/0.1",
        "key": "book.audit",
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "target_path": book_paths(slug)["book_dir"],
        "remaining_violations": len(escalated),
        "escalated": escalated,
        "mutated_paths": mutated_paths or [],
    }


def happy_responses(
    slug: str,
    *,
    extension: str = "epub",
    barrier: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    paths = book_paths(slug, extension=extension)
    responses: dict[str, list[dict[str, Any]]] = {
        "book.acquire": [
            reply(download_receipt(slug, extension=extension))
        ],
    }
    if extension == "pdf":
        responses.update(
            {
                "document.extract-text": [
                    reply(
                        text_extract_receipt(
                            paths["source"], paths["source_text"]
                        )
                    )
                ],
                "document.assess-readability": [
                    reply(readability_receipt(paths["source_text"], "readable"))
                ],
                "chapter.plan": [
                    reply(
                        plan_receipt(
                            slug,
                            input_path=paths["source"],
                            normalized_path=paths["source_text"],
                            mode="manual",
                        )
                    )
                ],
            }
        )
    responses.update(
        {
            "chapter.extract": [
                reply(
                    chapter_extract_receipt(
                        slug,
                        input_path=(
                            paths["source"]
                            if extension == "epub"
                            else paths["source"]
                        ),
                        mode="epub" if extension == "epub" else "manual",
                    )
                )
            ],
            "chapter.assess-boundaries": [
                reply(boundary_receipt(slug))
            ],
            "chapter.analyse:01": [
                reply(
                    chapter_analyse_receipt(slug, "01"),
                    barrier=("chapter-fanout", 3, 3) if barrier else None,
                )
            ],
            "chapter.analyse:02": [
                reply(
                    chapter_analyse_receipt(slug, "02"),
                    barrier=("chapter-fanout", 3, 1) if barrier else None,
                )
            ],
            "chapter.analyse:03": [
                reply(
                    chapter_analyse_receipt(slug, "03"),
                    barrier=("chapter-fanout", 3, 2) if barrier else None,
                )
            ],
            "book.synthesise": [reply(synthesis_receipt(slug))],
            "book.audit": [reply(audit_receipt(slug))],
        }
    )
    return responses


def calls(
    report: dict[str, Any],
    operation: str,
    *,
    slot: str | None = None,
) -> list[dict[str, Any]]:
    return [
        call
        for call in report["trace"]
        if call["operation"] == operation
        and (slot is None or call["slot"] == slot)
    ]


def one_call(
    report: dict[str, Any],
    operation: str,
    *,
    slot: str | None = None,
    occurrence: int = 1,
) -> dict[str, Any]:
    found = calls(report, operation, slot=slot)
    assert len(found) >= occurrence, (operation, slot, found)
    return found[occurrence - 1]


def operation_names(report: dict[str, Any]) -> list[str]:
    return [call["operation"] for call in report["trace"]]


def assert_material_complete(result: dict[str, Any], slug: str) -> None:
    assert result["status"] == "ok"
    receipt = result["material_receipt"]
    assert receipt["schema_version"] == MATERIAL_RECEIPT_VERSION
    assert receipt["material_key"] == f"book:{slug}"
    assert receipt["status"] == "complete"
    assert receipt["audit"][-1]["status"] == "clean"
    assert receipt["audit"][-1]["remaining_violations"] == 0
    assert receipt["audit"][-1]["escalated"] == []
    assert receipt["failure"] is None


def assert_book_failure_code(result: dict[str, Any]) -> str:
    receipt = result["material_receipt"]
    assert receipt["status"] in {"blocked", "failed"}
    code = receipt["failure"]["code"]
    assert not code.startswith("paper.")
    return code


def request_path(request: dict[str, Any], field: str) -> Any:
    value = request[field]
    return value.get("path") if isinstance(value, dict) else value


def test_three_chapter_happy_path_has_out_of_order_fanout_barriers(
    tmp_path: Path,
) -> None:
    slug = "book-three-chapter-happy"
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses=happy_responses(slug, barrier=True),
    )

    assert_material_complete(report["result"], slug)
    assert report["phases"] == ["Book"]
    analyses = calls(report, "chapter.analyse")
    assert [call["slot"] for call in analyses] == ["01", "02", "03"]
    assert max(call["start"] for call in analyses) < min(
        call["end"] for call in analyses
    )
    assert [call["slot"] for call in sorted(analyses, key=lambda call: call["end"])] == [
        "02",
        "03",
        "01",
    ]

    synthesis = one_call(report, "book.synthesise")
    audit = one_call(report, "book.audit")
    assert max(call["end"] for call in analyses) < synthesis["start"]
    assert synthesis["end"] < audit["start"]
    for call, member in zip(analyses, chapter_members(slug), strict=True):
        request = call["request"]
        assert call["phase"] == "Book"
        assert call["label"] == f"analyse-ch{member['slot']}:{slug}"
        assert request["material_key"] == f"book:{slug}"
        assert request["operation"] == "chapter.analyse"
        assert request["identity"]["chapter_slot"] == member["slot"]
        assert request_path(request, "input") == member["input_path"]
        assert request_path(request, "output") == member["output_path"]

    synth_request = synthesis["request"]
    assert [item["path"] for item in synth_request["inputs"]] == [
        member["output_path"] for member in chapter_members(slug)
    ]
    assert request_path(synth_request, "output") == book_paths(slug)["overview"]


def test_book_identity_preserves_publisher_and_category_ingress(
    tmp_path: Path,
) -> None:
    slug = "book-publisher-ingress"
    meta = book_meta(
        publisher="Exact Academic Publisher",
        category="edited-volume",
    )
    report = run_book_module(
        tmp_path,
        slug=slug,
        meta=meta,
        responses=happy_responses(slug),
    )

    assert_material_complete(report["result"], slug)
    download_request = one_call(report, "book.acquire")["request"]
    download_identity = download_request["identity"]
    synth_identity = one_call(
        report, "book.synthesise"
    )["request"]["identity"]
    assert download_identity["publisher"] == "Exact Academic Publisher"
    assert download_identity["category"] == "edited-volume"
    assert download_request["identity_contract"]["fields"] == [
        "title",
        "authors",
        "year",
        "publisher",
        "isbn",
        "category",
    ]
    assert synth_identity["publisher"] == "Exact Academic Publisher"
    assert synth_identity["category"] == "edited-volume"


@pytest.mark.parametrize("bundle", [False, True], ids=["source", "bundle"])
def test_explicit_accept_current_year_decision_progresses_second_run(
    tmp_path: Path,
    bundle: bool,
) -> None:
    if bundle and "year_decision" not in BUNDLE_MODULE.read_text():
        pytest.skip("coordinator-owned bundle has not been regenerated")
    slug = "book-year-decision-current-2026"
    evidence = year_mismatch_evidence()
    reordered = {
        key: evidence[key]
        for key in reversed(list(evidence))
    }
    reordered["source_years"] = {
        key: evidence["source_years"][key]
        for key in reversed(list(evidence["source_years"]))
    }
    decision = {
        "action": "accept-current",
        "tmp_path": f".quasi/temp/downloads/{slug}-prior.epub",
        "year_evidence": evidence,
    }
    responses = happy_responses(slug)
    responses["book.acquire"] = [
        reply(year_gate_receipt(slug, evidence=evidence)),
        reply(accepted_year_decision_receipt(slug, reordered)),
    ]
    report = run_book_entry(
        tmp_path,
        entry_requests=[
            {"kind": "book", "slug": slug, "meta": book_meta()},
            {
                "kind": "book",
                "slug": slug,
                "meta": book_meta(),
                "year_decision": decision,
            },
        ],
        responses=responses,
        bundle=bundle,
    )

    first, second = report["result"]
    assert first["status"] == "year_mismatch"
    assert first["tmp_path"] == decision["tmp_path"]
    assert_material_complete(second, slug)
    download_calls = calls(report, "book.acquire")
    assert len(download_calls) == 2
    assert download_calls[0]["request"]["year_decision"] is None
    assert download_calls[1]["request"]["year_decision"] == decision
    assert download_calls[1]["request"]["batch_accept_year"] is False
    assert (
        download_calls[1]["request"]["shell_argv"][
            "year_decision_tmp_path"
        ]
        == f"'{decision['tmp_path']}'"
    )


def test_use_recommended_year_requires_and_accepts_updated_slug_and_meta(
    tmp_path: Path,
) -> None:
    old_slug = "book-year-decision-recommended-2026"
    new_slug = "book-year-decision-recommended-2025"
    evidence = year_mismatch_evidence()
    decision = {
        "action": "use-recommended-year",
        "tmp_path": f".quasi/temp/downloads/{old_slug}-prior.epub",
        "year_evidence": evidence,
    }
    responses = happy_responses(new_slug)
    responses["book.acquire"] = [
        reply(year_gate_receipt(old_slug, evidence=evidence)),
        reply(accepted_year_decision_receipt(new_slug, evidence)),
    ]
    report = run_book_entry(
        tmp_path,
        entry_requests=[
            {
                "kind": "book",
                "slug": old_slug,
                "meta": book_meta(),
            },
            {
                "kind": "book",
                "slug": new_slug,
                "meta": book_meta(year=2025),
                "year_decision": decision,
            },
        ],
        responses=responses,
    )

    assert report["result"][0]["status"] == "year_mismatch"
    assert_material_complete(report["result"][1], new_slug)
    assert one_call(
        report, "book.acquire", occurrence=2
    )["request"]["year_decision"] == decision


@pytest.mark.parametrize(
    "decision",
    [
        {
            "action": "use-recommended-year",
            "tmp_path": ".quasi/temp/downloads/prior.epub",
            "year_evidence": year_mismatch_evidence(),
        },
        {
            "action": "accept-current",
            "tmp_path": "../prior.epub",
            "year_evidence": year_mismatch_evidence(),
        },
        {
            "action": "accept-current",
            "tmp_path": ".quasi/temp/downloads/prior.epub",
            "year_evidence": year_mismatch_evidence(),
            "extra": True,
        },
    ],
    ids=["slug-not-updated", "unsafe-tmp", "extra-key"],
)
def test_invalid_year_decision_blocks_before_any_writer(
    tmp_path: Path,
    decision: dict[str, Any],
) -> None:
    report = run_book_entry(
        tmp_path,
        entry_requests=[
            {
                "kind": "book",
                "slug": "book-year-decision-invalid-2026",
                "meta": book_meta(),
                "year_decision": decision,
            }
        ],
        responses={},
    )

    assert report["result"]["status"] == "blocked"
    assert assert_book_failure_code(report["result"]) == (
        "book.year_decision_invalid"
    )
    assert report["trace"] == []


def test_year_decision_rejects_changed_prior_evidence(
    tmp_path: Path,
) -> None:
    slug = "book-year-decision-evidence-change-2026"
    evidence = year_mismatch_evidence()
    changed = json.loads(json.dumps(evidence))
    changed["recommendation_reason"] = "changed after the user gate"
    decision = {
        "action": "accept-current",
        "tmp_path": f".quasi/temp/downloads/{slug}-prior.epub",
        "year_evidence": evidence,
    }
    report = run_book_entry(
        tmp_path,
        entry_requests=[
            {
                "kind": "book",
                "slug": slug,
                "meta": book_meta(),
                "year_decision": decision,
            }
        ],
        responses={
            "book.acquire": [
                reply(accepted_year_decision_receipt(slug, changed))
            ]
        },
    )

    assert report["result"]["status"] == "blocked"
    receipt = report["result"]["material_receipt"]
    assert receipt["failure"]["outcome"] == "unknown"
    assert receipt["resume"] == {"operation_key": "book.reconcile"}
    assert len(calls(report, "book.acquire")) == 1


def test_missing_format_accepts_exact_epub_handoff(
    tmp_path: Path,
) -> None:
    slug = "book-inferred-epub-format"
    meta = book_meta()
    meta.pop("format")
    report = run_book_module(
        tmp_path,
        slug=slug,
        meta=meta,
        responses=happy_responses(slug, extension="epub"),
    )

    assert_material_complete(report["result"], slug)
    extract = one_call(report, "chapter.extract")
    assert extract["mode"] == "epub"
    assert f"input_path: sources/{slug}.epub" in extract["prompt"]
    assert calls(report, "document.extract-text") == []


def test_missing_format_accepts_exact_pdf_handoff(
    tmp_path: Path,
) -> None:
    slug = "book-inferred-pdf-format"
    meta = book_meta()
    meta.pop("format")
    report = run_book_module(
        tmp_path,
        slug=slug,
        meta=meta,
        responses=happy_responses(slug, extension="pdf"),
    )

    assert_material_complete(report["result"], slug)
    assert len(calls(report, "document.extract-text")) == 1
    assert len(calls(report, "document.assess-readability")) == 1
    assert len(calls(report, "chapter.plan")) == 1
    extract = one_call(report, "chapter.extract")
    assert extract["mode"] == "manual"
    assert f"input_path: sources/{slug}.pdf" in extract["prompt"]


@pytest.mark.parametrize(
    "mutation",
    ["foreign-path", "missing-format", "unknown-format"],
)
def test_missing_format_blocks_ambiguous_or_nonexact_handoff(
    tmp_path: Path,
    mutation: str,
) -> None:
    slug = f"book-format-handoff-{mutation}"
    meta = book_meta()
    meta.pop("format")
    receipt = download_receipt(slug)
    item = receipt["per_item"][0]
    if mutation == "foreign-path":
        item["path"] = f"sources/{slug}-other.epub"
    elif mutation == "missing-format":
        item.pop("format")
    else:
        item["format"] = "unknown"
    report = run_book_module(
        tmp_path,
        slug=slug,
        meta=meta,
        responses={"book.acquire": [reply(receipt)]},
    )

    assert report["result"]["status"] == "blocked"
    failure = report["result"]["material_receipt"]["failure"]
    assert failure["outcome"] == "unknown"
    assert not failure["code"].startswith("paper.")
    assert len(calls(report, "book.acquire")) == 1
    assert operation_names(report) == ["book.acquire"]


@pytest.mark.parametrize(
    "mutation",
    [
        "year-final-path",
        "year-source",
        "year-failure",
        "unsafe-tmp",
        "ambiguous-winner",
        "failure-tmp",
        "failure-year",
        "failure-source",
        "failure-isbn",
        "blocked-path",
    ],
)
def test_book_download_branch_matrices_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    slug = f"book-download-matrix-{mutation}"
    if mutation.startswith(("failure-", "blocked-")):
        status = "blocked" if mutation.startswith("blocked-") else (
            "download_failed"
        )
        receipt = download_receipt(slug, status=status)
        item = receipt["per_item"][0]
        if mutation == "failure-tmp":
            item["tmp_path"] = (
                f".quasi/temp/downloads/{slug}-prior.epub"
            )
        elif mutation == "failure-year":
            item["year_evidence"] = year_evidence()
        elif mutation == "failure-source":
            item["source"] = "catalog"
        elif mutation == "failure-isbn":
            item["isbn"] = "9780000000002"
        else:
            item["path"] = f"sources/{slug}.epub"
    else:
        receipt = year_gate_receipt(slug)
        item = receipt["per_item"][0]
        if mutation == "year-final-path":
            item["path"] = f"sources/{slug}.epub"
        elif mutation == "year-source":
            item["source"] = "catalog"
        elif mutation == "year-failure":
            item["failure_reason"] = "not a final failure branch"
        elif mutation == "unsafe-tmp":
            item["tmp_path"] = "../outside.epub"
        else:
            item["status"] = "year_ambiguous"
            item["year_evidence"] = year_ambiguous_evidence()
            item["year_evidence"]["recommended_year"] = 2025
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses={"book.acquire": [reply(receipt)]},
    )

    assert report["result"]["status"] == "blocked"
    material = report["result"]["material_receipt"]
    assert material["failure"]["outcome"] == "unknown"
    assert material["resume"] == {"operation_key": "book.reconcile"}
    assert operation_names(report) == ["book.acquire"]


def test_book_download_accepts_ambiguous_only_without_unique_winner(
    tmp_path: Path,
) -> None:
    slug = "book-year-ambiguous-no-winner"
    evidence = year_ambiguous_evidence()
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses={
            "book.acquire": [
                reply(
                    year_gate_receipt(
                        slug,
                        evidence=evidence,
                        status="year_ambiguous",
                    )
                )
            ]
        },
    )

    assert report["result"]["status"] == "year_ambiguous"
    assert report["result"]["year_evidence"] == evidence


@pytest.mark.parametrize(
    ("status", "expected_failed"),
    [("download_failed", 1), ("blocked", 0)],
)
def test_book_download_accepts_exact_failure_branch_shapes(
    tmp_path: Path,
    status: str,
    expected_failed: int,
) -> None:
    slug = f"book-download-exact-{status.replace('_', '-')}"
    raw = download_receipt(slug, status=status)
    assert raw["failed"] == expected_failed
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses={"book.acquire": [reply(raw)]},
    )

    assert report["result"]["status"] == status
    failure = report["result"]["material_receipt"]["failure"]
    assert failure["outcome"] == (
        "unknown" if status == "blocked" else "known"
    )
    assert len(calls(report, "book.acquire")) == 1


@pytest.mark.parametrize(
    "meta",
    [
        book_meta(category="research"),
        book_meta(format="mobi"),
    ],
    ids=["invalid-category", "invalid-format"],
)
def test_invalid_book_category_or_format_fails_before_writers(
    tmp_path: Path,
    meta: dict[str, Any],
) -> None:
    report = run_book_module(
        tmp_path,
        slug="book-invalid-identity-enum",
        meta=meta,
        responses={},
    )
    assert report["result"]["status"] == "blocked"
    assert report["result"]["material_receipt"]["failure"]["code"] == (
        "book.identity_invalid"
    )
    assert report["trace"] == []


def test_known_missing_chapter_refills_only_that_slot_once(
    tmp_path: Path,
) -> None:
    slug = "book-one-known-refill"
    responses = happy_responses(slug)
    responses["chapter.analyse:02"] = [
        reply(chapter_analyse_receipt(slug, "02", status="failed")),
        reply(chapter_analyse_receipt(slug, "02")),
    ]
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert_material_complete(report["result"], slug)
    assert len(calls(report, "chapter.analyse", slot="01")) == 1
    assert len(calls(report, "chapter.analyse", slot="02")) == 2
    assert len(calls(report, "chapter.analyse", slot="03")) == 1
    refill = one_call(report, "chapter.analyse", slot="02", occurrence=2)
    assert refill["label"].startswith(
        ("refill-ch02:", "analyse-ch02:")
    )
    assert (
        max(call["end"] for call in calls(report, "chapter.analyse"))
        < one_call(report, "book.synthesise")["start"]
    )


def test_second_known_miss_returns_exact_chapter_inventory(
    tmp_path: Path,
) -> None:
    slug = "book-refill-exhausted"
    responses = happy_responses(slug)
    responses["chapter.analyse:02"] = [
        reply(chapter_analyse_receipt(slug, "02", status="failed")),
        reply(chapter_analyse_receipt(slug, "02", status="failed")),
    ]
    responses.pop("book.synthesise")
    responses.pop("book.audit")
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    result = report["result"]
    assert result["status"] == "chapters_incomplete"
    assert result["expected_slots"] == ["01", "02", "03"]
    assert result["present_slots"] == ["01", "03"]
    assert result["missing_slots"] == ["02"]
    receipt = result["material_receipt"]
    assert receipt["status"] == "failed"
    assert receipt["expected_slots"] == [
        "01",
        "02",
        "03",
    ]
    assert receipt["present_slots"] == [
        "01",
        "03",
    ]
    assert receipt["missing_slots"] == ["02"]
    assert len(calls(report, "chapter.analyse", slot="02")) == 2
    assert "book.synthesise" not in operation_names(report)


def pdf_ocr_responses(slug: str) -> dict[str, list[dict[str, Any]]]:
    paths = book_paths(slug, extension="pdf")
    responses = happy_responses(slug, extension="pdf")
    responses["document.extract-text"] = [
        reply(text_extract_receipt(paths["source"], paths["source_text"])),
        reply(text_extract_receipt(paths["ocr"], paths["ocr_text"])),
    ]
    responses["document.assess-readability"] = [
        reply(readability_receipt(paths["source_text"], "needs_ocr")),
        reply(readability_receipt(paths["ocr_text"], "readable")),
    ]
    responses["document.ocr"] = [reply(ocr_receipt(slug))]
    responses["chapter.plan"] = [
        reply(
            plan_receipt(
                slug,
                input_path=paths["ocr"],
                normalized_path=paths["ocr_text"],
            )
        )
    ]
    responses["chapter.extract"] = [
        reply(
            chapter_extract_receipt(
                slug,
                input_path=paths["ocr"],
                mode="manual",
            )
        )
    ]
    return responses


def test_typed_readability_alone_triggers_one_ocr_recovery(
    tmp_path: Path,
) -> None:
    slug = "book-pdf-needs-ocr"
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses=pdf_ocr_responses(slug),
        meta=book_meta(format="pdf"),
    )
    assert_material_complete(report["result"], slug)
    assert len(calls(report, "document.ocr")) == 1
    extracts = calls(report, "document.extract-text")
    assessments = calls(report, "document.assess-readability")
    assert len(extracts) == len(assessments) == 2
    assert extracts[0]["end"] < assessments[0]["start"]
    assert assessments[0]["end"] < one_call(report, "document.ocr")["start"]
    assert one_call(report, "document.ocr")["end"] < extracts[1]["start"]
    assert extracts[1]["end"] < assessments[1]["start"]
    assert assessments[1]["end"] < one_call(report, "chapter.plan")["start"]
    assert one_call(report, "chapter.plan")["end"] < one_call(
        report, "chapter.extract"
    )["start"]
    assert one_call(report, "chapter.extract")["end"] < one_call(
        report, "chapter.assess-boundaries"
    )["start"]
    assert one_call(report, "chapter.assess-boundaries")["end"] < min(
        call["start"] for call in calls(report, "chapter.analyse")
    )


def test_ocr_prose_cannot_override_typed_readable_signal(
    tmp_path: Path,
) -> None:
    slug = "book-pdf-ocr-prose-only"
    responses = happy_responses(slug, extension="pdf")
    paths = book_paths(slug, extension="pdf")
    readable = readability_receipt(paths["source_text"], "readable")
    readable["diagnostics"] = [
        "The chapter discusses OCR as a historical technique."
    ]
    responses["document.assess-readability"] = [reply(readable)]
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses=responses,
        meta=book_meta(format="pdf"),
    )

    assert_material_complete(report["result"], slug)
    assert calls(report, "document.ocr") == []


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {"status": "cancelled"},
        {
            "schema_version": "wrong",
            "key": "document.ocr",
            "effect": "writer",
            "status": "succeeded",
        },
    ],
    ids=["null", "cancelled", "mismatch"],
)
def test_ocr_unknown_blocks_once_without_downstream_analysis(
    tmp_path: Path,
    bad: Any,
) -> None:
    slug = "book-ocr-unknown"
    responses = pdf_ocr_responses(slug)
    responses["document.ocr"] = [reply(bad)]
    responses["document.extract-text"] = [
        responses["document.extract-text"][0]
    ]
    responses["document.assess-readability"] = [
        responses["document.assess-readability"][0]
    ]
    for route in (
        "chapter.plan",
        "chapter.extract",
        "chapter.assess-boundaries",
        "chapter.analyse:01",
        "chapter.analyse:02",
        "chapter.analyse:03",
        "book.synthesise",
        "book.audit",
    ):
        responses.pop(route)
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses=responses,
        meta=book_meta(format="pdf"),
    )

    assert report["result"]["status"] == "blocked"
    assert_book_failure_code(report["result"])
    assert len(calls(report, "document.ocr")) == 1
    assert "chapter.plan" not in operation_names(report)
    assert not any(call["label"].endswith(":retry") for call in report["trace"])


def test_needs_replan_runs_one_plan_and_one_fenced_replacement(
    tmp_path: Path,
) -> None:
    slug = "book-needs-replan"
    responses = happy_responses(slug)
    responses["chapter.extract"] = [
        reply(chapter_extract_receipt(slug, generation=1)),
        reply(
            chapter_extract_receipt(
                slug,
                input_path=book_paths(slug)["source"],
                mode="manual",
                disposition="replaced",
                generation=2,
            )
        ),
    ]
    responses["chapter.assess-boundaries"] = [
        reply(
            boundary_receipt(
                slug,
                "needs_replan",
                generation=1,
                diagnostics=[
                    {
                        "path": book_paths(slug)["manifest"],
                        "kind": "chapter_boundaries_systemic",
                        "reason": "the first plan merges two chapters",
                    }
                ],
            )
        ),
        reply(boundary_receipt(slug, generation=2)),
    ]
    responses["chapter.plan"] = [
        reply(
            plan_receipt(
                slug,
                input_path=book_paths(slug)["source"],
                normalized_path=None,
            )
        )
    ]
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert_material_complete(report["result"], slug)
    assert len(calls(report, "chapter.plan")) == 1
    extracts = calls(report, "chapter.extract")
    assert len(extracts) == 2
    replacement = extracts[1]
    assert replacement["mode"] == "manual"
    assert "--expected-manifest-fingerprint 'manifest-1'" in replacement[
        "prompt"
    ]
    assert extracts[0]["end"] < one_call(
        report, "chapter.assess-boundaries", occurrence=1
    )["start"]
    assert one_call(
        report, "chapter.assess-boundaries", occurrence=1
    )["end"] < one_call(report, "chapter.plan")["start"]
    assert one_call(report, "chapter.plan")["end"] < extracts[1]["start"]
    assessments = calls(report, "chapter.assess-boundaries")
    assert len(assessments) == 2
    assert extracts[1]["end"] < assessments[1]["start"]
    assert assessments[1]["end"] < min(
        call["start"] for call in calls(report, "chapter.analyse")
    )
    assert "--chapters '" in replacement["prompt"]
    assert "--pages" not in replacement["prompt"]


def test_local_repairs_are_serial_and_keep_other_members_stable(
    tmp_path: Path,
) -> None:
    slug = "book-local-boundary-repair"
    responses = happy_responses(slug, extension="pdf")
    paths = book_paths(slug, extension="pdf")
    responses["chapter.assess-boundaries"] = [
        reply(
            boundary_receipt(
                slug,
                "needs_repair",
                diagnostics=[
                    {
                        "slot": "02",
                        "path": (
                            f"{paths['chapters_dir']}/"
                            "02_Beta_Parallel_Chapters.txt"
                        ),
                        "kind": "truncated_end",
                        "reason": "last sentence is incomplete",
                        "pages": "11-20",
                    },
                    {
                        "slot": "03",
                        "path": (
                            f"{paths['chapters_dir']}/"
                            "03_Gamma_Audit_and_Repair.txt"
                        ),
                        "kind": "wrong_start",
                        "reason": "starts with the previous chapter",
                        "pages": "21-30",
                    },
                ],
            )
        ),
        reply(boundary_receipt(slug, generation=3)),
    ]
    responses["chapter.extract:02:repair"] = [
        reply(
            chapter_repair_receipt(
                slug,
                "02",
                generation=2,
                input_path=paths["source"],
            )
        )
    ]
    responses["chapter.extract:03:repair"] = [
        reply(
            chapter_repair_receipt(
                slug,
                "03",
                generation=3,
                input_path=paths["source"],
            )
        )
    ]
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses=responses,
        meta=book_meta(format="pdf"),
    )

    assert_material_complete(report["result"], slug)
    repairs = [
        call
        for call in calls(report, "chapter.extract")
        if call["mode"] == "repair"
    ]
    assert [call["slot"] for call in repairs] == ["02", "03"]
    assert repairs[0]["end"] < repairs[1]["start"]
    original = {
        member["slot"]: (member["filename"], member["slug"])
        for member in manifest_members(slug)
    }
    for repair in repairs:
        assert f"--slot '{repair['slot']}'" in repair["prompt"]
        assert "--expected-manifest-fingerprint" in repair["prompt"]
    assert "--expected-manifest-fingerprint 'manifest-1'" in repairs[0][
        "prompt"
    ]
    assert "--expected-manifest-fingerprint 'manifest-2'" in repairs[1][
        "prompt"
    ]
    assert all("--slot '01'" not in repair["prompt"] for repair in repairs)
    final_members = {
        member["slot"]: (member["filename"], member["slug"])
        for member in chapter_repair_receipt(
            slug,
            "03",
            generation=3,
            input_path=paths["source"],
        )["chapters"]
    }
    assert final_members == original


def test_boundary_repair_budget_exhaustion_fails_closed(
    tmp_path: Path,
) -> None:
    slug = "book-repair-budget-exhausted"
    responses = happy_responses(slug, extension="pdf")
    paths = book_paths(slug, extension="pdf")
    diagnostic = {
        "slot": "02",
        "path": f"{paths['chapters_dir']}/02_Beta_Parallel_Chapters.txt",
        "kind": "truncated_end",
        "reason": "last sentence remains incomplete",
        "pages": "11-20",
    }
    responses["chapter.assess-boundaries"] = [
        reply(
            boundary_receipt(
                slug, "needs_repair", diagnostics=[diagnostic]
            )
        ),
        reply(
            boundary_receipt(
                slug,
                "needs_repair",
                generation=2,
                diagnostics=[diagnostic],
            )
        ),
    ]
    responses["chapter.extract:02:repair"] = [
        reply(
            chapter_repair_receipt(
                slug,
                "02",
                generation=2,
                input_path=paths["source"],
            )
        )
    ]
    for route in (
        "chapter.analyse:01",
        "chapter.analyse:02",
        "chapter.analyse:03",
        "book.synthesise",
        "book.audit",
    ):
        responses.pop(route)
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses=responses,
        meta=book_meta(format="pdf"),
    )

    assert report["result"]["status"] == "extract_failed"
    assert report["result"]["material_receipt"]["status"] == "failed"
    assert len(
        [
            call
            for call in calls(report, "chapter.extract")
            if call["mode"] == "repair"
        ]
    ) == 1
    assert calls(report, "chapter.analyse") == []


def set_bad_writer_response(
    slug: str,
    target: str,
    bad: Any,
) -> dict[str, list[dict[str, Any]]]:
    extension = (
        "pdf"
        if target
        in {"document.extract-text", "document.ocr", "chapter.repair"}
        else "epub"
    )
    responses = (
        pdf_ocr_responses(slug)
        if target == "document.ocr"
        else happy_responses(slug, extension=extension)
    )
    if target == "chapter.repair":
        paths = book_paths(slug)
        responses["chapter.assess-boundaries"] = [
            reply(
                boundary_receipt(
                    slug,
                    "needs_repair",
                    diagnostics=[
                        {
                            "slot": "02",
                            "path": (
                                f"{paths['chapters_dir']}/"
                                "02_Beta_Parallel_Chapters.txt"
                            ),
                            "kind": "truncated_end",
                            "reason": "known local boundary defect",
                            "pages": "11-20",
                        }
                    ],
                )
            )
        ]
        responses["chapter.extract:02:repair"] = [reply(bad)]
    elif target == "chapter.analyse":
        responses["chapter.analyse:02"] = [reply(bad)]
    else:
        responses[target] = [reply(bad)]
    return responses


WRITER_CASES = [
    ("download", "book.acquire"),
    ("extract-text", "document.extract-text"),
    ("ocr", "document.ocr"),
    ("chapter-extract", "chapter.extract"),
    ("chapter-repair", "chapter.repair"),
    ("chapter-analyse", "chapter.analyse"),
    ("synth", "book.synthesise"),
    ("audit", "book.audit"),
]


@pytest.mark.parametrize(
    ("stage", "operation"),
    WRITER_CASES,
    ids=[case[0] for case in WRITER_CASES],
)
@pytest.mark.parametrize(
    "bad_factory",
    [
        pytest.param(lambda operation: None, id="null"),
        pytest.param(
            lambda operation: {
                "key": operation,
                "effect": "writer",
                "status": "cancelled",
            },
            id="cancelled",
        ),
        pytest.param(
            lambda operation: {
                "schema_version": "quasi.operation.mismatch/0",
                "key": operation,
                "effect": "writer",
                "status": "succeeded",
            },
            id="malformed",
        ),
    ],
)
def test_every_book_writer_unknown_blocks_without_same_run_replay(
    tmp_path: Path,
    stage: str,
    operation: str,
    bad_factory: Callable[[str], Any],
) -> None:
    slug = f"unknown-{operation.replace('.', '-')}"
    responses = set_bad_writer_response(
        slug, operation, bad_factory(operation)
    )
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses=responses,
        meta=book_meta(
            format=(
                "pdf"
                if operation
                in {
                    "document.extract-text",
                    "document.ocr",
                    "chapter.repair",
                }
                else "epub"
            )
        ),
        allow_unused=True,
    )

    assert report["result"]["status"] == "blocked"
    receipt = report["result"]["material_receipt"]
    assert_book_failure_code(report["result"])
    assert receipt["failure"]["outcome"] == "unknown"
    expected_operation = (
        "chapter.extract"
        if stage in {"chapter-extract", "chapter-repair"}
        else operation
    )
    assert receipt["failure"]["operation_key"] == expected_operation
    assert receipt["stage"]
    assert receipt["resume"] == {"operation_key": "book.reconcile"}
    assert receipt["resume"]["operation_key"] != expected_operation
    if stage == "chapter-repair":
        target_calls = [
            call
            for call in calls(report, "chapter.extract")
            if call["mode"] == "repair"
        ]
    elif stage == "chapter-extract":
        target_calls = [
            call
            for call in calls(report, "chapter.extract")
            if call["mode"] != "repair"
        ]
    elif stage == "chapter-analyse":
        target_calls = calls(report, operation, slot="02")
    else:
        target_calls = calls(report, operation)
    assert len(target_calls) == 1
    assert not any(call["label"].endswith(":retry") for call in report["trace"])
    assert not any(
        call["start"] > target_calls[0]["end"]
        and call["operation"]
        in {
            "chapter.analyse",
            "book.synthesise",
            "book.audit",
        }
        for call in report["trace"]
    )


@pytest.mark.parametrize(
    ("slug", "member_mutator"),
    [
        ("../unsafe-book", None),
        ("unsafe/book", None),
        (
            "unsafe-filename-dotdot",
            lambda members: members[0].update(filename="../chapter.txt"),
        ),
        (
            "unsafe-filename-slash",
            lambda members: members[0].update(filename="nested/chapter.txt"),
        ),
        (
            "unsafe-member-slug-dotdot",
            lambda members: members[0].update(slug="../chapter"),
        ),
        (
            "unsafe-member-slug-slash",
            lambda members: members[0].update(slug="nested/chapter"),
        ),
        (
            "duplicate-member-slot",
            lambda members: members[1].update(slot=members[0]["slot"]),
        ),
        (
            "duplicate-member-slug",
            lambda members: members[1].update(slug=members[0]["slug"]),
        ),
        (
            "duplicate-member-output",
            lambda members: members[1].update(
                output_path=(
                    "vault/books/duplicate-member-output/"
                    "ch01-alpha-stable-inputs.md"
                )
            ),
        ),
        (
            "member-output-mismatch",
            lambda members: members[0].update(
                output_path="vault/books/elsewhere/ch01-wrong.md"
            ),
        ),
    ],
)
def test_chapter_members_fail_closed_before_fanout(
    tmp_path: Path,
    slug: str,
    member_mutator: Callable[[list[dict[str, Any]]], None] | None,
) -> None:
    if member_mutator is None:
        report = run_book_module(tmp_path, slug=slug, responses={})
    else:
        members = manifest_members(slug)
        member_mutator(members)
        responses = happy_responses(slug)
        responses["chapter.extract"] = [
            reply(chapter_extract_receipt(slug, members=members))
        ]
        for route in (
            "chapter.assess-boundaries",
            "chapter.analyse:01",
            "chapter.analyse:02",
            "chapter.analyse:03",
            "book.synthesise",
            "book.audit",
        ):
            responses.pop(route)
        report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert report["result"]["status"] in {"blocked", "extract_failed"}
    assert calls(report, "chapter.analyse") == []
    assert calls(report, "book.synthesise") == []


def audit_diagnostic(path: str, kind: str = "schema") -> dict[str, str]:
    return {
        "path": path,
        "kind": kind,
        "reason": f"{kind} diagnostic at exact target",
    }


def test_overview_audit_diagnostic_routes_only_to_synthesis(
    tmp_path: Path,
) -> None:
    slug = "book-audit-overview-owner"
    responses = happy_responses(slug)
    responses["book.audit"] = [
        reply(
            audit_receipt(
                slug,
                status="partial",
                diagnostics=[
                    audit_diagnostic(
                        book_paths(slug)["overview"],
                        "overview_schema",
                    )
                ],
            )
        ),
        reply(audit_receipt(slug)),
    ]
    responses["book.synthesise"].append(
        reply(synthesis_receipt(slug, action="repair"))
    )
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert_material_complete(report["result"], slug)
    assert len(calls(report, "book.synthesise")) == 2
    assert all(
        len(calls(report, "chapter.analyse", slot=slot)) == 1
        for slot in ("01", "02", "03")
    )
    assert len(calls(report, "book.audit")) == 2


def test_audit_mechanical_overview_fix_is_not_overwritten_by_synthesis(
    tmp_path: Path,
) -> None:
    slug = "book-audit-mechanical-overview"
    overview = book_paths(slug)["overview"]
    responses = happy_responses(slug)
    responses["book.audit"] = [
        reply(audit_receipt(slug, mutated_paths=[overview])),
        reply(audit_receipt(slug)),
    ]
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses=responses,
        allow_unused=True,
    )

    assert report["result"]["status"] == "ok"
    receipt = report["result"]["material_receipt"]
    assert receipt["status"] == "complete"
    assert receipt["disposition"] == "repaired"
    assert len(calls(report, "book.synthesise")) == 1
    assert len(calls(report, "book.audit")) in {1, 2}


def test_confirmed_chapter_repair_survives_reconciled_synthesis(
    tmp_path: Path,
) -> None:
    slug = "book-repair-disposition-monotonic"
    chapter_path = chapter_members(slug)[1]["output_path"]
    responses = happy_responses(slug)
    responses["book.audit"] = [
        reply(
            audit_receipt(
                slug,
                status="partial",
                diagnostics=[
                    audit_diagnostic(chapter_path, "chapter_schema")
                ],
            )
        ),
        reply(audit_receipt(slug)),
    ]
    responses["chapter.analyse:02"].append(
        reply(chapter_analyse_receipt(slug, "02", action="repair"))
    )
    responses["book.synthesise"].append(
        reply(synthesis_receipt(slug, action="reconciled"))
    )
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert_material_complete(report["result"], slug)
    assert report["result"]["material_receipt"]["disposition"] == (
        "repaired"
    )
    assert len(calls(report, "chapter.analyse", slot="02")) == 2
    assert one_call(
        report, "book.synthesise", occurrence=2
    )["request"]["mode"] == "repair"


def test_overview_only_reconciled_synthesis_does_not_mark_repaired(
    tmp_path: Path,
) -> None:
    slug = "book-overview-reconcile-not-repaired"
    overview = book_paths(slug)["overview"]
    responses = happy_responses(slug)
    responses["book.audit"] = [
        reply(
            audit_receipt(
                slug,
                status="partial",
                diagnostics=[
                    audit_diagnostic(overview, "overview_schema")
                ],
            )
        ),
        reply(audit_receipt(slug)),
    ]
    responses["book.synthesise"].append(
        reply(synthesis_receipt(slug, action="reconciled"))
    )
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert_material_complete(report["result"], slug)
    assert report["result"]["material_receipt"]["disposition"] == (
        "created"
    )
    assert len(calls(report, "book.synthesise")) == 2


def test_pure_synthesis_reconcile_is_reused_not_repaired(
    tmp_path: Path,
) -> None:
    slug = "book-pure-reconcile-disposition"
    reconciled = synthesis_receipt(slug, action="reconciled")
    reconciled.update(
        {
            "status": "blocked",
            "failure": {
                "code": "output_exists_requires_reconcile",
                "operation_key": "book.synthesise",
                "outcome": "unknown",
                "retryable": False,
            },
        }
    )
    responses = happy_responses(slug)
    responses["book.synthesise"] = [reply(reconciled)]
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert_material_complete(report["result"], slug)
    assert report["result"]["material_receipt"]["disposition"] == "reused"
    assert len(calls(report, "book.synthesise")) == 1


def test_audit_repairs_exact_chapter_then_synthesis_before_one_reaudit(
    tmp_path: Path,
) -> None:
    slug = "book-audit-exact-owners"
    paths = book_paths(slug)
    chapter_path = chapter_members(slug)[1]["output_path"]
    responses = happy_responses(slug)
    responses["book.audit"] = [
        reply(
            audit_receipt(
                slug,
                status="partial",
                diagnostics=[
                    audit_diagnostic(chapter_path, "chapter_schema"),
                    audit_diagnostic(chapter_path, "chapter_content"),
                    audit_diagnostic(paths["overview"], "overview_schema"),
                ],
            )
        ),
        reply(audit_receipt(slug)),
    ]
    responses["chapter.analyse:02"].append(
        reply(chapter_analyse_receipt(slug, "02", action="repair"))
    )
    responses["book.synthesise"].append(
        reply(synthesis_receipt(slug, action="repair"))
    )
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert_material_complete(report["result"], slug)
    assert len(calls(report, "chapter.analyse", slot="02")) == 2
    assert len(calls(report, "chapter.analyse", slot="01")) == 1
    assert len(calls(report, "chapter.analyse", slot="03")) == 1
    assert len(calls(report, "book.synthesise")) == 2
    assert len(calls(report, "book.audit")) == 2
    repair = one_call(report, "chapter.analyse", slot="02", occurrence=2)
    synth_repair = one_call(report, "book.synthesise", occurrence=2)
    audit2 = one_call(report, "book.audit", occurrence=2)
    assert repair["end"] < synth_repair["start"]
    assert synth_repair["end"] < audit2["start"]


def test_audit_chapter_repair_barrier_precedes_overview_repair(
    tmp_path: Path,
) -> None:
    slug = "book-audit-chapter-barrier"
    diagnostics = [
        audit_diagnostic(
            chapter_members(slug)[0]["output_path"], "chapter_alpha"
        ),
        audit_diagnostic(
            chapter_members(slug)[2]["output_path"], "chapter_gamma"
        ),
    ]
    responses = happy_responses(slug)
    responses["book.audit"] = [
        reply(
            audit_receipt(
                slug, status="partial", diagnostics=diagnostics
            )
        ),
        reply(audit_receipt(slug)),
    ]
    responses["chapter.analyse:01"].append(
        reply(
            chapter_analyse_receipt(slug, "01", action="repair"),
            barrier=("audit-chapter-repairs", 2, 2),
        )
    )
    responses["chapter.analyse:03"].append(
        reply(
            chapter_analyse_receipt(slug, "03", action="repair"),
            barrier=("audit-chapter-repairs", 2, 1),
        )
    )
    responses["book.synthesise"].append(
        reply(synthesis_receipt(slug, action="repair"))
    )
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    repairs = [
        one_call(report, "chapter.analyse", slot=slot, occurrence=2)
        for slot in ("01", "03")
    ]
    synth_repair = one_call(report, "book.synthesise", occurrence=2)
    assert max(repair["start"] for repair in repairs) < min(
        repair["end"] for repair in repairs
    )
    assert max(repair["end"] for repair in repairs) < synth_repair["start"]
    assert len(calls(report, "book.audit")) == 2


@pytest.mark.parametrize(
    "target",
    [
        "vault/books/another-book/ch01-foreign.md",
        "vault/papers/not-a-book.md",
        "../outside.md",
    ],
)
def test_unknown_audit_target_never_guesses_a_repair_owner(
    tmp_path: Path,
    target: str,
) -> None:
    slug = "book-audit-owner-unknown"
    responses = happy_responses(slug)
    responses["book.audit"] = [
        reply(
            audit_receipt(
                slug,
                status="partial",
                diagnostics=[audit_diagnostic(target)],
            )
        )
    ]
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert report["result"]["status"] == "audit_escalated"
    assert assert_book_failure_code(report["result"]) == (
        "book.repair_owner_unknown"
    )
    assert len(calls(report, "book.audit")) == 1
    assert len(calls(report, "book.synthesise")) == 1
    assert all(
        len(calls(report, "chapter.analyse", slot=slot)) == 1
        for slot in ("01", "02", "03")
    )


def test_known_audit_error_is_not_reclassified_as_unknown(
    tmp_path: Path,
) -> None:
    slug = "book-audit-known-error"
    responses = happy_responses(slug)
    responses["book.audit"] = [
        reply(audit_receipt(slug, status="error"))
    ]
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert report["result"]["status"] == "audit_escalated"
    failure = report["result"]["material_receipt"]["failure"]
    assert failure["outcome"] == "known"
    assert not failure["code"].startswith("paper.")
    assert len(calls(report, "book.audit")) == 1


@pytest.mark.parametrize(
    "foreign_field",
    ["escalated", "mutated"],
)
def test_audit_error_foreign_owner_precedes_known_status(
    tmp_path: Path,
    foreign_field: str,
) -> None:
    slug = f"book-audit-error-foreign-{foreign_field}"
    foreign = "vault/books/another-book/ch01-foreign.md"
    responses = happy_responses(slug)
    responses["book.audit"] = [
        reply(
            audit_receipt(
                slug,
                status="error",
                diagnostics=(
                    [audit_diagnostic(foreign)]
                    if foreign_field == "escalated"
                    else None
                ),
                mutated_paths=(
                    [foreign]
                    if foreign_field == "mutated"
                    else None
                ),
            )
        )
    ]
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert report["result"]["status"] == "audit_escalated"
    assert assert_book_failure_code(report["result"]) == (
        "book.repair_owner_unknown"
    )
    assert len(calls(report, "book.audit")) == 1
    assert len(calls(report, "book.synthesise")) == 1


def test_audit_error_with_exact_owned_mutation_remains_known(
    tmp_path: Path,
) -> None:
    slug = "book-audit-error-owned"
    responses = happy_responses(slug)
    responses["book.audit"] = [
        reply(
            audit_receipt(
                slug,
                status="error",
                mutated_paths=[book_paths(slug)["overview"]],
            )
        )
    ]
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert report["result"]["status"] == "audit_escalated"
    failure = report["result"]["material_receipt"]["failure"]
    assert failure["code"] == "book.audit_failed"
    assert failure["outcome"] == "known"


def test_malformed_audit_receipt_blocks_without_repair(
    tmp_path: Path,
) -> None:
    slug = "book-audit-malformed"
    responses = happy_responses(slug)
    responses["book.audit"] = [
        reply(
            {
                "schema_version": (
                    "quasi.operation.book.audit.agent-receipt/0.1"
                ),
                "key": "book.audit",
                "effect": "writer",
                "status": "clean",
                "attempt": 1,
                "target_path": book_paths(slug)["book_dir"],
                "remaining_violations": 1,
                "escalated": [],
                "mutated_paths": [],
            }
        )
    ]
    report = run_book_module(tmp_path, slug=slug, responses=responses)

    assert report["result"]["status"] == "blocked"
    assert_book_failure_code(report["result"])
    assert len(calls(report, "book.audit")) == 1


def test_same_runtime_coalesces_identical_book_identity(
    tmp_path: Path,
) -> None:
    slug = "book-same-run-coalesce"
    meta = book_meta()
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses=happy_responses(slug, barrier=True),
        requests=[
            {"slug": slug, "meta": meta},
            {"slug": slug, "meta": dict(meta)},
        ],
        parallel_requests=True,
    )

    assert report["result"][0] == report["result"][1]
    assert_material_complete(report["result"][0], slug)
    assert len(calls(report, "book.acquire")) == 1
    assert len(calls(report, "chapter.extract")) == 1
    assert len(calls(report, "chapter.analyse")) == 3
    assert len(calls(report, "book.synthesise")) == 1
    assert len(calls(report, "book.audit")) == 1


def test_same_slug_conflicting_identity_never_starts_second_writer(
    tmp_path: Path,
) -> None:
    slug = "book-same-run-conflict"
    first = book_meta()
    second = book_meta(title="A Different Book with the Same Slug")
    report = run_book_module(
        tmp_path,
        slug=slug,
        responses=happy_responses(slug, barrier=True),
        requests=[
            {"slug": slug, "meta": first},
            {"slug": slug, "meta": second},
        ],
        parallel_requests=True,
    )

    statuses = sorted(result["status"] for result in report["result"])
    assert statuses == ["blocked", "ok"]
    conflict = next(
        result for result in report["result"] if result["status"] == "blocked"
    )
    assert "identity" in assert_book_failure_code(conflict)
    assert len(calls(report, "book.acquire")) == 1
    assert len(calls(report, "chapter.analyse")) == 3


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_synthetic_epub_builder_is_deterministic_and_self_contained(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.epub"
    second = tmp_path / "second.epub"
    metadata_path = tmp_path / "metadata.json"
    command = [
        sys.executable,
        str(EPUB_BUILDER),
        str(first),
        "--slug",
        "quasi-book-e2e-fixed",
        "--metadata-json",
        str(metadata_path),
    ]
    built = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    subprocess.run(
        [
            sys.executable,
            str(EPUB_BUILDER),
            str(second),
            "--slug",
            "quasi-book-e2e-fixed",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert sha256(first) == sha256(second)
    assert json.loads(built.stdout) == json.loads(
        metadata_path.read_text(encoding="utf-8")
    )
    assert json.loads(built.stdout)["meta"]["isbn"] == "9780000000002"

    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == [
            "mimetype",
            "META-INF/container.xml",
            "OEBPS/content.opf",
            "OEBPS/toc.ncx",
            "OEBPS/ch01.xhtml",
            "OEBPS/ch02.xhtml",
            "OEBPS/ch03.xhtml",
        ]
        assert (
            archive.getinfo("mimetype").compress_type
            == zipfile.ZIP_STORED
        )
        assert archive.read("mimetype") == b"application/epub+zip"
        package = archive.read("OEBPS/content.opf").decode("utf-8")
        assert "<dc:date>2026</dc:date>" in package
        for slot, sentinel in (
            ("01", "ALPHA"),
            ("02", "BETA"),
            ("03", "GAMMA"),
        ):
            body = archive.read(f"OEBPS/ch{slot}.xhtml").decode("utf-8")
            assert len(body) > 100
            assert sentinel in body
            if slot == "01":
                assert "Copyright © 2026 Quasi Test Press." in body
            else:
                assert "Copyright © 2026 Quasi Test Press." not in body
            for other in {"ALPHA", "BETA", "GAMMA"} - {sentinel}:
                assert other not in body

    assert set(path.name for path in tmp_path.iterdir()) == {
        "first.epub",
        "second.epub",
        "metadata.json",
    }

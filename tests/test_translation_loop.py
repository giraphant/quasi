"""Stage-oriented contract tests for the Translation derivative loop."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/workflows" / "derivatives" / "translation.mjs"
RUNTIME = ROOT / "scripts/workflows" / "runtime.mjs"
SHA = {
    "source": "a" * 64,
    "output": "b" * 64,
    "manifest": "c" * 64,
    "candidates": "d" * 64,
}


NODE_HARNESS = r"""
import { processTranslation } from __MODULE_URI__
import { createRuntime } from __RUNTIME_URI__

const config = JSON.parse(process.argv[1])
const trace = []
const phases = []
const indexes = new Map()

function clone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value))
}
function balancedObject(text, start) {
  let depth = 0, quoted = false, escaped = false
  for (let index = start; index < text.length; index++) {
    const char = text[index]
    if (quoted) {
      if (escaped) escaped = false
      else if (char === "\\") escaped = true
      else if (char === '"') quoted = false
      continue
    }
    if (char === '"') { quoted = true; continue }
    if (char === "{") depth++
    if (char === "}" && --depth === 0)
      return text.slice(start, index + 1)
  }
  return null
}
function parseRequest(prompt) {
  const text = String(prompt)
  for (let index = 0; index < text.length; index++) {
    if (text[index] !== "{") continue
    const candidate = balancedObject(text, index)
    if (!candidate) continue
    try {
      const value = JSON.parse(candidate)
      if (value?.operation) return value
    } catch {}
  }
  return null
}
async function agent(prompt, options = {}) {
  const request = parseRequest(prompt)
  const operation = request?.operation || null
  const occurrence = indexes.get(operation) || 0
  indexes.set(operation, occurrence + 1)
  trace.push({
    operation,
    occurrence: occurrence + 1,
    label: options.label || null,
    phase: options.phase || null,
    agent_type: options.agentType || null,
    request,
    schema: options.schema || null,
  })
  const step = config.responses[operation]?.[occurrence]
  if (!step) return null
  if (step.throw) throw new Error(step.throw)
  return clone(step.result)
}

const primitives = {
  agent,
  parallel: tasks => Promise.all(tasks.map(task => Promise.resolve().then(task))),
  phase: name => phases.push(String(name)),
  log: () => {},
}
const runtime = createRuntime(primitives)
const execute = request => processTranslation(runtime, request.slug, request.meta)
const result = config.requests
  ? await Promise.all(config.requests.map(execute))
  : await execute({slug: config.slug, meta: config.meta})
const unused = Object.fromEntries(
  Object.entries(config.responses)
    .map(([key, rows]) => [key, rows.length - (indexes.get(key) || 0)])
    .filter(([, count]) => count !== 0)
)
process.stdout.write(JSON.stringify({result, trace, phases, unused}))
"""


def paths(slug: str, language: str = "zh-CN") -> dict[str, str]:
    tag = language.lower()
    return {
        "source": f"sources/{slug}.pdf",
        "paper_ocr": f"processing/papers/{slug}/ocr.pdf",
        "recovery": f"processing/translations/{slug}-{tag}-reocr.pdf",
        "output": f"processing/translations/{slug}-{tag}.pdf",
        "manifest": f"processing/translations/{slug}-{tag}.manifest.json",
    }


def meta(slug: str, **overrides: Any) -> dict[str, Any]:
    value = {
        "source_file": paths(slug)["source"],
        "target_language": "zh-CN",
        "toc_json": None,
        "toc_page_side": "original",
    }
    value.update(overrides)
    return value


def coverage(signal: str = "pass") -> dict[str, Any]:
    if signal == "pass":
        median, minimum = 0.31, 0.22
    elif signal == "not_applicable":
        median, minimum = None, None
    else:
        median, minimum = 0.1, 0.22
    return {
        "signal": signal,
        "median": median,
        "measured_pages": 3,
        "minimum_median": minimum,
        "weakest": [{"page": 1, "ratio": median or 0.0}],
        "detail": "coverage evidence from the committed translated PDF",
    }


def gate(kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "missing_fields": ["translate_api_key"] if kind == "configuration_required" else [],
        "candidates": [] if kind == "configuration_required" else [
            {
                "path": "sources/example.pdf",
                "sha256": SHA["source"],
                "size": 1000,
                "pages": 3,
            }
        ],
        "candidates_fingerprint": None if kind == "configuration_required" else SHA["candidates"],
    }


def issue(
    code: str,
    *,
    question: str | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    return {
        "code": code,
        "operation": "translation.prepare",
        "summary": f"Translation Prepare reached {code}",
        "user_question": question,
        "retryable": retryable,
    }


def prepare_stage(
    slug: str,
    *,
    status: str = "complete",
    source_path: str | None = None,
    backend: str | None = "pdf2zh",
    disposition: str | None = "created",
    recovered: bool = False,
    stage_gate: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    stage_issue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = paths(slug)
    complete = status == "complete"
    if validation is None and complete:
        validation = {
            "output_sha256": SHA["output"],
            "manifest_sha256": SHA["manifest"],
            "output_size": 8000,
            "source_pages": 3,
            "output_pages": 6,
            "toc_entries": 4,
            "coverage": coverage(),
        }
    source = None
    if complete:
        source = {
            "path": source_path or p["source"],
            "sha256": SHA["source"],
            "size": 4000,
            "pages": 3,
        }
    return {
        "schema_version": "quasi.stage.receipt/0.1",
        "operation": "translation.prepare",
        "stage": "Prepare",
        "material_key": f"translation:paper:{slug}:zh-CN",
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "slug": slug,
        "target_language": "zh-CN",
        "backend": backend if complete else None,
        "source": source,
        "output_path": p["output"],
        "manifest_path": p["manifest"],
        "disposition": disposition if complete else None,
        "recovered": recovered,
        "validation": validation if complete else None,
        "gate": stage_gate,
        "steps": [{
            "capability": "quasi-translate and exact output inspection",
            "outcome": disposition or "failed",
            "summary": "prepared one coherent translated generation",
        }],
        "diagnostics": [],
        "issue": stage_issue,
    }


def response(value: Any) -> dict[str, Any]:
    return {"result": value}


def run_translation(
    slug: str,
    responses: dict[str, list[dict[str, Any]]],
    *,
    metadata: dict[str, Any] | None = None,
    requests: list[dict[str, Any]] | None = None,
    allow_unused: bool = False,
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = (
        NODE_HARNESS.replace("__MODULE_URI__", json.dumps(MODULE.as_uri()))
        .replace("__RUNTIME_URI__", json.dumps(RUNTIME.as_uri()))
    )
    config: dict[str, Any] = {
        "slug": slug,
        "meta": metadata or meta(slug),
        "responses": responses,
    }
    if requests is not None:
        config["requests"] = requests
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, json.dumps(config)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    if not allow_unused:
        assert report["unused"] == {}, report
    return report


def test_translation_is_one_goal_owning_prepare_stage() -> None:
    slug = "translation-stage-happy"
    report = run_translation(
        slug,
        {"translation.prepare": [response(prepare_stage(slug))]},
    )
    result = report["result"]
    receipt = result["translation_receipt"]
    assert result["status"] == "success"
    assert receipt["status"] == "complete"
    assert receipt["stage"] == "validation"
    assert report["phases"] == ["Prepare"]
    assert [row["operation"] for row in report["trace"]] == ["translation.prepare"]
    assert [row["role"] for row in receipt["artifacts"]] == [
        "source", "translated_pdf", "translation_manifest"
    ]
    assert receipt["artifacts"][0]["producer"] == "translation.prepare"


def test_prepare_envelope_exposes_goal_refs_and_capabilities() -> None:
    slug = "translation-stage-envelope"
    report = run_translation(
        slug,
        {"translation.prepare": [response(prepare_stage(slug))]},
    )
    call = report["trace"][0]
    request = call["request"]
    assert call["agent_type"] == "quasi:translate-agent"
    assert call["phase"] == "Prepare"
    assert call["label"] == f"{slug}:prepare"
    assert request["objective"].startswith("Select or reconcile")
    assert request["source_request"]["path"] == paths(slug)["source"]
    assert request["refs"]["output"] == paths(slug)["output"]
    assert "quasi-extract ocr INPUT OUTPUT --layout --no-clobber --json" in request["capabilities"]


def test_prepare_may_complete_after_its_internal_ocr_recovery() -> None:
    slug = "translation-stage-recovered"
    report = run_translation(
        slug,
        {"translation.prepare": [response(prepare_stage(
            slug,
            source_path=paths(slug)["recovery"],
            disposition="recovered",
            recovered=True,
        ))]},
    )
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "complete"
    assert receipt["disposition"] == "recovered"
    assert receipt["source"]["path"] == paths(slug)["recovery"]
    assert len(report["trace"]) == 1


@pytest.mark.parametrize(
    ("kind", "legacy_status"),
    [("source_selection", "needs_source_selection"),
     ("configuration_required", "needs_auth")],
)
def test_prepare_needs_input_preserves_a_real_user_gate(
    kind: str,
    legacy_status: str,
) -> None:
    slug = f"translation-stage-{kind.replace('_', '-')}"
    question = "Choose the authoritative source." if kind == "source_selection" else "Configure the translation backend."
    receipt = prepare_stage(
        slug,
        status="needs_input",
        backend=None,
        disposition=None,
        stage_gate=gate(kind),
        stage_issue=issue(f"translation.{kind}", question=question),
    )
    report = run_translation(slug, {"translation.prepare": [response(receipt)]})
    result = report["result"]
    assert result["status"] == legacy_status
    assert result["translation_receipt"]["status"] == "needs_input"
    assert result["translation_receipt"]["gate"]["kind"] == kind


def test_schema_valid_known_failure_keeps_the_specialist_code() -> None:
    slug = "translation-stage-failed"
    receipt = prepare_stage(
        slug,
        status="failed",
        backend=None,
        disposition=None,
        stage_issue=issue("translation.output_unusable", retryable=True),
    )
    report = run_translation(slug, {"translation.prepare": [response(receipt)]})
    result = report["result"]
    assert result["status"] == "error"
    assert result["translation_receipt"]["failure"]["code"] == "translation.output_unusable"


@pytest.mark.parametrize("bad_result", [None, {"status": "complete"}])
def test_unknown_or_malformed_prepare_writer_blocks_without_replay(
    bad_result: Any,
) -> None:
    slug = "translation-stage-unknown"
    report = run_translation(
        slug,
        {"translation.prepare": [response(bad_result)]},
    )
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "blocked"
    assert receipt["failure"]["outcome"] == "unknown"
    assert len(report["trace"]) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("output_path", "processing/translations/foreign.pdf"),
        ("manifest_path", "processing/translations/foreign.json"),
        ("source", {"path": "sources/foreign.pdf", "sha256": SHA["source"], "size": 1, "pages": 1}),
    ],
)
def test_complete_prepare_must_prove_exact_owned_paths(field: str, value: Any) -> None:
    slug = "translation-stage-exact"
    receipt = prepare_stage(slug)
    receipt[field] = value
    report = run_translation(
        slug,
        {"translation.prepare": [response(receipt)]},
    )
    result = report["result"]["translation_receipt"]
    assert result["status"] == "blocked"
    assert result["failure"]["code"] == "translation.writer_receipt_mismatch"


def test_complete_prepare_requires_output_page_invariant() -> None:
    slug = "translation-stage-pages"
    receipt = prepare_stage(slug)
    receipt["validation"]["output_pages"] = 5
    report = run_translation(
        slug,
        {"translation.prepare": [response(receipt)]},
    )
    # The StructuredOutput shape is valid, but the Stage completion predicate
    # must also prove the derivative postcondition.
    assert report["result"]["translation_receipt"]["status"] == "blocked"


def test_identical_same_runtime_requests_coalesce_the_prepare_writer() -> None:
    slug = "translation-stage-coalesce"
    request = {"slug": slug, "meta": meta(slug)}
    report = run_translation(
        slug,
        {"translation.prepare": [response(prepare_stage(slug))]},
        requests=[request, request],
    )
    assert report["result"][0] == report["result"][1]
    assert len(report["trace"]) == 1

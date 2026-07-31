"""Stage-oriented contract tests for the Talk material loop.

These tests exercise the host-neutral source modules with a scripted Agent
primitive.  They verify graph boundaries; they do not run transcription
engines or claim native Claude Workflow coverage.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
TALK_MODULE = ROOT / "scripts/workflows" / "materials" / "talk.mjs"
RUNTIME_MODULE = ROOT / "scripts/workflows" / "runtime.mjs"

ENGINES = ["soniox", "apple", "parakeet"]
SHA = {
    "source": "a" * 64,
    "request": "b" * 64,
    "transcript": "c" * 64,
    "subtitle": "d" * 64,
    "canonical": "e" * 64,
    "soniox": "1" * 64,
    "apple": "2" * 64,
    "parakeet": "3" * 64,
}


NODE_HARNESS = r"""
import { processTalk } from __TALK_URI__
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
function operationOf(prompt, request) {
  if (request?.operation) return String(request.operation)
  const match = String(prompt).match(/^operation:\s*(\S+)/m)
  return match ? match[1] : null
}
function modeOf(prompt, request) {
  if (request?.mode) return String(request.mode)
  const match = String(prompt).match(/^mode:\s*(\S+)/m)
  return match ? match[1] : null
}
function routeOf(operation, mode) {
  const exact = mode ? `${operation}:${mode}` : operation
  return Object.hasOwn(config.responses, exact) ? exact : operation
}
async function agent(prompt, options = {}) {
  const request = parseRequest(prompt)
  const operation = operationOf(prompt, request)
  const mode = modeOf(prompt, request)
  const route = routeOf(operation, mode)
  const occurrence = indexes.get(route) || 0
  indexes.set(route, occurrence + 1)
  trace.push({
    operation, mode, route, occurrence: occurrence + 1,
    label: options.label || null,
    phase: options.phase || null,
    agent_type: options.agentType || null,
    request,
    schema: options.schema || null,
  })
  const step = config.responses[route]?.[occurrence]
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
const execute = request => processTalk(runtime, request.slug, request.meta)
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


def paths(slug: str) -> dict[str, str]:
    return {
        "media": f"sources/{slug}.wav",
        "processing": f"processing/talks/{slug}",
        "manifest": f"processing/talks/{slug}/manifest.json",
        "transcript": f"vault/talks/{slug}/transcript.md",
        "subtitle": f"vault/talks/{slug}/recording.srt",
        "canonical": f"vault/talks/{slug}/talk.md",
    }


def meta(slug: str, **overrides: Any) -> dict[str, Any]:
    value = {
        "title": "A Talk About Stage Units",
        "date": "2026-07-31",
        "media": paths(slug)["media"],
        "engines": list(ENGINES),
        "lang": "auto",
        "prepare_media": False,
    }
    value.update(overrides)
    return value


def transcript_artifacts(slug: str) -> list[dict[str, Any]]:
    p = paths(slug)
    rows = [
        {
            "role": "transcript",
            "path": p["transcript"],
            "sha256": SHA["transcript"],
            "size": 1600,
        },
        {
            "role": "subtitle",
            "path": p["subtitle"],
            "sha256": SHA["subtitle"],
            "size": 900,
        },
    ]
    rows.extend(
        {
            "role": "engine_transcript",
            "path": f"{p['processing']}/transcript.{engine}.srt",
            "sha256": SHA[engine],
            "size": 700,
        }
        for engine in ENGINES
    )
    return rows


def issue(operation: str, code: str, *, question: str | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "operation": operation,
        "summary": f"{operation} reached {code}",
        "user_question": question,
        "retryable": False,
    }


def prepare_stage(
    slug: str,
    *,
    status: str = "complete",
    classification: str | None = "live",
    canonical_exists: bool = False,
    canonical_action: str | None = None,
    transcript_changed: bool = False,
    artifacts: list[dict[str, Any]] | None = None,
    stage_issue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = paths(slug)
    owns_silent = status == "complete" and classification in {"dead", "empty"}
    canonical_exists = canonical_exists or owns_silent
    if owns_silent and canonical_action is None:
        canonical_action = "create"
    prepared_artifacts = transcript_artifacts(slug) if artifacts is None else artifacts
    if owns_silent and artifacts is None:
        prepared_artifacts = [
            *prepared_artifacts,
            {
                "role": "canonical",
                "path": p["canonical"],
                "sha256": SHA["canonical"],
                "size": 1000,
            },
        ]
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "talk.prepare",
        "stage": "Prepare",
        "material_key": f"talk:{slug}",
        "effect": "writer",
        "attempt": 1,
        "slug": slug,
        "source_observation": (
            {"path": p["media"], "sha256": SHA["source"]}
            if status == "complete"
            else None
        ),
        "generation_observation": (
            {
                "manifest_path": p["manifest"],
                "request_fingerprint": SHA["request"],
            }
            if status == "complete"
            else None
        ),
        "classification": classification or "unclassified",
        "transcript_changed": transcript_changed,
        "canonical_observation": (
            {
                "path": p["canonical"],
                "sha256": SHA["canonical"],
            }
            if canonical_exists
            else None
        ),
        "canonical_action": canonical_action,
        "artifacts": prepared_artifacts,
        "steps": [
            {
                "capability": "quasi-transcribe and transcript inspection",
                "outcome": "reused" if canonical_exists else "created",
                "summary": "prepared one coherent transcript generation",
            }
        ],
        "diagnostics": [],
        "terminal": {"status": status, "issue": stage_issue},
    }


def analyse(slug: str, action: str = "create") -> dict[str, Any]:
    inputs = [
        row for row in transcript_artifacts(slug)
        if row["role"] in {"transcript", "engine_transcript"}
    ]
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "talk.analyse",
        "stage": "Analyse",
        "material_key": f"talk:{slug}",
        "effect": "writer",
        "attempt": 1,
        "input_paths": [row["path"] for row in inputs],
        "input_sha256s": [row["sha256"] for row in inputs],
        "output_path": paths(slug)["canonical"],
        "artifact_roles": ["canonical"],
        "terminal": {"status": "complete", "issue": None, "action": action},
    }

def audit(
    slug: str,
    *,
    status: str = "clean",
    diagnostic_path: str | None = None,
    mutated: bool = False,
    pass_number: int = 1,
) -> dict[str, Any]:
    target = paths(slug)["canonical"]
    escalated = []
    if status == "partial":
        escalated = [{
            "path": diagnostic_path or target,
            "kind": "block_kind_mismatch",
            "reason": "the exact Talk product needs a semantic repair",
        }]
    terminal_status = "complete" if status in {"clean", "partial"} else "failed"
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "talk.audit",
        "stage": "Audit",
        "material_key": f"talk:{slug}",
        "effect": "writer",
        "attempt": 1,
        "target_path": target,
        "artifact_roles": ["canonical"],
        "pass": pass_number,
        "remaining_violations": len(escalated),
        "escalated": escalated,
        "mutated_paths": [target] if mutated else [],
        "terminal": {
            "status": terminal_status,
            "issue": (
                None
                if terminal_status == "complete"
                else {
                    "code": "talk.audit_failed",
                    "operation": "talk.audit",
                    "summary": "Talk Audit did not complete",
                    "user_question": None,
                    "retryable": False,
                }
            ),
        },
    }


def response(value: Any) -> dict[str, Any]:
    return {"result": value}


def happy_responses(slug: str, signal: str = "live") -> dict[str, list[dict[str, Any]]]:
    values = {
        "talk.prepare": [response(prepare_stage(slug, classification=signal))],
        "talk.audit": [response(audit(slug))],
    }
    if signal == "live":
        values["talk.analyse:create"] = [response(analyse(slug))]
    return values


def run_talk(
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
        NODE_HARNESS.replace("__TALK_URI__", json.dumps(TALK_MODULE.as_uri()))
        .replace("__RUNTIME_URI__", json.dumps(RUNTIME_MODULE.as_uri()))
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


def operations(report: dict[str, Any]) -> list[str]:
    return [row["operation"] for row in report["trace"]]


def test_live_talk_is_one_prepare_stage_then_analyse_and_audit() -> None:
    slug = "stage-talk-live"
    report = run_talk(slug, happy_responses(slug))
    assert report["result"]["status"] == "ok"
    assert report["result"]["material_receipt"]["status"] == "complete"
    assert operations(report) == ["talk.prepare", "talk.analyse", "talk.audit"]
    assert [row["phase"] for row in report["trace"]] == ["Prepare", "Analyse", "Audit"]
    assert report["phases"] == ["Recall", "Prepare", "Analyse", "Audit"]


def test_prepare_envelope_gives_the_specialist_goal_and_capabilities() -> None:
    slug = "stage-talk-envelope"
    report = run_talk(slug, happy_responses(slug))
    call = report["trace"][0]
    request = call["request"]
    assert call["agent_type"] == "quasi:transcribe-agent"
    assert call["label"] == f"{slug}:prepare"
    assert request["operation"] == "talk.prepare"
    assert request["stage"] == "Prepare"
    assert request["objective"].startswith("Produce, reconcile, and classify")
    assert request["refs"]["media"] == paths(slug)["media"]
    assert "quasi-transcribe run ... --json" in request["capabilities"]
    assert request["engines"] == ENGINES


@pytest.mark.parametrize("signal", ["dead", "empty"])
def test_dead_or_empty_talk_finishes_the_silent_product_in_prepare(signal: str) -> None:
    slug = f"stage-talk-{signal}"
    report = run_talk(slug, happy_responses(slug, signal))
    assert report["result"]["status"] == "ok"
    assert operations(report) == ["talk.prepare", "talk.audit"]
    assert [row["phase"] for row in report["trace"]] == ["Prepare", "Audit"]
    receipt = report["result"]["material_receipt"]
    canonical = [row for row in receipt["artifacts"] if row["role"] == "canonical"]
    assert len(canonical) == 1
    assert canonical[0]["producer"] == "talk.prepare:create"


def test_existing_coherent_talk_skips_product_rewrite() -> None:
    slug = "stage-talk-reconcile"
    responses = {
        "talk.prepare": [response(prepare_stage(slug, canonical_exists=True))],
        "talk.audit": [response(audit(slug))],
    }
    report = run_talk(slug, responses)
    assert operations(report) == ["talk.prepare", "talk.audit"]
    receipt = report["result"]["material_receipt"]
    assert receipt["status"] == "complete"
    assert receipt["disposition"] == "reused"
    assert any(row["role"] == "canonical" for row in receipt["artifacts"])


def test_prepare_needs_input_preserves_the_specialist_question() -> None:
    slug = "stage-talk-gate"
    gate = issue(
        "talk.prepare", "media_choice_required",
        question="Which of the two recordings is authoritative?",
    )
    receipt = prepare_stage(
        slug, status="needs_input", classification=None, artifacts=[], stage_issue=gate
    )
    report = run_talk(slug, {"talk.prepare": [response(receipt)]})
    assert report["result"]["status"] == "needs_input"
    assert report["result"]["question"] == gate["user_question"]
    assert operations(report) == ["talk.prepare"]


def test_prepare_known_failure_is_not_reclassified_as_malformed() -> None:
    slug = "stage-talk-failed"
    receipt = prepare_stage(
        slug,
        status="failed",
        classification=None,
        artifacts=[],
        stage_issue=issue("talk.prepare", "transcript_unusable"),
    )
    report = run_talk(slug, {"talk.prepare": [response(receipt)]})
    result = report["result"]
    assert result["status"] == "transcribe_failed"
    assert result["material_receipt"]["failure"]["code"] == "transcript_unusable"
    assert operations(report) == ["talk.prepare"]


@pytest.mark.parametrize("bad_result", [None, {"status": "complete"}])
def test_unknown_or_malformed_prepare_writer_is_called_once_and_blocks(
    bad_result: Any,
) -> None:
    slug = "stage-talk-unknown"
    report = run_talk(
        slug,
        {"talk.prepare": [response(bad_result)]},
    )
    result = report["result"]
    assert result["status"] == "blocked"
    assert result["material_receipt"]["failure"]["outcome"] == "unknown"
    assert operations(report) == ["talk.prepare"]


def test_complete_prepare_must_prove_exact_transcript_artifacts() -> None:
    slug = "stage-talk-exact-artifact"
    rows = transcript_artifacts(slug)
    rows[0]["path"] = "vault/talks/foreign/transcript.md"
    report = run_talk(
        slug,
        {"talk.prepare": [response(prepare_stage(slug, artifacts=rows))]},
    )
    assert report["result"]["status"] == "blocked"
    assert report["result"]["material_receipt"]["failure"]["code"] == (
        "talk.writer_receipt_mismatch"
    )


def test_missing_canonical_rejects_a_fabricated_zero_hash() -> None:
    slug = "stage-talk-zero-hash"
    receipt = prepare_stage(slug, canonical_exists=True)
    receipt["canonical_observation"]["sha256"] = "0" * 64
    report = run_talk(slug, {"talk.prepare": [response(receipt)]})
    assert report["result"]["status"] == "blocked"
    assert report["result"]["material_receipt"]["failure"]["code"] == (
        "talk.writer_receipt_mismatch"
    )
    assert operations(report) == ["talk.prepare"]


def test_exact_audit_diagnostic_gets_one_product_repair_and_reaudit() -> None:
    slug = "stage-talk-repair"
    responses = happy_responses(slug)
    responses["talk.audit"] = [
        response(audit(slug, status="partial")),
        response(audit(slug, pass_number=2)),
    ]
    responses["talk.analyse:repair"] = [response(analyse(slug, "repair"))]
    report = run_talk(slug, responses)
    assert operations(report) == [
        "talk.prepare", "talk.analyse", "talk.audit",
        "talk.analyse", "talk.audit",
    ]
    assert report["result"]["material_receipt"]["disposition"] == "repaired"
    assert report["phases"][-3:] == ["Analyse", "Audit", "Analyse", "Audit"][-3:]


@pytest.mark.parametrize("signal", ["dead", "empty"])
def test_silent_audit_repair_returns_to_prepare_once(signal: str) -> None:
    slug = f"stage-talk-{signal}-repair"
    responses = {
        "talk.prepare": [
            response(prepare_stage(slug, classification=signal)),
            response(
                prepare_stage(
                    slug,
                    classification=signal,
                    canonical_action="repair",
                )
            ),
        ],
        "talk.audit": [
            response(audit(slug, status="partial")),
            response(audit(slug, pass_number=2)),
        ],
    }
    report = run_talk(slug, responses)
    assert operations(report) == [
        "talk.prepare", "talk.audit", "talk.prepare", "talk.audit"
    ]
    assert [row["phase"] for row in report["trace"]] == [
        "Prepare", "Audit", "Prepare", "Audit"
    ]
    assert report["result"]["material_receipt"]["disposition"] == "repaired"


def test_foreign_audit_target_fails_without_guessing_an_owner() -> None:
    slug = "stage-talk-owner"
    responses = happy_responses(slug)
    responses["talk.audit"] = [
        response(audit(slug, status="partial", diagnostic_path="vault/papers/other.md"))
    ]
    report = run_talk(slug, responses)
    result = report["result"]
    assert result["status"] == "audit_escalated"
    assert result["material_receipt"]["failure"]["code"] == "talk.repair_owner_unknown"
    assert operations(report).count("talk.analyse") == 1


def test_identical_same_runtime_requests_coalesce_all_writers() -> None:
    slug = "stage-talk-coalesce"
    request = {"slug": slug, "meta": meta(slug)}
    report = run_talk(
        slug,
        happy_responses(slug),
        requests=[request, request],
    )
    assert report["result"][0] == report["result"][1]
    assert operations(report) == ["talk.prepare", "talk.analyse", "talk.audit"]

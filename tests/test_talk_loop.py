"""Mock/contract tests for the strict Talk v0.1 material loop.

These tests execute the host-neutral source modules with a scripted ``agent``
primitive. They are not Claude Workflow end-to-end tests and never invoke a
transcription engine or write a user vault.
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
ENTRY_MODULE = ROOT / "scripts/workflows" / "process-material.entry.mjs"
BUNDLE = ROOT / "workflows" / "process-material.mjs"

ENGINES = ["soniox", "apple", "parakeet"]
SHA = {
    "source": "a" * 64,
    "prepared": "f" * 64,
    "manifest": "b" * 64,
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
import { run as runWorkflow } from __ENTRY_URI__
import { readFile } from "node:fs/promises"

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
      if (value?.operation || value?.schema_version) return value
    } catch {}
  }
  return null
}
function operationOf(prompt, request) {
  if (request?.operation) return String(request.operation)
  const found = String(prompt).match(/^operation:\s*(\S+)/m)
  return found ? found[1] : null
}
function modeOf(prompt, request) {
  if (request?.mode) return String(request.mode)
  const found = String(prompt).match(/^mode:\s*(\S+)/m)
  return found ? found[1] : null
}
function routeOf(operation, mode) {
  const exact = mode ? `${operation}:${mode}` : operation
  if (Object.hasOwn(config.responses, exact)) return exact
  return operation
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

async function bundled(args) {
  const source = await readFile(config.bundle_path, "utf8")
  const body = source.replace(/^export\s+const\s+meta\s*=/m, "const meta =")
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
  return new AsyncFunction("agent", "parallel", "phase", "log", "args", body)(
    agent, primitives.parallel, primitives.phase, primitives.log, args
  )
}

let result
if (config.entry) {
  result = config.bundle_path
    ? await bundled(config.args)
    : await runWorkflow(primitives, config.args)
} else if (config.requests) {
  result = await Promise.all(config.requests.map(request =>
    processTalk(runtime, request.slug, request.meta)
  ))
} else {
  result = await processTalk(runtime, config.slug, config.meta)
}
const unused = Object.fromEntries(
  Object.entries(config.responses)
    .map(([key, rows]) => [key, rows.length - (indexes.get(key) || 0)])
    .filter(([, value]) => value !== 0)
)
process.stdout.write(JSON.stringify({result, trace, phases, unused}))
"""


def paths(slug: str) -> dict[str, str]:
    return {
        "media": f"sources/{slug}.wav",
        "processing": f"processing/talks/{slug}",
        "manifest": f"processing/talks/{slug}/manifest.json",
        "talk_dir": f"vault/talks/{slug}",
        "transcript": f"vault/talks/{slug}/transcript.md",
        "subtitle": f"vault/talks/{slug}/recording.srt",
        "canonical": f"vault/talks/{slug}/talk.md",
    }


def meta(slug: str, **overrides: Any) -> dict[str, Any]:
    value = {
        "title": "A Strict Talk",
        "date": "2026-07-30",
        "media": paths(slug)["media"],
        "engines": list(ENGINES),
        "lang": "auto",
        "prepare_media": False,
    }
    value.update(overrides)
    return value


def artifact_rows(slug: str, *, canonical: bool = False) -> list[dict[str, Any]]:
    p = paths(slug)
    rows = [
        {
            "role": "transcript",
            "path": p["transcript"],
            "sha256": SHA["transcript"],
            "size": 1200,
        },
        {
            "role": "subtitle",
            "path": p["subtitle"],
            "sha256": SHA["subtitle"],
            "size": 900,
        },
    ]
    for engine in ENGINES:
        rows.append(
            {
                "role": "engine_transcript",
                "path": f"{p['processing']}/transcript.{engine}.srt",
                "sha256": SHA[engine],
                "size": 700,
            }
        )
    if canonical:
        rows.append(
            {
                "role": "canonical",
                "path": p["canonical"],
                "sha256": SHA["canonical"],
                "size": 1400,
            }
        )
    return rows


def observe(slug: str, *, reconciled: bool = False) -> dict[str, Any]:
    p = paths(slug)
    return {
        "schema_version": "quasi.operation.talk.observe.receipt/0.1",
        "key": "talk.observe",
        "effect": "readonly",
        "status": "succeeded",
        "attempt": 1,
        "material_key": f"talk:{slug}",
        "slug": slug,
        "input_path": p["media"],
        "output_dir": p["processing"],
        "manifest_path": p["manifest"],
        "manifest_exists": reconciled,
        "request_fingerprint": SHA["manifest"] if reconciled else None,
        "source_sha256": SHA["source"],
        "source_size": 64000,
        "prepared_path": None,
        "prepared_sha256": None,
        "transcript_path": p["transcript"] if reconciled else None,
        "subtitle_path": p["subtitle"] if reconciled else None,
        "talk_path": p["canonical"],
        "talk_exists": reconciled,
        "talk_sha256": SHA["canonical"] if reconciled else None,
        "classification": "live" if reconciled else None,
        "artifacts": artifact_rows(slug, canonical=True) if reconciled else [],
        "failure": None,
    }


def transcribe(
    slug: str,
    *,
    disposition: str = "created",
    input_path: str | None = None,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    p = paths(slug)
    return {
        "schema_version": "quasi.operation.talk.transcribe.receipt/0.1",
        "key": "talk.transcribe",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "material_key": f"talk:{slug}",
        "slug": slug,
        "input_path": input_path or p["media"],
        "output_dir": p["processing"],
        "talk_dir": p["talk_dir"],
        "manifest_path": p["manifest"],
        "manifest_exists": True,
        "manifest_fingerprint": SHA["manifest"],
        "request_fingerprint": SHA["manifest"],
        "source_sha256": source_sha256 or SHA["source"],
        "lang": "auto",
        "title": "A Strict Talk",
        "engines": list(ENGINES),
        "primary_engine": "soniox",
        "transcript_path": p["transcript"],
        "subtitle_path": p["subtitle"],
        "per_engine": [
            {
                "name": engine,
                "status": "succeeded",
                "segments": 10,
                "path": f"{p['processing']}/transcript.{engine}.srt",
                "sha256": SHA[engine],
            }
            for engine in ENGINES
        ],
        "artifacts": artifact_rows(slug),
        "disposition": disposition,
        "previous_manifest_preserved": False,
        "failure": None,
    }


def prepare(slug: str, action: str = "create") -> dict[str, Any]:
    p = paths(slug)
    return {
        "schema_version": "quasi.operation.talk.prepare-media.receipt/0.1",
        "key": "talk.prepare-media",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "material_key": f"talk:{slug}",
        "input_path": p["media"],
        "output_path": f"{p['talk_dir']}/recording.mp4",
        "artifact_roles": ["prepared_media"],
        "input_sha256": SHA["source"],
        "output_sha256": SHA["prepared"],
        "size": 32000,
        "action": action,
        "failure": None,
    }


def classify(slug: str, signal: str = "live") -> dict[str, Any]:
    return {
        "schema_version": "quasi.operation.talk.classify.receipt/0.1",
        "key": "talk.classify",
        "effect": "readonly",
        "status": "succeeded",
        "attempt": 1,
        "material_key": f"talk:{slug}",
        "input_path": paths(slug)["transcript"],
        "input_sha256": SHA["transcript"],
        "signal": signal,
        "machine_signals": {
            "total": 12 if signal != "empty" else 0,
            "uniq_ratio": 0.9 if signal == "live" else 0.0,
            "chars": 1500 if signal == "live" else 0,
            "spam_hits": 0,
            "blank_dominant": signal == "dead",
            "reason": "typed deterministic classification",
        },
        "failure": None,
    }


def analyse(slug: str, action: str = "create") -> dict[str, Any]:
    rows = artifact_rows(slug)
    inputs = [row for row in rows if row["role"] in {"transcript", "engine_transcript"}]
    return {
        "schema_version": "quasi.operation.talk.analyse.receipt/0.1",
        "key": "talk.analyse",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "input_paths": [row["path"] for row in inputs],
        "input_sha256s": [row["sha256"] for row in inputs],
        "output_path": paths(slug)["canonical"],
        "artifact_roles": ["canonical"],
        "action": action,
        "failure": None,
    }


def silent(slug: str, signal: str, action: str = "create") -> dict[str, Any]:
    return {
        "schema_version": "quasi.operation.talk.render-silent.receipt/0.1",
        "key": "talk.render-silent",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "material_key": f"talk:{slug}",
        "input_path": paths(slug)["transcript"],
        "output_path": paths(slug)["canonical"],
        "artifact_roles": ["canonical"],
        "classification_signal": signal,
        "action": action,
        "output_sha256": SHA["canonical"],
        "size": 1000,
        "failure": None,
    }


def audit(
    slug: str,
    *,
    status: str = "clean",
    path: str | None = None,
    mutated: bool = False,
) -> dict[str, Any]:
    target = paths(slug)["canonical"]
    diagnostic_path = path or target
    escalated = (
        [
            {
                "path": diagnostic_path,
                "kind": "block_kind_mismatch",
                "reason": "exact Talk schema block is wrong",
            }
        ]
        if status == "partial"
        else []
    )
    return {
        "schema_version": "quasi.operation.talk.audit.legacy.receipt/0.1",
        "key": "talk.audit.legacy",
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "target_path": target,
        "remaining_violations": len(escalated),
        "escalated": escalated,
        "mutated_paths": [target] if mutated else [],
    }


def response(value: Any) -> dict[str, Any]:
    return {"result": value}


def happy_responses(slug: str, signal: str = "live") -> dict[str, list[dict[str, Any]]]:
    values: dict[str, list[dict[str, Any]]] = {
        "talk.observe": [response(observe(slug))],
        "talk.transcribe": [response(transcribe(slug))],
        "talk.classify": [response(classify(slug, signal))],
        "talk.audit.legacy": [response(audit(slug))],
    }
    if signal == "live":
        values["talk.analyse:create"] = [response(analyse(slug))]
    else:
        values["talk.render-silent:create"] = [
            response(silent(slug, signal))
        ]
    return values


def run_talk(
    slug: str,
    responses: dict[str, list[dict[str, Any]]],
    *,
    metadata: dict[str, Any] | None = None,
    requests: list[dict[str, Any]] | None = None,
    entry: bool = False,
    bundle: bool = False,
    allow_unused: bool = False,
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = (
        NODE_HARNESS.replace("__TALK_URI__", json.dumps(TALK_MODULE.as_uri()))
        .replace("__RUNTIME_URI__", json.dumps(RUNTIME_MODULE.as_uri()))
        .replace("__ENTRY_URI__", json.dumps(ENTRY_MODULE.as_uri()))
    )
    config: dict[str, Any] = {
        "slug": slug,
        "meta": metadata or meta(slug),
        "responses": responses,
        "entry": entry,
    }
    if requests is not None:
        config["requests"] = requests
    if entry:
        config["args"] = {
            "kind": "talk",
            "slug": slug,
            "meta": metadata or meta(slug),
        }
    if bundle:
        config["bundle_path"] = str(BUNDLE)
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
    return [item["operation"] for item in report["trace"]]


def test_live_talk_runs_typed_sequence_and_completes() -> None:
    slug = "strict-talk-20260730"
    report = run_talk(slug, happy_responses(slug))
    result = report["result"]
    assert result["status"] == "ok"
    assert result["material_receipt"]["status"] == "complete"
    assert result["material_receipt"]["stage"] == "audit"
    assert operations(report) == [
        "talk.observe",
        "talk.transcribe",
        "talk.classify",
        "talk.analyse",
        "talk.audit.legacy",
    ]
    assert [row["phase"] for row in report["trace"]] == [
        "Recall",
        "Prepare",
        "Prepare",
        "Analyse",
        "Audit",
    ]
    analyse_call = report["trace"][3]
    assert analyse_call["agent_type"] == "quasi:analyse-agent"
    request = analyse_call["request"]
    assert "prompt_pack" not in request
    assert request["artifact_contract"]["schema_version"] == (
        "quasi.artifact.talk/0.1"
    )
    assert request["artifact_contract"]["document"]["section_order"][-1] == (
        "时间脉络"
    )
    assert request["frontmatter_seed"]["type"] == "talk"
    assert len(request["evidence_rules"]) == 3
    assert "type" not in request
    assert "topic" not in request
    assert "preamble" not in request
    assert "needs_ocr" not in request


def test_absolute_source_path_is_echoed_across_the_graph_boundary() -> None:
    slug = "absolute-source-talk"
    media_path = f"/Volumes/recordings/{slug}.wav"
    responses = happy_responses(slug)
    responses["talk.observe"][0]["result"]["input_path"] = media_path
    responses["talk.transcribe"][0]["result"]["input_path"] = media_path
    report = run_talk(
        slug,
        responses,
        metadata=meta(slug, media=media_path),
    )
    assert report["result"]["status"] == "ok"
    assert report["trace"][0]["request"]["identity"]["media"] == media_path
    assert report["trace"][1]["request"]["input"]["path"] == media_path


@pytest.mark.parametrize("signal", ["dead", "empty"])
def test_dead_or_empty_uses_silent_producer(signal: str) -> None:
    slug = f"silent-{signal}-20260730"
    report = run_talk(slug, happy_responses(slug, signal))
    assert report["result"]["status"] == "ok"
    assert "talk.analyse" not in operations(report)
    assert operations(report)[-2:] == [
        "talk.render-silent",
        "talk.audit.legacy",
    ]


def test_reconcile_skips_transcribe_and_existing_producer() -> None:
    slug = "reconcile-talk-20260730"
    responses = {
        "talk.observe": [response(observe(slug, reconciled=True))],
        "talk.classify": [response(classify(slug))],
        "talk.audit.legacy": [response(audit(slug))],
    }
    report = run_talk(slug, responses)
    assert report["result"]["material_receipt"]["disposition"] == "reused"
    assert operations(report) == [
        "talk.observe",
        "talk.classify",
        "talk.audit.legacy",
    ]


def test_changed_fingerprint_replaces_transcript_and_refreshes_canonical() -> None:
    slug = "replace-transcript-talk"
    stale = observe(slug)
    stale.update(
        {
            "manifest_exists": True,
            "transcript_path": paths(slug)["transcript"],
            "subtitle_path": paths(slug)["subtitle"],
            "talk_exists": True,
            "talk_sha256": SHA["canonical"],
        }
    )
    responses = {
        "talk.observe": [response(stale)],
        "talk.transcribe": [
            response(transcribe(slug, disposition="replaced"))
        ],
        "talk.classify": [response(classify(slug))],
        "talk.analyse:repair": [
            response(analyse(slug, action="repair"))
        ],
        "talk.audit.legacy": [response(audit(slug))],
    }
    report = run_talk(slug, responses)
    assert report["result"]["status"] == "ok"
    assert report["result"]["material_receipt"]["disposition"] == "repaired"
    assert operations(report) == [
        "talk.observe",
        "talk.transcribe",
        "talk.classify",
        "talk.analyse",
        "talk.audit.legacy",
    ]
    assert report["trace"][3]["mode"] == "repair"


def test_created_transcript_refreshes_an_existing_stale_canonical() -> None:
    slug = "created-over-stale-talk"
    stale = observe(slug)
    stale.update(
        {
            "manifest_exists": True,
            "transcript_path": paths(slug)["transcript"],
            "subtitle_path": paths(slug)["subtitle"],
            "talk_exists": True,
            "talk_sha256": SHA["canonical"],
        }
    )
    responses = {
        "talk.observe": [response(stale)],
        "talk.transcribe": [
            response(transcribe(slug, disposition="created"))
        ],
        "talk.classify": [response(classify(slug))],
        "talk.analyse:repair": [
            response(analyse(slug, action="repair"))
        ],
        "talk.audit.legacy": [response(audit(slug))],
    }
    report = run_talk(slug, responses)
    assert report["result"]["material_receipt"]["disposition"] == "repaired"
    assert report["trace"][3]["mode"] == "repair"


def test_prepare_media_sha_is_the_exact_transcription_source() -> None:
    slug = "prepared-video-talk"
    p = paths(slug)
    media_path = f"sources/{slug}.mov"
    prepared_path = f"{p['talk_dir']}/recording.mp4"
    responses = {
        "talk.observe": [response(observe(slug))],
        "talk.prepare-media": [response(prepare(slug))],
        "talk.transcribe": [
            response(
                transcribe(
                    slug,
                    input_path=prepared_path,
                    source_sha256=SHA["prepared"],
                )
            )
        ],
        "talk.classify": [response(classify(slug))],
        "talk.analyse:create": [response(analyse(slug))],
        "talk.audit.legacy": [response(audit(slug))],
    }
    responses["talk.observe"][0]["result"]["input_path"] = media_path
    responses["talk.prepare-media"][0]["result"]["input_path"] = media_path
    report = run_talk(
        slug,
        responses,
        metadata=meta(
            slug,
            media=media_path,
            prepare_media=True,
        ),
    )
    assert report["result"]["status"] == "ok"
    assert operations(report)[:3] == [
        "talk.observe",
        "talk.prepare-media",
        "talk.transcribe",
    ]

    mismatch = json.loads(json.dumps(responses))
    mismatch["talk.transcribe"][0]["result"]["source_sha256"] = SHA["source"]
    report = run_talk(
        slug,
        mismatch,
        metadata=meta(
            slug,
            media=media_path,
            prepare_media=True,
        ),
        allow_unused=True,
    )
    assert report["result"]["status"] == "blocked"
    assert report["result"]["material_receipt"]["stage"] == "transcribe"


def test_committed_transcription_failure_is_known_and_not_replayed() -> None:
    slug = "all-engines-empty-talk"
    failed = transcribe(slug)
    failed.update(
        {
            "status": "failed",
            "primary_engine": None,
            "transcript_path": None,
            "subtitle_path": None,
            "artifacts": [],
            "disposition": None,
            "per_engine": [
                {
                    "name": engine,
                    "status": "empty",
                    "segments": 0,
                    "path": None,
                    "sha256": None,
                }
                for engine in ENGINES
            ],
            "failure": {
                "code": "all_engines_empty",
                "operation_key": "talk.transcribe",
                "outcome": "known",
                "retryable": False,
                "message": "all engines returned empty",
            },
        }
    )
    report = run_talk(
        slug,
        {
            "talk.observe": [response(observe(slug))],
            "talk.transcribe": [response(failed)],
        },
    )
    assert report["result"]["status"] == "transcribe_failed"
    receipt = report["result"]["material_receipt"]
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "all_engines_empty"
    assert operations(report).count("talk.transcribe") == 1


@pytest.mark.parametrize(
    ("operation", "signal"),
    [
        ("talk.transcribe", "live"),
        ("talk.analyse:create", "live"),
        ("talk.render-silent:create", "dead"),
        ("talk.audit.legacy", "live"),
    ],
)
def test_unknown_writer_is_called_once_and_blocks(
    operation: str, signal: str
) -> None:
    slug = f"unknown-{operation.split('.')[1].replace(':', '-')}"
    responses = happy_responses(slug, signal)
    responses[operation] = [response(None)]
    report = run_talk(slug, responses, allow_unused=True)
    assert report["result"]["status"] == "blocked"
    receipt = report["result"]["material_receipt"]
    assert receipt["status"] == "blocked"
    assert receipt["resume"] == {"operation_key": "talk.reconcile"}
    routed = [row for row in report["trace"] if row["route"] == operation]
    assert len(routed) == 1


def test_classification_must_be_typed_and_exact() -> None:
    slug = "bad-classification"
    responses = happy_responses(slug)
    bad = classify(slug)
    bad["signal"] = "maybe"
    responses["talk.classify"] = [response(bad)]
    del responses["talk.analyse:create"]
    del responses["talk.audit.legacy"]
    report = run_talk(slug, responses)
    assert report["result"]["status"] == "transcribe_failed"
    assert report["result"]["material_receipt"]["stage"] == "classify"


def test_exact_audit_owner_routes_one_repair_then_reaudit() -> None:
    slug = "repair-talk"
    responses = happy_responses(slug)
    responses["talk.audit.legacy"] = [
        response(audit(slug, status="partial")),
        response(audit(slug)),
    ]
    responses["talk.analyse:repair"] = [
        response(analyse(slug, action="repair"))
    ]
    report = run_talk(slug, responses)
    assert report["result"]["material_receipt"]["disposition"] == "repaired"
    assert operations(report)[-3:] == [
        "talk.audit.legacy",
        "talk.analyse",
        "talk.audit.legacy",
    ]


def test_foreign_audit_path_never_invokes_repair() -> None:
    slug = "foreign-audit-talk"
    responses = happy_responses(slug)
    responses["talk.audit.legacy"] = [
        response(
            audit(
                slug,
                status="partial",
                path="vault/talks/another/talk.md",
            )
        )
    ]
    report = run_talk(slug, responses)
    assert report["result"]["status"] == "audit_escalated"
    assert (
        report["result"]["material_receipt"]["failure"]["code"]
        == "talk.repair_owner_unknown"
    )
    assert operations(report).count("talk.analyse") == 1


def test_same_runtime_coalesces_identical_and_rejects_conflict() -> None:
    slug = "coalesced-talk"
    requests = [
        {"slug": slug, "meta": meta(slug)},
        {"slug": slug, "meta": meta(slug)},
    ]
    report = run_talk(
        slug,
        happy_responses(slug),
        requests=requests,
    )
    assert [row["status"] for row in report["result"]] == ["ok", "ok"]
    assert operations(report).count("talk.transcribe") == 1

    conflict = run_talk(
        slug,
        happy_responses(slug),
        requests=[
            {"slug": slug, "meta": meta(slug)},
            {
                "slug": slug,
                "meta": meta(slug, title="Conflicting identity"),
            },
        ],
    )
    assert sorted(row["status"] for row in conflict["result"]) == [
        "blocked",
        "ok",
    ]
    assert operations(conflict).count("talk.transcribe") == 1


def test_source_entry_routes_talk() -> None:
    slug = "source-entry-talk"
    report = run_talk(
        slug,
        happy_responses(slug),
        entry=True,
    )
    assert report["result"]["status"] == "ok"
    assert report["phases"] == ["Recall"]


@pytest.mark.parametrize("slug", ["中文讲座-20260730", "Uppercase-talk", "../escape"])
def test_noncanonical_slug_is_rejected_before_any_agent(slug: str) -> None:
    report = run_talk(slug, {})
    assert report["result"]["status"] == "blocked"
    assert report["result"]["material_receipt"]["stage"] == "identity"
    assert (
        report["result"]["material_receipt"]["failure"]["code"]
        == "talk.identity_invalid"
    )
    assert report["trace"] == []


def test_generated_bundle_routes_talk_after_coordinator_rebuild() -> None:
    if "talk.observe" not in BUNDLE.read_text(encoding="utf-8"):
        pytest.skip("coordinator-owned generated bundle has not been rebuilt")
    slug = "bundle-entry-talk"
    report = run_talk(
        slug,
        happy_responses(slug),
        entry=True,
        bundle=True,
    )
    assert report["result"]["status"] == "ok"

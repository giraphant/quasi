"""Mock contracts for the strict Translate derivative loop.

The tests execute source modules with a scripted ``agent`` primitive. They are
not Claude Workflow end-to-end tests and never call a translation backend.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
TRANSLATION_MODULE = (
    ROOT / "scripts/workflows" / "derivatives" / "translation.mjs"
)
RUNTIME_MODULE = ROOT / "scripts/workflows" / "runtime.mjs"
ENTRY_MODULE = ROOT / "scripts/workflows" / "process-material.entry.mjs"
BUNDLE = ROOT / "workflows" / "process-material.mjs"
FIXTURE = ROOT / "tests" / "fixtures" / "make_synthetic_translation_pdf.py"
SHA = {
    "source": "a" * 64,
    "recovery": "b" * 64,
    "output": "c" * 64,
    "manifest": "d" * 64,
    "fingerprint": "e" * 64,
    "recovery_fingerprint": "f" * 64,
}


NODE_HARNESS = r"""
import { processTranslation } from __TRANSLATION_URI__
import { createRuntime } from __RUNTIME_URI__
import { run as runWorkflow } from __ENTRY_URI__
import { readFile } from "node:fs/promises"

const config = JSON.parse(process.argv[1])
const trace = []
const phases = []
const logs = []
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
function routes(operation, request, label) {
  const values = []
  if (operation === "translation.reconcile" && request?.mode)
    values.push(`${operation}:${request.mode}`)
  if (operation === "translation.run" && request?.attempt)
    values.push(`${operation}:${request.attempt}`)
  if (operation) values.push(operation)
  if (label) values.push(label)
  return values
}
async function agent(prompt, options = {}) {
  const request = parseRequest(prompt)
  const operation = operationOf(prompt, request)
  const candidates = routes(operation, request, options.label || null)
  const route = candidates.find(key => Object.hasOwn(config.responses, key))
    || candidates[0] || options.label || "unknown"
  const occurrence = indexes.get(route) || 0
  indexes.set(route, occurrence + 1)
  trace.push({
    operation, route, occurrence: occurrence + 1,
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
  log: value => logs.push(String(value)),
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
    processTranslation(runtime, request.slug, request.meta)
  ))
} else {
  result = await processTranslation(runtime, config.slug, config.meta)
}
const unused = Object.fromEntries(
  Object.entries(config.responses)
    .map(([key, rows]) => [key, rows.length - (indexes.get(key) || 0)])
    .filter(([, value]) => value !== 0)
)
process.stdout.write(JSON.stringify({result, trace, phases, logs, unused}))
"""


def paths(slug: str, lang: str = "zh-CN") -> dict[str, str]:
    tag = lang.lower()
    return {
        "source": f"sources/{slug}.pdf",
        "paper_ocr": f"processing/papers/{slug}/ocr.pdf",
        "recovery": (
            f"processing/translations/{slug}-{tag}-reocr.pdf"
        ),
        "output": f"processing/translations/{slug}-{tag}.pdf",
        "manifest": (
            f"processing/translations/{slug}-{tag}.manifest.json"
        ),
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


def coverage(
    *,
    signal: str = "pass",
    median: float | None = 0.31,
) -> dict[str, Any]:
    return {
        "signal": signal,
        "median": median,
        "measured_pages": 3,
        "minimum_median": 0.22,
        "weakest": [
            {"page": 1, "ratio": median if median is not None else 0.0}
        ],
        "detail": (
            "Under-translated"
            if signal == "under_translated"
            else "coverage is sufficient"
        ),
    }


def failure(
    code: str,
    operation: str,
    outcome: str = "known",
    message: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "operation_key": operation,
        "outcome": outcome,
        "retryable": False,
        "message": message,
    }


def gate(
    kind: str,
    *,
    fields: list[str] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    candidates_fingerprint: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "missing_fields": fields or [],
        "candidates": candidates or [],
        "candidates_fingerprint": candidates_fingerprint,
    }


def reconcile_reply(
    slug: str,
    *,
    mode: str = "initial",
    signal: str | None = "missing",
    requested_source: str | None = None,
    source_path: str | None = None,
    source_sha: str | None = None,
    backend: str = "pdf2zh",
    request_fingerprint: str | None = None,
    gate_value: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    candidates_fingerprint: str | None = None,
    generation_attempt: int | None = None,
) -> dict[str, Any]:
    p = paths(slug)
    if requested_source is None and signal not in {
        "source_selection",
        None,
    }:
        requested_source = p["source"]
    if source_path is None and signal in {"missing", "reused"}:
        source_path = requested_source
    if source_sha is None and signal in {"missing", "reused"}:
        source_sha = (
            SHA["recovery"]
            if source_path == p["recovery"]
            else SHA["source"]
        )
    if request_fingerprint is None and signal in {"missing", "reused"}:
        request_fingerprint = SHA["fingerprint"]
    is_reused = signal == "reused"
    if generation_attempt is None:
        if signal in {
            "configuration_required",
            "source_selection",
            None,
        }:
            generation_attempt = 0
        elif mode == "recovery":
            generation_attempt = 2
        elif (
            is_reused
            and source_path == p["recovery"]
        ):
            generation_attempt = 2
        else:
            generation_attempt = 1
    status = "succeeded"
    receipt_failure = None
    if signal == "configuration_required":
        status = "blocked"
        gate_value = gate(
            "configuration_required",
            fields=[
                "translate_base_url",
                "translate_api_key",
                "translate_model",
            ],
        )
        receipt_failure = failure(
            "translation.configuration_required",
            "translation.reconcile",
        )
    elif signal == "source_selection":
        status = "blocked"
        requested_source = None
        source_path = None
        source_sha = None
        request_fingerprint = None
        candidates = candidates or [
            {
                "path": p["source"],
                "sha256": "1" * 64,
                "size": 5100,
                "pages": 3,
            },
            {
                "path": p["paper_ocr"],
                "sha256": "2" * 64,
                "size": 5200,
                "pages": 3,
            },
        ]
        gate_value = gate(
            "source_selection",
            candidates=candidates,
            candidates_fingerprint="3" * 64,
        )
        receipt_failure = failure(
            "translation.source_selection_required",
            "translation.reconcile",
        )
    elif signal is None:
        status = "failed"
        requested_source = None
        source_path = None
        source_sha = None
        request_fingerprint = None
        receipt_failure = failure(
            "translation.source_missing",
            "translation.reconcile",
        )
    return {
        "schema_version": (
            "quasi.operation.translation.reconcile.receipt/0.1"
        ),
        "key": "translation.reconcile",
        "effect": "readonly",
        "status": status,
        "attempt": 1,
        "generation_attempt": generation_attempt,
        "derivative_key": f"translation:paper:{slug}:zh-CN",
        "slug": slug,
        "mode": mode,
        "requested_source": requested_source,
        "source_path": source_path,
        "output_path": p["output"],
        "manifest_path": p["manifest"],
        "target_language": "zh-CN",
        "toc_json": None,
        "toc_page_side": "original",
        "backend": backend,
        "signal": signal,
        "request_fingerprint": request_fingerprint,
        "source_sha256": source_sha,
        "source_size": 5200 if source_sha else 0,
        "source_pages": 3 if source_sha else 0,
        "output_sha256": SHA["output"] if is_reused else None,
        "manifest_sha256": SHA["manifest"] if is_reused else None,
        "output_size": 18000 if is_reused else 0,
        "output_pages": 6 if is_reused else 0,
        "toc_entries": 0,
        "coverage": coverage() if is_reused else None,
        "candidates": candidates or [],
        "candidates_fingerprint": (
            candidates_fingerprint
            if candidates_fingerprint is not None
            else "3" * 64
            if signal == "source_selection"
            else None
        ),
        "gate": gate_value,
        "failure": receipt_failure,
    }


def run_reply(
    slug: str,
    *,
    attempt: int = 1,
    status: str = "succeeded",
    code: str | None = None,
    backend: str = "pdf2zh",
    input_path: str | None = None,
    source_sha: str | None = None,
    request_fingerprint: str = SHA["fingerprint"],
) -> dict[str, Any]:
    p = paths(slug)
    input_path = input_path or (
        p["source"] if attempt == 1 else p["recovery"]
    )
    source_sha = source_sha or (
        SHA["source"] if attempt == 1 else SHA["recovery"]
    )
    is_success = status == "succeeded"
    is_under = code == "translation.under_translated"
    is_auth = code == "translation.configuration_required"
    outcome = "unknown" if status == "blocked" and not is_auth else "known"
    return {
        "schema_version": "quasi.operation.translation.run.receipt/0.1",
        "key": "translation.run",
        "effect": "writer",
        "status": status,
        "attempt": attempt,
        "derivative_key": f"translation:paper:{slug}:zh-CN",
        "slug": slug,
        "backend": backend,
        "input_path": input_path,
        "output_path": p["output"],
        "manifest_path": p["manifest"],
        "target_language": "zh-CN",
        "toc_json": None,
        "toc_page_side": "original",
        "request_fingerprint": request_fingerprint,
        "source_sha256": source_sha,
        "output_sha256": SHA["output"] if is_success else None,
        "manifest_sha256": SHA["manifest"] if is_success else None,
        "output_size": 18000 if is_success else 0,
        "source_pages": 3,
        "output_pages": 6 if is_success else 0,
        "toc_entries": 0,
        "coverage": (
            coverage()
            if is_success
            else coverage(
                signal="under_translated",
                median=0.12,
            )
            if is_under
            else None
        ),
        "disposition": "created" if is_success else None,
        "canonical_committed": is_success,
        "previous_manifest_preserved": not is_success,
        "gate": (
            gate(
                "configuration_required",
                fields=[
                    "translate_base_url",
                    "translate_api_key",
                    "translate_model",
                ],
            )
            if is_auth
            else None
        ),
        "failure": (
            None
            if is_success
            else failure(
                code or "translation.backend_failed",
                "translation.run",
                outcome,
            )
        ),
    }


def reocr_reply(
    slug: str,
    *,
    status: str = "ok",
    code: str | None = None,
) -> dict[str, Any]:
    p = paths(slug)
    is_success = status == "ok"
    is_existing = status == "existing"
    return {
        "status": status,
        "input": p["source"],
        "output": p["recovery"],
        "exit": 0 if is_success or is_existing else 1,
        "exists": is_success or is_existing,
        "size": 9000 if is_success or is_existing else 0,
        "failure": (
            None
            if is_success or is_existing
            else {
                "code": code or "ocr_failed",
                "message": "layout OCR failed",
            }
        ),
    }


def step(result: Any = None, *, throw: str | None = None) -> dict[str, Any]:
    return {"result": result, **({"throw": throw} if throw else {})}


def happy_responses(slug: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "translation.reconcile:initial": [
            step(reconcile_reply(slug))
        ],
        "translation.run:1": [step(run_reply(slug))],
        "translation.reconcile:final": [
            step(reconcile_reply(slug, mode="final", signal="reused"))
        ],
    }


def decision_responses(
    slug: str,
    decision: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "translation.reconcile:initial": [
            step(
                reconcile_reply(
                    slug,
                    requested_source=decision["path"],
                    source_path=decision["path"],
                    source_sha=decision["sha256"],
                    candidates_fingerprint=decision[
                        "candidates_fingerprint"
                    ],
                )
            )
        ],
        "translation.run:1": [
            step(
                run_reply(
                    slug,
                    input_path=decision["path"],
                    source_sha=decision["sha256"],
                )
            )
        ],
        "translation.reconcile:final": [
            step(
                reconcile_reply(
                    slug,
                    mode="final",
                    signal="reused",
                    requested_source=decision["path"],
                    source_path=decision["path"],
                    source_sha=decision["sha256"],
                )
            )
        ],
    }


def run_harness(config: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable")
    script = (
        NODE_HARNESS.replace(
            "__TRANSLATION_URI__", json.dumps(TRANSLATION_MODULE.as_uri())
        )
        .replace("__RUNTIME_URI__", json.dumps(RUNTIME_MODULE.as_uri()))
        .replace("__ENTRY_URI__", json.dumps(ENTRY_MODULE.as_uri()))
    )
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, json.dumps(config)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["unused"] == {}, report
    return report


def run_translation(
    slug: str,
    responses: dict[str, list[dict[str, Any]]],
    *,
    translation_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return run_harness(
        {
            "slug": slug,
            "meta": translation_meta or meta(slug),
            "responses": responses,
        }
    )


def operations(report: dict[str, Any]) -> list[str]:
    return [row["operation"] for row in report["trace"]]


def test_fresh_translation_uses_exact_typed_sequence() -> None:
    slug = "translation-fresh"
    report = run_translation(slug, happy_responses(slug))
    assert operations(report) == [
        "translation.reconcile",
        "translation.run",
        "translation.reconcile",
    ]
    assert report["phases"] == ["Recall"]
    assert [row["phase"] for row in report["trace"]] == [
        "Recall",
        "Prepare",
        "Audit",
    ]
    result = report["result"]
    assert result["status"] == "success"
    assert result["final_pdf"] == paths(slug)["output"]
    receipt = result["translation_receipt"]
    assert receipt["schema_version"] == (
        "quasi.derivative.translation.receipt/0.1"
    )
    assert receipt["status"] == "complete"
    assert receipt["disposition"] == "created"
    assert receipt["source"] == {
        "path": paths(slug)["source"],
        "sha256": SHA["source"],
        "size": 5200,
        "pages": 3,
    }
    assert receipt["validation"]["status"] == "clean"
    assert receipt["validation"]["output_pages"] == 6
    assert [row["role"] for row in receipt["artifacts"]] == [
        "source",
        "translated_pdf",
        "translation_manifest",
    ]
    reconcile_request = report["trace"][0]["request"]
    assert reconcile_request["generation_attempt"] == 1
    assert "--generation-attempt" not in reconcile_request["exact_command"]
    prompt_request = report["trace"][1]["request"]
    assert prompt_request["frozen_backend"] == "pdf2zh"
    assert "--backend" not in prompt_request["exact_command"]
    assert (
        "'quasi-translate' 'run' 'translation-fresh'"
        in prompt_request["exact_command"]
    )


def test_exact_command_posix_quotes_single_quote_in_source_path() -> None:
    slug = "translation-quoted-path"
    source = paths(slug)["source"]
    toc_json = ".quasi/translation-o'connor.json"
    responses = happy_responses(slug)
    for rows in responses.values():
        rows[0]["result"]["toc_json"] = toc_json
    report = run_translation(
        slug,
        responses,
        translation_meta=meta(slug, toc_json=toc_json),
    )
    commands = [
        row["request"]["exact_command"]
        for row in report["trace"]
    ]
    assert all("'\"'\"'" in command for command in commands)
    assert all("--backend" not in command for command in commands)


def test_existing_generation_reconciles_without_writer() -> None:
    slug = "translation-reused"
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug, signal="reused"))
            ]
        },
    )
    assert operations(report) == ["translation.reconcile"]
    assert report["result"]["status"] == "success"
    assert (
        report["result"]["translation_receipt"]["disposition"]
        == "reused"
    )
    assert {
        row["producer"]
        for row in report["result"]["translation_receipt"]["artifacts"]
        if row["role"] != "source"
    } == {"translation.reconcile:reused"}


@pytest.mark.parametrize(
    ("signal", "legacy_status"),
    [
        ("configuration_required", "needs_auth"),
        ("source_selection", "needs_source_selection"),
    ],
)
def test_typed_human_gates_start_no_writer(
    signal: str, legacy_status: str
) -> None:
    slug = f"translation-{signal.replace('_', '-')}"
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(
                    reconcile_reply(
                        slug,
                        signal=signal,
                        requested_source=(
                            None
                            if signal == "source_selection"
                            else paths(slug)["source"]
                        ),
                    )
                )
            ]
        },
        translation_meta=(
            meta(slug, source_file=None)
            if signal == "source_selection"
            else meta(slug)
        ),
    )
    assert operations(report) == ["translation.reconcile"]
    assert report["result"]["status"] == legacy_status
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "blocked"
    assert receipt["gate"]["kind"] == (
        "configuration_required"
        if signal == "configuration_required"
        else "source_selection"
    )
    assert receipt["resume"] == {
        "operation_key": "translation.reconcile"
    }


def test_zero_source_receipt_is_a_known_terminal_failure() -> None:
    slug = "translation-source-missing"
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug, signal=None))
            ]
        },
        translation_meta=meta(slug, source_file=None),
    )
    assert operations(report) == ["translation.reconcile"]
    result = report["result"]
    assert result["status"] == "error"
    receipt = result["translation_receipt"]
    assert receipt["status"] == "failed"
    assert receipt["stage"] == "reconcile"
    assert receipt["source"] is None
    assert receipt["failure"] == failure(
        "translation.source_missing",
        "translation.reconcile",
    )
    assert receipt["resume"] is None


def test_source_decision_is_closed_order_independent_evidence() -> None:
    slug = "translation-source-decision"
    decision = {
        "path": paths(slug)["paper_ocr"],
        "sha256": SHA["source"],
        "candidates_fingerprint": "4" * 64,
    }
    reordered = {
        "candidates_fingerprint": "4" * 64,
        "sha256": SHA["source"],
        "path": decision["path"],
    }
    report = run_harness(
        {
            "requests": [
                {
                    "slug": slug,
                    "meta": meta(
                        slug,
                        source_file=None,
                        source_decision=decision,
                    ),
                },
                {
                    "slug": slug,
                    "meta": meta(
                        slug,
                        source_file=None,
                        source_decision=reordered,
                    ),
                },
            ],
            "responses": decision_responses(slug, decision),
        }
    )
    assert [row["status"] for row in report["result"]] == [
        "success",
        "success",
    ]
    assert operations(report).count("translation.run") == 1
    command = report["trace"][0]["request"]["exact_command"]
    assert "'--decision-path'" in command
    assert "'--decision-sha256'" in command
    assert "'--candidates-fingerprint'" in command


@pytest.mark.parametrize(
    "changed",
    ["source_sha256", "candidates_fingerprint"],
)
def test_source_decision_toctou_or_value_change_blocks_before_writer(
    changed: str,
) -> None:
    slug = f"translation-decision-{changed.replace('_', '-')}"
    decision = {
        "path": paths(slug)["paper_ocr"],
        "sha256": SHA["source"],
        "candidates_fingerprint": "4" * 64,
    }
    observed = reconcile_reply(
        slug,
        requested_source=decision["path"],
        source_path=decision["path"],
        source_sha=decision["sha256"],
        candidates_fingerprint=decision["candidates_fingerprint"],
    )
    observed[changed] = "5" * 64
    report = run_translation(
        slug,
        {"translation.reconcile:initial": [step(observed)]},
        translation_meta=meta(
            slug,
            source_file=None,
            source_decision=decision,
        ),
    )
    assert operations(report) == ["translation.reconcile"]
    assert report["result"]["translation_receipt"]["status"] == "blocked"


@pytest.mark.parametrize(
    "field",
    [
        "toc_json",
        "output_sha256",
        "manifest_sha256",
        "candidates_fingerprint",
    ],
)
def test_reconcile_string_null_sentinel_blocks_before_writer(
    field: str,
) -> None:
    slug = f"translation-string-null-{field.replace('_', '-')}"
    observed = reconcile_reply(slug)
    observed[field] = "null"
    report = run_translation(
        slug,
        {"translation.reconcile:initial": [step(observed)]},
    )
    assert operations(report) == ["translation.reconcile"]
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "blocked"
    assert receipt["stage"] == "reconcile"
    assert receipt["failure"]["code"] == (
        "translation.reconcile_receipt_invalid"
    )


def test_source_decision_rejects_derivative_recovery_before_agent() -> None:
    slug = "translation-decision-role"
    report = run_translation(
        slug,
        {},
        translation_meta=meta(
            slug,
            source_file=None,
            source_decision={
                "path": paths(slug)["recovery"],
                "sha256": SHA["recovery"],
                "candidates_fingerprint": "4" * 64,
            },
        ),
    )
    assert report["trace"] == []
    assert (
        report["result"]["translation_receipt"]["failure"]["code"]
        == "translation.identity_invalid"
    )


@pytest.mark.parametrize(
    "forbidden_path",
    [
        "sources/foreign.pdf",
        "processing/papers/foreign/ocr.pdf",
        (
            "processing/translations/"
            "translation-source-gate-zh-cn-reocr.pdf"
        ),
    ],
)
def test_source_selection_gate_accepts_only_two_exact_source_roles(
    forbidden_path: str,
) -> None:
    slug = "translation-source-gate"
    observed = reconcile_reply(
        slug,
        signal="source_selection",
        requested_source=None,
    )
    observed["candidates"][0]["path"] = forbidden_path
    observed["gate"]["candidates"][0]["path"] = forbidden_path
    report = run_translation(
        slug,
        {"translation.reconcile:initial": [step(observed)]},
        translation_meta=meta(slug, source_file=None),
    )
    assert operations(report) == ["translation.reconcile"]
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "blocked"
    assert receipt["gate"] is None
    assert (
        receipt["failure"]["code"]
        == "translation.reconcile_receipt_invalid"
    )


def test_remote_auth_failure_is_a_typed_gate_without_writer_replay() -> None:
    slug = "translation-run-auth"
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug))
            ],
            "translation.run:1": [
                step(
                    run_reply(
                        slug,
                        status="blocked",
                        code="translation.configuration_required",
                    )
                )
            ],
        },
    )
    assert operations(report).count("translation.run") == 1
    assert report["result"]["status"] == "needs_auth"
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "blocked"
    assert receipt["gate"]["kind"] == "configuration_required"


def test_known_backend_failure_is_terminal_error_without_replay() -> None:
    slug = "translation-known-failure"
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug))
            ],
            "translation.run:1": [
                step(
                    run_reply(
                        slug,
                        status="failed",
                        code="translation.backend_failed",
                    )
                )
            ],
        },
    )
    assert operations(report).count("translation.run") == 1
    assert report["result"]["status"] == "error"
    assert (
        report["result"]["translation_receipt"]["failure"]["outcome"]
        == "known"
    )


def test_undertranslated_gets_exactly_one_layout_ocr_and_second_run() -> None:
    slug = "translation-recovery"
    p = paths(slug)
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug))
            ],
            "translation.run:1": [
                step(
                    run_reply(
                        slug,
                        status="failed",
                        code="translation.under_translated",
                    )
                )
            ],
            "translation.reocr": [step(reocr_reply(slug))],
            "translation.reconcile:recovery": [
                step(
                    reconcile_reply(
                        slug,
                        mode="recovery",
                        requested_source=p["recovery"],
                        source_path=p["recovery"],
                        source_sha=SHA["recovery"],
                        request_fingerprint=SHA["recovery_fingerprint"],
                    )
                )
            ],
            "translation.run:2": [
                step(
                    run_reply(
                        slug,
                        attempt=2,
                        request_fingerprint=SHA["recovery_fingerprint"],
                    )
                )
            ],
            "translation.reconcile:final": [
                step(
                    reconcile_reply(
                        slug,
                        mode="final",
                        signal="reused",
                        requested_source=p["recovery"],
                        source_path=p["recovery"],
                        source_sha=SHA["recovery"],
                        request_fingerprint=SHA["recovery_fingerprint"],
                    )
                )
            ],
        },
    )
    assert operations(report) == [
        "translation.reconcile",
        "translation.run",
        "translation.reocr",
        "translation.reconcile",
        "translation.run",
        "translation.reconcile",
    ]
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "complete"
    assert receipt["disposition"] == "recovered"
    assert receipt["budgets"]["reocr"] == {"limit": 1, "used": 1}
    normalized_ocr = next(
        row
        for row in receipt["operations"]
        if row["key"] == "translation.reocr"
    )
    assert set(normalized_ocr) == {
        "schema_version",
        "key",
        "effect",
        "status",
        "attempt",
        "derivative_key",
        "input_path",
        "output_path",
        "artifact_roles",
        "exit",
        "exists",
        "size",
        "sha256",
        "action",
        "failure",
    }
    assert normalized_ocr["status"] == "succeeded"
    assert normalized_ocr["sha256"] == SHA["recovery"]
    recovery_artifact = next(
        row
        for row in receipt["artifacts"]
        if row["role"] == "recovery_source"
    )
    assert recovery_artifact["sha256"] == SHA["recovery"]
    assert (
        recovery_artifact["producer"]
        == "translation.reocr:reconciled"
    )
    ocr_request = report["trace"][2]["request"]
    assert ocr_request["exact_command"] == (
        "'quasi-extract' 'ocr' "
        f"'{p['source']}' '{p['recovery']}' 'eng' "
        "'--layout' '--no-clobber' '--json'"
    )


def test_second_undertranslated_result_exhausts_recovery() -> None:
    slug = "translation-recovery-exhausted"
    p = paths(slug)
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug))
            ],
            "translation.run:1": [
                step(
                    run_reply(
                        slug,
                        status="failed",
                        code="translation.under_translated",
                    )
                )
            ],
            "translation.reocr": [step(reocr_reply(slug))],
            "translation.reconcile:recovery": [
                step(
                    reconcile_reply(
                        slug,
                        mode="recovery",
                        requested_source=p["recovery"],
                        source_path=p["recovery"],
                        source_sha=SHA["recovery"],
                        request_fingerprint=SHA["recovery_fingerprint"],
                    )
                )
            ],
            "translation.run:2": [
                step(
                    run_reply(
                        slug,
                        attempt=2,
                        status="failed",
                        code="translation.under_translated",
                        request_fingerprint=SHA["recovery_fingerprint"],
                    )
                )
            ],
        },
    )
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == (
        "translation.recovery_exhausted"
    )
    assert operations(report).count("translation.reocr") == 1
    assert operations(report).count("translation.run") == 2
    assert operations(report).count("translation.reconcile") == 2


@pytest.mark.parametrize(
    ("case", "step_value"),
    [
        ("null", step(None)),
        ("cancelled", step({"status": "cancelled"})),
        ("timeout", step({"status": "timeout"})),
        ("throw", step(throw="provider died")),
        ("malformed", step({"status": "succeeded"})),
    ],
)
def test_first_translation_writer_unknown_never_replays(
    case: str, step_value: dict[str, Any]
) -> None:
    slug = f"translation-run-{case}"
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug))
            ],
            "translation.run:1": [step_value],
        },
    )
    assert operations(report).count("translation.run") == 1
    assert operations(report) == [
        "translation.reconcile",
        "translation.run",
    ]
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "blocked"
    assert receipt["failure"]["outcome"] == "unknown"
    assert receipt["resume"] == {
        "operation_key": "translation.reconcile"
    }


@pytest.mark.parametrize(
    ("case", "step_value"),
    [
        ("null", step(None)),
        ("cancelled", step({"status": "cancelled"})),
        ("timeout", step({"status": "timeout"})),
        ("throw", step(throw="provider died")),
        ("malformed", step({"status": "succeeded"})),
    ],
)
def test_reocr_writer_unknown_never_runs_attempt_two(
    case: str, step_value: dict[str, Any]
) -> None:
    slug = f"translation-reocr-{case}"
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug))
            ],
            "translation.run:1": [
                step(
                    run_reply(
                        slug,
                        status="failed",
                        code="translation.under_translated",
                    )
                )
            ],
            "translation.reocr": [step_value],
        },
    )
    assert operations(report).count("translation.reocr") == 1
    assert operations(report).count("translation.run") == 1
    assert report["result"]["translation_receipt"]["status"] == "blocked"


def test_existing_reocr_collision_blocks_without_overwrite_or_run_two() -> None:
    slug = "translation-reocr-collision"
    collision = reocr_reply(
        slug,
        status="existing",
    )
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug))
            ],
            "translation.run:1": [
                step(
                    run_reply(
                        slug,
                        status="failed",
                        code="translation.under_translated",
                    )
                )
            ],
            "translation.reocr": [step(collision)],
        },
    )
    assert operations(report).count("translation.reocr") == 1
    assert operations(report).count("translation.run") == 1
    assert report["result"]["status"] == "blocked"
    assert (
        report["result"]["translation_receipt"]["failure"]["code"]
        == "translation.recovery_source_exists"
    )


def test_known_raw_reocr_failure_is_normalized_without_run_two() -> None:
    slug = "translation-reocr-known-failure"
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug))
            ],
            "translation.run:1": [
                step(
                    run_reply(
                        slug,
                        status="failed",
                        code="translation.under_translated",
                    )
                )
            ],
            "translation.reocr": [
                step(reocr_reply(slug, status="failed"))
            ],
        },
    )
    receipt = report["result"]["translation_receipt"]
    assert operations(report).count("translation.reocr") == 1
    assert operations(report).count("translation.run") == 1
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "translation.reocr_failed"
    normalized = receipt["operations"][-1]
    assert normalized["schema_version"] == (
        "quasi.operation.translation.reocr.receipt/0.1"
    )
    assert normalized["status"] == "failed"
    assert normalized["failure"]["outcome"] == "known"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("backend", "immersive"),
        ("request_fingerprint", "1" * 64),
        ("input_path", "sources/foreign.pdf"),
        ("output_path", "processing/translations/foreign-zh.pdf"),
    ],
)
def test_writer_identity_or_generation_mismatch_blocks(
    field: str, value: str
) -> None:
    slug = f"translation-mismatch-{field.replace('_', '-')}"
    broken = run_reply(slug)
    broken[field] = value
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug))
            ],
            "translation.run:1": [step(broken)],
        },
    )
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "blocked"
    assert receipt["failure"]["code"] == (
        "translation.writer_receipt_mismatch"
    )


def test_final_reconcile_mismatch_blocks_without_writer_replay() -> None:
    slug = "translation-final-mismatch"
    broken = reconcile_reply(slug, mode="final", signal="reused")
    broken["output_sha256"] = "1" * 64
    report = run_translation(
        slug,
        {
            "translation.reconcile:initial": [
                step(reconcile_reply(slug))
            ],
            "translation.run:1": [step(run_reply(slug))],
            "translation.reconcile:final": [step(broken)],
        },
    )
    assert operations(report).count("translation.run") == 1
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "blocked"
    assert receipt["stage"] == "validation"


def test_identical_requests_coalesce_one_pipeline() -> None:
    slug = "translation-coalesced"
    report = run_harness(
        {
            "requests": [
                {"slug": slug, "meta": meta(slug)},
                {"slug": slug, "meta": meta(slug)},
            ],
            "responses": happy_responses(slug),
        }
    )
    assert len(report["result"]) == 2
    assert report["result"][0] == report["result"][1]
    assert operations(report).count("translation.run") == 1


def test_conflicting_same_key_is_blocked_before_second_writer() -> None:
    slug = "translation-conflict"
    report = run_harness(
        {
            "requests": [
                {"slug": slug, "meta": meta(slug)},
                {
                    "slug": slug,
                    "meta": meta(
                        slug,
                        source_file=paths(slug)["recovery"],
                    ),
                },
            ],
            "responses": happy_responses(slug),
        }
    )
    statuses = sorted(
        row["translation_receipt"]["status"]
        for row in report["result"]
    )
    assert statuses == ["blocked", "complete"]
    assert operations(report).count("translation.run") == 1


@pytest.mark.parametrize("role", ["source", "paper_ocr", "recovery"])
def test_requested_source_accepts_only_exact_derived_roles(
    role: str,
) -> None:
    slug = f"translation-source-role-{role.replace('_', '-')}"
    p = paths(slug)
    source_path = p[role]
    source_sha = (
        SHA["recovery"] if role == "recovery" else SHA["source"]
    )
    responses = {
        "translation.reconcile:initial": [
            step(
                reconcile_reply(
                    slug,
                    requested_source=source_path,
                    source_path=source_path,
                    source_sha=source_sha,
                )
            )
        ],
        "translation.run:1": [
            step(
                run_reply(
                    slug,
                    input_path=source_path,
                    source_sha=source_sha,
                )
            )
        ],
        "translation.reconcile:final": [
            step(
                reconcile_reply(
                    slug,
                    mode="final",
                    signal="reused",
                    requested_source=source_path,
                    source_path=source_path,
                    source_sha=source_sha,
                    generation_attempt=1,
                )
            )
        ],
    }
    report = run_translation(
        slug,
        responses,
        translation_meta=meta(slug, source_file=source_path),
    )
    assert report["result"]["translation_receipt"]["status"] == "complete"


@pytest.mark.parametrize(
    "bad_meta",
    [
        {"source_file": "../escape.pdf"},
        {"source_file": "sources/not-a-pdf.txt"},
        {"source_file": "sources/other.pdf"},
        {"source_file": "processing/papers/other/ocr.pdf"},
        {
            "source_file": (
                "processing/translations/"
                "translation-invalid-zh-cn-other.pdf"
            )
        },
        {"target_language": "zh CN"},
        {"toc_json": "../toc.json"},
        {"toc_page_side": "both"},
    ],
)
def test_identity_is_rejected_before_paths_or_agent(
    bad_meta: dict[str, Any]
) -> None:
    slug = "translation-invalid"
    report = run_translation(
        slug,
        {},
        translation_meta=meta(slug, **bad_meta),
    )
    assert report["trace"] == []
    receipt = report["result"]["translation_receipt"]
    assert receipt["status"] == "failed"
    assert receipt["stage"] == "identity"


def test_root_schemas_are_plain_objects_without_top_level_combinators() -> None:
    script = """
import * as operations from "./scripts/workflows/operations/translate.mjs"
const schemas = Object.entries(operations)
  .filter(([name]) => name.endsWith("_SCHEMA"))
  .map(([name, schema]) => ({name, schema}))
for (const {name, schema} of schemas) {
  if (schema.type !== "object") throw new Error(`${name}: root is not object`)
  for (const key of ["oneOf", "allOf", "anyOf", "if", "then"])
    if (Object.hasOwn(schema, key)) throw new Error(`${name}: ${key}`)
}
process.stdout.write(JSON.stringify(schemas.map(({name}) => name)))
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert len(json.loads(proc.stdout)) == 3


def paper_responses(slug: str) -> dict[str, list[dict[str, Any]]]:
    source = paths(slug)["source"]
    normalized = f"processing/papers/{slug}/source.txt"
    canonical = f"vault/papers/{slug}.md"
    values = happy_responses(slug)
    values.update(
        {
            "material.recall": [
                step(
                    {
                        "schema_version": (
                            "quasi.operation.material.recall.receipt/0.2"
                        ),
                        "key": "material.recall",
                        "effect": "readonly",
                        "status": "succeeded",
                        "attempt": 1,
                        "request_key": f"paper:{slug}",
                        "kind": "paper",
                        "requested_slug": slug,
                        "vault_slug": "__none__",
                        "path": "__none__",
                        "match": "none",
                        "failure": None,
                    }
                )
            ],
            "material.search": [
                step(
                    {
                        "schema_version": (
                            "quasi.operation.material.search.receipt/0.1"
                        ),
                        "key": "material.search",
                        "effect": "readonly",
                        "status": "succeeded",
                        "attempt": 1,
                        "request_key": f"paper:{slug}",
                        "kind": "paper",
                        "query": {
                            "slug": slug,
                            "title": "A Paper with a Derivative",
                            "authors": ["Ada Example"],
                            "year": 2026,
                            "doi": "10.1000/translation",
                            "oa_url": None,
                            "url": None,
                            "journal": "Journal of Derivatives",
                        },
                        "picked": {
                            "slug": slug,
                            "title": "A Paper with a Derivative",
                            "authors": ["Ada Example"],
                            "year": 2026,
                            "doi": "10.1000/translation",
                            "oa_url": None,
                            "url": None,
                            "journal": "Journal of Derivatives",
                            "confidence": "high",
                        },
                        "confidence": "high",
                        "sources_hit": ["fixture"],
                        "conflicts": [],
                        "notes": "verified fixture identity",
                        "failure": None,
                    }
                )
            ],
            "material.resolve": [
                step(
                    {
                        "schema_version": (
                            "quasi.operation.material.resolve.receipt/0.2"
                        ),
                        "key": "material.resolve",
                        "effect": "readonly",
                        "status": "succeeded",
                        "attempt": 1,
                        "request_key": f"paper:{slug}",
                        "kind": "paper",
                        "requested_slug": slug,
                        "vault_slug": "__none__",
                        "path": "__none__",
                        "match": "none",
                        "failure": None,
                    }
                )
            ],
            "paper.acquire": [
                step(
                    {
                        "acquired": 1,
                        "failed": 0,
                        "per_item": [
                            {
                                "kind": "paper",
                                "slug": slug,
                                "status": "ok",
                                "disposition": "reused",
                                "identity_verified": True,
                                "attempts": [],
                                "doi": "10.1000/translation",
                                "path": source,
                                "source": "existing",
                            }
                        ],
                    }
                )
            ],
            "document.extract-text": [
                step(
                    {
                        "schema_version": (
                            "quasi.operation.document.extract-text.receipt/0.1"
                        ),
                        "key": "document.extract-text",
                        "effect": "writer",
                        "status": "succeeded",
                        "attempt": 1,
                        "input_path": source,
                        "output_path": normalized,
                        "artifact_roles": ["normalized_text"],
                        "exit": 0,
                        "exists": True,
                        "size": 12000,
                        "chars": 10000,
                        "non_whitespace_chars": 8500,
                        "pages": 3,
                        "text_pages": 3,
                        "failure": None,
                    }
                )
            ],
            "document.assess-readability": [
                step(
                    {
                        "schema_version": (
                            "quasi.operation.document.assess-readability.receipt/0.1"
                        ),
                        "key": "document.assess-readability",
                        "effect": "readonly",
                        "status": "succeeded",
                        "attempt": 1,
                        "input_path": normalized,
                        "artifact_roles": ["normalized_text"],
                        "signal": "readable",
                        "diagnostics": [],
                        "failure": None,
                    }
                )
            ],
            "paper.analyse": [
                step(
                    {
                        "schema_version": (
                            "quasi.operation.paper.analyse.receipt/0.1"
                        ),
                        "key": "paper.analyse",
                        "effect": "writer",
                        "status": "succeeded",
                        "attempt": 1,
                        "input_path": normalized,
                        "output_path": canonical,
                        "artifact_roles": ["canonical"],
                        "action": "create",
                        "failure": None,
                    }
                )
            ],
            "paper.audit": [
                step(
                    {
                        "schema_version": (
                            "quasi.operation.paper.audit.agent-receipt/0.1"
                        ),
                        "key": "paper.audit",
                        "effect": "writer",
                        "status": "clean",
                        "attempt": 1,
                        "target_path": canonical,
                        "remaining_violations": 0,
                        "escalated": [],
                    }
                )
            ],
        }
    )
    return values


def test_paper_optional_translation_keeps_material_receipt_independent() -> None:
    slug = "paper-with-translation"
    args = {
        "kind": "paper",
        "slug": slug,
        "translate": True,
        "meta": {
            "title": "A Paper with a Derivative",
            "authors": ["Ada Example"],
            "year": 2026,
            "journal": "Journal of Derivatives",
            "doi": "10.1000/translation",
        },
    }
    report = run_harness(
        {
            "entry": True,
            "args": args,
            "responses": paper_responses(slug),
        }
    )
    result = report["result"]
    assert result["status"] == "ok"
    assert result["material_receipt"]["status"] == "complete"
    assert result["material_receipt"]["kind"] == "paper"
    assert "translation_receipt" not in result["material_receipt"]
    assert result["translation"]["status"] == "success"
    assert result["translation_receipt"] == (
        result["translation"]["translation_receipt"]
    )
    assert result["translation_receipt"]["status"] == "complete"
    initial = next(
        row
        for row in report["trace"]
        if row["operation"] == "translation.reconcile"
    )
    assert initial["request"]["paths"]["requested_source"] == (
        paths(slug)["source"]
    )


def test_direct_translate_kind_routes_through_source_entry() -> None:
    slug = "translation-direct-entry"
    report = run_harness(
        {
            "entry": True,
            "args": {
                "kind": "translate",
                "slug": slug,
                "meta": meta(slug),
            },
            "responses": happy_responses(slug),
        }
    )
    assert report["result"]["status"] == "success"
    assert report["result"]["translation_receipt"]["status"] == "complete"
    assert report["phases"] == ["Recall"]


def test_source_entry_and_committed_bundle_parity_when_bundle_is_current() -> None:
    check = subprocess.run(
        ["node", "scripts/build-workflows.mjs", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode != 0:
        pytest.skip("coordinator-owned generated bundle is not current yet")
    slug = "translation-bundle-parity"
    args = {"kind": "translate", "slug": slug, "meta": meta(slug)}
    source = run_harness(
        {
            "entry": True,
            "args": args,
            "responses": happy_responses(slug),
        }
    )
    bundled = run_harness(
        {
            "entry": True,
            "bundle_path": str(BUNDLE),
            "args": args,
            "responses": happy_responses(slug),
        }
    )
    assert bundled["result"] == source["result"]
    assert bundled["trace"] == source["trace"]
    assert bundled["phases"] == source["phases"]
    assert bundled["logs"] == source["logs"]


def test_synthetic_fixture_is_deterministic_three_page_text_pdf(
    tmp_path: Path,
) -> None:
    first = tmp_path / "fixture-a.pdf"
    second = tmp_path / "fixture-b.pdf"
    for output in (first, second):
        proc = subprocess.run(
            [
                "python3",
                str(FIXTURE),
                "--output",
                str(output),
                "--slug",
                "translation-fixture",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().startswith(b"%PDF-1.4")
    pdfinfo = shutil.which("pdfinfo")
    pdftotext = shutil.which("pdftotext")
    if not pdfinfo or not pdftotext:
        pytest.skip("Poppler is unavailable")
    info = subprocess.run(
        [pdfinfo, str(first)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "Pages:           3" in info
    text = subprocess.run(
        [pdftotext, "-layout", str(first), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    pages = [page for page in text.split("\f") if page.strip()]
    assert len(pages) == 3
    for sentinel, page in zip(("ALPHA", "BETA", "GAMMA"), pages):
        assert f"{sentinel}_TRANSLATE_E2E" in page
        assert sum(character.isalpha() for character in page) > 200

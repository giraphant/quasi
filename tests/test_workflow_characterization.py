from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PLUGIN_ROOT / "scripts" / "pi-runner.mjs"
WORKFLOW = PLUGIN_ROOT / "workflows" / "process-material.mjs"


NODE_HARNESS = r"""
import { createRunner } from __RUNNER_URI__

const config = JSON.parse(process.argv[1])
const responseIndexes = new Map()
const trace = []
const events = []
const logs = []
const missing = []
let clock = 0

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map(key => [key, canonical(value[key])])
    )
  }
  return value
}

function schemaFingerprint(schema) {
  return schema ? JSON.stringify(canonical(schema)) : null
}

function normalizedPrompt(prompt) {
  return String(prompt).replace(/\r\n/g, "\n").trim()
}

const invokeAgent = async ({ definition, prompt, options }) => {
  const label = options.label || definition.name
  const occurrence = responseIndexes.get(label) || 0
  responseIndexes.set(label, occurrence + 1)
  const id = `${label}#${occurrence + 1}`
  const call = {
    id,
    label,
    occurrence: occurrence + 1,
    phase: options.phase || null,
    agent_type: options.agentType || definition.name,
    schema_fingerprint: schemaFingerprint(options.schema),
    prompt: normalizedPrompt(prompt),
    start: ++clock,
    end: null,
  }
  trace.push(call)
  events.push({ event: "start", id, label, clock: call.start })

  const steps = config.responses[label]
  const step = steps && steps[occurrence]
  if (!step) {
    missing.push(id)
    call.end = ++clock
    events.push({ event: "end", id, label, clock: call.end })
    return null
  }
  if (step.delay_ms)
    await new Promise(resolve => setTimeout(resolve, step.delay_ms))

  call.end = ++clock
  events.push({ event: "end", id, label, clock: call.end })
  return JSON.parse(JSON.stringify(step.result))
}

const runner = createRunner({
  pluginRoot: config.plugin_root,
  projectCwd: config.project_cwd,
  concurrency: config.concurrency || 4,
  timeoutMs: 5000,
  invokeAgent,
  log: message => logs.push(String(message)),
})
const result = await runner.runFile(config.workflow, config.args)
const unused = Object.fromEntries(
  Object.entries(config.responses)
    .map(([label, steps]) => [
      label,
      steps.length - (responseIndexes.get(label) || 0),
    ])
    .filter(([, count]) => count !== 0)
)
process.stdout.write(JSON.stringify({ result, trace, events, logs, missing, unused }))
"""


def reply(result: Any, *, delay_ms: int = 0) -> dict[str, Any]:
    return {"result": result, "delay_ms": delay_ms}


def paper_paths(slug: str) -> dict[str, str]:
    return {
        "source": f"sources/{slug}.pdf",
        "source_text": f"processing/papers/{slug}/source.txt",
        "ocr": f"processing/papers/{slug}/ocr.pdf",
        "ocr_text": f"processing/papers/{slug}/ocr.txt",
        "canonical": f"vault/papers/{slug}.md",
    }


def paper_download_receipt(
    slug: str,
    *,
    status: str = "ok",
    doi: str | None = None,
    source: str = "oa",
    failure_reason: str | None = None,
    attempts: list[dict[str, str | None]] | None = None,
) -> dict[str, Any]:
    succeeded = status == "ok"
    item: dict[str, Any] = {
        "kind": "paper",
        "slug": slug,
        "status": status,
        "disposition": "created" if succeeded else None,
        "identity_verified": succeeded,
        "attempts": attempts or [],
        "doi": doi,
    }
    if succeeded:
        item.update(
            {
                "path": paper_paths(slug)["source"],
                "source": source,
            }
        )
    else:
        item.update(
            {
                "source": source,
                "failure_reason": failure_reason,
            }
        )
    return {
        "acquired": 1 if succeeded else 0,
        "failed": 0 if succeeded else 1,
        "per_item": [item],
    }


def paper_prepare_receipt(
    slug: str,
    *,
    selected_input: str | None = None,
    recovered: bool = False,
) -> dict[str, Any]:
    paths = paper_paths(slug)
    selected = selected_input or paths["source_text"]
    artifacts = [
        {
            "role": "normalized_text",
            "path": selected,
            "exists": True,
            "usable": True,
        }
    ]
    if recovered:
        artifacts.insert(
            0,
            {
                "role": "recovery_source",
                "path": paths["ocr"],
                "exists": True,
                "usable": True,
            },
        )
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "paper.prepare",
        "stage": "Prepare",
        "material_key": f"paper:{slug}",
        "effect": "writer",
        "attempt": 1,
        "source_path": paths["source"],
        "selected_input": selected,
        "artifacts": artifacts,
        "steps": [
            {
                "capability": "quasi-extract",
                "outcome": "created" if not recovered else "repaired",
                "summary": "prepared one readable normalized text",
            }
        ],
        "diagnostics": [],
        "terminal": {"status": "complete", "issue": None},
    }


def paper_analyse_receipt(
    slug: str, input_path: str, *, action: str = "create"
) -> dict[str, Any]:
    return {
        "schema_version": "quasi.operation.paper.analyse.receipt/0.1",
        "key": "paper.analyse",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "input_path": input_path,
        "output_path": paper_paths(slug)["canonical"],
        "artifact_roles": ["canonical"],
        "action": action,
        "failure": None,
    }


def paper_audit_receipt(
    slug: str,
    *,
    status: str = "clean",
    remaining: int = 0,
    escalated: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": (
            "quasi.operation.paper.audit.agent-receipt/0.1"
        ),
        "key": "paper.audit",
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "target_path": paper_paths(slug)["canonical"],
        "remaining_violations": remaining,
        "escalated": escalated or [],
    }


def book_meta(*, format: str = "epub") -> dict[str, Any]:
    return {
        "title": "Legacy Book",
        "authors": ["B. Ook"],
        "year": 2020,
        "publisher": "Legacy Academic Press",
        "category": "monograph",
        "format": format,
    }


def book_year_evidence(
    expected: int = 2020,
    *,
    recommended: int | None = None,
    verdict: str = "MATCH",
) -> dict[str, Any]:
    chosen = expected if recommended is None and verdict == "MATCH" else recommended
    observed = chosen if chosen is not None else expected
    return {
        "slug_year": expected,
        "source_years": {
            "catalog": observed,
            "copyright": observed,
        },
        "pdf_signals": {
            "first_published": observed,
            "copyright_year": observed,
            "original_year": None,
            "other_years": [],
        },
        "recommended_year": chosen,
        "recommendation_reason": "two exact sources agree",
        "verdict": verdict,
    }


def book_download_receipt(
    slug: str,
    *,
    status: str = "ok",
    attempts: list[dict[str, str | None]] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "book",
        "slug": slug,
        "status": status,
        "disposition": "reused" if status == "ok" else None,
        "identity_verified": status in {"ok", "year_mismatch"},
        "format": "epub" if status == "ok" else None,
        "attempts": attempts or [],
    }
    if status == "ok":
        item.update(
            {
                "path": f"sources/{slug}.epub",
                "source": "existing",
                "format": "epub",
                "year_evidence": book_year_evidence(),
            }
        )
    elif status == "year_mismatch":
        item.update(
            {
                "tmp_path": (
                    f".quasi/temp/downloads/{slug}-prior.epub"
                ),
                "year_evidence": book_year_evidence(
                    recommended=2019,
                    verdict="MISMATCH",
                ),
            }
        )
    else:
        item["failure_reason"] = "all acquisition routes failed"
    return {
        "acquired": 1 if status == "ok" else 0,
        "failed": 0 if status == "ok" else 1,
        "per_item": [item],
    }


def book_chapters() -> list[dict[str, Any]]:
    return [
        {
            "slot": slot,
            "title": title,
            "filename": f"{slot}_{title}.txt",
            "slug": chapter_slug,
            "word_count": words,
            "start_page": start,
            "end_page": end,
        }
        for slot, title, chapter_slug, words, start, end in (
            ("01", "First", "first", 1000, 1, 10),
            ("02", "Second", "second", 1200, 11, 20),
            ("03", "Third", "third", 1400, 21, 30),
        )
    ]


def book_prepare_receipt(slug: str) -> dict[str, Any]:
    chapters = book_chapters()
    output_dir = f"processing/chapters/{slug}"
    manifest = f"{output_dir}/manifest.json"
    return {
        "schema_version": "quasi.stage.receipt/0.2",
        "operation": "book.prepare",
        "stage": "Prepare",
        "material_key": f"book:{slug}",
        "effect": "writer",
        "attempt": 1,
        "format": "epub",
        "output_dir": output_dir,
        "selected_source": f"sources/{slug}.epub",
        "normalized_path": None,
        "manifest_path": manifest,
        "manifest_fingerprint": "a" * 64,
        "mode": "epub",
        "disposition": "created",
        "chapter_count": len(chapters),
        "chapters": chapters,
        "artifacts": [
            {
                "role": "chapter_manifest",
                "path": manifest,
                "exists": True,
                "usable": True,
            },
            *[
                {
                    "role": "normalized_chapter",
                    "path": f"{output_dir}/{chapter['filename']}",
                    "exists": True,
                    "usable": True,
                }
                for chapter in chapters
            ],
        ],
        "steps": [
            {
                "capability": "quasi-extract epub",
                "outcome": "created",
                "summary": "prepared and verified three chapters",
            }
        ],
        "diagnostics": [],
        "terminal": {"status": "complete", "issue": None},
    }


def book_analyse_receipt(slug: str, chapter: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "quasi.operation.chapter.analyse.receipt/0.1",
        "key": "chapter.analyse",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "input_path": (
            f"processing/chapters/{slug}/{chapter['filename']}"
        ),
        "output_path": (
            f"vault/books/{slug}/"
            f"ch{chapter['slot']}-{chapter['slug']}.md"
        ),
        "artifact_roles": ["chapter_canonical"],
        "action": "create",
        "write_state": "written",
        "failure": None,
    }


def book_synth_receipt(slug: str) -> dict[str, Any]:
    return {
        "schema_version": "quasi.operation.book.synthesise.receipt/0.1",
        "key": "book.synthesise",
        "effect": "writer",
        "status": "succeeded",
        "attempt": 1,
        "input_paths": [
            f"vault/books/{slug}/ch{chapter['slot']}-{chapter['slug']}.md"
            for chapter in book_chapters()
        ],
        "output_path": f"vault/books/{slug}/00-overview.md",
        "artifact_roles": ["canonical"],
        "action": "create",
        "chapters_analyzed": 3,
        "failure": None,
    }


def book_audit_receipt(slug: str) -> dict[str, Any]:
    return {
        "schema_version": "quasi.operation.book.audit.receipt/0.1",
        "key": "book.audit",
        "effect": "writer",
        "status": "clean",
        "attempt": 1,
        "target_path": f"vault/books/{slug}",
        "remaining_violations": 0,
        "escalated": [],
        "mutated_paths": [],
    }


def material_ingress_responses(
    args: dict[str, Any],
    responses: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    kind = args.get("kind")
    slug = args.get("slug")
    meta = args.get("meta")
    if (
        kind not in {"book", "paper"}
        or not isinstance(slug, str)
        or not isinstance(meta, dict)
    ):
        return {}
    request_key = f"{kind}:{slug}"

    raw_authors = meta.get("authors", meta.get("author", []))
    authors = raw_authors if isinstance(raw_authors, list) else [raw_authors]
    raw_year = meta.get("year")
    year = (
        int(raw_year)
        if isinstance(raw_year, str) and raw_year.isdigit()
        else raw_year
    )
    if kind == "book":
        query = {
            "slug": slug,
            "title": meta.get("title"),
            "authors": authors,
            "year": year,
            "isbn": meta.get("isbn"),
            "publisher": meta.get("publisher"),
            "category": meta.get("category"),
            "format": meta.get("format"),
        }
        picked = {
            "slug": slug,
            "title": meta.get("title"),
            "authors": authors,
            "year": year,
            "isbn": meta.get("isbn"),
            "publisher": meta.get("publisher"),
            "category": meta.get("category"),
            "confidence": "high",
        }
    else:
        acquire = responses.get(f"{slug}:acquire", [])
        acquired_item = (
            acquire[0].get("result", {}).get("per_item", [{}])[0]
            if acquire
            else {}
        )
        query = {
            "slug": slug,
            "title": meta.get("title"),
            "authors": authors,
            "year": year,
            "doi": meta.get("doi"),
            "oa_url": meta.get("oa_url"),
            "url": meta.get("url"),
            "journal": meta.get("journal") or meta.get("venue"),
        }
        picked = {
            "slug": slug,
            "title": meta.get("title"),
            "authors": authors,
            "year": year,
            "doi": meta.get("doi") or acquired_item.get("doi"),
            "oa_url": meta.get("oa_url"),
            "url": meta.get("url"),
            "journal": (
                meta.get("journal")
                or meta.get("venue")
                or "Journal of Examples"
            ),
            "confidence": "high",
        }
    return {
        f"{slug}:search": [
            reply(
                {
                    "schema_version": "quasi.stage.receipt/0.2",
                    "operation": "material.search",
                    "stage": "Search",
                    "material_key": request_key,
                    "effect": "readonly",
                    "attempt": 1,
                    "kind": kind,
                    "identity": picked,
                    "local_owner": {
                        "identity_slug": slug,
                        "vault_slug": None,
                        "path": None,
                        "match": None,
                    },
                    "confidence": "high",
                    "observations": [
                        {
                            "source": "fixture",
                            "query": json.dumps(query, sort_keys=True),
                            "summary": "verified fixture identity",
                        }
                    ],
                    "terminal": {"status": "complete", "issue": None},
                }
            )
        ],
    }


def run_workflow(
    tmp_path: Path,
    *,
    args: dict[str, Any],
    responses: dict[str, list[dict[str, Any]]],
    allow_unused: bool = False,
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = NODE_HARNESS.replace("__RUNNER_URI__", json.dumps(RUNNER.as_uri()))
    ingress = material_ingress_responses(args, responses)
    config = {
        "plugin_root": str(PLUGIN_ROOT),
        "project_cwd": str(tmp_path),
        "workflow": str(WORKFLOW),
        "args": args,
        "responses": {**ingress, **responses},
    }
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, json.dumps(config)],
        cwd=PLUGIN_ROOT,
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


def call(report: dict[str, Any], label: str) -> dict[str, Any]:
    matches = [item for item in report["trace"] if item["label"] == label]
    assert len(matches) == 1, (label, matches)
    return matches[0]


def call_occurrence(
    report: dict[str, Any], label: str, occurrence: int
) -> dict[str, Any]:
    matches = [item for item in report["trace"] if item["label"] == label]
    assert len(matches) >= occurrence, (label, occurrence, matches)
    return matches[occurrence - 1]


def labels(report: dict[str, Any]) -> list[str]:
    return [item["label"] for item in report["trace"]]


def assert_before(
    report: dict[str, Any],
    earlier: str,
    later: str,
    *,
    earlier_event: str = "end",
    later_event: str = "start",
) -> None:
    assert call(report, earlier)[earlier_event] < call(report, later)[later_event]


def overlaps(report: dict[str, Any], left: str, right: str) -> bool:
    a, b = call(report, left), call(report, right)
    return a["start"] < b["end"] and b["start"] < a["end"]


def test_paper_happy_path_uses_stage_board_then_analyse_audit(
    tmp_path: Path,
) -> None:
    slug = "paper-happy"
    paths = paper_paths(slug)
    report = run_workflow(
        tmp_path,
        args={
            "kind": "paper",
            "slug": slug,
            "meta": {
                "title": "A Small Paper",
                "authors": ["Ada Example"],
                "year": 2024,
                "journal": "Journal of Examples",
                "doi": "10.1000/happy",
            },
        },
        responses={
            f"{slug}:acquire": [
                reply(
                    paper_download_receipt(
                        slug,
                        doi="10.1000/happy",
                    )
                )
            ],
            f"{slug}:prepare": [reply(paper_prepare_receipt(slug))],
            f"{slug}:analyse": [
                reply(paper_analyse_receipt(slug, paths["source_text"]))
            ],
            f"{slug}:audit": [
                reply(paper_audit_receipt(slug))
            ],
        },
    )

    assert report["result"]["slug"] == slug
    assert report["result"]["status"] == "ok"
    assert report["result"]["material_receipt"]["status"] == "complete"
    assert labels(report) == [
        f"{slug}:search",
        f"{slug}:acquire",
        f"{slug}:prepare",
        f"{slug}:analyse",
        f"{slug}:audit",
    ]
    assert [item["phase"] for item in report["trace"]] == [
        "Search",
        "Acquire",
        "Prepare",
        "Analyse",
        "Audit",
    ]
    assert all(item["schema_fingerprint"] for item in report["trace"])
    assert (
        f'"path": "{paths["canonical"]}"'
        in call(report, f"{slug}:analyse")["prompt"]
    )
    assert_before(
        report,
        f"{slug}:acquire",
        f"{slug}:prepare",
    )
    assert_before(report, f"{slug}:prepare", f"{slug}:analyse")
    assert_before(report, f"{slug}:analyse", f"{slug}:audit")


def test_paper_prepare_can_recover_ocr_before_analyse(
    tmp_path: Path,
) -> None:
    slug = "paper-scan"
    paths = paper_paths(slug)
    report = run_workflow(
        tmp_path,
        args={
            "kind": "paper",
            "slug": slug,
            "meta": {
                "title": "Scanned Paper",
                "authors": ["S. Can"],
                "year": 1999,
                "journal": "Scan Studies",
                "doi": "10.1000/scan",
            },
        },
        responses={
            f"{slug}:acquire": [
                reply(paper_download_receipt(slug))
            ],
            f"{slug}:prepare": [
                reply(
                    paper_prepare_receipt(
                        slug,
                        selected_input=paths["ocr_text"],
                        recovered=True,
                    )
                )
            ],
            f"{slug}:analyse": [
                reply(paper_analyse_receipt(slug, paths["ocr_text"]))
            ],
            f"{slug}:audit": [
                reply(paper_audit_receipt(slug))
            ],
        },
    )

    assert report["result"]["slug"] == slug
    assert report["result"]["status"] == "ok"
    assert labels(report) == [
        f"{slug}:search",
        f"{slug}:acquire",
        f"{slug}:prepare",
        f"{slug}:analyse",
        f"{slug}:audit",
    ]
    prepare = call(report, f"{slug}:prepare")
    assert prepare["agent_type"] == "quasi:extract-agent"
    assert "quasi-extract ocr INPUT OUTPUT --no-clobber --json" in prepare[
        "prompt"
    ]
    reanalysis = call(report, f"{slug}:analyse")
    assert f'"path": "{paths["ocr_text"]}"' in reanalysis["prompt"]
    assert_before(report, f"{slug}:prepare", f"{slug}:analyse")
    assert_before(report, f"{slug}:analyse", f"{slug}:audit")


def test_paper_download_failure_preserves_actionable_evidence(
    tmp_path: Path,
) -> None:
    slug = "paper-missing"
    attempts = [
        {"source": "oa", "status": "failed", "error": "HTTP 403"},
        {"source": "wayback", "status": "failed", "error": "not archived"},
    ]
    report = run_workflow(
        tmp_path,
        args={
            "kind": "paper",
            "slug": slug,
            "meta": {
                "title": "Unavailable Paper",
                "authors": ["N. O. Access"],
                "year": 2024,
                "journal": "Journal of Missing Papers",
            },
        },
        responses={
            f"{slug}:acquire": [
                reply(
                    paper_download_receipt(
                        slug,
                        status="download_failed",
                        doi="10.1000/missing",
                        source="wayback",
                        failure_reason="all acquisition routes failed",
                        attempts=attempts,
                    )
                )
            ]
        },
    )

    assert report["result"]["slug"] == slug
    assert report["result"]["status"] == "download_failed"
    assert report["result"]["doi"] == "10.1000/missing"
    assert report["result"]["source"] == "wayback"
    assert report["result"]["failure_reason"] == "all acquisition routes failed"
    assert report["result"]["attempts"] == attempts
    assert report["result"]["material_receipt"]["status"] == "failed"
    assert labels(report) == [
        f"{slug}:search",
        f"{slug}:acquire",
    ]
    fingerprint = call(
        report, f"{slug}:acquire"
    )["schema_fingerprint"]
    assert "failure_reason" in fingerprint
    assert "attempts" in fingerprint


def test_paper_audit_escalation_gets_one_repair_then_second_audit(
    tmp_path: Path,
) -> None:
    slug = "paper-repair"
    paths = paper_paths(slug)
    diagnostic = {
        "path": paths["canonical"],
        "kind": "missing_section",
        "reason": "required section missing",
    }
    report = run_workflow(
        tmp_path,
        args={
            "kind": "paper",
            "slug": slug,
            "meta": {
                "title": "Repairable Paper",
                "authors": ["R. Pair"],
                "year": 2020,
                "journal": "Repair Review",
            },
        },
        responses={
            f"{slug}:acquire": [
                reply(paper_download_receipt(slug))
            ],
            f"{slug}:prepare": [reply(paper_prepare_receipt(slug))],
            f"{slug}:analyse": [
                reply(paper_analyse_receipt(slug, paths["source_text"])),
                reply(
                    paper_analyse_receipt(
                        slug,
                        paths["source_text"],
                        action="repair",
                    )
                ),
            ],
            f"{slug}:audit": [
                reply(
                    paper_audit_receipt(
                        slug,
                        status="partial",
                        remaining=1,
                        escalated=[diagnostic],
                    )
                ),
                reply(paper_audit_receipt(slug)),
            ],
        },
    )

    assert report["result"]["slug"] == slug
    assert report["result"]["status"] == "ok"
    assert report["result"]["material_receipt"]["disposition"] == "repaired"
    assert labels(report) == [
        f"{slug}:search",
        f"{slug}:acquire",
        f"{slug}:prepare",
        f"{slug}:analyse",
        f"{slug}:audit",
        f"{slug}:analyse",
        f"{slug}:audit",
    ]
    repair = call_occurrence(report, f"{slug}:analyse", 2)
    assert repair["agent_type"] == "quasi:analyse-agent"
    assert repair["schema_fingerprint"] is not None
    assert '"mode": "repair"' in repair["prompt"]
    assert '"overwrite": true' in repair["prompt"]
    assert "required section missing" in repair["prompt"]
    assert (
        call_occurrence(report, f"{slug}:audit", 1)["end"]
        < repair["start"]
    )
    assert (
        repair["end"]
        < call_occurrence(report, f"{slug}:audit", 2)["start"]
    )


def test_book_download_keeps_legacy_year_status_and_temp_evidence(
    tmp_path: Path,
) -> None:
    slug = "legacy-book-download"
    report = run_workflow(
        tmp_path,
        args={
            "kind": "book",
            "slug": slug,
            "meta": book_meta(),
        },
        responses={
            f"{slug}:acquire": [
                reply(book_download_receipt(slug, status="year_mismatch"))
            ]
        },
    )

    assert report["result"]["slug"] == slug
    assert report["result"]["status"] == "year_mismatch"
    assert report["result"]["year_evidence"] == book_year_evidence(
        recommended=2019,
        verdict="MISMATCH",
    )
    assert report["result"]["tmp_path"] == (
        f".quasi/temp/downloads/{slug}-prior.epub"
    )


def test_book_download_failure_preserves_reason_and_attempts(
    tmp_path: Path,
) -> None:
    slug = "legacy-book-download-failure"
    attempts = [
        {
            "source": "direct",
            "status": "failed",
            "error": "HTTP 404",
        }
    ]
    report = run_workflow(
        tmp_path,
        args={"kind": "book", "slug": slug, "meta": book_meta()},
        responses={
            f"{slug}:acquire": [
                reply(
                    book_download_receipt(
                        slug,
                        status="download_failed",
                        attempts=attempts,
                    )
                )
            ]
        },
    )
    assert report["result"]["status"] == "download_failed"
    assert report["result"]["failure_reason"] == (
        "all acquisition routes failed"
    )
    assert report["result"]["attempts"] == attempts


def test_book_fanout_is_parallel_and_reconciles_before_synthesis(
    tmp_path: Path,
) -> None:
    slug = "book-three-chapters"
    chapters = book_chapters()
    report = run_workflow(
        tmp_path,
        args={
            "kind": "book",
            "slug": slug,
            "meta": book_meta(),
        },
        responses={
            f"{slug}:acquire": [
                reply(book_download_receipt(slug))
            ],
            f"{slug}:prepare": [reply(book_prepare_receipt(slug))],
            f"{slug}:ch01:analyse": [
                reply(
                    book_analyse_receipt(slug, chapters[0]),
                    delay_ms=120,
                )
            ],
            f"{slug}:ch02:analyse": [
                reply(
                    book_analyse_receipt(slug, chapters[1]),
                    delay_ms=40,
                )
            ],
            f"{slug}:ch03:analyse": [
                reply(
                    book_analyse_receipt(slug, chapters[2]),
                    delay_ms=80,
                )
            ],
            f"{slug}:synthesise": [reply(book_synth_receipt(slug))],
            f"{slug}:audit": [reply(book_audit_receipt(slug))],
        },
    )

    assert report["result"]["slug"] == slug
    assert report["result"]["status"] == "ok"
    assert report["result"]["year_warning"] is None
    analyse_labels = {
        f"{slug}:ch01:analyse",
        f"{slug}:ch02:analyse",
        f"{slug}:ch03:analyse",
    }
    assert analyse_labels.issubset(set(labels(report)))
    for left, right in (
        (f"{slug}:ch01:analyse", f"{slug}:ch02:analyse"),
        (f"{slug}:ch01:analyse", f"{slug}:ch03:analyse"),
        (f"{slug}:ch02:analyse", f"{slug}:ch03:analyse"),
    ):
        assert overlaps(report, left, right)
    assert_before(report, f"{slug}:acquire", f"{slug}:prepare")
    for analyse_label in analyse_labels:
        assert_before(report, f"{slug}:prepare", analyse_label)
        assert_before(report, analyse_label, f"{slug}:synthesise")
    assert_before(report, f"{slug}:synthesise", f"{slug}:audit")
    assert (
        call(report, f"{slug}:ch02:analyse")["end"]
        < call(report, f"{slug}:ch03:analyse")["end"]
        < call(report, f"{slug}:ch01:analyse")["end"]
    )


def test_author_deduplicates_two_candidates_resolved_to_one_vault_slug(
    tmp_path: Path,
) -> None:
    name = "ada-example"
    canonical = "example-canonical-book-2020"
    first_slug = "candidate-one-2020"
    second_slug = "candidate-two-2020"
    candidate_base = {
        "kind": "book",
        "title": "The Example",
        "authors": ["Ada Example"],
        "year": 2020,
        "isbn": "9780000000002",
        "publisher": "Example University Press",
        "category": "monograph",
        "confidence": "high",
    }
    candidates = [
        {**candidate_base, "slug": first_slug},
        {**candidate_base, "slug": second_slug},
    ]
    author_output = f"vault/authors/{name}.md"
    author_input = f"vault/books/{canonical}/00-overview.md"
    chapters = book_chapters()
    report = run_workflow(
        tmp_path,
        args={
            "kind": "author",
            "name": name,
            "meta": {
                "full_name": "Ada Example",
                "maxBooks": 2,
                "maxPapers": 0,
            },
        },
        responses={
            f"{name}:discover-books": [
                reply(
                    {
                        "schema_version": (
                            "quasi.operation.author.discover-books.receipt/0.1"
                        ),
                        "key": "author.discover-books",
                        "effect": "readonly",
                        "status": "succeeded",
                        "attempt": 1,
                        "collection_key": f"author:{name}",
                        "kind": "book",
                        "full_name": "Ada Example",
                        "topic": "",
                        "count": 2,
                        "candidates": candidates,
                        "failure": None,
                    },
                    delay_ms=100,
                )
            ],
            f"{name}:resolve-membership": [
                reply(
                    {
                        "schema_version": (
                            "quasi.operation.author.resolve-membership.receipt/0.1"
                        ),
                        "key": "author.resolve-membership",
                        "effect": "readonly",
                        "status": "succeeded",
                        "attempt": 1,
                        "collection_key": f"author:{name}",
                        "output_path": author_output,
                        "output_exists": False,
                        "requests": [
                            {"kind": "book", "slug": first_slug},
                            {"kind": "book", "slug": second_slug},
                        ],
                        "resolved": [
                            {
                                "kind": "book",
                                "requested_slug": first_slug,
                                "vault_slug": canonical,
                                "path": author_input,
                                "match": "isbn",
                            },
                            {
                                "kind": "book",
                                "requested_slug": second_slug,
                                "vault_slug": canonical,
                                "path": author_input,
                                "match": "isbn",
                            },
                        ],
                        "failure": None,
                    }
                )
            ],
            f"{canonical}:acquire": [
                reply(book_download_receipt(canonical))
            ],
            f"{canonical}:prepare": [
                reply(book_prepare_receipt(canonical))
            ],
            **{
                f"{canonical}:ch{chapter['slot']}:analyse": [
                    reply(book_analyse_receipt(canonical, chapter))
                ]
                for chapter in chapters
            },
            f"{canonical}:synthesise": [
                reply(book_synth_receipt(canonical))
            ],
            f"{canonical}:audit": [
                reply(book_audit_receipt(canonical))
            ],
            f"{name}:synthesise": [
                reply(
                    {
                        "schema_version": (
                            "quasi.operation.author.synthesise.receipt/0.1"
                        ),
                        "key": "author.synthesise",
                        "effect": "writer",
                        "status": "succeeded",
                        "attempt": 1,
                        "input_material_keys": [f"book:{canonical}"],
                        "input_paths": [author_input],
                        "output_path": author_output,
                        "artifact_roles": ["canonical"],
                        "action": "create",
                        "materials_analyzed": 1,
                        "failure": None,
                    }
                )
            ],
            f"{name}:audit": [
                reply(
                    {
                        "schema_version": (
                            "quasi.operation.author.audit.legacy.receipt/0.1"
                        ),
                        "key": "author.audit.legacy",
                        "effect": "writer",
                        "status": "clean",
                        "attempt": 1,
                        "target_path": author_output,
                        "remaining_violations": 0,
                        "escalated": [],
                        "mutated_paths": [],
                    }
                )
            ],
        },
        allow_unused=True,
    )

    result = report["result"]
    assert result["status"] == "ok", report
    assert result["books"] == 1
    assert result["papers"] == 0
    assert result["book_slugs"] == [canonical]
    assert result["book_failures"] == 0
    assert result["paper_failures"] == 0
    assert result["collection_receipt"]["status"] == "complete"
    assert labels(report).count(f"{canonical}:acquire") == 1
    synth_prompt = call(
        report, f"{name}:synthesise"
    )["prompt"]
    assert synth_prompt.count(author_input) >= 1
    assert_before(
        report,
        f"{name}:resolve-membership",
        f"{canonical}:acquire",
    )
    assert_before(
        report,
        f"{canonical}:audit",
        f"{name}:synthesise",
    )
    assert_before(
        report,
        f"{name}:synthesise",
        f"{name}:audit",
    )


def test_topic_processes_one_material_and_one_card_on_parallel_tracks(
    tmp_path: Path,
) -> None:
    topic = "mixed-topic"
    paper = "mixed-topic-paper"
    card = "mixed-topic-card"
    subq = "sq-one"
    card_path = f"vault/topics/{topic}/cards/{card}.md"
    paper_artifacts = paper_paths(paper)
    first_steer = {
        "outline_written": True,
        "saturated": False,
        "subquestions": [
            {
                "id": subq,
                "question": "What connects the two evidence tracks?",
                "coverage": "thin",
                "items": [],
                "cards": [],
                "dossier": False,
            }
        ],
        "dirty": [],
        "candidates": [
            {
                "kind": "paper",
                "slug": paper,
                "title": "Mixed Evidence",
                "authors": ["M. Ix"],
                "year": 2021,
                "journal": "Mixed Evidence Review",
                "doi": "10.1000/mixed",
                "subq": subq,
                "role": "case",
            }
        ],
        "web_tasks": [
            {
                "subq": subq,
                "query": "primary source for mixed evidence",
                "note": "official source",
                "card_slug": card,
            }
        ],
        "suggested_queries": [],
    }
    closing_steer = {
        "outline_written": True,
        "saturated": True,
        "subquestions": [
            {
                "id": subq,
                "question": "What connects the two evidence tracks?",
                "coverage": "adequate",
                "items": [
                    {
                        "kind": "paper",
                        "slug": paper,
                        "role": "case",
                    }
                ],
                "cards": [card],
                "dossier": False,
            }
        ],
        "dirty": [subq],
        "candidates": [],
        "web_tasks": [],
        "suggested_queries": [],
    }
    topic_audits = {
        f"{topic}:audit:{Path(path).name}": [
            reply({"status": "clean", "escalated": [],}, delay_ms=15)
        ]
        for path in (
            f"vault/topics/{topic}/00-overview.md",
            f"vault/topics/{topic}/01-resources.md",
            f"vault/topics/{topic}/02-outline.md",
            card_path,
        )
    }
    responses = {
        f"{topic}:recall": [reply({"items": []}, delay_ms=30)],
        f"{topic}:steer:r0": [reply(first_steer, delay_ms=30)],
        f"{topic}:webcard:{card}": [
            reply(
                {
                    "status": "ok",
                    "card_path": card_path,
                    "subq": subq,
                    "title": "Primary source",
                    "objects": 1,
                    "sources": 1,
                    "evidence": "confirmed",
                },
                delay_ms=180,
            )
        ],
        f"{topic}:probe-done:r1": [reply({"resolved": []}, delay_ms=10)],
        f"{paper}:acquire": [
            reply(
                paper_download_receipt(
                    paper,
                    doi="10.1000/mixed",
                ),
                delay_ms=35,
            )
        ],
        f"{paper}:prepare": [
            reply(paper_prepare_receipt(paper), delay_ms=40)
        ],
        f"{paper}:analyse": [
            reply(
                paper_analyse_receipt(paper, paper_artifacts["source_text"]),
                delay_ms=35,
            )
        ],
        f"{paper}:audit": [
            reply(
                paper_audit_receipt(paper),
                delay_ms=35,
            )
        ],
        f"{topic}:probe-cards:r1": [reply({"existing": [card]})],
        f"{topic}:steer:r1": [reply(closing_steer)],
        f"{topic}:synthesise-topic": [reply({"status": "success"})],
        **topic_audits,
    }
    report = run_workflow(
        tmp_path,
        args={
            "kind": "topic",
            "slug": topic,
            "meta": {
                "desc": "A topic requiring academic and primary evidence",
                "maxRounds": 1,
                "maxPerRound": 1,
                "maxCardsPerRound": 1,
                "final": True,
            },
        },
        responses=responses,
    )

    assert report["result"] == {
        "slug": topic,
        "status": "ok",
        "items": 1,
        "cards": 1,
        "recalled": 0,
        "rounds": 1,
        "outline": f"vault/topics/{topic}/02-outline.md",
        "saturated": True,
        "subquestions": [{"id": subq, "coverage": "adequate", "dossier": False}],
        "dossiers_failed": [],
        "book_slugs": [],
        "failures": 0,
        "dead_end": True,
    }
    assert overlaps(report, f"{topic}:recall", f"{topic}:steer:r0")
    assert_before(report, f"{topic}:recall", f"{topic}:probe-done:r1")
    assert_before(report, f"{topic}:steer:r0", f"{topic}:probe-done:r1")

    material_labels = [
        f"{paper}:acquire",
        f"{paper}:prepare",
        f"{paper}:analyse",
        f"{paper}:audit",
    ]
    assert any(
        overlaps(report, f"{topic}:webcard:{card}", material_label)
        for material_label in material_labels
    )
    assert_before(
        report,
        f"{topic}:probe-done:r1",
        f"{paper}:acquire",
    )
    assert_before(
        report,
        f"{paper}:acquire",
        f"{paper}:prepare",
    )
    assert_before(report, f"{paper}:prepare", f"{paper}:analyse")
    assert_before(
        report, f"{paper}:analyse", f"{paper}:audit"
    )
    assert_before(report, f"{paper}:audit", f"{topic}:steer:r1")
    assert_before(report, f"{topic}:probe-cards:r1", f"{topic}:steer:r1")
    assert_before(report, f"{topic}:steer:r1", f"{topic}:synthesise-topic")

    final_audit_labels = set(topic_audits)
    assert final_audit_labels.issubset(set(labels(report)))
    for audit_label in final_audit_labels:
        assert_before(report, f"{topic}:synthesise-topic", audit_label)
    final_audits = [call(report, label) for label in final_audit_labels]
    assert max(item["start"] for item in final_audits) < min(
        item["end"] for item in final_audits
    )
    spine_prompt = call(report, f"{topic}:synthesise-topic")["prompt"]
    assert '"corpus": [' in spine_prompt
    assert f'"path": "vault/papers/{paper}.md"' in spine_prompt
    assert '"role": "evidence_card"' in spine_prompt
    assert f'"path": "{card_path}"' in spine_prompt

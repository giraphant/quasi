from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "workflows" / "run-stage.mjs"

NODE_HARNESS = r"""
import {
  RUN_STAGE_REGISTRY,
  STAGE_STATUSES,
  resolveStage,
  resolveStageContext,
  run,
  stageReceiptSchema,
} from __ENTRY__

const config = JSON.parse(process.argv[1])
if (config.args?.inspectProtocol) {
  const registry = Object.fromEntries(
    Object.entries(RUN_STAGE_REGISTRY).map(([kind, stages]) => [
      kind,
      Object.fromEntries(
        Object.entries(stages).map(([stage, operation]) => {
          const resolved = resolveStage(kind, stage)
          return [stage, {
            operation,
            resolvedOperation: resolved?.operation || null,
            agentType: resolved?.descriptor?.agentType || null,
            phase: resolved?.descriptor?.stage || null,
          }]
        }),
      ),
    ]),
  )
  const stageSchema = stageReceiptSchema({
    operation: "protocol.example",
    stage: "Analyse",
    materialKey: "paper:example",
    effect: "writer",
  })
  process.stdout.write(JSON.stringify({ registry, statuses: STAGE_STATUSES, stageSchema }))
  process.exit(0)
}
const trace = []
const logs = []
const receipt = { sentinel: "returned-verbatim" }
const stageReceipts = config.stageReceipts || null
const hasUnits = Array.isArray(config.args.units) && config.args.units.length > 0
const result = await run({
  agent: async (prompt, options) => {
    trace.push({ prompt, options })
    const stageKey = options.phase.toLowerCase()
    if (
      stageReceipts &&
      Object.prototype.hasOwnProperty.call(stageReceipts, stageKey)
    ) {
      return stageReceipts[stageKey]
    }
    return hasUnits
      ? { ...receipt, unit_label: options.label }
      : receipt
  },
  parallel: async (thunks) => {
    const out = []
    for (const thunk of thunks) {
      try {
        out.push(await thunk())
      } catch {
        out.push(null)
      }
    }
    return out
  },
  log: (message) => {
    logs.push(message)
  },
}, config.args)
const resolved = resolveStage(config.args.kind, config.args.stage)
let direct = null
if (resolved && !hasUnits && result.schema_version !== "quasi.run-stage.error/0.1") {
  const context = resolveStageContext(
    resolved,
    config.args.slug,
    config.args.context,
  )
  const refs = resolved.descriptor.refs(context)
  const receiptSchema = typeof resolved.row.receiptSchema === "function"
    ? resolved.row.receiptSchema(context)
    : { modelSchema: resolved.row.schema(context), stampedValues: null }
  direct = {
    operation: resolved.operation,
    prompt: resolved.row.prompt(context),
    schema: receiptSchema.modelSchema,
    stampedValues: receiptSchema.stampedValues,
    request: resolved.descriptor.envelope(context, refs),
  }
}
process.stdout.write(JSON.stringify({ result, trace, logs, direct }))
"""


def run_stage(
    args: dict[str, Any],
    *,
    stage_receipts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = NODE_HARNESS.replace("__ENTRY__", json.dumps(ENTRY.as_uri()))
    config: dict[str, Any] = {"args": args}
    if stage_receipts is not None:
        config["stageReceipts"] = stage_receipts
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, json.dumps(config)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


EXPECTED_REGISTRY = {
    "paper": {
        "search": "material.search",
        "acquire": "paper.acquire",
        "prepare": "paper.prepare",
        "analyse": "paper.analyse",
        "audit": "paper.audit",
    },
    "book": {
        "search": "material.search",
        "acquire": "book.acquire",
        "prepare": "book.prepare",
        "analyse": "chapter.analyse",
        "synthesise": "book.synthesise",
        "audit": "book.audit",
    },
    "talk": {
        "prepare": "talk.prepare",
        "analyse": "talk.analyse",
        "audit": "talk.audit",
    },
    "translation": {"prepare": "translation.prepare"},
    "topic": {
        "recall": "topic.recall",
        "steer": "topic.steer",
        "webcard": "topic.webcard",
        "synthesise-overview": "topic.synthesise.overview",
        "synthesise-resources": "topic.synthesise.resources",
        "audit": "topic.audit",
    },
    "author": {
        "discover-books": "author.discover-books",
        "discover-papers": "author.discover-papers",
        "resolve-membership": "author.resolve-membership",
        "synthesise": "author.synthesise",
        "audit": "author.audit",
    },
    "translate": {"prepare": "translation.prepare"},
}


def stage_context(kind: str, stage: str) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if kind in {"paper", "book"} and stage == "acquire":
        context["meta"] = {
            "title": "Example Title",
            "authors": ["Example Author"],
            "year": 1991,
            "doi": None,
        }
        if kind == "paper":
            context["meta"].update(
                {
                    "oa_url": "https://example.org/example.pdf",
                    "url": "https://www.jstor.org/stable/43154235",
                }
            )
    if kind == "book" and stage == "analyse":
        context["chapter"] = {
            "slot": "01",
            "slug": "introduction",
            "title": "Introduction",
            "filename": "ch01-introduction.md",
        }
        context["output_exists"] = False
    if kind == "book" and stage == "prepare":
        context["format"] = "epub"
    if kind == "paper" and stage == "analyse":
        context["input"] = "processing/papers/example/source.txt"
    if kind == "topic" and stage == "webcard":
        context.update(
            {
                "query": "A bilingual topic query",
                "web_task": {
                    "subq": "sq-example",
                    "query": "example web query",
                    "card_slug": "example-card",
                },
            }
        )
    if kind == "topic" and stage == "recall":
        context.update(
            {
                "query": "A bilingual topic query",
                "subquestions": [
                    {
                        "id": "sq-example",
                        "question": "Which mechanisms matter?",
                        "coverage": "thin",
                    }
                ],
                "max_items": 8,
            }
        )
    if kind == "topic" and stage == "audit":
        context["target"] = "vault/topics/example/00-overview.md"
    if kind == "author" and stage == "synthesise":
        context.update(
            {
                "full_name": "Example Author",
                "inputs": [
                    {
                        "material_key": "paper:example-paper",
                        "kind": "paper",
                        "id": "example-paper",
                        "path": "vault/papers/example-paper.md",
                        "title": "Example Paper",
                    }
                ],
            }
        )
    if kind == "author" and stage in {"discover-books", "discover-papers"}:
        context.update(
            {
                "full_name": "Example Author",
                "topic": "example topic",
                "count": 5,
            }
        )
    return context


def paper_chain_model_outputs(slug: str = "example-paper") -> dict[str, Any]:
    normalized = f"processing/papers/{slug}/source.txt"
    return {
        "acquire": {
            "write_state": "written",
            "identity_verified": True,
            "attempts": [],
            "terminal": {
                "status": "complete",
                "issue": None,
                "disposition": "created",
                "source": "open_access",
            },
        },
        "prepare": {
            "selected_input": normalized,
            "artifacts": [
                {
                    "role": "normalized_text",
                    "path": normalized,
                    "exists": True,
                    "usable": True,
                }
            ],
            "steps": [],
            "diagnostics": [],
            "terminal": {"status": "complete", "issue": None},
        },
        "analyse": {
            "artifact_roles": ["canonical"],
            "terminal": {
                "status": "complete",
                "issue": None,
                "action": "create",
            },
        },
        "audit": {
            "remaining_violations": 0,
            "escalated": [],
            "mutated_paths": [],
            "terminal": {"status": "complete", "issue": None},
        },
    }


def expected_paper_chain_receipt(
    stage: str,
    model_output: dict[str, Any],
    slug: str = "example-paper",
) -> dict[str, Any]:
    normalized = f"processing/papers/{slug}/source.txt"
    common = {
        "schema_version": "quasi.stage.receipt/0.3",
        "material_key": f"paper:{slug}",
        "effect": "writer",
        "attempt": 1,
    }
    stage_stamps = {
        "acquire": {
            "operation": "paper.acquire",
            "stage": "Acquire",
            "output_path": f"sources/{slug}.pdf",
            "doi": None,
        },
        "prepare": {
            "operation": "paper.prepare",
            "stage": "Prepare",
            "source_path": f"sources/{slug}.pdf",
        },
        "analyse": {
            "operation": "paper.analyse",
            "stage": "Analyse",
            "input_path": normalized,
            "output_path": f"vault/papers/{slug}.md",
        },
        "audit": {
            "operation": "paper.audit",
            "stage": "Audit",
            "target_path": f"vault/papers/{slug}.md",
            "pass": 1,
            "artifact_roles": ["canonical"],
        },
    }
    return {**common, **stage_stamps[stage], **model_output}


def chapter_unit(
    slot: str, slug: str, title: str, *, output_exists: bool = False
) -> dict[str, Any]:
    return {
        "label": slug,
        "context": {
            "chapter": {
                "slot": slot,
                "slug": slug,
                "title": title,
                "filename": f"ch{slot}-{slug}.md",
            },
            "output_exists": output_exists,
        },
    }


def protocol_report() -> dict[str, Any]:
    return run_stage({"inspectProtocol": True})


@pytest.mark.parametrize(
    ("output_exists", "expected_action", "expected_write_state"),
    [
        (False, "create", "written"),
        (True, "reconciled", "not_written"),
    ],
)
def test_chapter_analyse_pins_complete_to_caller_output_observation(
    output_exists: bool, expected_action: str, expected_write_state: str
) -> None:
    context = stage_context("book", "analyse")
    context["output_exists"] = output_exists
    report = run_stage(
        {
            "kind": "book",
            "slug": "example-book",
            "stage": "analyse",
            "context": context,
        }
    )

    request = report["direct"]["request"]
    assert request["output_observation"] == {
        "path": "vault/books/example-book/ch01-introduction.md",
        "exists": output_exists,
        "authority": "caller",
    }

    terminal = report["direct"]["schema"]["properties"]["terminal"]
    complete = next(
        branch
        for branch in terminal["anyOf"]
        if branch["properties"]["status"]["const"] == "complete"
    )
    assert complete["properties"]["action"]["const"] == expected_action
    assert complete["properties"]["write_state"]["const"] == expected_write_state


def test_chapter_analyse_requires_caller_output_observation() -> None:
    context = stage_context("book", "analyse")
    del context["output_exists"]
    report = run_stage(
        {
            "kind": "book",
            "slug": "example-book",
            "stage": "analyse",
            "context": context,
        }
    )

    assert report["result"]["schema_version"] == "quasi.run-stage.error/0.1"
    assert report["result"]["error"]["code"] == "run-stage.invalid_context"
    assert report["direct"] is None
    assert report["trace"] == []


def test_paper_acquire_prompt_preserves_urls_and_real_diagnostic_capabilities() -> None:
    report = run_stage(
        {
            "kind": "paper",
            "slug": "example-paper",
            "stage": "acquire",
            "context": stage_context("paper", "acquire"),
        }
    )

    request = json.loads(report["direct"]["prompt"])

    assert request["identity"]["oa_url"] == "https://example.org/example.pdf"
    assert request["identity"]["url"] == "https://www.jstor.org/stable/43154235"
    assert "--output" not in request["capabilities"][0]
    assert request["capabilities"][0].startswith("quasi-download paper fetch --slug")
    assert request["capabilities"][1] == (
        "quasi-download paper diagnose --url URL [--via-ezproxy] "
        "[--timeout SECONDS] --json"
    )


def test_prompt_and_schema_are_exactly_the_selected_row_pair() -> None:
    report = run_stage(
        {
            "kind": "paper",
            "slug": "example-paper",
            "stage": "prepare",
            "context": {},
        }
    )
    call = report["trace"][0]
    assert call["prompt"] == report["direct"]["prompt"]
    assert call["options"]["schema"] == report["direct"]["schema"]
    assert call["options"]["agentType"] == "quasi:extract-agent"
    assert call["options"]["phase"] == "Prepare"
    assert call["options"]["label"] == "example-paper:prepare"
    schema = call["options"]["schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "selected_input",
        "artifacts",
        "steps",
        "diagnostics",
        "terminal",
    }
    assert set(schema["required"]) == set(schema["properties"])


@pytest.mark.parametrize(
    ("kind", "stage"),
    [
        (kind, stage)
        for kind, stages in EXPECTED_REGISTRY.items()
        for stage in stages
    ],
)
def test_every_request_envelope_uses_shared_stage_tag(
    kind: str, stage: str
) -> None:
    report = run_stage(
        {
            "kind": kind,
            "slug": "example",
            "stage": stage,
            "context": stage_context(kind, stage),
        }
    )
    assert report["direct"]["request"]["schema_version"] == (
        "quasi.stage.request/0.2"
    )


def test_stage_protocol_has_exactly_four_closed_terminal_branches() -> None:
    report = protocol_report()
    assert report["statuses"] == [
        "complete",
        "needs_input",
        "blocked",
        "failed",
    ]
    terminal = report["stageSchema"]["properties"]["terminal"]
    branches = {
        branch["properties"]["status"]["const"]: branch
        for branch in terminal["anyOf"]
    }
    assert set(branches) == set(report["statuses"])
    assert all(branch["additionalProperties"] is False for branch in branches.values())
    assert branches["complete"]["properties"]["issue"] == {"type": "null"}
    for status in ("needs_input", "blocked", "failed"):
        issue = branches[status]["properties"]["issue"]
        assert issue["additionalProperties"] is False
        assert issue["properties"]["operation"]["const"] == "protocol.example"
    assert (
        branches["needs_input"]["properties"]["issue"]["properties"]
        ["user_question"]["type"]
        == "string"
    )


def _bare_consts(node: Any, path: str = "$") -> list[str]:
    """Paths of schema nodes carrying `const` without an explicit `type`."""
    found: list[str] = []
    if isinstance(node, dict):
        if "const" in node and "type" not in node:
            found.append(path)
        for key, value in node.items():
            if key in {"const", "enum", "default", "examples"}:
                continue
            found.extend(_bare_consts(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_bare_consts(value, f"{path}/{index}"))
    return found


@pytest.mark.parametrize(
    ("kind", "stage"),
    [
        (kind, stage)
        for kind, stages in EXPECTED_REGISTRY.items()
        for stage in stages
    ],
)
def test_every_row_schema_types_its_consts(kind: str, stage: str) -> None:
    # A bare const invites weak StructuredOutput models to stringify the
    # echo (1 -> "1"), making exact-echo validation impossible to satisfy.
    report = run_stage(
        {
            "kind": kind,
            "slug": "example",
            "stage": stage,
            "context": stage_context(kind, stage),
        }
    )
    schema = report["direct"]["schema"]
    assert _bare_consts(schema) == []


@pytest.mark.parametrize("kind", ["paper", "book"])
def test_acquire_write_outcome_lives_only_in_complete_terminal(kind: str) -> None:
    # disposition/source describe an accepted write; on any non-complete
    # terminal the closed branch shape makes echoing them impossible.
    report = run_stage(
        {
            "kind": kind,
            "slug": "example",
            "stage": "acquire",
            "context": stage_context(kind, "acquire"),
        }
    )
    schema = report["direct"]["schema"]
    assert "disposition" not in schema["properties"]
    assert "source" not in schema["properties"]
    branches = {
        branch["properties"]["status"]["const"]: branch
        for branch in schema["properties"]["terminal"]["anyOf"]
    }
    complete = branches["complete"]
    assert {"disposition", "source"}.issubset(set(complete["required"]))
    assert complete["properties"]["disposition"]["enum"] == ["created", "reused"]
    assert complete["properties"]["source"]["type"] == "string"
    for status in ("needs_input", "blocked", "failed"):
        assert branches[status]["additionalProperties"] is False
        assert "disposition" not in branches[status]["properties"]
        assert "source" not in branches[status]["properties"]


def test_model_schema_omits_host_stamps_and_requires_judgement_fields() -> None:
    report = run_stage(
        {"kind": "paper", "slug": "example", "stage": "audit", "context": {}}
    )
    schema = report["direct"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "remaining_violations",
        "escalated",
        "mutated_paths",
        "terminal",
    }
    assert set(schema["required"]) == set(schema["properties"])
    assert report["direct"]["stampedValues"] == {
        "schema_version": "quasi.stage.receipt/0.3",
        "operation": "paper.audit",
        "stage": "Audit",
        "material_key": "paper:example",
        "effect": "writer",
        "attempt": 1,
        "target_path": "vault/papers/example.md",
        "pass": 1,
        "artifact_roles": ["canonical"],
    }


def test_host_stamps_bookkeeping_onto_validated_model_output() -> None:
    model_output = {
        "remaining_violations": 0,
        "escalated": [],
        "mutated_paths": [],
        "terminal": {"status": "complete", "issue": None},
    }
    report = run_stage(
        {"kind": "paper", "slug": "example", "stage": "audit", "context": {}},
        stage_receipts={"audit": model_output},
    )

    assert report["result"] == {
        "schema_version": "quasi.stage.receipt/0.3",
        "operation": "paper.audit",
        "stage": "Audit",
        "material_key": "paper:example",
        "effect": "writer",
        "attempt": 1,
        "target_path": "vault/papers/example.md",
        "pass": 1,
        "artifact_roles": ["canonical"],
        **model_output,
    }


@pytest.mark.parametrize(
    ("kind", "stage", "code"),
    [
        ("unknown", "prepare", "run-stage.unknown_kind"),
        ("paper", "unknown", "run-stage.unknown_stage"),
    ],
)
def test_unknown_selection_returns_typed_error(
    kind: str, stage: str, code: str
) -> None:
    report = run_stage(
        {"kind": kind, "slug": "example", "stage": stage, "context": {}}
    )
    assert report["trace"] == []
    assert report["result"]["schema_version"] == "quasi.run-stage.error/0.1"
    assert report["result"]["status"] == "error"
    assert report["result"]["error"]["code"] == code


def test_paper_chain_dispatches_fixed_sequence_and_carries_prepare_input() -> None:
    slug = "example-paper"
    model_outputs = paper_chain_model_outputs(slug)
    report = run_stage(
        {
            "kind": "paper",
            "slug": slug,
            "stage": "acquire",
            "until": "audit",
            "context": stage_context("paper", "acquire"),
        },
        stage_receipts=model_outputs,
    )

    assert [call["options"]["label"] for call in report["trace"]] == [
        f"{slug}:acquire",
        f"{slug}:prepare",
        f"{slug}:analyse",
        f"{slug}:audit",
    ]
    assert [call["options"]["phase"] for call in report["trace"]] == [
        "Acquire",
        "Prepare",
        "Analyse",
        "Audit",
    ]
    assert report["logs"] == [
        f"acquire — {slug}",
        f"prepare — {slug}",
        f"analyse — {slug}",
        f"audit — {slug}",
    ]
    analyse_request = json.loads(report["trace"][2]["prompt"].split("\n", 2)[2])
    assert analyse_request["input"]["path"] == (
        f"processing/papers/{slug}/source.txt"
    )

    result = report["result"]
    assert result["schema_version"] == "quasi.run-stage.chain/0.1"
    assert result["kind"] == "paper"
    assert result["slug"] == slug
    assert result["from"] == "acquire"
    assert result["until"] == "audit"
    assert result["stopped_at"] == "audit"
    assert result["stop_reason"] == "end"
    assert [item["stage"] for item in result["receipts"]] == [
        "acquire",
        "prepare",
        "analyse",
        "audit",
    ]
    assert [item["receipt"] for item in result["receipts"]] == [
        expected_paper_chain_receipt("acquire", model_outputs["acquire"], slug),
        expected_paper_chain_receipt("prepare", model_outputs["prepare"], slug),
        expected_paper_chain_receipt("analyse", model_outputs["analyse"], slug),
        expected_paper_chain_receipt("audit", model_outputs["audit"], slug),
    ]


def test_paper_chain_stops_at_needs_input_gate() -> None:
    model_outputs = paper_chain_model_outputs()
    model_outputs["acquire"] = {
        **model_outputs["acquire"],
        "write_state": "not_written",
        "identity_verified": False,
        "terminal": {
            "status": "needs_input",
            "issue": {
                "code": "paper.acquire_choice_required",
                "operation": "paper.acquire",
                "summary": "The accepted source needs a user decision.",
                "user_question": "Which accepted source should be used?",
                "retryable": True,
            },
        },
    }
    report = run_stage(
        {
            "kind": "paper",
            "slug": "example-paper",
            "stage": "acquire",
            "until": "audit",
            "context": stage_context("paper", "acquire"),
        },
        stage_receipts=model_outputs,
    )

    assert len(report["trace"]) == 1
    assert report["result"]["stop_reason"] == "needs_input"
    assert report["result"]["stopped_at"] == "acquire"
    assert report["result"]["receipts"] == [
        {
            "stage": "acquire",
            "receipt": expected_paper_chain_receipt(
                "acquire", model_outputs["acquire"]
            ),
        }
    ]


def test_paper_chain_rejects_incoherent_complete_before_next_stage() -> None:
    model_outputs = paper_chain_model_outputs()
    model_outputs["prepare"] = {
        **model_outputs["prepare"],
        "selected_input": None,
    }
    report = run_stage(
        {
            "kind": "paper",
            "slug": "example-paper",
            "stage": "acquire",
            "until": "audit",
            "context": stage_context("paper", "acquire"),
        },
        stage_receipts=model_outputs,
    )

    assert [call["options"]["phase"] for call in report["trace"]] == [
        "Acquire",
        "Prepare",
    ]
    assert report["result"]["stop_reason"] == "incoherent_complete"
    assert report["result"]["stopped_at"] == "prepare"
    assert [item["stage"] for item in report["result"]["receipts"]] == [
        "acquire",
        "prepare",
    ]


def test_paper_chain_records_dead_agent_as_null_receipt() -> None:
    model_outputs = paper_chain_model_outputs()
    model_outputs["prepare"] = None
    report = run_stage(
        {
            "kind": "paper",
            "slug": "example-paper",
            "stage": "acquire",
            "until": "audit",
            "context": stage_context("paper", "acquire"),
        },
        stage_receipts=model_outputs,
    )

    assert [call["options"]["phase"] for call in report["trace"]] == [
        "Acquire",
        "Prepare",
    ]
    assert report["result"]["stop_reason"] == "no_receipt"
    assert report["result"]["stopped_at"] == "prepare"
    assert report["result"]["receipts"][-1] == {
        "stage": "prepare",
        "receipt": None,
    }


@pytest.mark.parametrize(
    "units",
    [
        [{"context": stage_context("paper", "acquire")}],
        [],
    ],
)
def test_chain_rejects_units_as_invalid_context(units: list[dict[str, Any]]) -> None:
    report = run_stage(
        {
            "kind": "paper",
            "slug": "example-paper",
            "stage": "acquire",
            "until": "audit",
            "units": units,
        }
    )

    assert report["trace"] == []
    assert report["result"]["error"]["code"] == "run-stage.invalid_context"


def test_chain_rejects_reverse_range() -> None:
    report = run_stage(
        {
            "kind": "paper",
            "slug": "example-paper",
            "stage": "audit",
            "until": "acquire",
            "context": {},
        }
    )

    assert report["trace"] == []
    assert report["result"]["error"]["code"] == "run-stage.invalid_chain"


def test_chain_rejects_kind_without_sequence() -> None:
    report = run_stage(
        {
            "kind": "talk",
            "slug": "example-talk",
            "stage": "prepare",
            "until": "audit",
            "context": {},
        }
    )

    assert report["trace"] == []
    assert report["result"]["error"]["code"] == "run-stage.invalid_chain"


def test_book_analyse_fans_out_units_and_preserves_receipt_order() -> None:
    units = [
        chapter_unit("01", "introduction", "Introduction"),
        chapter_unit("02", "methods", "Methods"),
        chapter_unit("03", "conclusion", "Conclusion", output_exists=True),
    ]
    report = run_stage(
        {
            "kind": "book",
            "slug": "example-book",
            "stage": "analyse",
            "units": units,
        }
    )

    result = report["result"]
    expected_labels = [
        "example-book:analyse:introduction",
        "example-book:analyse:methods",
        "example-book:analyse:conclusion",
    ]
    assert result["schema_version"] == "quasi.run-stage.batch/0.1"
    assert result["kind"] == "book"
    assert result["stage"] == "analyse"
    assert result["count"] == 3
    assert [call["options"]["label"] for call in report["trace"]] == expected_labels
    expected_paths = [
        (
            "processing/chapters/example-book/ch01-introduction.md",
            "vault/books/example-book/ch01-introduction.md",
        ),
        (
            "processing/chapters/example-book/ch02-methods.md",
            "vault/books/example-book/ch02-methods.md",
        ),
        (
            "processing/chapters/example-book/ch03-conclusion.md",
            "vault/books/example-book/ch03-conclusion.md",
        ),
    ]
    assert len(result["receipts"]) == len(expected_labels)
    for receipt, label, (input_path, output_path) in zip(
        result["receipts"], expected_labels, expected_paths
    ):
        assert receipt == {
            "schema_version": "quasi.stage.receipt/0.3",
            "operation": "chapter.analyse",
            "stage": "Analyse",
            "material_key": "book:example-book",
            "effect": "writer",
            "attempt": 1,
            "input_path": input_path,
            "output_path": output_path,
            "sentinel": "returned-verbatim",
            "unit_label": label,
        }


def test_batch_invalid_context_is_per_unit_and_other_units_dispatch() -> None:
    units = [
        chapter_unit("01", "introduction", "Introduction"),
        {"label": "broken", "context": {"output_exists": False}},
        chapter_unit("03", "conclusion", "Conclusion"),
    ]
    report = run_stage(
        {
            "kind": "book",
            "slug": "example-book",
            "stage": "analyse",
            "units": units,
        }
    )

    receipts = report["result"]["receipts"]
    assert len(receipts) == 3
    assert receipts[0]["unit_label"] == "example-book:analyse:introduction"
    assert receipts[1]["schema_version"] == "quasi.run-stage.error/0.1"
    assert receipts[1]["error"]["code"] == "run-stage.invalid_context"
    assert receipts[2]["unit_label"] == "example-book:analyse:conclusion"
    assert [call["options"]["label"] for call in report["trace"]] == [
        "example-book:analyse:introduction",
        "example-book:analyse:conclusion",
    ]


def test_batch_duplicate_units_fail_before_any_agent_dispatch() -> None:
    unit = chapter_unit("01", "introduction", "Introduction")
    report = run_stage(
        {
            "kind": "book",
            "slug": "example-book",
            "stage": "analyse",
            "units": [unit, unit],
        }
    )

    assert report["result"]["schema_version"] == "quasi.run-stage.error/0.1"
    assert report["result"]["error"]["code"] == "run-stage.duplicate_unit"
    assert report["trace"] == []


def test_single_mode_returns_host_stamped_receipt_and_logs_narrative() -> None:
    slug = "s" * 61
    report = run_stage(
        {"kind": "paper", "slug": slug, "stage": "prepare", "context": {}}
    )

    assert report["result"] == {
        "schema_version": "quasi.stage.receipt/0.3",
        "operation": "paper.prepare",
        "stage": "Prepare",
        "material_key": f"paper:{slug}",
        "effect": "writer",
        "attempt": 1,
        "source_path": f"sources/{slug}.pdf",
        "sentinel": "returned-verbatim",
    }
    assert report["logs"] == [f"prepare — {slug[:60]}"]


@pytest.mark.parametrize(
    ("kind", "stage", "code"),
    [
        ("unknown", "prepare", "run-stage.unknown_kind"),
        ("paper", "unknown", "run-stage.unknown_stage"),
    ],
)
def test_batch_unknown_selection_remains_a_top_level_error(
    kind: str, stage: str, code: str
) -> None:
    report = run_stage(
        {
            "kind": kind,
            "slug": "example",
            "stage": stage,
            "units": [{"context": {}}],
        }
    )

    assert report["result"]["schema_version"] == "quasi.run-stage.error/0.1"
    assert report["result"]["error"]["code"] == code
    assert "receipts" not in report["result"]
    assert report["trace"] == []

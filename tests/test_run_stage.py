from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "workflows" / "run-stage.entry.mjs"
CONTEXT = ROOT / "scripts" / "workflows" / "run-stage-context.mjs"

NODE_HARNESS = r"""
import { RUN_STAGE_REGISTRY, resolveStage, run } from __ENTRY__
import { makeOperationContext } from __CONTEXT__
import { STAGE_STATUSES, stageReceiptSchema } from __STAGE__

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
const receipt = { sentinel: "returned-verbatim" }
const result = await run({
  agent: async (prompt, options) => {
    trace.push({ prompt, options })
    return receipt
  },
}, config.args)
const resolved = resolveStage(config.args.kind, config.args.stage)
let direct = null
if (resolved) {
  const context = makeOperationContext(
    resolved.kind,
    config.args.slug,
    resolved.operation,
    config.args.context,
  )
  direct = {
    operation: resolved.operation,
    prompt: resolved.row.prompt(context),
    schema: resolved.row.schema(context),
  }
}
process.stdout.write(JSON.stringify({ result, trace, direct }))
"""


def run_stage(args: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = (
        NODE_HARNESS.replace("__ENTRY__", json.dumps(ENTRY.as_uri()))
        .replace("__CONTEXT__", json.dumps(CONTEXT.as_uri()))
        .replace(
            "__STAGE__",
            json.dumps((ROOT / "scripts" / "workflows" / "stage.mjs").as_uri()),
        )
    )
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, json.dumps({"args": args})],
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
    "member": {"admission-probe": "member.admission-probe"},
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
    if kind == "book" and stage == "analyse":
        context["chapter"] = {
            "slot": "01",
            "slug": "introduction",
            "title": "Introduction",
            "filename": "ch01-introduction.md",
        }
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
    if kind == "member":
        context["member_kind"] = "paper"
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
    return context


def protocol_report() -> dict[str, Any]:
    return run_stage({"inspectProtocol": True})


def test_every_registered_stage_resolves_to_its_descriptor_row() -> None:
    registry = protocol_report()["registry"]
    assert set(registry) == set(EXPECTED_REGISTRY)
    for kind, stages in EXPECTED_REGISTRY.items():
        assert set(registry[kind]) == set(stages)
        for stage, operation in stages.items():
            resolved = registry[kind][stage]
            assert resolved["operation"] == operation
            assert resolved["resolvedOperation"] == operation
            assert resolved["agentType"] == "general-purpose" or resolved[
                "agentType"
            ].startswith("quasi:")
            assert resolved["phase"] in {
                "Recall",
                "Search",
                "Acquire",
                "Prepare",
                "Analyse",
                "Synthesise",
                "Audit",
            }


@pytest.mark.parametrize(
    ("kind", "stage", "operation"),
    [
        ("paper", "search", "material.search"),
        ("book", "audit", "book.audit"),
        ("talk", "audit", "talk.audit"),
        ("translation", "prepare", "translation.prepare"),
        ("topic", "recall", "topic.recall"),
        ("topic", "audit", "topic.audit"),
        ("author", "resolve-membership", "author.resolve-membership"),
        ("author", "synthesise", "author.synthesise"),
        ("author", "audit", "author.audit"),
        ("member", "admission-probe", "member.admission-probe"),
    ],
)
def test_registry_resolves_one_stage_per_kind(
    kind: str, stage: str, operation: str
) -> None:
    report = run_stage(
        {
            "kind": kind,
            "slug": "example",
            "stage": stage,
            "context": stage_context(kind, stage),
        }
    )
    assert report["direct"]["operation"] == operation
    assert report["result"] == {"sentinel": "returned-verbatim"}
    assert len(report["trace"]) == 1


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
    assert schema["properties"]["schema_version"]["const"] == (
        "quasi.stage.receipt/0.2"
    )
    assert schema["properties"]["operation"]["const"] == "paper.prepare"
    assert schema["properties"]["material_key"]["const"] == (
        "paper:example-paper"
    )
    assert "terminal" in schema["required"]


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


def test_audit_echo_consts_carry_value_types() -> None:
    report = run_stage(
        {"kind": "paper", "slug": "example", "stage": "audit", "context": {}}
    )
    properties = report["direct"]["schema"]["properties"]
    assert properties["pass"] == {"const": 1, "type": "integer"}
    assert properties["artifact_roles"]["type"] == "array"
    assert properties["artifact_roles"]["const"] == ["canonical"]
    assert properties["target_path"]["type"] == "string"


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

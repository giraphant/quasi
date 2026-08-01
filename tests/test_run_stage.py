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
import { resolveStage, run } from __ENTRY__
import { makeOperationContext } from __CONTEXT__

const config = JSON.parse(process.argv[1])
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


@pytest.mark.parametrize(
    ("kind", "stage", "operation"),
    [
        ("paper", "search", "material.search"),
        ("book", "audit", "book.audit"),
        ("talk", "audit", "talk.audit"),
        ("translation", "prepare", "translation.prepare"),
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
    context: dict[str, Any] = {}
    if kind == "topic":
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
    report = run_stage(
        {"kind": kind, "slug": "example", "stage": stage, "context": context}
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

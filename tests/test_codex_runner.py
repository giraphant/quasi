from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PLUGIN_ROOT / "scripts" / "codex-runner.mjs"


def node() -> str:
    command = shutil.which("node")
    if not command:
        pytest.skip("node not on PATH")
    return command


def test_codex_runner_strictifies_optional_receipt_fields() -> None:
    script = f"""
import {{ strictSchema }} from {json.dumps(RUNNER.as_uri())}
const source = {{
  type: 'object',
  required: ['status'],
  properties: {{
    status: {{ type: 'string' }},
    note: {{ type: 'string' }},
    items: {{ type: 'array', items: {{
      type: 'object',
      properties: {{ slug: {{ type: 'string' }} }},
    }} }},
  }},
}}
console.log(JSON.stringify(strictSchema(source)))
"""
    proc = subprocess.run(
        [node(), "--input-type=module", "-e", script],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    schema = json.loads(proc.stdout)

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["status", "note", "items"]
    assert schema["properties"]["note"]["type"] == ["string", "null"]
    item = schema["properties"]["items"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["slug"]
    assert item["properties"]["slug"]["type"] == ["string", "null"]


def test_codex_runner_preserves_explicit_nullable_scalar_branches() -> None:
    script = f"""
import {{ strictSchema }} from {json.dumps(RUNNER.as_uri())}
import {{
  TRANSLATION_PREPARE_STAGE_CONTRACT,
}} from "./scripts/workflows/operations/translate.mjs"
console.log(JSON.stringify(strictSchema(TRANSLATION_PREPARE_STAGE_CONTRACT.schema)))
"""
    proc = subprocess.run(
        [node(), "--input-type=module", "-e", script],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    schema = json.loads(proc.stdout)

    assert schema["type"] == "object"
    assert "anyOf" not in schema
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["properties"]["backend"]["type"]) == {"string", "null"}
    gate_fingerprint = schema["properties"]["gate"]["properties"][
        "candidates_fingerprint"
    ]
    assert any(branch == {"type": "null"} for branch in gate_fingerprint["anyOf"])
    assert any(branch.get("type") == "string" for branch in gate_fingerprint["anyOf"])
    median = schema["properties"]["validation"]["properties"]["coverage"][
        "properties"
    ]["median"]
    assert any(branch == {"type": "null"} for branch in median["anyOf"])
    assert any(branch.get("type") == "number" for branch in median["anyOf"])


def test_codex_runner_strictifies_stage_terminal_branches() -> None:
    script = f"""
import {{ strictSchema }} from {json.dumps(RUNNER.as_uri())}
import {{
  PAPER_PREPARE_STAGE_CONTRACT,
}} from "./scripts/workflows/operations/extract.mjs"
console.log(JSON.stringify(strictSchema(PAPER_PREPARE_STAGE_CONTRACT.schema)))
"""
    proc = subprocess.run(
        [node(), "--input-type=module", "-e", script],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    schema = json.loads(proc.stdout)
    branches = schema["properties"]["terminal"]["anyOf"]
    assert [branch["properties"]["status"]["const"] for branch in branches] == [
        "complete",
        "needs_input",
        "blocked",
        "failed",
    ]
    assert branches[0]["properties"]["issue"] == {"type": "null"}
    for branch in branches[1:]:
        issue = branch["properties"]["issue"]
        assert issue["additionalProperties"] is False
        assert set(issue["required"]) == set(issue["properties"])
        assert issue["properties"]["user_question"]["type"] in (
            "string",
            ["string", "null"],
        )


def test_codex_runner_executes_graph_through_codex_cli_contract(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    workflow = tmp_path / "smoke.mjs"
    workflow.write_text(
        """
export const meta = { name: 'codex-smoke' }
return agent('Return the smoke receipt.', {
  agentType: 'general-purpose',
  label: 'smoke',
  schema: {
    type: 'object',
    required: ['status'],
    properties: {
      status: { type: 'string' },
      note: { type: 'string' },
    },
  },
})
""",
        encoding="utf-8",
    )
    trace = tmp_path / "trace.json"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
output = Path(args[args.index("--output-last-message") + 1])
schema_path = Path(args[args.index("--output-schema") + 1])
Path(os.environ["FAKE_CODEX_TRACE"]).write_text(json.dumps({
    "args": args,
    "prompt": sys.stdin.read(),
    "schema": json.loads(schema_path.read_text()),
}))
output.write_text('{"status":"ok","note":null}\\n')
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    env = os.environ.copy()
    env["QUASI_CODEX_BIN"] = str(fake_codex)
    env["FAKE_CODEX_TRACE"] = str(trace)

    proc = subprocess.run(
        [
            node(),
            str(RUNNER),
            "--plugin-root",
            str(PLUGIN_ROOT),
            "--script",
            str(workflow),
            "--cwd",
            str(project),
            "--args-json",
            "{}",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(proc.stdout) == {"status": "ok", "note": None}
    invocation = json.loads(trace.read_text(encoding="utf-8"))
    assert invocation["args"][0] == "exec"
    assert "--ephemeral" in invocation["args"]
    assert ["--sandbox", "workspace-write"] == invocation["args"][
        invocation["args"].index("--sandbox") : invocation["args"].index(
            "--sandbox"
        )
        + 2
    ]
    assert "Return the smoke receipt." in invocation["prompt"]
    assert invocation["schema"]["required"] == ["status", "note"]
    assert invocation["schema"]["additionalProperties"] is False
    assert not list((project / ".quasi" / "temp").glob("codex-agent-*"))

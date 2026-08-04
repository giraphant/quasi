from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "workflows" / "run-stage.mjs"


def test_generated_run_stage_executes_with_documented_workflow_host_abi() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = r"""
import { readFile } from "node:fs/promises";

const source = await readFile(process.argv[1], "utf8");
const metaExports = source.match(/^export const meta =/gm) || [];
if (metaExports.length !== 1) {
  throw new Error(`expected one public meta export, got ${metaExports.length}`);
}
const body = source.replace(/^export const meta =/m, "const meta =");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const execute = new AsyncFunction("agent", "pipeline", "args", body);
const result = await execute(
  async () => ({
    remaining_violations: 0,
    escalated: [],
    mutated_paths: [],
    terminal: { status: "complete", issue: null },
  }),
  async (items, worker) => {
    const results = [];
    for (const item of items) results.push(await worker(item));
    return results;
  },
  { kind: "paper", slug: "example", stage: "audit", context: {} },
);
process.stdout.write(JSON.stringify(result));
"""
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, str(BUNDLE)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {
        "schema_version": "quasi.stage.receipt/0.3",
        "operation": "paper.audit",
        "stage": "Audit",
        "material_key": "paper:example",
        "effect": "writer",
        "attempt": 1,
        "target_path": "vault/papers/example.md",
        "pass": 1,
        "artifact_roles": ["canonical"],
        "remaining_violations": 0,
        "escalated": [],
        "mutated_paths": [],
        "terminal": {"status": "complete", "issue": None},
    }

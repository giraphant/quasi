from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "workflows" / "run-stage.mjs"
UNIVERSAL_CATALOG = "scripts/workflows/operations/catalog.mts"
ROW_PREFIX = "scripts/workflows/operations/rows/"
MATERIAL_RESULT = "scripts/workflows/shared/material-result.mts"


def _bundle_inputs(source: str) -> set[str]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = r"""
import { resolve } from "node:path";
import { build } from "esbuild";

const root = process.cwd();
const result = await build({
  absWorkingDir: root,
  bundle: true,
  entryPoints: [resolve(root, process.argv[1])],
  format: "esm",
  legalComments: "none",
  logLevel: "silent",
  metafile: true,
  platform: "node",
  target: ["es2022"],
  treeShaking: true,
  write: false,
});
process.stdout.write(JSON.stringify(Object.keys(result.metafile.inputs)));
"""
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return {Path(item).as_posix() for item in json.loads(proc.stdout)}


def _row_inputs(inputs: set[str]) -> set[str]:
    return {
        item.removeprefix(ROW_PREFIX).removesuffix(".mts")
        for item in inputs
        if item.startswith(ROW_PREFIX) and item.endswith(".mts")
    }


def test_prepared_dispatch_has_no_catalog_or_operation_row_dependency() -> None:
    inputs = _bundle_inputs(
        "scripts/workflows/shared/dispatch-prepared.mts"
    )

    assert UNIVERSAL_CATALOG not in inputs
    assert _row_inputs(inputs) == set()


@pytest.mark.parametrize(
    ("kind", "expected_rows"),
    [
        ("paper", {"search", "paper"}),
        ("book", {"search", "book"}),
        ("talk", {"talk"}),
        ("translation", {"translation"}),
    ],
)
def test_leaf_catalog_has_exact_material_row_dependencies(
    kind: str,
    expected_rows: set[str],
) -> None:
    inputs = _bundle_inputs(
        f"scripts/workflows/operations/catalogs/{kind}.mts"
    )

    assert UNIVERSAL_CATALOG not in inputs
    assert _row_inputs(inputs) == expected_rows


@pytest.mark.parametrize("kind", ["paper", "book"])
def test_leaf_parser_plus_public_result_stays_domain_local(kind: str) -> None:
    inputs = _bundle_inputs(f"scripts/workflows/contracts/{kind}.mts")

    assert MATERIAL_RESULT in inputs
    forbidden = {
        f"scripts/workflows/contracts/{other}.mts"
        for other in ("paper", "book", "talk", "translation", "topic")
        if other != kind
    }
    assert inputs.isdisjoint(forbidden)


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

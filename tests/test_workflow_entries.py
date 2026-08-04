from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from test_material_plans import (
    AUTHOR_SEED,
    audit_complete,
    author_discovery_complete,
    author_observation,
    author_resolve_complete,
    book_identity,
    canonical_book_input,
    canonical_input,
    canonical_talk_input,
    canonical_translation_input,
    translation_complete,
)
from workflow_test_support import ROOT


ENTRY_HARNESS = r"""
import { resolve } from "node:path";
import { build } from "esbuild";

const root = process.cwd();
const config = JSON.parse(process.argv[1]);
const built = await build({
  absWorkingDir: root,
  bundle: true,
  entryPoints: [resolve(root, `scripts/workflows/${config.entry}.entry.mts`)],
  format: "esm",
  legalComments: "none",
  logLevel: "silent",
  platform: "node",
  target: ["es2022"],
  treeShaking: true,
  write: false,
});
const code = built.outputFiles[0].text;
const loaded = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`
);
let agentCalls = 0;
const runtime = {
  agent: async () => {
    agentCalls += 1;
    return null;
  },
  pipeline: async (items, worker) => Promise.all(items.map(worker)),
};
const result = await loaded.run(runtime, config.input);
process.stdout.write(JSON.stringify({ result, agentCalls }));
"""


def _run_entry(value: dict[str, Any], entry: str = "paper") -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            ENTRY_HARNESS,
            json.dumps({"input": value, "entry": entry}),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


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


def test_paper_entry_rejects_unknown_input_key_before_agent_dispatch() -> None:
    value = canonical_input(canonical=True, admitted=True)
    value["cursor"] = "hidden-state"

    report = _run_entry(value)

    assert report["agentCalls"] == 0
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "material.invalid_input"


def test_generated_paper_executes_with_the_documented_host_abi() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    bundle = ROOT / "workflows" / "paper.mjs"
    source = bundle.read_text(encoding="utf-8")
    assert source.count("export const meta =") == 1
    assert source.rstrip().endswith(
        "return await __quasiWorkflow.run({ agent, pipeline }, args)"
    )
    for foreign_operation in (
        "author.audit",
        "topic.recall",
        "talk.prepare",
        "book.acquire",
    ):
        assert foreign_operation not in source
    script = r"""
import { readFile } from "node:fs/promises";
const config = JSON.parse(process.argv[2]);
const source = await readFile(process.argv[1], "utf8");
const body = source.replace(/^export const meta =/m, "const meta =");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const execute = new AsyncFunction("agent", "pipeline", "args", body);
let calls = 0;
const outputs = [...config.outputs];
const result = await execute(
  async () => {
    calls += 1;
    return outputs.shift();
  },
  async (items, worker) => Promise.all(items.map(worker)),
  config.input,
);
process.stdout.write(JSON.stringify({ result, calls }));
"""
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            script,
            str(bundle),
            json.dumps(
                {
                    "input": canonical_input(canonical=True, admitted=True),
                    "outputs": [audit_complete()],
                }
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["calls"] == 1
    assert report["result"]["terminal"] == "complete"


def test_paper_entry_uses_only_its_local_operation_dependencies() -> None:
    inputs = _bundle_inputs("scripts/workflows/paper.entry.mts")

    assert "scripts/workflows/operations/catalog.mts" not in inputs
    assert "scripts/workflows/shared/dispatch.mts" not in inputs
    assert "scripts/workflows/operations/catalogs/paper.mts" in inputs
    assert "scripts/workflows/shared/dispatch-prepared.mts" in inputs
    row_inputs = {
        item.removeprefix("scripts/workflows/operations/rows/").removesuffix(".mts")
        for item in inputs
        if item.startswith("scripts/workflows/operations/rows/")
    }
    assert row_inputs == {"paper", "search"}
    assert inputs.isdisjoint(
        {
            "scripts/workflows/contracts/talk.mts",
            "scripts/workflows/contracts/topic.mts",
            "scripts/workflows/contracts/translation.mts",
        }
    )


def test_book_entry_rejects_unknown_input_key_before_agent_dispatch() -> None:
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(True, True),
    )
    value["cursor"] = "hidden-state"

    report = _run_entry(value, "book")

    assert report["agentCalls"] == 0
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "material.invalid_input"


def test_book_entry_uses_only_its_local_operation_dependencies() -> None:
    inputs = _bundle_inputs("scripts/workflows/book.entry.mts")

    assert "scripts/workflows/operations/catalog.mts" not in inputs
    assert "scripts/workflows/shared/dispatch.mts" not in inputs
    assert "scripts/workflows/operations/catalogs/book.mts" in inputs
    assert "scripts/workflows/shared/dispatch-prepared.mts" in inputs
    row_inputs = {
        item.removeprefix("scripts/workflows/operations/rows/").removesuffix(".mts")
        for item in inputs
        if item.startswith("scripts/workflows/operations/rows/")
    }
    assert row_inputs == {"book", "search"}
    assert inputs.isdisjoint(
        {
            "scripts/workflows/contracts/talk.mts",
            "scripts/workflows/contracts/topic.mts",
            "scripts/workflows/contracts/translation.mts",
        }
    )


def test_generated_book_executes_with_the_documented_host_abi() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    bundle = ROOT / "workflows" / "book.mjs"
    source = bundle.read_text(encoding="utf-8")
    assert source.count("export const meta =") == 1
    assert source.rstrip().endswith(
        "return await __quasiWorkflow.run({ agent, pipeline }, args)"
    )
    for foreign_operation in (
        "author.audit",
        "topic.recall",
        "talk.prepare",
        "translation.prepare",
    ):
        assert foreign_operation not in source
    script = r"""
import { readFile } from "node:fs/promises";
const config = JSON.parse(process.argv[2]);
const source = await readFile(process.argv[1], "utf8");
const body = source.replace(/^export const meta =/m, "const meta =");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const execute = new AsyncFunction("agent", "pipeline", "args", body);
let agentCalls = 0;
let pipelineCalls = 0;
const result = await execute(
  async () => {
    agentCalls += 1;
    return config.output;
  },
  async (items, worker) => {
    pipelineCalls += 1;
    return Promise.all(items.map(worker));
  },
  config.input,
);
process.stdout.write(JSON.stringify({ result, agentCalls, pipelineCalls }));
"""
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(True, True),
    )
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            script,
            str(bundle),
            json.dumps({"input": value, "output": audit_complete()}),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["agentCalls"] == 1
    assert report["pipelineCalls"] == 0
    assert report["result"]["terminal"] == "complete"


@pytest.mark.parametrize(
    ("entry", "value"),
    [
        ("talk", canonical_talk_input(canonical=True)),
        ("translation", canonical_translation_input()),
    ],
)
def test_new_material_entries_reject_unknown_input_before_agent_dispatch(
    entry: str,
    value: dict[str, Any],
) -> None:
    value["cursor"] = "hidden-state"

    report = _run_entry(value, entry)

    assert report["agentCalls"] == 0
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "material.invalid_input"


@pytest.mark.parametrize(
    ("entry", "row"),
    [("talk", "talk"), ("translation", "translation")],
)
def test_new_material_entries_use_only_their_local_operation_row(
    entry: str,
    row: str,
) -> None:
    inputs = _bundle_inputs(f"scripts/workflows/{entry}.entry.mts")

    assert "scripts/workflows/operations/catalog.mts" not in inputs
    assert "scripts/workflows/shared/dispatch.mts" not in inputs
    assert f"scripts/workflows/operations/catalogs/{entry}.mts" in inputs
    assert "scripts/workflows/shared/dispatch-prepared.mts" in inputs
    row_inputs = {
        item.removeprefix("scripts/workflows/operations/rows/").removesuffix(".mts")
        for item in inputs
        if item.startswith("scripts/workflows/operations/rows/")
    }
    assert row_inputs == {row}


@pytest.mark.parametrize(
    ("entry", "value", "outputs"),
    [
        ("talk", canonical_talk_input(canonical=True), [audit_complete()]),
        ("translation", canonical_translation_input(), [translation_complete()]),
    ],
)
def test_generated_new_material_workflows_execute_with_the_host_abi(
    entry: str,
    value: dict[str, Any],
    outputs: list[dict[str, Any]],
) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    bundle = ROOT / "workflows" / f"{entry}.mjs"
    source = bundle.read_text(encoding="utf-8")
    assert source.count("export const meta =") == 1
    assert source.rstrip().endswith(
        "return await __quasiWorkflow.run({ agent, pipeline }, args)"
    )
    script = r"""
import { readFile } from "node:fs/promises";
const config = JSON.parse(process.argv[2]);
const source = await readFile(process.argv[1], "utf8");
const body = source.replace(/^export const meta =/m, "const meta =");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const execute = new AsyncFunction("agent", "pipeline", "args", body);
const outputs = [...config.outputs];
let calls = 0;
const result = await execute(
  async () => {
    calls += 1;
    return outputs.shift();
  },
  async (items, worker) => Promise.all(items.map(worker)),
  config.input,
);
process.stdout.write(JSON.stringify({ result, calls }));
"""
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            script,
            str(bundle),
            json.dumps({"input": value, "outputs": outputs}),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["calls"] == 1
    assert report["result"]["terminal"] == "complete"


def test_author_entry_rejects_unknown_input_before_agent_dispatch() -> None:
    value = {
        "seed": AUTHOR_SEED,
        "observation": author_observation(),
        "options": {},
        "cursor": "hidden-state",
    }

    report = _run_entry(value, "author")

    assert report["agentCalls"] == 0
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "material.invalid_input"


def test_author_entry_composes_only_local_author_and_leaf_dependencies() -> None:
    inputs = _bundle_inputs("scripts/workflows/author.entry.mts")

    assert "scripts/workflows/operations/catalog.mts" not in inputs
    assert "scripts/workflows/shared/dispatch.mts" not in inputs
    assert "scripts/workflows/operations/catalogs/author.mts" in inputs
    assert "scripts/workflows/operations/catalogs/paper.mts" in inputs
    assert "scripts/workflows/operations/catalogs/book.mts" in inputs
    row_inputs = {
        item.removeprefix("scripts/workflows/operations/rows/").removesuffix(".mts")
        for item in inputs
        if item.startswith("scripts/workflows/operations/rows/")
    }
    assert row_inputs == {"author", "paper", "book", "search"}
    assert inputs.isdisjoint(
        {
            "scripts/workflows/contracts/topic.mts",
            "scripts/workflows/contracts/talk.mts",
            "scripts/workflows/contracts/translation.mts",
            "scripts/workflows/run-stage.entry.mts",
        }
    )


def test_generated_author_executes_the_discovery_pass_with_host_abi() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    bundle = ROOT / "workflows" / "author.mjs"
    source = bundle.read_text(encoding="utf-8")
    assert source.count("export const meta =") == 1
    assert source.rstrip().endswith(
        "return await __quasiWorkflow.run({ agent, pipeline }, args)"
    )
    script = r"""
import { readFile } from "node:fs/promises";
const config = JSON.parse(process.argv[2]);
const source = await readFile(process.argv[1], "utf8");
const body = source.replace(/^export const meta =/m, "const meta =");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const execute = new AsyncFunction("agent", "pipeline", "args", body);
const outputs = [...config.outputs];
let agentCalls = 0;
let pipelineCalls = 0;
const result = await execute(
  async () => {
    agentCalls += 1;
    return outputs.shift();
  },
  async (items, worker) => {
    pipelineCalls += 1;
    return Promise.all(items.map(worker));
  },
  config.input,
);
process.stdout.write(JSON.stringify({ result, agentCalls, pipelineCalls }));
"""
    book = {"kind": "book", **book_identity("book-one", "Book One")}
    outputs = [
        author_discovery_complete([book]),
        author_discovery_complete([]),
        author_resolve_complete([book]),
    ]
    proc = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            script,
            str(bundle),
            json.dumps(
                {
                    "input": {
                        "seed": AUTHOR_SEED,
                        "observation": author_observation(),
                        "options": {},
                    },
                    "outputs": outputs,
                }
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["agentCalls"] == 3
    assert report["pipelineCalls"] == 0
    assert report["result"]["terminal"] == "needs_observation"

"""Concurrency contract for the host-neutral Workflow runtime."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "workflows" / "runtime.mjs"


def run_node(body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [node, "--input-type=module", "-e", body],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_one_phase_is_fifo_and_shared_by_every_operation_surface() -> None:
    result = run_node(
        f"""
import {{ createRuntime, PHASE_AGENT_LIMIT }} from {json.dumps(RUNTIME.as_uri())}

const started = []
const releases = new Map()
const agent = (prompt, opts) => new Promise(resolve => {{
  started.push([prompt, opts.phase])
  releases.set(prompt, () => resolve({{ status: 'succeeded' }}))
}})
const runtime = createRuntime({{
  agent,
  parallel: tasks => Promise.all(tasks.map(task => Promise.resolve().then(task))),
  phase: () => {{}},
  log: () => {{}},
}})
const writer = {{
  effect: 'writer', retry: 'forbidden', key: 'writer',
  unknownFailureCode: 'test.writer_unknown',
}}
const readonly = {{
  effect: 'readonly', retry: 'forbidden', key: 'readonly',
  unknownFailureCode: 'test.readonly_unknown',
}}
const contract = {{
  schema: {{
    type: 'object', additionalProperties: false,
    required: ['status'],
    properties: {{ status: {{ const: 'succeeded' }} }},
  }},
  statuses: {{ succeeded: () => true }},
  edges: {{ succeeded: 'ok' }},
}}

const calls = [
  runtime.runOperation('op-0', {{ phase: 'Analyse', label: 'op-0' }}, writer),
  runtime.runOperation('op-1', {{ phase: 'Analyse', label: 'op-1' }}, readonly),
  runtime.operate('op-2', {{ phase: 'Analyse', label: 'op-2' }}, {{ ...writer, contract }}),
  runtime.runOperation('op-3', {{ phase: 'Analyse', label: 'op-3' }}, writer),
  runtime.operate('op-4', {{ phase: 'Analyse', label: 'op-4' }}, {{ ...readonly, contract }}),
  runtime.runOperation('op-5', {{ phase: 'Analyse', label: 'op-5' }}, writer),
  runtime.runOperation('op-6', {{ phase: 'Analyse', label: 'op-6' }}, readonly),
  runtime.operate('op-7', {{ phase: 'Analyse', label: 'op-7' }}, {{ ...writer, contract }}),
]
const tick = () => new Promise(resolve => setTimeout(resolve, 0))
await tick()
const initial = started.map(row => row[0])
releases.get('op-2')()
await tick()
const afterFirstSlot = started.map(row => row[0])
releases.get('op-0')()
await tick()
const afterSecondSlot = started.map(row => row[0])
releases.get('op-4')()
await tick()
const afterThirdSlot = started.map(row => row[0])
for (const prompt of started.map(row => row[0]))
  releases.get(prompt)?.()
await Promise.all(calls)

console.log(JSON.stringify({{
  limit: PHASE_AGENT_LIMIT,
  initial,
  afterFirstSlot,
  afterSecondSlot,
  afterThirdSlot,
  phases: [...new Set(started.map(row => row[1]))],
}}))
"""
    )

    assert result == {
        "limit": 5,
        "initial": ["op-0", "op-1", "op-2", "op-3", "op-4"],
        "afterFirstSlot": ["op-0", "op-1", "op-2", "op-3", "op-4", "op-5"],
        "afterSecondSlot": [
            "op-0", "op-1", "op-2", "op-3", "op-4", "op-5", "op-6"
        ],
        "afterThirdSlot": [
            "op-0", "op-1", "op-2", "op-3", "op-4", "op-5", "op-6", "op-7"
        ],
        "phases": ["Analyse"],
    }


def test_different_phases_have_independent_admission_lanes() -> None:
    result = run_node(
        f"""
import {{ createRuntime }} from {json.dumps(RUNTIME.as_uri())}

const started = []
const releases = new Map()
const active = new Map()
const maxima = new Map()
const agent = (prompt, opts) => new Promise(resolve => {{
  const phase = opts.phase
  active.set(phase, (active.get(phase) || 0) + 1)
  maxima.set(phase, Math.max(maxima.get(phase) || 0, active.get(phase)))
  started.push([prompt, phase])
  releases.set(prompt, () => {{
    active.set(phase, active.get(phase) - 1)
    resolve({{ status: 'succeeded' }})
  }})
}})
const runtime = createRuntime({{
  agent,
  parallel: tasks => Promise.all(tasks.map(task => Promise.resolve().then(task))),
  phase: () => {{}},
  log: () => {{}},
}})
const spec = {{
  effect: 'writer', retry: 'forbidden', key: 'writer',
  unknownFailureCode: 'test.writer_unknown',
}}
const recall = Array.from({{ length: 6 }}, (_, index) =>
  runtime.runOperation(`recall-${{index}}`, {{ phase: 'Recall', label: `recall-${{index}}` }}, spec)
)
const tick = () => new Promise(resolve => setTimeout(resolve, 0))
await tick()
const beforeSearch = started.map(row => row[0])
const search = Array.from({{ length: 3 }}, (_, index) =>
  runtime.runOperation(`search-${{index}}`, {{ phase: 'Search', label: `search-${{index}}` }}, spec)
)
await tick()
const withSearch = started.map(row => row[0])
for (const prompt of started.map(row => row[0])) releases.get(prompt)?.()
await tick()
for (const prompt of started.map(row => row[0])) releases.get(prompt)?.()
await Promise.all([...recall, ...search])

console.log(JSON.stringify({{
  beforeSearch,
  withSearch,
  maxima: Object.fromEntries(maxima),
}}))
"""
    )

    assert result == {
        "beforeSearch": [
            "recall-0", "recall-1", "recall-2", "recall-3", "recall-4"
        ],
        "withSearch": [
            "recall-0", "recall-1", "recall-2", "recall-3", "recall-4",
            "search-0", "search-1", "search-2",
        ],
        "maxima": {"Recall": 5, "Search": 3},
    }


def test_admission_does_not_change_unknown_writer_terminal() -> None:
    result = run_node(
        f"""
import {{ createRuntime }} from {json.dumps(RUNTIME.as_uri())}
const runtime = createRuntime({{
  agent: async () => null,
  parallel: tasks => Promise.all(tasks.map(task => Promise.resolve().then(task))),
  phase: () => {{}},
  log: () => {{}},
}})
const receipt = await runtime.runOperation(
  'unknown-writer',
  {{ phase: 'Analyse', label: 'unknown-writer' }},
  {{
    effect: 'writer', retry: 'forbidden', key: 'paper.analyse',
    artifactRoles: ['canonical'], replay: 'blocked',
    unknownFailureCode: 'paper.writer_outcome_unknown',
  }},
)
console.log(JSON.stringify(receipt))
"""
    )

    assert result["status"] == "blocked"
    assert result["replay"] == "blocked"

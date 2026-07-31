from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BUNDLE = PLUGIN_ROOT / "workflows" / "process-material.mjs"
ENTRY = PLUGIN_ROOT / "scripts/workflows" / "process-material.entry.mjs"
BUILD = PLUGIN_ROOT / "scripts" / "build-workflows.mjs"
CLAUDE_WORKFLOW_MAX_BYTES = 512 * 1024


def run_node(body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [node, "--input-type=module", "-e", body],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_workflow_source_tree_is_minimal_and_complete() -> None:
    expected = {
        "collections/author.mjs",
        "derivatives/translation.mjs",
        "materials/book.mjs",
        "materials/member.mjs",
        "materials/batch.mjs",
        "materials/dispatch.mjs",
        "materials/ingress.mjs",
            "materials/paper.mjs",
            "materials/receipt.mjs",
            "materials/route.mjs",
            "materials/talk.mjs",
        "operations/acquire.mjs",
        "operations/analyse.mjs",
            "operations/audit.mjs",
            "operations/book-year-evidence.mjs",
            "operations/extract.mjs",
        "operations/steer.mjs",
        "operations/synthesise.mjs",
        "operations/shared.mjs",
        "operations/transcribe.mjs",
        "operations/translate.mjs",
        "process-material.entry.mjs",
        "artifact-contracts/generated.mjs",
        "research/topic-recall.mjs",
        "research/topic.mjs",
        "runtime.mjs",
        "stage.mjs",
    }
    actual = {
        str(path.relative_to(PLUGIN_ROOT / "scripts/workflows"))
        for path in (PLUGIN_ROOT / "scripts/workflows").rglob("*.mjs")
    }
    assert actual == expected


def test_workflow_meta_describes_the_common_lifecycle_not_every_router_branch() -> None:
    result = run_node(
        f"""
import {{ workflowMeta }} from {json.dumps(ENTRY.as_uri())}
console.log(JSON.stringify(workflowMeta))
"""
    )

    assert result["description"] == (
        "Moves academic materials through a shared processing pipeline"
    )
    assert result["phases"] == [
        {"title": "Recall"},
        {"title": "Search"},
        {"title": "Acquire"},
        {"title": "Prepare"},
        {"title": "Analyse"},
        {"title": "Synthesise"},
        {"title": "Audit"},
    ]
    assert not {
        "Book",
        "Paper",
        "Talk",
        "Translation",
        "Author",
        "Topic",
    }.intersection(phase["title"] for phase in result["phases"])


def test_operation_attempt_schemas_explicitly_require_integer_one() -> None:
    module_uris = [
        (PLUGIN_ROOT / "scripts/workflows" / "operations" / name).as_uri()
        for name in (
            "acquire.mjs",
            "analyse.mjs",
            "audit.mjs",
            "extract.mjs",
            "steer.mjs",
            "synthesise.mjs",
            "transcribe.mjs",
            "translate.mjs",
        )
    ]
    result = run_node(
        f"""
const modules = await Promise.all(
  {json.dumps(module_uris)}.map(uri => import(uri))
)
const seen = new WeakSet()
const attempts = []
function visit(value, path) {{
  if (!value || typeof value !== 'object' || seen.has(value)) return
  seen.add(value)
  if (
    value.properties &&
    Object.prototype.hasOwnProperty.call(value.properties, 'attempt')
  ) {{
    attempts.push({{ path, schema: value.properties.attempt }})
  }}
  for (const [key, child] of Object.entries(value)) {{
    visit(child, `${{path}}.${{key}}`)
  }}
}}
for (const [moduleIndex, module] of modules.entries()) {{
  for (const [name, value] of Object.entries(module)) {{
    if (name.endsWith('_SCHEMA')) visit(value, `${{moduleIndex}}:${{name}}`)
  }}
}}
console.log(JSON.stringify({{ attempts }}))
"""
    )
    assert len(result["attempts"]) >= 11
    for attempt in result["attempts"]:
        assert attempt["schema"] == {"type": "integer", "const": 1}, attempt["path"]


def test_workflow_bundle_is_current() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [node, str(BUILD), "--check"],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "workflow bundle is current" in proc.stdout


def test_workflow_bundle_fits_claude_code_limit() -> None:
    size = len(BUNDLE.read_bytes())
    assert size <= CLAUDE_WORKFLOW_MAX_BYTES, (
        f"workflow bundle is {size} bytes; Claude Code accepts at most "
        f"{CLAUDE_WORKFLOW_MAX_BYTES}"
    )


def test_workflow_bundle_has_the_asyncfunction_abi() -> None:
    source = BUNDLE.read_text(encoding="utf-8")
    meta_exports = re.findall(
        r"^\s*export\s+const\s+meta\s*=", source, re.MULTILINE
    )
    assert len(meta_exports) == 1

    body = re.sub(
        r"^\s*export\s+const\s+meta\s*=",
        "const meta =",
        source,
        count=1,
        flags=re.MULTILINE,
    )
    assert not re.search(r"^\s*import(?:\s|\{|\*)", body, re.MULTILINE)
    assert not re.search(r"^\s*export(?:\s|\{|\*)", body, re.MULTILINE)
    assert not re.search(r"\bimport\s*\(", body)
    assert not re.search(r"\brequire\s*\(", body)
    assert not re.search(r"from\s+[\"']node:fs|[\"']fs[\"']", body)
    assert "return await __quasiWorkflow.run(" in body

    result = run_node(
        f"""
const source = {json.dumps(body)}
const AsyncFunction = Object.getPrototypeOf(async () => {{}}).constructor
new AsyncFunction('agent', 'parallel', 'phase', 'log', 'args', source)
console.log(JSON.stringify({{ compiled: true }}))
"""
    )
    assert result == {"compiled": True}


def test_source_and_bundle_keep_the_same_stage_trace() -> None:
    result = run_node(
        f"""
import {{ readFile }} from 'node:fs/promises'
import {{ run }} from {json.dumps(ENTRY.as_uri())}

const args = {{
  kind: 'paper',
  slug: 'parity-paper',
  meta: {{
    title: 'Parity Paper',
    authors: ['P. Arity'],
    year: 2024,
    journal: 'Parity Review',
    doi: '10.1000/parity',
  }},
}}

function harness() {{
  const trace = []
  const logs = []
  const primitives = {{
    agent: async (prompt, options) => {{
      trace.push({{
        prompt: String(prompt),
        label: options.label,
        phase: options.phase,
        agentType: options.agentType,
        schema: options.schema,
      }})
      if (options.label === 'parity-paper:search')
        return {{
          schema_version: 'quasi.stage.receipt/0.2',
          operation: 'material.search',
          stage: 'Search',
          material_key: 'paper:parity-paper',
          effect: 'readonly',
          attempt: 1,
          kind: 'paper',
          identity: {{
            slug: 'parity-paper',
            title: 'Parity Paper',
            authors: ['P. Arity'],
            year: 2024,
            doi: '10.1000/parity',
            oa_url: null,
            url: null,
            journal: 'Parity Review',
            confidence: 'high',
          }},
          local_owner: null,
          confidence: 'high',
          observations: [{{
            source: 'Crossref',
            query: '10.1000/parity',
            summary: 'exact DOI fixture',
          }}],
          terminal: {{ status: 'complete', issue: null }},
        }}
      return {{
        schema_version: 'quasi.stage.receipt/0.2',
        operation: 'paper.acquire',
        stage: 'Acquire',
        material_key: 'paper:parity-paper',
        effect: 'writer',
        attempt: 1,
        output_path: 'sources/parity-paper.pdf',
        doi: '10.1000/parity',
        disposition: null,
        write_state: 'not_written',
        identity_verified: false,
        source: null,
        attempts: [{{ source: 'oa', status: 'failed', error: '404' }}],
        terminal: {{
          status: 'failed',
          issue: {{
            code: 'paper.download_failed',
            operation: 'paper.acquire',
            summary: 'not available',
            user_question: null,
            retryable: false,
          }},
        }},
      }}
    }},
    parallel: tasks => Promise.all(tasks.map(task => Promise.resolve().then(task))),
    phase: () => {{}},
    log: message => logs.push(String(message)),
  }}
  return {{ primitives, trace, logs }}
}}

const sourceHarness = harness()
const sourceResult = await run(sourceHarness.primitives, args)

const bundleHarness = harness()
const bundled = (await readFile({json.dumps(str(BUNDLE))}, 'utf8'))
  .replace(/^export\\s+const\\s+meta\\s*=/m, 'const meta =')
const AsyncFunction = Object.getPrototypeOf(async () => {{}}).constructor
const bundleResult = await new AsyncFunction(
  'agent', 'parallel', 'phase', 'log', 'args', bundled
)(
  bundleHarness.primitives.agent,
  bundleHarness.primitives.parallel,
  bundleHarness.primitives.phase,
  bundleHarness.primitives.log,
  args,
)

console.log(JSON.stringify({{
  sourceResult,
  bundleResult,
  sourceTrace: sourceHarness.trace,
  bundleTrace: bundleHarness.trace,
  sourceLogs: sourceHarness.logs,
  bundleLogs: bundleHarness.logs,
}}))
"""
    )
    assert result["sourceResult"] == result["bundleResult"]
    assert result["sourceTrace"] == result["bundleTrace"]
    assert result["sourceLogs"] == result["bundleLogs"]
    assert result["sourceLogs"] == [
        "process-material result: kind=paper id=parity-paper "
        "status=download_failed"
    ]
    log_text = "\n".join(result["sourceLogs"])
    for secret in (
        "material_receipt",
        "failure_reason",
        "not available",
        "attempts",
        "10.1000/parity",
    ):
        assert secret not in log_text


def test_book_download_failure_keeps_the_public_evidence_shape() -> None:
    result = run_node(
        f"""
import {{ run }} from {json.dumps(ENTRY.as_uri())}

const calls = []
const primitives = {{
  agent: async (_prompt, options) => {{
    calls.push({{ label: options.label }})
    if (options.label === 'legacy-book:search')
      return {{
        schema_version: 'quasi.stage.receipt/0.2',
        operation: 'material.search',
        stage: 'Search',
        material_key: 'book:legacy-book',
        effect: 'readonly',
        attempt: 1,
        kind: 'book',
        identity: {{
          slug: 'legacy-book',
          title: 'Legacy Book',
          authors: ['A. Author'],
          year: 2020,
          isbn: null,
          publisher: 'Legacy Academic Press',
          category: 'monograph',
          confidence: 'high',
        }},
        local_owner: null,
        confidence: 'high',
        observations: [{{
          source: 'catalog',
          query: 'Legacy Book A. Author',
          summary: 'publisher and year agree',
        }}],
        terminal: {{ status: 'complete', issue: null }},
      }}
    return {{
      schema_version: 'quasi.stage.receipt/0.2',
      operation: 'book.acquire',
      stage: 'Acquire',
      material_key: 'book:legacy-book',
      effect: 'writer',
      attempt: 1,
      output_path: null,
      allowed_output_paths: ['sources/legacy-book.epub'],
      disposition: null,
      write_state: 'not_written',
      identity_verified: false,
      format: null,
      tmp_path: null,
      source: null,
      isbn: null,
      year_evidence: null,
      attempts: [{{ source: 'direct', status: 'failed', error: 'not found' }}],
      terminal: {{
        status: 'failed',
        issue: {{
          code: 'book.download_failed',
          operation: 'book.acquire',
          summary: 'candidate could not be acquired',
          user_question: null,
          retryable: false,
        }},
      }},
    }}
  }},
  parallel: tasks => Promise.all(tasks.map(task => task())),
  phase: () => {{}},
  log: () => {{}},
}}
const value = await run(primitives, {{
  kind: 'book',
  slug: 'legacy-book',
  meta: {{
    title: 'Legacy Book',
    authors: ['A. Author'],
    year: 2020,
    publisher: 'Legacy Academic Press',
    category: 'monograph',
    format: 'epub',
  }},
}})
console.log(JSON.stringify({{ value, calls }}))
"""
    )

    value = result["value"]
    assert {
        key: value[key]
        for key in ("slug", "status", "failure_reason", "attempts")
    } == {
        "slug": "legacy-book",
        "status": "download_failed",
        "failure_reason": "candidate could not be acquired",
        "attempts": [
            {
                "source": "direct",
                "status": "failed",
                "error": "not found",
            }
        ],
    }
    assert result["calls"] == [
        {"label": "legacy-book:search"},
        {"label": "legacy-book:acquire"},
    ]


def test_esbuild_is_exactly_pinned_and_dev_only() -> None:
    package = json.loads((PLUGIN_ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["private"] is True
    assert package["devDependencies"] == {"esbuild": "0.28.1"}
    assert "dependencies" not in package
    lock = json.loads(
        (PLUGIN_ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    assert lock["packages"][""]["devDependencies"]["esbuild"] == "0.28.1"

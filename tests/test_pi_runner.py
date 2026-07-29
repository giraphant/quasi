from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PLUGIN_ROOT / "scripts" / "pi-runner.mjs"


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


def test_pi_runner_loads_quasi_audit_agent_and_maps_its_tools() -> None:
    result = run_node(f"""
import {{ createRunner }} from {json.dumps(RUNNER.as_uri())}
const calls = []
const runner = createRunner({{
  pluginRoot: {json.dumps(str(PLUGIN_ROOT))},
  projectCwd: '/tmp/quasi-project',
  invokeAgent: async call => {{ calls.push(call); return {{ status: 'clean', escalated: [] }} }},
  log: () => {{}},
}})
const workflow = `
export const meta = {{ name: 'audit-test' }}
phase('Audit')
return agent('path: vault/books/demo', {{
  phase: 'Audit', agentType: 'quasi:audit-agent', label: 'audit:demo',
  schema: {{ type: 'object', properties: {{ status: {{ type: 'string' }} }} }}
}})
`
const output = await runner.runSource(workflow, {{}})
console.log(JSON.stringify({{
  output,
  name: calls[0].definition.name,
  model: calls[0].definition.model,
  tools: calls[0].definition.piTools,
  prompt: calls[0].prompt,
  hasContract: calls[0].definition.body.includes('quasi-audit'),
  projectDir: process.env.CLAUDE_PROJECT_DIR,
  pathHasBin: process.env.PATH.startsWith({json.dumps(str(PLUGIN_ROOT / "bin"))}),
}}))
""")

    assert result == {
        "output": {"status": "clean", "escalated": []},
        "name": "audit-agent",
        "model": "sonnet",
        "tools": ["read", "edit", "bash"],
        "prompt": "path: vault/books/demo",
        "hasContract": True,
        "projectDir": "/tmp/quasi-project",
        "pathHasBin": True,
    }


def test_pi_runner_parallel_is_ordered_and_concurrency_limited() -> None:
    result = run_node(f"""
import {{ createRunner }} from {json.dumps(RUNNER.as_uri())}
let active = 0, maxActive = 0
const runner = createRunner({{
  pluginRoot: {json.dumps(str(PLUGIN_ROOT))},
  concurrency: 2,
  invokeAgent: async ({{ prompt }}) => {{
    active++; maxActive = Math.max(maxActive, active)
    await new Promise(resolve => setTimeout(resolve, prompt === 'slow' ? 80 : 20))
    active--
    return prompt
  }},
  log: () => {{}},
}})
const workflow = `return parallel([
  () => agent('slow', {{ agentType: 'general-purpose' }}),
  () => agent('fast-1', {{ agentType: 'general-purpose' }}),
  () => agent('fast-2', {{ agentType: 'general-purpose' }}),
])`
const output = await runner.runSource(workflow, {{}})
console.log(JSON.stringify({{ output, maxActive }}))
""")

    assert result == {"output": ["slow", "fast-1", "fast-2"], "maxActive": 2}


def test_pi_runner_timeout_aborts_an_injected_agent() -> None:
    result = run_node(f"""
import {{ createRunner }} from {json.dumps(RUNNER.as_uri())}
let aborted = false
const runner = createRunner({{
  pluginRoot: {json.dumps(str(PLUGIN_ROOT))},
  timeoutMs: 25,
  invokeAgent: ({{ signal }}) => new Promise(resolve => {{
    signal.addEventListener('abort', () => {{ aborted = true; resolve('late') }}, {{ once: true }})
  }}),
  log: () => {{}},
}})
const output = await runner.agent('wait', {{ agentType: 'general-purpose' }})
console.log(JSON.stringify({{ output, aborted }}))
""")

    assert result == {"output": None, "aborted": True}


def test_web_fetch_is_only_mapped_for_webcard_agent() -> None:
    result = run_node(f"""
import {{ createRunner }} from {json.dumps(RUNNER.as_uri())}
const calls = []
const runner = createRunner({{
  pluginRoot: {json.dumps(str(PLUGIN_ROOT))},
  invokeAgent: async call => {{ calls.push([call.definition.name, call.definition.piTools]); return 'ok' }},
  log: () => {{}},
}})
await runner.agent('audit', {{ agentType: 'quasi:audit-agent' }})
await runner.agent('card', {{ agentType: 'quasi:webcard-agent' }})
console.log(JSON.stringify(calls))
""")

    assert result == [
        ["audit-agent", ["read", "edit", "bash"]],
        ["webcard-agent", ["read", "edit", "write", "bash", "web_fetch"]],
    ]


def test_load_keychain_configs_parses_plugin_secrets() -> None:
    result = run_node(f"""
import {{ loadKeychainConfigs }} from {json.dumps(RUNNER.as_uri())}
const blob = JSON.stringify({{
  pluginSecrets: {{
    'quasi@ramu-toolkit': {{
      kagi_session_token: 'secret-token',
      translate_backend: 'pdf2zh',
      translate_base_url: 'https://api.example.com',
    }}
  }}
}})
delete process.env.QUASI_KAGI_SESSION_TOKEN
delete process.env.QUASI_TRANSLATE_BACKEND
await loadKeychainConfigs({{
  readBlob: async () => blob,
  log: () => {{}},
}})
console.log(JSON.stringify({{
  kagi: process.env.QUASI_KAGI_SESSION_TOKEN,
  backend: process.env.QUASI_TRANSLATE_BACKEND,
}}))
""")

    assert result == {
        "kagi": "secret-token",
        "backend": "pdf2zh",
    }


def test_load_keychain_configs_existing_env_wins() -> None:
    result = run_node(f"""
import {{ loadKeychainConfigs }} from {json.dumps(RUNNER.as_uri())}
const blob = JSON.stringify({{
  pluginSecrets: {{ 'quasi@x': {{ kagi_session_token: 'from-keychain' }} }}
}})
process.env.QUASI_KAGI_SESSION_TOKEN = 'from-env'
await loadKeychainConfigs({{
  readBlob: async () => blob,
  log: () => {{}},
}})
console.log(JSON.stringify({{ kagi: process.env.QUASI_KAGI_SESSION_TOKEN }}))
""")

    assert result == {"kagi": "from-env"}


def test_load_keychain_configs_fails_soft_when_no_keychain() -> None:
    result = run_node(f"""
import {{ loadKeychainConfigs }} from {json.dumps(RUNNER.as_uri())}
delete process.env.QUASI_KAGI_SESSION_TOKEN
await loadKeychainConfigs({{
  readBlob: async () => {{ throw new Error('no security binary') }},
  log: () => {{}},
}})
console.log(JSON.stringify({{ kagi: process.env.QUASI_KAGI_SESSION_TOKEN ?? null }}))
""")

    assert result == {"kagi": None}

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOK = PLUGIN_ROOT / "scripts" / "hooks" / "inject-userconfig.py"


def run_hook(command: str, env: dict[str, str]) -> dict:
    payload = {"tool_input": {"command": command}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return json.loads(result.stdout)


def test_hook_does_not_inject_session_token_for_native_kagi_command():
    payload = {"tool_input": {"command": "kagi search --format json 'site:books.com.tw 不受掌控 ISBN'"}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN": "session-token"},
        check=True,
    )

    assert result.stdout == ""


def test_hook_injects_quasi_token_for_quasi_search_kagi_wrapper():
    out = run_hook(
        "quasi-search kagi search --format json 'site:books.com.tw 不受掌控 ISBN'",
        {
            "CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN": "session-token",
            "CLAUDE_PLUGIN_ROOT": "/plugin/root",
            "CLAUDE_PLUGIN_DATA": "/plugin/data",
        },
    )

    updated = out["hookSpecificOutput"]["updatedInput"]["command"]
    assert "QUASI_KAGI_SESSION_TOKEN=session-token" in updated
    assert "quasi-search kagi search --format json" in updated


def test_hook_does_not_inject_session_token_for_chained_native_kagi_command():
    payload = {"tool_input": {"command": "kagi search books; env"}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN": "session-token"},
        check=True,
    )

    assert result.stdout == ""


def test_hook_does_not_inject_session_token_for_embedded_native_kagi_command():
    payload = {"tool_input": {"command": "echo start && kagi search books"}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN": "session-token"},
        check=True,
    )

    assert result.stdout == ""


def test_hook_keeps_quasi_user_config_injection():
    out = run_hook(
        "quasi-search book --title X",
        {
            "CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN": "session-token",
            "CLAUDE_PLUGIN_ROOT": "/plugin/root",
            "CLAUDE_PLUGIN_DATA": "/plugin/data",
        },
    )

    updated = out["hookSpecificOutput"]["updatedInput"]["command"]
    assert "QUASI_KAGI_SESSION_TOKEN=session-token" in updated
    assert "CLAUDE_PLUGIN_ROOT=/plugin/root" in updated
    assert "CLAUDE_PLUGIN_DATA=/plugin/data" in updated


def test_hook_injects_superset_agent_for_superset_agent_creates():
    out = run_hook(
        "superset agents create --workspace \"$SUPERSET_WORKSPACE_ID\" --prompt 'Run /quasi:process-paper' --json --quiet",
        {
            "CLAUDE_PLUGIN_OPTION_SUPERSET_AGENT": "copilot",
            "CLAUDE_PLUGIN_ROOT": "/plugin/root",
            "CLAUDE_PLUGIN_DATA": "/plugin/data",
        },
    )

    updated = out["hookSpecificOutput"]["updatedInput"]["command"]
    assert "QUASI_SUPERSET_AGENT=copilot" in updated
    assert "superset agents create --workspace" in updated


def test_hook_does_not_inject_for_removed_superset_agents_run():
    # `superset agents run` no longer exists in the CLI; the hook must not treat
    # it as a dispatch, so it produces no env-injecting output.
    payload = {"tool_input": {"command": "superset agents run --workspace \"$SUPERSET_WORKSPACE_ID\" --prompt 'Run /quasi:process-paper' --json --quiet"}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={
            "CLAUDE_PLUGIN_OPTION_SUPERSET_AGENT": "copilot",
            "CLAUDE_PLUGIN_ROOT": "/plugin/root",
            "CLAUDE_PLUGIN_DATA": "/plugin/data",
        },
        check=True,
    )

    assert result.stdout == ""


def test_hook_limits_superset_agent_creates_to_superset_agent_config():
    out = run_hook(
        "superset agents create --workspace \"$SUPERSET_WORKSPACE_ID\" --prompt 'Run /quasi:process-paper' --json --quiet",
        {
            "CLAUDE_PLUGIN_OPTION_SUPERSET_AGENT": "copilot",
            "CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN": "session-token",
            "CLAUDE_PLUGIN_ROOT": "/plugin/root",
            "CLAUDE_PLUGIN_DATA": "/plugin/data",
        },
    )

    updated = out["hookSpecificOutput"]["updatedInput"]["command"]
    assert "QUASI_SUPERSET_AGENT=copilot" in updated
    assert "QUASI_KAGI_SESSION_TOKEN" not in updated


def test_hook_limits_superset_agent_creates_even_when_prompt_contains_quasi_command_text():
    out = run_hook(
        "superset agents create --workspace \"$SUPERSET_WORKSPACE_ID\" --prompt 'Run quasi-search and /quasi:process-paper' --json --quiet",
        {
            "CLAUDE_PLUGIN_OPTION_SUPERSET_AGENT": "copilot",
            "CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN": "session-token",
            "CLAUDE_PLUGIN_ROOT": "/plugin/root",
            "CLAUDE_PLUGIN_DATA": "/plugin/data",
        },
    )

    updated = out["hookSpecificOutput"]["updatedInput"]["command"]
    assert "QUASI_SUPERSET_AGENT=copilot" in updated
    assert "QUASI_KAGI_SESSION_TOKEN" not in updated


def test_hook_injects_all_config_for_compound_superset_then_quasi_command():
    out = run_hook(
        "superset agents create --workspace \"$SUPERSET_WORKSPACE_ID\" --json --quiet && quasi-search book --title X",
        {
            "CLAUDE_PLUGIN_OPTION_SUPERSET_AGENT": "copilot",
            "CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN": "session-token",
            "CLAUDE_PLUGIN_ROOT": "/plugin/root",
            "CLAUDE_PLUGIN_DATA": "/plugin/data",
        },
    )

    updated = out["hookSpecificOutput"]["updatedInput"]["command"]
    assert "QUASI_SUPERSET_AGENT=copilot" in updated
    assert "QUASI_KAGI_SESSION_TOKEN=session-token" in updated


def test_hook_ignores_quoted_quasi_command_text_without_target_command():
    payload = {"tool_input": {"command": "echo 'Run quasi-search and superset agents create later'"}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={
            "CLAUDE_PLUGIN_OPTION_SUPERSET_AGENT": "copilot",
            "CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN": "session-token",
        },
        check=True,
    )

    assert result.stdout == ""

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

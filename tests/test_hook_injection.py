from __future__ import annotations

import json
import importlib.util
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


def load_hook_module():
    spec = importlib.util.spec_from_file_location("quasi_inject_userconfig", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hook_reads_quasi_options_from_claude_keychain_blob():
    module = load_hook_module()
    blob = json.dumps(
        {
            "pluginSecrets": {
                "quasi@ramu-toolkit": {
                    "kagi_session_token": "session-token",
                    "cookiecloud_server": "https://cookies.example",
                    "non_string": 42,
                }
            }
        }
    )

    assert module._keychain_options(lambda: blob) == {
        "KAGI_SESSION_TOKEN": "session-token",
        "COOKIECLOUD_SERVER": "https://cookies.example",
    }


def test_hook_existing_quasi_env_is_not_serialised_into_command():
    out = run_hook(
        "quasi-search paper --title X",
        {
            "QUASI_KAGI_SESSION_TOKEN": "from-env",
            "PLUGIN_ROOT": "/codex/plugin",
            "PLUGIN_DATA": "/codex/data",
            "PATH": "/usr/bin:/bin",
        },
    )

    updated = out["hookSpecificOutput"]["updatedInput"]["command"]
    assert "QUASI_KAGI_SESSION_TOKEN=from-env" not in updated
    assert "quasi-search paper --title X" in updated


def test_python_shims_load_keychain_config_themselves():
    shims = [
        "quasi-audit",
        "quasi-doctor",
        "quasi-download",
        "quasi-extract",
        "quasi-helpers",
        "quasi-search",
        "quasi-transcribe",
        "quasi-translate",
    ]

    for name in shims:
        text = (PLUGIN_ROOT / "bin" / name).read_text(encoding="utf-8")
        assert '. "$PLUGIN_ROOT/scripts/load-keychain-env.sh"' in text


def test_hook_does_not_inject_session_token_for_native_kagi_command():
    payload = {
        "tool_input": {
            "command": "kagi search --format json 'site:books.com.tw 不受掌控 ISBN'"
        }
    }
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
    if sys.platform == "darwin":
        assert "--keychain-exports" in updated
        assert "session-token" not in updated
    else:
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
    if sys.platform == "darwin":
        assert "--keychain-exports" in updated
        assert "session-token" not in updated
    else:
        assert "QUASI_KAGI_SESSION_TOKEN=session-token" in updated
    assert "CLAUDE_PLUGIN_ROOT=/plugin/root" in updated
    assert "CLAUDE_PLUGIN_DATA=/plugin/data" in updated


def test_macos_hook_never_serialises_plugin_secret_into_updated_input():
    if sys.platform != "darwin":
        return

    marker = "must-not-appear-in-process-argv"
    out = run_hook(
        "quasi-download paper fetch --doi 10.1/x --slug x --json",
        {
            "CLAUDE_PLUGIN_OPTION_COOKIECLOUD_PASSWORD": marker,
            "CLAUDE_PLUGIN_ROOT": "/plugin/root",
            "CLAUDE_PLUGIN_DATA": "/plugin/data",
            "PATH": "/usr/bin:/bin",
        },
    )

    updated = out["hookSpecificOutput"]["updatedInput"]["command"]
    assert "--keychain-exports" in updated
    assert marker not in updated


def test_hook_uses_codex_plugin_vars_and_adds_plugin_bin_to_path():
    out = run_hook(
        "quasi-codex-runner --args-json '{}'",
        {
            "PLUGIN_ROOT": "/codex/plugin",
            "PLUGIN_DATA": "/codex/data",
            "PATH": "/usr/bin:/bin",
            "CODEX_THREAD_ID": "thread-test",
        },
    )

    updated = out["hookSpecificOutput"]["updatedInput"]["command"]
    assert "--keychain-exports" in updated
    assert "CLAUDE_PLUGIN_ROOT=/codex/plugin" in updated
    assert "CLAUDE_PLUGIN_DATA=/codex/data" in updated
    assert "PATH=/codex/plugin/bin:/usr/bin:/bin" in updated


def test_hook_ignores_quoted_quasi_command_text_without_target_command():
    payload = {"tool_input": {"command": "echo 'Run quasi-search later'"}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={
            "CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN": "session-token",
        },
        check=True,
    )

    assert result.stdout == ""

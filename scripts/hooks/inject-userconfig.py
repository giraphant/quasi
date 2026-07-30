#!/usr/bin/env python3
"""PreToolUse hook for the Bash tool — inject plugin userConfig as env.

Claude Code injects plugin user-config values (set via `/plugin install` /
Configure options) as `CLAUDE_PLUGIN_OPTION_*` env vars into "plugin
subprocesses" — but only into a narrow set: hook / MCP / LSP / monitor
processes. Bash tool subprocesses do NOT get those env vars.

This hook bridges that gap. It runs in the hook subprocess (which does get
the env), inspects the Bash command Claude is about to run, and — for
`quasi-*` commands — prepends a `QUASI_<KEY>='<value>' ...` env prefix to
the command. Other commands pass through untouched.

Net effect: quasi scripts can `os.environ['QUASI_X']` and get the values
the user set at plugin install time, including sensitive ones stored in
the system keychain.

Input/output schema: https://code.claude.com/docs/en/hooks
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

# Keys we propagate. Hook reads CLAUDE_PLUGIN_OPTION_<KEY>, writes
# QUASI_<KEY>. Keep this list in sync with plugin.json's `userConfig`.
_KEYS = [
    "ANNA_DONATOR_KEY",
    "COOKIECLOUD_SERVER",
    "COOKIECLOUD_UUID",
    "COOKIECLOUD_PASSWORD",
    "COOKIECLOUD_EZPROXY_DOMAIN",
    "COOKIECLOUD_EZPROXY_BASE_URL",
    "IMMERSIVE_AUTH_KEY",
    "TRANSLATE_BACKEND",
    "TRANSLATE_BASE_URL",
    "TRANSLATE_API_KEY",
    "TRANSLATE_MODEL",
    "KAGI_SESSION_TOKEN",
    "SONIOX_API_KEY",
]

# Match command words at start of line/string or after shell separators.
# Detection runs against text with quoted spans blanked out, so prompt text like
# `--prompt 'Run quasi-search'` does not trigger broad config injection.
_QUASI_CMD = re.compile(r"(?:^|[\s;&|`(])quasi-")


def _read_keychain_blob() -> str:
    if sys.platform != "darwin":
        return ""
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                "Claude Code-credentials",
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _decode_keychain_payload(blob: str) -> dict:
    """Decode Claude credentials stored as JSON text or Keychain hex bytes."""
    candidates = [blob.strip()]
    encoded = candidates[0]
    if encoded.lower().startswith("0x"):
        encoded = encoded[2:]
    if encoded and len(encoded) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", encoded):
        try:
            candidates.append(bytes.fromhex(encoded).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            pass
    for candidate in candidates:
        try:
            payload = json.loads(candidate or "{}")
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _keychain_options(read_blob=_read_keychain_blob) -> dict[str, str]:
    """Read quasi's Claude plugin config for hosts that cannot inject options."""
    payload = _decode_keychain_payload(read_blob() or "")
    secrets = payload.get("pluginSecrets")
    if not isinstance(secrets, dict):
        return {}
    plugin_key = next(
        (key for key in secrets if isinstance(key, str) and key.startswith("quasi@")),
        None,
    )
    values = secrets.get(plugin_key) if plugin_key else None
    if not isinstance(values, dict):
        return {}
    return {
        str(key).upper(): value
        for key, value in values.items()
        if isinstance(value, str) and value.strip()
    }


def _print_keychain_exports() -> None:
    exports = [
        f"QUASI_{key}={shlex.quote(value)}"
        for key, value in _keychain_options().items()
        if key in _KEYS and not os.environ.get(f"QUASI_{key}")
    ]
    if exports:
        print("export " + " ".join(exports))


def _blank_quoted_spans(cmd: str) -> str:
    chars = list(cmd)
    quote: str | None = None
    escaped = False
    for i, ch in enumerate(chars):
        if escaped:
            if quote:
                chars[i] = " "
            escaped = False
            continue
        if ch == "\\" and quote != "'":
            if quote:
                chars[i] = " "
            escaped = True
            continue
        if quote:
            chars[i] = " "
            if ch == quote:
                quote = None
            continue
        if ch in {"'", '"'}:
            chars[i] = " "
            quote = ch
    return "".join(chars)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    cmd = payload.get("tool_input", {}).get("command", "")
    unquoted_cmd = _blank_quoted_spans(cmd)
    if not cmd or not _QUASI_CMD.search(unquoted_cmd):
        return

    exports: list[str] = []
    prelude: list[str] = []

    # Propagate the plugin path vars too: Bash-tool subprocesses don't inherit
    # CLAUDE_PLUGIN_ROOT / CLAUDE_PLUGIN_DATA either, so the quasi-* shims fall
    # back to `~/.cache/quasi` for the venv and lose the bundled-path fast
    # path. Re-injecting here keeps everything pointing at the official
    # `$CLAUDE_PLUGIN_DATA` (= `~/.claude/plugins/data/<id>/`) location.
    plugin_root = os.environ.get(
        "PLUGIN_ROOT", os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    ).strip()
    plugin_data = os.environ.get(
        "PLUGIN_DATA", os.environ.get("CLAUDE_PLUGIN_DATA", "")
    ).strip()
    plugin_vars = {
        "CLAUDE_PLUGIN_ROOT": plugin_root,
        "CLAUDE_PLUGIN_DATA": plugin_data,
    }
    for plugin_var, val in plugin_vars.items():
        if val:
            exports.append(f"{plugin_var}={shlex.quote(val)}")

    # Claude Code exposes plugin bins directly; Codex deliberately discovers
    # only skills/hooks/MCP. Add quasi's stable shell surface when this hook is
    # already rewriting a quasi-* command, so the same skill text works in both
    # hosts without hard-coding an installed cache path.
    if plugin_root:
        path = os.pathsep.join(
            [os.path.join(plugin_root, "bin"), os.environ.get("PATH", "")]
        )
        exports.append(f"PATH={shlex.quote(path)}")

    host_options = {
        key: os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key}", "").strip()
        for key in _KEYS
    }

    # On macOS Claude, Codex, and Pi all share Claude's encrypted Keychain
    # record. Resolve it inside the Bash process instead of serialising plugin
    # option values into updatedInput: process argv contains only this helper
    # path. Explicit QUASI_* values are ordinary inherited environment and the
    # helper deliberately leaves them untouched.
    use_keychain_helper = sys.platform == "darwin" and (
        bool(os.environ.get("CODEX_THREAD_ID")) or any(host_options.values())
    )
    if use_keychain_helper:
        hook_path = os.path.realpath(__file__)
        prelude.append(
            f'eval "$({shlex.quote(sys.executable)} '
            f'{shlex.quote(hook_path)} --keychain-exports)"'
        )

    # Non-macOS hosts do not have this Keychain bridge yet, so preserve the
    # existing functional fallback there. Explicit QUASI_* values never need
    # command rewriting: Bash inherits them directly.
    if not use_keychain_helper:
        for key, val in host_options.items():
            if val:
                exports.append(f"QUASI_{key}={shlex.quote(val)}")

    if not exports and not prelude:
        return

    # `export VAR=val ...; <cmd>` so the env applies to the entire compound
    # command (including subsequent chains like `&&`, `;`, `|`), not just
    # the first command after the prefix.
    if exports:
        prelude.append("export " + " ".join(exports))
    new_cmd = "; ".join([*prelude, cmd])

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {"command": new_cmd},
        }
    }))


if __name__ == "__main__":
    if sys.argv[1:] == ["--keychain-exports"]:
        _print_keychain_exports()
    else:
        main()

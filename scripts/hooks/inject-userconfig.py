#!/usr/bin/env python3
"""PreToolUse hook for the Bash tool — inject plugin userConfig as env.

Claude Code injects plugin user-config values (set via `/plugin install` /
Configure options) as `CLAUDE_PLUGIN_OPTION_*` env vars into "plugin
subprocesses" — but only into a narrow set: hook / MCP / LSP / monitor
processes. Bash tool subprocesses do NOT get those env vars.

This hook bridges that gap. It runs in the hook subprocess (which does get
the env), inspects the Bash command Claude is about to run, and — for
`quasi-*` commands — prepends a `QUASI_<KEY>='<value>' ...` env prefix to
the command. `superset agents create` dispatches get only the Superset-specific
option. Other commands pass through untouched.

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
    "KAGI_SESSION_TOKEN",
    "SONIOX_API_KEY",
    "SUPERSET_AGENT",
]
_SUPERSET_KEYS = ["SUPERSET_AGENT"]

# Match command words at start of line/string or after shell separators.
# Detection runs against text with quoted spans blanked out, so prompt text like
# `--prompt 'Run quasi-search'` does not trigger broad config injection.
_QUASI_CMD = re.compile(r"(?:^|[\s;&|`(])quasi-")
# Current Superset CLI exposes `agents create` (and `agents list`); there is no
# `agents run`. Dispatches go through `agents create`, so that is what we inject
# QUASI_SUPERSET_AGENT for.
_SUPERSET_AGENTS_CREATE = re.compile(r"(?:^|[\s;&|`(])superset\s+agents\s+create(?:$|[\s;&|`)])")


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
    is_quasi = bool(_QUASI_CMD.search(unquoted_cmd))
    is_superset_agents_create = bool(_SUPERSET_AGENTS_CREATE.search(unquoted_cmd))
    if not cmd or not (is_quasi or is_superset_agents_create):
        return

    keys = _KEYS if is_quasi else _SUPERSET_KEYS
    exports: list[str] = []

    # Propagate the plugin path vars too: Bash-tool subprocesses don't inherit
    # CLAUDE_PLUGIN_ROOT / CLAUDE_PLUGIN_DATA either, so the qua-* shims fall
    # back to `~/.cache/quasi` for the venv and lose the bundled-path fast
    # path. Re-injecting here keeps everything pointing at the official
    # `$CLAUDE_PLUGIN_DATA` (= `~/.claude/plugins/data/<id>/`) location.
    for plugin_var in ("CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA"):
        val = os.environ.get(plugin_var, "").strip()
        if val:
            exports.append(f"{plugin_var}={shlex.quote(val)}")

    for key in keys:
        val = os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key}", "").strip()
        if val:
            exports.append(f"QUASI_{key}={shlex.quote(val)}")

    if not exports:
        return

    # `export VAR=val ...; <cmd>` so the env applies to the entire compound
    # command (including subsequent chains like `&&`, `;`, `|`), not just
    # the first command after the prefix.
    new_cmd = "export " + " ".join(exports) + "; " + cmd

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {"command": new_cmd},
        }
    }))


if __name__ == "__main__":
    main()

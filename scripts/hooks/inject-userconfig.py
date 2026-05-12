#!/usr/bin/env python3
"""PreToolUse hook for the Bash tool — inject plugin userConfig as env.

Claude Code injects plugin user-config values (set via `/plugin install` /
Configure options) as `CLAUDE_PLUGIN_OPTION_*` env vars into "plugin
subprocesses" — but only into a narrow set: hook / MCP / LSP / monitor
processes. Bash tool subprocesses do NOT get those env vars.

This hook bridges that gap. It runs in the hook subprocess (which does get
the env), inspects the Bash command Claude is about to run, and — for
`quasi-*` commands only — prepends a `QUASI_<KEY>='<value>' ...` env
prefix to the command. Non-quasi commands pass through untouched.

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
    "ANNA_MIRRORS",
    "COOKIECLOUD_SERVER",
    "COOKIECLOUD_UUID",
    "COOKIECLOUD_PASSWORD",
    "COOKIECLOUD_EZPROXY_DOMAIN",
    "COOKIECLOUD_LOGIN_URL",
    "IMMERSIVE_AUTH_KEY",
]

# Match `quasi-` as a bare command word: at start of line/string or after
# a shell separator (whitespace, ;, &, |, &&, ||, etc.). Avoids matching
# substrings inside paths or quoted strings.
_QUASI_CMD = re.compile(r"(?:^|[\s;&|`(])quasi-")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    cmd = payload.get("tool_input", {}).get("command", "")
    if not cmd or not _QUASI_CMD.search(cmd):
        return

    exports: list[str] = []
    for key in _KEYS:
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

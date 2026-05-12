# quasi maintenance notes

This file applies to the `plugins/quasi/` subtree.

## Claude Code plugin layout

- Keep plugin components at the plugin root: `skills/`, `agents/`, `bin/`, `hooks/`, `monitors/`, `.mcp.json`, `.lsp.json`.
- Only the manifest belongs under `.claude-plugin/plugin.json`.
- Do not assume a plugin-root `CLAUDE.md` is loaded when the plugin is installed. Plugin runtime guidance must live in skills, agents, hooks, or scripts.

## Version discipline

- Keep `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` versions in sync.
- `plugin.json` wins when both define a version; a stale marketplace version is ignored at install/update time and causes `claude plugin validate` warnings.
- After bumping a version, run `claude plugin validate plugins/quasi` from the repository root before considering the release ready.
- Prefer `claude plugin tag plugins/quasi` for release tagging so version mismatches are caught automatically.

## Runtime state and dependencies

- `bin/` tools may be invoked as bare commands while the plugin is enabled.
- Persistent generated state, virtualenvs, caches, and downloaded dependencies should use `CLAUDE_PLUGIN_DATA` rather than writing into `CLAUDE_PLUGIN_ROOT`.
- Treat `CLAUDE_PLUGIN_ROOT` as versioned and ephemeral; use it only to read bundled scripts, schemas, and static assets.

## Python dependencies

- Declared in `scripts/requirements.txt`. Edit there to add/remove deps.
- Installed into a shared venv at `$CLAUDE_PLUGIN_DATA/.venv` (fallback `~/.cache/quasi/.venv`) by `scripts/bootstrap-venv.sh`.
- Bootstrap fires automatically via `hooks/hooks.json` (`SessionStart`); each shim also self-bootstraps if the venv is missing, so bare invocation still works.
- Do **not** put pip installs back inside individual shims — that pattern was removed in 0.11.0.

## Verification

- For manifest or marketplace changes, run `claude plugin validate plugins/quasi`.
- For component inventory/token-cost changes, run `claude plugin details quasi` after reinstalling/updating the local plugin if needed.

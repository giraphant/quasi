# quasi maintainer guide

quasi is a Claude Code plugin for academic reading workflows: discovery, download, extraction, analysis, synthesis, translation, and schema checking.

## Important plugin-system facts

- Installed plugins load components from root-level `skills/`, `agents/`, `bin/`, `hooks/`, `monitors/`, `.mcp.json`, and `.lsp.json`.
- `.claude-plugin/plugin.json` is metadata only. Do not place components inside `.claude-plugin/`.
- This `CLAUDE.md` helps humans and Claude Code sessions opened inside the quasi source tree, but Claude Code does not load a plugin-root `CLAUDE.md` as context when quasi is installed as a plugin.

## Release checklist

1. Update `.claude-plugin/plugin.json`.
2. Mirror the same version in `.claude-plugin/marketplace.json`.
3. Run:
   ```bash
   claude plugin validate plugins/quasi
   ```
4. If publishing a release tag, prefer:
   ```bash
   claude plugin tag plugins/quasi
   ```

The version in `plugin.json` takes precedence over marketplace entry versions. If these drift, installation still works but validation warns and users can see confusing version information.

## Runtime state

- `CLAUDE_PLUGIN_ROOT` is for reading bundled code and assets only.
- `CLAUDE_PLUGIN_DATA` is for persistent virtualenvs, caches, generated files, and installed dependencies.
- Avoid writing dependency state into the plugin root; installed plugin roots are versioned and may change across updates.

## Python venv bootstrap (since 0.11.0)

Python dependencies are declared in `scripts/requirements.txt` and installed into a
shared venv at `${CLAUDE_PLUGIN_DATA}/.venv` (falls back to `~/.cache/quasi/.venv`
when run outside a plugin context).

Bootstrap is handled by `scripts/bootstrap-venv.sh`, wired to the `SessionStart`
hook in `hooks/hooks.json`. It diffs the bundled `requirements.txt` against the
copy in `$DATA_DIR/requirements.txt` and only reinstalls on change. Each `bin/qua-*`
shim resolves `$DATA_DIR/.venv/bin/python` and falls back to running bootstrap if
the venv is missing — so shims work even when SessionStart hasn't fired yet
(bare invocation, fresh install).

To bump deps: edit `scripts/requirements.txt`, ship. Next session picks up the diff.

## Recent Changes

- **0.13.0** (2026-05-12): **Breaking.** EZProxy credentials moved from
  `config/*.json` project files to plugin `userConfig` (`.claude-plugin/plugin.json`).
  `/plugin install quasi` now prompts for `cookiecloud_server/uuid/password/
  ezproxy_domain/login_url` once; sensitive `password` lands in the system keychain
  rather than a plaintext file. `download.py` no longer reads
  `config/cookiecloud.json` *or* `config/ezproxy.json` — cookies are pulled fresh
  from the CookieCloud server on each process start and cached in memory. Manual
  cookie-pasting fallback is gone. `setup-agent` no longer handles EZProxy at all.
- **0.12.1** (2026-05-12): Drop `setup-agent` Step 0 (plugin self-install bootstrap).
  Installation is now the canonical `/plugin marketplace add giraphant/quasi` +
  `/plugin install quasi@ramu-toolkit` flow; `setup-agent` is purely env + creds.
  README install section rewritten to match.
- **0.12.0** (2026-05-12): CookieCloud auto-refresh for EZProxy. Initial `config/
  cookiecloud.json` + `config/ezproxy.json` file-based flow — superseded by 0.13.0.
- **0.11.0** (2026-05-12): Python venv extracted from per-shim inline pip into a
  `SessionStart` hook + bootstrap script. Shims now ~half the size. Persistent venv
  lives in `$CLAUDE_PLUGIN_DATA` (or `~/.cache/quasi/`), never in plugin root.
- **0.10.0**: SPEC v0.2 schema + typecheck-agent + bin shims.
- **0.9.0**: Unified setup-agent (bootstrap + config).

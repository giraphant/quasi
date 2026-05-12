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
copy in `$DATA_DIR/requirements.txt` and only reinstalls on change. Each `bin/quasi-*`
shim resolves `$DATA_DIR/.venv/bin/python` and falls back to running bootstrap if
the venv is missing — so shims work even when SessionStart hasn't fired yet
(bare invocation, fresh install).

To bump deps: edit `scripts/requirements.txt`, ship. Next session picks up the diff.

## Recent Changes

- **0.15.0** (2026-05-12): **Breaking.** Final config resolution: PreToolUse hook
  bridge. The docs claim `CLAUDE_PLUGIN_OPTION_*` env vars reach "plugin
  subprocesses" but empirically Bash-tool subprocesses don't get them — only
  hooks/MCP/LSP/monitor do. Solution: a PreToolUse(Bash) hook
  (`scripts/hooks/inject-userconfig.py`) runs in a real plugin subprocess, reads
  its env, and prepends `export QUASI_<KEY>=...; ` to any `quasi-*` shell
  command before Claude Code executes it. Scripts read clean `QUASI_*` env
  vars. Sensitive userConfig fields stay in the macOS keychain — they only
  materialise in the hook+bash process env for one tool call at a time. Also
  renames all `bin/qua-*` shims to `bin/quasi-*`. Probe agent removed.
- **0.14.1–0.14.3** (2026-05-12): Diagnostic releases — probe agents and probe
  hooks to map out which subprocess types actually receive `CLAUDE_PLUGIN_OPTION_*`
  env injection. Results: only the 4 documented types (hook/MCP/LSP/monitor) do;
  Bash-tool subprocesses and Task-tool subagents do not. Drove the 0.15.0 design.
- **0.14.0** (2026-05-12): **Breaking.** Anna's Archive and Immersive Translate
  credentials follow CookieCloud into plugin `userConfig`. New userConfig fields:
  `anna_donator_key` (sensitive), `anna_mirrors` (multiple, defaults to 3 official
  mirrors), `immersive_auth_key` (sensitive). `download.py` / `search.py` /
  `immersive_translate.py` no longer read `config/anna-archive.json` or
  `config/immersive-translate.json` — fully env-var driven. `setup-agent` becomes
  purely permissions + system deps + dokobot indicator; the entire `$PWD/config/`
  directory is now optional and quasi never writes there.
- **0.13.0** (2026-05-12): EZProxy creds moved to `userConfig` (CookieCloud).
  Removed `config/cookiecloud.json` and `config/ezproxy.json` reading.
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

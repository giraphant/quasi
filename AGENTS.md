# quasi maintainer guide

quasi is a Claude Code plugin for academic reading workflows: discovery, download, extraction, analysis, synthesis, translation, and schema checking.

## Important plugin-system facts

- Installed plugins load components from root-level `skills/`, `agents/`, `bin/`, `hooks/`, `monitors/`, `.mcp.json`, and `.lsp.json`.
- `.claude-plugin/plugin.json` is metadata only. Do not place components inside `.claude-plugin/`.
- `CLAUDE.md` and `AGENTS.md` must stay byte-for-byte identical. They are mirrored instruction files for different agent frameworks, not separate reader-specific guides.
- Claude Code does not load a plugin-root `CLAUDE.md` as context when quasi is installed as a plugin. Runtime guidance must live in skills, agents, hooks, or scripts.

## Current runtime contract

### Layer ownership

- `skills/` own user-facing workflow state machines: input normalisation, manifests, skip rules, human gates, and dispatch order.
- `agents/` are specialist workers. They call only the public `quasi-*` CLI or read/write the exact local artifact named in their contract.
- `bin/quasi-*` is the stable shell surface exposed to agents and skills.
- `scripts/` contains deterministic capability entrypoints.
- `scripts/schemas/` is for deterministic validation/migration code, not an agent-facing API.
- `core/` is the minimal runtime base for path/frontmatter/json/module-loading helpers.

### Path roots

- `$CLAUDE_PROJECT_DIR` is the project/vault root for user data. Active skills and agents should resolve relative user paths from it.
- `$CLAUDE_PLUGIN_ROOT` is versioned plugin code and should be read-only at runtime.
- `$CLAUDE_PLUGIN_DATA` is persistent plugin data: venvs, caches, generated dependency state, and EZProxy throttle state.
- `${CLAUDE_PLUGIN_DATA:-~/.cache/quasi}` is the non-plugin fallback data dir used by shims and bootstrap.
- `QUA_PROJECT_ROOT` is a legacy/local script override still accepted by some migration code; do not introduce it into active skill or agent contracts.
- `vault/` holds user-facing reading outputs.
- `sources/` holds accepted source files.
- `processing/chapters/`, `processing/translations/`, and `processing/talks/` (per-engine talk transcripts) hold user-inspectable intermediates.
- `.quasi/` holds orchestration state, manifests, caches, proofread/citation state, audit output, localise cache, and temp downloads.

### Configure option and env flow

- User-facing plugin options live in `.claude-plugin/plugin.json#userConfig`.
- Hook propagation keys live in `scripts/hooks/inject-userconfig.py::_KEYS` and must stay in sync with `plugin.json`.
- Claude Code injects configured values into hook/MCP/LSP/monitor subprocesses as `CLAUDE_PLUGIN_OPTION_<KEY>`.
- Bash tool subprocesses do not receive those variables directly.
- `hooks/hooks.json` registers a `PreToolUse` Bash hook that runs `scripts/hooks/inject-userconfig.py`.
- For commands containing a bare `quasi-` word, the hook prepends `export ...;` with `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, and each configured `QUASI_<KEY>`.
- Scripts read only `QUASI_*` service variables, not `CLAUDE_PLUGIN_OPTION_*`.
- Kagi is special only at the subprocess edge: quasi reads `QUASI_KAGI_SESSION_TOKEN` and maps it to `KAGI_SESSION_TOKEN` for `kagi` CLI calls.
- Do not document a Configure option as current unless it exists in `plugin.json#userConfig` and is forwarded by `_KEYS`.

Current userConfig mapping:

| Configure field | Hook env input | Script env output | Main consumer |
|---|---|---|---|
| `anna_donator_key` | `CLAUDE_PLUGIN_OPTION_ANNA_DONATOR_KEY` | `QUASI_ANNA_DONATOR_KEY` | `scripts/download/aa.py` |
| `cookiecloud_server` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_SERVER` | `QUASI_COOKIECLOUD_SERVER` | `scripts/download/cookiecloud.py` |
| `cookiecloud_uuid` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_UUID` | `QUASI_COOKIECLOUD_UUID` | `scripts/download/cookiecloud.py` |
| `cookiecloud_password` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_PASSWORD` | `QUASI_COOKIECLOUD_PASSWORD` | `scripts/download/cookiecloud.py` |
| `cookiecloud_ezproxy_domain` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_EZPROXY_DOMAIN` | `QUASI_COOKIECLOUD_EZPROXY_DOMAIN` | `scripts/download/cookiecloud.py` |
| `cookiecloud_ezproxy_base_url` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_EZPROXY_BASE_URL` | `QUASI_COOKIECLOUD_EZPROXY_BASE_URL` | `scripts/download/cookiecloud.py` |
| `immersive_auth_key` | `CLAUDE_PLUGIN_OPTION_IMMERSIVE_AUTH_KEY` | `QUASI_IMMERSIVE_AUTH_KEY` | `scripts/translate/immersive_translate.py` |
| `kagi_session_token` | `CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN` | `QUASI_KAGI_SESSION_TOKEN` | `scripts/search/search.py`, `scripts/search/sources/douban_cn.py`, `scripts/download/download.py` |
| `soniox_api_key` | `CLAUDE_PLUGIN_OPTION_SONIOX_API_KEY` | `QUASI_SONIOX_API_KEY` | `scripts/transcribe/engines.py` |

### State and handoff contracts

- The skill main process owns workflow state files: manifests, decisions, search caches, recovery files, and `.quasi/<domain>/...` orchestration artifacts.
- `search-agent` returns JSON and does not write files.
- `download-agent` accepts or rejects candidates through `quasi-download`; it returns `DOWNLOAD_RESULT.per_item` and does not own caller manifests.
- `extract-agent` writes chapter extraction output and `processing/chapters/{slug}/manifest.json`.
- `analyse-agent`, `synthesis-agent`, `proofread-agent`, and `citecheck-agent` write only the exact product path assigned by the caller.
- `audit-agent` runs `quasi-audit --path`; it may apply local mechanical fixes but does not own workflow state.
- A deterministic CLI may write an artifact only when its command contract names that output path.
- Pseudocode helpers in skill files (`parse_args`, `read_json`, `write_json`, `write_temp_json`, `format_yaml_list`, `exists`, `Agent(...).result`) are maintainer shorthand for main-process Claude Code actions, not a hidden runtime library.
- Temp JSON passed to helpers should live under `.quasi/temp/` unless a specific helper contract says otherwise.

### Active CLI surface

```bash
quasi-search book|paper ...
quasi-download book candidates|fetch ...
quasi-download paper fetch ...
quasi-download accept ...
quasi-extract epub|ocr|split ...
quasi-transcribe run|classify|silent ...
quasi-audit --path ...
quasi-helpers proofread prepare|cleanup ...
quasi-helpers citation parse|biblio|resolve|review-cards|emit-bib ...
quasi-helpers localise scan|write ...
quasi-helpers vault resolve --items-json|--items-file ...
quasi-doctor [--json] [--sync] [--profile ...]
quasi-translate ...
```

`quasi-extract ocr` defaults to **DS OCR2** (DeepSeek-OCR-2 via `mlx-vlm`, Apple Silicon). The engine pins **mlx-vlm==0.3.12** — 0.4+ bumped its transformers dependency to 5.x, which breaks this model's loader and generate path; 0.3.12 is the last version that runs DeepSeek-OCR-2 end-to-end. It also pulls torch/torchvision/addict/einops/matplotlib/tqdm (the model's remote-code imports), all via uvx — NOT in `requirements.txt`. OCR auto-falls-back to tesseract if uvx, the model (`QUASI_DSOCR2_MODEL`, a local BF16 dir or HF repo id), or Apple Silicon is missing; `--engine tesseract` forces tesseract. The DS OCR2 path writes a text-layer PDF (one page per input page) so the existing `split` flow is unchanged.

Removed legacy bins must not reappear in active docs or prompts: `quasi-citation`, `quasi-proofread`, and `quasi-download batch`.

## Skill writing schema

`docs/SKILL_ORCHESTRATION.md` is maintainer guidance. Active `SKILL.md` files should not cite it directly; runtime skill text should contain only information the executing model needs.

Use this shape for active skills when applicable:

```text
任务
输入
硬约束
状态
Agent / Helper 合同
工作流
执行流程
断点续跑
输出
```

`任务` should be one short positive sentence naming the work. Use `输入` instead of `调用方式` unless the skill has a real machine-facing invocation API. In normal plugin use, the frontmatter description and natural language trigger the skill; the body should define variable extraction and workflow contracts.

Frontmatter `description` is only a routing hint. Skill descriptions should describe user intent; agent descriptions should describe one worker action and its main output. Do not put trigger-word lists, history notes, or phase walkthroughs in descriptions.

## Runtime state and dependencies

- `bin/` tools may be invoked as bare commands while the plugin is enabled.
- Python dependencies are declared in `scripts/requirements.txt`.
- `scripts/bootstrap-venv.sh` installs them into `${CLAUDE_PLUGIN_DATA}/.venv`, falling back to `~/.cache/quasi/.venv` outside plugin context.
- Bootstrap runs from `hooks/hooks.json` on `SessionStart`; each shim also self-bootstraps if the venv is missing.
- Optional out-of-venv deps (fail-soft, like the transcribe engines): `ffmpeg`/`whisper-cli`/`uvx` for transcription, `mlx-vlm` for DS OCR2 OCR.
- Do not put pip installs back inside individual shims.
- EZProxy global throttle state lives under `${CLAUDE_PLUGIN_DATA:-~/.cache/quasi}/ezproxy-throttle.state` and is owned by `scripts/download/download.py`.

## Change checklist

When changing config, runtime state, or handoff contracts:

1. Keep `.claude-plugin/plugin.json` and `scripts/hooks/inject-userconfig.py::_KEYS` in sync.
2. Keep `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` versions in sync for releases.
3. Keep `CLAUDE.md` and `AGENTS.md` byte-for-byte identical.
4. Update active skills only when the executing model needs the information at runtime.
5. Update agent files when an agent input/output contract changes.
6. Update tests that guard dead names, frontmatter routing hints, CLI surface, or manifest schema.
7. Run `claude plugin validate plugins/quasi` after manifest/marketplace changes.

## Verification

- For instruction-only changes, run `cmp -s plugins/quasi/CLAUDE.md plugins/quasi/AGENTS.md` and confirm exit code 0.
- Run `pytest plugins/quasi/tests/test_dead_names.py plugins/quasi/tests/test_skill_orchestration.py -q` if those tests exist in the current checkout.
- For manifest or marketplace changes, run `claude plugin validate plugins/quasi`.

## Debugging gotchas

- `$CLAUDE_PROJECT_DIR` is fixed at session start; a `cd` inside a dispatched worker's *prompt* does not redirect where the orchestration graph writes. Dispatch E2E workers with the correct cwd; never rely on an in-prompt `cd`.
- A dead Workflow subagent writes no `result` line in `journal.jsonl` — its key stays `started`-only forever, and a retry shows up as a *new* started+result pair. Count `started` vs `result` keys to find deaths; do not look for `result: null`.
- `agent()` returns `null` when a subagent dies on a terminal API error after retries. `orchestrate.mjs::retryNull` pays exactly one retry per null, because a `null` cannot distinguish a deterministic failure from a transient one.
- A run that looks hung is usually harness backoff, not deadlock. A dying subagent's transcript ends in a synthetic `API Error: …` assistant message, but the harness can sit in invisible retry backoff for 20–40 minutes before `agent()` finally sees `null` — no result line, no progress, nothing a script can observe or shorten. Before declaring a run dead, check each no-result agent's transcript mtime: still advancing = live agent (a `0 tok` display can just be a slow provider), stale with an API-error tail = a death still waiting to be reported. The only shortcut is killing the run and re-invoking with `resumeFromRunId`.

## Changelog

Full version history lives in `docs/CHANGELOG.md` (newest first, entries carry the why as well as the what). Current version: 0.49.1.

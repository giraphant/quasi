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
- For commands containing a bare `quasi-` word, the hook prepends `export ...;` with `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, and each configured `QUASI_<KEY>`; for `superset agents create`, it prepends only the configured `QUASI_SUPERSET_AGENT`. (There is no `superset agents run` in the current CLI; dispatch is `agents create`.)
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
| `superset_agent` | `CLAUDE_PLUGIN_OPTION_SUPERSET_AGENT` | `QUASI_SUPERSET_AGENT` | `skills/process-topic/SKILL.md` |

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
quasi-doctor [--json] [--sync] [--profile ...]
quasi-translate ...
```

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

## Recent Changes

- **0.41.2** (2026-06-19): **Anna's Archive mirror discovery hardens against domain and TLS churn.**
  - `scripts/download/aa.py` now treats the current official domains as a static
    first tier (`annas-archive.pk`, `.gd`, `.gl`) and falls back to the
    Wikipedia infobox URL list when all static mirrors fail. The dynamic list is
    cached under `${CLAUDE_PLUGIN_DATA:-~/.cache/quasi}/aa-mirrors.json` for 90
    days so normal runs stay deterministic and do not depend on Wikipedia.
  - AA HTML search, Fast Download API calls, and AA file streams use the shared
    AA HTTP helper, which prefers `curl_cffi`'s Chrome TLS impersonation. This
    avoids macOS system-Python LibreSSL failures observed against the 2026 AA
    mirrors before HTTP starts.
  - Legacy AA metadata sweep defaults are reordered to match the current static
    mirror list, and `test_download_cli.py` guards both the official-domain list
    and the Wikipedia recovery parser. No schema-contract change.

- **0.41.1** (2026-06-14): **process-talk gains local single-recording media
  compression.**
  - New `quasi-helpers talk compress-media --media F --output O` wraps a small
    deterministic `ffmpeg`/`libx265` helper for one talk recording at a time,
    matching the normal process-talk flow where the source recording often
    lives outside `vault/talks`.
  - `quasi:process-talk` now compresses video inputs locally to
    `vault/talks/{slug}/recording.mp4` before transcription and then uses that
    path for the rest of the workflow. Audio-only inputs skip compression.
  - No schema-contract change; plugin manifest / marketplace versions are
    bumped to `0.41.1`.

- **0.41.0** (2026-06-11): **image schema gains descriptive metadata fields (schema contract 0.6.0 → 0.7.0).**
  - `ImageSchema` now accepts optional `creator`, `date`, `source`, `themes`,
    `topics`, and `rating` alongside the existing required `type` / `title`, so
    local image objects can carry human-curated descriptive metadata without
    overloading the body.
  - Technical image facts (width, height, format, file size) remain explicitly
    path/indexer-derived from `vault/images/<slug>/original.<ext>` and must not
    be persisted in frontmatter (QUA-175).
  - `SPEC.md` §3.8 documents the expanded frontmatter shape and the plugin
    manifest / marketplace versions are bumped to `0.41.0`.

- **0.40.1** (2026-06-09): **punctuation autofix guards `!`/`?` inside Latin
  names.** A 5-agent adversarial review of the 0.40.0 dry-run over the live
  16.9k-file vault confirmed colons, commas, semicolons, parens, and masking
  (code/inline-code/links/wikilinks/frontmatter/`$…$` math) all clean — zero
  false positives (one reviewer independently reimplemented the masking and
  reproduced the change set exactly). It surfaced **one real bug class**: a
  proper noun whose spelling ends in `!`/`?` glued onto Han text
  (`Yahoo!目录`, `Spacewar!`, `Earth First!`, `Dans le Noir?黑暗餐厅`) had its
  mark "corrected" to full-width — 33 such corruptions across the vault.
  - Fix: `_is_ascii_alpha` guard in `_punctuation_replacements` — for `!`/`?`
    (`LATIN_TOKEN_PUNCT`), skip when an ASCII letter sits immediately before the
    mark and CJK immediately after (Latin-token-then-mark-then-CJK = the name
    pattern). The mirror direction (CJK-then-mark-then-Latin) is deliberately
    NOT guarded: `…会发生什么变化?Baldwin…` is a Chinese question whose next
    sentence merely starts with a Latin name — a sentence boundary, not a name.
    The first patch guarded both directions and wrongly killed ~19 such
    legitimate questions; re-running the dry-run caught it, and the guard was
    narrowed to one direction. Known residual: the `!Kung` click consonant
    (1 occurrence) still converts — accepted over re-killing real questions.
  - Two nested-paren cases (`(它们是世界的物质(再)配置)`) convert the inner CJK
    pair but leave the outer half-width — cosmetic incomplete conversion, not
    corruption; left as a known limitation.
  - `test_audit_punctuation_style_makes_cjk_halfwidth_full_width` extended with
    `Yahoo!目录` / `Spacewar!` / `Dans le Noir?` (unchanged) and a real Chinese
    question before a Latin name (still converts). Full suite 117 pass.
  - No schema-contract change. Vault not yet swept.

- **0.40.0** (2026-06-09): **audit gains a CJK half-width→full-width
  punctuation autofix pass.** Mirrors the existing quote-style pass in
  `scripts/audit/audit.py`: a new `_run_punctuation_autofix` runs right after
  `_run_quote_style_autofix`, over the same `_mask_markdown_non_body` /
  `_split_frontmatter_text` machinery, so code fences, inline code, link
  targets, `[[wikilink]]`, and frontmatter are never touched.
  - **Scope** (`CJK_PUNCT_INLINE` + `PAREN_PAIR_RE`): inline `, : ; ! ?` →
    `，：；！？` convert only when a CJK char sits immediately on either side;
    parentheses convert as a pair (`(…)` → `（…）`) only when the content
    contains CJK. Each replacement is one-char-for-one-char, so body offsets
    stay stable and before/after sentence contexts are read by index.
    Diagnostics: `id: punctuation.cjk_halfwidth`, `pass: punctuation_style`,
    `status: auto_fixed`, `action: none`; counted under
    `fix_counts.punctuation_style`.
  - **Period (`.`) deliberately excluded.** A read-only dry-run over the live
    16.9k-file vault produced 108,239 changes across 5,438 files with zero
    false positives on the inline+paren set — digit-flanked colons
    (`ISO 9000:1987`, `6:54`, `Foucault 2008:63`), English/digit-only parens
    (`(relational model)`, `(2011-12 IPO)`, `(1)`), and masked code/links all
    correctly preserved. The only `.→。` hits (58) were bibliography
    line-endings (`*活力物质*. 西北大学出版社.`), where converting the terminal
    dot but not the title-separator dot makes the entry mix `. … 。`. So the
    period rule is omitted entirely.
  - `agents/audit-agent.md` core-principle line extended to name CJK
    punctuation alongside quote style as body-only typography.
  - Tests: `test_audit_cli.py::test_audit_punctuation_style_makes_cjk_halfwidth_full_width`
    asserts the positive conversions plus the must-not-touch cases
    (digit-flanked colon, English-only parens, inline-code/link masking, no
    period rewrite). Full suite 117 pass.
  - No schema-contract change.

- **0.39.1** (2026-06-08): **process-topic delegated prompts explicitly forbid branch/worktree switching.**
  - Every `superset agents create --prompt` example in `skills/process-topic/SKILL.md`
    now begins with the vault/content-processing preface: this is not a software
    development task; do not create, enter, or switch git branches/worktrees; do
    not run `git worktree`, `git switch`, or `git checkout`; if isolation seems
    necessary, stop and report cwd + branch instead. This prevents delegated
    process-paper/book/author/synthesis/audit agents from misrouting content work
    into development-branch completion flows.
  - The old live maintainer smoke script under `skills/process-topic/` is removed
    from the active skill tree; the runtime contract is now guarded by
    `test_skill_orchestration.py` instead.
  - No schema-contract change; instruction/test-only release.

- **0.39.0** (2026-06-06): **process-topic Superset dispatch moves from the
  removed `agents run` to `agents create`, plus prompt-file transport,
  completion sentinels, and update-safe completion polling (QUA-187).**
  - Current Superset CLI (0.2.x) exposes only `agents create` / `agents list`
    (and `terminals create`); there is **no `agents run`** (it errors
    `Unknown command: run`) and **no transcript/status/logs/result** command
    for a session. `agents create` is fire-and-forget — it returns only a
    `sessionId`. So completion can only be judged from vault artifacts, never
    by querying the session. All of this is now documented as a hard
    constraint in `skills/process-topic/SKILL.md`.
  - **Dispatch verb**: every `superset agents run` template/example in
    `process-topic` is now `superset agents create`. The `--agent
    "${QUASI_SUPERSET_AGENT:-copilot}"` contract is unchanged.
  - **Hook**: `scripts/hooks/inject-userconfig.py` now matches `superset
    agents create` (regex `_SUPERSET_AGENTS_CREATE`) to inject only
    `QUASI_SUPERSET_AGENT`; it no longer matches the dead `agents run`.
    `test_hook_injection.py` updated (create-form injection + a guard that
    the removed `agents run` form gets no injection). The active-contract
    line in this file / `AGENTS.md` updated accordingly.
  - **Prompt-file transport**: long synthesis/audit/refine prompts no longer
    go through argv (copilot is `promptTransport: argv`; long Chinese prompts
    with quotes/numbered sections are fragile there). The skill writes a task
    file `.quasi/process-topic-runs/{slug}.prompt.md` and dispatches a short
    `Read … and perform it exactly` prompt. `--attachment` is a confirmed
    alternative (Superset uploads the file and injects an `# Attached files`
    absolute path into the prompt); prompt-file is preferred for being
    deterministic.
  - **Completion sentinels + poll modes**: poll-agent now supports `exists`
    (first-time generation), `mtime_changed` (overwrite/update), and
    `sentinel` (agent writes `.quasi/process-topic-runs/{run_id}.json`).
    Update/refine completion requires **sentinel AND mtime change** — a
    sentinel can land a beat before the file flush, and a sentinel alone does
    not prove the target actually changed.
  - **Refine mode + `final_status` state machine**: manifest gains `mode`
    (`generate` | `refine`) and `final_status`
    (`missing`/`generated`/`needs_update`/`updated`). FINAL is skipped only
    when `final_status ∈ {generated, updated}` — an explicit refine/update
    request is **not** skipped just because `00-overview.md` already exists.
  - **Smoke test**: `skills/process-topic/smoke-dispatch.sh` (live,
    maintainer-run, not CI) proves `agents create` creates a file and that
    prompt-file dispatch updates an existing file with sentinel+mtime
    detection. Validated live: both pass in ~15s on a real-backend agent
    preset. Note: the configured `copilot` preset routes through a local
    model proxy (`monster.json` → `ANTHROPIC_BASE_URL`); when that backend
    stalls, sessions are created but never produce output and there is no
    transcript to inspect — the skill detects this via poll timeout (the
    QUA-187 reproduction's "20 minutes, no change" was this backend stall,
    not a Superset/mechanism fault).
  - No schema-contract change; no Python script changes beyond the hook.

- **0.38.2** (2026-06-06): **extract-agent 阶段 2 prompt trimmed to instructions
  only.** The 0.38.1 prompt carried maintainer-facing rationale (why it used to
  stick, root cause, the "绝不整章通读" prohibition) inside the agent's runtime
  instructions — but the agent only ever receives the head+tail digest, so the
  prohibition is moot and the history is noise. Rewritten to four action steps:
  read `manifest.json` (empty → OCR; >100 → re-split), run the head/tail digest
  command and read its output, eyeball each chapter for truncation / boundary
  mis-cut / garble (Read a single chapter only if unsure), pass. No behaviour
  change; the "why" stays here in the changelog where maintainers read it.

- **0.38.1** (2026-06-06): **extract-agent validation no longer floods its own
  context (QUA-186).** The agent "经常卡住" because its 阶段 2 验证 read head+tail
  (~100+100 lines) *and* `wc -l`'d **every** chapter file — a 40-chapter book dumped
  ~8,000 lines (≈120–160k tokens) into the sonnet subagent, which then slowed,
  looped, or ran out of context.
  - Full per-chapter coverage is **kept** (sampling was rejected: an isolated
    mid-book boundary mis-cut — e.g. between ch5/ch6 — is only catchable by looking
    at every chapter; and OCR'd chapter-start formatting is too unstable for a
    script to judge heading presence, so truncation/garble judgment stays with the
    agent's eye). The fix is **volume per chapter**, not coverage.
  - `agents/extract-agent.md` 阶段 2 rewritten: mechanical pre-check reads only
    `manifest.json` (`extracted_count`, per-chapter `word_count`, fragmentation
    >100, file-count via one `ls | wc -l`; neighbour `word_count` jumps flag
    boundary mis-cuts). Then a **single** Bash `for f … head -n 8; tail -n 8`
    command emits one head+tail digest of **all** chapters, read in one shot —
    every chapter eyeballed for truncation/garble at ~16 lines each instead of 200,
    and ~1 tool call instead of ~80. "每章只看头尾少量行，绝不整章通读" is the stated
    hard constraint; chapter-start markers are explicitly treated as optional
    (OCR-unreliable).
  - 阶段 3 修复: per-chapter / boundary re-extract uses the manifest's `start_page`;
    after a re-run the head+tail digest is re-run; still capped at 2 rounds.
  - Output contract (`EXTRACT_RESULT`), CLI surface, and manifest schema unchanged —
    pure agent-prompt fix, no Python/test changes.

- **0.38.0** (2026-06-05): **New `quasi:process-talk` skill — recording → multi-engine
  ensemble transcription → structured talk summary (QUA-182).**
  - New `talk` + `transcript` schema types (schema contract **0.5.0 → 0.6.0**):
    `talk` = `vault/talks/<slug>/talk.md` (TalkSchema frontmatter `type/title/date/
    speaker/themes/rating/media` + six fixed four-char H2 body `核心论点 / 时间脉络 /
    分节摘要 / 关键概念 / 项目关联 / 文献人物` — `时间脉络` is video-specific, replacing
    paper's `理论框架`; `文献人物` replaces `核心引用`; Q&A folds into `分节摘要`).
    `transcript` = `vault/talks/<slug>/transcript.md`, lightweight freeform body
    (timestamped), frontmatter `type/title/talk`. Registered in `scripts/schemas/`
    (`talk.py`, `transcript.py`, `body.py`, `registry.py`, `__init__.py`), mirrored
    into `audit-agent.md`, snapshot/registry tests bumped. `autofix_mechanical`
    keeps `talk.date` (the global orphan list drops `date` for paper).
  - **Transcription is a multi-engine ENSEMBLE** (`scripts/transcribe/` +
    `bin/quasi-transcribe`): `run` extracts 16k mono wav and runs Soniox
    (`stt-async-v4`, cloud, highest quality + word timestamps, needs
    `soniox_api_key`) + Apple `SpeechTranscriber` (on-device, macOS 26, compiled
    from `apple_stt.swift`) + Parakeet-v3 (mlx, English/European, auto-skipped for
    Chinese) in parallel; each engine's SRT lands under `processing/talks/<slug>/`
    (tracked, user-inspectable intermediates like `processing/chapters/` — kept so
    the summary can be re-run without re-transcribing / re-paying Soniox) and
    the primary (Soniox-preferred) assembles `transcript.md` plus a tracked
    `recording.srt` (named to match `recording.<ext>` so video players auto-load
    it as subtitles). `classify` does a
    text-only live/DEAD verdict; `silent` writes the schema-conforming "no usable
    audio" `talk.md`. Engines fail-soft (empty on error) so the ensemble degrades.
  - `analyse-agent` gains a `type: T` (talk) mode: reads all engine transcripts and
    **cross-references by timestamp** (agreement ≈ truth, disagreement = the
    proper-noun/homophone/jargon spans to adjudicate), then writes `talk.md` per
    TALK_BODY, back-filling `speaker` / `themes`. Minimal additive change — A/B
    untouched.
  - New `soniox_api_key` userConfig (sensitive) → `QUASI_SONIOX_API_KEY` via the
    inject-userconfig hook `_KEYS`. New `skills/process-talk/SKILL.md` (single-talk,
    Step-0 local recall, `quasi-transcribe` + `analyse-agent` + `audit-agent`).
  - System deps for transcription: `ffmpeg`, `whisper-cli` (optional engine +
    language detect), `swiftc` (Apple), `uvx` (Parakeet). All optional/fail-soft
    except at least one working engine.
  - Tests: `test_transcribe.py` (SRT parse, Soniox word-boundary grouping, classify,
    silent/transcript body conformance), `test_schema_registry.py` +
    `test_schema_snapshot.py` extended for `talk`/`transcript`. Full suite 114 pass.

- **0.37.6** (2026-05-31): **Step 0 uses local-first duplicate/resume recall before search/download.**
  - `process-book` and `process-paper` now check local completed outputs,
    accepted sources, caches/manifests, and rg fuzzy candidates before calling
    `search-agent` / `download-agent`, so slug stopword drift is less likely to
    duplicate work.
  - `process-author` now checks existing author profile/manifest/discovery
    caches first and reconciles representative works against local final/source
    /partial artifacts before acquisition.
  - Regression tests assert local recall/reconcile precedes search/download.

- **0.37.5** (2026-05-30): **`topic` / `journal` pages gain required `title`
  (schema contract 0.4.0 → 0.5.0) + process-topic dispatch/polling hardening.**
  - `TopicSchema` and `JournalSchema` now require `title: Title` so every page
    type carries a human title for the reader / Marple frontend without
    parsing H1. journal `title` = 期刊名 (redundant with `journal` by design —
    every page type is uniform). Breaking field addition → schema contract
    version bumped `0.4.0 → 0.5.0` (`SPEC.md`, `scripts/schemas/__init__.py`).
  - Stale consumers caught the same way 0.37.2's `topics` mismatch was — the
    schema shipped without anyone downstream tracking it. Updated together:
    `SPEC.md` §3.5/§3.6 (TS defs, YAML examples, rules), `synthesis-agent.md`
    §J/§T (added the missing `<frontmatter_schema>` block — it had none),
    `process-topic` synthesis dispatch prompt (now emits `title: {topic}`),
    and `topic.py` docstring. The published Marple snapshot
    (`scripts/audit/emit_schema.py` → `.quasi/schema.json`) reads live models,
    so it self-updates; its expected-required table in
    `test_schema_snapshot.py` was bumped.
  - Tests: `test_schema_registry.py` (3 cases: lightweight validate now needs
    `title`; the old "journal-with-title is rejected" case became "extra field
    rejected" + a new "missing `title` rejected"; freeform-body fixtures gain
    `title`) and `test_schema_snapshot.py` (required tables). Full suite 209
    passing.
  - **process-topic** (problem the user flagged — tree dispatch wasn't stable):
    - New hard constraint at the top: 主进程只编排,绝不亲自处理 — every
      `process-*` / `synthesis` / `audit` step goes through `superset agents
      run`; the main process never runs `/quasi:process-*` or the `quasi-*`
      pipeline itself.
    - Completion polling moved off the main process: instead of the main
      process Glob-polling vault products (which floods its context on long
      delegated runs), it now dispatches one clean `general-purpose` poll-agent
      per batch with the batch's `vault_path` list. The agent loops `ls`/`test
      -f` every 60s until all present or 30min timeout, returns a compact
      `{present, missing, elapsed_s}`. read-only; main process updates the
      manifest from the result.
    - Added the `## Agent / Helper 合同` section the orchestration schema
      requires (process-topic was missing it — `test_active_skills_follow_
      runtime_schema` was already red on the prior commit) and houses the
      poll-agent contract there.
    - Fixed `test_process_topic_superset_agent_uses_shell_default_contract`
      which asserted double-brace `${{...}}` — the rest of the codebase (and
      the 0.37.1 runtime contract) uses single-brace `${QUASI_SUPERSET_AGENT:
      -copilot}`; the test was over-escaped, the SKILL was correct.

- **0.37.2** (2026-05-29): **Fix mechanical autofix stripping the `topics` support field.**
  - 0.37.0 (QUA-36) added `topics` as an optional membership field on the
    book / paper / chapter / author schemas and SPEC.md, but left `topics`
    in `scripts/typecheck/autofix_mechanical.py::ORPHAN_FIELDS`. Mechanical
    autofix therefore deleted the field as an orphan, undoing topic
    membership written by `process-topic` (and any hand-added `topics`).
  - Fix: removed `"topics"` from `ORPHAN_FIELDS`. The legacy singular
    `"topic"` stays an orphan — SPEC keeps dropping it; membership lives on
    the plural `topics` list. The schema field set and the orphan list were
    never linked by a test, so the QUA-36 schema change shipped without
    anything catching the mismatch.
  - Regression guard: `tests/test_block_list_yaml.py::`
    `test_autofix_keeps_topics_drops_singular_topic` feeds a fixture with
    both `topic` and `topics` through autofix and asserts `topics` survives
    while singular `topic` is dropped. Full suite 100 passing.

- **0.37.1** (2026-05-29): **Configurable Superset agent for process-topic dispatch.**
  - New `superset_agent` userConfig option (default `copilot`) forwarded as
    `QUASI_SUPERSET_AGENT`; `process-topic` dispatches
    `superset agents run --agent ${QUASI_SUPERSET_AGENT:-copilot}` instead of
    hardcoding `claude`.
  - `inject-userconfig` hook injects only `QUASI_SUPERSET_AGENT` for
    `superset agents run` commands, and blanks quoted spans before command
    detection so prompt text like `--prompt 'Run quasi-search'` no longer
    triggers broad config injection.

- **0.37.0** (2026-05-29): **Process-topic becomes vault-native review + reading-list indexing.**
  - `process-topic` now discovers papers and books with `quasi-search`, delegates
    item processing to `process-paper` / `process-book`, and indexes accepted vault
    products with topic-page `[[wikilinks]]` plus entity `topics: [slug]` membership.
  - Topic frontmatter now carries only `type` / `kind`; paper, book, chapter, and
    author schemas gain optional `topics` membership lists. Schema contract version
    is bumped to 0.4.0.
  - Resume handling reconciles stranded processing items by checking whether the
    delegated vault product already exists before re-dispatching work.

- **0.36.3** (2026-05-28): **Schema accepts numeric ISBNs and audit reports strict fields.**
  - `BookSchema.isbn` now accepts `int | str` input and coerces ISBN values to
    strings, so numeric YAML/JSON ISBNs validate instead of failing type checks.
  - `quasi-audit --path` now surfaces strict frontmatter field diagnostics for
    schema fields that need maintainer attention.

- **0.36.2** (2026-05-27): **Audit emits diagnostic-first repair contracts.**
  - `quasi-audit --path` now returns per-file `diagnostics[]` with explicit
    `status`, `action`, and location fields instead of the older
    `llm_editable` / `escalated` buckets.
  - Mechanical audit fixes report their own diagnostics, including QUA-108
    frontmatter flow-array to block-list rewrites and CJK body quote cleanup
    that skips frontmatter, code, links, and wiki aliases.
  - `audit-agent` now follows the diagnostics contract directly, applying only
    the actions the audit runner declares safe and escalating everything else.
  - `process-book`, `process-paper`, `process-author`, and `process-topic` now
    best-effort open the final Marple page after successful completion.

- **0.36.1** (2026-05-21): **Wrap-up citation review uses four-card AskUserQuestion rounds.**
  - `wrap-up` Phase 2.4 now tells the main process to show a short queue
    summary, expand at most four review cards, and collect the current round's
    decisions with `AskUserQuestion`.
  - Each `AskUserQuestion` question maps to one review card; complex cards run
    alone, while simple same-kind cards can share a round up to the four-question
    tool limit.
  - After each round, the main process must immediately update
    `decisions.json`, apply needed local edits, re-emit `references.bib`, and
    report remaining pending cards before showing the next round.

- **0.36.0** (2026-05-21): **Wrap-up citation review moves to Claude Code-native review cards.**
  - `quasi-helpers citation review-cards` merges `citecheck-agent` batch
    outputs into `.quasi/citation/{stem}/review-cards.json`, preserving
    both the new rich card fields and the legacy `flag` / `note` shape for
    transition.
  - `citecheck-agent` now writes high-context review cards: draft quote,
    use summary, current bib concern, candidate evidence from vault files,
    recommended action, confidence, and missing evidence. It still never
    edits draft, vault, manifest, biblio, or decisions.
  - `wrap-up` Phase 2.4 is explicitly CC-native review, not HTML/TUI. The
    main process must pass review-card context through to the user and, after
    each group of user decisions, immediately update `decisions.json`, apply
    needed local edits, re-emit `references.bib`, and report remaining work.
  - Tests: `tests/test_citation_review_cards.py` covers rich-card merging and
    legacy compact-note normalisation.

- **0.35.0** (2026-05-20): **Audit agent gains frontmatter metadata QA via search CLI (QUA-61).**
  - `audit-agent` now follows an explicit step sequence: Step 1 local audit
    transaction, Step 2 minimal LLM edits, Step 3 frontmatter check, Step 4
    validation.
  - Step 3 reads each item's frontmatter and, when needed, calls the existing
    `quasi-search` CLI (`book --isbn` / `--title --author`, `paper --doi` /
    `--title --author`) to verify `title`, `authors`, `year`, `isbn`, `doi`,
    `journal`, `publisher` against online metadata.
  - Mismatches are reported as `kind: "metadata_mismatch"` with current value,
    search candidate, and evidence source. Only clear, minimal frontmatter edits
    are applied; conflicts, weak matches, and edition/translation judgment calls
    are escalated. Never fabricates DOI / ISBN / year / publisher.

- **0.34.0** (2026-05-20): **EZProxy global cross-process rate gate (QUA-50).**
  - `quasi-download` now spaces EZProxy attempts across separate processes so
    parallel paper downloads cannot trigger institutional EZProxy bans —
    agent-side concurrency control was unreliable.
  - New `_ezproxy_throttle()` in `scripts/download/download.py` takes an
    exclusive `fcntl.flock` on a user-global state file
    (`${CLAUDE_PLUGIN_DATA:-~/.cache/quasi}/ezproxy-throttle.state`), and
    **holds the lock across the wait**, so competing processes pass the gate
    exactly one interval apart (true serialization, no thundering herd).
  - Called once at the top of `try_ezproxy_download`, after the
    "not configured" skip — unconfigured runs never wait; Phase-1, Phase-2
    Kagi, and the cookie-refresh retry all funnel through the single gate.
  - `EZPROXY_MIN_INTERVAL = 30` seconds, hardcoded (no env var, no Configure
    option). Wait is uncapped (a queued process always waits its turn) but a
    single wait is bounded to one interval against corrupted/future
    timestamps. No-op when `fcntl` is unavailable.
  - Scope: EZProxy only. AA stays agent-spaced; `download-agent.md` note
    relaxed accordingly.
  - Tests: `tests/test_download_cli.py` gains throttle timing/locking unit
    tests, a real multi-process serialization test, and gate-placement tests
    for `try_ezproxy_download`.

- **0.33.6** (2026-05-20): **Publisher PDF discovery handles Crossref PDF endpoints and proxied INFORMS hosts.**
  - Crossref PDF discovery now accepts official PDF-looking URLs even when Crossref marks their `content-type` as `unspecified`, covering OUP article-PDF URLs.
  - Cambridge Crossref `content/view/...` endpoints are accepted as PDF candidates; live 2026 Cambridge EZProxy validation also succeeds through `citation_pdf_url` when direct construction is not usable.
  - INFORMS proxied hosts (`pubsonline-informs-...`) now match the EZProxy PDF pattern, and DOI prefix `10.1287/` now maps to `pubsonline.informs.org/doi/pdf/{doi}` for publisher-direct attempts.
  - Live 2026 EZProxy validation: ACM, Cambridge, De Gruyter, Brill, MIT Press, OUP, Project MUSE, SAGE, Taylor & Francis, UChicago, Wiley, plus forced Springer EZProxy stage all succeed. INFORMS reaches the proxied article page but tested `/doi/pdf/...` endpoints return HTML/no entitlement; Elsevier ScienceDirect reaches the subscribed article page but PDF download is gated by a browser intermediate page.
  - Tests: full suite 29/29 passing.

- **0.33.5** (2026-05-19): **EZProxy CookieCloud domain matching handles OCLC subdomains.**
  - CookieCloud filtering now keeps cookies across the configured EZProxy domain tree instead of requiring exact-domain equality. Configuring `oclc.org` now preserves usable cookies from `idm.oclc.org` and publisher-specific proxied subdomains.
  - EZProxy sessions preserve each CookieCloud cookie's original domain/path, so parent-domain and subdomain cookies are scoped the same way the browser scoped them.
  - Direct proxied PDF downloads build a Cookie header from only the cookie records matching the requested proxied host, avoiding stale or unrelated sibling-domain cookies.
  - Live validation: Taylor & Francis proxied direct PDF for DOI `10.1080/02691728.2025.2480274` succeeds with configured domain `oclc.org`.
  - Tests: full suite 25/25 passing.

- **0.33.4** (2026-05-19): **Fix proxied direct URL cookie injection.**
  - `download_pdf_from_url()` now supports CookieCloud's multi-cookie EZProxy config (`cookies` dict) when downloading already-proxied direct PDF URLs.
  - Fixes a `KeyError: 'cookie'` path introduced after CookieCloud moved from a single cookie value to domain-filtered cookie dictionaries.
  - Tests: full suite 23/23 passing.

- **0.33.3** (2026-05-19): **Plugin config cleanup for worktrees.**
  - All active plugin Configure options are marked `sensitive` so Claude Code stores and injects every option through the same private/keychain path. This works around worktree sessions only receiving private plugin options in hook subprocesses.
  - `anna_mirrors` is removed from plugin Configure options and no longer forwarded by the Bash PreToolUse hook.
  - Anna's Archive download still uses the built-in default mirror list internally, so users only configure `anna_donator_key`.
  - README credential table updated accordingly.

- **0.33.2** (2026-05-19): **Publisher PDF download query variants.**
  - EZProxy direct PDF patterns now try `?download=true` variants for Taylor & Francis, Wiley, and UChicago before falling back to embedded viewer scraping.
  - EZProxy epdf fallback now covers Taylor & Francis (`/doi/epdf/{doi}?needAccess=true`) and Wiley (`/doi/epdf/{doi}`), matching proxied viewer URLs observed for Social Epistemology and British Journal of Sociology papers.
  - Publisher Direct and Wayback URL construction now include `?download=true` variants for Taylor & Francis, Wiley, and UChicago; Wiley `10.1111/` DOI prefixes are included alongside `10.1002/`.
  - `citation_pdf_url` meta extraction is now attribute-order tolerant, so viewer pages with extra `<meta>` attributes still resolve to the underlying PDF URL.
  - Tests: full suite 23/23 passing.

- **0.33.1** (2026-05-19): **UChicago EZProxy PDF discovery.**
  - EZProxy publisher-pattern download now tries all matching publisher
    patterns instead of stopping after the first match. This lets UChicago
    fall through from `/doi/pdf/{doi}` to `/doi/pdfplus/{doi}`.
  - UChicago embedded viewer support: EZProxy fetches `/doi/epdf/{doi}`
    and extracts `citation_pdf_url` from the page before the generic HTML
    link scrape. This covers UChicago pages whose direct PDF endpoint is
    not exposed on the DOI landing page.
  - Publisher Direct also tries all matching patterns and includes
    UChicago `/doi/pdfplus/{doi}`.
  - Tests: full suite 23/23 passing.

- **0.33.0** (2026-05-19): **Paper download gains multi-source discovery,
  publisher direct PDF, and Kagi recovery.** Driven by 19-paper test
  batch where 15 papers failed acquisition (6× EZProxy expired,
  6× abstract-only/no-PDF, 2× paywall+no OA, 1× too new — the
  remaining 4× ECONNRESET/502 were already fixed by 0.32.15 retry).
  Root cause: papers had no multi-source candidate discovery — unlike
  books (which search Anna's Archive for multiple candidates and iterate),
  papers took a single DOI and ran a fixed cascade. If the DOI was wrong
  or the cascade failed, there was no fallback.
  - **Paper fetch cascade expanded** from 5 stages to 8 (Phase 1) + Kagi
    recovery (Phase 2). New cascade:
    `hint URLs → OA (+Crossref links) → Sci-Hub → Publisher Direct
    → EZProxy → Wayback → [if all fail] Kagi discovery → retry with
    discovered DOIs/URLs`.
  - **Crossref PDF links** added to `find_oa_url()` as 4th source.
    Queries `https://api.crossref.org/works/{doi}` and extracts
    `link[]` entries with `content-type: application/pdf`. Many
    publishers register their PDF endpoints here.
  - **Publisher Direct PDF** — new cascade stage between Sci-Hub and
    EZProxy. `_try_publisher_direct(doi, output_path)` constructs
    publisher PDF URLs from DOI prefix patterns
    (`_PUBLISHER_DIRECT_URLS`: uchicago, tandfonline, sagepub, oup,
    wiley, springer, nature, mit, acm, muse, cambridge, informs)
    and tries fetching them without EZProxy. Catches cases where
    institutional IP access works or publisher has opened access.
  - **Kagi recovery** — when Phase 1 cascade exhausts all sources,
    `_kagi_discover_paper(title, author)` searches the paper title
    via `kagi search --format json`, filters results by ≥50% title
    word overlap, extracts DOIs from URLs via regex, and collects
    publisher URLs. Discovered URLs are tried directly; discovered
    DOIs (different from the original) are retried through
    OA/Sci-Hub/EZProxy. Silently skipped if kagi CLI is unavailable
    or `QUASI_KAGI_SESSION_TOKEN` is unset. Enables acquisition
    even when the caller's DOI is wrong.
  - **Multiple `--url` hints** — `paper fetch` now accepts repeated
    `--url` flags (`action="append"`). Each URL is tried as a direct
    download attempt before the DOI cascade. This lets the agent
    pass OA URLs and publisher URLs discovered via search.
  - **`--title` / `--author` flags** — `paper fetch` now accepts
    `--title` and `--author` for Kagi recovery. When the DOI cascade
    fails, these enable the automatic Kagi discovery phase.
  - **Wayback patterns expanded** — `find_wayback_url()` now
    constructs publisher-specific PDF URLs for UChicago (`10.1086`),
    Wiley (`10.1002`), OUP (`10.1093`), MIT Press (`10.1162`),
    T&F (`10.1080`), SAGE (`10.1177`), in addition to the existing
    ACM, Springer, MUSE patterns. Each gets a dedicated CDX lookup.
  - **download-agent.md** — paper flow now mirrors book flow: agent
    calls `quasi-search paper --doi/--title/--author --json` to
    verify DOI and discover access URLs before calling `paper fetch`.
    Passes verified DOI + `oa_url`/`url` as `--url` hints. Handles
    wrong/missing DOI case. Agent prompt updated with new CLI
    examples and search-before-fetch guidance.
  - **process-paper SKILL.md** — download-agent dispatch now passes
    `oa_url` and `url` from search-agent results through to
    download-agent's `identifiers:` block, so download-agent already
    has URLs to try without re-searching.
  - Tests: full suite 23/23 passing. No test changes needed — new
    features are additive (new cascade stages, new CLI flags with
    defaults, new recovery path).

- **0.32.15** (2026-05-19): **Paper download cascade gains retry/backoff
  and a real INFORMS pattern; Wayback always on.** Triggered by a 5-paper
  batch (Hayles 2019 / Star 1996 / Oudshoorn 2004 / Lock 1994 /
  Dhaliwal 2022) where 4 of 5 papers failed acquisition. Live re-probe
  showed 3 of 4 DOI-bearing papers downloaded fine *today* — the original
  batch had been killed by transient sci-hub / EZProxy errors that no
  retry layer was catching. Lock 1994 has no DOI (JSTOR stable URL
  only) and is out of scope for download.py; that one needs agent-side
  changes to fall back through `--url` when `doi:null`.
  - New `_retry(fn, attempts=3, base_delay=1.0)` helper with
    `_is_retryable_http()` companion. Retries `URLError` /
    `RequestException` / `TimeoutError` / `ConnectionResetError` and
    transient HTTP codes (`429, 500, 502, 503, 504, 520, 521, 522, 524`)
    with exponential backoff. Determinstic 4xx propagates immediately —
    a 404 should never become 3× wall-clock cost.
  - Wrapped network entry points: `try_scihub_download` (both the
    page-fetch and the PDF-fetch `urlopen`s, per mirror),
    `download_pdf_from_url` (urllib), `_stream_download` (requests stream
    — chunked transfer restarts from byte 0 on failure), and
    `try_ezproxy_download`'s three `session.get` calls (login redirect,
    publisher-pattern PDF try, scrape try).
  - `SCIHUB_MIRRORS`: `[".ru", ".ren"]` → `[".ru", ".st", ".box"]`.
    Probed 2026-05: `.ren` persistently returns 403; `.st` and `.box`
    mirror the same storage backend as `.ru` and reliably surface
    `citation_pdf_url` meta tags. Mirror list is now 3 deep with no
    known-dead entries.
  - `PUBLISHER_PDF_PATTERNS` gains `("pubsonline.informs",
    "/doi/pdf/{doi}")` — INFORMS journals (Information Systems
    Research, Organization Science, MIS Quarterly, etc.) host PDFs at
    `pubsonline.informs.org/doi/pdf/{doi}`. Previously EZProxy
    redirects to INFORMS fell through to the HTML-scrape branch which
    rarely works (INFORMS hides PDF links behind a JS click handler).
  - `try_ezproxy_download` logs `EZProxy: not configured (CookieCloud
    env vars missing), skipping` when `load_ezproxy_config()` returns
    None. Was silent — diagnostically misleading because the cascade
    printed `Trying EZProxy for X...` then `Could not download paper`
    with no signal that the stage was a no-op.
  - `--retry-wayback` flag accepted but ignored (help hidden via
    `argparse.SUPPRESS`); Wayback is now always tried as the last
    cascade step. `_cmd_paper_fetch` calls `download_paper(...,
    retry_wayback=True)` unconditionally. The flag stays callable so
    existing agent prompts / skills that still pass it don't break.
  - `agents/download-agent.md` paper-fetch command example drops
    `[--retry-wayback]` and notes the cascade has retry/backoff at each
    stage.
  - Tests: `test_download_cli.py` + `test_dead_names.py` unchanged and
    passing (7/7). `_retry` smoke-tested out of band: 4xx propagates
    after 1 attempt, 5xx / ConnectionResetError retry to 3 attempts
    then re-raise, second-attempt-success returns the value.
  - End-to-end re-probe (post-fix):
    - Star 1996 (`10.1287/isre.7.1.111`) → sci-hub.ru direct, 2.4 MB ✓
    - Dhaliwal 2022 (`10.1086/721167`) → sci-hub.ru/.st/.box all empty
      (sci-hub doesn't have the 2022 article) → EZProxy uchicago
      pattern → 10.5 MB ✓

- **0.32.14** (2026-05-19): **Douban zh-localisation: two-stage CJK
  filter; bin no longer guesses relevance.** Three interlocking bugs
  surfaced when localising *Living a Feminist Life* — Kagi's top hit
  (`/subject/36494081/?_dtcc=1`) was being silently dropped, and the
  ISBN fallback variant was polluting results with popular unrelated
  Chinese books. Root cause was 0.32.9's "strict admission" regex
  rejecting normal URL cruft, plus an under-considered ISBN variant
  using the original-language ISBN that Douban doesn't index.
  - **Regex normalises subject-URL cruft instead of rejecting it.**
    `_RE_DOUBAN_SUBJECT_CLEAN` switched to
    `^https?://book\.douban\.com/subject/(\d+)/*(?:\?[^#]*)?(?:#.*)?$`.
    Accepts `/subject/{id}//` (double-slash) and `/subject/{id}/?_dtcc=1`
    (Kagi tracking suffix) and `/subject/{id}#frag`, all normalise to
    canonical `/subject/{id}/`. Still rejects `/comments`,
    `/blockquotes`, `/doulists`, `/annotation`, `/offers`, `/buylinks`,
    `/reviews/...` child paths. This reverses 0.32.9 — that release's
    "exact policy" was a regression in disguise; real Kagi output
    routinely carries the cruft on legitimate subject pages.
  - **ISBN variant gated to ISBN-only queries.** `_external_book_queries`
    no longer adds the ISBN as a Kagi search variant when title or
    free-text query is present. Douban indexes the *Chinese-edition*
    ISBN, never the original English one — so an English-edition ISBN
    triggers Kagi's "no precise match, return popular results"
    fallback, which surfaces top-rated unrelated Chinese books
    (典型: 如何阅读一本书 / 脑髓地狱 / 边界力 / 谁来决定吃什么 returned for any
    English ISBN under `subject=zh`).
  - **Pre-fetch CJK title filter.** `_kagi_subject_urls` now returns
    `[(canonical_url, kagi_title), ...]` pairs. `_kagi_book_search`
    accepts `cjk_title_only=True` and skips Kagi hits whose page title
    is Latin-dominant before spending an HTTP fetch on them — drops
    the English-edition Douban page when we're after the Chinese
    translation. `_cjk_dominant` decides by CJK-vs-ASCII-letter count.
  - **Bin no longer attempts query-vs-record relevance matching.**
    `_zh_localisation_search` is two coarse filters and a sort:
    pre-fetch CJK title → fetch → post-fetch `_is_chinese_edition`
    (publisher / translator / ISBN-agency / kana-hangul-reject signals
    unchanged) → sort by `ratings_count`. The "is this record the
    translation of *this specific* book the caller asked for"
    disambiguation is the caller agent's job — bin returns the small
    set of Chinese-book candidates Kagi surfaced, agent picks.
  - **Per-variant Kagi pull bumped 10 → 20** so the CJK pre-filter has
    enough candidates to survive even when the EN edition crowds the
    top of Kagi's ranking.
  - Tests in `test_source_douban_cn.py` and `test_douban_cn_en2zh.py`
    updated for the new `(url, title)` return shape and the cjk-title
    pre-filter behaviour. Full search suite green (35 + 12 + others).
  - Behaviour: end-to-end `quasi-search book --title "Living a
    Feminist Life" --author "Sara Ahmed" --source douban_cn --subject
    zh` now returns the single correct record `subject 36494081 过一种
    女性主义的生活, 原作名 = Living a Feminist Life, 出版社 = 上海文艺出版社`
    (previously: 4 unrelated popular Chinese books).

- **0.32.13** (2026-05-19): **EZProxy config takes a base URL, not a
  half login prefix.**
  - Breaking config rename: `cookiecloud_login_url` is removed and
    replaced by `cookiecloud_ezproxy_base_url`.
  - Users now enter a clean base such as `https://ezproxy.example.edu` or
    `ezproxy.example.edu`. `scripts/download/cookiecloud.py` normalises it
    to `https://.../login?url=` internally.
  - Removed the last hard-coded EZProxy login-prefix fallback from
    `download.py`; EZProxy only runs when the new base URL and the rest of
    the CookieCloud config are present.

- **0.32.12** (2026-05-19): **Configure Options copy cleanup for
  CookieCloud / EZProxy.**
  - Removed the hard-coded Harvard EZProxy default from
    `cookiecloud_login_url`; users should provide their own institution's
    redirect prefix if they want EZProxy downloads.
  - Clarified the three distinct values: CookieCloud endpoint, EZProxy
    cookie domain, and EZProxy login URL prefix. The CookieCloud endpoint
    is only used to fetch browser cookies; the EZProxy fields describe the
    institution proxy itself.

- **0.32.11** (2026-05-19): **Kagi auth moves into plugin userConfig.**
  - Added sensitive `kagi_session_token` to `.claude-plugin/plugin.json`.
    Users configure it via `/plugin` → Configure options, matching the
    existing Anna's Archive / CookieCloud / Immersive Translate credential
    flow.
  - `scripts/hooks/inject-userconfig.py` now propagates it as
    `QUASI_KAGI_SESSION_TOKEN` for `quasi-*` Bash commands.
  - `scripts/search/sources/douban_cn.py` maps `QUASI_KAGI_SESSION_TOKEN`
    to `KAGI_SESSION_TOKEN` only for the `kagi` subprocess. This uses
    kagi-cli's documented env-var override and avoids relying on CWD
    `.kagi.toml`.

- **0.32.9** (2026-05-19): **Douban subject discovery tightened and
  query variants broadened.**
  - URL admission now uses the exact book-subject policy:
    `^https?://book\.douban\.com/subject/(\d+)/?$`. Only canonical
    `/subject/<digits>` and `/subject/<digits>/` pages survive; child
    pages such as `/comments`, `/blockquotes`, `/annotation`,
    `/doulists`, `/reviews/...`, query-string URLs, and double-slash
    variants are rejected instead of being normalised into candidates.
  - Kagi discovery now tries ordered query variants instead of one weak
    `title-head + author` string. It first searches the exact original
    title, then exact-title variants with Douban metadata hints
    (`原作名`, `译者`), then title-head variants for subtitled books, and
    only then author-qualified fallbacks.
  - Restored `_zh_localisation_search(query)` as a thin wrapper around the
    Kagi path for test and maintainer clarity: it fetches subject pages,
    filters Chinese editions, and sorts them by `ratings_count`.
  - Tests updated to the Kagi-only adapter surface:
    `test_source_douban_cn.py` 33/33 and `test_douban_cn_en2zh.py` 12/12.

- **0.32.8** (2026-05-19): **Douban localisation: Doko walk removed,
  Kagi + BeautifulSoup is the only path.** 10/10 live test books (Foucault
  / Butler / Latour / Anderson / Said / Arendt / Bourdieu / Haraway etc.)
  returned at least one Chinese-edition candidate via the simple flow —
  vindicating the user's diagnosis that the Doko maze was overengineering.
  - **`scripts/search/sources/douban_cn.py`**: 1402 → 678 lines (51% cut).
    Deleted: `_doko_read`, `_find_cndouban`, `_cndouban_works_*`,
    `_related_version_search`, `_fetch_subject_for_related`,
    `_parse_cn_subject_page`, `_parse_doko_subject_page`,
    `_grab_doko_meta`, `_doko_meta_window`, `_clean_doko_title`,
    `_extract_related_version_urls*`, `_version_section_snippets`,
    `_parse_doko_references`, `_extract_manifestations_from_works_page`,
    `_kagi_site_subject_urls`, `_kagi_site_subject_query`,
    `_score_primary_match`, `_normalise_for_match`, plus a dozen helpers.
    Net deletion of the entire Doko subprocess path.
  - **New 3-step path** (`_zh_localisation_search`):
    1. `_compact_external_book_query(title, author)` →
       `_kagi_subject_urls(q)` runs `kagi search --format json
       site:book.douban.com/subject {q}` and filters `data[].url` via
       `_RE_DOUBAN_SUBJECT_CLEAN = r"^https?://book\.douban\.com/subject/
       (\d+)/*(?:\?[^#]*)?$"` — drops `/comments`, `/blockquotes`,
       `/doulists`, `/reviews/...`, normalises `/subject/ID//` and
       `?_dtcc=...` to canonical `/subject/ID/`.
    2. `_fetch_subject_via_bs4(url)` uses plain `urllib` (`_dd_fetch`) +
       `BeautifulSoup` to parse `<span property="v:itemreviewed">` for the
       title and `<div id="info">` for `作者 / 译者 / 出版社 / 出版年 / ISBN
       / 原作名` etc. Field parsing uses label-alt lookahead so the inline
       metadata block doesn't bleed across fields, and stays scoped to
       `#info` so stray `译者:` in reader comments can't leak in.
    3. `_is_chinese_edition(rec)` (unchanged from 0.32.7): ISBN agency
       prefix decisive (CN/TW/HK accept, JP/KR/VN reject), then kana /
       hangul anywhere reject, then CJK in publisher / translator-with-CJK
       / title accept.
  - `search_book(query)` `subject=zh` branch shrinks from a 3-fallback
    cascade (Doko cndouban → kagi-seeded related-version walk → direct
    search → related-version walk) to one call to
    `_zh_localisation_search`.
  - **No new `userConfig`** — `kagi` CLI reads `.kagi.toml` from CWD per
    its own convention; the plugin doesn't bridge or override.
  - **Tests rewritten**: `test_source_douban_cn.py` (29 tests) and
    `test_douban_cn_en2zh.py` (19 tests) target the new functions —
    URL-filter regex (canonical / `/comments` reject / double-slash
    normalisation / dedup / limit), `_compact_external_book_query`
    behaviour, `_kagi_subject_urls` shell-out (kagi missing / nonzero rc
    / site-limiter format), `_fetch_subject_via_bs4` parsing (info-block
    isolation, block detection, fetch-failure handling),
    `_is_chinese_edition` matrix (CN/TW/HK accept, JP reject even with
    kanji, kana/hangul reject, CJK-publisher accept, non-CJK translator
    reject), `_zh_localisation_search` integration (filter mix EN+ZH,
    sort by ratings_count, kagi-warning surface). Full suite: 94 pass.
  - `agents/search-agent.md` zh-localisation note updated:
    `Kagi 不可用或无结果时,bin 会自行走豆瓣兜底` → `Kagi 不可用时,
    localisations.zh.candidates 为空`. No more Doko fallback to misrepresent.
  - `docs/DOUBAN_LOCALISATION_HANDOFF.md` rewritten end-to-end against
    the new 3-step pipeline.

- **0.32.7** (2026-05-19): **Douban Chinese localisation pipeline — end-to-end
  correctness pass.** Builds on 0.32.4–0.32.6 (Kagi-CLI primary subject
  discovery). Five real-book end-to-end runs surfaced five downstream bugs
  that were masking each other; all fixed in `scripts/search/sources/douban_cn.py`:
  - **Primary-subject picker no longer takes Kagi rank #1 blindly.** For
    "Strange Encounters / Sara Ahmed" Kagi ranked *The Cultural Politics of
    Emotion* #1 (CPE's page text mentions SE). Now each Kagi URL is
    Doko-fetched, parsed, and scored against the original title/author
    (`_score_primary_match`: title-head substring ⇒ +1.0; token overlap ≥60%
    ⇒ +0.6; author-surname ⇒ +0.4). Score ≥1.2 early-breaks; <0.3 rejects.
  - **`_parse_cn_subject_page` field extraction rewritten.** Doko renders
    Douban metadata as one long line `作者: ... 出版社: ... 出版年: ... ISBN: ...`,
    so the old `作者:.+?\n` regex greedily grabbed the entire blob. Now uses
    `_grab_doko_meta` with label lookahead against `_DOKO_META_LABELS`.
  - **`_grab_doko_meta` scoped to a metadata window.** Previously matched
    anywhere in the body — picked up stray `译者:` from reader comments far
    below the metadata, producing translator blobs like `"Alice Lian Sara
    Ahmed(2004),The Cultural Politics of Emotion..."`. New helper
    `_doko_meta_window(body)` slices text between `**Title**` and `豆瓣评分`.
  - **Title cleaning.** `_guess_title_from_subject_page` used to return
    `# Title (豆瓣)` with markdown noise. Now prefers the `**Title**` marker
    and strips the `(豆瓣)` suffix via `_clean_doko_title`.
  - **Chinese-edition detection no longer a publisher whitelist.** Old
    `_ZH_PUBLISHER_HINT_RE` enumerated ~25 publisher fragments (`三联|译林|
    上海|...`) — could never keep up with the long tail of academic / indie
    presses, and its bare `出版` alternation also matched the year label
    `出版年` (false positive). Replaced with registry-based signals:
    - ISBN agency prefix `978-7-` (mainland) / `978-957/986` (TW) /
      `978-988/962` (HK) ⇒ accept
    - ISBN prefix `978-4-` (JP) / `978-89/11` (KR) / `978-604` (VN) ⇒
      explicit reject (otherwise kanji-only Japanese titles like 伴侶種宣言
      slip through the generic CJK check)
    - Kana or Hangul anywhere in title / publisher / translator ⇒ reject
    - CJK in publisher | (CJK in translator AND translator non-empty) |
      CJK in title ⇒ accept
    The translator-non-empty alone (which had let through a French CPE
    edition by "Laurence Brottier") now requires CJK to count.
  - **End-to-end validation** in `docs/DOUBAN_LOCALISATION_HANDOFF.md`:
    Gender Trouble returns 3 Chinese editions (上海三联书店 / 岳麓书社 /
    桂冠 TW); Discipline and Punish returns 4 (三联书店 various years);
    Strange Encounters / CPE / Staying with the Trouble correctly return
    no candidates (no Chinese Douban subject for those works exists).
  - Existing 38 `douban_cn` tests still pass; full search suite 84 pass.
  - No new plugin `userConfig` slot — `kagi` CLI auth is read from
    `.kagi.toml` in CWD (user's own setup), not bridged through the
    plugin.

- **0.32.3** (2026-05-18): **book localisation sidecar becomes
  Doko-first and source-independent.** `quasi-search book` now always
  attempts the `localisations.zh` Douban sidecar, even when the caller
  limits canonical metadata search with `--source`. Chinese localisation
  lookup now prefers the Doko-rendered path (ISBN/search → Douban subject
  → other versions / works page → Chinese manifestation subject) before
  falling back to direct HTTP + related-version probing. Doko failures are
  surfaced as `localisations.zh.status="error"` instead of the previous
  false-negative `none`, so callers do not cache "no translation" when the
  browser bridge/API path was unavailable.

- **0.32.1** (2026-05-18): **frontmatter description discipline.**
  Treats `description:` as a routing hint, not a mini-README.
  Skill descriptions normalised to user-intent shape — `Use when
  the user wants to {core task} from/with {likely inputs}.`
  Agent descriptions normalised to worker shape — `Worker for
  {single specialist action}. {Main contract.}` Trigger-word piles,
  history notes (`前身: ...`), and phase walkthroughs (`Phase X →
  ...`) removed across all 5 active skills and all 9 active agents.
  `AGENTS.md`, `CLAUDE.md`, and `docs/SKILL_ORCHESTRATION.md`
  carry the maintainer-facing convention. Enforcement landed as
  `tests/test_skill_orchestration.py::test_frontmatter_descriptions_are_routing_hints`
  (length cap 220, required prefix per kind, forbidden tokens
  `user says / 前身 / Phase / → / 由 ` per kind).

- **0.32.0** (2026-05-18): **skill orchestration schema + bin
  surface trim.** All five active skills rewritten to the
  maintainer schema documented in `docs/SKILL_ORCHESTRATION.md`
  (new file): `任务` (one positive sentence), `输入` (intent →
  variable extraction), `硬约束`, `状态` (skill main process owns
  workflow state), `Agent / Helper 合同`, `工作流`, `执行流程`,
  `断点续跑`, `输出`. `调用方式`-style invocation API blocks are
  removed from runtime skills; natural-language trigger via
  frontmatter description is canonical. `AGENTS.md`, `CLAUDE.md`,
  `README.md`, and `docs/ARCHITECTURE.md` carry the maintainer-facing
  pointer to the schema doc, so active `SKILL.md` files no longer
  link back to maintainer docs.
  - Rewritten: `process-book`, `process-author`, `process-paper`,
    `process-topic`, `wrap-up`. Behaviour preserved end-to-end; the
    rewrite is structural — phases, agent dispatches, and human
    gates are now made explicit per the schema.
  - **BREAKING — `quasi-search`**: `--shape canonical|raw|single`
    and `--output PATH` flags removed; the markdown emitter is
    gone. Output is always canonical JSON to stdout. `--json` is
    accepted as a no-op for compatibility. Callers that needed
    `--shape single` should slice `results[:1]` themselves; the
    `raw` shape was unused.
  - **BREAKING — `quasi-download`**: `batch` subcommand removed
    along with `batch_download_manifest()` and the related glue
    (`_cmd_batch`, parser entry). Batch acquisition is now a skill
    main-process concern — `process-author` / `process-topic`
    dispatch `download-agent` directly with structured items.
  - `quasi-extract` chapter manifest: per-chapter field `file`
    renamed to `filename`; added `extracted_count` (top-level) and
    `word_count` (per chapter). Downstream extract callers and
    `process-book` Step 2 read the new shape.
  - `tests/test_dead_names.py` now scans active markdown plus
    `bin/quasi-*` shims, `README.md`, and `docs/ARCHITECTURE.md`,
    and grows entries for `--shape single|raw`, `--output`,
    `quasi-download batch`, `output_schema`, `citation-agent`
    (post-0.25.2 rename), and `mode: papers` (post-0.24.0 search
    refactor).
  - New tests: `tests/test_search_cli.py` (asserts JSON-only output
    contract, no `--shape`/`--output`), `tests/test_extract_cli.py`
    (asserts new chapter manifest field names),
    `tests/test_skill_orchestration.py` (asserts all five active
    skills carry the schema landmarks).
  - Minor: `scripts/extract/toc_utils.py` gains
    `from __future__ import annotations`; `scripts/citation/emit_bib.py`
    docstring updated to reference the wrap-up review step (not the
    deprecated `review.html` "导出 JSON" button); `quasi-helpers`
    header comment updated to `citecheck-agent` (post-0.25.2).

- **0.31.0** (2026-05-18): **quasi-audit becomes a single
  agent-facing typecheck wrapper.** The active CLI is now
  `quasi-audit --path PATH`. It always runs mechanical autofix,
  typecheck, residual issue classification, and emits JSON. Removed
  the agent-facing `run` verb, `--mode`, and `--json`; there is no
  check-only path in the active workflow. `emit-bib` moved to
  `quasi-helpers citation biblio`, and metadata backfill sweeps are
  maintenance scripts rather than `quasi-audit` subcommands.

- **0.30.0** (2026-05-18): **localise becomes a scale-facing helper,
  keyed by original ISBN.** This supersedes the 0.27/0.29
  local-agent/audit-localise shape. Book search now returns
  `localisations.zh` sidecar candidates; search-agent filters and
  passes those candidates upward but does not write files. The top-level
  skill decides whether to persist them via
  `quasi-helpers localise scan|write`, which writes
  `.quasi/localise/cndouban.json`:
  - `by_isbn[{normalized_original_isbn}]` stores checked state,
    current book path snapshots, and curated `cndouban_ids`.
  - `by_douban_id[{id}]` stores Chinese-edition metadata.
  - `quasi-audit localise` and `agents/local-agent.md` are removed from
    the active surface; audit is back to vault consistency only.

- **0.29.0** (2026-05-18): **cndouban fully externalised + audit
  reverts to a stateless typechecker.** Two intertwined cleanups landed
  together. First: continues 0.26.0's `.quasi/` artifact discipline by
  evicting `cndouban` from book frontmatter — it was the last
  user-facing field that was actually plumbing (an index into
  `.quasi/audit/translations.json`); now both the per-book state
  machine and the per-id metadata cache live in that file. Second:
  audit-agent has no persistent state of its own — it's structurally
  a unit-like typechecker — so its disk-write surface contracts to
  zero, and the cndouban backfill knowledge moves out of audit into
  local-agent's domain entirely.

  **Externalising cndouban:**
  - `scripts/schemas/book.py`: `cndouban` field removed. Comment in its place
    points readers to the external file.
  - `.quasi/audit/translations.json` schema bumped v1 → v2:
    ```json
    {
      "version": 2,
      "by_book": {
        "{slug}": {
          "checked_at": "YYYY-MM-DD",
          "verdict": "found" | "none",
          "douban_ids": [12345, 67890]
        }
      },
      "by_douban_id": {
        "12345": { ...per-id metadata, as before... }
      }
    }
    ```
    `verdict="none"` replaces the old `cndouban: []` semantic (查过、无中
    译本). `by_book[slug]` absent ⇒ 未查 (replaces `cndouban` field-absent
    semantic). v1 flat files are migrated by the script — readers do
    not need to handle v1 directly.
  - `scripts/migrations/cndouban_externalise.py` (new): one-shot
    user-disk migration. Scans `vault/books/**/00-overview.md`,
    converts each `cndouban: [...] / [] / null` field into a
    `by_book` entry (or for the null case, just strips the line —
    "not yet queried" needs no entry), reformats existing
    `translations.json` from v1 flat to v2 if needed, then strips
    the `cndouban:` line from frontmatter. Idempotent on
    already-migrated vaults. Invoke with
    `CLAUDE_PROJECT_DIR=/path/to/vault python "$CLAUDE_PLUGIN_ROOT/scripts/migrations/cndouban_externalise.py"`,
    optionally `--dry-run` first.
  - `agents/audit-agent.md`: book frontmatter `optional` list drops
    `cndouban` with a pointer comment to the external file.

  **Audit runner ⟂ translations.json decoupling + helper subcommands
  for local-agent:**
  - `scripts/audit/audit.py:_scan_needs_backfill` no longer flags
    `cndouban` at all; only structural frontmatter fields
    (publisher/isbn/doi) are reported. The runner doesn't open
    translations.json; cross-domain coupling that briefly slipped
    into `needs_backfill` is gone.
  - `scripts/audit/localise.py` (new) + `quasi-audit localise`
    subcommand: gives local-agent the script support it needs without
    a whole new bin. Two verbs:
    - `quasi-audit localise scan [--path X] [--json]` — enumerate
      `00-overview.md` files under PATH, emit per-book `{slug, path,
      has_entry, title, authors, year, isbn}`. `has_entry=true` means
      `by_book[slug]` is present in translations.json — the agent
      uses this for idempotent gating.
    - `quasi-audit localise write --slug SLUG (--results-json '[...]'
      | --results-file PATH)` — merge one book's localise outcome
      into translations.json. Empty results ⇒ `verdict=none`;
      non-empty ⇒ `verdict=found` + merge per-id metadata
      (`first_seen` preserved on existing keys). v1 flat cache
      auto-migrates to v2 on first write.

    These verbs live under `quasi-audit` purely as the natural home
    for small vault-touching helpers; the runner's analytical output
    stays domain-pure (cf. `feedback_audit_stateless` — runner stays
    decoupled even though bin can ship related helpers).
  - `agents/local-agent.md` rewritten: agent calls
    `quasi-audit localise scan --json` for the work list, dispatches
    `quasi-search book --source douban_cn --subject zh` per pending
    book, and writes results back via `quasi-audit localise write`.
    Agent no longer touches the JSON cache or vault frontmatter
    directly — tool surface trimmed to `Read, Bash`.
  - `skills/{process-book,process-author}/SKILL.md`: Step 6 / Phase 7
    LOCALISE comments + resume tables updated to reference
    `.quasi/audit/translations.json#by_book[slug]`; local-agent's
    self-contained gating noted.

  **Audit CLI dead-code cleanup — audit becomes effectively stateless:**
  - `scripts/audit/audit.py`: `_write_state()` deleted along with its
    `.quasi/audit/audit-state.json` artifact. Nothing programmatic
    read it; the wrap-up SKILL referenced it in pseudocode
    (`audit_state_clean()`) for a Phase 0 gating that was never
    actually implemented.
  - `quasi-audit check` and `quasi-audit fix` subcommands removed —
    they thin-delegated to typecheck.py / autofix_mechanical.py and
    had zero callers (agents use `quasi-audit run --mode {check,fix}`,
    which carries the structured JSON envelope). The `_delegate`
    helper goes with them. `bin/quasi-audit` shim help block rewritten.
  - `skills/wrap-up/SKILL.md`: `--audit-first` flag + the
    `audit_state_clean()` pseudocode block stripped (Phase 0 was never
    real; the only real audit consumers are inside process-book /
    process-author skills which dispatch audit-agent directly).
  - Post-cleanup, audit's only disk side-effect is
    `.quasi/audit/typecheck-results.json` (the in-process round-trip
    artifact left behind by typecheck.py). audit-agent itself is now
    truly stateless — runs, returns JSON, done.

  **Tests**: no test changes — existing `test_douban_cn_en2zh.py` /
    `test_source_douban_cn.py` cover the data-source layer
    (HTML parsing, search, normalisation), not the agent writeback
    path or the translations.json schema, so they're untouched by
    this refactor.

- **0.28.0** (2026-05-18): **process-book/author reorchestration +
  new process-paper skill.** Rewires `process-book` Step 0 and
  `process-author` Phase 1/2 around the post-0.24.0 search-bin and
  post-0.25.0 agent contracts, and lifts YEAR_TRIAGE out of skill
  prose into a structured field in `download-agent`'s output protocol.
  - `agents/download-agent.md`: `DOWNLOAD_RESULT.per_item` for
    `kind=book` gains a `year_evidence` sub-object
    (`slug_year`, `source_years`, `pdf_signals`, `recommended_year`,
    `recommendation_reason`, `verdict`). Status enum grows
    `year_mismatch` and `year_ambiguous`; `tmp_path` exposed in those
    cases. Verdict computation rule codified in the agent prompt:
    `recommended_year` prefers `pdf.first_published` > multi-source
    mode > `pdf.copyright_year`; translation books exclude
    `original_year`; `MATCH` iff `slug_year == recommended_year` and
    ≥2 corroborating signals. Papers (`kind=paper`) explicitly do
    not carry `year_evidence` — DOIs are one-to-one, no version
    ambiguity.
  - `skills/process-book/SKILL.md`: Step 0 shrinks from ~80-line
    inline prompt (replicating search→download→finalize chain inside
    download-agent's prompt) to a thin caller — dispatch
    download-agent with `{kind: book, items: [1]}`, branch on
    `item.status`. `ok` → continue to EXTRACT;
    `year_mismatch`/`year_ambiguous` → report `year_evidence`
    verbatim to user (user changes slug or manually mv tmp);
    `download_failed` → fail. No more string-match parsing of agent
    reply prose. Preamble describing the inline chain rewritten to
    point at the agent contract.
  - `skills/process-author/SKILL.md`: Phase 1 replaces single
    narrative search-agent dispatch with two strict-contract
    dispatches (`kind=book` + `kind=paper`) writing
    `.quasi/authors/{slug}/{books,papers}.json`; skill merges into
    the canonical `manifest.json` shape Phase 2+ already expects.
    Phase 2 replaces single `mode=both` download-agent dispatch (no
    longer supported by agent contract since 0.24.0) with two
    structured dispatches (`kind=book` + `kind=paper`). Batch policy
    on book year mismatch: do NOT pause — skill overrides agent's
    "keep as tmp" signal, `mv`s tmp → final under slug-authoritative
    name, records `year_evidence` + a one-line `year_warning` for
    end-of-run report. Paper failures (fail-fast, no candidate
    retry) recorded with `failure_note`. Manifest status enum grows
    `year_mismatch` and `year_ambiguous`; resume-skip rules updated
    accordingly. Orchestration diagram updated to show
    `Phase 2: download-agent × 2`.
  - `skills/process-paper/SKILL.md` (new): single-paper end-to-end
    skill — `--doi` (preferred), `--slug` (PDF already in
    `sources/`), or `--title --author` (fallback). Opt-in
    `--translate` flag dispatches `translate-agent`. Reuses
    search-agent, download-agent, analyse-agent type=B, audit-agent,
    translate-agent with no new agent. No synthesis step;
    `analyse-agent type=B` already produces the full
    `vault/papers/{slug}.md` indistinguishable from
    `process-author` Phase 4 output. Trigger phrases: "处理这篇论文",
    "process paper", "跑这篇 paper", "summarize this paper".
  - Historical implementation plan docs were removed after completion; the
    active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
    the skill / agent files.
  - No bin changes, no Python changes, no user-disk migration.
    process-author manifests with `status: acquired` from earlier
    runs are consumed unchanged; new `status: year_mismatch` /
    `year_ambiguous` entries are treated as `acquired` by downstream
    Phase 3+ (file is on disk, just with a year warning attached).

- **0.27.0** (2026-05-18): **local-agent for cndouban backfill +
  douban_cn related-version probe.** Splits "find the Chinese
  translation of this book" out of the audit pipeline into its
  own narrow-scope agent, and gives the douban_cn source the
  capability to surface translations from a direct hit's other-versions
  block.
  - `agents/local-agent.md` (new): the only agent in quasi whose
    job is filling `cndouban: [...]` onto book frontmatter and
    maintaining `.quasi/audit/translations.json`. Reads
    `quasi-audit run --mode check --json`, filters
    `needs_backfill[]` to `type=book` + `missing=cndouban`, calls
    `quasi-search book --subject cndouban`, writes back. Idempotent
    on already-localised records (even `cndouban: []` is treated
    as "user already decided no Chinese edition exists" and
    skipped).
  - `scripts/search/sources/douban_cn.py`: new related-version
    probe path. When the caller passes `--subject
    zh/chinese/cn/translation/cndouban` **and** the direct search
    returns a hit, the source walks the subject page's `其他版本`
    / `同一作品` block and emits Chinese-like manifestations. Hint
    regex covers mainland presses (人民/三联/商务/译林/中信...)
    plus HK/TW patterns (聯經/時報/麥田/遠流/天下/印書館). Subject
    URL + works URL both normalised against `book.douban.com`.
    Pure addition — non-`zh` queries are unchanged; CJK-author
    fallback to works-page enumeration still triggers when direct
    returns empty.
  - `skills/process-book/SKILL.md`: new Step 6 LOCALISE, dispatched
    foreground after audit. Resume table documents the
    "frontmatter already has `cndouban` ⇒ skip" idempotency.
  - `skills/process-journal/SKILL.md`: Step 6 grows the same
    audit-escalation loop that `process-book` has had — items the
    audit escalates get one regeneration pass via `analyse-agent`
    (type B for journal papers), then re-audit; if still escalated,
    report and bail. Brings the two skills into structural parity.
  - `scripts/audit/audit.py` + `scripts/audit/sweep/README.md`:
    docstring/prose updates reflecting that online metadata
    backfill is its own workflow, not orchestrated by `audit-agent`.
    Sweep README's "Integration plan (future)" section is now
    just "Integration" — `quasi-audit backfill` is the actual
    dispatcher.
  - `agents/search-agent.md`: drop one redundant "不要在 prompt 里
    推该调哪个源" paragraph — the I/O contract already covers this.
  - `tests/test_douban_cn_en2zh.py` (new): end-to-end mock-driven
    test for the English-title → Chinese-translation pipeline.
    `test_source_douban_cn.py` grows a case proving the
    related-version probe fires when `--subject zh` and direct hits
    exist, and stays out of the way otherwise.
  - `docs/`: delete four stale design docs —
    `ADR-002-capability-layering.md`, `LAYERS.md`,
    `EXPERIENCE-vault-metadata-backfill.md`,
    `processing-schema.md`. The layered architecture they
    described was simplified away in 0.18.0; keeping them around
    misled both humans and Claude Code sessions opened in the
    source tree.

- **0.26.0** (2026-05-18): **artifact path discipline.** Sharpens the
  `processing/` vs `.quasi/` split on "would the user ever open this
  file?" Everything plumbing-shaped — manifests, indices, audit state,
  dispatch scratch, downloaded temp PDFs — moves into `.quasi/`.
  `processing/` ends minimal: `chapters/` (extracted text the user
  reads when PDFs are unclear) and `translations/` (translated PDFs).
  - Group B: `processing/proofread/{stem}/sections.json` →
    `.quasi/proofread/{stem}/`. Cleanup goes from optional to required.
  - Group C: `/tmp/{journal,topic,snowball}-pdfs/` →
    `.quasi/temp/{journal-pdfs/{name}, topic-pdfs/{name}, snowball-pdfs}/`.
    Brings temp PDFs into the project tree where they're inspectable
    and not subject to macOS /tmp/ reaping.
  - Group D: audit pipeline consolidates under `.quasi/audit/`.
    `scripts/typecheck/typecheck.py` `OUT_DIR` moves from `.quasi/`
    top-level to `.quasi/audit/`. `agents/audit-agent.md` doc paths
    fixed across multiple stale references (state.json,
    translations.json, typecheck-*). `scripts/schemas/book.py` description
    string + `docs/ARCHITECTURE.md` echo updated.
  - Group E: `processing/authors/{name}/manifest.json` →
    `.quasi/authors/{name}/manifest.json`. Driver file for the
    process-author phase state machine; user never opens.
  - Group A: residual cleanup. The bulk of the citation move was
    already merged in 0.22.x (`ct_dir = .quasi/citation/...`); this
    release finishes the trailing edges — citecheck-agent example,
    citation.py docstring, wrap-up 中间产物 tree. `render.py:741`
    has a stale reference too but render.py is deprecated per 0.22.0
    and skipped here.
  - User-disk migration: only `authors/{name}/manifest.json` carries
    a real caveat — any author run paused mid-flight loses its
    `--resume` state on upgrade. Finish or abandon before upgrading.
    Other stale dirs (`processing/citation/`, `processing/proofread/`,
    `processing/audit/`, top-level `.quasi/typecheck-*`) become
    harmless orphans the user can `rm -rf` at leisure.
  - Historical implementation plan docs were removed after completion; the
    active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
    the skill / agent files.

- **0.25.2** (2026-05-18): **rename citation-agent → citecheck-agent.**
  Naming consistency pass: most agents in quasi are verb-form
  (`search-agent` / `download-agent` / `extract-agent` / `proofread-agent` /
  `translate-agent` / `audit-agent` / `analyse-agent`); `citation-agent`
  was a noun-form outlier. Renamed to `citecheck-agent` (compare
  "spellcheck") to bring it into line.
  - `agents/citation-agent.md` → `agents/citecheck-agent.md` (`git mv` +
    frontmatter `name:` update).
  - Caller / cross-reference updates in `skills/wrap-up/SKILL.md`
    (Phase 2.2 dispatch + prose), `agents/proofread-agent.md` (cross-ref
    in 不动清单), `docs/ARCHITECTURE.md` (pattern table + DAG).
  - Historical references in `CLAUDE.md` Recent Changes entries
    (0.16 / 0.17 / 0.18 / 0.20 / 0.22 / 0.25.1) and in the committed
    spec / plan docs are **left intact** — they record what the agent
    was called at the time.
  - Caller-visible breaking change: any external invocation
    `Agent("quasi:citation-agent", ...)` must switch to
    `Agent("quasi:citecheck-agent", ...)`. All in-tree callers updated
    in the same commit.

- **0.25.1** (2026-05-18): **citation-agent vault-grounded judgment.**
  Phase 2.2 of `quasi:wrap-up` historically had `citation-agent` judge
  context-fit by reading `biblio.json` metadata fields
  (`title / journal / themes / publisher`) plus LLM prior knowledge.
  That meant judgments for obscure / non-English / idiosyncratically-read
  works degraded into hallucination. Re-grounded:
  - `agents/citation-agent.md` rewritten so each candidate is judged by
    reading the user's actual vault summary file (`vault/papers/{slug}.md`
    or `vault/books/{slug}/00-overview.md`) via `candidate.path` — already
    present in manifest since 0.17.0. New "严禁仅凭 title / publisher /
    LLM 先验知识判断" guard in the judgment guidance.
  - `biblio.json` dropped from the agent's input contract.
    `skills/wrap-up/SKILL.md` Phase 2.2 dispatch no longer passes
    `biblio:` to the agent. `biblio.json` is still produced upstream and
    consumed by `resolve.py` (for manifest building) and `emit_bib.py`
    (for the final .bib) — those uses are unchanged.
  - No Python script changes. `path` field on candidate was already
    propagated from `biblio.py:230` → `resolve.py:101` since the 0.17.0
    citation refactor; this release just starts using it.
  - Token cost: net byte volume to the agent goes **down** (drops a
    whole-vault frontmatter index, picks up a handful of scoped summary
    reads per batch). Main-process context unaffected — same prompt
    shape with one fewer path.
  - Historical implementation plan docs were removed after completion; the
    active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
    the skill / agent files.

- **0.25.0** (2026-05-18): **agent surface cleanup post-search-refactor.**
  Lands the long-lived `quasi-arch-refactor` branch into main and tidies
  the agent file naming after 0.24.0's atomic search-bin cutover.
  - `agents/new-discover-agent.md` → `agents/search-agent.md` (146 → 119
    lines). Frontmatter `name:` updated; content rewritten against the
    new bin: dropped the trust/priority table (bin does
    `match_and_priority` internally), dropped per-source fallback table
    (bin internal fallback handles douban_cn works-page / etc), fixed
    envelope shape to `{kind, query, results, diagnostics}`, corrected
    source counts (8 book + 3 paper), confidence heuristic now keyed on
    `sources_hit` + `conflicts`, output protocol renamed
    `DISCOVER_RESULT` → `SEARCH_RESULT`.
  - `agents/discover-agent.md` deleted — superseded by `search-agent`;
    all callers (process-author, wrap-up Phase 2.5, process-book Step 0)
    migrated on the refactor branch.
  - `process-author/SKILL.md` and `scripts/search/context.md` rename
    references updated.
  - No bin-layer change. Pure agent file rename + caller rewire.

- **0.24.0** (2026-05-17): **search bin complete refactor (BREAKING).**
  Historical implementation plan docs were removed after completion; the
  active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
  the skill / agent files.
  - 2137-line `scripts/search/search.py` replaced by sectioned ~700-line
    `search.py` + 9 per-platform adapters in `sources/`.
  - CLI: only two verbs left — `quasi-search book` / `quasi-search paper`.
    `metadata` / `validate` / `scholar` / `backfill` / `cndouban` / `books` /
    `papers` removed entirely (no back-compat).
  - AA file-locate moved to `scripts/download/aa.py` (Python import only,
    no CLI verb). `download-agent` calls it directly.
  - Backfill dispatcher + sweep scripts moved to `scripts/audit/`.
    `quasi-audit backfill --strategy X` replaces `quasi-search backfill`.
  - Unpaywall / S2 / Wayback adapters dropped (enrich cascade non-goal).
  - Conflict surfacing: every fan-out call's diagnostics carries
    `conflicts[].evidence` for year / isbn_13 / publisher / page_count /
    authors — process-book Step 0 YEAR_TRIAGE now reads this rather than
    re-calling each source. Generalises 0.21.0's `year_signals` hack.
  - Callers migrated in same PR: `new-discover-agent.md` (delete routing
    table), `process-book` / `process-topic` / `process-author` /
    `wrap-up` (verb rename + remove validate/metadata batch calls),
    `download-agent.md` (AA via Python import), `discover-agent.md`
    (verb rename + delete validate/scholar).

- **0.22.0** (2026-05-17): **citation review pivots to TUI — HTML report
  + structured verdict enum deprecated.** Background: 0.20.0's tab-based
  HTML review still had a coarse fit between agent output shape and what
  the user actually had to do per cite — and earlier reflection on the
  Decisions Report json export (274 entries, ~10% had unstructured-note
  carryover that the buckets couldn't capture) showed the agent's
  structured verdict was both token-wasteful and less useful than a
  short context-fit note. User's diagnosis: "我们之前犯的错就是太结构化了".
  - **citation-agent rewritten** to output a minimal `{key, picked_slug,
    flag, note}` per cite. Drops the 4-way verdict enum (ok /
    context-mismatch / maybe-vault-typo / missing-from-vault) entirely.
    Agent only does two things now: pick the bib_source from candidates
    (single → the only one; multi → context-fittest), and flag ok or
    review for upper-layer triage. Note is free-form Chinese.
  - **wrap-up Phase 2 restructured** into 2.1 parse+resolve → 2.2
    citation-agent (single+multi only) → 2.3 discover-agent recover
    (miss only) → **2.4 TUI 审定** → 2.5 decisions.json + emit-bib.
    Phase 2.4 is a main-process AskUserQuestion loop, walking bins in
    dimension order (`review_single` / `review_multi` / `miss_recover` /
    `miss_orphan`) — `flag=ok` cites auto-accept with no user prompt.
    Each prompt shows mention snippet + agent's picked_slug + note;
    options vary by bin (accept / pick another candidate / mark
    draft-rewrite / vault-todo / skip).
  - **HTML review.html no longer driven by the skill.** `render.py` /
    `quasi-helpers citation render` is retained on disk but is now
    **stale** — it expects the old verdict enum (`ok` / `context-mismatch`
    / `maybe-vault-typo` / `missing-from-vault`) and will not render
    cleanly against the new `{key, picked_slug, flag, note}` batch
    format. Will be either rewritten against the new shape or deleted
    in a future minor; not blocking. The Phase 3 SUMMARY HTML is
    dropped — TUI prints a final stats block + paths inline.
  - **decisions.json schema preserved at the seams** — top level still
    `by_key: {key: {bib_source, decision, note}}` (what emit_bib.py
    consumes via `_pick_vault_slug`) plus `vault_todo[]` and
    `draft_rewrites[]` arrays for the user's follow-up work. emit_bib
    unchanged.
  - `--citation-only` flag now skips Phase 0/1/3 (cleanup), runs only
    Phase 2 (parse → agent → recover → TUI → emit). `--no-recover` still
    skips 2.3.

- **0.21.0** (2026-05-17): **year triage overhaul — N-source contract,
  structured PDF year signals, Google Books via dokobot.** Triggered by a
  failure case where Simondon's *Imagination and Invention* (UMN Press
  English translation, canonical year 2023) kept finalising as 2022.
  Root causes were 4 independent bugs stacked:
  - `_guess_year` in `scripts/download/download.py` returned the *first*
    `\b(?:19|20)\d{2}\b` regex hit in front matter — for translations this
    is almost always the original-language year ("Originally published in
    French as ... 1965"). Replaced with `_extract_year_signals` returning
    a structured dict `{first_published, copyright_year, original_year,
    other_years, best_guess, evidence_text}`. Anchors on
    "First published / First edition / Published" patterns, treats
    "Copyright YEAR" separately, and never lets "Originally published"
    or "Translated from" leak into best_guess. Includes a Q4-press
    heuristic: if `copyright == YEAR` and `YEAR+1` or `YEAR+2` also
    appears in front matter, prefer the later one (typical for press
    books copyrighted in Q4 and shipped the following year).
    `verify_book_file` returns `year_signals` alongside `year`;
    `finalize_book_identity` propagates it into the manifest entry.
    Back-compat shim `_guess_year` still exists, calling
    `_extract_year_signals(...)["best_guess"]`.
  - `process-book/SKILL.md` Step 0 prompt previously asked the agent
    for a slug / ol / pdf 3-way compare but named the discover-side year
    `ol_year` regardless of which source it came from — almost always
    Anna's Archive, since AA is the only source that yields an MD5.
    Rewritten as YEAR_TRIAGE: agent reports per-source years separately
    (`source_years: {google_books, openlibrary, openalex, anna_archive}`),
    per-pattern PDF signals (`pdf_signals: {first_published,
    copyright_year, original_year, other_years}`), a `recommended_year`
    with a one-line `recommendation_reason`, and a `verdict ∈ {MATCH,
    MISMATCH, AMBIGUOUS}`. Only `MATCH` finalises the file rename;
    other verdicts keep the `.tmp.{ext}` and surface the full triage
    block to the skill main process for user adjudication.
    `download-agent.md` finalize-doc updated to describe the new
    `year_signals` field and the N-source contract.
  - `search_google_books` was hitting the unauthenticated
    `googleapis.com/books/v1/volumes` endpoint, which returns HTTP 429
    with `RATE_LIMIT_EXCEEDED` (quota=0 on the default project) — i.e.
    the Google Books source was silently dead, cutting cross-verification
    from 3 sources to 2 without anyone noticing. Refactored into
    `_search_google_books_http` (existing path) + `_search_google_books_via_doko`
    (new, scrapes `google.com/search?tbm=bks` via `dokobot read --local`,
    falls back to remote mode if no bridge installed). Wrapper detects
    HTTP 429 / `RATE_LIMIT_EXCEEDED` and dispatches automatically.
    Returns parsed entries (title / authors / year via `AUTHOR · YEAR`
    pattern) plus a `raw_doko_text` field so agents can re-parse when
    the structured parse looks thin.
  - The agent-prompt heuristic "pdf_year = 出现的最大 published year,
    排除 reprint dates" couldn't distinguish copyright year from
    publication year — the new N-source contract makes the agent
    enumerate both `copyright_year` and `first_published` separately
    instead, so the skill main process sees the actual structure.

  Net: Simondon's book now triages as `pdf_signals.first_published=2023,
  pdf_signals.copyright_year=2022, pdf_signals.original_year=1965`,
  GB+OL=2023, AA=2022 — `recommended_year=2023` with reason "first_published
  beats copyright by 1 year (Q4 press lag)", and the slug `-2017` shows
  up as MISMATCH for user correction rather than auto-finalising to 2022.

- **0.20.0** (2026-05-17): **citation review UI — tabs by dimension,
  decisions grouped by side-effect.** Background: the previous review.html
  rendered a flat table with uniform `✓ ✗ ?` per row whose "✓ accept agent
  suggestion" semantics differed wildly across statuses (apply draft rewrite
  / run vault mv / pick candidate / nothing-to-apply for `ok`). User found
  the buttons misleading — particularly `ok` rows showing "accept" when
  there's nothing to accept, and a sea of `?` for rows agent didn't process.
  - render.py: replaced the 3-state filter (全部/需处理/已通过) with a
    7-tab nav by display_status: 全部 / 挑候选 / 修 draft / 修 vault /
    补 vault / 等 agent / ✓ 通过. Each tab shows count.
  - new `_action_widget()` renders per-dimension actions:
      ok                  → "✓ 通过" read-only badge
      pending             → "⏳ 等 agent" read-only badge
      context-mismatch    → [✓ 应用] [✗ 保留原引] (default 应用)
      maybe-vault-typo    → [✓ 执行 rename] [✗ 忽略] (default 忽略;
                            renames are destructive, opt-in)
      missing-from-vault  → [✓ 加待跑] [✗ 忽略] (default 加 if Phase 2.5
                            recovered with ≥medium confidence)
      multi-hit           → badge → "展开选 bib chooser radio"
  - JS exportDecisions now emits 4 grouped buckets:
      draft_rewrites     (context-mismatch + applied)
      vault_renames      (maybe-vault-typo + applied)
      vault_todo         (missing-from-vault + applied)
      multi_hit_picks    (multi-hit + bib chosen)
    plus a `skipped` group and a flat `by_key` for backward compat.
  - apply-bar at top of report instructs user to run
    `quasi-helpers citation apply <decisions.json>` (subcommand not yet
    implemented — coming in next minor version; for now decisions.json
    is enough to drive things manually).

- **0.19.1** (2026-05-17): wrap-up `--citation-only` flag.
  Skips Phase 0 (audit) + Phase 1 (proofread) + Phase 4 (cleanup), runs
  Phase 2 + 2.5 + 3 only. Use after补 vault'd a few books — re-emit bib
  in seconds without re-proofreading. Also documents `--no-recover` and
  `--audit-first` flags more explicitly in the call-shape section.

- **0.19.0** (2026-05-17): **wrap-up Phase 2.5 — online citation recovery.**
  When citation-agent flags an entry as `missing-from-vault`, the existing
  flow could only say "vault 缺,补完再重跑". This release adds an online
  step: discover-agent gains a new `mode=recover-citation` that takes the
  citation key + author + year_hint + mention_context + citation-agent's
  prior-knowledge guess, hits quasi-search (Crossref/OL/AA + scholar
  fallback), and emits an `online_recovery` record with title / author /
  year / ISBN / DOI / publisher / confidence / suggested_slug /
  process_book_cmd. wrap-up dispatches one discover-agent per missing
  entry in parallel (cap 4) after citation-agent finishes; render.py
  merges `verdicts/recovery-*.json` into the review UI so each
  missing row shows a "🔍 在线 recover" block with the recovered ID.
  This converts vault-todo from "list of names to look up" into "list of
  ready-to-paste `/quasi:process-book {slug}` commands". Opt-out with
  `/quasi:wrap-up <draft> --no-recover` to skip the online step.

- **0.18.1** (2026-05-17): process-book Step 0 hardening.
  - Self-dispatches download-agent when `sources/{slug}.{epub,pdf}` is
    absent — no longer bails out telling the user to "先用 process-author".
    The skill is orchestration; acquisition is part of orchestration.
  - download-agent prompt now replicates process-author's
    discover→download→finalize 3-stage chain (N=1 version): pre-download
    `quasi-search books` records `ol_year`, post-download Read PDF first
    3 pages records `pdf_year`, 3-way compare against `slug_year`. Any
    mismatch returns `YEAR_MISMATCH` report (skill main process decides
    whether to correct slug or accept) — file kept as `.tmp.{ext}` until
    resolution. Prevents the "user-supplied slug year propagating through"
    failure mode (e.g. user passes `simondon-...-2024` for a book whose
    canonical first English edition is 2023).

- **0.18.0** (2026-05-17): **Layer-cleanup refactor (BREAKING).** End-to-end
  rework of the bin / agent / skill split per `docs/LAYERS.md` and
  `docs/ARCHITECTURE.md`. Drives Pattern B (skill 直调 bin) out of the
  layer model by aggregating skill helpers into a single `quasi-helpers` bin.
  - **bins**: 13 → 6. Deletions: `quasi-typecheck`,
    `quasi-autofix-mechanical`, `quasi-proofread`, `quasi-citation`,
    `quasi-extract-{epub,ocr,split}`, `quasi-journal-{fetch,report}`,
    `quasi-synthesize-refs`. The last three are **deletion-as-forcing-
    function**: synthesis-agent's journal/topic mode will fail until the
    refs-extraction redesign (Q3) and journal stack rework land. New:
    `quasi-audit {check|fix|emit-bib}` (vault consistency dispatcher),
    `quasi-helpers {proofread|citation} <sub>` (skill orchestration aggregator).
    Subcommand restructure: `quasi-extract {epub|ocr|split}`,
    `quasi-download {paper|book|batch|finalize}` (was flag-based),
    `quasi-search` + `scholar` (dokobot Google Scholar) + `backfill`
    (vault metadata multi-source chain; ingests bts/scripts 8 sweep scripts
    documented in `docs/EXPERIENCE-vault-metadata-backfill.md`).
  - **agents**: `typecheck-agent` → `audit-agent` with new online
    metadata backfill responsibility. `analyze-agent` → `analyse-agent`
    (British spelling). `overview-agent` + `profile-agent` + 原 `synthesis-agent`
    → unified `synthesis-agent` with caller-passed `mode = book|author|
    journal|topic|kb-update`. `scan-agent` / `setup-agent` marked DEPRECATED
    (files retained, not dispatched by new code).
  - **skills**: `citation-snowball/` → `process-topic/` (rename only,
    internal redesign deferred). `wrap-up/SKILL.md` now calls `quasi-helpers
    {proofread,citation} *` and gains a Phase 0 audit-agent dispatch.
    `process-book` / `process-author` migrated to `synthesis-agent(mode=X)` +
    `audit-agent`.
  - **Deferred** (next round): entire journal stack
    (`quasi-journal-{fetch,report}` / `scan-agent` / `/quasi:process-journal`
    skill / `quasi-search journal` subcommand); `setup-agent` redesign;
    `process-topic` internal redesign; `quasi-synthesize-refs` disposition.

- **0.17.0** (2026-05-17): **Citation pipeline refactor — biblio.json as ground truth.**
  Driven by ADR-002 (see `docs/ADR-002-capability-layering.md`): citation
  flow now reads a pre-computed `biblio.json` instead of glob-walking the
  vault each call. New artefacts in `scripts/citation/`:
  - `biblio.py` scans vault frontmatter into `biblio.json` (multi-segment
    author-slug indexing so multi-word surnames like `agard-jones` /
    `fausto-sterling` resolve correctly)
  - `resolve.py` rewritten: input is `parse.json` + `biblio.json`,
    output is `manifest.json` with `{single-hit, multi-hit, miss}` status
    and 4-tier fuzzy fallback (strict → author-only → fuzzy author+year → miss)
  - `render.py` rewritten: single-decision review UI, bib chooser per row,
    top banner for missing-from-vault + maybe-vault-typo
  - `emit_bib.py` (new) renders BibTeX from `biblio.json` keyed by the draft's
    citation set; honours user-picked `bib_source` from decisions.json
  - `citation.py` subcommands: `biblio` / `parse` / `resolve` / `render` /
    `emit-bib` (removed `run` — orchestration belongs in the skill, not the CLI)
  `citation-agent` rewritten as **offline universal consistency judge**
  (no WebFetch / WebSearch): verdict ∈ `{ok, context-mismatch,
  maybe-vault-typo, missing-from-vault}`. Online cross-checking for vault
  metadata moves out of citation entirely (slated for `quasi-audit` in a
  future release). `skills/wrap-up/SKILL.md` is **not yet updated** for the
  new pipeline — TODO next.
- **0.16.0** (2026-05-15): **New `quasi:wrap-up` skill + two reusable agents**
  (`proofread-agent`, `citation-agent`). Drift finalisation in one shot —
  Phase 1 proofread (per-section parallel agents in-place edit typos /
  punctuation / spacing), Phase 2 citation (parse + vault lookup CLI →
  per-batch parallel agents do online cross-verification against Crossref /
  Anna's / Douban via dokobot), Phase 3 summary HTML linking both reports.
  Design rule: **skills only exist for composition; single-task work is
  done by dispatching agents directly** — so no standalone `citation` or
  `proofread` skills. New files: `skills/wrap-up/SKILL.md`,
  `agents/{proofread,citation}-agent.md`,
  `scripts/{proofread,citation}/*.py`,
  `bin/quasi-{proofread,citation}`. Citation parse-step ships a loose-scan
  validator (any paren-with-4-digit-year) to catch what the strict parser
  misses before downstream consumers see the data.
- **0.15.3** (2026-05-13): Doc/script rename — `$PWD` → `$CLAUDE_PROJECT_DIR`
  across all 11 agent prompts, `bin/quasi-typecheck`, and the two typecheck
  scripts' docstrings/help. Aligns with the official plugins-reference
  recommendation: `$CLAUDE_PROJECT_DIR` is set by Claude Code at session start
  and doesn't drift if anything `cd`s; `$PWD` is just the shell's transient
  cwd. `typecheck.py` / `autofix_mechanical.py` `PROJECT_ROOT` resolution now
  consults `CLAUDE_PROJECT_DIR` between the existing `QUA_PROJECT_ROOT`
  escape hatch and the `os.getcwd()` fallback — no behavior change when
  invoked from the project root (the common case), but stable under `cd`.
- **0.15.2** (2026-05-12): PreToolUse hook also propagates `CLAUDE_PLUGIN_ROOT`
  and `CLAUDE_PLUGIN_DATA` to bash subprocesses (in addition to the userConfig
  `QUASI_*` block). Before this, the shims fell back to `~/.cache/quasi/.venv`
  for the venv because `$CLAUDE_PLUGIN_DATA` was unset in Bash-tool env, even
  though the SessionStart hook had already materialised the venv at the
  official `$CLAUDE_PLUGIN_DATA/.venv` (= `~/.claude/plugins/data/<id>/.venv`).
  Now shims use the official path. Users with the old fallback venv can
  `rm -rf ~/.cache/quasi/.venv` to reclaim disk.
- **0.15.1** (2026-05-12): Trim `setup-agent.md` (166 → 122 lines). Drop the
  obsolete "credentials don't live here" callout and "调用方约定 (主 Claude 应
  AskUserQuestion 收集凭据)" section — neither makes sense after 0.15.0's hook
  bridge. No functional change.
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
  purely permissions + system deps + dokobot indicator; the entire `$CLAUDE_PROJECT_DIR/config/`
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

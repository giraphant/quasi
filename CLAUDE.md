# quasi maintainer guide

quasi is a Claude Code plugin for academic reading workflows: discovery, download, extraction, analysis, synthesis, translation, and schema checking.

This file holds only the contracts a maintainer needs before editing. The detail lives in `docs/`:

- `docs/ARCHITECTURE.md` — layers, CLI surface, capability entrypoints, per-agent write ownership, skill routing, Configure/env mapping.
- `docs/PDF_PIPELINE.md` — measured institutional memory of the OCR and translation pipeline. Read it before touching `scripts/extract/` or `scripts/translate/`.
- `docs/SKILL_ORCHESTRATION.md` and `docs/GRAPH_COLLABORATION.md` — maintainer guidance. Active `SKILL.md` files must not cite either directly.
- `docs/CHANGELOG.md` — full version history, newest first; entries carry the why as well as the what.

## Plugin-system facts

- Installed plugins load components from root-level `skills/`, `workflows/`, `agents/`, `output-styles/`, `bin/`, `hooks/`, `monitors/`, `.mcp.json`, and `.lsp.json`.
- `.claude-plugin/plugin.json` is metadata only. Do not place components inside `.claude-plugin/`.
- `.codex-plugin/plugin.json` is the Codex-native package manifest; leave it alone when changing Claude Code runtime components.
- `CLAUDE.md` and `AGENTS.md` are mirrored instruction files for different agent frameworks and must stay byte-for-byte identical.
- Claude Code does not load a plugin-root `CLAUDE.md` as context when quasi is installed as a plugin. Runtime guidance must live in skills, agents, hooks, or scripts.
- quasi targets Claude Code only; the retired Pi and Codex host adapters are recoverable from git history.

## Layers

`skills/` (user-facing drivers) → `workflows/run-stage.mjs` (the only Workflow entry, generated) → `agents/` (goal-owning specialists) → `bin/quasi-*` (stable shell surface) → `scripts/` (deterministic capabilities; `scripts/workflows/` is the editable run-stage TypeScript source; `scripts/schemas/` is the single source of truth for artifact structure) → `scripts/core/` (minimal runtime base for path/frontmatter/json/module-loading helpers; imports nothing above itself).

## Runtime contract

- Skills drive. They observe disk through `quasi-status`, choose the next applicable stage from `Recall → Search → Acquire → Prepare → Analyse → Synthesise → Audit`, dispatch exactly one `kind + stage` (optionally `until`, advancing the kind's fixed stage sequence) per `workflows/run-stage.mjs` call, present typed human gates, and re-observe exact artifacts before continuing. Stage phases name processing progress, never material kinds; every `agent()` call carries its stage through `opts.phase`, and labels begin with the material slug or collection key.
- `run-stage` resolves one descriptor row and, for each requested unit, composes its prompt and schema, invokes one specialist, and returns that unit's complete host-validated receipt. One invocation may fan out across units in the same stage when they write distinct exact outputs; duplicate requests are rejected. With `until`, it advances the kind's fixed sequence, evaluates each stamped receipt's terminal and the owning row's cross-field completion predicate, stops at the first receipt that is not a coherent complete, and returns all receipts in order. It does not branch, retry, join, choose stage order, or keep state across invocations.
- The shared receipt is `quasi.stage.receipt/0.3` with a closed `terminal` union `complete|needs_input|blocked|failed`. The model produces judgement fields and the entire terminal; after validation, the host stamps every top-level single-value bookkeeping `const`, so downstream consumers still receive the full receipt shape. `complete` proves only the exact artifacts required by the next stage and requires `issue:null`; the other terminals carry one typed issue, while `needs_input` also carries concrete candidates, conflict fields, and a user question.
- Agents own professional method, stopping judgement, and local recovery over their declared `quasi-*` capabilities. Do not encode query counts, provider cascades, text-readability heuristics, OCR decisions, chapter replanning, or translation recovery in a skill's stage routing. An agent reads or writes only the exact artifacts in its request; the sole remote-tool exception is `webcard-agent`, which may `WebFetch` the exact URLs returned by `quasi-search kagi` for its one assigned evidence card. Every writer verifies the envelope's exact refs at entry (inputs exist; output state matches the request) and returns `blocked` without writing on mismatch; it never searches for alternative paths.
- The skill main process owns material identity and processing state, derived from `quasi-status` observations plus the current receipt — never a second hidden state file, never writer success inferred from prose, never a second receipt validator, and never reinterpreting a schema-valid failure because it disagrees with the specialist's method.
- StructuredOutput may ask a still-running agent to repair malformed output; that provider-level correction is not a new stage dispatch. A receipt is consumed once. Cross-field checks that JSON Schema cannot express stay small and concrete in the owning descriptor row (exact path join, count equality, coherent manifest generation).
- Unknown writer outcomes stop the run: no duplicate writers, no path discovery outside the envelope, no replay after an ambiguous write. Resume begins with a fresh disk observation.
- Collection and research skills admit child materials directly from disk testimony: the skill runs exact `quasi-status` and consumes its nullable identity plus kind-specific facts before adding a member. Audit has no durable status signal yet; a clean final audit is receipt-proven for the current invocation only.
- Per-agent write ownership, skill routing (`collect-material` / `research-topic` / `finalise-draft`), batch semantics, and topic products are specified in `docs/ARCHITECTURE.md`.

## Path roots

- The current working directory is the project/vault root for user data. Workflow specialists may receive an empty `CLAUDE_PROJECT_DIR`; when it is non-empty it takes precedence, otherwise resolve relative paths from cwd.
- `$CLAUDE_PLUGIN_ROOT` is versioned plugin code, read-only at runtime. `$CLAUDE_PLUGIN_DATA` is persistent plugin data (venvs, caches, EZProxy throttle state); `${CLAUDE_PLUGIN_DATA:-~/.cache/quasi}` is the non-plugin fallback used by shims and bootstrap. `QUA_PROJECT_ROOT` is a legacy compatibility override still accepted by `scripts/core/core.py`; do not introduce it into active skill or agent contracts.
- `vault/` holds user-facing reading outputs; `sources/` holds accepted source files; `processing/chapters/`, `processing/translations/`, and `processing/talks/` hold user-inspectable intermediates; `.quasi/` holds orchestration state, manifests, caches, audit output, and temp downloads. Temp JSON passed to helpers lives under `.quasi/temp/` unless a specific helper contract says otherwise.

## Configure options and env flow

- User-facing options live in `.claude-plugin/plugin.json#userConfig`; `scripts/hooks/inject-userconfig.py::_KEYS` must stay in sync with it. Do not document a Configure option as current unless it exists in both. The full field → env → consumer mapping is in `docs/ARCHITECTURE.md`.
- Claude Code injects configured values into hook/MCP/LSP/monitor subprocesses as `CLAUDE_PLUGIN_OPTION_<KEY>`; Bash tool subprocesses do not receive them. The `PreToolUse` Bash hook (`scripts/hooks/inject-userconfig.py`, registered in `hooks/hooks.json`) prepends `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, and the plugin `bin/` path for commands containing a bare `quasi-` word.
- Scripts read only `QUASI_*` service variables, never `CLAUDE_PLUGIN_OPTION_*`. On macOS both the hook and every Python-facing shim fill missing `QUASI_*` values through the shared Keychain helper (`scripts/load-keychain-env.sh`), so secret values never enter argv; explicit `QUASI_*` values take precedence. Non-macOS keeps the direct-export fallback. Kagi is special only at the subprocess edge: `QUASI_KAGI_SESSION_TOKEN` maps to `KAGI_SESSION_TOKEN` for `kagi` CLI calls.

## Active CLI surface

```bash
quasi-search book|paper ...
quasi-download book candidates|fetch ...
quasi-download paper fetch|diagnose ...
quasi-download accept ...
quasi-extract epub|text|ocr|split ...
quasi-transcribe run|classify|silent ...
quasi-audit --path ...
quasi-status --kind paper|book|talk|author|topic --slug SLUG --json
quasi-status --kind translation --slug SLUG --target-language TAG --json
quasi-status --scan --json
workflows/run-stage.mjs  # Workflow input: kind, slug, stage, context
quasi-helpers proofread prepare|cleanup ...
quasi-helpers citation parse|biblio|resolve|review-cards|emit-bib ...
quasi-helpers localise scan|write ...
quasi-helpers talk compress-media ...
quasi-helpers vault resolve --items-json|--items-file ...
quasi-doctor [--json] [--sync] [--profile ...]
quasi-translate SLUG [--backend immersive|pdf2zh] ...
```

## Artifact ownership and builds

- Four ownership layers: `agents/*.md` owns the worker's stable role, common request/receipt protocol, and epistemic rules; `scripts/schemas/{type}.py` plus `scripts/schemas/body.py` owns frontmatter, path/identity fields, H1, section order, block shapes, and section semantics; `scripts/schemas/pipeline.py` owns run-stage kind/stage order, operation identity (phase, effect, and agent), receipt-to-context carries, and exact artifact path templates consumed by both the Workflow build and `quasi-status`; descriptor rows under `scripts/workflows/operations/rows/` (one Operation factory: `scripts/workflows/operations/define.mts`) own only operation behavior — request/receipt schema construction, exact-ref envelopes, and operation-only evidence rules. Rows must not duplicate artifact structure or pipeline identity; agents never import the schema registry — the build injects canonical producer/search projections.
- For an Agent-owned boundary, prefer a self-contained JSON envelope: goal, bounded identity, exact refs, available capabilities, and the receipt schema. Do not surround a sufficient JSON envelope with a second prose contract; a descriptor-row request states the goal and capabilities without transcribing the specialist's decision tree.
- Edit `scripts/schemas/` when changing a Paper, Chapter, Book overview, or Talk output structure, then run `npm run build:workflows`. `scripts/workflows/artifact-contracts/generated.mjs`, its generated declarations, and `workflows/run-stage.mjs` are generated artifacts and must not be hand-edited. esbuild compiles the editable `.mts` workflow layer into the bundle at build time; `npm run check:workflows` verifies schema/projection/operation/bundle parity and runs strict `tsc --noEmit` checking over those TypeScript sources.
- A deterministic CLI may write an artifact only when its command contract names that output path.
- Paper metadata merging treats Crossref as the authority for the journal container title and decodes its HTML entities at the adapter boundary. Do not let asynchronous adapter completion order choose `venue`; OpenAlex may omit meaningful punctuation from the same journal name.
- Removed legacy bins must not reappear in active docs or prompts: `quasi-citation`, `quasi-proofread`, `quasi-download batch`.

## Extraction and translation invariants

The measured reasoning behind each rule is in `docs/PDF_PIPELINE.md`; do not relax one without reading its paragraph there.

- `quasi-extract ocr` defaults to DS OCR2 and pins `mlx-vlm==0.3.12`; 0.4+ breaks the model's loader and generate path. Do not reject a candidate OCR model for requiring transformers 5.x. Never pass `trust_remote_code=True` when loading DS OCR2 (`tests/test_extract_cli.py` guards it). Fallback is tesseract.
- `--layout` writes a replacement text layer drawn over the scan image (never under it), snaps line sizes to the book-wide dominant size, flows one textbox per MinerU-grouped paragraph at a flat `SHRINK` 0.90, strips old text layers including Form XObjects, and skips pages with no image object (born-digital pages keep their own text).
- Both translate backends share one output contract (`processing/translations/{slug}-{full-target-tag-lower}.pdf`, alternating original/translated pages, bookmarks) and both must run `tounicode.py::repair_pdf` before the per-page-median coverage gate. Rejected or uncertain generations stay in their fenced `processing/translations/.{stem}.translate-*` directory and never become canonical output.
- Backend selection is user config (`translate_backend`), not a free caller argument. For pdf2zh, a root-only `translate_base_url` gets `/v1` appended; explicit paths are preserved. Provider credentials stay out of argv.

## Skill writing schema

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

`任务` is one short positive sentence naming the work; use `输入` unless the skill has a real machine-facing invocation API. Frontmatter `description` is only a routing hint describing user intent — no trigger-word lists, history notes, or phase walkthroughs. Pseudocode helpers in skill files (`parse_args`, `read_json`, `write_json`, `write_temp_json`, `format_yaml_list`, `exists`) are maintainer shorthand for main-process Claude Code actions, not a hidden runtime library.

## Runtime state and dependencies

- `bin/` tools may be invoked as bare commands while the plugin is enabled. Python dependencies are declared in `scripts/requirements.txt`; `scripts/bootstrap-venv.sh` installs them into `${CLAUDE_PLUGIN_DATA}/.venv` (SessionStart hook; each shim also self-bootstraps). Do not put pip installs back inside individual shims.
- Optional out-of-venv deps are fail-soft: `ffmpeg`/`whisper-cli`/`uvx` for transcription, `mlx-vlm` for DS OCR2 OCR, `mineru-vl-utils` for `--layout` paragraph grouping.
- EZProxy global throttle state lives under `${CLAUDE_PLUGIN_DATA:-~/.cache/quasi}/ezproxy-throttle.state` and is owned by `scripts/download/download.py`.

## Change checklist

When changing config, runtime state, or handoff contracts:

1. Keep `.claude-plugin/plugin.json` and `scripts/hooks/inject-userconfig.py::_KEYS` in sync.
2. Keep `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` versions in sync for releases.
3. Keep `CLAUDE.md` and `AGENTS.md` byte-for-byte identical (verify with `cmp -s CLAUDE.md AGENTS.md`).
4. Update active skills only when the executing model needs the information at runtime.
5. Update agent files when an agent input/output contract changes.
6. Update tests that guard dead names, frontmatter routing hints, CLI surface, or manifest schema and run `pytest tests/test_dead_names.py tests/test_skill_orchestration.py -q`. Orchestration tests assert cross-file coherence (shared names, stages, schema versions) and dead-name quarantine — never the presence of specific prose sentences.
7. Run `claude plugin validate .` after manifest changes.

## Debugging gotchas

- Dispatch E2E workers with cwd set to the intended project root. `CLAUDE_PROJECT_DIR` may be empty inside a Workflow specialist; when non-empty it overrides cwd, but an in-prompt `cd` is never a substitute for correct dispatch placement.
- A dead Workflow subagent can leave no usable Stage receipt. The skill must stop, re-observe disk state, and resume or reconcile explicitly; it must never concurrently replay a writer whose outcome is unknown.
- `claude -p --output-format json` stdout contains the final session envelope, not a full stage/tool transcript. For headless E2E evidence, inspect the session JSONL and per-Workflow JSON sidecars as well as captured stdout.

## Changelog

Full version history lives in `docs/CHANGELOG.md` (newest first, entries carry the why as well as the what).

# quasi maintainer guide

quasi is a Claude Code plugin for academic reading workflows: discovery, download, extraction, analysis, synthesis, translation, and schema checking.

## Important plugin-system facts

- Installed plugins load components from root-level `skills/`, `workflows/`, `agents/`, `bin/`, `hooks/`, `monitors/`, `.mcp.json`, and `.lsp.json`.
- `.claude-plugin/plugin.json` is metadata only. Do not place components inside `.claude-plugin/`.
- `.codex-plugin/plugin.json` is the Codex-native package manifest. Codex discovers `skills/` and default `hooks/hooks.json`; it does not currently install plugin-root `agents/` as custom roles. Quasi loads those Markdown contracts through its runners, and `quasi-codex-agents` explicitly generates project/user Codex TOML roles when requested.
- `CLAUDE.md` and `AGENTS.md` must stay byte-for-byte identical. They are mirrored instruction files for different agent frameworks, not separate reader-specific guides.
- Claude Code does not load a plugin-root `CLAUDE.md` as context when quasi is installed as a plugin. Runtime guidance must live in skills, agents, hooks, or scripts.

## Current runtime contract

### Layer ownership

- `skills/` own user-facing workflow state machines: input normalisation, manifests, skip rules, human gates, and dispatch order.
- `workflows/` owns host-neutral deterministic graphs. Graphs use only the injected `agent`, `parallel`, `phase`, `log`, and `args` primitives.
- `agents/` are specialist workers. They call only the public `quasi-*` CLI or read/write the exact local artifact named in their contract. The sole remote-tool exception is `webcard-agent`, which may `WebFetch` the exact URLs returned by `quasi-search kagi` for its one assigned evidence card.
- `bin/quasi-*` is the stable shell surface exposed to agents and skills.
- `scripts/` contains deterministic capability entrypoints and build-only sources;
  `scripts/workflows/` is the editable host-neutral graph source.
- `scripts/schemas/` is the single source of truth for artifact frontmatter and body structure.
  Agents do not import it directly: the workflow build injects canonical producer/search
  projections, while audit/typecheck/migration consume the registry in Python.
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
- For commands containing a bare `quasi-` word, the hook prepends `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, and the plugin `bin/` path. On macOS, configured `QUASI_<KEY>` values are loaded inside the Bash process through the same Keychain helper used by the shims, so credential values never enter the rewritten command or process argv; non-macOS retains the direct-export compatibility fallback.
- Scripts read only `QUASI_*` service variables, not `CLAUDE_PLUGIN_OPTION_*`.
- Kagi is special only at the subprocess edge: quasi reads `QUASI_KAGI_SESSION_TOKEN` and maps it to `KAGI_SESSION_TOKEN` for `kagi` CLI calls.
- Do not document a Configure option as current unless it exists in `plugin.json#userConfig` and is forwarded by `_KEYS`.

Current userConfig mapping:

| Configure field | Hook env input | Script env output | Main consumer |
| --- | --- | --- | --- |
| `anna_donator_key` | `CLAUDE_PLUGIN_OPTION_ANNA_DONATOR_KEY` | `QUASI_ANNA_DONATOR_KEY` | `scripts/download/aa.py` |
| `cookiecloud_server` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_SERVER` | `QUASI_COOKIECLOUD_SERVER` | `scripts/download/cookiecloud.py` |
| `cookiecloud_uuid` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_UUID` | `QUASI_COOKIECLOUD_UUID` | `scripts/download/cookiecloud.py` |
| `cookiecloud_password` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_PASSWORD` | `QUASI_COOKIECLOUD_PASSWORD` | `scripts/download/cookiecloud.py` |
| `cookiecloud_ezproxy_domain` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_EZPROXY_DOMAIN` | `QUASI_COOKIECLOUD_EZPROXY_DOMAIN` | `scripts/download/cookiecloud.py` |
| `cookiecloud_ezproxy_base_url` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_EZPROXY_BASE_URL` | `QUASI_COOKIECLOUD_EZPROXY_BASE_URL` | `scripts/download/cookiecloud.py` |
| `immersive_auth_key` | `CLAUDE_PLUGIN_OPTION_IMMERSIVE_AUTH_KEY` | `QUASI_IMMERSIVE_AUTH_KEY` | `scripts/translate/immersive_translate.py` |
| `translate_backend` | `CLAUDE_PLUGIN_OPTION_TRANSLATE_BACKEND` | `QUASI_TRANSLATE_BACKEND` | `bin/quasi-translate` |
| `translate_base_url` | `CLAUDE_PLUGIN_OPTION_TRANSLATE_BASE_URL` | `QUASI_TRANSLATE_BASE_URL` | `scripts/translate/pdf2zh_translate.py` |
| `translate_api_key` | `CLAUDE_PLUGIN_OPTION_TRANSLATE_API_KEY` | `QUASI_TRANSLATE_API_KEY` | `scripts/translate/pdf2zh_translate.py` |
| `translate_model` | `CLAUDE_PLUGIN_OPTION_TRANSLATE_MODEL` | `QUASI_TRANSLATE_MODEL` | `scripts/translate/pdf2zh_translate.py` |
| `kagi_session_token` | `CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN` | `QUASI_KAGI_SESSION_TOKEN` | `scripts/search/search.py`, `scripts/search/sources/douban_cn.py`, `scripts/download/download.py` |
| `soniox_api_key` | `CLAUDE_PLUGIN_OPTION_SONIOX_API_KEY` | `QUASI_SONIOX_API_KEY` | `scripts/transcribe/engines.py` |

### State and handoff contracts

- The skill main process owns workflow state files: manifests, decisions, search caches, recovery files, and `.quasi/<domain>/...` orchestration artifacts.
- `search-agent` returns JSON and does not write files.
- `download-agent` accepts or rejects candidates through `quasi-download`; it returns `DOWNLOAD_RESULT.per_item` and does not own caller manifests.
- `extract-agent` writes chapter extraction output and `processing/chapters/{slug}/manifest.json`.
- `analyse-agent`, `synthesis-agent`, `proofread-agent`, and `citecheck-agent` write only the exact product path assigned by the caller.
- `steer-agent` owns `vault/topics/{slug}/02-outline.md` (the topic research outline; users may hand-edit it between runs) and returns sub-question-targeted candidates; it writes nothing else.
- `webcard-agent` turns one topic `web_task` into one evidence card at the caller-named `vault/topics/{slug}/cards/{card-slug}.md`; it writes nothing else, and returns `status: empty` rather than writing a card it could not verify. Cards are not vault analysis products: they travel on their own `cards` channel (outline `subquestions[].cards`, synth `card_paths`) and never enter the `book|paper|talk` corpus table.
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
quasi-extract epub|text|ocr|split ...
quasi-transcribe run|classify|silent ...
quasi-audit --path ...
quasi-helpers proofread prepare|cleanup ...
quasi-helpers citation parse|biblio|resolve|review-cards|emit-bib ...
quasi-helpers localise scan|write ...
quasi-helpers vault resolve --items-json|--items-file ...
quasi-doctor [--json] [--sync] [--profile ...]
quasi-translate SLUG [--backend immersive|pdf2zh] ...
quasi-pi-runner --script PATH --args-file JSON [--cwd PROJECT] ...
quasi-codex-agents (--project PATH|--user) [--check] [--json]
quasi-codex-driver --script PATH --args-file JSON [--cwd PROJECT] ...
quasi-codex-runner --script PATH --args-file JSON [--cwd PROJECT] ...
```

`scripts/workflows/` contains the modular Claude Workflow graph source and generated
artifact-schema projections. `npm run build:workflows` deterministically bundles it
into the committed `workflows/process-material.mjs` entry; never hand-edit the
generated bundle.

Artifact writing has three ownership layers:

- `agents/*.md` owns the worker's stable role, common request/receipt protocol,
  epistemic rules, and generic execution sequence.
- `scripts/schemas/{type}.py` plus `scripts/schemas/body.py` owns frontmatter,
  path/identity fields, H1, section order, block shapes, table columns, and
  section semantics. Producer projections omit migration-only aliases.
- `scripts/workflows/operations/*.mjs` owns request/receipt schemas, exact refs,
  dynamic frontmatter seeds, and operation-only evidence rules. It must not
  duplicate artifact structure.

Edit `scripts/schemas/` when changing a Paper, Chapter, Book overview, or Talk
output structure, then run `npm run build:workflows`. The build updates
`scripts/workflows/artifact-contracts/generated.mjs` and
`workflows/process-material.mjs`; both are generated artifacts and must not be
hand-edited. Non-artifact behavior such as acquisition policy is structured
inside its owning `scripts/workflows/operations/*.mjs` request rather than kept
as a prose prompt pack. `npm run check:workflows` verifies
schema/projection/operation/bundle parity.

The Paper loop is the first Operation-based vertical slice: it normalises every
source through `quasi-extract text`, asks a read-only Agent to judge semantic
readability, follows a bounded OCR recovery edge when needed, and gives one
common `analyse-agent` a Paper-specific operation envelope. Writer receipts are
strictly reconciled against exact target identity; a malformed or ambiguous
writer receipt is an unknown outcome and must block rather than retry.

`quasi-pi-runner` is the Pi-only adapter for the existing `workflows/process-material.mjs` graph. It uses the official Pi SDK already installed with Pi, loads `quasi:<name>` definitions from root `agents/`, and deliberately implements only `agent`, `parallel`, `phase`, `log`, and `args`; do not add a third-party workflow compatibility dependency. Claude Code keeps using its native Workflow path.

`quasi-codex-runner` reuses the same `createRunner` graph runtime and replaces only the worker invoker with ephemeral `codex exec --output-schema` calls. Codex runs workers in `workspace-write`, grants network because acquisition commands require it, and adds only plugin data as an extra writable root. Claude agent model aliases are not mapped in this first compatibility release; their reasoning tiers map to `opus=high`, `sonnet=medium`, and general-purpose `low`. `QUASI_CODEX_MODEL` and `QUASI_CODEX_REASONING_LEVEL` may override the Codex worker defaults.

`quasi-codex-agents` is the explicit native-role installation boundary. Root `agents/*.md` remains the sole source of truth; `--project PATH` generates `PATH/.codex/agents/quasi_*.toml`, while `--user` targets `${CODEX_HOME:-~/.codex}/agents`. It writes only `name`, `description`, and `developer_instructions`, inherits the coordinator model, does not delete unrelated files, and supports a non-mutating `--check`. Codex loads these files at thread startup, so a new thread is required after syncing.

`quasi-codex-driver` is the Codex GUI path. It runs the same graph but turns each `agent()` into a bidirectional JSONL `agent_request`; each event carries both the cross-host `agent_type` and the registered `codex_agent_type` (`quasi_download`, `quasi_analyse`, etc., or built-in `worker` fallback). The full worker contract is stored in the event's short-lived `.quasi/temp/...` `request_path`, avoiding terminal truncation. The active skill answers through the current thread's native `spawn_agent` tools, serializes each full result to the assigned `receipt_path`, and writes only a short `result_path` event to the driver's PTY stdin. Those workers therefore appear in the current Codex agent tree, while large diagnostic receipts cannot be truncated by the PTY/tool input limit. The driver keeps graph continuations in memory, validates returned receipts against the graph schema, caps requests at three so the coordinator retains one thread slot, and emits `agent_cancel` when the graph aborts. `quasi-codex-runner` remains the headless/CI fallback when native subagent or resumable-exec tools are unavailable.

Public skill routing separates material intake from topic research. `collect-material` owns paper, book, author, Talk, and Translation; `precise-topic` owns vault recall, outline steering, evidence cards, human seed gates, and topic synthesis. Both still call `workflows/process-material.mjs`, so topic candidates reuse the same paper/book router without duplicating graph nodes. Draft proofreading and citation closure use `finalise-draft`.

For a single title-only book or paper request, `collect-material` must dispatch `search-agent` before vault recall or graph startup. The verified record owns author order, year, identifiers, venue, access URLs, and canonical slug. The main process must not substitute generic web or browser search; a failed download must preserve `failure_reason` and per-source `attempts` in the graph result.

Paper metadata merging treats Crossref as the authority for the journal container title and decodes its HTML entities at the adapter boundary. Do not let asynchronous adapter completion order choose `venue`; OpenAlex may omit meaningful punctuation from the same journal name.

Codex does not inject Claude plugin Configure options, and a native subagent may not inherit the coordinator's plugin hook. Every Python-facing `quasi-*` shim therefore sources `scripts/load-keychain-env.sh`, which fills missing `QUASI_*` values at runtime from the existing encrypted `Claude Code-credentials` Keychain record. On macOS the PreToolUse hook uses the same `--keychain-exports` helper for coordinator commands, including Claude-hosted commands whose `CLAUDE_PLUGIN_OPTION_*` values are visible only to the hook. Command argv contains only helper paths, never secret values; explicit `QUASI_*` values take precedence because the helper fills only missing keys. This is also the config source used by the Pi bridge; secrets are not written to request envelopes or plugin data. Non-macOS currently keeps the older direct-export hook fallback because it has no shared Keychain provider.

`quasi-translate` has two interchangeable backends behind one output contract (`processing/translations/{slug}-{full-target-tag-lower}.pdf`, for example `-zh-cn.pdf`; alternating original/translated pages, bookmarks): `immersive` (default, Immersive Translate Zotero API) and `pdf2zh` (local `pdf2zh-next` via uvx, driving a user-supplied OpenAI-compatible endpoint). Backend selection is user config (`translate_backend`), not an agent decision — strict `observe`/`run` reject a caller backend override, while the legacy prose entry still accepts `--backend` as a compatibility adapter into the same transaction. For pdf2zh, a root-only `translate_base_url` gets `/v1` appended; any explicit path is preserved because compatible providers also use paths such as `/api/paas/v4` and `/openai/v1`. The pdf2zh path uses `--use-alternating-pages-dual`, which emits the same page layout Immersive produces *after* `split_dual_pdf()`, so the TOC helpers are shared verbatim. Strict and legacy public entries reject free backend arguments; provider credentials stay out of argv. Because pdf2zh-next exits 0 on a mangled translation, the transaction gates on output pages == 2× source pages, then ToUnicode repair and coverage, before manifest-last publication. Rejected or uncertain generations remain in their fenced `processing/translations/.{stem}.translate-*` directory and never become canonical output.

Both backends also gate on translation coverage (`scripts/translate/coverage.py`), because a structurally perfect dual PDF — right page count, exit 0, no warning — can still be missing most of its body text: when the source's own text layer is fragmented, BabelDOC's layout model stops recognising paragraphs as translatable blocks and leaves them as untouched scan. Translated Han characters per source Latin letter separates the two cleanly (0.30–0.36 on every healthy page measured; 0.15 median, 0.01 at worst on a book that came out 43% translated), so the gate is the per-page median against `MIN_MEDIAN`. It is a median, not a mean or a per-page rule, so one plate or part-title page cannot reject a complete book; the cost is that a single dead page inside a good book passes. Only Chinese targets are scored. The check must run *after* `tounicode.py::repair_pdf`, and does in both backends: an unrepaired book extracts as mojibake in the CJK extension-A block, which the counter deliberately does not count, so a healthy 368-page translation scored 0.17 before repair and 0.31 after. Run the script standalone to audit PDFs translated before this existed — repair first. `agents/translate-agent.md` answers the error with exactly one re-OCR-and-retry through `quasi-extract ocr --layout`.

Both backends run `scripts/translate/tounicode.py::repair_pdf` on the finished PDF. BabelDOC — which Immersive Translate's PDF pipeline also uses, same font stack — emits a `/ToUnicode` CMap holding a couple of dozen entries instead of one per glyph once a run exceeds a few translated pages. The pages render correctly but copy/paste and in-PDF search return mojibake, because the reader falls back to reading the raw CID as a codepoint. The subset fonts are Identity-H with original glyph numbering, so the map is rebuilt from the cached original TTF under `~/.cache/babeldoc/fonts` (override with `QUASI_BABELDOC_FONT_DIR`); every rebuild is cross-checked against the entries BabelDOC got right and a font that disagrees is skipped rather than corrupted. Run the script standalone to repair PDFs translated before this existed.

`quasi-extract ocr` defaults to **DS OCR2** (DeepSeek-OCR-2 via `mlx-vlm`, Apple Silicon). The engine pins **mlx-vlm==0.3.12** — 0.4+ breaks this model's loader ("Unrecognized processing class") and generate path ("TokenizersBackend has no attribute stopping_criteria"); 0.3.12 is the last version that runs DeepSeek-OCR-2 end to end. The cause is *not* transformers: 0.3.12 already requires `transformers>=5.1.0` itself, and the only declared dependency delta to 0.4.0 is `mlx-lm` (0.30.7 vs 0.31.0). Do not reject a candidate model for needing transformers 5.x — that reasoning was wrong once already and it excluded GLM-OCR. It also pulls torch/torchvision/addict/einops/matplotlib/tqdm (the model's remote-code imports), all via uvx — NOT in `requirements.txt`. OCR auto-falls-back to tesseract if uvx, the model (`QUASI_DSOCR2_MODEL`, a local BF16 dir or HF repo id), or Apple Silicon is missing; `--engine tesseract` forces tesseract. The DS OCR2 path writes a text-layer PDF (one page per input page) so the existing `split` flow is unchanged.

Never pass `trust_remote_code=True` when loading this model: mlx-vlm ships its own `DeepseekOCR2Processor`, while the HF repo's remote code imports `LlamaFlashAttention2`, deleted from modern transformers. mlx-vlm swallows that ImportError in `models/base.py` and re-raises it as a bogus "Unrecognized processing class", which sent every run silently down the tesseract fallback. `tests/test_extract_cli.py` guards it.

`--layout` switches the output shape: instead of reflowed markdown it writes the source's own pages with their text layer replaced — scan image untouched, invisible text at the boxes DS OCR2 returns for the `<|grounding|>` prompt (a 0-999 space, normalised to the page). This exists to feed `quasi-translate`: BabelDOC carries the *source* font size onto the translation (measured at a constant 0.90x across both of a slice's two source sizes, character counts in the same ratio), so whatever size the OCR layer writes is what the Chinese renders at. Three constraints are load-bearing. The text is drawn *over* the image, not under it the way ocrmypdf does — BabelDOC substitutes the translation in place, so an ocrmypdf-shaped source yields a translated page that extracts fine and renders as the untouched English scan. The font is base-14 Helvetica whenever it covers the text: PyMuPDF embeds a fontfile whole and cannot subset without fontTools, so an unconditional Arial Unicode adds ~16MB per output. And every line's size is snapped to the book's dominant one (`dominant_size` / `SNAP`, character-weighted median over every grounded line, book-wide because one page holds too few lines to see through the noise): a box hugs its ink, so its height tracks whether the line has ascenders rather than its type size, and identically-set body lines otherwise compute -9%/+4% apart — which is precisely the "字号时大时小" symptom, 25 distinct sizes on a slice whose source layer used 2. Snapping puts 99.6% of characters on one size. It also flattens headings and no threshold avoids that: the same slice's chapter title is set 1.36x body in the source but its *box* computes to 1.12x where body lines already reach 1.07x. Fixing that needs an engine that labels blocks rather than lines: `mlx-community/dots.ocr-4bit` returns `{bbox, category: Title|Text|Section-header, text}` per paragraph, runs on the same mlx-vlm 0.3.12 pin at 6-8s/page against this engine's ~20s, and over the same 10 pages made 1 word error against DS OCR2's 6 plus 2 silently dropped phrases — its one real loss is that it eats superscript footnote markers. Its boxes are in the input PNG's own pixel space, not a 0-999 grid. Surveyed and left unwired. Stripping the old text layer must reach **Form XObjects**, not just `page.get_contents()`: ABBYY-style scans park their OCR text in a Form named `OCR-<id>`, and five of eight books measured are that shape. Missing it left two stacked text layers, which BabelDOC answers by silently dropping body text — coverage 0.23–0.29 against a healthy 0.33, one book losing its longest paragraph on every page. Only `/Form` subtypes are rewritten; the same `BT…ET` regex over an image stream would corrupt it. A page with no image object is skipped entirely (`relayer_page` returns -1): it is born-digital, its text *is* the page, so stripping would blank it — and the layer it already has is the clean one `--layout` exists to reconstruct for scans. Note that a scan can still carry real font names; `archer-culture-and-agency-1996.pdf` is an ABBYY-style scan whose text layer uses TimesNewRomanPSMT, not tesseract's `GlyphLessFont`, so the image object is the reliable test, not the font name.

`--layout` writes one flowed textbox per **paragraph**, not per line, and that is the single biggest readability win in the translation path. Handed a line box, BabelDOC must fit that line's Chinese into that line's width and parks the tail in the margin, so a paragraph arrives cut into pieces — measured on three books' 10-page slices, per-line produced 11/12/19 margin scraps and 20/34/77 overlaps, paragraph flow 1/3/33 and 0/7/32, and it fixed the coherence on 3/3. A paragraph box has nowhere to spill: it rewraps internally. The grouping comes from **MinerU2.5-Pro** (`opendatalab/MinerU2.5-Pro-2605-1.2B`, `QUASI_MINERU_MODEL`) called through `MinerUClient.layout_detect`, which returns `{type, bbox}` and **no text at all** — DS OCR2 keeps every bit of its recognition advantage and MinerU is used purely as a grouper. Same mlx-vlm 0.3.12 pin, ~2s/page against DS OCR2's ~20s, and fail-soft: no MinerU means the old per-line layer. Leading comes from the source's own line pitch, so the flow lands on the ink it replaces instead of needing the box to grow — growing is what makes boxes overlap and translations stack. Five things are load-bearing. Geometry (nesting, bottom-edge extension) runs over **every** block and the flowable-category filter comes **last**: filter first and a `list` of footnotes looks childless once its `ref_text` children are gone, so six numbered notes flow as one blob, and a body block above a figure grows through it and swallows the caption — both were real regressions on book two. `FLOW` includes `ref_text`, because a footnote is a paragraph and leaving it per-line reproduces exactly the shredding this path exists to fix; it was the largest flowable category being dropped (44/52/52 lines on the three footnote-heavy books of eight measured) and adding it took margin scraps 3→1 on galison and 32→15 on hounshell. A block's box comes from **sorted** line extents, never from `lines[0]`/`lines[-1]`: grounding order is reading order, and on a page with figures a block's last line can sit above its first, which built an inverted rect and crashed PyMuPDF outright. Lines no block claims stay per-line, and furniture outside every block keeps its measured size rather than being snapped to body, because snapping made BabelDOC read a running head as the first line of the paragraph under it. The source layer is written at a flat `SHRINK` 0.90: BabelDOC sets CJK at `line_skip` 1.50 (`typesetting.py`) into a box a scanned book built at ~1.15 pitch, and that vertical deficit — not character width, since Chinese needs only 0.70x the width of English at the same size — is what overflows; below scale 0.70 BabelDOC stops shrinking and expands the paragraph box rightwards instead, which *is* the margin scrap. And the shrink is flat rather than per-paragraph because BabelDOC caps every paragraph at `min(multimode(scales))` document-wide, so a mixed source comes out mixed (41-49% of characters on the dominant size against 72-94% for a flat one); 0.90 measured identical to 0.85 in defects on three books, 0.95 gained nothing on the densest of them and halved its uniformity, and 1.00 collides. The constant is deliberately not calibrated per book: across five further books, 0.95 and 0.90 produced the same margin-scrap counts to within noise (9/9, 23/23, 0/0, 7/7, 12/12), so the per-book variance that looked like a density problem was three bugs, not a missing knob. Block lines are joined with `join_lines`, which undoes end-of-line hyphenation (104 cases over two slices) at the join rather than on the joined string, so the real hyphen in `pre-logical` survives.

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
- Optional out-of-venv deps (fail-soft, like the transcribe engines): `ffmpeg`/`whisper-cli`/`uvx` for transcription, `mlx-vlm` for DS OCR2 OCR, `mineru-vl-utils` for `--layout` paragraph grouping.
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
8. After releasing, sync `~/.agents/plugins/quasi/` from the new version — the Pi extension symlink reads from there, so a stale copy means Pi discovers old skills.

## Verification

- For instruction-only changes, run `cmp -s plugins/quasi/CLAUDE.md plugins/quasi/AGENTS.md` and confirm exit code 0.
- Run `pytest plugins/quasi/tests/test_dead_names.py plugins/quasi/tests/test_skill_orchestration.py -q` if those tests exist in the current checkout.
- For manifest or marketplace changes, run `claude plugin validate plugins/quasi`.

## Debugging gotchas

- `$CLAUDE_PROJECT_DIR` is fixed at session start; a `cd` inside a dispatched worker's *prompt* does not redirect where the orchestration graph writes. Dispatch E2E workers with the correct cwd; never rely on an in-prompt `cd`.
- A dead Workflow subagent writes no `result` line in `journal.jsonl` — its key stays `started`-only forever, and a retry shows up as a *new* started+result pair. Count `started` vs `result` keys to find deaths; do not look for `result: null`.
- `agent()` returns `null` when a subagent dies on a terminal API error after retries. `process-material.mjs::retryNull` pays exactly one retry per null, because a `null` cannot distinguish a deterministic failure from a transient one.
- A run that looks hung is usually harness backoff, not deadlock. A dying subagent's transcript ends in a synthetic `API Error: …` assistant message, but the harness can sit in invisible retry backoff for 20–40 minutes before `agent()` finally sees `null` — no result line, no progress, nothing a script can observe or shorten. Before declaring a run dead, check each no-result agent's transcript mtime: still advancing = live agent (a `0 tok` display can just be a slow provider), stale with an API-error tail = a death still waiting to be reported. Legacy and read-only graph calls may still use `guard` and `retryNull` to bound a dead worker. Paper writer Operations deliberately await their exact Agent call without a timer race: a timed-out Promise could continue writing after the graph had followed another edge. Resume or reconciliation, not a concurrent retry, is the safe recovery for an unknown writer outcome. Other workflow scripts have no such bound — there, killing the run and re-invoking with `resumeFromRunId` is still the only shortcut.

## Changelog

Full version history lives in `docs/CHANGELOG.md` (newest first, entries carry the why as well as the what). Current version: 0.52.13.

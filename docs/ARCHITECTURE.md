# Quasi Architecture

date: 2026-08-01
status: current contract

Quasi is optimized for agent maintenance: keep a flat monorepo, keep each
capability in a readable large entrypoint, and make upper layers depend only on
the layer directly below them.

## Layers

```text
L5 skills/          user-facing coordinators and human gates
L4 scripts/workflows/ modular TypeScript source for host-neutral stage graphs
L4 workflows/       generated, host-loadable workflow entries
L3 agents/          specialist LLM workers, only calls quasi-* bins
L2 bin/             stable command surface
L1 scripts/         capability entrypoints and build sources
L0 scripts/core/    runtime plumbing
L0 scripts/schemas/ vault domain spec
```

`scripts/core/` and `scripts/schemas/` are both foundational, but intentionally
separate:

- `scripts/core/` knows paths, frontmatter, JSON, atomic writes, and module loading.
- `scripts/schemas/` knows vault types, frontmatter schemas, body schemas, and
  type aliases. It is the single source of truth for artifact structure.
- `scripts/core/` must not import sibling script domains or `scripts/schemas/`.
- agents and skills must not import Python packages directly; the Workflow
  build injects canonical artifact projections generated from this registry.

## Public CLI

| bin | contract |
|---|---|
| `quasi-search` | `book|paper` metadata discovery |
| `quasi-download` | `book candidates|fetch`; `paper fetch|diagnose`; `accept` |
| `quasi-extract` | `epub|text|ocr|split` text extraction and normalisation (`ocr` default engine DS OCR2, `--engine dsocr2\|tesseract`, `--layout` replacement text layer) |
| `quasi-audit` | agent-facing `--path PATH` autofix + typecheck + classify |
| `quasi-status` | read-only disk oracle: `--kind paper|book|talk --slug SLUG --json [--identity]`; `--scan --json` |
| `quasi-transcribe` | `run|classify|silent` talk transcript engines |
| `quasi-helpers` | `proofread prepare|cleanup`; `citation parse|biblio|resolve|review-cards|emit-bib`; `localise scan|write`; `talk compress-media`; `vault resolve` |
| `quasi-doctor` | runtime healthcheck: venv sync, core Python deps, optional external tools by profile |
| `quasi-translate` | configured `immersive|pdf2zh` PDF translation; shared alternating-page, TOC, ToUnicode, and coverage contract |

`quasi-status` imports `scripts/schemas/pipeline.py::PIPELINE` for the reported
stage order and exact artifact path templates. Its hardened manifest parsing,
frontmatter reads, media enumeration, derivative globbing, and scan discovery
remain explicit Python observation logic rather than a rule-DSL walker.

Removed legacy bins:

- `quasi-citation` → use `quasi-helpers citation ...`
- `quasi-proofread` → use `quasi-helpers proofread ...`

## Capability Entry Points

- `scripts/search/search.py`: metadata discovery, source merge, and book
  `localisations.zh` sidecar candidates.
- `scripts/download/download.py`: acquisition by DOI/URL/MD5, diagnostics, and accept
  into `sources/`. AA file search remains in `scripts/download/aa.py` because it is
  acquisition discovery, not metadata search.
- `scripts/extract/extract.py`: unified extraction dispatcher.
- `scripts/audit/audit.py`: agent-facing typecheck wrapper. It always runs
  mechanical autofix, then typecheck, then residual issue classification, and
  emits JSON.
- `scripts/localise/localise.py`: scale-facing ISBN-keyed cndouban cache helper.
- `scripts/citation/citation.py`: deterministic draft citation helpers only.
- `scripts/proofread/proofread.py`: deterministic proofread setup/cleanup only.
- `scripts/doctor/doctor.py`: runtime healthcheck for venv sync, core Python deps, and optional system tools by profile.
- `scripts/translate/immersive_translate.py` and `pdf2zh_translate.py`: interchangeable PDF translation backends behind the `quasi-translate` shim. Both run `tounicode.py` repair followed by `coverage.py` acceptance; DS OCR2/MinerU are recovery dependencies only after `Under-translated`, not pdf2zh startup requirements.

## Workflow source and runtime

`scripts/schemas/pipeline.py` is the single source of run-stage kind/stage order,
operation identity (`operation`, display phase, effect, and agent), declarative
receipt-to-context carries, and stage artifact path templates. The Python exporter
projects `PIPELINE` into `scripts/workflows/artifact-contracts/generated.mjs` alongside
the canonical artifact contracts, and emits `generated.d.mts` literal unions and
interfaces from the same source. `scripts/workflows/operations/rows/*.mts` owns
operation-specific context derivation as well as request/receipt behavior;
`run-stage.entry.mts` supplies the shared passthrough/default base, expands manifest
templates after row context is known, and derives both `RUN_STAGE_REGISTRY` and runtime
chain functions. The former central context switch is gone. `scripts/build-workflows.mjs`
rejects duplicate kind/stage pairs, missing or duplicate row joins, unregistered rows,
invalid manifest identity, and carries whose source field is not required by the owning
receipt schema in both build and `--check` mode. The pinned esbuild dependency compiles
the editable `.mts` layer into the committed `workflows/run-stage.mjs` at build time;
`npm run check:workflows` also rejects a stale projection, declaration, bundle, or
forbidden runtime import, then runs strict `tsc --noEmit` checking over those
TypeScript sources.

Skills are the drivers. They observe exact disk state through `quasi-status`,
normalise and coalesce identity before writers, preserve batch input order, and
select an applicable stage from
`Recall → Search → Acquire → Prepare → Analyse → Synthesise → Audit`.
Without `until`, each run-stage invocation selects one descriptor row and, for
each request unit, gives one specialist a goal, exact refs, declared capabilities,
and a closed `quasi.stage.receipt/0.2` schema, then returns that unit's terminal
unchanged. A single invocation may fan out within one stage when every unit writes
a distinct exact output; prompt-identical duplicate requests are rejected. With
`until`, run-stage walks only the registered fixed slice, stopping when a terminal
is not complete or the owning row's cross-field completion predicate rejects it.
Carries thread receipt evidence without filesystem access; the Paper chain passes
`paper.prepare.selected_input` into `paper.analyse.input`. Paper Search stays a
single dispatch because the skill owns post-Search identity judgement, so its
chain begins at Acquire. The specialist owns method and local recovery; unknown
writer outcomes stop instead of racing a second writer.

Root `settings.json` supplies a plugin-default `subagentStatusLine`. The
zero-dependency `scripts/subagent-statusline.py` renders only quasi task rows,
so unrelated subagents retain Claude Code's default row.

## Active Agents

| agent | depends on |
|---|---|
| `metadata-agent` | `quasi-search` + vault resolve → one canonical identity and local owner |
| `discovery-agent` | `quasi-search book|paper` → bounded Author/Topic/citation candidates |
| `steer-agent` | topic outline page + `quasi-search` |
| `webcard-agent` | `quasi-search kagi` + WebFetch → topic `cards/` page |
| `download-agent` | `quasi-download`, direct AA search import |
| `extract-agent` | `quasi-extract` capabilities → Paper/Book Prepare Stage |
| `analyse-agent` | vault/source files |
| `synthesis-agent` | vault analysis files |
| `audit-agent` | `quasi-audit` |
| `proofread-agent` | draft sections prepared by `quasi-helpers` |
| `citecheck-agent` | citation manifest prepared by `quasi-helpers` |
| `transcribe-agent` | `quasi-transcribe` capabilities → Talk Prepare Stage |
| `translate-agent` | `quasi-translate` + optional layout OCR → Translation Prepare Stage |

### Write ownership

- `metadata-agent` and `discovery-agent` return JSON and do not write files.
- `download-agent` reconciles or accepts one exact Book/Paper source through `quasi-download`; it returns that material's direct Acquire receipt, including a standard `needs_input` terminal for a Book year gate, and does not own caller manifests. A failed download preserves `failure_reason` and per-source `attempts` in its receipt.
- `extract-agent` owns Paper/Book Prepare judgement and local recovery over caller-named refs. It invokes deterministic `quasi-extract` transactions; those CLI transactions own chapter files and `processing/chapters/{slug}/manifest.json`.
- `analyse-agent`, `synthesis-agent`, `proofread-agent`, and `citecheck-agent` write only the exact product path assigned by the caller.
- `steer-agent` owns `vault/topics/{slug}/02-outline.md` (the topic research outline; users may hand-edit it between runs) and returns sub-question-targeted candidates; it writes nothing else.
- `webcard-agent` turns one topic `web_task` into one evidence card at the caller-named `vault/topics/{slug}/cards/{card-slug}.md`; it writes nothing else, and returns `status: empty` rather than writing a card it could not verify. Cards travel on their own `cards` channel (outline `subquestions[].cards`, synth `card_paths`) and never enter the `book|paper|talk` corpus table.
- `audit-agent` runs `quasi-audit --path`; it may apply local mechanical fixes but does not own workflow state.
- `transcribe-agent` and `translate-agent` own Talk and Translation Prepare with the same terminal shape, preserving media reconciliation and fenced-generation publication contracts.

Deprecated agents live under `deprecated/agents/` and must not be dispatched by
active skills.

## Active Skills

- `collect-material`
- `research-topic`
- `finalise-draft`

`collect-material` owns the current Paper/Book/Author/Talk/Translation entry.
Talk-specific media normalisation is progressively disclosed from
`skills/collect-material/references/talk.md`; it is not a second public Skill.
`research-topic` owns the distinct iterative topic state machine while reusing
the same material graph rather than duplicating its nodes. `finalise-draft`
owns interactive proofreading, citation review, and bibliography closure.
Journal has a schema but no active or archived workflow; its future entry will
be a thin collection loop over Paper receipts.

For a single Book or Paper request, `collect-material` begins from user-provided
hints and current disk observations. One `material.search` Stage Unit gives
`metadata-agent` both search and vault-resolution capabilities, so the
specialist establishes the canonical identity and exact existing owner in one
investigation; Search owns author order, year, identifiers, venue/publisher,
access URLs, and canonical slug. Author/Topic candidate finding uses
`discovery-agent`; Chinese-edition matching uses the deterministic
`quasi-helpers localise scan|write` helper.

For 2–32 top-level Books/Papers, the skill preserves input order, normalises
and coalesces duplicate identities before any writer, and drives independent
items with bounded host-level concurrency. A Paper call may own one fixed
post-Search chain slice; every other Workflow call still owns one stage.

Topic synthesis produces only `00-overview.md` and `01-resources.md` beside the
user-editable `02-outline.md`; per-subquestion dossier pages are retired as a
product decision.

## Material Loops

Concrete materials are thin stage pipelines, not product categories layered
above a separate library executor. A Material Loop coordinates exact Stage
inputs/outputs, joins producer artifacts, audits the canonical product, and
terminates through typed `complete|needs_input|blocked|failed` edges. Stage Unit
Agents own professional judgement; bins own deterministic effects; `sources/`,
`processing/`, and `vault/` are the persisted result space.

Design history (RFCs, campaign plans, review records) lives in git history
and `docs/CHANGELOG.md`; this file plus `CLAUDE.md`,
`docs/PDF_PIPELINE.md`, `docs/SKILL_ORCHESTRATION.md`, and
`docs/GRAPH_COLLABORATION.md` are the only maintained maintainer documents.

Active skill writing follows `docs/SKILL_ORCHESTRATION.md`: Skill owns user
intent, identity, state, and decisions; Workflow owns descriptor dispatch and
fixed chain progression; Agent owns specialist judgement, and CLI owns deterministic writes. Active `SKILL.md`
files contain runtime instructions, not links back to maintainer docs.

## Configure options and env flow

Authoritative sources are `.claude-plugin/plugin.json#userConfig` and
`scripts/hooks/inject-userconfig.py::_KEYS`; the mapping below documents the
current flow from Configure field to script consumer.

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

Every Python-facing `quasi-*` shim sources `scripts/load-keychain-env.sh`, which fills missing `QUASI_*` values at runtime from the existing encrypted `Claude Code-credentials` Keychain record. On macOS the PreToolUse hook uses the same `--keychain-exports` helper for coordinator commands, including Claude-hosted commands whose `CLAUDE_PLUGIN_OPTION_*` values are visible only to the hook. Command argv contains only helper paths, never secret values; explicit `QUASI_*` values take precedence because the helper fills only missing keys. Non-macOS currently keeps the older direct-export hook fallback because it has no shared Keychain provider.

## Guardrails

- Keep scripts as large, sectioned entrypoints unless splitting removes real
  duplication.
- Add shared code to `scripts/core/` only when at least two capability domains need the
  exact same runtime policy.
- Keep schema changes in `scripts/schemas/`; do not duplicate schema facts in
  agents or skill prose.
- Active agents/skills must not reference removed entrypoint names; this is
  enforced by `tests/test_dead_names.py`.

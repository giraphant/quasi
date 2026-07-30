# Quasi Architecture

date: 2026-07-30
status: current contract

Quasi is optimized for agent maintenance: keep a flat monorepo, keep each
capability in a readable large entrypoint, and make upper layers depend only on
the layer directly below them.

## Layers

```text
L5 skills/          user-facing state machines and human gates
L4 scripts/workflows/ modular source for host-neutral deterministic graphs
L4 workflows/       generated, host-loadable workflow entries
L3 agents/          specialist LLM workers, only calls quasi-* bins
L2 bin/             stable command surface
L1 scripts/         capability entrypoints, host adapters, and build sources
L0 core/            runtime plumbing
L0 scripts/schemas/ vault domain spec
```

`core/` and `scripts/schemas/` are both foundational, but intentionally
separate:

- `core/` knows paths, frontmatter, JSON, atomic writes, and module loading.
- `scripts/schemas/` knows vault types, frontmatter schemas, body schemas, and
  type aliases. It is the single source of truth for artifact structure.
- `core/` must not import `scripts` or `schemas`.
- agents and skills must not import Python packages directly; the Workflow
  build injects canonical artifact projections generated from this registry.

## Public CLI

| bin | contract |
|---|---|
| `quasi-search` | `book|paper` metadata discovery |
| `quasi-download` | `book candidates|fetch`; `paper fetch`; `accept` |
| `quasi-extract` | `epub|text|ocr|split` text extraction and normalisation (`ocr` default engine DS OCR2, `--engine dsocr2\|tesseract`, `--layout` replacement text layer) |
| `quasi-audit` | agent-facing `--path PATH` autofix + typecheck + classify |
| `quasi-helpers` | `proofread prepare|cleanup`; `citation parse|biblio|resolve|review-cards|emit-bib`; `localise scan|write`; `talk compress-media` |
| `quasi-doctor` | runtime healthcheck: venv sync, core Python deps, optional external tools by profile |
| `quasi-translate` | configured `immersive|pdf2zh` PDF translation; shared alternating-page, TOC, ToUnicode, and coverage contract |
| `quasi-pi-runner` | minimal Pi SDK runner for the existing deterministic `process-material` graph |
| `quasi-codex-agents` | explicit `agents/*.md` → project/user `.codex/agents/quasi_*.toml` native-role sync |
| `quasi-codex-driver` | Codex GUI bridge: graph requests → current-thread native subagents → validated receipts |
| `quasi-codex-runner` | minimal Codex CLI runner for the same deterministic `process-material` graph |

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
- `scripts/pi-runner.mjs`: Pi SDK adapter for `workflows/process-material.mjs`; owns agent-definition loading, Claude→Pi tool mapping, bounded subagent concurrency, structured receipts, and aborts, but no generic workflow features.
- `scripts/codex-agents.mjs`: deterministic native-role generator. Root `agents/*.md` remains the sole role source; explicit project/user sync writes only supported Codex TOML fields and never silently mutates global config.
- `scripts/codex-driver.mjs`: interactive Codex adapter over the same `createRunner`. It never launches a worker itself; it holds graph continuations while exchanging short JSONL path events with the active skill, which uses native current-thread subagents. Each request carries a `codex_agent_type` such as `quasi_download`, with generic `worker` fallback. Full worker contracts and receipts live in paired per-request files under `.quasi/temp/`, so neither large prompts/schemas nor rich results cross the terminal event buffer.
- `scripts/codex-runner.mjs`: Codex adapter over `pi-runner.mjs::createRunner`; launches one ephemeral `codex exec` per graph worker and converts the graph's ordinary receipt schemas into strict Codex output schemas.

## Workflow source and runtime

`scripts/workflows/**/*.mjs` is the only hand-maintained graph source. It separates
material loops, collection loops, research loops, and narrow Operations while
retaining a single logical Workflow universe. `npm run build:workflows` uses the
pinned esbuild dependency to produce the committed
`workflows/process-material.mjs`; `npm run check:workflows` rejects a stale
bundle or forbidden runtime imports.

The Paper loop is the first Operation-based vertical slice. Its edge order is:
acquire/reconcile → deterministic text normalisation → semantic readability
assessment → bounded OCR recovery when required → the common `analyse-agent`
with the Paper artifact-schema projection → audit/reconciliation. Each edge has one handler and a
strict receipt; unknown writer outcomes block instead of racing a second writer.
The existing Book and collection/research routes remain behavioural baselines
for later slices.

Root `settings.json` supplies a plugin-default `subagentStatusLine`. The
zero-dependency `scripts/subagent-statusline.py` renders only quasi task rows,
so unrelated subagents retain Claude Code's default row.

## Active Agents

| agent | depends on |
|---|---|
| `search-agent` | `quasi-search` |
| `steer-agent` | topic outline page + `quasi-search` |
| `webcard-agent` | `quasi-search kagi` + WebFetch → topic `cards/` page |
| `download-agent` | `quasi-download`, direct AA search import |
| `extract-agent` | `quasi-extract` |
| `analyse-agent` | vault/source files |
| `synthesis-agent` | vault analysis files |
| `audit-agent` | `quasi-audit` |
| `proofread-agent` | draft sections prepared by `quasi-helpers` |
| `citecheck-agent` | citation manifest prepared by `quasi-helpers` |
| `translate-agent` | `quasi-translate` |

Deprecated agents live under `deprecated/agents/` and must not be dispatched by
active skills.

## Active Skills

- `process-material`
- `research-topic`
- `process-talk`
- `process-draft`

`process-material` owns the current Paper/Book/Author entry. `research-topic`
owns the distinct iterative research state machine while reusing the same
material graph rather than duplicating its nodes. `process-talk` remains the
current Talk intake until the Talk Material Loop gains generation/fingerprint
state. Journal has a schema but no active or archived workflow; its future entry
will be a thin collection loop over Paper receipts.

## Material Loops

Concrete materials are bounded loops, not product categories layered above a
separate library executor. A Material Loop reconciles persisted artifacts, runs
one named operation at a time, audits the canonical product, follows a bounded
repair edge when possible, and terminates as `complete | blocked | failed`.
Agents and bins are handler choices for those operations; `sources/`,
`processing/`, and `vault/` are the persisted result space.

The normative v0.1 contract and Paper reference implementation are documented in
`docs/material-loop-protocol.md`. The accepted business hierarchy and rollout
order are in `docs/workflow-universe-rfc.md`; operation ownership and Agent/Bin
selection rules are in `docs/operation-layer-design.md`; the implemented source
layout and rollout gates are in `docs/workflow-modularization-master.md`.

Active skill writing follows the maintainer schema in
`docs/SKILL_ORCHESTRATION.md`:the skill main process owns workflow state,
agents are specialist workers, and each phase must state its skip condition,
writes, failure behavior, and human gate. Active `SKILL.md` files should contain
runtime instructions, not links back to maintainer docs.

## Guardrails

- Keep scripts as large, sectioned entrypoints unless splitting removes real
  duplication.
- Add shared code to `core/` only when at least two capability domains need the
  exact same runtime policy.
- Keep schema changes in `scripts/schemas/`; do not duplicate schema facts in
  agents or skill prose.
- Active agents/skills must not reference removed entrypoint names; this is
  enforced by `tests/test_dead_names.py`.

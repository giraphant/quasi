# Quasi Architecture

date: 2026-07-30
status: current contract

Quasi is optimized for agent maintenance: keep a flat monorepo, keep each
capability in a readable large entrypoint, and make upper layers depend only on
the layer directly below them.

## Layers

```text
L5 skills/          user-facing coordinators and human gates
L4 scripts/workflows/ modular source for host-neutral stage graphs
L4 workflows/       generated, host-loadable workflow entries
L3 agents/          specialist LLM workers, only calls quasi-* bins
L2 bin/             stable command surface
L1 scripts/         capability entrypoints and build sources
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

`scripts/workflows/**/*.mjs` is the only hand-maintained graph source. It separates
material loops, collection loops, research loops, and narrow Operations while
retaining a single logical Workflow universe. `npm run build:workflows` uses the
pinned esbuild dependency to produce the committed
`workflows/process-material.mjs`; `npm run check:workflows` rejects a stale
bundle or forbidden runtime imports.

Top-level requests containing 2–32 Books/Papers use one material-batch
coordinator inside that same Workflow invocation. It shares the runtime and
coalescing map with every child Material Loop, runs independent items through
`parallel`, preserves input order in the aggregate receipt, and never creates a
second Workflow per item. `quasi.collection.material-batch.receipt/0.2`
contains one ordered, authoritative projection per input item: identity, status,
canonical artifacts, user gate or issue, and resume. It deliberately omits
duplicate raw child results; strict child MaterialReceipt admission happens at
the shared join before that projection is emitted.

The shared graph presents progress as
`Recall → Search → Acquire → Prepare → Analyse → Synthesise → Audit`.
Non-trivial work such as bibliographic investigation, readable-text recovery,
chapter preparation, Talk transcription, and Translation validation is a Stage
Unit: one specialist receives a goal, exact refs, declared capabilities, and a
closed `quasi.stage.receipt/0.2` schema. The terminal is a discriminated union,
so complete and non-complete evidence cannot be mixed. The specialist owns method and local
recovery; the graph checks only the exact artifacts needed by the next stage.
Single-product Analyse/Synthesise/Audit operations remain narrow. Unknown writer
outcomes block instead of racing a second writer.

Root `settings.json` supplies a plugin-default `subagentStatusLine`. The
zero-dependency `scripts/subagent-statusline.py` renders only quasi task rows,
so unrelated subagents retain Claude Code's default row.

## Active Agents

| agent | depends on |
|---|---|
| `metadata-agent` | `quasi-search` + vault resolve → one canonical identity and local owner |
| `discovery-agent` | `quasi-search book|paper` → bounded Author/Topic/citation candidates |
| `localisation-agent` | `quasi-search book` localisation sidecar |
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

Deprecated agents live under `deprecated/agents/` and must not be dispatched by
active skills.

## Active Skills

- `collect-material`
- `precise-topic`
- `finalise-draft`

`collect-material` owns the current Paper/Book/Author/Talk/Translation entry.
Talk-specific media normalisation is progressively disclosed from
`skills/collect-material/references/talk.md`; it is not a second public Skill.
`precise-topic` owns the distinct iterative topic state machine while reusing
the same material graph rather than duplicating its nodes. `finalise-draft`
owns interactive proofreading, citation review, and bibliography closure.
Journal has a schema but no active or archived workflow; its future entry will
be a thin collection loop over Paper receipts.

## Material Loops

Concrete materials are thin stage pipelines, not product categories layered
above a separate library executor. A Material Loop coordinates exact Stage
inputs/outputs, joins producer artifacts, audits the canonical product, and
terminates through typed `complete|needs_input|blocked|failed` edges. Stage Unit
Agents own professional judgement; bins own deterministic effects; `sources/`,
`processing/`, and `vault/` are the persisted result space.

The normative v0.1 contract and Paper reference implementation are documented in
`docs/material-loop-protocol.md`. The accepted business hierarchy and rollout
order are in `docs/workflow-universe-rfc.md`; operation ownership and Agent/Bin
selection rules are in `docs/operation-layer-design.md`; the implemented source
layout and rollout gates are in `docs/workflow-modularization-master.md`.

Active skill writing follows `docs/SKILL_ORCHESTRATION.md`: Skill owns user
intent and decisions, Workflow owns material state and phase routing, Agent owns
specialist judgement, and CLI owns deterministic writes. Active `SKILL.md`
files contain runtime instructions, not links back to maintainer docs.

## Guardrails

- Keep scripts as large, sectioned entrypoints unless splitting removes real
  duplication.
- Add shared code to `core/` only when at least two capability domains need the
  exact same runtime policy.
- Keep schema changes in `scripts/schemas/`; do not duplicate schema facts in
  agents or skill prose.
- Active agents/skills must not reference removed entrypoint names; this is
  enforced by `tests/test_dead_names.py`.

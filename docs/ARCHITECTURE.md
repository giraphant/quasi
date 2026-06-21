# Quasi Architecture

date: 2026-05-18
status: current contract

Quasi is optimized for agent maintenance: keep a flat monorepo, keep each
capability in a readable large entrypoint, and make upper layers depend only on
the layer directly below them.

## Layers

```text
L4 skills/          user-facing workflows
L3 agents/          LLM orchestration, only calls quasi-* bins
L2 bin/             stable command surface
L1 scripts/         deterministic capability entrypoints
L0 core/            runtime plumbing
L0 scripts/schemas/ vault domain spec
```

`core/` and `scripts/schemas/` are both foundational, but intentionally
separate:

- `core/` knows paths, frontmatter, JSON, atomic writes, and module loading.
- `scripts/schemas/` knows vault types, frontmatter schemas, body schemas, and
  type aliases.
- `core/` must not import `scripts` or `schemas`.
- agents and skills must not import Python packages directly.

## Public CLI

| bin | contract |
|---|---|
| `quasi-search` | `book|paper` metadata discovery |
| `quasi-download` | `book candidates|fetch`; `paper fetch`; `accept` |
| `quasi-extract` | `epub|ocr|split` text extraction (`ocr` default engine DS OCR2, `--engine dsocr2\|tesseract`) |
| `quasi-audit` | agent-facing `--path PATH` autofix + typecheck + classify |
| `quasi-helpers` | `proofread prepare|cleanup`; `citation parse|biblio|resolve|review-cards|emit-bib`; `localise scan|write`; `talk compress-media` |
| `quasi-doctor` | runtime healthcheck: venv sync, core Python deps, optional external tools by profile |
| `quasi-translate` | immersive translation |

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

## Active Agents

| agent | depends on |
|---|---|
| `search-agent` | `quasi-search` |
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

- `process-book`
- `process-paper`
- `process-author`
- `process-topic`
- `wrap-up`

`process-journal` is archived under `deprecated/skills/` until journal
acquisition is redesigned.

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

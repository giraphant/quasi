# Artifact path discipline — `processing/` vs `.quasi/` — Design

Date: 2026-05-18
Affects: `skills/wrap-up/SKILL.md`, `skills/process-journal/SKILL.md`,
`skills/process-topic/SKILL.md`, `skills/process-author/SKILL.md`,
`scripts/download/download.py`, `scripts/proofread/proofread.py`,
`scripts/typecheck/typecheck.py`, `scripts/citation/*.py`,
`schemas/book.py`,
`agents/citecheck-agent.md`, `agents/audit-agent.md`,
`agents/search-agent.md`, `agents/download-agent.md`,
`agents/analyse-agent.md`, `agents/synthesis-agent.md`
Version target: 0.26.0 (minor — interim-artifact path move; no script API
change; user-disk migration is soft — old files become harmless orphans)

## Background

quasi writes interim artifacts under the user's project directory
(`$CLAUDE_PROJECT_DIR`). Two project-local roots are in active use today:

- `processing/` — meant for **artifacts that get read again** (by later
  phases of the same skill run, by re-runs, or by sibling skills).
- `.quasi/` — meant for **ephemeral state** (single-phase scratch,
  diagnostic reports, cross-call status flags).

Plus `vault/` (final products) and `sources/` (downloaded raw inputs).
Those are not in scope.

## Problem

Two audit passes plus a third revision (re-grounding the principle on
"would a user ever open this file?") confirm the layout drifted in
several places:

1. **Plumbing artifacts living in `processing/`.** Files that are pure
   metadata — manifests, indices, audit state, dispatch scratch — are
   scattered across `processing/`:
   - The entire `processing/citation/{stem}/` tree (parse, manifest,
     biblio, decisions, verdicts) — regenerated on every wrap-up run.
   - `processing/proofread/{stem}/sections.json` — section index for
     Phase 1 dispatch.
   - `processing/authors/{name}/manifest.json` — process-author phase
     state machine driver; user never opens.
   - `processing/audit/state.json` and `processing/audit/translations.json`
     per the agent doc and `schemas/book.py:50` — although `audit.py`
     code actually writes `audit-state.json` to `.quasi/audit/` already,
     so the doc/code mismatch alone is a bug.

2. **Two skills bypass project-local discipline entirely.** Both
   `process-journal` and `process-topic` write downloaded PDFs into
   `/tmp/{name}-pdfs/`, and `scripts/download/download.py:1096`
   defaults `pdf_dir` to `/tmp/snowball-pdfs`. `/tmp/` is outside the
   project tree — invisible to user inspection, escapes any
   project-level cleanup, and (on some macOS configs) gets reaped by
   the OS at unpredictable times.

3. **`.quasi/` internal inconsistency.** `typecheck.py` writes
   `typecheck-results.json` + `typecheck-report.md` at `.quasi/` top
   level, while the sibling `audit-state.json` lives at `.quasi/audit/`.
   Same root, different depths, no reason for the split.

4. **Doc/code drift in audit-agent.** `agents/audit-agent.md` lines 14
   / 43 / 241 / 253-255 reference paths that don't match
   `scripts/audit/audit.py` and `scripts/typecheck/typecheck.py`. Some
   say `processing/audit/...`, some say `.quasi/typecheck-...`. The
   doc is the canonical instruction the LLM follows at runtime, so
   doc drift = runtime drift.

There are no hidden log / lock / cache mechanisms — quasi has no
runtime state daemon, every "state" file is a serialised JSON written
by an explicit `Write` call. Most fixes are string-swaps; only one
(typecheck `OUT_DIR`) is a real Python edit, and even that is one line.

## Principle (the rule we'll enforce going forward)

A project-local interim artifact belongs in:

- **`processing/`** if and only if **it is content the user might
  actually open and read as part of their research workflow** — extracted
  chapter text they fall back to when a PDF is unclear, a translated PDF
  they read alongside the original. "Survives the run" is necessary but
  not sufficient; the test is whether the file has substantive existence
  to the user as readable matter.
- **`.quasi/`** for **everything else**: manifests, indices,
  status flags, parse buffers, dispatch scratch, audit-trail JSON,
  downloaded temp PDFs that get analysed and then have no further use.
  Even when a manifest spans many phases or many runs, if the user
  never opens it, it's plumbing — and plumbing belongs hidden.

The key test (sharpened): **would the user ever cat / open this file
in their normal workflow?** If yes → `processing/`. If it exists only
as input to other quasi steps → `.quasi/`.

This is stricter than a pure "survives the run" rule. A discovery
manifest like `authors/{name}/manifest.json` survives many phases and
many runs, but the user never reads it — it's a driver file for
process-author's internal state machine. It belongs in `.quasi/`.

`vault/` and `sources/` are out of scope — they hold user-facing /
authored artifacts and are not "interim".

## Decision — classification table

Apply the user-readable test to every interim artifact:

| Path | Producer | Is this user-readable content? | Action |
|---|---|---|---|
| `processing/chapters/{slug}/ch*.txt` | extract-agent | **Yes.** User opens when PDF is unclear or for keyword search. | stay |
| `processing/chapters/{slug}/manifest.json` | extract-agent | No — pure index. But co-located with the .txt content it indexes; splitting the directory makes both halves harder to reason about. | stay (rides with content) |
| `processing/translations/{slug}-{lang}.pdf` | translate-agent | **Yes.** This is the user's translated PDF. | stay |
| `processing/authors/{name}/manifest.json` | process-author Phase 1 | No — driver file for the phase state machine; user never opens. | **move to `.quasi/authors/{name}/`** |
| `processing/citation/{stem}/*` (all six files) | wrap-up Phase 2.x | No — pipeline scratch + audit-trail JSON. | **move to `.quasi/citation/{stem}/`** |
| `processing/proofread/{stem}/sections.json` | wrap-up Phase 1 split | No — section index for dispatch. | **move to `.quasi/proofread/{stem}/`** |
| `processing/audit/state.json` (per docs) / actually written as `.quasi/audit/audit-state.json` (per code) | audit-agent | No — vault-wide audit status flag. | **canonicalise at `.quasi/audit/audit-state.json`; fix stale docs** |
| `processing/audit/translations.json` (per docs + schema) | audit-agent backfill mode | No — list of book↔translation associations the agent maintains. | **move to `.quasi/audit/translations.json`** |
| `/tmp/{name}-pdfs/` (journal) | process-journal | No — downloaded PDFs are inputs for analyse-agent, then disposable. | **move to `.quasi/temp/journal-pdfs/{name}/`** |
| `/tmp/{name}-pdfs/` (topic) | process-topic | No (same as above). | **move to `.quasi/temp/topic-pdfs/{name}/`** |
| `/tmp/snowball-pdfs/` (download.py default) | scripts/download/download.py | No. | **change default to `.quasi/temp/snowball-pdfs/`** |
| `.quasi/typecheck-results.json` (per code, top-level) | typecheck.py | No — diagnostic JSON. But sits at `.quasi/` top level instead of `.quasi/audit/` alongside the other audit files. | **move within `.quasi/` to `.quasi/audit/typecheck-results.json`** |
| `.quasi/typecheck-report.md` (per code, top-level) | typecheck.py | Borderline — user *can* read it post-audit, but it's a transient diagnostic, not part of the workflow. | **move within `.quasi/` to `.quasi/audit/typecheck-report.md`** |

After all moves, `processing/` holds **only user-readable content**:

```
processing/
├── chapters/{slug}/               # ch*.txt (content) + manifest.json (rides along)
└── translations/                  # {slug}-{lang}.pdf
```

Everything plumbing-shaped — manifests, indices, audit state, dispatch
scratch, temp downloads — lives under `.quasi/`. The cognitive rule
for users becomes simple: "anything I might want to open lives in
`processing/` or `vault/`; `.quasi/` is the program's working space."

### Note on `processing/papers/`

You mentioned `papers/` as a third user-readable category alongside
chapters/ and translations/. As of 0.25.x there is no
`processing/papers/` directory — papers are processed without an
intermediate extracted-text stage; analyse-agent reads the PDF directly,
and the analysis goes straight to `vault/papers/{slug}.md`.

If we later decide to mirror book chapter-extraction for papers (so
the user has a fallback when the PDF is unreadable), `processing/papers/`
would be the natural home and the principle above admits it cleanly.
**Out of scope** for 0.26.0.

## `.quasi/` internal layout

We adopt layout **A: mirror `processing/` structure where parallels
exist, freestanding subdirs where unique**:

```
.quasi/
├── audit/
│   ├── audit-state.json           # cross-call vault audit status
│   ├── translations.json          # vault book↔translation associations
│   ├── typecheck-results.json     # per-call diagnostic (moves from .quasi/ top-level)
│   └── typecheck-report.md        # per-call diagnostic (moves from .quasi/ top-level)
├── authors/{name}/
│   └── manifest.json              # process-author discovery + phase state
├── proofread/{stem}/
│   └── sections.json
├── citation/{stem}/
│   ├── parse.json
│   ├── manifest.json
│   ├── biblio.json
│   ├── decisions.json
│   └── verdicts/
│       ├── batch-*.json
│       └── recovery-*.json
└── temp/
    ├── journal-pdfs/{name}/
    ├── topic-pdfs/{name}/
    └── snowball-pdfs/
```

`processing/` ends up minimal and entirely user-readable:

```
processing/
├── chapters/{slug}/               # ch*.txt + manifest.json (manifest rides with content)
└── translations/                  # {slug}-{lang}.pdf
```

Rationale: the parallel naming (`.quasi/citation/foo/` ↔
`processing/citation/foo/`) makes the "ephemeral cousin of …" relationship
obvious when debugging. `temp/` collects the heavyweight binary
downloads, which are conceptually different from the lightweight JSON
scratch files at the top level.

Alternatives considered:

- **By lifecycle** (`.quasi/state/`, `.quasi/reports/`, `.quasi/temp/`):
  only `audit-state.json` is genuinely cross-call state, so the state/
  bucket would hold one file. Not worth the extra hierarchy.
- **Fully flat with prefixes** (`.quasi/proofread-{stem}-sections.json`):
  unsearchable, hard to clean by stem.

## Per-change file list (the actual edits)

Five logical change-groups. Each group commits atomically; groups can
ship as one PR or in separate commits, but all should land before
0.26.0 is tagged.

### Group A — citation pipeline directory move (largest)

The entire `processing/citation/{stem}/` tree moves to
`.quasi/citation/{stem}/`. Six JSON files migrate (`parse.json`,
`manifest.json`, `biblio.json`, `decisions.json`,
`verdicts/batch-*.json`, `verdicts/recovery-*.json`). Affected files:

- **`skills/wrap-up/SKILL.md`** — every Phase 2.x reference to
  `processing/citation/` becomes `.quasi/citation/`. Specifically:
  Phase 2.1 parse + biblio + resolve output paths; Phase 2.2
  citecheck-agent dispatch (verdicts output); Phase 2.3 search-agent
  recover-mode dispatch (recovery output); Phase 2.4 TUI input globs;
  Phase 2.5 `decisions.json` write site and emit-bib invocation.
  The Phase 4 cleanup line for citation artefacts moves from "可选"
  to required (`.quasi/` is disposable by definition).
- **`scripts/citation/citation.py`** — module docstring + argparse
  help examples. Subcommands receive paths as args, no logic change.
- **`scripts/citation/biblio.py`** / **`resolve.py`** / **`emit_bib.py`** —
  verify each accepts the output / input path as an argument rather
  than hardcoded; fix if hardcoded. (`render.py` is deprecated per
  0.22.0; skip unless touched separately.)
- **`agents/citecheck-agent.md`** — if the agent prompt names any
  `processing/citation/...` paths in its input/output contract,
  update to `.quasi/citation/...`. The path is normally passed in
  by the caller, but the doc may show example paths.

Verification: `rg "processing/citation" plugins/quasi/` must return
zero matches after the group lands. (One exception: this spec and
the corresponding implementation plan document the move and will
mention the old path — that's intentional.)

### Group B — proofread sections move

- **`skills/wrap-up/SKILL.md`** — Phase 1 split step:
  `processing/proofread/{stem}/` → `.quasi/proofread/{stem}/`. The
  Phase 3 cleanup line goes from "可选" to required.
- **`scripts/proofread/proofread.py`** — argparse help example paths
  (lines around 15 and 208).

Verification: `rg "processing/proofread" plugins/quasi/` returns zero.

### Group C — temp PDF moves (journal + topic + snowball default)

- **`skills/process-journal/SKILL.md`** — every
  `/tmp/{journal_name}-pdfs/` template →
  `.quasi/temp/journal-pdfs/{journal_name}/`. Update both the producer
  step (download instruction) and consumer steps (analyse-agent
  dispatch + any cleanup line).
- **`skills/process-topic/SKILL.md`** — same for `topic-pdfs/{topic_slug}/`.
- **`scripts/download/download.py:1096`** — change the
  `manifest.get("pdf_dir", ...)` default from `/tmp/snowball-pdfs`
  to `.quasi/temp/snowball-pdfs`. Callers passing `pdf_dir` explicitly
  are unaffected (the two updated skills above do exactly that).

Verification: `rg '/tmp/.*pdfs' plugins/quasi/` returns zero.

### Group D — audit pipeline consolidation under `.quasi/audit/`

Two issues to clean up in one group:

1. **typecheck output location.** `scripts/typecheck/typecheck.py`
   currently writes to `.quasi/typecheck-{results.json,report.md}`
   at the `.quasi/` top level (line 50: `OUT_DIR = PROJECT_ROOT / ".quasi"`).
   These belong in `.quasi/audit/` alongside `audit-state.json`. Edit
   `OUT_DIR = PROJECT_ROOT / ".quasi" / "audit"` and remove the
   `audit/` segment from any downstream path joins that were
   compensating.

2. **audit-agent doc paths.** `agents/audit-agent.md` has multiple
   stale references that pre-date the `.quasi/audit/` convention:
   - line 14: `processing/audit/state.json` → `.quasi/audit/audit-state.json`
   - lines 43, 78, 462 (all `typecheck-results.json` references):
     `.quasi/typecheck-results.json` → `.quasi/audit/typecheck-results.json`
   - lines 241, 253-255 (translations.json section):
     `processing/audit/translations.json` → `.quasi/audit/translations.json`
   - `schemas/book.py:50` (description string): same translations.json
     path → `.quasi/audit/translations.json`
   - `docs/ARCHITECTURE.md:317`: stale doc reference to
     `processing/audit/state.json`

   Implementer should grep `rg "(processing/audit|\.quasi/typecheck-)" plugins/quasi/`
   for the full list rather than rely on line numbers above (they may
   drift before this lands).

Note on `translations.json`: this file is **written by audit-agent
at runtime** when called with `backfill=true` (via the Write tool, per
agent doc section 4B.5). The path it writes is dictated by the agent
doc instructions — so changing the doc changes the runtime behaviour.
There's no separate Python-side write site to update.

Verification: `rg "processing/audit" plugins/quasi/` must return zero
matches (modulo this spec and the implementation plan).

### Group E — process-author discovery manifest move

- **`skills/process-author/SKILL.md`** — every reference to
  `processing/authors/{name}/manifest.json` →
  `.quasi/authors/{name}/manifest.json`. Update the Phase 1 write
  site and every later phase's read site.
- **`agents/search-agent.md`** — if the agent doc references the
  manifest path in its example dispatch shape, update.
- **`agents/download-agent.md`** — same.
- **`agents/analyse-agent.md`** — same.
- **`agents/synthesis-agent.md`** — same (the author-mode synthesis
  consumes the manifest).

Verification: `rg "processing/authors" plugins/quasi/` returns zero.

### Cross-cutting check (post all groups)

Run once at the end:

```
rg -l "processing/(citation|proofread|authors|audit)" plugins/quasi/
rg -l "/tmp/(snowball|journal|topic)" plugins/quasi/
rg -n "\.quasi/typecheck-(results|report)" plugins/quasi/  # top-level path must be gone
```

Each should return only this spec file (and the implementation plan if
already written), nothing else.

## Side-effect / risk analysis

Per group:

- **Group A (citation directory move)** — risk: **medium-high**.
  The most ramified change: six file moves across one skill, four
  scripts, one agent doc. Mitigation: grep before and after; smoke-test
  `quasi:wrap-up` end-to-end on a real draft (including `--citation-only`
  re-run) before tagging. No script logic changes — only string
  literals — which limits failure modes to "agent or script can't find
  file" (immediate, loud failure rather than silent corruption).

- **Group B (proofread)** — risk: low. Two files, narrow surface.
  Phase 3 cleanup-required is a documented behaviour change but only
  affects disk-hygiene.

- **Group C (temp PDFs)** — risk: medium. Skill prompts embed `/tmp/`
  paths in instructions to dispatched agents; every reference must be
  caught. Mitigation: the `rg '/tmp/.*pdfs'` check above is the
  authoritative verification.

- **Group D (audit consolidation)** — risk: medium. Mix of a small
  code change (`typecheck.py` `OUT_DIR`) and several doc fixes plus
  a runtime-write path change for `translations.json`. The code change
  is one-line and well-contained. Risk lives in the runtime path:
  audit-agent's behaviour for `translations.json` is dictated by its
  prompt; changing the prompt changes what the LLM writes. Mitigation:
  smoke-test `quasi-audit --backfill` on a small vault subset and
  confirm `translations.json` lands at `.quasi/audit/`.

- **Group E (authors manifest move)** — risk: medium. Touches one
  skill plus four agent docs; multiple read/write sites within
  process-author's phase chain. Mitigation: smoke-test
  `quasi:process-author` end-to-end on a small author (≤3 works) to
  confirm Phase 1 → Phase 6 chain still finds the manifest at each
  step.

### User-disk migration

After 0.26.0 lands, users may have stale dirs from prior runs:
`processing/citation/`, `processing/proofread/`, `processing/authors/`,
`processing/audit/`, and `.quasi/typecheck-{results.json,report.md}`
at the `.quasi/` top level. Under the new layout these are all
orphans.

**No automated migration.** Rationale:

- Every relocated file is regenerated on the next run of its
  producing skill. Old copies have no consumer.
- The big risk would be `processing/authors/{name}/manifest.json` —
  it's the only relocated file whose state was previously assumed to
  survive across runs (process-author resumes phases from it). To
  keep `--resume` semantics intact, the 0.26.0 release notes should
  explicitly tell users mid-flight on an author run to **finish or
  abandon** before upgrading. The skill will start the next author from
  scratch under the new path. This is the only user-visible migration
  caveat.
- Other stale dirs (`processing/citation/`, `processing/proofread/`,
  `processing/audit/`, top-level `.quasi/typecheck-*`) are pure
  orphans the user can `rm -rf` at leisure. Release notes mention
  this as a one-liner.

No skill is extended to auto-warn about stale paths. (Considered and
rejected: noise-to-signal too low; users who care will see the orphans
on first `ls`.)

### `.gitignore`

User project repos likely already ignore `.quasi/`, but not always
explicitly. **Out of scope** for this change — quasi doesn't write a
`.gitignore` to user projects today and won't start. We document the
recommended ignore pattern in skill READMEs in a follow-up if friction
shows up.

## Explicit non-goals

- `processing/chapters/{slug}/` namespace separation between
  `process-book` and `process-author`. Audit confirms slugs (which
  embed author-title-year) make collision implausible. If it ever
  bites, addressed in a follow-up.
- Orphan-cleanup of `.quasi/citation/{stem}/` directories whose
  drafts were renamed/removed, or stale `processing/citation/`
  leftover from pre-0.26.0 runs. Documented limitation; not solved
  here.
- Renaming `processing/` or `.quasi/` themselves. The roots are fine;
  only the contents under them are being re-sorted.
- A general "ephemeral-path API" or helper. The codebase has six
  hardcoded paths to move and no need for an abstraction yet.

## Migration order (for the implementation plan)

Low-risk, isolated groups first; the larger / more ramified moves last:

1. **Group B** — proofread sections move. Two files, narrow surface.
2. **Group C** — temp PDF moves (process-journal + process-topic +
   download.py default). Independent of everything else.
3. **Group D** — audit pipeline consolidation. One small code change
   in typecheck.py plus doc fixes; smoke-test `quasi-audit --backfill`
   on a small vault to confirm `translations.json` lands at the new
   path.
4. **Group E** — process-author manifest move. Touches one skill +
   four agent docs in lockstep; smoke-test a small author end-to-end.
5. **Group A** — citation directory move. Largest blast radius;
   land last so prior groups have stabilised.
6. **End-to-end smoke test** — `quasi:wrap-up` on a real draft (full
   pipeline + `--citation-only` re-run), `quasi:process-topic` on a
   small snowball, `quasi:process-author` on a small author,
   `quasi-audit` on the user's vault. Spot-check `.quasi/` shape
   matches the layout diagram. Required before tagging 0.26.0.

Each group is committable on its own; no inter-group ordering
constraint matters for correctness, only for blast-radius isolation
if something goes wrong. The implementation plan should keep groups
as separate commits even if they ship in one PR.

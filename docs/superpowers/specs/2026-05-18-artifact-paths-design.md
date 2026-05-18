# Artifact path discipline — `processing/` vs `.quasi/` — Design

Date: 2026-05-18
Affects: `skills/wrap-up/SKILL.md`, `skills/process-journal/SKILL.md`,
`skills/process-topic/SKILL.md`, `scripts/download/download.py`,
`scripts/proofread/proofread.py`, `scripts/citation/*.py`,
`agents/citecheck-agent.md`, `agents/audit-agent.md`
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

Two audit passes confirm the principle drifted in practice:

1. **Run-internal artifacts living in `processing/`.** The entire
   `processing/citation/{stem}/` tree — `parse.json`, `manifest.json`,
   `biblio.json`, `decisions.json`, and the `verdicts/` subdirectory —
   is read only within a single `quasi:wrap-up` invocation and
   regenerated on every re-run (including `--citation-only`). Same
   for `processing/proofread/{stem}/sections.json`. None of these
   survive their producing run in any meaningful sense; they sit in
   `processing/` only because that root got picked early without a
   sharp survival criterion in place.

2. **Two skills bypass project-local discipline entirely.** Both
   `process-journal` and `process-topic` write downloaded PDFs into
   `/tmp/{name}-pdfs/`, and `scripts/download/download.py:1096`
   defaults `pdf_dir` to `/tmp/snowball-pdfs`. `/tmp/` is outside the
   project tree — invisible to user inspection, escapes any
   project-level cleanup, and (on some macOS configs) gets reaped by
   the OS at unpredictable times.

3. **One documentation inconsistency.** `audit.py` and `typecheck.py`
   actually write `.quasi/audit/typecheck-results.json`, but
   `agents/audit-agent.md` references the file at `.quasi/typecheck-results.json`
   (one level up). Caller behaviour is fine; the doc lies.

There are no hidden log / lock / cache mechanisms — quasi has no
runtime state daemon, every "state" file is a serialised JSON written
by an explicit `Write` call. This is why the fix is purely a string-swap
exercise with no runtime migration.

## Principle (the rule we'll enforce going forward)

A project-local interim artifact belongs in:

- **`processing/`** if and only if **it outlives the skill run that
  produced it** — i.e. a sibling skill consumes it later, a future
  run re-reads it (not regenerates), or the user inspects it as a
  durable record. "Read by a later phase of the same skill run" is
  **not** sufficient: that artifact is still internal to one run, even
  if multiple steps touch it.
- **`.quasi/`** for everything else internal to a single skill run:
  parse buffers, dispatch scratch, per-phase JSON intermediates,
  regenerated indices, audit-trail snapshots, downloaded temp PDFs,
  status flags for the next quasi invocation.

The key test: **if this skill run failed catastrophically and the file
got nuked, would a future re-run lose anything?** If yes → `processing/`.
If the next run would just rebuild it from upstream sources → `.quasi/`.

`vault/` and `sources/` are out of scope — they hold user-facing /
authored artifacts and are not "interim".

## Decision — classification table

Applying the principle: an artifact survives its skill run only if a
**different** skill, a **future** run, or the **user** consumes it.
"Multiple phases of the same run read it" is not survival — that's just
internal plumbing.

| Path | Producer | Consumer | Survives run? | Action |
|---|---|---|---|---|
| `processing/chapters/{slug}/` (txt + manifest) | extract-agent | analyse-agent across many later runs; re-analysis without re-extract | **yes** | stay |
| `processing/authors/{name}/manifest.json` | process-author Phase 1 | Phases 2–6 + user re-runs to add new works | **yes** | stay |
| `processing/translations/{slug}-{lang}.pdf` | translate-agent | user keeps as durable output | **yes** | stay |
| `processing/citation/{stem}/manifest.json` | wrap-up Phase 2.1 | Phase 2.2–2.5 same run only; `--citation-only` regenerates from scratch | no | **move to `.quasi/citation/{stem}/`** |
| `processing/citation/{stem}/biblio.json` | wrap-up Phase 2.1 | resolve + emit-bib same run only; regenerated each run | no | **move to `.quasi/citation/{stem}/`** |
| `processing/citation/{stem}/decisions.json` | wrap-up Phase 2.5 TUI | emit-bib same run only; re-run TUI overwrites | no | **move to `.quasi/citation/{stem}/`** |
| `processing/citation/{stem}/parse.json` | wrap-up Phase 2.1 | resolve same run only | no | **move to `.quasi/citation/{stem}/`** |
| `processing/citation/{stem}/verdicts/batch-*.json` | citecheck-agent | Phase 2.4 TUI input same run only | no | **move to `.quasi/citation/{stem}/verdicts/`** |
| `processing/citation/{stem}/verdicts/recovery-*.json` | search-agent (recover mode) | Phase 2.4 TUI input same run only | no | **move to `.quasi/citation/{stem}/verdicts/`** |
| `processing/proofread/{stem}/sections.json` | wrap-up Phase 1 split | Phase 1 dispatch same run only | no | **move to `.quasi/proofread/{stem}/`** |
| `/tmp/{name}-pdfs/` (journal) | process-journal | analyse-agent same run only | no | **move to `.quasi/temp/journal-pdfs/{name}/`** |
| `/tmp/{name}-pdfs/` (topic) | process-topic | analyse-agent same run only | no | **move to `.quasi/temp/topic-pdfs/{name}/`** |
| `/tmp/snowball-pdfs/` (download.py default) | scripts/download/download.py | caller same run only | no | **change default to `.quasi/temp/snowball-pdfs/`** |
| `.quasi/audit/audit-state.json` | audit-agent | wrap-up Phase 0 gating in **future** runs | **yes (cross-call)** | stay |
| `.quasi/audit/typecheck-results.json` | typecheck.py | audit-agent same call only | no | stay (path already correct in code; **fix audit-agent.md doc**) |
| `.quasi/audit/typecheck-report.md` | typecheck.py | user inspects after audit | no | stay |

The **entire `processing/citation/` directory tree disappears** — all
six citation-pipeline JSON files are wrap-up-run-internal. `processing/`
becomes a clean three-namespace home for genuinely durable interim
output: `chapters/`, `authors/`, `translations/`.

`.quasi/audit/audit-state.json` is the only "stays in `.quasi/` but
survives across runs" file — it's a status flag that wrap-up's next
invocation reads to skip Phase 0. That's not a durable artifact in the
user's sense; it's a daemon-style flag, which is why `.quasi/` is still
the right home.

## `.quasi/` internal layout

We adopt layout **A: mirror `processing/` structure where parallels
exist, freestanding subdirs where unique**:

```
.quasi/
├── audit/
│   ├── audit-state.json           # cross-call status flag
│   ├── typecheck-results.json     # per-call diagnostic
│   └── typecheck-report.md        # user-readable
├── proofread/{stem}/
│   └── sections.json
├── citation/{stem}/
│   ├── parse.json                 # raw cite parse
│   ├── manifest.json              # resolved candidates + status
│   ├── biblio.json                # vault frontmatter index
│   ├── decisions.json             # TUI verdicts (audit trail)
│   └── verdicts/
│       ├── batch-*.json           # citecheck-agent context-fit notes
│       └── recovery-*.json        # search-agent recover-mode output
└── temp/
    ├── journal-pdfs/{name}/
    ├── topic-pdfs/{name}/
    └── snowball-pdfs/
```

The matching `processing/` shape ends up clean:

```
processing/
├── chapters/{slug}/               # extracted ch*.txt + manifest.json
├── authors/{name}/                # discovery manifest.json
└── translations/                  # final {slug}-{lang}.pdf
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

Four logical change-groups. Each group commits atomically; groups can
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

### Group D — audit-agent doc consistency fix

- **`agents/audit-agent.md`** — change the documented path from
  `.quasi/typecheck-results.json` to `.quasi/audit/typecheck-results.json`.
  Doc-only.

### Cross-cutting check (post all groups)

Run once at the end:

```
rg -l "processing/(citation|proofread)" plugins/quasi/
rg -l "/tmp/(snowball|journal|topic)" plugins/quasi/
```

Both should return only this spec file (and the implementation plan if
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

- **Group D (audit-agent doc)** — risk: low. Doc-only.

### User-disk migration

Users may have existing `processing/proofread/` and
`processing/citation/{stem}/` directories from past runs. These
contain files that, under the new layout, would be produced in
`.quasi/`.

**No automated migration.** Rationale:

- All migrated files are run-internal (the Group A move clarified
  this: even manifest / biblio / decisions are run-internal — they're
  rebuilt on every wrap-up invocation including `--citation-only`).
  Old leftovers therefore have no consumer.
- A new wrap-up run produces fresh files in `.quasi/citation/{stem}/`
  and ignores any stale copies under `processing/citation/{stem}/`.
  The stale dirs become harmless orphans.
- Users who want a clean tree can `rm -rf processing/citation
  processing/proofread` themselves at their leisure. Documenting this
  in the 0.26.0 release notes is sufficient.

The `wrap-up` Phase 0 audit step is **not** extended to warn about
stale paths. (Considered and rejected: noise-to-signal too low; most
users don't care; those who do will see the orphans on first `ls`.)

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

Low-risk, isolated groups first; the big citation move last:

1. **Group D** — `agents/audit-agent.md` doc fix. Independent, doc-only.
2. **Group B** — proofread sections move. Two files, narrow surface.
3. **Group C** — temp PDF moves (process-journal + process-topic +
   download.py default). Three files, independent of citation work.
4. **Group A** — citation directory move. Largest blast radius;
   land last so prior groups have stabilised.
5. **End-to-end smoke test** — run `quasi:wrap-up` on a real draft
   (full pipeline + `--citation-only` re-run); run `quasi:process-topic`
   on a small snowball; spot-check `.quasi/` shape matches the layout
   diagram. Required before tagging 0.26.0.

Each group is committable on its own; no inter-group ordering constraint
matters for correctness, only for blast-radius isolation if something
goes wrong. The implementation plan should keep groups as separate
commits even if they ship in one PR.

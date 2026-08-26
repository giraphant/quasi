# Shared OCR Generation Migration Design

**Date:** 2026-08-26  
**Status:** Proposed  
**Scope:** Replace the unshipped Paper-only OCR generation implementation and the shipped Book-only resumable OCR path with one deterministic generation mechanism plus thin material adapters.

## Problem

The repository currently has two OCR state models:

- Book uses `quasi-extract ocr --resume` and `ocr_resume.py` to commit one PDF page range at a time into a fixed recovery PDF.
- The uncommitted Paper work adds a 1,158-line `paper_ocr.py` wrapper with its own generation key, lock, work tree, final manifest, status projection, and publication rules.

The second implementation imports the first implementation's range runner, so the OCR engine is already shared, but nearly all durable generation, observation, and publication policy is Paper-specific. That is the wrong boundary. Source binding, progress, locking, range validation, atomic publication, engine selection, and unknown-outcome handling are properties of a deterministic OCR transaction, not of Papers.

Paper and Book do have different consumers. A Paper sends normalized OCR text to Analyse. A Book sends the recovery PDF and text into chapter planning and splitting. Those differences belong in thin material adapters after one shared generation has been committed.

## Goals

1. One deterministic OCR generation implementation serves Paper and Book.
2. A generation is bound to the exact accepted source and the complete OCR profile.
3. Every invocation commits at most one page range and can be resumed from fresh status testimony.
4. Chunk size is selected by engine profile: DS OCR2 uses 16 pages; Tesseract-only uses 32 pages.
5. The final generation publishes one coherent `ocr.pdf`, `ocr.txt`, and `manifest.json` bundle with manifest-last semantics.
6. Paper and Book keep separate Workflow operation names and downstream Prepare behavior while sharing request/receipt construction and the deterministic capability.
7. Existing released Book progress can finish safely; new work never creates legacy progress.
8. Fixed historical Paper and Book OCR artifacts are never overwritten during migration.

## Non-goals

- Translation `--layout` is not migrated. It requires whole-document dominant-size and paragraph-grouping evidence and remains a separate foreground generation.
- Talk and Webpage do not gain OCR operations.
- OCR page ranges are never processed concurrently for one material.
- The Workflow does not preallocate Agent counts or fan out OCR ranges.
- The Skill does not interpret OCR quality, select engines, or inspect private work state.
- This migration does not add a background worker, job database, hidden cursor, or replay log.

## Architecture

### Shared deterministic capability

Create one shared module, `scripts/extract/ocr_generation.py`, and one public command:

```text
quasi-extract ocr-generation \
  --kind paper|book \
  --slug SLUG \
  --source-file PATH \
  --expected-source-sha256 SHA256 \
  --generation-key SHA256 \
  --profile dsocr2-text|tesseract-text \
  --json
```

`kind` and `slug` select the allowed processing root:

- Paper: `processing/papers/{slug}`
- Book: `processing/chapters/{slug}`

The command derives every work and final path. It rejects paths outside the project, unsafe roots, symlinked components, a source outside the exact material role, and a generation key that does not match the source and profile. Agents cannot choose arbitrary publication targets.

The unshipped `quasi-extract paper-ocr` surface and `scripts/extract/paper_ocr.py` are removed rather than retained as aliases.

### Profile and engine policy

The closed profile is included in the generation-key fingerprint and final manifest. It contains:

```json
{
  "schema_version": "quasi.ocr.profile/0.2",
  "engine_order": ["dsocr2", "tesseract"],
  "chunk_pages": 16,
  "language": "chi_sim+eng",
  "text_extractor": "pymupdf",
  "validation_policy": "paper-text-v1"
}
```

Profiles are named and implemented by the deterministic capability; callers do not supply arbitrary JSON. The effective profile is selected by the closed `(kind, profile name)` pair: the profile name fixes engine order and range size, while the material adapter fixes the validation policy. The fully resolved profile, including that validation policy, is what enters the generation fingerprint and manifest.

- `dsocr2-text` uses engine order `dsocr2, tesseract` and a 16-page range.
- `tesseract-text` uses only `tesseract` and a 32-page range.
- If DS OCR2 fails or its output fails the declared range-quality policy, Tesseract retries that same 16-page range. A fallback does not change range size or generation identity.
- The engine actually used for each committed range is recorded in progress and the final manifest.

Validation policy is declared by the material adapter and included in the profile fingerprint. The shared core always proves readable PDF structure, exact physical page counts, UTF-8 text projection, hashes, sizes, and per-page text signals. Material-specific policy may additionally reject a range. The initial Paper policy retains its strict text-page requirement. The Book policy preserves existing Book acceptance semantics during this migration rather than silently imposing a new professional rule.

### Generation layout

For either material root, the generation owns:

```text
{processing-root}/.ocr-generation.lock
{processing-root}/.ocr-work/{generation-key}/progress.json
{processing-root}/.ocr-work/{generation-key}/parts/pages-000001-000016.pdf
{processing-root}/ocr-generations/{generation-key}/ocr.pdf
{processing-root}/ocr-generations/{generation-key}/ocr.txt
{processing-root}/ocr-generations/{generation-key}/manifest.json
```

The generation key is a canonical JSON SHA-256 over:

- material kind and material key;
- exact project-relative source role;
- source SHA-256;
- complete named OCR profile.

Changing the accepted source, engine policy, chunk size, language, extractor, or validation policy selects a new generation. Existing generations are immutable.

### Progress and range records

Progress is closed JSON and includes the complete source/profile identity plus ordered committed ranges. Each range records start/end pages, exact part path, engine actually used, PDF hash, page count, and quality signals required by its declared policy.

Only the next contiguous range may be created. A new invocation validates every prior part and the complete directory inventory before running an engine. An exact orphan next part caused by interruption between part publication and progress publication may be reconciled after full validation. Any other unexpected inventory is `unknown` and stops.

### Atomic transaction

One invocation performs this sequence:

1. Validate the exact source, project roots, generation key, and profile.
2. Acquire the material generation lock without waiting indefinitely.
3. Observe the current final and work inventories.
4. Return `reconciled` without writing if the immutable generation is already committed.
5. Validate all committed ranges and select the next contiguous range.
6. Run the profile's engine policy for that range only.
7. Re-hash the source and validate the candidate PDF and text signals.
8. Atomically publish the part, fsync its directory, then atomically publish progress.
9. Return `partial` if pages remain.
10. When all ranges exist, merge them in order, validate the merged PDF, extract normalized UTF-8 text, and build the final manifest.
11. Create the immutable final directory, publish PDF and text, fsync, publish the manifest last, and fsync again.
12. Re-observe the final bundle. Only a proven `committed` observation permits work-tree cleanup and a `created` receipt.

An interruption before a part commit leaves no durable claim. An interruption after a part commit is reconciled from that exact part. An interruption during final publication yields `unknown`; no caller overwrites, deletes, or blindly replays it.

### Shared observation

`observe_ocr_generation()` returns one closed capsule for both materials:

```text
missing | in_progress | committed | invalid | unknown
```

It includes material/source/profile identity, exact paths, progress, final artifact facts, and one failure code. `quasi-status` embeds this same capsule as `facts.ocr_generation` for Paper and Book. Workflow code never scans private directories itself.

- `missing`: no work or final generation exists.
- `in_progress`: the exact closed work inventory is safe to advance.
- `committed`: the exact immutable bundle and manifest are coherent.
- `invalid`: a known malformed or mismatched state exists and must not be overwritten.
- `unknown`: unsafe paths, ambiguous inventory, or an unprovable publication outcome exists.

## Material adapters

### Workflow operations

Keep `paper.ocr` and add `book.ocr`. Both rows are produced by one shared `makeOcrGenerationRow()` factory with only material kind, processing root, and validation profile as parameters. They use the same Agent, Stage, request schema, receipt schema, write ownership shape, and complete/blocked/failed coherence checks.

Separate operation names remain useful because Paper and Book have distinct material keys, paths, plans, and professional Prepare goals. This is a thin adapter boundary, not a second OCR implementation.

### Paper

1. `paper.prepare` extracts and reads the accepted PDF's direct text layer.
2. If usable, it returns `prepared` and Paper continues normally.
3. If unusable, it returns `ocr_required` without running OCR.
4. Paper Plan dispatches exactly one `paper.ocr` transaction and returns `needs_observation` after any writer receipt.
5. Once status reports `committed`, `paper.prepare` reads the exact generation `ocr.txt`; it never rewrites or copies it.
6. Analyse consumes that generation text, and complete returns the accepted source, selected normalized text, and canonical page.

The fixed historical `processing/papers/{slug}/ocr.pdf|ocr.txt` paths remain read-only legacy evidence and are never selected as a current committed generation.

### Book

1. `book.prepare` first evaluates the direct PDF text and chapter structure.
2. When OCR is professionally required, it returns `ocr_required` without starting a generic OCR subprocess.
3. Book Plan dispatches exactly one `book.ocr` transaction and returns `needs_observation` after any writer receipt.
4. Once status reports `committed`, `book.prepare` receives the exact generation PDF/text and continues its existing TOC, pattern, manual structure gate, split, and chapter-manifest behavior.

Book's professional structure decisions remain in `book.prepare`; the shared OCR capability has no knowledge of chapters.

## Legacy migration

The migration must preserve released 0.65.27 Book work without creating two active state machines.

- A valid existing `processing/chapters/{slug}/ocr.progress.json` and `.ocr-parts/` inventory may continue through the existing legacy executor until its fixed `ocr.pdf` is completed. This is the only path allowed to write legacy OCR state.
- No legacy progress means all new OCR starts use a generation directory.
- A valid already-complete Book fixed recovery PDF remains available only when the current usable chapter manifest already binds its exact source identity and chapter inventory to that recovery path. It is never rewritten and cannot start a new Prepare. New or unbound source recovery uses a generation.
- Fixed Paper recovery files are read-only and never automatically promoted because they lack a source/profile manifest.
- Legacy observation is explicit and separate from the current `ocr_generation` capsule. A caller never treats both as writable candidates.
- No migration step deletes user artifacts. Cleanup is limited to a generation's own proven private work tree after successful immutable publication.

Once legacy in-progress support is no longer needed, it can be removed in a later release with its own evidence. It is not mixed into the new generation format.

## Workflow and Skill control flow

OCR remains sequential. A 40-page DS OCR2 source requires three logical OCR transactions: 16, 16, and 8 pages. There is never a three-Agent fan-out.

After a writer receipt, a leaf returns the exact material route as `needs_observation`. Collect obtains fresh `quasi-status` testimony and resumes the same leaf. It may continue while the generation makes durable progress; the existing no-progress stopping rule remains the outer safety bound.

Unknown writer outcomes are not replayed. Fresh status may prove that the expected range committed; otherwise the run stops with the generation state intact.

## Failure semantics

- Lock contention is typed retryable blocked and never starts a second writer.
- Source hash or profile drift is a known failed result selecting no existing generation.
- Invalid prior work/final state is blocked without mutation.
- Unsafe paths, unexpected inventory, or ambiguous final publication are unknown and blocked.
- Engine failure after the declared fallback is a known failed range; previously committed ranges remain intact.
- A semantically unreadable committed OCR text is a material Prepare failure, not a reason to rewrite the immutable generation.

## Implementation boundaries

The migration should produce these ownership boundaries:

- `scripts/extract/ocr_generation.py`: common profile, key, observer, transaction, engine policy, final publication.
- `scripts/extract/ocr_resume.py`: retained only as the one-way legacy Book progress executor. New range, observer, profile, and publication work lives in the common generation module.
- `scripts/extract/extract.py`: one `ocr-generation` public route plus the bounded legacy Book route.
- `scripts/status/status.py`: shared observation invoked by Paper and Book status.
- `scripts/workflows/operations/rows/ocr-generation.mts`: shared row/schema factory.
- Paper and Book contracts/plans/rows: thin material-specific Prepare and continuation adapters.
- `agents/extract-agent.md`: one common OCR transaction method plus distinct Paper/Book professional Prepare methods.

Generated artifact contracts and all named bundles are rebuilt; generated files are never edited directly.

## Verification

### Deterministic core

Parameterize the same tests across Paper and Book roots:

- stable source/profile-bound generation keys;
- DS OCR2 16-page ranges and Tesseract-only 32-page ranges;
- DS failure/quality rejection falls back on the same 16-page range;
- actual engine recorded per part;
- one range per invocation;
- source drift, lock contention, corrupt prior part, orphan reconciliation, unsafe path, and unexpected inventory;
- manifest-last publication and exact final inventory;
- killed range and killed final publication behavior;
- no rewrite of a committed generation;
- no writes to fixed legacy Paper/Book paths.

### Status and contracts

- Paper and Book status emit the same closed generation capsule.
- Missing, in-progress, committed, invalid, and unknown states parse identically.
- Shared operation-row tests prove exact paths, write ownership, one capability, and receipt coherence for both kinds.
- Generated entry tests run in the native-like VM realm.

### Material journeys

- Paper direct text skips OCR.
- Paper unreadable text advances 16-page DS transactions to committed text and then analyses.
- Book direct text skips OCR and preserves chapter behavior.
- Book unreadable text advances the same generation mechanism and then performs structure/split.
- Each writer receipt returns `needs_observation`; an unchanged observation stops under the existing outer rule.
- Released Book legacy progress resumes without starting a current generation.

Run focused extraction, status, dispatch, Paper, Book, Author, Topic, and Skill tests; rebuild/check all Workflow bundles; then run the full plugin-venv suite and plugin validation before release.

## Completion criteria

The migration is complete only when:

1. `paper_ocr.py` and the `paper-ocr` CLI no longer exist.
2. Paper and Book both use one active OCR generation module and observer.
3. DS OCR2 ranges are 16 pages and Tesseract-only ranges are 32 pages in source, manifests, status, requests, and tests.
4. Paper and Book operation rows share one factory and differ only through explicit adapter configuration.
5. No active Workflow capability starts the old fixed-path OCR transaction for new work.
6. Legacy Book progress has a tested one-way completion path and fixed legacy artifacts are not overwritten.
7. Paper and Book complete only from fresh source, selected normalized text, canonical/overview, and clean Audit testimony required by their existing contracts.
8. Generated bundles are current, manifests agree, `CLAUDE.md` and `AGENTS.md` are identical, the full test suite passes in the plugin environment, and the release commit is pushed with a clean worktree.

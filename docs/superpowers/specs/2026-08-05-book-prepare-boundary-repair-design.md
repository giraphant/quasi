# Book Prepare Boundary Repair Design

**Status:** Approved in conversation on 2026-08-05.

## Goal

Make a valid Book Prepare generation pass its Workflow boundary, keep chapter splitting bound to the selected PDF, and report rejected private staging generations as known failures.

## Observed failures

The same book exposed two independent boundary defects:

1. A valid PDF TOC generation published 11 chapters, but the specialist echoed absolute `artifacts[].path` values. The receipt schema accepted them and the host later rejected the otherwise coherent completion because request refs are project-relative.
2. After that generation was deleted, the specialist passed `source.txt` to `quasi-extract split`. Pattern splitting then found Chapter 9 once in the contents and once in the body. The private staging manifest was rejected for duplicate slot `09`, but the extractor labelled this pre-publish result `blocked/unknown`.

## Chosen design

Keep the existing ownership and manifest rules and repair only the three leaking boundaries:

- The Book Prepare StructuredOutput schema requires non-empty project-relative artifact paths. The existing completion predicate remains responsible for exact membership and chapter-path agreement.
- The request envelope renders split capabilities with the exact accepted PDF and exact OCR recovery PDF as their only possible positional inputs. The normalized text remains readable evidence and is never advertised as a split input.
- A `ChapterFailure` raised while preparing or validating the private staging manifest is reclassified at that pre-publish boundary as `failed/known`. Durable existing-manifest validation and failures after publication begins keep their current classifications.

The capability binding belongs in the self-contained request envelope rather than in a second Skill rule. The failure reclassification belongs at the staging boundary rather than in the shared durable-manifest validator, because the same validator correctly treats an invalid canonical manifest as ownership-unsafe.

## Rejected alternatives

- Convert absolute receipt paths to relative paths in the host. This would silently reinterpret model output and create a compatibility path instead of expressing the existing contract in StructuredOutput.
- Add automatic retries, cleanup, or a `.txt` rejection cascade. None is needed: the correct PDF input is already known, and the failed staging generation never became durable.
- Relax duplicate-slot or manifest validation. The duplicate slot was real evidence that the wrong input had been split.

## Tests

- A Workflow schema test proves Book Prepare artifact paths accept a project-relative path and reject the observed absolute path.
- A request-envelope test proves PDF split capabilities contain only the exact source PDF or recovery PDF and never the normalized text.
- An extractor test builds a duplicate-slot private staging manifest and proves the receipt is `failed/known`, no final manifest or chapter is published, and staging is removed.
- Existing tests continue to prove malformed durable manifests and ambiguous publication outcomes stop safely.

## Release

Ship as `0.65.4` after the Workflow build/type check, focused tests, full test suite, manifest validation, and mirror-file check pass.

## Explicit non-goals

- No backward-compatibility reader or one-off migration.
- No automatic writer replay or retry.
- No new cleanup command or hidden state.
- No book-specific heuristic for *The Explanation of Social Action*.

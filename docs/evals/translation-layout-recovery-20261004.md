# Translation layout and observation recovery, 2026-10-04

## Evidence and scope

Read-only diagnosis of BTS's four battery books used the installed 0.68.4
translation/OCR implementation and its exact run logs. The local checkout was
already current at 0.68.5 (`af5417b`). This maintenance does not update that
installed plugin or publish any user-vault artifact.

- The Battery and Bottled Lightning finished 326 and 280 pages of recognition,
  respectively, then failed placement at the 3 pt lower bound. The old error
  omitted the page, block and text, and discarded the complete raw recognition.
- Bottled Energy failed on physical page 68's `image_footnote`, which exists in
  the pinned mineru-vl-utils 2.0.5. Extending the earlier whitelist had merely
  deferred the next false rejection.
- Charged's observing agent encountered EPERM while reading temporary receipts,
  logs and Python modules. It returned blocked at 19:47 London while the same
  translation completed at 19:48:59. Its PDF/manifest/receipt subsequently agreed:
  514 pages, 14 bookmarks, Chinese body median 0.314556 over 205 measured pages,
  zero near-zero pages, 47 reference pages excluded. No second translation was
  required. The exact OS cause of EPERM was not established.

## Changes and their boundaries

Block labels now choose presentation instead of deciding whether data is
admissible. Unfamiliar nonempty content becomes ordinary text; an unfamiliar
empty/container block adds no text. Known visual blocks retain their image
treatment, and known footnote/title aliases retain their presentation. This
changes the downstream projection as well as removing the whitelist, avoiding
silent loss from a later text-only filter. Geometry, usable fonts, full-paragraph
placement and recognized-content checks remain at the renderer that needs them.

`--recognition-json` names one explicit raw-data artifact owned by Translation
Prepare. Complete recognition is saved before normalization/placement; retries
reuse it when source/model/render profile and page count match. The raw result
does not depend on placement implementation, is not a second PDF, and does not
prove that a PDF exists. It is not a progress cursor: an interrupted incomplete
inference still has to run again. Existing unrelated data is preserved.

Read-only translation observation can report an actually held publication lock
as `running` and verify a committed PDF/manifest as `reused` without relying on
temporary stdout/stderr. Merely finding a lock filename is insufficient. A
PDF-before-manifest publication window remains running, with no completed-output
proof. Agent guidance keeps observing an identifiable existing writer through a
temporary read failure; it does not launch another writer. This cannot override
OS permissions or prevent a Host from ending an invocation.

## Real-page check

One cached local MinerU run recognized 41 sample pages: The Battery 1–20,
Bottled Lightning 1–20, and Bottled Energy 68. It used the existing fixed model,
200 dpi rendering and pinned dependencies. Scratch results are under
`/private/tmp/quasi-layout-repair-probe/`; no provider translation ran.

| Sample | Result |
| --- | --- |
| The Battery 1–20 | Layout prepared; all 12,924 projected non-whitespace characters round-tripped in order; rendered pixels unchanged on every page. The historical failure elsewhere in the book was not located by this sample. |
| Bottled Energy 68 | Both `image_footnote` blocks retained; all 1,286 projected non-whitespace characters round-tripped in order; rendered pixels unchanged; layout proof valid. Visual review confirmed the diagram and both footnotes remain intact. |
| Bottled Lightning 16 | Reproduced placement failure, now naming page 16, block 1, its rectangle, rotation and text. A second block also fails the same fit check. No layout PDF was published. |

Visual inspection of Bottled Lightning 16 shows a nearly blank sheet with
show-through. MinerU produced an invented sequence through 100, a Chinese 2023
  company-announcement sentence and other unrelated text. This is recognition
failure, not evidence that the font-size floor is too strict. The patch therefore
does not shrink hallucinated text further or automatically discard suspect
blocks. Saving and locating this evidence makes local diagnosis possible; an
automatic correction policy for such pages is outside this change. The checks
above are sample validation, not successful whole-book translation.

The changed `observe(mode="final")` implementation also ran read-only against
Charged's existing exact recovery source and manifest configuration. Without
opening temporary stdout/stderr, it returned `status:succeeded`, `signal:reused`,
generation attempt 2, 514 output pages, 14 TOC entries and `failure:null`.
The observation is saved at `/private/tmp/quasi-charged-final-observation.json`.

## Thought ablation

| Remove or add | Consequence | Decision |
| --- | --- | --- |
| Remove type rejection without changing downstream selection | Unknown text silently disappears. | Use content projection at normalization. |
| Keep extending the type enum | Next upstream label can stop another full book. | Remove label admission altogether. |
| Remove source/model binding on saved recognition | A different PDF or recognizer's pages can be reused. | Keep this one reuse-boundary check; do not bind placement code or timestamps. |
| Save only after PDF success | Every placement error loses completed OCR. | Save complete raw pages before placement. |
| Add per-block receipts, cursors or retry counters | More orchestration state without fixing either failure. | Add none. |
| Require temporary logs after a valid canonical commit | A completed Charged still looks blocked. | Accept canonical proof independently. |
| Treat any lock filename as running | Stale files can cause indefinite waiting. | Inspect the actual existing lock, without creating one. |
| Replay a writer after EPERM | Risks duplicate paid work and concurrent publication. | Restore observation only. |
| Lower the 3 pt floor until every block fits | Can encode invented text from an effectively blank page. | Retain the fit boundary and expose the original block. |

No coverage threshold, second receipt validator, whole-book retry controller,
new completion gate or automatic OCR-engine fallback was added. The extra JSON
is raw OCR data at a declared output path. Tests cover the real failure boundaries
without requiring a live model in the normal regression suite.

## Regression validation

- Full suite: **1,914 passed, 1 skipped**, 247.34 seconds. The skipped case is the
  opt-in paid Host E2E. Existing local HTTP/native WebKit tests ran with the
  permissions needed by those fixtures. Log:
  `/private/tmp/quasi-translation-full.log`.
- After the last source-check refinement, **51 focused OCR/recovery tests passed**.
  Coverage includes raw recognition surviving failed placement and PDF staging,
  reuse without another inference, refusal to overwrite mismatched recognition,
  full unfamiliar-block text round trips, exact failure locations, an active
  publication window, a stale lock file, and canonical reuse without stdout/logs.
- Workflow build/parity and strict TypeScript checks passed. Maintainer instruction
  mirrors are byte-identical; diff whitespace checks passed.

No live Host permission-failure replay or whole-book translation was claimed.

# Local OCR correction after the Bottled Lightning retry

The user's 0.68.6 retry finished recognition of all 280 pages and retained its
source-bound JSON, then failed on physical page 16. The previous maintenance had
made this diagnosable and preserved costly inference but had not supplied an
agent-owned correction capability. Repeating the same placement could not help.

## Complete saved-result inspection

No inference or paid translation was started. A read-only placement probe used
the existing BTS recognition and identified nine unplaceable blocks on seven
pages. Each of those source pages was rendered and visually inspected.

| Physical page | Original evidence | Applied correction |
| --- | --- | --- |
| 16 | Blank sheet with show-through; invented numeric sequence and unrelated prose | Empty reviewed block list; keep scan image |
| 21 | Printed page number 5; OCR says `[NO TEXT]` | Replace block 2 content with `5` |
| 117 | Header THE LITHIUM WARS; OCR repeats thousands of numeric tokens | Replace block 1 content with the visible header |
| 135 | Header THE BRINK; OCR repeats thousands of numeric tokens | Replace block 1 content with the visible header |
| 234 | Blank sheet with show-through; two invented, very long blocks | Empty reviewed block list; keep scan image |
| 242 | Header NOTES; OCR produces a sentence claiming the page is blank | Replace block 2 content with `NOTES`, preserving all actual notes |
| 260 | Header INDEX; OCR repeats thousands of numeric tokens | Replace block 2 content with `INDEX`, preserving both index columns |

All five nonblank reviewed pages copied their original block lists and changed
only the indicated `content`. There is no book-specific page list or string
blacklist in the implementation.

## Capability and ownership

The existing `ocr --layout --recognition-json` command accepts an optional
`--review-json` containing the source SHA-256 and selected physical pages. Each
page has a visual-review reason and its complete replacement block list. The
Translation Prepare envelope names the exact optional review path and permits
the specialist to write it. The agent owns reading the page and judging the
correction. No review is required for successful ordinary processing.

Paragraph fit errors are collected across the layout pass, allowing a batch of
local corrections instead of finding one failing block on each re-placement.

The CLI only applies reviews to saved recognition and image-bearing pages. It
does not start inference if that saved input is missing. It retains source
binding, page bounds, font coverage, normalization and complete paragraph fit.
A reviewed blank may override an old noisy text layer; unreviewed missing text
still follows the existing check. The raw JSON remains intact. The applied
review is embedded inside the recovery PDF, and explicit review requests must
match that embedded data before an existing PDF can be reused. Unrelated or
stale outputs are never overwritten.

## Whole-book result

Re-placement of all **280 pages succeeded**, using only the existing recognition:

- **477,599 projected non-whitespace characters** extracted in the expected order,
  checked separately on every page; no page differed.
- Rendered pixels matched the source on **all 280 pages**. Representative reviewed
  output pages were also inspected visually.
- The full source-bound layout check passed, with the review embedded exactly.
- The existing old/new OCR comparison measured 920 body blocks with zero reported
  disagreements. This is an agreement signal, not a semantic accuracy guarantee.
- The source and output both have zero embedded TOC entries; bookmark generation
  and provider translation were not part of this validation.

Source SHA-256:
`7ddb5225df4cf17799cd00cdd0f43b575a132436e6b685bb3dd8832374ea63d9`.
Retained recognition SHA-256:
`3c5213d0adda2ed4ef5418368d9d1707711e4c01ab79e849992df2cffb8e5096`.

Scratch evidence:

- `/private/tmp/quasi-lightning-failed-pages.json`
- `/private/tmp/quasi-lightning-layout-review.json`
- `/private/tmp/quasi-lightning-reviewed-layout.pdf`
- `/private/tmp/quasi-lightning-reviewed-verification.json`

MuPDF emitted a missing-xref diagnostic during save; the written PDF reopened,
passed layout evidence, and rendered every page identically to the source. No
separate source-repair behavior was introduced for that diagnostic.

The user vault and raw evidence were not changed. No canonical recovery or
Chinese PDF was published, no other book was restarted, and this check does not
claim that the eventual provider translation passes coverage.

## Thought ablation

- Lowering the 3 pt floor would encode hallucinations. Keep fit validation and
  permit evidence-based correction before it.
- Automatically treating every failed page as blank would delete real body text
  on five of the seven affected pages. Keep visual judgement with the specialist.
- Dropping every header would avoid several failures while losing real text.
  Correct the visible heading/page number instead.
- Editing raw recognition would erase the original evidence. Keep an optional
  review input and embed the applied corrections in the PDF.
- Requiring another approval gate, state cursor, review receipt or all-page audit
  would not resolve this local failure. Add none of them.
- Binding review data to placement code or OCR file timestamps would make a
  renderer update invalidate useful corrections. Bind to source content only;
  the replacement pages are self-contained and do not depend on raw block indices.

Regression tests exercise the actual CLI: initial fit failure, successful local
review without uvx, preserved source/raw/image/body content, applied-review
provenance, existing-output mismatch, missing recognition, wrong source/page,
native-text protection and a reviewed paragraph that still cannot fit.

Full suite: **1,919 passed, 1 skipped**, 249.89 seconds; the skipped test is the
opt-in paid Host E2E. After the final source-binding/fit-report refinement,
**156 focused extraction/recovery tests passed**, including one newly added
unplaceable-review case. The **21 required contract tests** also passed, as did
Workflow parity, strict TypeScript, plugin validation, maintainer mirrors and
diff checks. Logs are `/private/tmp/quasi-layout-review-full.log` and
`/private/tmp/quasi-layout-review-final-targeted.log`.

The final public CLI reported all nine original fit failures in one failed
invocation without publishing an unreviewed PDF. Passing the reviewed input
then reconciled the validated scratch layout as `existing`, without new OCR.
No live model-Host behavioral acceptance or provider translation is claimed.

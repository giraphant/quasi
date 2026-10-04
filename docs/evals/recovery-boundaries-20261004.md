# Recovery boundaries: maintenance and ablation review

Date: 2026-10-04. Based on main at `af5417b` (0.68.5), after a successful
`git pull --ff-only` reported already up to date. Repository maintenance only;
installed plugins and user-vault artifacts were not changed.

## Problem and ownership

The review started with Book PDF bookmarks and the purpose of source hashes,
then examined cases where a useful validation prematurely stops the whole task.
The repair keeps final artifact requirements while removing redundant work and
finishing already identified repairs before judging the material again.

| Boundary | Responsibility after this change |
| --- | --- |
| Deterministic extraction CLI | Validate exact source content, extraction options, owned files and publication preconditions; keep atomic publication and source-drift checks |
| Extraction specialist | Correct errors with known unchanged or fully rolled-back outputs inside its existing operation; preserve typed gates and unknown-outcome stopping |
| Material Workflow | Dispatch every distinct Book owner named by audit, chapters before overview, then audit the repaired set; accept a clean Paper audit even when that audit mechanically repaired files |
| Main-agent Skill | Continue `needs_observation` within the active user task, using fresh exact status and the returned continuation; do not turn it into a request to say “continue” |

Book's chapter join now preserves uncertainty and actual failed siblings instead
of hiding them behind a refresh request. Only the existing typed, pre-write
output-observation mismatch requests fresh observation. This is a correction to
the existing unknown-writer contract, not a new class of validation.

The current Workflow host exposes agent and pipeline operations, not filesystem
reads. The main-agent continuation remains a model-executed bridge. Prompt changes
cannot establish that every host/model will continue autonomously; no deterministic
host continuation, new interpreter or live-model acceptance is claimed here.

## Ablation thought experiment

These are counterfactual design checks, not measured model-performance experiments.

| Remove or change in isolation | Consequence | Decision |
| --- | --- | --- |
| Require an audit with no mutations after an already clean audit | Mechanical fixes cause another dispatch, and a later mechanical fix can prevent completion despite a clean result | Remove Paper's extra stability pass; retain verification after CLI fixes and any manual edit |
| Repair only the first Book audit target | A second audit sees the other known defects before their owners have had a chance to repair them | Repair the existing finite set of distinct flagged owners once, then run the existing final audit |
| Remove the final audit after semantic repairs | Producer success would substitute for artifact validation | Retain the final audit and residual-violation failure |
| Treat every tool error as terminal Prepare failure | Correctable invocation/extraction errors escape the professional owner too early | Keep local recovery with the specialist when the durable outcome is known |
| Automatically retry every `retryable:true` receipt | Unknown or genuine failed work can be duplicated or silently reinterpreted | Keep the specific known pre-write refresh route; other failures retain their meaning |
| Refresh because one chapter has stale observation, ignoring siblings | Another chapter's unknown writer or substantive failure disappears behind continuation | Join all outcomes first; preserve uncertainty and real failures before the refresh |
| Remove the source hash from chapter reuse | Changed PDF/EPUB bytes can reuse stale chapter text | Retain SHA-256, exact path, size, extraction mode/options and filter signature |
| Include mtime in the reuse identity | Touching an unchanged source rebuilds chapters and rejects exact slot repair | Remove mtime from reuse identity; retain the full observation for detecting changes during extraction |
| Drop compatibility with timestamp-bound manifests | Existing valid chapters rebuild merely because the fingerprint algorithm changed | Verify the historical request against its recorded observation and current content/options; reuse without rewriting the manifest |
| Add another global validator, recovery state file or retry budget | More control flow and competing ownership, without resolving any of the demonstrated failures | Do not add them; reuse the existing receipt, status and transaction contracts |

No new receipt status, persisted state, numerical threshold, user approval gate,
or universal retry loop was introduced. The compatibility branch is not a new
requirement on a current manifest: it only allows a previously valid generation
to be reused. Hash validation still proves byte identity, not semantic correctness.

## Bookmark implications

The earlier isolated fixture experiment used real chapter CLI and OCR transaction
code with a synthetic OCR runner. It found:

- Adding bookmarks before chapter extraction produced a manifest bound to the
  resulting PDF; an unchanged outline skipped rewriting and the next extraction
  reconciled successfully.
- Adding bookmarks after extraction changed PDF bytes and rebuilt identical
  chapter text. Reapplying the same outline unconditionally could change the hash
  again. The pre-maintenance mtime-only case also rebuilt identical chapters.
- A 17-page OCR fixture advanced in 16+1-page ranges. Changing its source PDF
  bookmarks invalidated the old source-bound generation request. The existing
  merge lost source outlines; an in-memory prototype restoring them before final
  publication preserved them and allowed stable chapter extraction afterward.

These observations explain why changing a single stored hash after publication
is insufficient: OCR generations and normalized-text evidence also bind PDF bytes.
They do not establish that bookmarks need a second user-facing PDF.

A reviewed chapter manifest is a useful authority for bookmark labels and physical
page destinations. A future implementation should place that PDF mutation inside
an explicit publication boundary and make identical-outline writes idempotent.
This maintenance does not implement bookmark writing, relax immutable OCR
generations, or introduce semantic PDF hashing/provenance migration. The current
flat chapter inventory also does not preserve all outline hierarchy or the page
destinations of skipped sections; it is not yet a complete book TOC contract.

The scratch fixture results were at
`/private/tmp/quasi-bookmark-order-nzauo8x4/results.json`; they are exploratory
evidence, not a new production feature or a real-book OCR/TOC quality evaluation.

## Validation

Regression coverage exercises clean-but-mutating Paper audits before and after
semantic repair; all flagged Book owners and diagnostic grouping; stopping between
repairs when a writer disappears; sibling-failure precedence; Author propagation;
timestamp-only reuse of current and historical manifests; timestamp-only slot
repair; and changed PDF bytes with identical size and timestamp. Existing conflict,
manifest-precondition, extraction, audit and dispatch tests remain in place.

Workflow specialists are stubbed in these tests. No paid provider, real model
inference, live host acceptance, user-vault write, plugin installation or release
was performed.

The initial focused run passed 435 tests and exposed one inherited Author test
which incorrectly treated an unknown writer as a fresh-observation continuation.
That expectation was replaced with coverage for both the known pre-write mismatch
and the unknown writer. The deprecated Topic composition fixture had the same
obsolete expectation and was updated to use the known mismatch for its refresh case.

The full suite ran 1,906 cases: **1,877 passed, 28 failed, 1 skipped** in 191.77s.
The failures comprised that already-corrected Topic fixture and 27 tests requiring
local HTTP sockets, native WebKit processes or Swift compiler access unavailable
inside the sandbox. All **28 passed** on the targeted retry in 147.69s, using the
same interpreter/dependencies outside the sandbox and temporary plugin-data and
compiler-cache directories. Across these runs, **1,905 tests passed**; the one
paid Host E2E remains opt-in and was skipped. No runtime dependency was installed.

`npm run build:workflows` regenerated the bundles, including the Author and
deprecated Topic compositions that embed Book/Paper. `npm run check:workflows`
(generated parity and strict TypeScript), `cmp -s CLAUDE.md AGENTS.md` and
`git diff --check` passed. Logs were retained at
`/private/tmp/quasi-maintenance-full-tests.log` and
`/private/tmp/quasi-maintenance-retry-tests.log`.

# Book Audit Path Identity Design

## Problem

`book.audit` owns the canonical Book subtree because it may report violations
against either `00-overview.md` or one of the exact chapter outputs. Its receipt
therefore accepts a diagnostic path as a bounded string rather than constraining
it to one schema `const`.

The Book plan currently compares that string directly with project-relative
owner paths. When Audit reports the absolute spelling of an owned chapter, the
comparison and subsequent chapter-map lookup fail even though both spellings
identify the same file. The plan then returns `workflow.owner_ambiguity` instead
of performing the bounded repair.

## Scope

This change fixes Book audit ownership and repair routing only. It does not
change artifact schemas, Audit judgement, the one-repair budget, or the terminal
meaning of a remaining soft violation. Other material audits use different
exact-target contracts and are outside this incident.

## Path identity

Add one pure shared Workflow helper that converts a non-empty path into a
lexically resolved absolute identity:

- The trusted project root is non-empty `CLAUDE_PROJECT_DIR`, otherwise cwd.
- A project-relative path resolves against that root.
- An absolute path remains anchored at its own root and is normalized.
- No filesystem lookup or `realpath` is performed; ownership remains a
  comparison against the exact artifact inventory rather than a directory scan.

Two path spellings are equivalent only when their resolved identities are equal.
Consequently, an absolute path outside the project, a different Book path, or an
unlisted file inside the Book directory does not match an owner.

## Book audit flow

The Book plan builds its owner inventory from the existing exact relative
paths: one overview and the chapters admitted by the manifest/status testimony.
It indexes that inventory by resolved path identity while retaining each
project-relative owner path and chapter row.

For both the first audit and the second audit:

1. Resolve every escalation path to its identity.
2. Stop with `workflow.owner_ambiguity` if any identity is absent from the exact
   owner inventory.
3. Group first-pass diagnostics by resolved identity, so absolute and relative
   spellings of the same artifact remain one repair target.
4. Route repair through the retained owner record: `chapter.analyse` for a
   chapter and `book.synthesise` for the overview.
5. Check observed/current-run chapter evidence with the retained relative owner
   path, not with the Audit spelling.

The original diagnostic objects remain unchanged in `repair_diagnostics`; path
normalization is used only for Workflow ownership and routing.

## Terminal behavior

- A first-pass absolute path for an owned chapter or overview follows the same
  repair path as its project-relative spelling.
- A foreign or unlisted path still returns `workflow.owner_ambiguity` before a
  repair writer is dispatched.
- A clean second audit completes the Book.
- A second audit that still reports an owned `block_kind_mismatch_soft` returns
  `workflow.repair_exhausted`, preserving evidence without misclassifying its
  owner.

## Tests and build

Add focused Book plan regressions that prove:

- an absolute owned chapter path routes to `chapter.analyse` repair;
- an absolute owned overview path routes to `book.synthesise` repair;
- relative owned paths retain their existing behavior;
- an absolute foreign path is rejected;
- a second owned absolute-path escalation is classified as repair exhaustion,
  not owner ambiguity.

Run the focused material-plan tests, rebuild generated Workflow bundles, verify
bundle/type parity, and then run the full Python suite plus plugin validation.

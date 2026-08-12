# Book Observation-Backed Recovery

## Goal

Let a Book run recover from ambiguous chapter-writer outcomes without weakening
Stage schemas, replaying already usable chapters, or asking the user to manually
restart the material.

The change extends the existing `needs_observation` handshake. It does not add a
retry engine, durable cursor, operation ledger, lock, or second material-state
file.

## Problem

Book currently dispatches every chapter in one `pipeline()`. If any chapter
Agent returns no consumable receipt, the join returns
`workflow.unknown_outcome`. Successful sibling artifacts remain on disk, but the
Book result is immediately `blocked`, so the outer Agent must diagnose and
restart the material manually. A later fresh `quasi-status` already contains the
evidence needed to resume safely; the current runtime simply does not request
that observation itself.

This failure is not evidence that the artifact or Stage schemas are too strict.
An unknown outcome means only that the Workflow cannot prove whether the writer
committed. Re-observing the exact durable path is the safe recovery boundary.

## Design

### One existing observation pump

The Skills remain the sole filesystem observers. Their execution rule becomes:

1. When a Workflow returns `needs_observation`, run fresh `quasi-status` for its
   exact `routes`.
2. Copy the returned `resume_seed` unchanged into the same named Workflow and
   supply the fresh observations in that entry's existing input shape.
3. Continue while the material advances. If the same requested observations
   remain unchanged for two consecutive recovery cycles, stop and report that
   recovery stalled.

This is main-process guidance in `SKILL.md`, not a coded fingerprint, counter,
generic controller, or persistent state. The Skill does not interpret chapters,
operations, or repair policy.

### Book opts into recovery

At the chapter join, `unknown_outcome` and an incoherent completion with
ambiguous write state return `needs_observation` for the exact canonical Book
route together with the Book leaf continuation. A schema-valid specialist
`blocked` or `failed` remains a real terminal and is not silently retried.

On entry with fresh Book status, the plan dispatches only chapters whose exact
canonical output is not already usable. Usable chapter outputs are durable
progress and do not receive reconciliation Agents. Once the observation plus
the current invocation prove all chapter outputs, Book continues to synthesis
and audit normally.

This makes recovery stepwise: for a 13-chapter Book with 11 usable outputs, the
next invocation owns only the two unresolved chapter paths.

### Author and Topic only lift the request

Author and Topic already transport `needs_observation` through opaque
continuations. If a composed Book returns that terminal, the composition plan:

- stores the Book's updated leaf continuation in its existing outer
  continuation;
- returns its existing `needs_observation` result with exact child routes; and
- performs no progress comparison, retry counting, or Book-specific reasoning.

Thus Author and Topic do not gain separate recovery controllers. Their own
discovery, synthesis, and audit unknown outcomes remain unchanged in this first
version.

### Public contract

`quasi.material.result/0.1` keeps its existing JSON shape and version. Its
`needs_observation.resume_seed` union is widened to admit a leaf continuation in
addition to the existing Author and Topic continuations. Direct Book callers use
the leaf continuation; composition callers wrap it in their existing opaque
continuation.

## Error semantics

- `unknown_outcome` at the Book chapter join requests fresh observation.
- `incoherent_complete` at that join requests fresh observation because a write
  may already exist.
- A schema-valid `needs_input` remains a user gate.
- A schema-valid `blocked` or `failed` remains terminal.
- An exact usable output is skipped on resume.
- A present but unusable output is not treated as successful durable progress;
  existing owner-correct handling remains responsible for it.
- Two consecutive recovery observations with no change stop the Skill loop and
  surface the last typed issue and status rather than spinning indefinitely.

## Scope and non-goals

The first version covers Book chapter fan-out, including a Book composed inside
Author or Topic. It does not automatically recover Paper, Talk, Translation, or
Author/Topic-owned writers. Those plans may opt into the same handshake later
only if runtime evidence shows a recurring need.

It does not revive the old synthesis-agent disk scan or all-chapter refill. It
does not weaken StructuredOutput validation, replay an ambiguous writer inside
the same Workflow invocation, or add generic retry policy to operation rows.

## Tests

Protect only the causal seams:

1. A Book chapter `unknown_outcome` returns an exact Book
   `needs_observation` continuation rather than `blocked`.
2. Fresh status proving 11 of 13 usable outputs dispatches exactly the two
   unresolved chapters, then synthesises after coherent completion.
3. A schema-valid child `blocked` or `failed` is still surfaced without an
   observation loop.
4. Author and Topic lift a child Book observation request without interpreting
   or rebuilding the leaf continuation.
5. A Skill orchestration scenario exercises direct-leaf observation recovery
   and the two-unchanged-observations stop rule. Contract tests check the
   terminal shapes and routing names, not snapshots of prose sentences.

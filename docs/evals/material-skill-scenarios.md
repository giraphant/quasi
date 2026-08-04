# Material Skill Consumer Scenarios

These are manual or headless consumer checks for the thin `collect-material`
driver. They are not deterministic unit tests: each run records the actual
Workflow result and exact `quasi-status` evidence from a disposable vault.

## 1. Ordinary leaf completion

**Fixture:** one Paper (or Book/Talk/Translation) whose input is available in a
disposable project root.

**Run:**

1. Record `quasi-status --kind <kind> --slug <request-key> --json`; for
   Translation also pass `--target-language <normalized-target>`.
2. Invoke the matching named Workflow through `collect-material`.
3. Record the returned `quasi.material.result/0.1`.
4. Record exact post-status at `result.material.canonical.slug`.

**Pass evidence:** one named Workflow handled the logical material; the result
is `complete`; every returned artifact is present and usable in post-status;
the Skill did not choose a stage or consume a Stage receipt.

**Last run:** not yet recorded.

## 2. Typed gate and fresh-observation resume

**Fixture:** a real identity, Book-year/structure, or Translation-source
ambiguity.

**Run:**

1. Capture the `needs_input` MaterialResult and user-visible gate.
2. Answer the gate.
3. Run one fresh exact status for the returned `resume_seed.route`.
4. Restart the route's named Workflow with `resume_seed.seed`,
   `resume_seed.options`, that fresh observation, and a `UserDecision` whose
   `material_key`, `operation`, and gate testimony are copied byte-for-byte;
   add only the user's selected candidate, source path, or action in the owning
   gate's closed value shape.

**Pass evidence:** the Skill does not derive a new decision key, canonical slug,
operation, candidate set, conflict set, year evidence, temp path, source
fingerprint, seed, route, or options; `translation_configuration` uses Configure
plus the returned continuation and no decision object; the resumed Workflow
either completes or returns a new typed terminal honestly. A Book identity gate
followed by a year/structure gate resumes from the latter gate without replaying
the identity decision; Translation source→configuration retains the selected
source in the returned effective options.

**Last run:** not yet recorded.

## 3. Two-material batch

**Fixture:** two distinct leaf request keys, optionally of different kinds.

**Run:** process both through `collect-material`, allowing both named Workflows
to be in flight.

**Pass evidence:** at most five Workflows are in flight; each exact key has at
most one owner; a stop in one item does not cancel the other; the report restores
original input order. Only byte-identical pre-launch keys are coalesced.

**Last run:** not yet recorded.

## 4. Malformed intake

**Fixture:** a public material envelope that violates its fixed entry parser,
such as a Paper provisional seed with neither title nor DOI.

**Run:** invoke the relevant generated named Workflow through the same wrapper
used by the Skill.

**Pass evidence:** the result is `terminal:"blocked"` with
`issue.code:"material.invalid_input"`; the Agent call count is zero; the Skill
does not pre-validate by reproducing the TypeScript contract.

**Last run:** not yet recorded.

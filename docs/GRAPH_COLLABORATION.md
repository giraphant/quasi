# Named Workflow collaboration model

Maintainer guidance for how quasi divides authority between Skills, named
Workflows, specialist Agents, and deterministic capabilities. Active Skills and
Agent contracts should contain only what their executing model needs.

## Layers

1. **Skills** (`skills/*/SKILL.md`) recognise user intent, construct one closed
   Workflow input, obtain exact `quasi-status` observations requested by the
   Workflow, present typed gates, and verify final artifacts.
2. **Named Workflows** (`workflows/{paper,book,talk,translation,author,topic}.mjs`)
   own fixed material progression. Their editable TypeScript plans live under
   `scripts/workflows/`; material-local catalogs select only their own operation
   rows.
3. **Operation rows and Agents** own one specialist boundary. A row derives exact
   refs, prompt, receipt schema, and a small cross-field completion predicate. The
   Agent owns professional method, local recovery, and its honest terminal.
4. **CLIs** (`bin/quasi-*`, `scripts/`) perform deterministic observation and I/O.
   A writer touches only outputs named by its command or Agent envelope.

`scripts/schemas/operations.py` supplies operation identity and artifact templates to both Workflow
builds and `quasi-status`; it does not define a stage graph.

## Trust rules

- **The host proves shape.** StructuredOutput validates the model-facing Stage
  receipt. The prepared-dispatch boundary stamps host-owned single-value fields
  after validation; callers do not run a second receipt validator.
- **Disk proves durable facts.** Skills pass exact `quasi-status/0.2`
  observations. A Material result never authorises guessing another path or
  treating prose as writer success.
- **The specialist owns judgement.** A schema-valid
  `complete|needs_input|blocked|failed` Stage terminal is not reinterpreted by a
  plan because another method looks preferable.
- **The named plan owns progression.** Paper, Book, Talk, Translation, Author,
  and Topic each have one explicit plan. There is no universal mode engine,
  runtime stage router, or durable Workflow cursor.

## Public and internal results

The public boundary is `quasi.material.result/0.1`. A named Workflow returns one
material-level terminal:

- `complete`, with exact artifacts and an optional typed next material;
- `needs_observation`, with exact routes and one opaque continuation;
- `needs_input`, with a typed gate and, for composed leaf gates, the effective
  continuation;
- `incomplete`, only for a bounded Topic result with ordered pending work; or
- `blocked|failed`, with one typed issue.

Inside a plan, each prepared operation returns `quasi.stage.receipt/0.3` with
exactly four specialist terminals. StructuredOutput repair while that Agent is
still running is provider-level correction, not a new operation dispatch.

## Composition rules

- One named invocation owns one logical material. Only Book uses host
  `pipeline()` internally, for chapter outputs whose exact write targets are
  disjoint.
- Author composes Paper and Book plans. Topic composes Paper, Book, and Talk
  plans plus Topic-owned rows. Any named Workflow may request fresh exact host
  observations through `needs_observation`; the Skill copies the opaque continuation
  back unchanged. Complete returned status observations for the same routes advance only
  when they differ byte-for-byte; it stops after two consecutive byte-for-byte identical
  recovery observations.
- Unknown writer outcomes stop. A `needs_observation` recovery refreshes status for the
  same Workflow; it never blindly replays the writer.
- A Skill may run different top-level material Workflows concurrently after
  exact material keys are known. The plans do not add a second scheduler, lock,
  reservation, replay log, or collision-cleanup layer.
- `needs_input` is shown at the owning boundary. Only the gate's declared value
  is added on resume.

## What must not return

- a universal stage runner, `until` mode, batch envelope, FIFO lane scheduler,
  generic graph executor, or compatibility alias for one;
- per-Agent query counts, provider cascades, OCR heuristics, or recovery trees in
  Skills or operation rows;
- path discovery outside an exact envelope, duplicate writer ownership, or a
  second hidden material-state file; or
- broad tests that enumerate generic modes instead of protecting a concrete
  causal seam.

## Project roots and observability

cwd is the project/vault root. A non-empty `CLAUDE_PROJECT_DIR` takes precedence;
Workflow specialists may receive it empty and then use cwd. Headless
`claude -p --output-format json` stdout is only the final session envelope; E2E
diagnosis may also require the session JSONL and per-Workflow sidecars.

## Tests

Keep tests at ownership boundaries:

- capability CLI and status observations;
- generated schema, operation-catalog, and bundle parity;
- prepared dispatch host stamping and the four closed Stage terminals;
- one causal journey for each meaningful material transition, typed gate,
  unknown-writer stop, join, checkpoint, and owner repair; and
- Skill routing and dead-name quarantine.

Do not recreate deleted stage-order, ingress, batch, retry, or scheduler matrices.
A characterization test for retired machinery is not a compatibility contract.

## Migration record

- **0.55.0:** the self-running graph driver was replaced by Skill-driven Stage
  dispatch and exact disk observation.
- **2026-08-04 named-entry cutover:** Paper, Book, Talk, Translation, Author, and
  Topic gained fixed named Workflows. The universal Stage compatibility engine
  and its mode tests were then retired; Stage receipts remain only as the
  internal Agent boundary.

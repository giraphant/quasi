# Material-Oriented Workflow Refactor

date: 2026-08-04
status: awaiting user review

## Summary

Replace the public, universal `run-stage` controller with one official Claude Code
Workflow per first-order material kind: Paper, Book, Talk, and Translation. Keep
the official Workflow runtime where it adds unique value—host-enforced structured
agent output—and move each material's control flow into a small, readable
TypeScript plan.

The user-facing Skill becomes a thin interaction shell. It identifies the route,
observes disk state with `quasi-status`, invokes the selected material Workflow,
and either presents the result or asks the typed human-gate question. It no longer
chooses stages or understands material-specific branching.

The objective is maintainability, not minimum source lines. Generated bundles may
duplicate shared bytes; authored business logic must not be duplicated.

## Context

Quasi has passed through several control shapes: an early Skill controller, a
self-running Workflow Graph, and the current Skill-driven generic official
Workflow. The early Skill controller was fluent but writer outcomes lacked a
sufficiently strong schema-validation boundary. The graph moved too much
interaction and state into one abstraction. The current design restored the Skill
as driver and recovered official host validation, but left business control split
between Skill prose and one universal `run-stage` entry.

The official Workflow boundary remains valuable: every specialist can be called
with a closed StructuredOutput schema, and the host can repair malformed model
output before returning it to the caller.

The later `units` and `until` additions solved real UX problems. `units` changed a
30-chapter Book from about 30 top-level Workflow cards into one same-stage fan-out.
`until` changed a successful post-Search Paper from four mechanical Workflow calls
into one sequential chain. Those improvements should not be interpreted as
mistakes.

The maintainability problem is the abstraction that accumulated around them. One
public entry now supports every `kind`, every `stage`, and three execution modes:
single, batch, and chain. The Skill must understand the stage graph, special
carries, material-specific gates, Book chapter scheduling, Talk classification,
Audit repair ownership, and restart behavior. The generic entry must then recover
the same distinctions through registries, descriptor rows, context expansion,
and mode-specific validation. The apparent unification increases change
amplification and makes the front-end interaction noisy.

The target retains the two things that proved valuable:

1. official Workflow host validation for every specialist result; and
2. one logical material normally progressing within one Workflow run.

It removes the assumption that heterogeneous material processes should share one
public control-flow API.

## Goals

- Make Paper, Book, Talk, and Translation independently understandable and
  changeable.
- Keep `agent(..., {schema})` at every Agent-owned boundary.
- Make the normal UX one Workflow run per logical material, ending only at
  completion, a typed gate, or a genuine stop condition.
- Make the outer Skill a route/status/gate loop rather than a business
  controller.
- Keep disk observations and validated receipts as the only processing evidence;
  add no hidden workflow state file.
- Preserve exact artifact ownership, unknown-writer safety, canonical schema
  ownership, and deterministic CLI boundaries.
- Shift test effort from speculative state-machine combinations toward contracts,
  realistic integration paths, and Agent capability evaluation.

## Non-goals

- Replacing official Workflows with a custom external orchestrator.
- Minimizing generated bundle size.
- Adding general graph, retry, compensation, checkpoint, or nested-Workflow
  frameworks.
- Rewriting deterministic extraction, translation, download, or audit
  capabilities.
- Changing artifact schemas merely to simplify orchestration code.
- Implementing Topic or Author composition in the first delivery. Author's
  one-way dependency direction is designed here; its observation/resume seam
  follows after the four leaf plan APIs stabilize.
- Making `needs_input` rare. A necessary gate is an honest outcome, not a defect.
- Preventing the rare case where two differently worded concurrent requests later
  canonicalize to the same material. The Skill suppresses only duplicate known
  material keys. A hidden semantic collision is accepted as a maintainability
  trade-off and may require manual cleanup.

## Design principles

### Unify protocols, not business control flow

All material Workflows share receipt types, host stamping, schema builders,
operation dispatch, exact-ref validation, and material-level terminal handling.
They do not share a generic stage interpreter.

### One canonical material, one logical run

A normal invocation advances one canonical material as far as it can. A gate ends
the current run. After the user answers, the Skill performs a fresh disk
observation and starts a new run. No run waits for mid-run user input.

### Explicit plans over a graph DSL

Paper's straight line, Book's chapter fan-out and join, Talk's classification
branch, and Translation's derivative transaction should be visible as ordinary
TypeScript control flow. A local graph-shaped operation may use `pipeline()` when
it earns its complexity; the repository does not expose a universal graph model.

### Strong Agents, small orchestrator

Agents own professional method and bounded local recovery over their declared
capabilities. A high `blocked` or `failed` rate is first treated as an Agent,
request-envelope, or capability problem—not a request to add Workflow branches.

### No speculative defensive programming

Code handles the host's documented outcomes, reachable domain states, observed
regressions, and the few boundaries where a mistake can corrupt or duplicate user
artifacts. It does not add fallback paths for imagined failures, accept several
legacy spellings “just in case,” validate the same value independently at several
layers, catch errors only to relabel them, or retain compatibility branches after
their last caller is gone.

Every non-trivial guard, retry, fallback, or compatibility path needs one concrete
owner and one concrete justification: a host contract, a domain invariant, an
active caller, or a reproduced failure. Otherwise it is omitted. TypeScript types,
the official StructuredOutput boundary, and the deterministic capability's own
contract are preferred over caller-side revalidation.

## Target architecture

```text
skills/
  thin route + status + typed-gate interaction
        |
        +--> workflows/paper.mjs
        +--> workflows/book.mjs
        +--> workflows/talk.mjs
        +--> workflows/translation.mjs
                  generated public entries
                         |
scripts/workflows/plans/{paper,book,talk,translation}.mts
                  explicit business control flow
                         |
scripts/workflows/shared/dispatch.mts
scripts/workflows/operations/rows/*.mts
                  shared validated operation boundary
                         |
agents/ -> bin/quasi-* -> scripts/ -> scripts/core/
                         |
scripts/schemas/          canonical artifact contracts and status evidence
```

Exact directory names may be adjusted during implementation, but these ownership
boundaries are normative.

### Skill ownership

The material Skill owns only:

- interpreting the user's top-level intent and material kind;
- selecting the corresponding Workflow entry;
- obtaining a fresh `quasi-status` observation before a run and before reporting
  material completion;
- passing the observation, material identity, options, and an optional user
  decision into the Workflow;
- presenting `complete`, one typed gate, or a stop diagnosis; and
- repeating the observe/invoke loop after a gate.

It does not send `stage`, `until`, or `units`. It does not know stage order,
special receipt carries, chapter fan-out, Talk classification branches, Agent
types, or completion predicates.

For a user batch, the Skill starts one Workflow per logical material, limits the
number of in-flight Workflows, preserves input order, and aggregates their
top-level terminals. It never launches two concurrent Workflows for the same known
material key. There is no material-batch Workflow, public fan-out mode, or `units`
API.

### Public Workflow entries

Each generated public file contains metadata, normalizes its fixed-kind input,
adapts the host globals to the shared runtime interface, and calls one plan. It
contains no operation registry or generic mode selection.

Suggested public names are `paper`, `book`, `talk`, and `translation`, namespaced
by the plugin at runtime. No new aliases are added speculatively. The old generic
entry remains only while a named active consumer has not migrated.

### Material plan ownership

Each plan owns:

- its operation order;
- branches and joins;
- receipt-to-next-operation carries;
- the rule for choosing the next applicable operation from the initial status
  observation and receipts produced during the current run;
- its local fan-out ownership check; and
- its one owner-correct Audit repair, where applicable.

Plans call a single-unit `dispatchOperation()` primitive. Sequential composition
uses `await`; same-stage independent fan-out uses the official `pipeline()`
primitive. Book chapter analysis is the one current intra-material fan-out. It is
owned entirely by the Book plan and is invisible to the Skill. There are no public
single/batch/chain modes.

### Operation and schema ownership

Operation rows continue to own one specialist boundary: context normalization,
request envelope, output schema, exact refs, and the small cross-field completion
predicate that JSON Schema cannot express. Shared dispatch must apply the owning
completion predicate to every schema-valid `complete` receipt, regardless of
which material plan called it.

`scripts/schemas/` remains the single source of artifact structure. The existing
pipeline projection is narrowed into an operation/status-evidence catalog. It may
group operation identities and exact artifact templates by material, but it no
longer owns stage sequencing, chains, carries, or next-stage policy. Those belong
to the TypeScript plans. `quasi-status` reports facts by stable operation/evidence
name and does not act as a control-flow oracle.

The build checks that every plan-referenced operation exists in the generated
catalog and that every writer has an explicit exact or conservative potential
write-target projection. It does not generate a universal stage graph.

### Agent and capability ownership

Agents retain professional judgement, stopping judgement, and local recovery.
They receive one sufficient JSON request envelope rather than a duplicated prose
state machine. Deterministic CLIs retain their existing transactional and exact
output contracts. The refactor does not move download cascades, OCR choices,
chapter replanning, transcription method, or translation recovery into plans.

## Material plan behavior

### Paper

The Paper plan performs Search when canonical identity is not already admitted,
then advances through Acquire, Prepare, Analyse, and Audit. Search's validated
identity and local-owner result establish the canonical slug for the rest of that
run. Prepare's validated `selected_input` is passed directly to Analyse. A clean
Audit completes the material; an owner-correct escalation allows one Analyse
repair followed by one re-Audit.

When Search changes the slug, the plan does not create a second preflight run or a
second status Agent. It trusts the host-validated Search receipt for in-run
identity and lets each following writer observe its exact input and output at
entry. The final caller-side status check remains authoritative for durable
artifacts.

This preserves the successful UX of `until` without exposing `until` as a generic
mode.

### Book

The Book plan performs Search, Acquire, and Prepare. The validated Prepare receipt
already contains the complete, unique chapter list, so the plan can fan out one
Analyse dispatch per distinct chapter output without reading the filesystem.
After every chapter is coherent-complete, it runs Synthesise and Audit. Audit may
route one repair to the owning chapter or overview producer, then re-Audit once.

Before fan-out, the plan computes exact output ownership keys and rejects overlap.
Prompt inequality is never used as evidence that writers are independent.

The plan uses the Prepare receipt's chapter inventory within the current run. It
does not add a second model-independent manifest checkpoint merely to defend
against a schema-valid Agent omitting a row. The plan, not the chapter Agent,
binds the create/reconcile branch: an exact chapter output attested by the initial
status gets `output_exists:true`; a chapter first discovered during the run gets
`output_exists:false` and must produce `create/written`. If that Agent observes an
unexpected existing output, it returns `blocked` without writing; the next run's
fresh status can bind reconcile. This preserves the reproduced 0.58.2 correctness
fix without adding a second manifest observer. The final status check reads the
durable manifest and chapter artifacts. A rare omitted row therefore prevents
reported completion and is reconciled on a later run.

Book chapter `pipeline()` uses the host's bounded concurrency and preserves input
order. Each Agent receives the Book phase and a chapter-specific label so the one
Workflow card remains inspectable. The plan does not implement its own chunking,
worker pool, or concurrency scheduler.

### Talk

The Talk plan performs Prepare and branches on its validated classification.
`live` proceeds to Analyse; `dead` and `empty` use the canonical artifact already
owned by Prepare. The selected path then proceeds to Audit. One owner-correct
Analyse repair and re-Audit is allowed for a live Talk. A `dead` or `empty` Talk
routes an owner-correct repair back to Prepare, not Analyse.

### Translation

Translation is an independent derivative plan, even when the user reaches it from
a completed Paper. Its identity is the source material plus the normalized full
target-language tag. It invokes the existing Translation Prepare operation and
ends with the canonical derivative and manifest contract. It has no separate
Audit stage today.

Translation status uses the explicit interface
`quasi-status --kind translation --slug SLUG --target-language TAG --json`.
`TAG` is normalized by the same full-language-tag rule as Translation Prepare, and
the result echoes the normalized tag plus only that target's exact output and
manifest evidence. A different target's derivative never satisfies the request.

## Code-level composition for Author and Topic

Official Workflow entry files are not nested. Instead, the editable leaf plans
export code-level plan APIs behind a shared runtime interface:

```ts
runPaperPlan(runtime, input): Promise<MaterialResult>
runBookPlan(runtime, input): Promise<MaterialResult>
```

An Author plan may discover candidate works, resolve membership, invoke the
appropriate leaf plan APIs, and synthesize the Author artifact. This is the only
layer where Paper and Book are coupled. Paper and Book never import Author logic,
and Author owns references to canonical child materials rather than copies of
their processing state.

This document fixes that dependency direction, not the complete Author intake and
resume protocol. Dynamic children are discovered after an Author run starts, while
leaf plan inputs normally include caller observations. The Author follow-up design
must choose the smallest explicit observation seam and define how a child gate is
lifted with its `kind` and canonical `slug`. It must not add Author logic to the
leaf plans.

Topic may later compose the same leaf APIs, but its iterative recall, evidence
cards, and user-editable outline deserve a separate design review rather than
being forced into the first migration.

## Invocation and result contracts

The four public entries share a small transport envelope. The fixed entry decides
the material kind; the payload carries facts rather than routing instructions.

```ts
interface MaterialRunInput<TIdentity, TOptions, TDecision> {
  identity: TIdentity;
  observation: QuasiStatusObservation;
  userDecision?: TDecision;
  options: TOptions;
}
```

`TIdentity` is the bounded identity supplied or observed so far; it is not assumed
canonical before Search completes. Kind-specific identity facts, options, and
decisions remain typed at their owning entry—for example Talk media intake and
Translation target language. They are not hidden in a universal untyped context
bag.

Every plan returns a small, closed material-level union. The host constructs this
envelope from validated receipts; an Agent does not generate it.

```ts
interface MaterialResultBase {
  schema_version: "quasi.material.result/0.1";
  material: {
    requested: RequestedMaterialIdentity;
    canonical: CanonicalMaterialIdentity | null;
  };
  receipts: StageReceipt[];
}

type MaterialResult =
  | (MaterialResultBase & {
      terminal: "complete";
      issue: null;
      artifacts: ExactArtifactRef[];
      next: MaterialRoute | null;
    })
  | (MaterialResultBase & {
      terminal: "needs_input";
      issue: MaterialIssue;
      gate: TypedGate;
    })
  | (MaterialResultBase & {
      terminal: "blocked" | "failed";
      issue: MaterialIssue;
    });
```

The existing closed `quasi.stage.receipt/0.3` remains the Agent-facing result.
`complete` requires a canonical material identity; Search gates and early stops
may return `canonical:null`. The Skill consumes only the material-level identity,
terminal, issue, gate, and final artifacts; it does not interpret the stage
receipts.

`next` is normally `null`. It carries a typed next route only for an existing
cross-kind disposition such as a Paper request confirmed to be a Book. The Skill
follows the route generically; it does not learn the publication-type rule.

## Execution and resume data flow

```text
Skill
  -> quasi-status obtains current disk testimony
  -> invoke the fixed material Workflow
       -> validate input identity against observation
       -> plan chooses the next operation
       -> dispatch Agent with closed StructuredOutput schema
       -> host stamps bookkeeping and checks owning completion predicate
       -> coherent complete: carry validated evidence and continue
       -> gate or stop terminal: return immediately
       -> all required operations complete: return material complete
  -> on material complete, quasi-status verifies exact durable artifacts
  -> present completion or ask the gate question
  -> after an answer, re-observe disk and start a new run
```

Across runs, disk testimony is authoritative. Within one run, the plan advances
from the initial observation plus host-validated receipts. Every writer still
verifies its exact inputs and output state at entry. This allows a fluent
multi-operation run without inventing a filesystem-reading Workflow primitive or
a hidden cursor.

Search may establish a canonical slug different from the provisional observation.
The plan deliberately does not pause for another status call: subsequent Agents
observe and reconcile their exact refs, and the post-run status check verifies the
canonical durable outputs. This accepts the low-frequency concurrent canonical
collision discussed in Non-goals instead of adding a pre-writer admission graph.

A material-level `complete` is not reported to the user until the post-run
target-aware status observation contains the required exact artifacts for that
canonical material. A clean Audit remains receipt-proven for the current
invocation only; status proves artifacts, not Audit cleanliness. If the durable
evidence disagrees with the result, the Skill stops with the observation rather
than silently claiming success.

A user decision is scoped to the current material and gate operation. If fresh
status shows that the material has already advanced, the plan follows the facts
and does not apply a stale decision to a different operation.

The decision echoes only the gate's existing concrete evidence binding: for
example Book year evidence and temporary path, or Translation's candidate
fingerprint and selected exact path. The design does not add a second generic gate
token system.

## Error model

Workflow code advances known-good results; it does not perform speculative
recovery.

| terminal | meaning | caller action |
|---|---|---|
| `complete` | Exact completion evidence is coherent | Continue the plan or report success |
| `needs_input` | A concrete user semantic choice is required | Present one typed gate and end the run |
| `blocked` | It is unsafe to continue, including stale refs or an ambiguous writer outcome | Stop and re-observe disk |
| `failed` | A known execution failure has a concrete diagnosis | Report it; do not disguise it as a gate |

Only provider-level StructuredOutput repair and the specialist's bounded local
recovery are implicit. Plans contain no generic retry matrix or provider cascade.

If `agent()` returns `null`, rejects after dispatch, or exhausts the host's
StructuredOutput repair without a valid receipt, the host cannot prove that a
writer did not commit. The material result is `blocked` with an unknown-outcome
issue, and the plan does not replay that writer. Writer calls do not add a local
Promise-race timeout that could leave work running in the background. The next
attempt starts with `quasi-status`. A schema-valid specialist `failed` receipt
remains `failed`; the host does not reinterpret professional judgement.

If a writer returns schema-valid `complete` but its owning cross-field predicate
rejects it, the host retains the receipt for diagnosis and returns material-level
`blocked` with `incoherent_complete`. It does not rewrite the specialist terminal
to `failed` and does not replay the writer.

For fan-out, all already-dispatched units are allowed to settle. The next stage
starts only when every required unit is coherent-complete. Successful sibling
outputs are retained. Any unknown writer outcome makes the material-level result
`blocked`; it is never hidden behind a sibling gate. Otherwise the first
non-complete receipt in stable chapter order becomes the top-level gate or stop.
The validated receipt list remains available for diagnosis and the next
disk-based resume. Gate aggregation is deferred until real UX evidence justifies
it.

## Test design

The current suite has strong behavioral protection but too much maintenance
surface: 40 test modules, roughly 12,000 lines, and more than 500 collected cases.
Large modules, repeated harnesses, source-string assertions, private-helper
coupling, and prose snapshots obscure the highest-value contracts.

The target suite has four layers.

### 1. Shared contract tests

Test shared dispatch once for:

- all four receipt terminals;
- StructuredOutput boundary and host-stamped fields;
- the completion predicate on every `complete` receipt;
- exact-ref and write-target validation; and
- null, exception, or invalid final receipt producing an unknown-outcome stop.

One catalog-driven wiring test checks that every plan-referenced operation exists,
uses its own schema/refs/write-target projection, and supplies its owning
completion predicate to shared dispatch. It does not manufacture every theoretical
terminal combination for every row. Operation-specific predicate semantics remain
focused tests only where the row has real cross-field behavior.

### 2. Pure plan and component tests

Use a small fake Workflow runtime that returns explicit receipts. Test observable
operation sequences rather than internal helper calls or complete prompt strings.

Each leaf plan needs:

- one ordinary happy path;
- one gate followed by a fresh-observation resume;
- its material-specific branch: Paper carry and repair, Book chapter fan-out and
  join, Talk classification, or Translation target-aware reconcile; and
- one ambiguous writer stop proving that no later operation dispatches.

The Book plan additionally proves that duplicate exact outputs are rejected before
dispatch, distinct outputs preserve receipt order, and status-bound
`output_exists` permits exactly reconcile or create as appropriate. One mixed
chapter case covers out-of-order completion with successful siblings plus one gate
or unknown outcome: all launched chapters settle, validated successes remain, an
unknown dominates a gate, and Synthesise/Audit do not start.

The Skill and generated-entry component tests remain small: fixed-kind routing,
one pre-run and post-complete status observation, gate resume with a fresh
observation, batch concurrency limit and result order, and zero dispatch for a
malformed required material input. They do not snapshot Skill prose.

Translation status tests cover the owning interface directly: full-tag
normalization, exact output/manifest evidence for the requested target, and a
different target remaining incomplete. `--kind translation` requires
`--target-language`; this is a domain input, not a fallback guessing opportunity.

### 3. Agent capability evaluations

Maintain a small representative corpus for Paper, Book, Talk, and Translation.
These runs assess artifact quality, correct capability use, gate precision, and
the observed `blocked`/`failed` rate. They are a tuning suite, not a deterministic
per-commit unit suite or a merge gate. The first implementation uses documented
manual/headless scenarios rather than building a general evaluation framework;
automation is added only if repeated use justifies it.

When an evaluation does not complete, diagnose in this order:

1. Was the request envelope sufficient?
2. Was a capability missing or difficult to use?
3. Does the Agent role or method need improvement?
4. Only then, is a new Workflow branch genuinely required?

Do not optimize for fewer `needs_input` receipts. Optimize for justified gates and
high-quality completion.

### 4. Slow acceptance and regression tests

Keep a few synthetic flows through public shims and generated Workflows, plus the
existing cross-process and PDF acceptance tests. Live providers remain scheduled
or manual. A real production incident earns a focused regression test;
speculative orchestration combinations do not. Existing safety partitions—path
and symlink rejection, output collisions, transactional fencing, post-replace
faults, and non-idempotent network operations—remain covered because their failure
cost is concrete.

### Existing test cleanup

Preserve the existing tests for transactional fencing and recovery, PDF layout and
translation coverage, identity/path security, schema closure, Crossref venue
authority, and secret/environment boundaries.

During the refactor:

- replace `test_run_stage.py` mode-matrix coverage with shared-dispatch and
  material-plan behavior tests;
- delete homemade `main()` runners in nested search tests after confirming pytest
  collection;
- consolidate duplicate Douban and dead-name coverage;
- remove wrapper tests that only invoke production `demo()` self-assertions;
- replace exact prose and source-string assertions with semantic, AST-backed, or
  runtime checks; in particular, preserve the DS OCR2
  `trust_remote_code=True` prohibition with a behavioral or AST-backed test;
- centralize fixtures and provider seams, then parameterize repeated download and
  extraction cases; splitting large files is only an organizational consequence;
- add root pytest configuration, clean-environment and no-network fixtures, and
  explicit slow/integration markers without dropping `scripts/core/tests` or
  `scripts/search/tests` from collection;
- add a small public-`bin` smoke matrix so shell bootstrap and environment routing
  are not bypassed completely; and
- either wire the three synthetic fixture generators into the slow acceptance
  lane or remove them after confirming they have no documented manual use.

Deleting a private-helper test is allowed only after equivalent public behavior is
covered. Test-line reduction is a consequence, not the acceptance criterion.

Before deleting cases from `test_run_stage.py`, maintain a short migration map from
each load-bearing invariant—row/schema pairing, terminal closure, host stamping,
incoherent complete, null receipt, chapter ordering, and duplicate writer
ownership—to its new shared-dispatch or material-plan test. Tests whose only
subject is the retired public mode syntax may be marked obsolete and removed.

## Current correctness findings carried into the migration

The read-only architecture audit found three issues that the new boundary must not
preserve:

1. The owning `complete()` predicate currently runs only in chain mode. Single and
   batch paths can accept schema-valid but cross-field-incoherent `complete`
   receipts.
2. Batch duplicate-writer detection currently compares prompts. Different prompts
   can target the same chapter output.
3. Malformed input can fail open: empty/non-array `units`, missing slug, and missing
   artifact placeholders can dispatch with unintended single mode or `undefined`
   paths.

The shared `dispatchOperation()` migration seam fixes the first issue for all call
sites. Explicit potential write targets fix the second. Typed material inputs and
strict placeholder expansion fix the third. These are correctness requirements,
not reasons to retain the generic mode engine.

During an incremental cutover, the old `run-stage` entry may temporarily call the
same hardened dispatch primitive for unported Author/Topic operations. No new
features are added to its public `stage`/`until`/`units` API.

## Migration sequence

1. Introduce the shared runtime, material result envelope, single-unit validated
   dispatch, strict context expansion, and explicit writer ownership projection.
   Use the dispatch primitive from the compatibility entry while migration is in
   progress.
2. Add the generated-entry build pattern and target-aware Translation status while
   leaving the existing chain/carry projection intact for active callers.
3. Implement and verify the Paper plan and generated public entry, then switch its
   Skill route without removing the compatibility Paper chain yet.
4. Implement Book, including receipt-driven chapter `pipeline()` and exact ownership
   checks.
5. Implement Talk and Translation.
6. Cut the material Skill over to route/status/gate behavior and remove its
   stage-specific prose for the four leaf kinds. This is the leaf-cutover
   milestone.
7. Export stable leaf plan APIs and give Author's observation/resume seam its
   focused follow-up design. Give Topic a separate design review. The compatibility
   entry remains while either is an active consumer.
8. After Author and Topic have explicit replacement entries, remove the public
   generic `run-stage`, its chain/carry and mode registry, mode-only tests, and dead
   documentation. Narrow the schema projection to operation identity and status
   evidence at this retirement milestone.
9. Perform the broader test cleanup in behavior-preserving slices, running the
   relevant focused suite after each slice.

Generated artifacts are rebuilt rather than hand-edited. Active docs, Agent
contracts, and mirrored `CLAUDE.md`/`AGENTS.md` are updated at the cutover points
where their runtime statements become true.

## Leaf-cutover acceptance criteria

- Paper, Book, Talk, and Translation each have one generated official Workflow
  entry backed by one readable TypeScript material plan.
- A normal one-material happy path uses one top-level Workflow run.
- A gate ends the run; resume begins with a fresh `quasi-status` observation and a
  new run.
- Every material-level `complete` receives a post-run target-aware status check
  before the Skill reports success; current-run Audit cleanliness remains
  receipt-proven.
- The material Skill passes no public `stage`, `until`, or `units` values and does
  not encode the four plans' stage order or branches.
- Every specialist call retains closed host StructuredOutput validation and applies
  its owning completion predicate.
- Book chapter `pipeline()` proves distinct exact outputs before dispatch, retains
  stable result order and phase/labels, and relies on the host's bounded
  concurrency rather than a second scheduler.
- Unknown writer outcomes never auto-replay.
- Translation resume is based on an exact target-aware status observation.
- Required runtime fields such as slug, observation identity, target language, and
  exact path placeholders reject before Agent dispatch when absent or malformed.
- Existing CLI JSON shapes, artifact paths and schemas, transactional fencing,
  identity/path/symlink protections, PDF-pipeline invariants, and secret-out-of-argv
  boundaries remain covered.
- A test-migration map accounts for every load-bearing `test_run_stage.py`
  invariant before mode-only cases are deleted.
- Every guard, fallback, retry, or compatibility branch added or modified in the
  workflow/orchestration refactor has a documented host contract, domain
  invariant, active caller, or reproduced regression.
- `npm run check:workflows` proves catalog/projection/declaration/bundle parity and
  strict TypeScript checking. Every generated entry remains below the existing
  512 KiB loader gate.

## Full-retirement acceptance criteria

- Paper and Book contain no Author-specific logic; an approved Author entry
  composes their source plan APIs in one direction.
- Topic has an approved replacement entry rather than being forced into a leaf
  material plan.
- No active Skill calls `run-stage`; only then are the compatibility entry,
  universal mode registry, chain/carry projection, and mode-only tests deleted.

## Trade-offs

- Four generated bundles may be larger than one generic bundle. They are generated
  deployment artifacts; the source remains shared and easier to reason about.
- Explicit material plans duplicate a small amount of orchestration shape. This is
  intentional because the shapes have different business meanings.
- Restart after a gate creates a new run instead of a suspended interactive graph.
  This matches the host constraint and keeps disk state authoritative.
- Two differently worded concurrent requests may rarely canonicalize to the same
  material after launch. The design accepts manual reconciliation rather than
  adding a preflight graph, semantic lock service, or second top-level run.
- Agent evaluations cost more and are less deterministic than unit tests. They run
  separately because they measure the capability that determines real workflow
  fluency.
- Some current generic abstractions remain temporarily during migration. The
  compatibility period is bounded by the deletion criterion above.

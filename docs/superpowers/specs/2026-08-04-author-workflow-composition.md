# Author Workflow Composition Contract

**Status:** focused design for Task 11A

**Scope:** one named Author Workflow, its automatic disk-observation handshake,
and its one-way composition of the existing Paper and Book plans

## Purpose

One Author invocation owns one logical author. It discovers representative Books
and Papers, resolves one stable membership, obtains exact child disk testimony
through the caller, runs the existing leaf plans sequentially, and writes and
audits one Author page.

Author is the only layer that couples Paper and Book. It follows the public
Paper-to-Book disposition but does not copy leaf stage logic, inspect Stage
receipts, or make either leaf depend on Author.

The design has two explicit host passes:

1. discover and freeze a bounded membership;
2. consume exact statuses for that membership and compose its leaf plans.

The boundary is automatic and user-invisible. It exists because a Workflow
cannot read the filesystem, while `quasi-status` output must reach the plan as
direct host testimony rather than be relayed through a model. In particular, a
Book observation may contain a large chapter inventory; it is Workflow input,
never Agent-generated StructuredOutput.

There is no Workflow cursor, completed-prefix list, receipt store, hidden state
file, lock, retry loop, cleanup pass, or whole-vault scan.

## Public input

The generated `workflows/author.mjs` entry accepts one of two closed envelopes.
Presence of `resume_seed` selects composition; there is no public `phase`,
`stage`, `until`, or mode field.

```ts
interface AuthorSeed {
  slug: string;
  full_name: string;
  topic: string;
}

interface AuthorOptions {
  maxBooks?: number;
  maxPapers?: number;
}

interface AuthorDiscoverEnvelope {
  seed: AuthorSeed;
  observation: AuthorStatusObservation;
  options: AuthorOptions;
}

interface AuthorComposeEnvelope {
  observation: AuthorStatusObservation;
  resume_seed: AuthorResumeSeed;
  child_observations: ChildObservationInput[];
  userDecision?: UserDecision;
}
```

The initial `seed` and `resume_seed.seed` use the same parser. Their slug matches
`^[a-z0-9][a-z0-9-]{0,79}$`; `full_name` and `topic` are trimmed non-empty
strings. `maxBooks` and `maxPapers` are optional positive downward caps whose
defaults and maxima remain 5 Books and 10 Papers. Unknown keys or out-of-range
values return `material.invalid_input` before any Agent call.

### Exact Author observation

The Skill obtains the Author observation directly:

```bash
quasi-status --kind author --slug <current Author seed.slug> --json
```

The parser accepts only `quasi.status/0.2`, `kind:"author"`, the requested
slug, and canonical path `vault/authors/{slug}.md`; `usable` implies `present`.
A usable canonical is admitted only when `identity.name === seed.full_name`.
A usable page with another name is an owner conflict and stops before discovery.
A present but unusable page is repairable.

This observation is the sole Author disk fact. Author synthesis uses
`observation.facts.canonical.present` to choose `create|repair`. It never uses
`author.resolve-membership.output_exists`; that compatibility field may remain
until Task 13 removes it, but the named plan does not consume it.

### Membership and continuation types

```ts
type ChildRoute =
  | { kind: "paper"; slug: string }
  | { kind: "book"; slug: string };

type AuthorLeafContinuation = Extract<
  LeafResumeSeed,
  { route: ChildRoute }
>;

interface AuthorMemberSeed {
  member_route: ChildRoute;
  leaf: AuthorLeafContinuation;
}

interface AuthorResumeSeed {
  kind: "author";
  seed: AuthorSeed;
  options: AuthorOptions;
  members: AuthorMemberSeed[];
  decision_member: ChildRoute | null;
}

interface ChildObservationInput {
  route: ChildRoute;
  observation: PaperStatusObservation | BookStatusObservation;
}
```

Every object is closed. Discovery creates canonical member seeds from full
validated identities. Initially `leaf.route === member_route`; after composition,
`leaf` is that stable position's current effective `{route,seed,options}`.
`seed.material_slug === leaf.route.slug`; the owning Paper or Book parser validates
identity and options. A member has no duplicated title field; its label is always
`leaf.seed.identity.title` from the current canonical leaf identity.

`AuthorResumeSeed` is caller-owned closed re-execution testimony. Its stable
membership and order never change; only each member's current leaf call and the
nullable `decision_member` may change. It carries the original Author seed/options
but contains no operation, stage, receipt, completed-prefix, numeric index, or next
instruction. Member routes are unique and preserve resolver order.

`decision_member` names only the stable member receiving the next `UserDecision`
once. A gate sets it; ordinary composition and Paper-to-Book observation keep it
null.

`child_observations` is a closed array representation of the exact route map. The
Author parser delegates values to the owning leaf status parser, binds kind/slug,
and rejects duplicates or foreign kinds. Its keys must equal the stable, unique
projection of current `members[].leaf.route`; missing and unrequested rows are
invalid, and absence is never represented as disk testimony.

`userDecision` is present iff `decision_member` is non-null, and its
`material_key` matches that member's current leaf route. Author forwards
`operation` and `value` unchanged without interpreting gate-specific evidence.

## Pass 1: discover and freeze membership

An input without `resume_seed` performs exactly:

1. `author.discover-books`, with `count = options.maxBooks ?? 5`;
2. `author.discover-papers`, with `count = options.maxPapers ?? 10`;
3. `author.resolve-membership`, once over all Book candidates followed by all
   Paper candidates.

These calls use ordinary sequential `await`. Author itself never calls
`pipeline()`; only a nested Book may use the host pipeline for disjoint chapters.
The resolver remains the sole dynamic membership observer. It runs only its exact
vault-resolution helper; it never runs `quasi-status` or asks an Agent to relay
status JSON.

The host validates that resolved rows preserve candidate count and order:

- an existing row has the exact canonical Paper or Book overview path and uses
  `vault_slug` as its route slug;
- a missing row has null path/match and uses `requested_slug` as its route slug.

Pair each resolved row with its discovery candidate by index. Strip the candidate's
transport-only `kind` before calling `parsePaperIdentity` or `parseBookIdentity`;
the owning closed identity parsers must not receive that extra field. Coalesce
exact `kind:slug` route duplicates, keeping the first position. Do not coalesce
Books with Papers or use title heuristics. For every remaining row, construct a
canonical leaf continuation with the resolved route slug, parsed full identity,
and options `{}`.

If no member remains, stop with `author.no_representative_works`; do not synthesize
an evidence-free Author page. Otherwise return one automatic observation control
result containing all unique membership routes in stable order and an
`AuthorResumeSeed` with `decision_member:null`.

Any non-coherent or non-complete discovery/resolver outcome stops immediately.
It does not become an observation request.

## Automatic `needs_observation` control branch

`needs_observation` is a host-control terminal of `quasi.material.result/0.1`,
not an Agent receipt terminal and not a human gate. Stage receipts retain their
closed `complete|needs_input|blocked|failed` union unchanged.

The shared MaterialResult adds one small higher-order branch usable by Author and
Topic. Task 11 implements only its `kind:"author"` resume-seed arm; Task 12 adds
the Topic arm.

```ts
type HigherOrderObservationResumeSeed =
  AuthorResumeSeed; // Task 12 widens this to AuthorResumeSeed | TopicResumeSeed

interface NeedsObservationMaterialResult {
  schema_version: "quasi.material.result/0.1";
  material: MaterialResultBase["material"];
  terminal: "needs_observation";
  issue: null;
  routes: ObservationRoute[];
  resume_seed: HigherOrderObservationResumeSeed;
}
```

The branch is closed. `routes` is the non-empty, stable, unique projection of
`resume_seed.members[].leaf.route`. It carries no `gate`, artifacts, pending work,
receipts, or decision.

The Skill fulfills this result without asking the user: run every returned exact
status command concurrently, preserve the returned route binding, and reinvoke
the same Author entry with the unchanged resume seed and observation map.

## Pass 2: compose exact leaf observations

An input with `resume_seed` never reruns discovery or membership resolution. The
closed membership seed freezes the logical Author run and avoids nondeterministic
candidate drift between the two host passes.

Process members sequentially through each member's current `leaf.route`, `.seed`,
and `.options`, using the matching exact observation. Only the member equal to
`decision_member` receives `userDecision`; every other leaf receives null. Clear
`decision_member` after that one delivery.

### Internal leaf composition outcome

The direct named Paper and Book entries keep their existing public
`MaterialResult` unchanged. Their TypeScript composition API additionally exposes
the effective continuation held in local plan state:

```ts
interface LeafCompositionOutcome {
  result: MaterialResult;
  continuation: AuthorLeafContinuation;
}

runPaperPlanForComposition(runtime, input): Promise<LeafCompositionOutcome>;
runBookPlanForComposition(runtime, input): Promise<LeafCompositionOutcome>;
```

The existing `runPaperPlan` and `runBookPlan` return only `outcome.result`, so
generated leaf bundles and complete results do not grow a resume field. For every
coherent Author-owned canonical call, `continuation` contains the final runtime
owner route, full canonical seed, and effective options. On `needs_input`, it
equals the public leaf `result.resume_seed`.

After every coherent Paper or Book call, Author replaces that member's `leaf`
with `outcome.continuation` before interpreting the result. This is the only fact
needed to re-execute the same logical child after a later member stops. It is not
a completed marker or Stage cursor.

The first non-complete child stops Author. No later child, Author synthesis, repair,
or Audit call starts.

- `complete` with `next:null`: validate and admit the owner-correct leaf result;
- `complete` with typed `next`: follow the generic Paper-to-Book rule below;
- `needs_input`: lift the unchanged leaf gate and effective continuation;
- `blocked|failed`: preserve the child issue and stop;
- an unknown or incoherent writer outcome remains blocked and is never replayed
  automatically.

There is no automatic observation recovery after `blocked|failed`. A later manual
run begins as a new Author invocation with a fresh Author status.

## Child gates and fresh restart

The inner leaf gate is unchanged:

```ts
interface AuthorChildGate {
  kind: "child";
  route: ChildRoute;
  gate: LeafGate;
}

interface AuthorNeedsInputResult {
  schema_version: "quasi.material.result/0.1";
  material: MaterialResultBase["material"];
  terminal: "needs_input";
  issue: MaterialIssue;
  gate: AuthorChildGate;
  routes: ChildRoute[];
  resume_seed: AuthorResumeSeed;
}
```

For a coherent leaf `needs_input`, wrap the leaf result as follows:

- replace the current member's `leaf` with the leaf-owned effective
  `{route,seed,options}`;
- set `decision_member` to that member's stable `member_route`;
- carry the entire updated member array in `resume_seed`;
- `gate.route` equals the updated member leaf route;
- the inner gate is copied byte-for-byte;
- `routes` is the same non-empty, stable, unique set used by the automatic
  branch: the projection of all current member leaf routes.

The Skill presents only the inner human question. After the answer it reruns fresh
exact status for the returned routes, upserts those observations, copies the
returned resume seed, and adds the one closed `UserDecision`. The Skill treats the
resume seed as opaque. This deliberately refreshes the replayed prefix without
introducing a completed-prefix cursor.

A route, material-key, or continuation mismatch is `material.invalid_input`
before dispatch. A malformed leaf gate/result binding is
`workflow.incoherent_gate` and has no continuation.

## Generic Paper-to-Book routing

After a Paper completion, inspect only its public disposition:

```ts
if (paperResult.next?.kind === "book") {
  // continue with paperResult.next.identity
}
```

Author does not inspect publication-type evidence or reconstruct that judgement.
Replace that member's current leaf with a canonical Book continuation built from
the returned full identity, route `next.identity.slug`, and options `{}`; retain
the original Paper `member_route` and keep `decision_member:null`. The Book now
occupies that stable position.

If the Book route is already in the exact observation map, call `runBookPlan`
immediately. Otherwise return `needs_observation` from the updated member-leaf
projection. On restart, Author calls Book directly at the original Paper position;
the Paper gate is not replayed.

## Canonical coalescing and Author output

For every leaf completion with `next:null`, require a non-null canonical route and
the exact representative artifact:

- Paper: sole `role:"canonical"` at `vault/papers/{slug}.md`;
- Book: sole `role:"overview"` at `vault/books/{slug}/00-overview.md`.

Key completed children by `${kind}:${canonical.slug}` and keep the first occurrence.
This second coalescing handles distinct membership routes which later resolve to
one owner. It adds no reservation, rollback, or collision cleanup.

Synthesis inputs preserve first-admitted order and contain only material key,
kind, canonical owner slug, representative path, and the current canonical
`member.leaf.seed.identity.title`. Chapter artifacts remain Book-owned.

After all children complete:

1. dispatch `author.synthesise` once to `vault/authors/{seed.slug}.md`, using
   `repair` iff the caller's exact Author pre-status says the path is present;
2. dispatch `author.audit` pass 1 on that exact path;
3. if violations remain, run exactly one synthesis repair with those diagnostics
   and one Audit pass 2.

The Author Audit row sets `exactPaths:true`, so its validated diagnostics and
mutated paths can name only the exact Author target. The plan has no foreign-path
guard or owner-ambiguity branch. Remaining pass-2 violations stop as
`workflow.repair_exhausted`. Unknown synthesis, repair, or Audit outcomes stop;
status existence never proves a clean Audit.

## Closed Author results

Author uses `quasi.material.result/0.1` and returns no Stage receipts. Legal
terminals are:

- `needs_observation`: automatic branch above, `issue:null`, routes, resume seed;
- `needs_input`: child gate, child issue, exact refresh routes, and full Author
  resume seed;
- `complete`: `issue:null`, exact Author canonical artifact, `next:null`;
- `blocked|failed`: one typed issue and no continuation.

After valid parsing, requested and canonical material routes are the current
Author slug. Invalid input may retain an extractable requested slug but has
`canonical:null`. Author never returns `incomplete`, non-null `next`, pending work,
membership rows outside its closed resume seed, or partial success.

## Skill protocol

`collect-material` remains a thin host driver:

1. normalize Author intake and run exact Author pre-status;
2. invoke `workflows/author.mjs` without a resume seed;
3. on `needs_observation`, concurrently run exactly the returned Paper/Book status
   routes and reinvoke with the copied resume seed;
4. on a child gate, ask the user, refresh exactly its returned routes, add only
   the typed answer, and reinvoke;
5. on `blocked|failed`, report the issue and stop;
6. on complete, run exact Author post-status and report success only when the
   canonical path is present, usable, and projects `name === seed.full_name`.

The Skill never sees discovery candidates, interprets membership, selects a leaf
stage, consumes a Stage receipt, scans the vault, or maintains progress state.

## Implementation boundary

Task 11B creates:

- `scripts/workflows/contracts/author.mts` for both closed envelopes, Author
  status, membership/resume, and exact observation-map parsing;
- `scripts/workflows/operations/catalogs/author.mts` for only `author.*` rows;
- `scripts/workflows/plans/author.mts` for the two passes and leaf composition;
- `scripts/workflows/author.entry.mts` and generated `workflows/author.mjs`.

It minimally modifies:

- `scripts/workflows/shared/material-result.mts` to add the discriminated
  higher-order `needs_observation` branch and Author child continuation;
- `scripts/workflows/plans/{paper,book}.mts` to expose the narrow internal
  composition outcome while preserving the existing public plan result;
- `scripts/workflows/contracts/paper.mts` to bind Paper status paths exactly to
  `sources/{slug}.pdf`, the producer-ordered `processing/papers/{slug}/source.txt`
  and `processing/papers/{slug}/ocr.txt`, and `vault/papers/{slug}.md`;
- `scripts/workflows/operations/rows/author.mts` to make the Author Audit receipt
  path exact with `exactPaths:true`;
- `scripts/build-workflows.mjs` to build Author;
- `skills/collect-material/SKILL.md` for automatic route fulfillment and gates.

The Paper/Book entry modules continue calling `runPaperPlan` / `runBookPlan` and
therefore expose the same named-leaf ABI. Only Author imports the composition
variants. The Paper path change receives one producer-parity test, not a matrix of
malformed path permutations.

The Author bundle may import Paper/Book plans and their local catalogs. It must
not import the universal catalog, `run-stage`, Topic, Talk, Translation, or a
generic plan engine. Paper and Book remain dependency leaves.

Focused tests cover only behavior-bearing seams:

1. exact Author parsing and zero-dispatch malformed input;
2. discovery/resolver order and a non-empty, stable, deduplicated membership seed;
3. automatic batch routes fulfilled by exact Paper/Book statuses, with no model
   status relay and no second discovery pass;
4. stable sequential Paper/Book calls and canonical-owner coalescing;
5. unchanged child gate plus complete `{member_route,route,seed,options}`;
6. gate restart refreshing all current member-leaf routes and delivering one
   decision only;
7. Paper-to-Book missing-route observation handshake and direct Book restart;
8. P1 routing to B1 with a changed identity title, followed by a P2 gate, then
   restart calling B1 directly and final synthesis using B1's current leaf identity
   title while delivering the P2 decision exactly once;
9. unknown child outcome stopping every later child and Author writer;
10. synthesis, clean Audit, one owner-correct repair/re-Audit, and exhaustion;
11. generated host ABI, exact local bundle dependencies, and zero Author-owned
    `pipeline()` calls.

Do not add field-permutation matrices, mocked vault scans, retry counters, lock
tests, cursor snapshots, or duplicate-dispatch cases already excluded by exact
route and canonical-owner coalescing.

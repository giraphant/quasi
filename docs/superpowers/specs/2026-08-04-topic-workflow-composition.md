# Topic Workflow Composition Contract

**Status:** Implemented by Task 12B on 2026-08-04.

**Goal:** Replace the Topic Skill's public Stage loop with one fixed Topic
Workflow that composes the existing leaf plans and Topic-owned operations while
keeping the user-editable outline as the only durable research state.

## Decision and scope

`workflows/topic.mjs` is a higher-order Workflow, not a generic scheduler. One
invocation owns one Topic and may do only this bounded composition:

1. validate one exact Topic observation and sparse exact child observations;
2. run one readonly `topic.recall`;
3. create or reconcile the exact Topic outline through `topic.steer`;
4. process at most `maxRounds` stable, sequential research queues;
5. checkpoint every newly admitted exact member/card ref before another risky
   writer starts;
6. audit the final outline, synthesize overview and resources, then audit those
   two products; and
7. allow at most one owner-correct repair and one re-Audit per exact product.

Paper, Book, and Talk remain leaf plans. Topic calls their public TypeScript APIs
and consumes their public material results; it does not copy their stage logic
or inspect Stage receipts. Only Book may use `pipeline()` internally. All Topic
children and cards use ordinary `await` in stable order.

The outline at `vault/topics/{slug}/02-outline.md` is the only durable research
state. There is no Workflow cursor, receipt log, seen-set sidecar, whole-vault
inventory, lock, reservation, retry matrix, collision cleanup, or generic graph
engine. A returned continuation is one caller-owned work value, not persisted
state. Unknown writer outcomes stop immediately.

## Implementation surface and ownership

Task 12B is expected to touch these ownership boundaries:

- `scripts/schemas/topic.py`, `scripts/schemas/export_contracts.py`, and
  `scripts/status/status.py` own artifact structure, generated projections, and
  exact disk testimony respectively;
- `agents/steer-agent.md` owns specialist method and steer-signal meaning;
- `scripts/workflows/contracts/topic.mts` and
  `scripts/workflows/shared/material-result.mts` own public Topic types and the
  shared higher-order result seam;
- `scripts/workflows/shared/material-input.mts` adds Topic to
  `ObservationRoute`, `ObservationKey`, and its route parser only for checkpoint
  exact-status control;
- `scripts/workflows/contracts/{paper,book,talk}.mts` export and Topic reuses
  `parsePaperSeed`, `parseBookSeed`, `parseTalkSeed`, and `parseTalkOptions`;
- `scripts/workflows/operations/rows/topic.mts` owns operation envelopes and
  their small cross-field completion predicates;
- `scripts/workflows/operations/catalogs/topic.mts`,
  `scripts/workflows/plans/topic.mts`, and
  `scripts/workflows/topic.entry.mts` own the named Workflow; and
- `skills/research-topic/SKILL.md` owns only outer transport and user dialogue.

`scripts/workflows/operations/rows/topic.mts` must stop locally redefining the
outline's subquestion, item, and card shapes. Producer and status projections are
generated from `scripts/schemas/topic.py`; the row imports those projections and
adds only operation-owned demand/task schemas, request-bound constants, and the
cross-field rules listed below. If the desired identifier, length, count, role,
or `theory_used` constraints differ from the current Pydantic model, change the
Pydantic model first and rebuild. Do not maintain a stricter private
`SUBQUESTION_SCHEMA` beside a looser durable schema.

Those exports retain leaf semantics; Topic never copies or weakens their input
contracts. Generated bundles/contracts are rebuilt, never hand-edited.

## Public input

The generated entry accepts one closed object. It has no `context`, `stage`,
`until`, `units`, inventory, or arbitrary option bag.

```ts
interface TopicQuery {
  slug: string;
  description: string;
}

interface TopicOptions {
  maxRounds: number;        // integer 0..8; Skill default 3
  maxCardsPerRound: number; // integer 0..6; Skill default 3
}

type TopicSeedMaterial =
  | { kind: "paper"; seed: PaperSeed; options: {} }
  | { kind: "book"; seed: BookSeed; options: {} }
  | { kind: "talk"; seed: TalkSeed; options: TalkOptions };

type TopicChildRoute = {kind: "paper" | "book" | "talk"; slug: string};

interface TopicChildObservation {
  route: TopicChildRoute;
  observation:
    | PaperStatusObservation
    | BookStatusObservation
    | TalkStatusObservation;
}

interface TopicRunInput {
  query: TopicQuery;
  observation: TopicStatusObservation;
  options: TopicOptions;
  seed_materials: TopicSeedMaterial[];
  child_observations: TopicChildObservation[];
  resume?: TopicResumeInput;
}
```

Paper and Book seeds are the existing closed leaf unions. Talk remains
canonical-only and includes its exact title, ISO date, and
`sources/{slug}.{supported-extension}` media identity. Topic never invents a
Talk identity from Recall.

The parser binds before any Agent call:

- `query.slug`, Topic observation slug, and every exact Topic artifact owner;
- each child route to its owning status parser and observation slug;
- duplicate child observation route keys as invalid;
- every seed to its owning leaf parser; and
- an optional continuation to the same query, exact child route, and matching
  sparse observation required by that continuation.

The shared observation union/key/parser adds the Topic route key
`topic:${string}` solely so
`needs_observation.routes` can request fresh Topic status after an ambiguous
checkpoint. `child_observations` remains leaf-only and rejects Topic rows.

Malformed input returns `material.invalid_input` with zero Agent calls. Topic
does not normalize a query into a slug, repair observations, or search for an
alternative path.

A minimal invocation is:

```json
{
  "query": {"slug": "platform-governance", "description": "How do platforms govern academic visibility?"},
  "observation": {"schema_version": "quasi.status/0.2", "kind": "topic", "slug": "platform-governance", "identity": null, "facts": {
    "kind": "topic",
    "outline": {"path": "vault/topics/platform-governance/02-outline.md", "present": false, "usable": false, "valid": false, "projection": null},
    "overview": {"path": "vault/topics/platform-governance/00-overview.md", "present": false, "usable": false},
    "resources": {"path": "vault/topics/platform-governance/01-resources.md", "present": false, "usable": false}
  }},
  "options": {"maxRounds": 3, "maxCardsPerRound": 3},
  "seed_materials": [],
  "child_observations": []
}
```

## Exact Topic observation

`TopicStatusObservation` remains `quasi.status/0.2`. Its three top-level paths
are exactly:

```text
vault/topics/{topicSlug}/02-outline.md
vault/topics/{topicSlug}/00-overview.md
vault/topics/{topicSlug}/01-resources.md
```

`outline.valid === (outline.projection !== null)`. A valid projection has the
schema-owned subquestions plus flattened member and card observations:

```ts
interface TopicOutlineProjection {
  subquestions: TopicSubquestionProjection[];
  members: Array<{
    kind: "paper" | "book" | "talk";
    slug: string;
    subq: string;
    role: TopicMemberRole | null;
    artifact: ArtifactObservation;
  }>;
  cards: Array<{
    slug: string;
    subq: string;
    title: string | null;
    artifact: ArtifactObservation;
  }>;
}

type TopicMemberRole = "evidence" | "theory" | "method" | "context";
```

The producer and TypeScript parser bind every nested row, not merely its path
shape:

- Paper member: `vault/papers/{slug}.md`;
- Book member: `vault/books/{slug}/00-overview.md`;
- Talk member: `vault/talks/{slug}/talk.md`;
- card: `vault/topics/{topicSlug}/cards/{slug}.md`; and
- every member/card `subq` occurs in the same projection's subquestion-id set.

`usable => present` for every artifact. Repeating one canonical artifact under
multiple subquestions is legal, so the projection must not impose global path
uniqueness. The schema authority also guarantees unique subquestion ids within
one outline. An invalid but present outline is not converted to an empty valid
projection: `topic.steer` refresh rereads that exact user-editable file.

## Closed continuation ABI

Dynamic Recall and steer work exist only in receipts; a restart cannot assume a
new model call reproduces the same row. Every dynamic exact-status request and
lifted child gate therefore carries one closed continuation capsule.

```ts
interface TopicCandidateDemand {
  kind: "paper" | "book";
  requested_slug: string;
  query: string;
  subq: string;
  role: TopicMemberRole;
  reason: string;
}

interface TopicAssignment {
  subq: string;
  role: TopicMemberRole;
}

type PaperOrBookLeafResume = Extract<
  LeafResumeSeed,
  { route: { kind: "paper" | "book" } }
>;

type TopicSeedLeaf =
  | PaperOrBookLeafResume
  | {
      route: { kind: "talk"; slug: string };
      seed: TalkSeed;
      options: TalkOptions;
    };

interface TopicSeedChildContinuation {
  kind: "seed_child";
  topic: TopicQuery;
  fingerprint: string;
  member_route: TopicChildRoute;
  leaf: TopicSeedLeaf;
}

interface TopicWorkContinuation {
  kind: "material_work";
  topic: TopicQuery;
  demand: TopicCandidateDemand;
  assignment: TopicAssignment;
  fingerprint: string;
  member_route: TopicChildRoute;
  leaf: PaperOrBookLeafResume;
}

interface TopicRecallContinuation {
  kind: "recalled_member";
  topic: TopicQuery;
  item: {
    kind: "paper" | "book" | "talk";
    slug: string;
    path: string | null;
  };
  fingerprint: string;
  route: TopicChildRoute;
}

type TopicCheckpointAdmission =
  | {
      kind: "checkpoint_admission";
      topic: TopicQuery;
      item: "member";
      source_route: TopicChildRoute;
      ref: {kind: "paper" | "book" | "talk"; slug: string; path: string};
      assignment: TopicAssignment | null;
    }
  | {
      kind: "checkpoint_admission";
      topic: TopicQuery;
      item: "card";
      ref: {slug: string; path: string; title: string | null};
      assignment: {subq: string};
    };

type TopicResumeSeed =
  | TopicSeedChildContinuation
  | TopicWorkContinuation
  | TopicRecallContinuation
  | TopicCheckpointAdmission;

type TopicResumeInput =
  | {resume_seed: TopicRecallContinuation | TopicCheckpointAdmission}
  | {
      resume_seed: TopicSeedChildContinuation | TopicWorkContinuation;
      userDecision?: UserDecision;
    };
```

All objects are closed. Where present, `topic`, `fingerprint`, route kind/slug,
leaf seed, options, and current public query are bound exactly. For material work,
`assignment.subq/role` equal `demand.subq/role`; the fingerprint is the canonical
JSON encoding of
`[kind,requested_slug,query,subq,role,reason]`. The initial `member_route` is the
demand's Paper or Book requested route. A Paper-to-Book transition preserves
that member route while replacing `leaf` with the Book route and seed.

A seed-child fingerprint is the canonical JSON encoding of
`["seed",kind,member_route.slug,seed,options]`. A recalled-member fingerprint is
the canonical JSON encoding of `["recall",kind,slug,path]`. Canonical encoding
uses the same recursively sorted object-key rule at parser and producer; it is
not model prose or a fuzzy title key.

Most importantly, a lifted leaf gate wraps the leaf-owned effective
`result.resume_seed` introduced in `723ff55`. Topic must not rebuild it from the
call-time seed. This preserves a resolved Book identity across a later year or
structure gate and preserves leaf options. If a resumed leaf returns another
gate, Topic replaces `leaf` with that newer effective capsule and keeps the same
work/assignment fingerprint.

The shared higher-order result ABI permits `resume_seed` only on:

- a lifted `needs_input` child gate; or
- the automatic `terminal:"needs_observation"` control branch, together with
  its non-empty exact `routes` array.

Topic normally requests one route: the current child for dynamic/seed work, or
the Topic route for checkpoint admission. The caller echoes the capsule in
`resume`, adding `userDecision` only after a human gate. The matching leaf still
owns operation and evidence-bound value validation.

Before resumed work runs, Topic:

1. consumes the capsule before accepting any newly proposed work;
2. binds it to the unchanged query and required exact child or Topic observation;
3. for `material_work`, verifies the subquestion still exists, the assignment
   still matches, and that the target is not already satisfied in the exact
   projection;
4. for a leaf continuation, verifies route/seed/options with its parser; and
5. dispatches only that one leaf.

If the user deleted the subquestion or current status already satisfies the
work, the capsule is stale: Topic discards it without delivering a decision or
calling the leaf, then reconciles from current disk facts. A structurally
inconsistent capsule is invalid input. A missing required exact child
observation returns `needs_observation` with the same capsule and exact route;
it does not guess from the path.

For a dynamic Recall row, the capsule stores the exact validated row because a
new Recall is allowed to return a different set. After its requested status is
supplied, Topic admits that exact route if the canonical artifact is usable;
otherwise it remains non-evidence and is not fabricated into a leaf identity.

`checkpoint_admission` is separate from child/Recall continuation and exact-binds
its `topic` to the current query. It protects one newly admitted member/card whose
immediately following steer checkpoint returned unknown or incoherent. Demand
work always carries its non-null directed assignment; seed/Recall intake may use
`assignment:null`. A member capsule's closed `source_route` records only the
seed, Recall row, or directed demand route that produced the admitted ref; it is
an origin identity, not a cursor. It lets resume skip that same invocation-local
intake route even when a provisional Paper or Book resolves to a different
canonical slug. After fresh Topic status, flatten the projection: a non-null
assignment requires its exact tuple, while null needs the exact member ref under
any schema-valid assignment. Otherwise call only `topic.steer` reconcile with
current projected refs plus the directed ref, or the bare ref when null. Never
replay the leaf or webcard. Another unknown checkpoint
returns the same one-item admission request; it never grows into a completed
prefix, queue, cursor, or retry engine.

This capsule is one pending value owned by the caller. It is not written to the
vault, `.quasi/`, or another sidecar, and it contains no stage, round cursor,
receipt chain, or sibling queue.

## Result terminals

Topic uses `quasi.material.result/0.1`. For every valid input, requested and
canonical Topic slugs equal `query.slug`.

- `complete` carries exact outline, overview, and resources refs and `next:null`.
- `needs_input` is either a direct Topic gate or one unchanged leaf gate wrapped
  as `{kind:"child", route, gate}`. A lifted child gate also carries the closed
  `resume_seed` above.
- `needs_observation` is an automatic, non-human control branch carrying exact
  `routes` and one closed `resume_seed`; the Skill fulfills it and reinvokes.
- real `blocked`/`failed` and every unknown outside that single checkpoint seam
  stop without a capsule or automatic replay meaning.
- `incomplete` uses only `topic.round_limit`, carries the three audited Topic
  artifacts, and reports the final ordered pending work.

The two direct Topic gates remain:

- `topic_seed`: no usable evidence can be produced under the current explicit
  seeds and bound; and
- `topic_needs_seeds`: a coherent final steer returned `signal:"needs_seeds"`.

The latter copies `suggested_queries` and derives
`uncovered_subquestions` in returned subquestion order from the same validated
steer receipt's `gap|thin` rows. Neither gate accepts an acknowledgement token.
The user changes public facts, options, seeds, or the outline and restarts.

`TopicPendingWork.role` is closed, not `string`:

```ts
type TopicPendingWork =
  | {
      kind: "material";
      material_kind: "paper" | "book";
      requested_slug: string;
      subq: string;
      role: TopicMemberRole;
      fingerprint: string;
    }
  | {
      kind: "webcard";
      card_slug: string;
      subq: string;
      fingerprint: string;
    };
```

## Operation-level coherence

### Recall

Run `topic.recall` exactly once per top-level invocation with research key
`topic:{query.slug}`, the query description, the current valid projected
subquestions if any, the three canonical roots, and fixed `max_items:8`. It is
readonly. Preserve returned order; each non-null path must be the exact canonical
path for its kind. Reject duplicate kind/slug rows. A non-complete or unknown
Recall stops before a writer.

A restart performs one new bounded Recall, but an explicit recalled-member
continuation is consumed independently of whether the new receipt repeats it.

### Steer

`topic.steer` rereads the exact outline on every create, refresh, checkpoint, or
repair call. Its returned subquestions use the schema-owned projection. Its
operation-owned candidate demand now requires deterministic `requested_slug`;
the plan never derives one from `query`. Every steer request binds
`max_cards:options.maxCardsPerRound`, and the receipt schema sets
`web_tasks.maxItems` to that exact bound (including zero).

Replace `complete: () => true` with a small concrete predicate. A complete steer
receipt is coherent only when:

- every demand, web task, dirty id, member assignment, and card assignment names
  a subquestion returned by that receipt;
- every demand/task targets a currently uncovered (`gap|thin`) subquestion;
- flattening returned outline items/cards admits no member or card absent from
  the request's exact refs;
- every request-bound member ref appears at least once, and every directed
  assignment appears as exact `(kind,slug,subq,role)`;
- every request-bound card appears as exact `(slug,subq)`;
- `needs_seeds` and `saturated` contain no candidate demands or web tasks;
- `needs_seeds` has at least one derived uncovered subquestion and at least one
  non-empty `suggested_queries` row; `saturated` has no uncovered
  subquestions;
- distinct material rows do not claim the same exact
  `(kind, requested_slug)` writer target;
- distinct web rows do not claim the same exact
  `vault/topics/{topicSlug}/cards/{card_slug}.md` target; and
- exact duplicate rows are coalesced in first-seen order before the predicate,
  never redispatched.

Different work tuples which collide on an exact output are an incoherent steer
receipt and stop before any child/card dispatch. Do not let fingerprint
uniqueness stand in for writer ownership. The same admitted artifact may still
appear under different subquestions; that is assignment, not a ref collision.

Interpret signals only as follows:

- `continue`: its validated work may open a bounded round;
- `needs_seeds`: return the typed gate; and
- `saturated`: the specialist has made the sole saturation claim.

Quiescence (no unseen work) is a loop stop, never relabelled saturation.

## Reconstruction and seed admission

At invocation start, reconstruct only from:

- the exact Topic observation's valid projection;
- explicit `seed_materials`;
- sparse exact child observations; and
- the optional one-shot resume capsule.

Admit usable projected members/cards in projection order. Repeating an artifact
under two assignments remains legal. A projected missing or unusable child is
not guessed from its path.

Process an applicable continuation before new writer work. Then process explicit
seeds in input order and validated Recall rows in receipt order. Coalesce only
exact current-run member owner keys, preserving first position.

Every newly admitted seed or recalled member is reconciled into the outline by
one `topic.steer` create/refresh checkpoint before another risky seed/child/card
writer starts. This also makes a dynamic Recall admission durable before a later
stop. Work proposed by these intake checkpoints is deferred until seed/Recall
admission finishes; the last coherent checkpoint can then open the first bounded
round. If intake added no new evidence, call one ordinary create/refresh steer to
open the loop.

For explicit seeds:

- a usable canonical exact observation is admitted directly;
- a canonical Paper or Book whose exact observation is present but incomplete
  is passed to its leaf even when `maxRounds === 0`; `maxRounds` limits research
  expansion, not completion of a supplied canonical material;
- a canonical seed lacking exact status returns `needs_observation` for its route
  with a `seed_child` continuation;
- at `maxRounds > 0`, a provisional Paper/Book without exact status returns
  `needs_observation`; only the real returned missing-status testimony is passed
  to its leaf;
- at `maxRounds === 0`, provisional seeds are collected into one `topic_seed`
  gate rather than dispatched; and
- an incomplete Talk runs only from its caller-supplied identity when the exact
  media is usable. Talk without usable canonical output or exact media enters the
  seed gate.

Candidate-demand and Paper-to-Book routes use the same handshake; Topic never
constructs a synthetic empty leaf observation.

A representative required test is a canonical, incomplete Book with
`maxRounds:0`: it must run the Book leaf and may return its real gate; it must not
be misclassified as forbidden discovery.

Leaf `complete` is admitted only with `next:null` and non-null canonical owner
slug. Topic uses that runtime owner slug and exact canonical path, never an
identity slug guessed by Topic.

For Paper `next`, do not admit the Paper. Construct the canonical Book seed from
the returned full `BookIdentity`, preserve the original Paper `member_route`,
and call `runBookPlan`. A Book gate wraps Book's effective leaf resume seed. Topic
does not reproduce the Paper publication-type predicate.

## Stable rounds and per-item checkpoints

A normal coherent steer receipt opens one stable ordered queue. Candidate
demands keep receipt order, followed by all returned web tasks in receipt order;
the request-bound receipt schema has already capped that array at
`maxCardsPerRound`. Validate all exact writer targets before dispatching the
first item. Material work fingerprints use
`[kind,requested_slug,query,subq,role,reason]`; web work uses
`[card_slug,subq,query,note]`.

`maxRounds` counts only queues whose first still-applicable work item begins. It
does not count the initial steer, checkpoint calls, finalization, or a queue whose
items all became stale.

For every item in the stable queue:

1. revalidate its subquestion and exact target against the latest checkpoint;
   drop stale or already-satisfied items while preserving remaining order;
2. run one Paper/Book leaf or one webcard with ordinary `await`;
3. admit only a coherent leaf completion, or `ok|unchanged` webcard with
   `card_available:true`; coherent `empty` only marks its fingerprint seen,
   records no admission, and skips the checkpoint;
4. for an admitted ref, immediately call one `topic.steer` refresh,
   before any next risky writer; and
5. treat that call as a checkpoint: update current subquestions and durable
   outline, but do not append its newly proposed work to the open queue.

After every checkpoint, revalidate the untouched remainder of the original
queue, preserve its order, and drop rows whose subquestion disappeared, became
covered/saturated, or whose exact target is now satisfied. A checkpoint
`needs_seeds` or `saturated` stops the loop. An unknown/incoherent checkpoint
starts only the one-item `checkpoint_admission` exact-status handshake; no later
writer starts.

The most recent coherent steer receipt closes the round: the opening receipt when no ref was admitted, otherwise the last admitted-ref checkpoint.
After the queue, including trailing `empty` rows, re-filter its proposals against seen fingerprints and current facts; remaining work opens the next round or becomes pending at the bound.
Do not add another steer, capsule, replay, or proposal merge.

Thus a successful item is either proved in the outline before the next writer or
protected by one admission capsule. Child gates/status requests return their
separate capsule directly. Neither a leaf/webcard nor an unknown writer is
redispatched.

If the bound is reached and the closing steer still has unseen applicable work,
freeze that order as `pending_work`, finish and audit current products, and
return `terminal:"incomplete"` with `topic.round_limit`. If no academic member or
available card exists at any loop stopping point, return `topic_seed` and never
synthesize empty evidence.

## Finalization and Audit order

The current closing steer receipt is the final steer: it already reread and
wrote the exact outline after the last admitted item. Finalization order is
strict:

1. Audit the exact outline.
2. If escalated, call only `topic.steer` with `mode:"repair"` and diagnostics for
   the exact outline, then re-Audit that outline once.
3. Only after the outline passes, run `topic.synthesise.overview` and then
   `topic.synthesise.resources` with the same exact admitted member/card refs.
4. Audit overview, allowing only its synthesis owner one repair and one
   re-Audit.
5. Audit resources, allowing only its synthesis owner one repair and one
   re-Audit.

Ownership is:

| Exact product | Semantic writer and escalated-repair owner |
| --- | --- |
| `02-outline.md` | `topic.steer` |
| `00-overview.md` | `topic.synthesise.overview` |
| `01-resources.md` | `topic.synthesise.resources` |

`topic.audit` is itself allowed only target-local mechanical edits declared by
its exact Audit contract; it never semantically rewrites a sibling. Because the
row's `exactPaths:true` schema binds every diagnostic to the requested target, a
schema-valid foreign diagnostic is unreachable. Do not add
`workflow.owner_ambiguity` production logic or a defensive test for that branch.
Malformed/unknown Audit output stops normally. Residual violations after the one
owner repair and pass-2 Audit return `workflow.repair_exhausted`.

An outline repair receipt may update the schema-owned subquestion projection for
synthesis, but its proposed research work is not dispatched during finalization.

## Skill boundary

The rewritten `research-topic` Skill does only outer transport:

1. collect query, bounded options, and explicit seeds;
2. obtain one exact Topic status;
3. invoke fixed `workflows/topic.mjs`;
4. for `needs_observation`, run every exact route status (normally one), place a
   child result in the sparse map or replace the Topic observation, echo the
   capsule without a decision, and restart;
5. for a lifted child gate, present the unchanged inner question, obtain one
   answer, run fresh exact child status, echo the capsule with that one decision,
   refresh Topic status, and restart;
6. present direct Topic gates or ordered incomplete work without interpreting
   Stage receipts; and
7. after `complete`, run one exact Topic post-status.

Post-status must prove a valid usable outline with non-null projection, usable
overview, and usable resources at the three exact paths. Otherwise the Skill
reports the disk mismatch and does not announce completion. It never scans the
vault, selects a Topic operation, derives a child slug, or persists a capsule.

## Focused Task 12B evidence

Tests should prove behavior at load-bearing seams, not enumerate defensive
permutations:

- strict public/status binding, including exact nested projection paths and
  subquestion membership, with zero Agent calls on malformed input;
- schema-generated steer projection plus the concrete cross-field predicate;
- one ordinary bounded run, explicit seeds, and Recall admission;
- canonical incomplete Paper/Book at `maxRounds:0`, provisional status handshake
  above zero and seed gate at zero, Talk behavior, and generic Paper-to-Book;
- one stable sequential queue with a checkpoint after each admitted ref and no
  next writer after a checkpoint unknown;
- a later gate/status request after an earlier success proving the earlier
  success is already in the outline;
- dynamic work and Recall observation continuations surviving a changed next
  Recall/steer receipt;
- intake and directed checkpoint unknowns returning one admission capsule, then
  fresh Topic status proving or reconciling that item without writer replay;
- two successive Book gates using the newer leaf-owned effective resume seed;
- stale continuation after user deletion of its subquestion causing no leaf
  dispatch;
- exact output collision rejection before the first writer;
- coherent empty web evidence producing no checkpoint capsule, `needs_seeds`,
  sole saturation signal,
  no-evidence gate, and round-limit pending order with closed roles;
- final order: final steer, outline Audit/repair/re-Audit, both syntheses, then
  overview and resources audits/repairs;
- no foreign-path Audit defense; and
- exact Topic post-complete status at the Skill boundary.

Do not add scheduler, lock, reservation, collision recovery, cursor, vault
inventory, field-permutation, or all-terminals-by-all-kinds tests.

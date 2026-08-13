# Skill Orchestration Schema

date: 2026-08-04
status: maintainer contract

This document describes how quasi Skills drive named material Workflows. Active
`SKILL.md` files contain only the runtime guidance needed by their executing
model.

## Principle

A Skill is a thin user-facing driver. It recognises intent, observes exact disk
state, invokes a fixed named Workflow, presents typed human decisions, and
verifies the returned artifacts. It does not reproduce material progression or a
specialist's professional method.

A named Workflow owns one logical material. Its TypeScript plan selects
material-local operations from current testimony and returns one typed Material
result. An Agent owns judgement inside one exact operation envelope. A
deterministic CLI owns its declared I/O mechanics.

## Active Skill shape

Use these landmarks when applicable:

```text
任务
输入
硬约束
状态
Agent / Helper 合同
工作流
执行流程
断点续跑
输出
```

`任务` is one positive sentence. `输入` records facts that can come from the
user. Frontmatter `description` is a short routing hint, not a trigger list,
history note, or phase walkthrough.

## Ownership

- The Skill owns the current user request, top-level material concurrency, and
  presentation of typed results.
- The named Workflow owns material identity transitions, operation order,
  bounded joins, checkpoints, and owner-correct repair.
- The exact `quasi-status/0.2` observation owns durable processing facts.
- A Stage Agent owns professional judgement within one request envelope.
- Artifact schemas own frontmatter/body structure; the operation catalog in
  `scripts/schemas/operations.py` owns stable operation identity and artifact templates; descriptor rows own only
  request/receipt behavior.

There is no second Skill state machine, Workflow cursor, receipt log, or inferred
writer success.

## Named Workflow input and result

The active entries are:

```text
workflows/paper.mjs
workflows/book.mjs
workflows/talk.mjs
workflows/translation.mjs
workflows/author.mjs
workflows/topic.mjs
workflows/webpage.mjs
```

Paper, Book, Talk, and Translation receive a closed seed/options envelope plus
one exact status observation. Webpage is the sole initial exception: Collect transports
its exact public URL in a provisional seed with `observation:null`; the entry returns a
canonical route that Collect observes before the existing direct-leaf resume. Any named
entry may return exact routes for host observation and an opaque one-item continuation.

The public result is `quasi.material.result/0.1`:

- `complete` — verify its exact canonical artifacts with fresh status;
- `needs_observation` — fetch only the returned routes and reinvoke the same
  entry with the unchanged continuation; complete returned status observations
  for the same routes advance only when they differ byte-for-byte; after two
  consecutive byte-for-byte identical recovery observations, stop and report
  the last typed result and exact status;
- `needs_input` — present the typed gate, refresh its routes, and attach only the
  gate-owned decision;
- `incomplete` — report Topic's ordered bounded pending work without calling it
  saturated; and
- `blocked|failed` — present the typed issue and stop.

One result is consumed once. A fresh ordinary invocation reconstructs from disk;
only a current gate or observation result authorises use of its opaque
continuation.

## Internal Stage unit contract

A prepared Stage request states:

```text
Goal          The useful state this specialist must establish.
Identity      The bounded material or collection identity.
Exact refs    Inputs it may inspect and outputs it may create.
Capabilities The public quasi commands or exact reads/writes it may use.
Evidence      Facts already established by the caller.
Receipt       One StructuredOutput schema and terminal meanings.
```

The internal receipt is `quasi.stage.receipt/0.3`. The model produces judgement
fields and one closed `complete|needs_input|blocked|failed` terminal. After
StructuredOutput validation, the host stamps top-level single-value bookkeeping
consts. Plans may check small concrete cross-field relationships, but do not
reinterpret a schema-valid specialist failure.

An Agent chooses its own useful number of searches, comparisons, or recovery
steps. Numerical bounds belong at genuine shared-resource or composition
boundaries, not as proxies for professional judgement.

## Concurrency and recovery

`collect-material` may run up to its documented number of distinct top-level
material keys concurrently. One named Workflow owns each key. Webpage's provisional
URL intake is followed by the same direct-leaf exact-status resume: copy its opaque
`resume_seed.{seed,options}` byte-for-byte, use the returned canonical route observation,
and retain the two unchanged-observation stop rule. Only Book fans out
inside a Workflow, using one host pipeline over disjoint chapter outputs. Topic
uses stable sequential work with immediate outline checkpoints; Author composes
its frozen child list sequentially.

Unknown writer outcomes stop the invocation. A `needs_observation` result is not an
unknown writer outcome: the Skill resumes it with fresh exact status and the current
opaque continuation, but never blindly replays a writer. Do not add automatic retry,
lock, reservation, completed-prefix, or replay machinery.

## Review checklist

When changing a Skill or Workflow:

1. Identify one owner for user state, material progression, specialist judgement,
   deterministic effects, and artifact shape.
2. Keep every writable path exact and every public input closed.
3. Reuse the generated schema and prepared-dispatch boundary; do not add another
   validator.
4. Keep negative prose limited to real safety or ownership boundaries.
5. Prefer one causal test per meaningful seam over field or mode matrices.
6. Update routing, dead-name, bundle-parity, and exact-status tests.
7. Run `npm run build:workflows`, `npm run check:workflows`, focused tests, and
   the full suite.

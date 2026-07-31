# Skill Orchestration Schema

date: 2026-07-31
status: maintainer contract

This document describes how quasi skills coordinate a graph. It is maintainer
guidance; active `SKILL.md` files contain only the runtime guidance needed by the
executing model.

## Principle

A skill is the user-facing coordinator. It recognises intent, starts the graph,
understands typed terminals, presents real human decisions, and explains what
happened. It does not duplicate the graph's material state or a specialist's
professional method.

The Workflow is a stage board. It controls phase order, exact envelopes,
concurrency, coalescing, ownership boundaries, and typed routing. It should be
easy to answer “which material is at which stage?” without reading specialist
reasoning.

An Agent is a goal-owning specialist. Given exact scope and declared
capabilities, it may investigate, compare evidence, and perform local recovery
until it can honestly return `complete`, `needs_input`, `blocked`, or `failed`.
The deterministic CLI remains responsible for I/O mechanics, locks, staging,
fingerprints, and atomic publication.

## Active Skill Shape

Use these landmarks when they help the executing model:

```text
任务
输入
状态
Agent / Helper 合同
工作流
执行流程
断点续跑
输出
```

`任务` is one positive sentence. `输入` records facts that can come from the
user. `状态` names authoritative receipts and ownership. `执行流程` is concise
pseudocode only when prose would leave host or batch behaviour ambiguous.

Frontmatter `description` is a short routing hint describing user intent. It is
not a trigger-word list, phase walkthrough, history note, or miniature README.

## Ownership

- The graph owns canonical identity, phase state, exact artifacts, and material
  or collection receipts.
- The Skill owns the current user request, explicit user decisions, and
  skill-scoped completion sidecars.
- A Stage Unit Agent owns its professional judgement within the request
  envelope. Read-only specialists return evidence; producer specialists write
  only caller-named products.
- A deterministic CLI writes only outputs named by its command contract.
- Artifact schemas own frontmatter and body structure; Workflow Operations own
  dynamic refs and evidence requirements.

This split leaves one source of truth for each concern. In particular, the
Skill does not keep a second recall/metadata/writer-success state machine, and
the Graph does not reproduce an Agent's search strategy or recovery dialogue.

## Stage Unit Contract

A Stage Unit request should answer:

```text
Goal          What useful state this specialist must establish.
Identity      The bounded material or collection identity.
Exact refs    Inputs it may inspect and outputs it may create.
Capabilities The public quasi commands or exact reads/writes it may use.
Evidence      Facts already established by earlier stages.
Receipt       One StructuredOutput schema and its terminal meanings.
```

The shared receipt is `quasi.stage.receipt/0.2`. Its required `terminal` is a
closed status union, so a success receipt cannot also carry a failure issue:

- `complete`: the specialist established the exact postcondition consumed by
  the next stage.
- `needs_input`: one concrete user answer can change the outcome; the terminal
  carries the evidence-backed candidates and exact identity conflict fields.
- `blocked`: the current capability boundary or an unknown writer outcome
  prevents a trustworthy continuation.
- `failed`: the specialist exhausted useful approaches and reached a known
  failure.

StructuredOutput and Graph validation use the same schema. Graph-side checks
may re-prove exact path ownership and joins between artifacts, but should not
reinterpret a schema-valid failure as malformed because of a hidden policy.

An Agent chooses its own useful number of queries, comparisons, or diagnostic
steps. A numerical budget belongs in the Graph when it protects a shared
resource, prevents duplicate writers, or bounds a collection fan-out—not as a
proxy for professional judgement.

## Workflow and Batch Behaviour

The shared UI phases are:

```text
Recall → Search → Acquire → Prepare → Analyse → Synthesise → Audit
```

Agent labels begin with the stable material key and then the operation. One
request containing 2–32 Books/Papers enters one batch Workflow. Phase-local
FIFO admission allows items to pipeline independently while keeping one
aggregate graph and one correlated result list.

Single-action Operations may remain small. Analyse, Synthesise, and Audit often
have one exact product and one clear postcondition; a Stage Unit is useful where
the work naturally needs investigation or local recovery, not as a reason to
make every Agent large.

## Human Gates and Recovery

The specialist formulates a concrete question and returns `needs_input`; the
Skill presents it and records the user's answer in a new graph request. The new
graph observes durable artifacts again rather than relying on an old JavaScript
cursor.

Unknown writer outcomes remain suspended for the current run. A later explicit
request re-enters the graph: Search observes the exact local owner again and
the receiving production Stage reconciles its durable artifact before any new
write. Neither Agent autonomy nor Skill recovery creates a concurrent duplicate
writer.

For a batch, the Skill reports all item terminals together and gathers user
answers before submitting one follow-up batch containing the affected original
items.

## Review Checklist

When changing a skill or stage:

1. Identify one owner for user state, graph state, specialist judgement, CLI
   effects, and artifact shape.
2. Confirm the request is self-contained and every writable path is exact.
3. Confirm StructuredOutput and runtime validation share one schema.
4. Check that negative prose is limited to genuine safety or ownership
   boundaries; describe the desired work positively.
5. Keep phases progress-oriented and labels material-oriented.
6. Update tests that assert receipts, routing, source/bundle parity, or removed
   names.
7. Rebuild `workflows/process-material.mjs` from `scripts/workflows/` and run
   the focused plus full test suites.

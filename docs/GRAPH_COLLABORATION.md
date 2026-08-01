# Graph collaboration model

Maintainer constitution for `scripts/workflows/`. This document pins how the
process-material graph is allowed to collaborate with capabilities, agents,
and the entry skill, so that judgment stops re-accumulating in the graph.
Like `docs/SKILL_ORCHESTRATION.md`, this is maintainer guidance: active
skills and agent contracts must not cite it at runtime.

## The four layers

1. **Capabilities** (`bin/quasi-*`, `scripts/`): deterministic and, where
   they write, transactional (fenced generation, manifest-last publication).
   They own file writes, publication, and identity/state probes. They never
   make fuzzy judgments. They have been stable; treat them as the bedrock.
2. **Agents** (`agents/*.md`): own all fuzzy judgment — method choice,
   interpretation of capability output, local recovery, stopping, and the
   honesty of their terminal. An agent wraps capabilities precisely because
   capability output sometimes needs judgment.
3. **Graph** (`scripts/workflows/`): a thin interpreter. It exists to reduce
   the agent's burden: assemble the envelope (feed external data in), let
   the host enforce the output schema, route the terminal, and provide
   concurrency and writer safety. It never re-judges specialist output.
4. **Entry skill**: user intent, gate presentation, and fault tolerance
   around whole runs. It owns no second state machine.

## Trust rules — who proves what

- **Shape is proven by the host.** The schema handed to StructuredOutput is
  the only shape validation. The graph does not re-validate shape.
  (Foreign-receipt admission performs its own validation because it does not
  cross the host boundary.) Every Operation then passes the same narrow,
  contract-relative terminal readability gate: a receipt whose required
  terminal structure cannot even be read is an **unknown outcome** and fails
  closed (blocked, never replayed, never ok). This is the writer-safety rule
  applied uniformly to unintelligible output, not a second validation of
  host-proven shape.
- **Facts are proven by the disk.** A writer stage's postcondition is an
  artifact probe (`quasi-status` is the shared prover), never
  cross-examination of receipt fields. Receipts can lie; the disk cannot.
  This applies at joins too: child admission re-proves from disk, not by
  introspecting the child's receipt. The oracle reports **observations,
  not inferences**: stage order, dispatchability, and next-step choice are
  the driving agent's judgment, never encoded into the status tool.
- **Judgment is proven by no one.** The agent returns one honest terminal;
  the graph routes it verbatim. A schema-valid failure receipt is never
  reinterpreted as malformed because the graph disagrees with the method.

## The one call protocol

Every agent invocation is a **data row**, not a code entity:

```
{ agent, stage, envelope_refs, payload_schema, disk_postcondition }
```

- Receipts share one shape: `quasi.stage.receipt/0.2`, four terminals
  (`complete | needs_input | blocked | failed`), one typed issue.
- Uniform rules, written once in the interpreter:
  - writers are never retried or replayed; an unknown writer outcome stops
    the run (resume/reconcile only);
  - readonly calls may retry once;
  - `needs_input` bubbles to the user unchanged (all gates are stage gates);
  - `blocked` stops the run;
  - every call enters its stage's FIFO lane.

## What the graph must NOT contain

- per-operation status invariants, echo functions, or branch unions;
- policy or method knobs inside envelopes (a budget belongs in an envelope
  only when it protects a genuinely shared resource);
- a second, stricter interpretation of any schema-valid receipt;
- receipt re-validation at joins where a disk probe proves the same thing;
- special-cased user gates;
- backwards-compatibility shims (explicit project decision: no legacy
  compatibility; delete, do not alias).

## Target shape

- One interpreter plus declarative operation rows for material, collection,
  and research graphs — same internals, different owners and entries.
- One shared receipt shape with small per-row payloads (diary fields, not
  contract fields).
- One source of truth for stage order and artifact layout, read by the
  loops, `quasi-status`, join admission, and tests alike.
- Budget: the graph should converge toward roughly 4-6k lines total.
  Anything above that needs a named reason in this document.

## Tests

Tests defend the constitution and the capability layer, never the graph's
internals.

- **Keep**: capability-layer CLI tests (extract/download/translate/
  transcribe/audit/vault/status — they test deterministic bedrock and are
  the safety net while the graph shrinks); protocol tests (the shared
  receipt shape, four-terminal routing, writer no-replay, gate passthrough
  — written once against the interpreter); join-admission and ingress
  normalization tests; cheap guards (dead names, doc sync).
- **Forbidden as durable tests**: assertions that pin per-operation receipt
  fields, per-loop edge order, exact failure-code strings, or any shape
  this document schedules for deletion. Characterization tests are
  scaffolding with an expiry date: they exist only inside a
  behavior-preserving migration and are torn down when it lands.
- A failing test is not authority. When a test conflicts with this
  document, the test is wrong: delete or rewrite it against the rule it
  should defend, and say so in the report. Minimal code edits whose only
  purpose is appeasing a pinned implementation detail are the failure mode
  this section exists to prevent.
- Budget: graph-internal test mass should track the graph budget (roughly
  one line of protocol/table test per two lines of graph); capability
  tests are exempt.

## Migration state

- **0.52.27**: Paper/Book Acquire on the shared stage receipt; book year
  gate is a standard `needs_input`; acquisition method moved to
  `agents/download-agent.md`; shared edge router `materials/route.mjs`;
  `quasi-status` disk oracle added.
- **0.52.28**: Analyse / Audit / Synthesise unified onto stage
  terminals; strict Topic-recall vertical unified; member/receipt admission
  slimmed onto shared validators; legacy operation IDs removed.
- **0.53.0 (constitution round)**: the Pi/Codex host adapters and modern
  runtime schema backstop are gone; stage receipts pass one contract-relative
  terminal readability gate, while pre-stage author discovery and rolling
  Topic remain a named legacy island. Graph-internal characterization tests
  were pruned from about 23.5k to 14.8k lines so they defend doctrine instead
  of implementations. One `defineOperation` factory now interprets descriptor
  rows for Paper, Book, Talk, and Translation, and the 182-line material
  interpreter executes their per-kind declarative tables. Collection joins
  admit children from `member.admission-probe` disk testimony via
  `quasi-status --identity`; because audit has no durable disk signal yet,
  clean-audit proof deliberately remains receipt-based.
- **0.54.0 (Topic-merge round)**: the Author discovery family moved onto
  descriptor rows, followed by Topic steer and webcard. The rolling Topic loop
  was retired in favour of one bounded modern graph owned solely by
  `research/topic-recall.mjs`: its `maxRounds` loop fans out web cards, reuses
  shared material dispatch and disk-backed child admission, and closes through
  canonical `topic.audit`. The compatibility island and the old
  `guard`/`retryNull` helpers were deleted, so every Operation now crosses the
  same terminal gate. Topic dossier pages were retired as a product decision;
  the public `precise-topic` skill became `research-topic`.

## Next focus

Reduce graph and graph-internal test mass toward the 4–6k-line budget by
factoring shared payload vocabularies out of descriptor rows, establishing one
source of truth for artifact layout, and adding a durable audit disk record so
collection/research admission can finish moving from receipt proof to disk
testimony.

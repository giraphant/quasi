# Skill-driven collaboration model

Maintainer constitution for quasi's stage collaboration. This document pins how
skills, descriptor rows, specialist Agents, and deterministic capabilities share
authority now that the self-running graph driver is gone. Like
`docs/SKILL_ORCHESTRATION.md`, it is maintainer guidance: active skills and Agent
contracts must contain only the runtime information their executing model needs.

## The four layers

1. **Skills** (`skills/*/SKILL.md`) are the drivers. They identify user intent,
   normalise and coalesce requests, observe disk state through `quasi-status`,
   select the next applicable stage, present typed human gates, and stop honestly
   on blocked, failed, or unknown writer outcomes.
2. **Rows plus run-stage** (`scripts/workflows/operations/rows/`,
   `scripts/workflows/run-stage.entry.mjs`, and the generated
   `workflows/run-stage.mjs`) form the host boundary. A descriptor row owns one
   operation's exact refs, envelope, Agent type, phase, receipt schema, and narrow
   completion contract. run-stage resolves one `kind + stage`, invokes exactly one
   Agent with that row's prompt/schema, and returns its receipt verbatim. It has no
   next-stage routing, retry, coalescing, join, or material-state loop.
3. **Agents** (`agents/*.md`) own all fuzzy judgment: method choice,
   interpretation of capability output, local recovery, stopping, and the honesty
   of their terminal. An Agent reads or writes only the exact artifacts in its
   request.
4. **CLIs** (`bin/quasi-*`, `scripts/`) are deterministic and, where they write,
   transactional through fenced generation and manifest-last or atomic
   publication. They own file mutation and identity/state probes, never fuzzy
   judgment.

## Trust rules

- **Shape is proven by the host.** The schema passed to StructuredOutput is the
  receipt-shape authority. run-stage returns that receipt unchanged; neither it
  nor the skill adds a second schema validator.
- **Facts are proven by disk observations.** `quasi-status` reports exact evidence
  and refs. After a stage, the skill re-observes disk before choosing a later
  writer. A receipt alone never proves a later-stage artifact exists.
- **Judgment belongs to the specialist.** A schema-valid
  `complete|needs_input|blocked|failed` terminal is consumed as returned. The
  skill must not reinterpret a failure merely because it would prefer another
  method.
- **Routing belongs to the skill.** Stage order, bounded concurrency, duplicate
  prevention, collection membership, and user-facing gates are explicit skill
  actions over observations and receipts, not an implicit graph state machine.

## The one-call protocol

Every Workflow invocation selects one data row:

```text
{ operation, agentType, stage, exact_refs, envelope, receipt_schema,
  completion_contract }
```

- Receipts share `quasi.stage.receipt/0.2` and exactly four terminals:
  `complete | needs_input | blocked | failed`.
- `workflows/run-stage.mjs` accepts `kind`, `slug`, `stage`, and caller context,
  resolves one row, makes one Agent call, and returns the result.
- StructuredOutput repair of a still-running invocation is provider-level schema
  correction, not a new stage dispatch.
- A skill may dispatch independent work concurrently, but it must resolve and
  coalesce identity before any duplicate writer.
- A missing or ambiguous writer receipt stops the current driver. Resume starts
  with `quasi-status`; the writer is never blindly replayed.
- `needs_input` is presented to the user unchanged. `blocked` and `failed` stop
  that item with their typed issue.

## What must not return

- a self-running graph, per-kind loop, batch driver, router, join runtime, FIFO
  lane scheduler, receipt classifier, or automatic replay mechanism;
- a compatibility alias for a deleted entry or module — project policy is
  delete, do not alias;
- per-operation method trees in skills or rows;
- inferred state inside `quasi-status`; it reports observations only;
- duplicate artifact ownership or path discovery outside the current envelope.

## Project roots and observability

- cwd is the project/vault root. A non-empty `CLAUDE_PROJECT_DIR` takes
  precedence, but Workflow specialists may receive it as an empty string and
  must then use cwd for exact relative refs.
- `claude -p --output-format json` stdout contains only the final session
  envelope, not a complete stage/tool trace. Headless E2E harnesses must inspect
  the session JSONL and per-Workflow JSON sidecars when proving which stage
  driver ran.

## Tests

Tests defend the capability layer and the surviving stage protocol:

- keep capability CLI tests (extract, download, translate, transcribe, audit,
  vault, status), skill/dead-name guards, schema registry tests, and run-stage
  protocol tests;
- run-stage protocol coverage resolves every registered kind/stage row, checks
  schema generation, and pins the four closed terminal branches from
  `stage.mjs`;
- do not recreate per-loop edge-order, ingress, join, scheduler, retry, or batch
  harnesses for deleted machinery;
- a failing characterization test is not authority when it contradicts this
  constitution: delete or rewrite it against the surviving boundary.

## Migration state

- **0.52.27**: Paper/Book Acquire moved to the shared Stage receipt; Book year
  gates became `needs_input`; `quasi-status` was added as the disk oracle.
- **0.53.0**: one `defineOperation` factory began interpreting descriptor rows;
  host-specific adapters and duplicate schema backstops were removed.
- **0.54.0**: Author and Topic operations moved onto descriptor rows, and the
  public topic skill became `research-topic`.
- **0.55.0 (skill-driven cutover)**: the self-running driver layer and its graph
  tests were deleted. The runtime is now exactly the four layers above: skill,
  rows + run-stage, Agents, and CLIs. A real clean-project E2E at
  `/tmp/quasi-e2e-r4/REPORT.md` was the deletion gate: `collect-material`
  alternated five run-stage calls with `quasi-status` observations through
  Search → Acquire → Prepare → Analyse → Audit, created and independently
  verified all artifacts, and never invoked the retired driver. The run also
  established two expected observations: Analyse may complete before Audit
  performs mechanical normalization, which is designed Analyse-then-Audit
  behavior; and headless stdout alone does not expose the full stage/tool trace,
  so JSONL plus Workflow sidecars are the definitive execution evidence.

## Next focus

Keep skills readable as explicit drivers, and reduce duplicated vocabulary
across descriptor rows without moving judgment into them. Audit is
deliberately not a status concern: a full-vault audit re-runs in under a
minute (measured: 19,648 files in 42s), so cleanliness is recomputed on
demand and covered by the maintainer's periodic sweep, never cached.

# Material-Oriented Workflow Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generic public `run-stage` API with named, material-oriented Workflows for Paper, Book, Talk, Translation, Author, and Topic, while keeping every specialist boundary schema-validated and making the user-facing Skills thin status/gate drivers.

**Architecture:** Generated fixed-kind entries delegate to explicit TypeScript plans. Plans compose small material-local row sets with one hardened prepared-operation dispatch primitive; the universal catalog remains compatibility-only until retirement. Only Book uses host `pipeline()` for intra-material chapter concurrency. Disk observations are explicit Workflow inputs, current-run receipts are trusted inside the owning plan after host validation but are not part of the public MaterialResult, and no hidden cursor, replay loop, lock service, or speculative fallback is introduced. Author and Topic compose the leaf plan APIs in one direction and request only the exact child observation that a concrete route actually needs.

**Tech Stack:** TypeScript 5.9, esbuild, Claude Code Dynamic Workflows, Python 3, pytest, existing JSON Schema projection and `quasi-*` CLI surface.

## Global Constraints

- Do not hand-edit `workflows/*.mjs` or `scripts/workflows/artifact-contracts/generated.{mjs,d.mts}`; rebuild them with `npm run build:workflows`.
- A host-loadable Workflow bundle exports only `meta` and executes a top-level `return await __quasiWorkflow.run({agent,pipeline}, args)` wrapper. Internal source entries may export `run` for bundling/tests; generated public files must not export runtime helpers. Do not depend on undocumented `parallel`, `phase`, or `log` globals.
- `scripts/schemas/` remains the source of artifact paths and structures. TypeScript plans own order, branching, joins, carries, and repair routing.
- Preserve `quasi.stage.receipt/0.3`; add the host-owned `quasi.material.result/0.1` union rather than changing Agent receipts.
- Every schema-valid `complete` receipt must pass its owning row's cross-field predicate at every dispatch site.
- Unknown writer outcomes stop and are never replayed in the same run. Do not add local Promise timeouts.
- Writer independence is proved by exact/subtree write targets, never prompt equality.
- Only Book chapter analysis uses intra-material `pipeline()`. Author and Topic process child materials in stable sequence; top-level Skill concurrency remains one Workflow per logical material.
- Do not add cross-process locks or semantic-canonicalization services. Suppress only duplicate known material keys before launch; accept rare post-Search canonical collisions for manual cleanup.
- Add a guard, fallback, retry, alias, or compatibility branch only when tied to a documented host outcome, reachable domain state, active caller, or reproduced regression.
- Keep `CLAUDE.md` and `AGENTS.md` byte-for-byte identical.
- Preserve transactional, path/symlink, PDF, identity, schema, secret/env, and Crossref venue-authority tests.

---

### Task 1: Record the baseline and the test-migration ledger

**Files:**

- Create: `docs/superpowers/plans/2026-08-04-run-stage-test-migration-map.md`
- Verify: `tests/test_run_stage.py`
- Verify: `tests/test_skill_orchestration.py`
- Verify: `tests/test_status_cli.py`

- [ ] Run the pre-change baseline and save the exact command results in the migration ledger:

```bash
npm run check:workflows
python3 -m pytest tests/test_run_stage.py tests/test_status_cli.py tests/test_skill_orchestration.py tests/test_dead_names.py -q
python3 -m pytest --collect-only -q
```

- [ ] Enumerate every `test_*` function in `tests/test_run_stage.py` and give it an individual ledger row. Start with these mandatory destinations and add a row for every remaining function before committing:

```markdown
| Existing invariant | Replacement test | Retirement condition |
|---|---|---|
| row/schema pairing | `test_workflow_dispatch.py::test_catalog_prepares_each_operation_with_its_own_schema` | replacement passes |
| four closed terminals | `test_workflow_dispatch.py::test_stage_terminal_union_is_closed` | replacement passes |
| host stamping | `test_workflow_dispatch.py::test_dispatch_stamps_only_host_fields` | replacement passes |
| incoherent complete | `test_workflow_dispatch.py::test_incoherent_complete_blocks` | replacement passes |
| null/exception outcome | `test_workflow_dispatch.py::test_unknown_outcome_blocks_without_replay` | replacement passes |
| Paper carry/order | `test_material_plans.py::test_paper_happy_path_carries_selected_input` | replacement passes |
| chapter ordering | `test_material_plans.py::test_book_pipeline_preserves_manifest_order` | replacement passes |
| duplicate writer ownership | `test_material_plans.py::test_book_rejects_overlapping_outputs_before_dispatch` | replacement passes |
| `output_exists` binding | `test_material_plans.py::test_book_binds_create_and_reconcile_from_initial_observation` | replacement passes |
| generated bundle executes source run | `test_workflow_bundle_abi.py::test_generated_workflow_returns_source_run_result` | replacement passes |
| missing chapter observation rejects | focused `chapter.analyse` context test in `test_workflow_dispatch.py` | replacement passes |
| chapter label/title preservation | focused `chapter.analyse` request test in `test_workflow_dispatch.py` | replacement passes |
| Paper Acquire URL/capability envelope | focused `paper.acquire` request test in `test_workflow_dispatch.py` | replacement passes |
| shared request tag and phase | catalog wiring test in `test_workflow_dispatch.py` | replacement passes |
| every schema const is typed | schema-closure test in `test_workflow_dispatch.py` | replacement passes |
| model schema excludes host stamps | `test_workflow_dispatch.py::test_dispatch_stamps_only_host_fields` | replacement passes |
| Acquire write fields exist only on complete | focused Paper/Book Acquire schema test in `test_workflow_dispatch.py` | replacement passes |
```

- [ ] Mark old tests about public `stage`, `until`, `units`, unknown kind/stage, and batch envelopes as “mode-only; delete after all active callers migrate.” Do not delete tests in this task.

- [ ] Commit the ledger.

```bash
git add docs/superpowers/plans/2026-08-04-run-stage-test-migration-map.md
git commit -m "test: map run-stage coverage to material workflows"
```

### Task 2: Define the host runtime and closed material result

**Files:**

- Create: `scripts/workflows/shared/host-runtime.mts`
- Create: `scripts/workflows/shared/material-result.mts`
- Create: `scripts/workflows/shared/material-input.mts`
- Create: `tests/workflow_harness.mjs`
- Create: `tests/workflow_test_support.py`
- Create: `tests/test_material_result.py`

- [ ] Add failing parser/result tests for non-object input, missing identity, malformed slug, missing observation, and a valid material envelope. Assert malformed inputs produce `quasi.material.result/0.1` with `terminal:"blocked"` and `issue.code:"material.invalid_input"` before a dispatch invocation can be constructed.

- [ ] Define the runtime exactly once:

```ts
export interface AgentOptions {
  schema: JsonSchema;
  agentType: string;
  phase: PhaseName;
  label: string;
}

export interface DispatchRuntime {
  agent(prompt: string, options: AgentOptions): Promise<WorkflowContext | null>;
}

export interface MaterialRuntime extends DispatchRuntime {
  pipeline<T, R>(
    items: readonly T[],
    worker: (item: T) => Promise<R>,
  ): Promise<R[]>;
}
```

- [ ] Implement the closed host-owned result types and constructors:

```ts
export const MATERIAL_RESULT_VERSION = "quasi.material.result/0.1" as const;

export type MaterialKind =
  | "paper" | "book" | "talk" | "translation" | "author" | "topic";

export interface RequestedMaterialIdentity {
  kind: MaterialKind;
  slug: string | null;
}

export interface CanonicalMaterialIdentity {
  kind: MaterialKind;
  slug: string;
}

export interface ExactArtifactRef {
  role:
    | "source" | "normalized_text" | "manifest" | "chapter"
    | "canonical" | "overview" | "outline" | "resources"
    | "translation";
  path: string;
}

export type ObservationRoute =
  | { kind: "paper" | "book" | "talk"; slug: string }
  | { kind: "translation"; slug: string; target_language: string };

export type ObservationKey =
  | `paper:${string}` | `book:${string}` | `talk:${string}`
  | `translation:paper:${string}:${string}`;

export type SparseObservationMap = ReadonlyMap<
  ObservationKey,
  QuasiStatusObservation
>;

export interface SparseObservationInput {
  route: ObservationRoute;
  observation: QuasiStatusObservation;
}

export type MaterialNextRoute = {
  kind: "book";
  identity: BookIdentity;
};

export interface MaterialIssue {
  code: string;
  operation: OperationName | null;
  summary: string;
  retryable: boolean;
  observation_request: ObservationRoute | null;
}

export type DirectGate =
  | {
      kind: "identity_conflict";
      operation: "material.search";
      material_key: string;
      question: string;
      conflicts: string[];
      candidates: Array<
        { kind: "paper"; identity: PaperIdentity }
        | { kind: "book"; identity: BookIdentity }
      >;
    }
  | {
      kind: "book_year";
      operation: "book.acquire";
      material_key: string;
      current_identity: BookIdentity;
      question: string;
      tmp_path: string;
      year_evidence: BookYearEvidence;
      proposed_actions: Array<"accept-current" | "use-recommended-year">;
    }
  | {
      kind: "book_structure";
      operation: "book.prepare";
      material_key: string;
      question: string;
      source_path: string;
      candidates: BookStructureCandidate[];
      conflicts: BookStructureConflict[];
    }
  | {
      kind: "translation_source" | "translation_configuration";
      operation: "translation.prepare";
      material_key: string;
      question: string;
      missing_fields: string[];
      candidates: TranslationCandidate[];
      candidates_fingerprint: string | null;
    }
  | {
      kind: "topic_seed";
      operation: null;
      question: string;
      seeds: Array<{ kind: "paper" | "book" | "talk"; slug: string; reason: string }>;
    }
  | {
      kind: "topic_needs_seeds";
      operation: "topic.steer";
      question: string;
      suggested_queries: string[];
      uncovered_subquestions: string[];
    };

export type TopicPendingWork =
  | { kind: "material"; material_kind: "paper" | "book"; requested_slug: string; subq: string; role: string; fingerprint: string }
  | { kind: "webcard"; card_slug: string; subq: string; fingerprint: string };

export type TypedGate =
  | DirectGate
  | { kind: "child"; route: ObservationRoute; gate: DirectGate };

export interface MaterialResultBase {
  schema_version: typeof MATERIAL_RESULT_VERSION;
  material: {
    requested: RequestedMaterialIdentity;
    canonical: CanonicalMaterialIdentity | null;
  };
}

export type MaterialResult =
  | (MaterialResultBase & {
      terminal: "complete";
      issue: null;
      artifacts: ExactArtifactRef[];
      next: MaterialNextRoute | null;
    })
  | (MaterialResultBase & {
      terminal: "needs_input";
      issue: MaterialIssue;
      gate: TypedGate;
    })
  | (MaterialResultBase & {
      terminal: "incomplete";
      issue: MaterialIssue & { code: "topic.round_limit" };
      artifacts: ExactArtifactRef[];
      pending_work: TopicPendingWork[];
    })
  | (MaterialResultBase & {
      terminal: "blocked" | "failed";
      issue: MaterialIssue;
    });
```

`PaperIdentity`, `BookIdentity`, and `TranslationCandidate` are closed interfaces matching their owning row schemas. Invalid input can therefore still return a result: `requested.slug` is `null` when no valid slug was supplied. `TypedGate` contains only gates with an active caller; there is no generic specialist-question escape hatch. Stage receipts remain plan-local evidence and are never copied into the public MaterialResult. `incomplete` belongs only to Topic after it has produced and audited its current bounded products but `maxRounds` leaves unseen work; it never claims saturation and returns the exact pending rows.

`material.canonical.slug` is the runtime material/owner slug used for exact status and child routing, not necessarily the bibliographic `identity.slug`: a Search hit uses `local_owner.vault_slug`, while a miss uses `receipt.identity.slug`. Post-status, Author/Topic coalescing, and child routes use this field. The sole unresolved disposition is Paper→Book `next`; before the Book plan establishes an owner, `material.canonical.slug` equals `next.identity.slug`, and every caller follows `next` rather than reporting completion.

`MaterialIssue` may carry one typed `observation_request` only when a higher-order plan cannot safely continue a dynamically discovered child without fresh disk testimony. This is an explicit stop-and-resume seam, not a retry: the Skill runs the named leaf `quasi-status` once, adds that exact observation to the next input, and starts a new higher-order Workflow.

Complete artifacts are exact and kind-specific when `next:null`: Paper canonical; Book manifest, every manifest-listed chapter canonical, and overview; Talk canonical; Translation PDF and manifest; Author canonical; Topic outline, overview, and resources. The sole `next !== null` case is a completed Paper publication-type disposition: `material.canonical` is the confirmed Book identity, `artifacts` is empty, and every caller follows the typed Book route before reporting material completion. No caller interprets the publication-type rule itself.

- [ ] Implement strict shared parsing for `identity`, `observation`, `options`, and optional `userDecision`. `sparseObservations(entries)` validates every observation's kind, slug, and Translation target against its route, rejects duplicate keys, and builds the sole in-memory `SparseObservationMap`; a leaf entry wraps its one public observation as a one-row map, while Author/Topic parse `child_observations` through the same helper. Add zero-Agent-call mismatch tests. A decision envelope is `{material_key,operation,value}`; a plan applies it only when both bindings match the next owning operation. Gate-specific values retain their evidence binding: identity conflict echoes candidate/conflict sets plus exact selection; Book keeps its structure or year evidence; Translation source keeps the candidate fingerprint and exact selected source path. Translation configuration is changed out of band and has no decision value. If fresh observation proves the owning operation's durable output, a supplied decision is stale and ignored. Kind-specific entry parsers add their own fields; the shared parser must not accept a universal `context` bag.

- [ ] Make `tests/workflow_harness.mjs` bundle a caller-named `.mts` source module with the repository's pinned esbuild and expose its internal named exports only inside the test process. Do not change the public Workflow ABI to make source helpers importable.

- [ ] Run:

```bash
npm run check:workflows
python3 -m pytest tests/test_material_result.py -q
```

- [ ] Commit.

```bash
git add scripts/workflows/shared tests/workflow_harness.mjs tests/workflow_test_support.py tests/test_material_result.py
git commit -m "feat: define material workflow runtime contract"
```

### Task 3: Extract the operation catalog and make context expansion fail closed

**Files:**

- Create: `scripts/workflows/operations/catalog.mts`
- Modify: `scripts/workflows/context-base.mts`
- Modify: `scripts/workflows/operations/define.mts`
- Modify: `scripts/workflows/operations/shared.mts`
- Modify: `scripts/workflows/operations/rows/search.mts`
- Modify: `scripts/workflows/operations/rows/paper.mts`
- Modify: `scripts/workflows/operations/rows/book.mts`
- Modify: `scripts/workflows/operations/rows/talk.mts`
- Modify: `scripts/workflows/operations/rows/translation.mts`
- Modify: `scripts/workflows/operations/rows/author.mts`
- Modify: `scripts/workflows/operations/rows/topic.mts`
- Modify: `scripts/schemas/export_contracts.py`
- Create: `tests/test_workflow_dispatch.py`

- [ ] Add failing tests proving: missing slug rejects before prompt construction; missing artifact variables never become `undefined`; every writer exposes at least one explicit target; audit rows expose their exact target; two exact targets collide; an exact target inside a subtree collides; two disjoint exact targets do not.

- [ ] Extend the generated `OperationRow` interface with a projection over already-resolved refs:

```ts
export type WriteTarget =
  | { scope: "exact"; path: string }
  | { scope: "subtree"; path: string };

readonly writeTargets?: (
  refs: WorkflowContext,
  context: WorkflowContext,
) => readonly WriteTarget[];
```

Readonly rows omit `writeTargets`. Every writer row supplies it. `book.acquire` returns both allowed source paths as conservative exact targets; Prepare rows list every path they may publish. `makeAuditRow()` takes an explicit `targetScope`; Paper, Talk, Author, and Topic pass `"exact"`, while Book passes `"subtree"` for `vault/books/{slug}`. No row derives ownership from prose.

- [ ] Make template expansion reject an absent/non-scalar placeholder:

```ts
export class InputContractError extends Error {}

const templateValue = (values: WorkflowContext, name: string): string => {
  const value = values[name];
  if (typeof value !== "string" && typeof value !== "number")
    throw new InputContractError(`missing artifact template value: ${name}`);
  return String(value);
};
```

Use `InputContractError` only for caller/domain contract violations that may safely become a zero-dispatch `invalid_context`. Validate canonical ASCII kebab slugs at `operationContextBase()` entry. Do not silently trim a malformed slug into a different identity. Ordinary implementation exceptions are not relabeled.

- [ ] Move row aggregation and descriptor preparation from `run-stage.entry.mts` into `operations/catalog.mts`. The public interface is:

```ts
export interface OperationInvocation {
  kind: KindName;
  operation: OperationName;
  slug: string;
  context: WorkflowContext;
  label: string;
}

export interface PreparedOperation {
  invocation: OperationInvocation;
  context: WorkflowContext;
  prompt: string;
  options: AgentOptions;
  stampedValues: WorkflowContext;
  complete(receipt: StageReceipt): boolean;
  writeTargets: readonly WriteTarget[];
}

export function prepareOperation(invocation: OperationInvocation): PreparedOperation;
export function writeTargetsOverlap(left: WriteTarget, right: WriteTarget): boolean;
```

- [ ] Extend `material.search` so a Paper request can represent the existing publication-type gate. The closed Search identity/candidate union carries `{kind:"paper",identity:PaperIdentity}` or `{kind:"book",identity:BookIdentity}`. Same-kind coherent complete continues the Paper plan; a user-confirmed Book identity produces the typed `MaterialNextRoute`. Do not add other cross-kind aliases.

- [ ] Add a catalog wiring test that prepares every registered operation with its real row/schema/refs and verifies every writer target is a normalized project-relative path. Do not create a terminal Cartesian product per row.

- [ ] Rebuild projections, run focused tests, and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_workflow_dispatch.py tests/test_run_stage.py -q
git add scripts/schemas/export_contracts.py scripts/workflows tests/test_workflow_dispatch.py workflows/run-stage.mjs
git commit -m "refactor: extract strict workflow operation catalog"
```

### Task 4: Harden one shared dispatch boundary and reuse it from compatibility mode

**Files:**

- Create: `scripts/workflows/shared/dispatch.mts`
- Modify: `scripts/workflows/run-stage.entry.mts`
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `tests/test_run_stage.py`

- [ ] Add failing shared tests for all four validated Stage terminals, host stamping, typed invalid context before Agent dispatch, a throwing Agent, a null Agent result, a predicate implementation error propagating unchanged, and a schema-valid but cross-field-incoherent `complete`. Do not add a speculative host-stamp-collision case: the closed StructuredOutput schema excludes stamped keys.

- [ ] Implement exactly this outcome boundary:

```ts
export type DispatchOutcome =
  | { kind: "receipt"; receipt: StageReceipt }
  | { kind: "invalid_context"; receipt: null; issue: MaterialIssue }
  | { kind: "incoherent_complete"; receipt: StageReceipt; issue: MaterialIssue }
  | { kind: "unknown_outcome"; receipt: null; issue: MaterialIssue };

export async function dispatchPreparedOperation(
  runtime: DispatchRuntime,
  prepared: PreparedOperation,
): Promise<DispatchOutcome>;

export async function dispatchOperation(
  runtime: DispatchRuntime,
  invocation: OperationInvocation,
): Promise<DispatchOutcome>;
```

`dispatchOperation()` catches only `InputContractError` before Agent launch and returns `invalid_context`; unexpected preparation exceptions propagate as implementation failures. `dispatchPreparedOperation()` maps only Agent rejection/null to `unknown_outcome`; it does not add a second JSON validator around host StructuredOutput. A predicate `false` retains the receipt as `incoherent_complete`; a predicate exception propagates unchanged and fails the implementation test instead of masquerading as a business terminal. No branch retries. Non-complete validated receipts remain `kind:"receipt"` unchanged, and the dispatch primitive does not reject for any documented Agent outcome, so every launched Book chapter can settle through `pipeline()`.

- [ ] Replace all compatibility single/batch/chain Agent calls with this primitive. Apply the predicate in single and batch modes as well as chain mode. Adapt the temporary batch path to the documented `pipeline(items, worker)` primitive and remove its `parallel` dependency. Preserve the old outward shapes for active callers: a coherent `receipt` unwraps to the receipt; chain maps `invalid_context`, `incoherent_complete`, and `unknown_outcome` to its existing distinct `stop_reason`; batch stores the corresponding typed compatibility error at the same input index; single returns the existing typed compatibility error. Add no new public mode behavior.

- [ ] Run:

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_workflow_dispatch.py tests/test_run_stage.py -q
```

- [ ] Commit.

```bash
git add scripts/workflows/shared/dispatch.mts scripts/workflows/run-stage.entry.mts tests/test_workflow_dispatch.py tests/test_run_stage.py workflows/run-stage.mjs
git commit -m "fix: apply operation completion checks at every dispatch"
```

### Task 5: Restore the official Workflow execution ABI and generalize the build

**Files:**

- Modify: `scripts/build-workflows.mjs`
- Create: `tests/test_workflow_bundle_abi.py`

- [ ] Add a failing regression test that executes the generated compatibility bundle as the host does: strip/replace only `export const meta`, construct `AsyncFunction("agent","pipeline","args", source)`, invoke it, and assert it returns the Stage result. The test must fail against the current export-only bundle.

- [ ] Replace the name-only build list with an entry table that can grow one named entry at a time. At this task only the active compatibility entry exists:

```js
const WORKFLOWS = [
  { name: "run-stage", kind: "compatibility", validate: validateCompatibilityEntry },
].map(({ name, ...config }) => ({
  name,
  entry: join(WORKFLOW_SOURCE_ROOT, `${name}.entry.mts`),
  output: join(ROOT, "workflows", `${name}.mjs`),
  ...config,
}));
```

The compatibility validator alone checks the old registry/chain projection. `validateMaterialEntry` is added now for later tasks and checks internal `workflowMeta`, internal `run`, and fixed-kind metadata. Operation calls already accept the generated `OperationName` type and resolve through the sole catalog; do not add a second hand-maintained operation list merely for build validation.

- [ ] Generate the official host shape, not an ESM test API:

```js
export const meta = ${JSON.stringify(workflowMeta, null, 2)}

${bundledSource}

return await __quasiWorkflow.run({ agent, pipeline }, args)
```

After replacing the single `export const meta` with a local declaration, reject every remaining static/dynamic import, `require`, or `export`; compile the body with `AsyncFunction("agent","pipeline","args", body)` using the documented host globals. Keep the 512 KiB gate per output. Internal source-entry exports remain available to the esbuild-based test harness, never in `workflows/*.mjs`.

- [ ] Build, check, and commit generated entries.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_workflow_bundle_abi.py tests/test_run_stage.py -q
git add scripts/build-workflows.mjs workflows/run-stage.mjs tests/test_workflow_bundle_abi.py
git commit -m "fix: restore executable workflow bundle ABI"
```

### Task 6: Establish the final factual status protocol

**Files:**

- Modify: `scripts/status/status.py`
- Modify: `bin/quasi-status`
- Modify: `scripts/translate/translate_commit.py`
- Modify: `scripts/workflows/shared/material-input.mts`
- Modify: `scripts/workflows/operations/rows/translation.mts`
- Modify: `skills/collect-material/SKILL.md`
- Modify: `skills/research-topic/SKILL.md`
- Create: `tests/fixtures/translation_language_tags.json`
- Modify: `tests/test_status_cli.py`
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `tests/test_skill_orchestration.py`

- [ ] Add failing tests for the final `quasi.status/0.2` payload. Remove `stages`, `next_stage`, and control-flow hints; every kind returns common `{schema_version,kind,slug,identity,facts}` with exact factual observations:

```ts
interface ArtifactObservation {
  path: string;
  present: boolean;
  usable: boolean;
}

interface TopicOutlineProjection {
  subquestions: Array<{
    id: string;
    question: string;
    coverage: "gap" | "thin" | "covered" | "saturated";
    channel: "academic" | "web" | "mixed";
    theory_used: number;
  }>;
  members: Array<{
    kind: "paper" | "book" | "talk";
    slug: string;
    subq: string;
    role: "evidence" | "theory" | "method" | "context" | null;
    artifact: ArtifactObservation;
  }>;
  cards: Array<{
    slug: string;
    subq: string;
    title: string | null;
    artifact: ArtifactObservation;
  }>;
}

type StatusFacts =
  | { kind: "paper"; source: ArtifactObservation; prepared: ArtifactObservation[]; canonical: ArtifactObservation }
  | { kind: "book"; sources: Array<{format:"epub"|"pdf"; artifact:ArtifactObservation}>; manifest: ArtifactObservation & {valid:boolean}; chapters: Array<{slot:string;title:string;filename:string;slug:string;word_count:number;start_page:number|null;end_page:number|null;input:ArtifactObservation;output:ArtifactObservation}>; overview: ArtifactObservation }
  | { kind: "talk"; media: ArtifactObservation[]; transcripts: ArtifactObservation[]; canonical: ArtifactObservation }
  | { kind: "translation"; target_language:string; source:ArtifactObservation; output:ArtifactObservation; manifest:ArtifactObservation }
  | { kind: "author"; canonical: ArtifactObservation }
  | { kind: "topic"; outline: ArtifactObservation & {valid:boolean; projection:TopicOutlineProjection|null}; overview: ArtifactObservation; resources: ArtifactObservation };
```

`identity` is always present and nullable; it is projected only from a usable canonical frontmatter file. A valid Book manifest row retains every field required by `chapter.analyse` (`slot`, `title`, `filename`, `slug`, `word_count`, `start_page`, and `end_page`), so a resumed plan never invents chapter labels or ranges. Remove the `--identity` mode and update active callers in the same commit. `quasi.status-scan/0.2` remains compact and returns only sorted unique `{kind,slug}` items, with no `next_stage` and no nested full observations.

- [ ] Preserve current path/readability/symlink/manifest checks while changing only the outward shape. Book `chapters[].output.present` is actual lstat evidence; it is never inferred from the expected path list. Add a regression where the manifest lists two outputs but only one exists, and only that chapter reports `present:true`. Add Author and Topic exact status kinds so their Skills can perform the same pre-run/post-complete durable check without a hidden cursor. Topic status parses the outline through the canonical Topic schema, derives only safe canonical member/card paths named by that validated outline, lstat-observes those exact paths, and returns a stable-order recovery projection; invalid outline yields `valid:false, projection:null`. No Agent discovers paths from outline prose.

- [ ] Replace the existing all-derivatives Translation test with failing tests for: required `--target-language`; `zh-cn` normalized to `zh-CN`; exact PDF plus exact manifest required; `fr-FR` artifacts never complete `zh-CN`; echoed `target_language`; and exact target facts only. `--scan` rejects `--target-language`.

- [ ] Reuse `validate_language()` and `output_paths()` from `scripts/translate/translate_commit.py`; do not create a third Python rule. Use `tests/fixtures/translation_language_tags.json` to drive Python and bundled-TypeScript parity tests, and change the TS row's `{0,2}` suffix bound to the Python contract's `{0,3}`. Translation v0.1 remains explicitly Paper-derived (`translation:paper:{slug}:{tag}`); remove any `source_kind` generalization from plan inputs.

- [ ] Change the interface to:

```bash
quasi-status --kind translation --slug SLUG --target-language TAG --json
```

`translation_status(root, slug, target_language)` reports source precondition and only the requested target's PDF/manifest facts.

- [ ] Update the shared TypeScript observation parser and the still-active compatibility Skills to consume `facts`. This keeps every commit runnable; later named plans use the same frozen v0.2 shape, and Task 13 changes only the internal catalog source, not status JSON.

- [ ] Run and commit.

```bash
python3 -m pytest tests/test_status_cli.py tests/test_translate_cli.py tests/test_material_result.py tests/test_workflow_dispatch.py tests/test_skill_orchestration.py -q
git add scripts/status/status.py scripts/translate/translate_commit.py scripts/workflows/shared/material-input.mts scripts/workflows/operations/rows/translation.mts bin/quasi-status skills tests
git commit -m "refactor: expose factual material status observations"
```

### Task 6B: Keep leaf bundles material-local

**Files:**

- Create: `scripts/workflows/shared/dispatch-prepared.mts`
- Create: `scripts/workflows/operations/prepare.mts`
- Create: `scripts/workflows/operations/catalogs/paper.mts`
- Create: `scripts/workflows/operations/catalogs/book.mts`
- Create: `scripts/workflows/operations/catalogs/talk.mts`
- Create: `scripts/workflows/operations/catalogs/translation.mts`
- Modify: `scripts/workflows/shared/dispatch.mts`
- Modify: `scripts/workflows/operations/catalog.mts`
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `tests/test_workflow_bundle_abi.py`

- [ ] Add one esbuild-metafile dependency test proving that a prepared-dispatch probe imports neither `operations/catalog.mts` nor any operation row, and one probe per leaf material proving that its preparer imports only Search plus that material's row modules. This is the executable independence boundary, not a snapshot of bundle text or byte size.

- [ ] Move `DispatchOutcome` and `dispatchPreparedOperation()` into `dispatch-prepared.mts`, which imports only host/result/artifact types and never imports a catalog. Keep the temporary compatibility `dispatchOperation()` in `dispatch.mts`; it alone may import the universal catalog until Task 13. Do not duplicate error mapping or add another receipt validator.

- [ ] Extract the row-parameterized preparation algorithm into `operations/prepare.mts`. Material-local catalog modules pass only their exact row sets: Paper = Search + Paper, Book = Search + Book, Talk = Talk, Translation = Translation. They use the generated factual operation identity projection and the same `defineOperation` path; they do not copy phase/effect/agent/artifact values or introduce hand-maintained stage sequences. A leaf plan imports its one material catalog and `dispatch-prepared.mts`, never `operations/catalog.mts` or `shared/dispatch.mts`.

- [ ] Keep the compatibility catalog as a thin aggregation over the same preparer and all rows so every existing caller remains runnable. Task 13 deletes that aggregation with `run-stage`; no named Workflow gains a universal resolver.

- [ ] Run, review the metafile evidence, and commit.

```bash
npm run check:workflows
python3 -m pytest tests/test_workflow_dispatch.py tests/test_workflow_bundle_abi.py tests/test_run_stage.py -q
git add scripts/workflows/shared/dispatch-prepared.mts scripts/workflows/shared/dispatch.mts scripts/workflows/operations/prepare.mts scripts/workflows/operations/catalog.mts scripts/workflows/operations/catalogs tests/test_workflow_dispatch.py tests/test_workflow_bundle_abi.py
git commit -m "refactor: isolate material operation dependencies"
```

### Task 6C: Split domain contracts and narrow the public result

**Files:**

- Create/Modify: `scripts/workflows/contracts/paper.mts`
- Create/Modify: `scripts/workflows/contracts/book.mts`
- Create/Modify: `scripts/workflows/contracts/talk.mts`
- Create/Modify: `scripts/workflows/contracts/translation.mts`
- Create/Modify: `scripts/workflows/contracts/topic.mts`
- Modify: `scripts/workflows/shared/material-input.mts`
- Modify: `scripts/workflows/shared/material-result.mts`
- Modify: `tests/test_material_result.py`
- Modify: `tests/test_workflow_bundle_abi.py`

- [ ] Move closed identities, kind-specific status facts, seed parsing, and gate/decision parsing into their owning domain contract modules. `material-input.mts` retains only genuine shared primitives: slug/language normalization where cross-kind, the UserDecision envelope, observation keys/maps, and small envelope helpers. Do not create a new framework or a barrel that makes every leaf import every domain contract.

- [ ] Give Paper and Book separate public entry parsers; a named entry imports only its own parser plus shared primitives. Delete the generic `parseLeafMaterialInput` export in this task and migrate its tests to those real parser seams; it has no production caller and must not survive as a temporary Paper/Book barrel. Preserve behavior while moving code; do not add field-permutation tests.

- [ ] Remove `receipts` from `MaterialResultBase` and its constructors. Plans keep validated current-run receipts only in local variables for carry, joining, and bounded repair; Skills and higher-order plans receive only material identity, terminal, issue/gate, exact artifacts, `next`, or Topic pending work. Add one public-result shape test plus one owner-drift case proving `material.canonical.slug` is the runtime vault slug while bibliographic identity remains separate, then delete receipt-shape assertions rather than replacing them with a compact trace that has no consumer.

- [ ] Use esbuild metafiles to bundle each real leaf seam (`public domain parser + shared result`) and prove Paper does not pull Book/Topic/Translation contracts and vice versa. Probing an isolated contract export is insufficient because it would miss an indirect shared-result barrel. Test this boundary once; do not snapshot source layout broadly.

- [ ] Run and commit.

```bash
npm run check:workflows
python3 -m pytest tests/test_material_result.py tests/test_workflow_dispatch.py tests/test_workflow_bundle_abi.py -q
git add scripts/workflows/contracts scripts/workflows/shared/material-input.mts scripts/workflows/shared/material-result.mts tests/test_material_result.py tests/test_workflow_bundle_abi.py
git commit -m "refactor: keep material contracts and results narrow"
```

### Task 7: Implement the Paper plan and entry

**Files:**

- Create: `scripts/workflows/plans/paper.mts`
- Create: `scripts/workflows/paper.entry.mts`
- Modify: `scripts/build-workflows.mjs`
- Create: `tests/test_material_plans.py`
- Create: `tests/test_workflow_entries.py`

- [ ] Add failing Paper tests for: a provisional `title|doi` seed running Search → Acquire → Prepare → Analyse → Audit; a strict canonical seed and existing canonical observation starting at Audit; Prepare `selected_input` carry; identity-conflict exact candidate/conflict echo and selected membership; same-kind selection performing one owner-reconcile Search under the copied host key; user-confirmed Paper→Book selection producing typed `next`; stale Search decision ignored after fresh facts advance; a resumed prepared-but-not-analysed Paper reconciling Prepare to rebuild `selected_input`; an existing canonical whose Audit requests Analyse repair reconciling Prepare first; writer unknown stop/no later dispatch; owner-correct Analyse repair followed by one re-Audit; foreign Audit path blocked.

- [ ] Implement:

```ts
export async function runPaperPlan(
  runtime: MaterialRuntime,
  input: PaperRunInput,
): Promise<MaterialResult>;
```

Choose the first applicable operation from explicit observed facts. A provisional seed always runs Search; a canonical seed skips Search only when its `material_slug` observation proves the canonical artifact admitted. A coherent Search receipt establishes the bibliographic identity, while the downstream runtime slug and observation lookup use a validated `local_owner.vault_slug` on an owner hit and `receipt.identity.slug` on a miss. Preserve identity slug and runtime owner slug as distinct facts; never rewrite one into the other. When the caller supplied a sparse observation for that runtime key, rebind to it with one in-memory `(kind,slug)` lookup and otherwise keep the explicit empty observation. Do not run a second status call inside the Workflow. Keep only the stamped receipts needed as current-run local carries; the first non-complete/unknown/incoherent outcome returns a material-level stop without copying receipts into the public result. Pass Prepare's validated `selected_input` directly into Analyse.

- [ ] Lift Search identity conflicts only through `parseIdentityConflictGate`. On resume, parse the exact echoed decision. A selected Paper is supplied once to a Search owner-reconciliation call under the same gate key, whose complete identity must equal the selection. A selected Book returns the typed `next` immediately; the caller starts Book with that identity and Book establishes its own owner. Invalid gate semantics stop as `workflow.incoherent_gate`; a stale/mismatched decision is not applied.

- [ ] Across-run receipts do not exist. If Analyse or an Audit repair needs a Prepare carry and Prepare did not complete in this invocation, dispatch `paper.prepare` in reconcile mode first and use its new validated `selected_input`; do not guess between durable normalized/OCR files. This is stage reconciliation, not a generic retry.

- [ ] Audit repair is bounded to one Analyse repair and one `pass:2` re-Audit. No generic loop or retry counter exists.

- [ ] Treat a complete result carrying `next:{kind:"book",...}` as a typed disposition, not a Paper artifact completion. The top-level Skill and both higher-order plans call `runBookPlan` (or `workflows/book.mjs` at the Skill boundary) with that identity and its exact available observation; they never duplicate the publication-type condition.

- [ ] Entry parsing accepts exactly `{seed,observation,options,userDecision?}` using the frozen provisional-or-canonical Paper seed contract (`material_slug` is explicit on canonical seeds) and calls `runPaperPlan`; it ignores no unknown routing keys. The Skill does not run Search first, and the plan never promotes narrow status identity into a full Search identity.

- [ ] Add `paper` to the build table. The generated `workflows/paper.mjs` exports only `meta` and ends in the host wrapper return.

- [ ] Build, test, and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_material_plans.py -k paper tests/test_workflow_entries.py -q
git add scripts/build-workflows.mjs scripts/workflows/plans/paper.mts scripts/workflows/paper.entry.mts workflows/paper.mjs tests/test_material_plans.py tests/test_workflow_entries.py
git commit -m "feat: run one paper per workflow"
```

### Task 8: Implement the Book plan with one owned chapter pipeline

**Files:**

- Create: `scripts/workflows/plans/book.mts`
- Create: `scripts/workflows/book.entry.mts`
- Modify: `scripts/build-workflows.mjs`
- Modify: `tests/test_material_plans.py`
- Modify: `tests/test_workflow_entries.py`

- [ ] Add failing Book tests for: a provisional `title|isbn` seed and happy path; same-kind identity-conflict selection performing one owner-reconcile Search; Book year gate with exact host-owned `material_key/current_identity/tmp_path/year_evidence/action` binding, single consumption, stale fresh facts, owner drift, `use-recommended-year` recanonicalization through Search, and unknown Search causing zero Acquire calls; Book structure gate before fan-out with exact key/source/candidate binding; Prepare inventory fan-out; valid-manifest resume without a current-run Prepare receipt; invalid/missing manifest reconciling Prepare; missing source reconciling Acquire before Prepare; stable manifest order under out-of-order completion; overlapping exact outputs rejected before any chapter dispatch; a two-chapter observation where only the actually present output binds `reconciled/not_written`; a new chapter binds `create/written`; mixed sibling success/blocked/unknown settles all and lets unknown dominate; Synthesise/Audit never start after a failed join; one owner-correct chapter or overview repair; and a chapter newly written in this run being repaired with `mode:"repair", output_exists:true` before re-Audit.

- [ ] Implement `runBookPlan(runtime,input)` using ordinary `await` for Search/Acquire/Prepare/Synthesise/Audit. For chapters:

```ts
const prepared = chapters.map((chapter, index) =>
  prepareOperation({
    kind: "book",
    operation: "chapter.analyse",
    slug,
    label: `${slug}:analyse:${chapter.slug}`,
    context: {
      ...base,
      chapter,
      output_exists: observedChapterOutputs.has(chapterOutputPath(slug, chapter)),
    },
  }),
);
assertDistinctWriteTargets(prepared);
const outcomes = await runtime.pipeline(
  prepared,
  (operation) => dispatchPreparedOperation(runtime, operation),
);
```

Define `observedChapterOutputs` only from disk testimony:

```ts
const observedChapterOutputs = new Set(
  initialObservation.facts.chapters
    .filter((chapter) => chapter.output.present)
    .map((chapter) => chapter.output.path),
);
```

Use the Prepare receipt's unique chapter inventory when Prepare completed in the current run. On resume, a valid status manifest supplies the same complete validated rows; an invalid/missing manifest requires `book.prepare` reconciliation, and a missing usable source first requires `book.acquire` reconciliation. Never derive `output_exists` from expected paths. If a new chapter unexpectedly finds an output, its Agent blocks; the plan stops for a fresh next-run status.

- [ ] Join in stable chapter order after every launched call settles. Unknown dominates blocked or failed siblings; otherwise the first non-complete outcome in manifest order controls the top-level terminal. Retain successful sibling receipts only in plan-local state long enough to establish same-run outputs; do not expose them in MaterialResult. Track chapter outputs established by coherent current-run completions; an Audit escalation for one of them invokes `chapter.analyse` with `mode:"repair"` and `output_exists:true`, then performs exactly one re-Audit.

- [ ] Consume only the frozen typed gates. `book.prepare` may return `book_structure` before any chapter dispatch. Validate its cross-field semantics with `parseBookStructureGate` before lifting it to the user, validate the echoed decision with `parseBookStructureDecisionValue` on resume, and stop explicitly as an incoherent gate rather than exposing invalid alternatives. Chapter Analyse has no human gate; after every launched child settles, unknown dominates blocked/failed siblings, otherwise the first manifest-order non-complete receipt controls the stop. Parse the outer Book-year envelope/value structurally at entry without sending it to an ordinary Search. After current identity and resolver-confirmed runtime slug are known and fresh facts have not made it stale, compare its copied gate `material_key`, operation, and current identity exactly once. `accept-current` invokes Acquire directly with unchanged identity. `use-recommended-year` invokes one readonly Search under the old owner key; any stop prevents Acquire. On coherent Search completion, take the full identity from the receipt, choose the new runtime key only from `local_owner.vault_slug` or `receipt.identity.slug`, and pass the already-validated value internally to Acquire without calling `decisionForOperation()` again. Neither plan nor Skill computes/replaces a slug. Recovery persists no partial Search result: a later run re-observes and may receive the same outer decision.

- [ ] Add `book` to the build table and verify its generated public file has only `meta` plus the top-level wrapper.

- [ ] Build, test, and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_material_plans.py -k book tests/test_workflow_entries.py -q
git add scripts/build-workflows.mjs scripts/workflows/plans/book.mts scripts/workflows/book.entry.mts workflows/book.mjs tests/test_material_plans.py tests/test_workflow_entries.py
git commit -m "feat: run one book per workflow"
```

### Task 9: Implement Talk and Translation plans

**Files:**

- Create: `scripts/workflows/plans/talk.mts`
- Create: `scripts/workflows/plans/translation.mts`
- Create: `scripts/workflows/talk.entry.mts`
- Create: `scripts/workflows/translation.entry.mts`
- Modify: `scripts/build-workflows.mjs`
- Modify: `tests/test_material_plans.py`
- Modify: `tests/test_workflow_entries.py`

- [ ] Add failing Talk tests for `live` Prepare → Analyse → Audit, `dead|empty` Prepare-owned canonical → Audit, a resumed transcript-without-canonical run reconciling Prepare to recover classification and exact transcript refs, existing canonical starting at Audit, live Audit repair reconciling Prepare before Analyse when no current-run carry exists, dead/empty Prepare repair, and unknown writer stop. Talk has no real human gate in the current domain; do not invent one merely for terminal symmetry.

- [ ] Implement `runTalkPlan()` with only the receipt-defined classification branch. Use the Prepare receipt's exact same-generation transcript refs for live Analyse. Because status contains facts rather than a past receipt, a resumed run that needs classification/transcript carry reconciles `talk.prepare` first. Audit escalation routes only to the owner of its exact path and is bounded to one repair/re-Audit.

- [ ] Add failing Translation tests for target normalization parity, exact target reconcile, missing source gate, different-target observation ignored, exact candidate-fingerprint plus selected-path decision binding, stale source decision ignored after the requested PDF and manifest are both present, a configuration gate carrying the exact material key but rejecting any acknowledgement decision, and unknown writer stop.

- [ ] Implement `runTranslationPlan()` as one `translation.prepare` dispatch with no Audit. `translation_source` resumes with its exact fingerprint/path decision. `translation_configuration` is satisfied only by changing Configure/env out of band and restarting the same seed with fresh status; the material key is display/ownership data, not an acknowledgement token. Version 0.1 is Paper-derived only and uses the exact key `translation:paper:${slug}:${normalizedTag}`; do not add a configurable source kind.

- [ ] Add both entries to the build table and verify both generated bundles execute through the host wrapper.

- [ ] Build, test, and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_material_plans.py -k 'talk or translation' tests/test_workflow_entries.py tests/test_status_cli.py -q
git add scripts/build-workflows.mjs scripts/workflows/plans/{talk,translation}.mts scripts/workflows/{talk,translation}.entry.mts workflows/{talk,translation}.mjs tests/test_material_plans.py tests/test_workflow_entries.py
git commit -m "feat: add talk and translation workflows"
```

### Task 10: Cut the leaf material Skill over to named entries

**Files:**

- Modify: `skills/collect-material/SKILL.md`
- Modify: `skills/collect-material/references/talk.md`
- Modify: `tests/test_skill_orchestration.py`
- Modify: `tests/test_dead_names.py`
- Create: `docs/evals/material-skill-scenarios.md`

- [ ] Add only structural cross-file tests that parse valid Skill frontmatter, resolve each referenced named entry to a generated file, and reject active references to `run-stage`, public `stage`, `until`, or `units` after the relevant branch migrates. Do not snapshot sentences or try to prove execution order by grepping prose.

- [ ] Rewrite the leaf portion of `collect-material` to the required thin shape: recognize the requested kind, assign/reuse the request key, pass raw hints in the provisional seed, coalesce known keys, make one pre-run observation, invoke the fixed entry, follow generic typed `next`, present material-level terminals, and make one post-complete observation at `material.canonical.slug` (the runtime owner slug). Strict hint/identity/owner validation belongs only to the TypeScript entry parser; malformed input may launch the Workflow wrapper but must cause zero Agent dispatch. Retain a valid caller request key when present; otherwise assign `request-{kind}-{one-based original input ordinal}` for this invocation, and reuse `material.requested.slug` byte-for-byte on a gate resume. The Skill never runs Search itself, treats that provisional key as canonical, pads a narrow status identity, or rewrites a canonical slug/year. Keep Author compatibility prose only until Task 11. A Paper→Book route selects the Book entry by route kind; the Skill does not contain the publication-type condition.

- [ ] Every named Workflow invocation carries exactly one observation matching its seed's `requested_slug` or `material_slug`. Before following a typed Paper→Book `next`, run one exact `quasi-status --kind book --slug <next.identity.slug> --json`, construct the initial canonical Book seed with `material_slug:next.identity.slug`, and pass that Book observation. The Paper observation is never reused for the target route; the Book plan may still run Search when that exact canonical artifact is not admitted and may then rebind to a resolver-confirmed owner slug.

- [ ] Rewrite `references/talk.md` around `workflows/talk.mjs`; remove stage selection and receipt interpretation from the Skill.

- [ ] Keep top-level bounded concurrency at five distinct known material keys. Coalesce only exact keys known before launch. Do not add semantic locks, canonicalization reservations, collision recovery, or cleanup automation; a rare post-Search collision is left visible for manual cleanup.

- [ ] For each decision-resumed Stage gate (`identity_conflict`, `book_year`, `book_structure`, `translation_source`), construct `UserDecision` by copying `gate.material_key` and `gate.operation` byte-for-byte. Never derive a decision key from canonical identity, child route, or diagnostic data; MaterialResult exposes no Stage receipts. For `translation_configuration`, present the missing Configure fields and restart the same seed with fresh observation after configuration changes, with no decision object.

- [ ] Document four manual/headless consumer scenarios in `docs/evals/material-skill-scenarios.md`: one ordinary leaf completion with pre/post status, one gate with a fresh-observation resume copying its exact material key, a two-material batch preserving order, and a malformed intake returning `material.invalid_input` with zero Agent dispatch. Record commands/evidence when these scenarios are run; keep them outside the deterministic unit suite.

- [ ] Run and commit.

```bash
python3 -m pytest tests/test_skill_orchestration.py tests/test_dead_names.py tests/test_status_cli.py -q
git add skills/collect-material docs/evals/material-skill-scenarios.md tests/test_skill_orchestration.py tests/test_dead_names.py
git commit -m "refactor: make leaf material skill a thin workflow driver"
```

### Task 11A: Freeze the Author composition contract

**Files:**

- Create: `docs/superpowers/specs/2026-08-04-author-workflow-composition.md`

- [ ] Write the focused spec before implementation. Resolve these decisions explicitly: Author has its own exact `quasi-status --kind author` pre/post observation; input carries a sparse map of exact child observations accumulated only after a concrete route is known; `author.resolve-membership` is the only dynamic membership observer; a discovered child absent from that map is treated as new for this run and relies on leaf writer reconciliation; if continuation actually requires disk testimony, Author returns `blocked` with one typed `observation_request`; the Skill observes only that child and restarts Author; user-facing child gates are lifted unchanged with the exact child route; a child decision is forwarded only when its material key matches that route; there is no whole-vault inventory or Author cursor; child plans run sequentially in stable membership order.

- [ ] Specify generic child routing: if a Paper child returns the typed Book `next`, Author calls `runBookPlan` with the returned identity and matching sparse observation. It does not reproduce the publication-type test. Completed children are keyed/coalesced by `result.material.canonical.slug`, the runtime owner slug, never by a stale bibliographic slug. Specify Author synthesis/Audit ownership and the one bounded owner-correct repair/re-Audit.

- [ ] Obtain a fresh design review of this focused spec and resolve every blocking finding before implementation. Commit the reviewed contract separately.

```bash
git add docs/superpowers/specs/2026-08-04-author-workflow-composition.md
git commit -m "docs: specify author workflow composition"
```

### Task 11B: Implement the Author composition entry

**Files:**

- Create: `scripts/workflows/plans/author.mts`
- Create: `scripts/workflows/author.entry.mts`
- Create: `scripts/workflows/operations/catalogs/author.mts`
- Modify: `scripts/build-workflows.mjs`
- Modify: `skills/collect-material/SKILL.md`
- Modify: `tests/test_material_plans.py`
- Modify: `tests/test_workflow_entries.py`
- Modify: `tests/test_skill_orchestration.py`

- [ ] Add failing Author tests for exact pre-run facts, discovery/membership order, one Book and one Paper composed through their public plan APIs, Paper→Book child routing, existing admitted child reuse, decision delivery only to the matching child, lifted child gate, one exact observation-request/resume, Synthesise/Audit, one Author synthesis repair, no child dispatch after unknown outcome, and exact Author post-complete status evidence.

- [ ] Implement:

```ts
export async function runAuthorPlan(
  runtime: MaterialRuntime,
  input: AuthorRunInput,
): Promise<MaterialResult>;
```

Run `author.discover-books`, `author.discover-papers`, and `author.resolve-membership` in explicit sequence. Coalesce the returned membership by canonical material key. For each member, call `runBookPlan` or `runPaperPlan` with its matching sparse observation or the explicit empty observation constructor. Admit only leaf completions with `next:null`, and record their `material.canonical.slug` as the owner-correct child route; follow a typed Book route through `runBookPlan`. A lifted gate includes the child route; it does not expose Stage ordering to the Skill. A child stop that needs disk testimony carries exactly that child's observation request; it does not trigger a vault scan.

- [ ] After all children complete, call `author.synthesise` then `author.audit`; allow one owner-correct synthesis repair and re-Audit. Paper/Book plans must not import Author code.

- [ ] Prepare Author-owned operations through its material-local catalog and the pure prepared-dispatch boundary. The Author bundle composes Paper/Book plan APIs but never imports the universal compatibility catalog.

- [ ] Switch Author routing in `collect-material` to `workflows/author.mjs`. Start with the exact Author observation and an empty sparse child-observation map; on an `observation_request`, run the exact leaf status command, add its result, and restart. User gates require an answer plus a fresh exact child observation. After `complete`, verify the exact Author canonical fact once.

- [ ] Add `author` to the build table only when its plan and parser are complete.

- [ ] Build, test, and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_material_plans.py -k author tests/test_workflow_entries.py tests/test_skill_orchestration.py tests/test_status_cli.py -q
git add scripts/build-workflows.mjs scripts/workflows/operations/catalogs/author.mts scripts/workflows/plans/author.mts scripts/workflows/author.entry.mts workflows/author.mjs skills/collect-material/SKILL.md tests
git commit -m "feat: compose leaf workflows for authors"
```

### Task 12A: Freeze the Topic composition contract

**Files:**

- Create: `docs/superpowers/specs/2026-08-04-topic-workflow-composition.md`

- [ ] Write the focused spec before implementation. Resolve these decisions explicitly: Topic receives query/options, exact Topic status facts, `seed_materials`, and a sparse map of already-requested exact child observations; it owns one Recall, outline create/refresh, bounded rounds, sequential child leaf plans and webcards, overview/resources synthesis, three exact audits, and one owner-correct repair/re-Audit; user-editable outline is the durable research state; `topic.steer` rereads it on every run; there is no whole-vault inventory or hidden cursor; child observation requests and gates are lifted with the exact route and the whole Topic restarts after the requested exact status call.

- [ ] Preserve the current real stopping behavior: noncanonical seeds at `maxRounds==0` produce one typed seed gate; `signal:"needs_seeds"` is a typed gate; no admitted member or available card cannot silently complete; `signal:"saturated"` is the only saturation claim; hitting `maxRounds` with unseen work returns an incomplete report carrying that work, not saturation. `seed_materials` remain part of the public input.

- [ ] Define resume data without a sidecar: the exact Topic status projection supplies the current validated outline's subquestions plus observed member/card refs; `topic.steer` receives those refs and returns its newly written subquestions in the current receipt. Every candidate demand carries a validated deterministic `requested_slug`; the plan never fabricates a slug from the query. A Paper child `next` is followed generically through the Book plan. Completed children are admitted under `result.material.canonical.slug`, the runtime owner slug. A child decision is forwarded only to the exact matching route.

- [ ] Close the existing Talk path: a canonical Talk seed/recalled member is admitted from exact Talk status; an incomplete Talk with usable media is passed to `runTalkPlan`; an explicit Talk seed with neither canonical output nor usable media is included in the typed `topic_seed` gate. Topic never invents media identity for a recalled slug.

- [ ] Specify owner mapping exactly: outline → `topic.steer`, overview → `topic.synthesise.overview`, resources → `topic.synthesise.resources`; each of the three paths has its own exact Audit call and at most one owner repair/re-Audit. Obtain a fresh design review and resolve every blocking finding before implementation. Commit the reviewed contract separately.

```bash
git add docs/superpowers/specs/2026-08-04-topic-workflow-composition.md
git commit -m "docs: specify topic workflow composition"
```

### Task 12B: Implement the Topic entry

**Files:**

- Modify: `scripts/workflows/operations/rows/topic.mts`
- Create: `scripts/workflows/operations/catalogs/topic.mts`
- Create: `scripts/workflows/plans/topic.mts`
- Create: `scripts/workflows/topic.entry.mts`
- Modify: `scripts/build-workflows.mjs`
- Modify: `skills/research-topic/SKILL.md`
- Modify: `tests/test_material_plans.py`
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `tests/test_workflow_entries.py`
- Modify: `tests/test_skill_orchestration.py`
- Modify: `tests/test_status_cli.py`

- [ ] First add failing row tests that make `requested_slug` required on each `candidate_demands` row and include it in the closed receipt. The plan uses that exact slug for the child route; no query-to-slug helper exists.

- [ ] Add failing Topic plan tests for exact Topic pre-run facts, ordinary bounded path, `seed_materials`, `maxRounds==0` noncanonical-seed gate, `needs_seeds`, no-evidence seed gate, hard-bound-with-unseen-work `terminal:"incomplete"` plus exact pending rows, one Paper child, one Book child, Paper→Book routing, canonical Talk admission, incomplete Talk with media, Talk-without-media seed gate, one webcard, resume reconstruction from the Topic status projection, decision delivery only to the matching child, lifted child gate, overview/resources synthesis, three exact audit targets, owner-correct repair, unknown outcome preventing later writes, and exact post-complete status evidence.

- [ ] Implement `runTopicPlan(runtime,input)` by reusing existing `topic.*` rows and leaf APIs. Keep configured `maxRounds` as the only loop bound. Process children and cards in stable order with ordinary `await`; do not add a Topic fan-out scheduler.

- [ ] Prepare Topic-owned operations through its material-local catalog and the pure prepared-dispatch boundary. The Topic bundle composes leaf plan APIs but never imports the universal compatibility catalog.

- [ ] Rewrite `research-topic/SKILL.md` to intake/query/options, exact Topic pre-status, fixed `workflows/topic.mjs` call, exact-child observation fulfillment, typed gate presentation, exact Topic post-status, and result reporting. Present `terminal:"incomplete"` with its exact pending work and never label it saturated. Remove public stage vocabulary, scan-as-inventory, and receipt interpretation.

- [ ] Add `topic` to the build table only when its plan and parser are complete.

- [ ] Build, test, and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_material_plans.py -k topic tests/test_workflow_dispatch.py tests/test_workflow_entries.py tests/test_skill_orchestration.py tests/test_status_cli.py -q
git add scripts/build-workflows.mjs scripts/workflows/operations/rows/topic.mts scripts/workflows/operations/catalogs/topic.mts scripts/workflows/plans/topic.mts scripts/workflows/topic.entry.mts workflows/topic.mjs skills/research-topic/SKILL.md tests
git commit -m "feat: move topic orchestration into a named workflow"
```

### Task 13: Retire the universal mode engine and narrow the schema catalog

**Files:**

- Delete: `scripts/workflows/run-stage.entry.mts`
- Delete: `workflows/run-stage.mjs`
- Delete: `scripts/workflows/shared/dispatch.mts`
- Delete: `scripts/workflows/operations/catalog.mts`
- Modify: `scripts/build-workflows.mjs`
- Modify: `scripts/schemas/pipeline.py`
- Modify: `scripts/schemas/export_contracts.py`
- Modify: `scripts/status/status.py`
- Modify: `scripts/workflows/artifact-contracts/generated.mjs` (generated)
- Modify: `scripts/workflows/artifact-contracts/generated.d.mts` (generated)
- Delete: `tests/test_run_stage.py`
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `tests/test_workflow_bundle_abi.py`
- Modify: `tests/test_material_plans.py`
- Modify: `tests/test_skill_orchestration.py`
- Modify: `tests/test_status_cli.py`

- [ ] Prove the deletion gate before editing:

```bash
! rg -n 'workflows/run-stage\.mjs|RUN_STAGE_REGISTRY|STAGE_CHAINS|"until"|"units"' skills
```

The command must have no active Skill hits.

- [ ] Move every ledger invariant to passing replacement tests. Delete `test_run_stage.py` only after the ledger contains no unmigrated load-bearing row.

- [ ] Remove sequencing, chain, carry, and public mode registry data from `pipeline.py`. Retain only this shape (with one row for every existing operation and its real templates):

```py
OPERATION_CATALOG = {
    "material.search": {
        "kinds": ["paper", "book"],
        "phase": "Search",
        "effect": "readonly",
        "agent": "quasi:metadata-agent",
        "artifacts": {},
    },
    "paper.acquire": {
        "kinds": ["paper"],
        "phase": "Acquire",
        "effect": "writer",
        "agent": "quasi:download-agent",
        "artifacts": {"output": "sources/{slug}.pdf"},
    },
    # ...all remaining stable operation keys, with facts only.
}
```

There are no stage aliases, per-kind sequences, carries, next-operation pointers, or chains. Generated TypeScript exposes `OperationDefinition` and `OperationName`, not `StageName`, `PipelineCarry`, or `KindDefinition.chain`. Status looks up a stable operation key plus artifact role only for path templates; plans call that same catalog through typed operation literals, with no second declaration list.

- [ ] Update `status.py` to read the narrowed evidence catalog while continuing to compute facts with its explicit Python observers. Status must not become a rule-DSL graph interpreter.

- [ ] Remove `run-stage` from the build table and delete its source/generated entry together with the compatibility-only universal catalog and `dispatchOperation()` wrapper. Named plans retain the row-parameterized preparer, their material-local catalogs, and pure `dispatchPreparedOperation()`. Remove only mode-specific tests and compatibility errors; retain migrated dispatch/plan behavior. Add the retired name to quarantine only in Task 14 after maintained documents stop referring to it, so the quarantine test and its own literal do not make this commit self-failing.

- [ ] Delete `validateCompatibilityEntry`, `validatePipelineStructure`, compatibility typedefs/probes, and all `PIPELINE/RUN_STAGE_REGISTRY/STAGE_CHAINS` build validation that existed only for `run-stage` from `scripts/build-workflows.mjs`. Retain the fixed-kind `validateMaterialEntry` and public ABI/size checks.

- [ ] Replace the compatibility-only ABI regression with a parameterized execution test over `paper.mjs`, `book.mjs`, `talk.mjs`, `translation.mjs`, `author.mjs`, and `topic.mjs`. Each generated bundle must execute its internal `run` through the public top-level wrapper and return the source result. The test contains no retired `run-stage` reference.

- [ ] Rebuild, run the static retirement gate, and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_workflow_dispatch.py tests/test_workflow_bundle_abi.py tests/test_material_plans.py tests/test_workflow_entries.py tests/test_status_cli.py tests/test_skill_orchestration.py -q
test ! -e scripts/workflows/run-stage.entry.mts
test ! -e workflows/run-stage.mjs
! rg -n 'workflows/run-stage\.mjs|RUN_STAGE_REGISTRY|STAGE_CHAINS|validateCompatibilityEntry|validatePipelineStructure|quasi\.run-stage\.(chain|batch|error)' scripts/build-workflows.mjs skills scripts/workflows workflows tests --glob '!test_dead_names.py'
git add scripts/build-workflows.mjs
git add -A scripts/workflows scripts/schemas scripts/status workflows tests
git commit -m "refactor: retire the generic run-stage workflow"
```

The Task 13 `rg` must have no runtime or test matches. Root maintainer documents intentionally move in Task 14, where the final active-contract gate runs after their update; historical changelog/spec text stays outside that gate.

### Task 14: Update maintained contracts and run the completion audit

**Files:**

- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/SKILL_ORCHESTRATION.md`
- Modify: `docs/GRAPH_COLLABORATION.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-08-04-material-workflow-refactor-design.md`
- Modify: `tests/test_dead_names.py`

- [ ] Update the layer/runtime contracts to named Workflows, explicit plans, shared dispatch, target-aware Translation status, Author/Topic one-way composition, and Book-only internal `pipeline()`.

- [ ] Mark the design implemented and append a newest-first changelog entry explaining why generic modes and Skill-owned stage logic were removed. Do not rewrite historical changelog mentions.

- [ ] Add the retired public `run-stage` names to `tests/test_dead_names.py` only now, with its existing active-code/document scope. Run the test after all maintained contracts are updated; the quarantine file's own literals remain outside its scan.

- [ ] Copy the final maintainer guide change so the two root instruction files are byte-identical, then verify:

```bash
cmp -s CLAUDE.md AGENTS.md
! rg -n 'workflows/run-stage\.mjs|RUN_STAGE_REGISTRY|STAGE_CHAINS|quasi\.run-stage\.(chain|batch|error)' AGENTS.md CLAUDE.md docs/ARCHITECTURE.md docs/GRAPH_COLLABORATION.md docs/SKILL_ORCHESTRATION.md
python3 -m pytest tests/test_dead_names.py -q
```

- [ ] Run the complete workflow and repository audit:

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest -q
cmp -s CLAUDE.md AGENTS.md
git diff --check
git status --short
```

- [ ] Inspect every guard/fallback/retry/compatibility branch changed in this refactor and record its evidence in the implementation plan's completion notes. Remove any branch without a documented host contract, reachable state, active caller, or reproduced regression.

- [ ] Commit maintained contracts.

```bash
git add AGENTS.md CLAUDE.md docs skills workflows scripts tests
git commit -m "docs: document material-oriented workflow architecture"
```

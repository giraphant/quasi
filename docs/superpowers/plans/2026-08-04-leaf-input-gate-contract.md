# Leaf Input and Gate Contract Correction Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the leaf Workflow input, identity-owner, and human-gate contracts before Paper and Book plans are implemented, so a named Workflow can start from raw user hints, surface only real business decisions, and resume without guessing identity, paths, or prior receipts.

**Architecture:** A leaf invocation carries an explicit provisional-or-canonical seed plus one factual `quasi.status/0.2` observation. Search alone promotes a provisional seed to a full canonical identity and owns any year-driven canonical slug change. Operation schemas opt in to `needs_input` only by defining an operation-specific `terminalPayloads.needs_input`; the global Stage status vocabulary remains the same four values. The only leaf gates are identity conflict, Book year, Book chapter structure, and Translation source/configuration. No generic specialist question, hidden cursor, retry loop, lock, or slug rewrite is introduced.

**Tech Stack:** TypeScript 5.9, esbuild, Claude Code Dynamic Workflows, pytest, generated JSON Schema projections.

## Global Constraints

- Keep `PaperIdentity` and `BookIdentity` strict. A provisional intake is a different type, never a partial canonical identity.
- The status protocol's narrow disk identity is factual testimony, not a value to pad into a Search identity.
- A runtime material slug comes only from a canonical seed's explicit `material_slug`, a validated status owner, or a coherent `material.search` receipt. Skills and plans never derive a canonical slug or replace a year suffix. A provisional request key is not a canonical claim.
- `local_owner:null` is the sole Search miss. A non-null owner is a complete hit bound to the selected identity.
- A row without an evaluated `terminalPayloads.needs_input` branch cannot return `needs_input` through StructuredOutput. Do not add a second boolean capability flag.
- Preserve the global `complete|needs_input|blocked|failed` Stage vocabulary and `quasi.stage.receipt/0.3` version.
- Do not add a generic `specialist_question`, malformed-input Cartesian matrices, retries, locks, hidden state, fingerprints with no deterministic producer, or prose-snapshot tests.
- Rebuild generated Workflow files; never hand-edit them. Keep `CLAUDE.md` and `AGENTS.md` byte-for-byte identical.

---

### Task 1: Separate provisional leaf intake from canonical identity

**Files:**

- Modify: `scripts/workflows/shared/material-input.mts`
- Modify: `tests/test_material_result.py`

- [ ] Add failing behavior tests for one minimal Paper seed (`title` or `doi`), one minimal Book seed (`title` or `isbn`), a strict canonical seed, a provisional observation whose slug does not match `requested_slug`, a canonical observation whose slug does not match `material_slug`, and one valid owner-drift seed where `material_slug !== identity.slug`. Keep the existing full identity rejection tests; do not turn them into a field-by-field matrix.

- [ ] Define closed intake types and the public leaf envelope:

```ts
export interface PaperIntake {
  title?: string;
  doi?: string;
  authors?: string[];
  year?: number;
  journal?: string;
  oa_url?: string;
  url?: string;
}

export interface BookIntake {
  title?: string;
  isbn?: string;
  authors?: string[];
  year?: number;
  publisher?: string;
  category?: BookIdentity["category"];
}

export type LeafSeed<TIntake, TIdentity> =
  | { state: "provisional"; requested_slug: string; hints: TIntake }
  | { state: "canonical"; material_slug: string; identity: TIdentity };
```

Paper hints require at least one of `title|doi`; Book hints require at least one of `title|isbn`. Optional values are validated only when present. The Skill owns the provisional key: retain a valid caller key when one exists; otherwise use `request-{kind}-{one-based original input ordinal}` for this request. A gate resume reuses `material.requested.slug` from the prior result byte-for-byte. This key is only a label and pre-Search observation key; a provisional seed always runs Search and the key never participates in canonical slug derivation.

- [ ] Change the leaf parser input to exact `{seed,observation,options,userDecision?}`. A provisional observation binds to `requested_slug`; a canonical observation binds to `material_slug`, which may differ from `identity.slug` only when exact owner testimony established slug drift. Unknown top-level and seed keys reject before dispatch. Keep `parsePaperIdentity()` and `parseBookIdentity()` unchanged for Search receipts, candidates, canonical seeds, and typed `next` routes.

- [ ] Keep `QuasiStatusObservation.identity` as the narrow factual v0.2 projection. Do not cast it to `PaperIdentity|BookIdentity` or manufacture missing `confidence`, URL, venue, or publisher fields.

- [ ] Run and commit.

```bash
npm run check:workflows
python3 -m pytest tests/test_material_result.py -q
git add scripts/workflows/shared/material-input.mts tests/test_material_result.py
git commit -m "refactor: distinguish leaf intake from canonical identity"
```

### Task 2: Bind Search completion to one selected identity owner

**Files:**

- Modify: `scripts/workflows/operations/rows/search.mts`
- Modify: `agents/metadata-agent.md`
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `workflows/run-stage.mjs` (generated)

- [ ] Add failing Search completion tests for: `local_owner:null` as the only miss; a hit whose `identity_slug` differs from `receipt.identity.slug`; a hit with a null `vault_slug`, path, or match; and a valid slug-drift hit whose exact vault path is derived from `vault_slug`. These four cases protect one write-routing boundary, not a general malformed-object matrix.

- [ ] Close `localOwnerSchema`: non-null rows require non-null `identity_slug`, `vault_slug`, `path`, and `match`. Remove the object-with-null-fields miss representation.

- [ ] Make the owning completion predicate prove `owner.identity_slug === receipt.identity.slug`; allow `owner.vault_slug !== owner.identity_slug` because resolver-confirmed slug drift is the purpose of the owner result. Derive the exact Paper/Book canonical path from `vault_slug`.

- [ ] Update the metadata Agent contract to return JSON `null` for a miss and a complete exact hit otherwise. Do not add method counts or a prose-sentence assertion.

- [ ] Build, test, and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_workflow_dispatch.py tests/test_run_stage.py tests/test_skill_orchestration.py -q
git add scripts/workflows/operations/rows/search.mts agents/metadata-agent.md tests/test_workflow_dispatch.py workflows/run-stage.mjs
git commit -m "fix: bind material search owner to selected identity"
```

### Task 3: Make human gates explicit and operation-specific

**Files:**

- Modify: `scripts/workflows/stage.mts`
- Modify: `scripts/workflows/operations/define.mts`
- Modify: `scripts/workflows/operations/rows/book.mts`
- Modify: `scripts/workflows/operations/rows/translation.mts`
- Modify: `scripts/workflows/operations/rows/topic.mts`
- Modify: `scripts/workflows/shared/material-input.mts`
- Modify: `scripts/workflows/shared/material-result.mts`
- Modify: `agents/extract-agent.md`
- Modify: `agents/analyse-agent.md`
- Modify: `agents/transcribe-agent.md`
- Modify: `agents/translate-agent.md`
- Modify: `agents/webcard-agent.md`
- Modify: `tests/test_run_stage.py`
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `tests/test_material_result.py`
- Modify: `workflows/run-stage.mjs` (generated)

- [ ] Add a failing catalog-derived set-equality test proving that the shared Stage vocabulary still names four statuses while exactly `material.search`, `book.acquire`, `book.prepare`, and `translation.prepare` expose a `needs_input` StructuredOutput branch. Representative negative checks include Paper Acquire/Prepare/Analyse/Audit, Chapter Analyse, Book Synthesise/Audit, Talk Prepare/Analyse/Audit, Topic Recall/Webcard, and Author operations; do not snapshot every schema branch.

- [ ] Derive the operation terminal branches from evaluated `terminalPayloads`; do not add `supportsNeedsInput`. The generic protocol test may explicitly supply an empty `needs_input` payload to exercise all four statuses.

- [ ] Add the concrete Book structure contract:

```ts
export interface BookStructureCandidate {
  key: string;
  label: string;
  summary: string;
  chapter_count: number;
  chapters: Array<{
    title: string;
    start: number;
    end: number;
  }>;
}

export type BookStructureConflict =
  | "chapter_boundaries"
  | "reading_order"
  | "included_material";

export interface BookStructureDecisionValue {
  source_path: string;
  candidates: BookStructureCandidate[];
  conflicts: BookStructureConflict[];
  selected_candidate: BookStructureCandidate;
}
```

`book.prepare` alone uses issue code `book.chapter_structure_ambiguous` and returns exact `source_path`, 2–4 closed candidates, and one or more closed conflicts. Every candidate is a complete ordered PDF manual-split specification directly consumable by the existing `--chapters` capability, with `chapter_count === chapters.length` and valid non-overlapping ranges. Until another deterministic capability can execute an EPUB alternative, EPUB ambiguity does not produce this gate. The material gate is `{kind:"book_structure",operation:"book.prepare",question,source_path,candidates,conflicts}`. No synthetic fingerprint is added.

- [ ] Bind a Book structure decision to material key and operation through `UserDecision`, then to the current exact source path, the echoed complete candidate set/conflicts, and exact membership of `selected_candidate`. Pass its exact ordered chapter specification as inert request data to `book.prepare`. A valid current manifest makes the decision stale in the later Book plan; a different source path never consumes it.

- [ ] Move Translation's non-null source/configuration gate into `terminalPayloads.needs_input` and require it there; remove the nullable top-level gate escape hatch so `needs_input + gate:null` is schema-impossible. Update the Translation Agent output contract to place the typed gate in that terminal branch. Keep Search and Book Acquire's existing typed payloads.

- [ ] Narrow Agent method contracts: Paper Prepare and Chapter Analyse have no user decision; Talk Prepare, Topic Recall, and Webcard have no current typed Stage gate. They return `blocked` for unconfirmed ownership/outcomes and `failed` when their bounded capabilities cannot complete. Topic seed/needs-seeds remain plan-level typed gates. Book Prepare alone may ask the chapter-structure question. Do not test exact prose.

- [ ] Remove schema-invalid mock behavior: change the direct four-status dispatch test to use a synthetic prepared operation or real opt-in row for `needs_input`; change the Paper compatibility chain gate case to a valid `blocked|failed` Paper stop, and prove compatibility `needs_input` with Search or Book Acquire. The fake runtime must not make schema-impossible Paper Audit/Acquire receipts look supported.

- [ ] Build, test, and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_workflow_dispatch.py tests/test_material_result.py tests/test_run_stage.py tests/test_skill_orchestration.py -q
git add scripts/workflows/stage.mts scripts/workflows/operations/define.mts scripts/workflows/operations/rows/book.mts scripts/workflows/operations/rows/translation.mts scripts/workflows/operations/rows/topic.mts scripts/workflows/shared/material-input.mts scripts/workflows/shared/material-result.mts agents/extract-agent.md agents/analyse-agent.md agents/transcribe-agent.md agents/translate-agent.md agents/webcard-agent.md tests/test_run_stage.py tests/test_workflow_dispatch.py tests/test_material_result.py workflows/run-stage.mjs
git commit -m "refactor: expose only typed material gates"
```

### Task 4: Freeze Book year recanonicalization ownership

**Files:**

- Modify: `scripts/workflows/shared/material-input.mts`
- Modify: `scripts/workflows/shared/material-result.mts`
- Modify: `scripts/workflows/operations/rows/search.mts`
- Modify: `scripts/workflows/operations/rows/book.mts`
- Modify: `agents/metadata-agent.md`
- Modify: `agents/download-agent.md`
- Modify: `tests/test_material_result.py`
- Modify: `tests/test_run_stage.py`
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `workflows/run-stage.mjs` (generated)

- [ ] Add failing tests for a Book year gate/decision carrying exact `current_identity`; an `accept-current` decision bound to the current runtime material key and prior evidence; an owner-drift case where that key uses `material_slug` rather than `current_identity.slug`; a `use-recommended-year` decision rejected unless prior evidence is `MISMATCH` with a distinct non-null `recommended_year`; Search completion that fails to return the recommended year; and Acquire completion that tries to treat any truthy decision as sufficient.

- [ ] Add `current_identity: BookIdentity` to the `book_year` gate and `BookYearDecisionValue`. Require `year_evidence.slug_year === current_identity.year`. Preserve exact `tmp_path`, evidence, action, and identity across the user handoff.

- [ ] Delete the undocumented `batchAcceptYear|batch_accept_year` context, envelope, and completion bypass. Every accepted mismatch or ambiguity now requires the typed Book year decision.

- [ ] Define action-specific coherence:

  - `accept-current`: retain `current_identity`; Acquire validates the exact prior evidence against its year.
  - `use-recommended-year`: require exact prior `MISMATCH`; the Book plan will call `material.search` with `current_identity + decision`; Search must return `identity.year === recommended_year` and a canonical slug/owner established by the metadata Agent; Acquire then receives the recanonicalized identity plus the same exact temp/evidence/action.

The row predicates validate these relationships. The outer `UserDecision` value may be structurally parsed at entry, but the Book plan consumes it exactly once only after the current runtime slug is known, against `book:${material_slug}`. On an owner hit that is the resolver-confirmed `local_owner.vault_slug`, not the bibliographic `current_identity.slug`; `current_identity` binds only identity/year evidence. The plan then threads the already-validated `BookYearDecisionValue` internally through Search to Acquire after recanonicalization changes the runtime slug; it does not call `decisionForOperation()` again with the new key. Neither the Skill nor the plan computes a slug or rewrites its year suffix.

- [ ] Update the two Agent contracts to reflect ownership: download owns temp/evidence and acceptance; metadata Search owns canonical year/slug. Do not add a second year-normalization helper.

- [ ] Amend the main refactor plan's Task 7, Task 8, and Task 10 assumptions to consume the frozen seed/gate/year contract. In particular, Book chapter mixed outcomes are success/blocked/unknown; `book_structure` is the only Prepare/fan-out human gate, while Acquire may first return `book_year`. Search owner hits set the downstream runtime slug and observation lookup to `local_owner.vault_slug`; a miss uses `receipt.identity.slug`.

- [ ] Run the full contract verification and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_material_result.py tests/test_workflow_dispatch.py tests/test_run_stage.py tests/test_skill_orchestration.py tests/test_dead_names.py -q
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-leaf-contract-test-data python3 -m pytest -q
cmp -s CLAUDE.md AGENTS.md
git diff --check
git add scripts/workflows/shared/material-input.mts scripts/workflows/shared/material-result.mts scripts/workflows/operations/rows/search.mts scripts/workflows/operations/rows/book.mts agents/metadata-agent.md agents/download-agent.md tests/test_material_result.py tests/test_run_stage.py tests/test_workflow_dispatch.py workflows/run-stage.mjs docs/superpowers/plans/2026-08-04-material-workflow-refactor.md
git commit -m "fix: bind book year decisions to recanonicalization"
```

After Task 4, return to Task 7 of the material Workflow refactor. Do not add a separate runtime adapter or compatibility API.

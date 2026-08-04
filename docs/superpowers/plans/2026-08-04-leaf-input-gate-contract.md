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
- Every Stage-owned gate carries a host-owned `material_key` copied from the stamped Stage receipt. For gates resumed through `UserDecision`, Skills and higher-order plans copy that key byte-for-byte and never derive it from identity, material result, or child route. This applies to identity-conflict, Book-year, Book-structure, and Translation-source. Translation-configuration is the sole out-of-band configuration gate: after Configure changes, rerun the same seed with fresh status and no decision. Topic plan-level gates remain separately specified.
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
- Modify: `scripts/workflows/operations/rows/search.mts`
- Modify: `scripts/workflows/operations/rows/book.mts`
- Modify: `scripts/workflows/operations/rows/translation.mts`
- Modify: `scripts/workflows/operations/rows/topic.mts`
- Create: `scripts/workflows/contracts/search.mts`
- Create: `scripts/workflows/contracts/book.mts`
- Modify: `scripts/workflows/shared/material-result.mts`
- Modify: `agents/metadata-agent.md`
- Modify: `agents/extract-agent.md`
- Modify: `agents/analyse-agent.md`
- Modify: `agents/transcribe-agent.md`
- Modify: `agents/translate-agent.md`
- Modify: `agents/webcard-agent.md`
- Modify: `tests/test_run_stage.py`
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `tests/test_material_result.py`
- Modify: `workflows/run-stage.mjs` (generated)

- [ ] Add a failing catalog-derived set-equality test proving that the shared Stage vocabulary still names four statuses while exactly `material.search`, `book.acquire`, PDF-context `book.prepare`, and `translation.prepare` expose a `needs_input` StructuredOutput branch. Use an explicit PDF fixture for the positive `book.prepare` row and additionally prove that the same row has the branch for PDF but not EPUB. Representative negative checks include Paper Acquire/Prepare/Analyse/Audit, Chapter Analyse, Book Synthesise/Audit, Talk Prepare/Analyse/Audit, Topic Recall/Webcard, and Author operations; do not snapshot every schema branch.

- [ ] Derive the operation terminal branches from evaluated `terminalPayloads`; do not add `supportsNeedsInput`. The generic protocol test may explicitly supply an empty `needs_input` payload to exercise all four statuses.

- [ ] Freeze the identity-conflict handoff in `contracts/search.mts`:

```ts
export interface IdentityConflictDecisionValue {
  candidates: Array<
    | { kind: "paper"; identity: PaperIdentity }
    | { kind: "book"; identity: BookIdentity }
  >;
  conflicts: IdentityConflict[];
  selected_candidate: IdentityCandidate;
}
```

`parseIdentityConflictGate` accepts only `material.search/needs_input` with issue code `material.identity_conflict`, binds the stamped `material_key`, validates the closed conflict set and candidate kinds for the requested kind, and returns the Material gate. `parseIdentityConflictDecisionValue` requires exact candidates/conflicts echo and exact membership of `selected_candidate`. A same-kind selection is passed once to an owner-reconcile Search under the same host key; the Search complete identity must equal the selection before normal Task 2 owner proof. A Paper→Book selection produces typed `next` and lets the Book plan establish its own owner. Do not add a fingerprint or generic gate parser.

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

- [ ] Add pure typed `parseBookStructureGate` and `parseBookStructureDecisionValue` validators in the Book-owned `contracts/book.mts`; do not add more Book business parsing to the shared `material-input.mts`. They prove 2–4 unique candidate keys, `chapter_count === chapters.length`, `1 <= start <= end`, strict ordered non-overlap, non-empty unique closed conflicts, exact echoed source/candidates/conflicts, exact membership of `selected_candidate`, and that the lifted gate's `material_key` equals the stamped receipt key. JSON Schema proves the closed basic shape only; these parsers own the cross-field semantics and must neither discover paths nor create a second generic receipt validator.

- [ ] Add `material_key` to the MaterialResult forms of `identity_conflict`, `book_structure`, `book_year`, and both Translation gates. Plans lift it only from `receipt.material_key`; Skills and higher-order plans copy it into `UserDecision` only for the decision-resumed gates, without reading receipts or deriving a key. Bind a Book structure decision to that key and operation, then to the current exact source path, the echoed complete candidate set/conflicts, and exact membership of `selected_candidate`. Pass its exact ordered chapter specification as inert request data to `book.prepare`. The Book plan must call the same semantic parser before lifting a Stage gate and again on resume; an invalid gate is an explicit incoherent-gate stop and is never shown as a user choice. A valid current manifest makes the decision stale in the later Book plan; a different source path never consumes it.

- [ ] Move Translation's non-null source/configuration gate into `terminalPayloads.needs_input` and require it there; remove the nullable top-level gate escape hatch so `needs_input + gate:null` is schema-impossible. Update the Translation Agent output contract to place the typed gate in that terminal branch. `translation_source` alone has the existing closed fingerprint/path decision; `translation_configuration` names missing Configure fields, carries `material_key` for ownership, and resumes only after out-of-band configuration plus fresh observation, with no acknowledgement decision. Keep Search and Book Acquire's existing typed payloads.

- [ ] Narrow Agent method contracts: Paper Prepare and Chapter Analyse have no user decision; Talk Prepare, Topic Recall, and Webcard have no current typed Stage gate. They return `blocked` for unconfirmed ownership/outcomes and `failed` when their bounded capabilities cannot complete. Topic seed/needs-seeds remain plan-level typed gates. Book Prepare alone may ask the chapter-structure question. Do not test exact prose.

- [ ] Remove schema-invalid mock behavior: change the direct four-status dispatch test to use a synthetic prepared operation or real opt-in row for `needs_input`; change the Paper compatibility chain gate case to a valid `blocked|failed` Paper stop, and prove compatibility `needs_input` with Search or Book Acquire. The fake runtime must not make schema-impossible Paper Audit/Acquire receipts look supported.

- [ ] Build, test, and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_workflow_dispatch.py tests/test_material_result.py tests/test_run_stage.py tests/test_skill_orchestration.py -q
git add scripts/workflows/stage.mts scripts/workflows/operations/define.mts scripts/workflows/operations/rows/search.mts scripts/workflows/operations/rows/book.mts scripts/workflows/operations/rows/translation.mts scripts/workflows/operations/rows/topic.mts scripts/workflows/contracts/search.mts scripts/workflows/contracts/book.mts scripts/workflows/shared/material-result.mts agents/metadata-agent.md agents/extract-agent.md agents/analyse-agent.md agents/transcribe-agent.md agents/translate-agent.md agents/webcard-agent.md tests/test_run_stage.py tests/test_workflow_dispatch.py tests/test_material_result.py workflows/run-stage.mjs
git commit -m "refactor: expose only typed material gates"
```

### Task 4: Freeze Book year recanonicalization ownership

**Files:**

- Modify: `scripts/workflows/contracts/book.mts`
- Modify: `scripts/workflows/shared/material-result.mts`
- Modify: `scripts/workflows/operations/book-year-evidence.mts`
- Modify: `scripts/workflows/operations/rows/search.mts`
- Modify: `scripts/workflows/operations/rows/book.mts`
- Modify: `agents/metadata-agent.md`
- Modify: `agents/download-agent.md`
- Modify: `tests/test_material_result.py`
- Modify: `tests/test_run_stage.py`
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `workflows/run-stage.mjs` (generated)

- [ ] Add only the currently executable parser/row boundary tests: parser positives for `accept-current` and `use-recommended-year`; one table-driven invalid-action set; `slug_year/current_identity.year` mismatch; owner-drift gate lifting with `material_key === book:<vault_slug>` while the bibliographic identity slug remains unchanged; verdict/issue/action incoherence; Acquire truthy/batch bypass rejection plus the two exact decision paths; and Search old-year rejection plus recommended-year success. The Book-plan single-consumption, stale-facts, and unknown-Search traces belong to main Task 8 after that plan exists. Do not expand these into a field matrix.

- [ ] Replace the generic `WorkflowContext` year evidence with one closed `BookYearEvidence` type and one semantic parser shared by the Book contract and the Book/Search rows. Reuse or move `book-year-evidence.mts`; do not create a second validator. It owns the six exact fields, exact `pdf_signals`, the temp-path pattern, and the small verdict relationships: `MATCH` has `recommended_year === slug_year`; `MISMATCH` has a non-null distinct recommendation; `AMBIGUOUS` has no recommendation. Evidence-source counts remain Agent judgement, not host heuristics.

- [ ] Define `BookYearDecisionValue` exactly as `{current_identity,tmp_path,year_evidence,action}` in the Book-owned contract. Its parser requires a strict `BookIdentity`, an exact temp path, and `year_evidence.slug_year === current_identity.year`. `accept-current` is eligible only for prior `MISMATCH|AMBIGUOUS`; `use-recommended-year` only for prior `MISMATCH` with a distinct recommendation in the valid Book year range. A `MATCH` decision is invalid because no gate exists for it. Preserve all four values exactly through the user handoff.

- [ ] Add pure `parseBookYearGate(receipt,currentIdentity)` beside the decision parser. It accepts only `book.acquire/needs_input`, binds the host-stamped `material_key`, exact temp/evidence, and strict current identity, requires the verdict-specific issue code, and proves the deterministic action list (`accept-current,use-recommended-year` only when the recommendation is actionable; otherwise `accept-current`). Task 8 maps invalid semantics to `workflow.incoherent_gate` and never displays them. Do not add a generic non-complete receipt validator.

- [ ] Remove duplicate Book-year handoff fields from the common receipt payload. Put `tmp_path/year_evidence` once in `terminal.complete` and once in `terminal.needs_input`, with `proposed_actions` only in `needs_input`; the gate parser reads the needs-input branch and the complete predicate reads the complete branch.

- [ ] Delete the undocumented `batchAcceptYear|batch_accept_year` context, envelope, and completion bypass. Every accepted mismatch or ambiguity now requires the typed Book year decision.

- [ ] Make `book.acquire` parse a non-null internal year decision before dispatch; malformed truthy data raises `InputContractError`. With no decision, complete requires coherent `MATCH` evidence for the invocation identity. Define action-specific coherence:

  - `accept-current`: retain `current_identity`; Acquire validates the exact prior evidence against its year.
  - `use-recommended-year`: require exact prior `MISMATCH`; Acquire receives a Search-owned full identity whose year equals the recommendation, plus the same exact temp/evidence/action. It does not require identity slug to equal runtime owner slug and never transforms either slug.

- [ ] `material.search` accepts a year decision only for Book `use-recommended-year`; `accept-current` never dispatches Search. Its request carries exact current identity plus decision, and complete additionally requires `receipt.identity.year === recommended_year` before the normal Search-owner proof. The metadata Agent owns the returned full identity and slug.

- [ ] Amend main Task 8 to parse the outer envelope/value at entry without sending it to an ordinary Search; establish current identity and runtime slug first; ignore it when fresh source facts make it stale; compare copied gate key/operation/identity exactly once; run `accept-current` directly through Acquire; run `use-recommended-year` through one readonly Search under the old key and never Acquire after any Search stop; then take identity and runtime slug only from the coherent Search receipt and thread the already-validated value directly to Acquire without a second `decisionForOperation()` call. Recovery persists no partial Search result or cursor.

- [ ] Update the two Agent contracts to reflect ownership: the plan supplies host-owned `current_identity` and `material_key`; download owns temp/evidence/verdict and acceptance; metadata Search owns canonical year/slug. Do not add a second year-normalization helper.

- [ ] Amend the main refactor plan's Task 7, Task 8, and Task 10 assumptions to consume the frozen seed/gate/year contract. In particular, Book chapter mixed outcomes are success/blocked/unknown; `book_structure` is the only Prepare/fan-out human gate, while Acquire may first return `book_year`. Search owner hits set the downstream runtime slug and observation lookup to `local_owner.vault_slug`; a miss uses `receipt.identity.slug`.

- [ ] Run the full contract verification and commit.

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_material_result.py tests/test_workflow_dispatch.py tests/test_run_stage.py tests/test_skill_orchestration.py tests/test_dead_names.py -q
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-leaf-contract-test-data python3 -m pytest -q
cmp -s CLAUDE.md AGENTS.md
git diff --check
git add scripts/workflows/contracts/book.mts scripts/workflows/shared/material-result.mts scripts/workflows/operations/book-year-evidence.mts scripts/workflows/operations/rows/search.mts scripts/workflows/operations/rows/book.mts agents/metadata-agent.md agents/download-agent.md tests/test_material_result.py tests/test_run_stage.py tests/test_workflow_dispatch.py workflows/run-stage.mjs docs/superpowers/plans/2026-08-04-material-workflow-refactor.md
git commit -m "fix: bind book year decisions to recanonicalization"
```

After Task 4, execute main Tasks 6B and 6C before returning to Task 7 of the material Workflow refactor. Do not add a separate runtime adapter or compatibility API.

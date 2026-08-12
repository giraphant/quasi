# Book Observation Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resume a partially completed Book after an ambiguous chapter-writer outcome by obtaining fresh exact status and dispatching only unresolved chapters.

**Architecture:** Reuse the existing `quasi.material.result/0.1` `needs_observation` handshake. Book opts into it at the chapter join; Author and Topic only lift a child Book request through their existing opaque continuations; the Skills perform the already-established status-and-resume transport from prose guidance.

**Tech Stack:** TypeScript ES2022 Workflow sources, generated esbuild Workflow bundles, Python pytest harnesses, Markdown Claude Code skills.

## Global Constraints

- Do not weaken `quasi.stage.receipt/0.3` validation or replay an ambiguous writer inside one Workflow invocation.
- Do not add a generic retry engine, coded progress fingerprint, retry counter, durable cursor, lock, or second state file.
- Only Book chapter fan-out produces the new leaf observation request; other leaf and composition-owned writers keep their existing terminal behavior.
- A fresh usable chapter output is durable progress and must not receive another Chapter Agent.
- Author and Topic may lift the request but must not interpret Book progress.
- Preserve all pre-existing uncommitted work and stage only recovery-specific hunks.
- Generated `workflows/*.mjs` files are updated only through `npm run build:workflows`.

---

### Task 1: Book leaf observation recovery

**Files:**
- Modify: `scripts/workflows/shared/material-result.mts`
- Modify: `scripts/workflows/plans/book.mts`
- Test: `tests/test_material_plans.py`

**Interfaces:**
- Consumes: `LeafResumeSeed`, `needsObservationMaterialResult()`, exact `BookStatusObservation.facts.chapters`.
- Produces: a `needs_observation` MaterialResult whose `resume_seed` is the current Book `LeafResumeSeed`; missing-only Chapter Agent dispatch on fresh status.

- [ ] **Step 1: Write failing Book recovery tests**

Add causal tests beside the existing Book join tests:

```python
def test_book_unknown_chapter_requests_fresh_book_observation() -> None:
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(False, False),
    )
    report = run_book(value, [chapter_complete(), "__throw__"])

    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [
        {"kind": "book", "slug": "exact-book"}
    ]
    assert report["result"]["resume_seed"] == {
        "route": {"kind": "book", "slug": "exact-book"},
        "seed": value["seed"],
        "options": {},
    }


def test_book_incoherent_chapter_requests_fresh_book_observation() -> None:
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(False, False),
    )
    report = run_book(
        value,
        [chapter_complete(), chapter_complete(reconciled=True)],
    )

    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [
        {"kind": "book", "slug": "exact-book"}
    ]


def test_book_fresh_status_dispatches_only_unusable_chapters() -> None:
    value = canonical_book_input(
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(True, False),
        overview=False,
    )
    report = run_book(
        value,
        [chapter_complete(), book_synthesise_complete(), audit_complete()],
    )

    chapter_calls = [
        call for call in report["calls"]
        if call["request"]["operation"] == "chapter.analyse"
    ]
    assert [call["request"]["output"]["path"] for call in chapter_calls] == [
        "vault/books/exact-book/ch02-closing.md"
    ]
    assert report["result"]["terminal"] == "complete"
```

Keep the existing test proving that a schema-valid `blocked` receipt remains terminal.

- [ ] **Step 2: Run the tests and verify the current behavior fails**

Run:

```bash
pytest tests/test_material_plans.py -k 'book_unknown_chapter_requests or book_fresh_status_dispatches_only' -q
```

Expected: the unknown case returns `blocked`, and the partial-status case dispatches both chapters.

- [ ] **Step 3: Widen the existing result union without changing its JSON version**

In `material-result.mts`, allow `needs_observation.resume_seed` to be either the existing higher-order seed or a leaf seed:

```ts
export type ObservationResumeSeed =
  | LeafResumeSeed
  | HigherOrderObservationResumeSeed;

export const needsObservationMaterialResult = (
  seed: MaterialResultSeed,
  routes: ObservationRoute[],
  resumeSeed: ObservationResumeSeed,
): MaterialResult => ({
  ...materialBase(seed),
  terminal: "needs_observation",
  issue: null,
  routes,
  resume_seed: resumeSeed,
});
```

Use the same type in the `MaterialResult` union. Do not add a schema version or a second result constructor.

- [ ] **Step 4: Make Book recover from an ambiguous chapter join**

In `book.mts`, remember the current leaf continuation before fan-out. Build `preparedChapters` only from chapters whose status output is not usable. If every output is already usable, use an empty current-run output set and continue directly to synthesis.

After `pipeline()` settles, map `unknown_outcome` or `incoherent_complete` to:

```ts
return needsObservationMaterialResult(
  resultSeed(state),
  [{ kind: "book", slug }],
  resumeSeed(input, state),
);
```

Do not map a receipt terminal `blocked`, `failed`, or `needs_input` to observation recovery.

- [ ] **Step 5: Run focused Book tests**

Run:

```bash
pytest tests/test_material_plans.py -k 'book_' -q
```

Expected: PASS, including existing stable-order, gate, and audit-repair tests.

- [ ] **Step 6: Commit Task 1 hunks only**

Stage the two TypeScript sources and only the new Book test hunks, preserving the unrelated Translation edits already present in `tests/test_material_plans.py`.

```bash
git commit -m "fix: resume partial book chapter fanout"
```

---

### Task 2: Lift child Book observation requests through composition

**Files:**
- Modify: `scripts/workflows/plans/author.mts`
- Modify: `scripts/workflows/plans/topic.mts`
- Test: `tests/test_material_plans.py`
- Test: `tests/test_topic_plan.py`

**Interfaces:**
- Consumes: a composed child result with `terminal: "needs_observation"` and the updated `LeafCompositionOutcome.continuation`.
- Produces: the existing Author or Topic `needs_observation` result with an opaque outer continuation that contains the updated Book leaf.

- [ ] **Step 1: Add failing composition tests**

For Author, add a single-member partial Book whose only unresolved Chapter Agent disappears:

```python
def test_author_lifts_partial_book_observation_request() -> None:
    identity = book_identity("book-one", "Book One")
    route = {"kind": "book", "slug": "book-one"}
    observation = book_observation(
        "book-one",
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(True, False),
        overview=False,
        admitted=True,
    )
    observation["identity"] = {
        "title": identity["title"],
        "authors": identity["authors"],
        "year": identity["year"],
    }
    report = run_author(
        author_compose_input(
            [author_member(route, route, identity)],
            [(route, observation)],
        ),
        ["__throw__"],
    )

    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [route]
    assert report["result"]["resume_seed"]["members"][0]["leaf"]["route"] == route
```

For Topic, change `TOPIC_HARNESS.pipeline` to `Promise.all(items.map(worker))`, then add the same canonical Book shape as an explicit seed and assert that the returned Topic continuation retains its Book leaf:

```python
def test_topic_lifts_partial_book_observation_request() -> None:
    gap = {**SUBQUESTION, "coverage": "gap"}
    route = {"kind": "book", "slug": "exact-book"}
    observation = book_observation(
        "exact-book",
        manifest=True,
        chapter_inputs=(True, True),
        chapter_outputs=(True, False),
        overview=False,
        admitted=True,
    )
    report = run_topic(
        topic_input(
            observation=topic_observation(subquestions=[gap], members=[], cards=[]),
            seeds=[book_seed()],
            children=[(route, observation)],
        ),
        [recall_complete(), "__throw__"],
    )

    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [route]
    assert report["result"]["resume_seed"]["leaf"]["route"] == route
```

Retain the existing tests showing that child `blocked|failed` is surfaced unchanged.

- [ ] **Step 2: Run the new tests and verify unsupported-terminal failures**

Run:

```bash
pytest tests/test_material_plans.py -k 'author_lifts_partial_book_observation' -q
```

Expected: Author reports `workflow.incoherent_complete`. Run Topic separately:

```bash
pytest tests/test_topic_plan.py -k 'topic_lifts_partial_book_observation' -q
```

- [ ] **Step 3: Add one lift branch in Author**

After validating and storing `outcome.continuation`, handle the child result before the generic unsupported-terminal branch:

```ts
if (result.terminal === "needs_observation") {
  const continuation = resumeSeed(
    input.resumeSeed.seed,
    input.resumeSeed.options,
    members,
    decisionMember,
  );
  return needsObservationMaterialResult(
    resultSeed(input.resumeSeed.seed),
    uniqueRoutes(members),
    continuation,
  );
}
```

Author does not inspect the Book's chapter status or count recovery rounds.

- [ ] **Step 4: Add one lift branch in Topic**

After updating `current` from the returned Book leaf continuation, wrap that continuation in the current `TopicSeedChildContinuation | TopicWorkContinuation` and return `needsObservationMaterialResult` for the exact leaf route. Do not copy Book logic into Topic.

```ts
if (result.terminal === "needs_observation")
  return {
    result: needsObservationMaterialResult(
      resultSeed(input),
      [current.leaf.route],
      current,
    ),
    receipt: null,
  };
```

- [ ] **Step 5: Run Author and Topic plan tests**

Run:

```bash
pytest tests/test_material_plans.py -k 'author_' -q
```

Run Topic separately:

```bash
pytest tests/test_topic_plan.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2 hunks only**

```bash
git commit -m "fix: lift book recovery through compositions"
```

---

### Task 3: Teach the Skills the minimal observation loop

**Files:**
- Modify: `skills/collect-material/SKILL.md`
- Modify: `skills/research-topic/SKILL.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/SKILL_ORCHESTRATION.md`
- Modify: `docs/GRAPH_COLLABORATION.md`
- Test: `tests/test_skill_orchestration.py`

**Interfaces:**
- Consumes: any valid `needs_observation` MaterialResult with exact `routes` and opaque `resume_seed`.
- Produces: fresh exact observations passed back to the same named Workflow; a user-visible stop after two consecutive unchanged recovery observations.

- [ ] **Step 1: Run the existing orchestration contract tests before documentation changes**

Run:

```bash
pytest tests/test_skill_orchestration.py tests/test_material_result.py -q
```

Expected: PASS. These tests protect headings, shared terminal names, and cross-file contract coherence without snapshotting prose.

- [ ] **Step 2: Generalize the Skill rule in prose**

In both executing Skills, replace the “higher-order only” limitation with this behavior, adapted to each Skill's existing input examples:

```text
needs_observation is automatic: run fresh exact status for every returned route,
copy the opaque resume_seed unchanged, and invoke the same named Workflow again.
Continue while the requested observations advance. If two consecutive recovery
observations for the same routes are unchanged, stop and report the last typed
result and exact status. Do not interpret chapter progress in the Skill.
```

Direct leaf resume reconstructs its ordinary closed input from
`resume_seed.{seed,options}` plus the one fresh route observation. Author and Topic keep their existing composed input shapes.

- [ ] **Step 3: Align maintainer documentation**

Update the three maintainer documents only where they currently say that leaf unknown outcomes always stop or that `needs_observation` is high-order-only. Preserve the rule that a Workflow itself never blindly replays an ambiguous writer.

- [ ] **Step 4: Run Skill and dead-name tests**

Run:

```bash
pytest tests/test_dead_names.py tests/test_skill_orchestration.py tests/test_material_result.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3 hunks only**

Preserve the existing Translation and Workflow-args edits in `collect-material/SKILL.md`; stage only observation-recovery hunks.

```bash
git commit -m "docs: automate exact observation recovery"
```

---

### Task 4: Build, verify, and publish

**Files:**
- Generate: `workflows/author.mjs`
- Generate: `workflows/book.mjs`
- Generate: `workflows/topic.mjs`
- Preserve any pre-existing worktree changes that the standard build also reproduces in sibling bundles.

**Interfaces:**
- Consumes: all TypeScript source changes from Tasks 1–3.
- Produces: generated bundles matching the editable TypeScript sources and a pushed `main` branch.

- [ ] **Step 1: Build generated Workflow bundles**

Run:

```bash
npm run build:workflows
```

Expected: successful esbuild output.

- [ ] **Step 2: Run strict Workflow checks**

Run:

```bash
npm run check:workflows
```

Expected: schema/projection/operation/bundle parity and `tsc --noEmit` all pass.

- [ ] **Step 3: Run focused regression suites**

Run:

```bash
pytest tests/test_material_plans.py tests/test_topic_plan.py tests/test_material_result.py tests/test_skill_orchestration.py tests/test_dead_names.py -q
```

Expected: PASS.

- [ ] **Step 4: Review generated and staged scope**

Verify that generated bundle changes reflect the TypeScript recovery changes while pre-existing generated Translation changes remain unstaged unless they were already committed separately:

```bash
git diff --check
git diff --cached --check
git status --short
```

- [ ] **Step 5: Commit generated recovery hunks**

```bash
git commit -m "build: refresh observation recovery workflows"
```

- [ ] **Step 6: Push the completed commits**

```bash
git push origin main
```

Expected: `origin/main` advances to the verified recovery implementation while unrelated working-tree edits remain local and unstaged.

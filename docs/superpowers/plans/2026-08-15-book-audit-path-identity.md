# Book Audit Path Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Book audit diagnostics use either project-relative or equivalent absolute paths without weakening exact artifact ownership.

**Architecture:** Add one pure Workflow helper that resolves path spellings against the configured project root, then index the existing Book overview/chapter inventory by that identity. First- and second-pass audit checks use the same identity map, while repair requests retain the original diagnostic objects and route through the inventory's relative owner record.

**Tech Stack:** TypeScript `.mts` Workflow sources, Node `node:path`, generated esbuild Workflow bundles, Python `pytest` harness.

## Global Constraints

- Use non-empty `CLAUDE_PROJECT_DIR` as the trusted project root; otherwise use cwd.
- Do not perform filesystem discovery or `realpath`; compare lexical identities only.
- Accept only the exact overview and manifest-admitted chapter outputs, never any arbitrary file under the Book directory.
- Preserve Audit diagnostic objects byte-for-byte in `repair_diagnostics`.
- Do not change Audit judgement, schema structure, the one-repair budget, or terminal semantics.
- Edit `.mts` sources and regenerate `workflows/book.mjs`; never hand-edit the generated bundle.

---

### Task 1: Resolve first-pass Book audit owners by path identity

**Files:**
- Create: `scripts/workflows/shared/project-path.mts`
- Modify: `scripts/workflows/plans/book.mts:288-365`
- Test: `tests/test_material_plans.py:2020-2100`
- Generate: `workflows/book.mjs`

**Interfaces:**
- Produces: `projectPathIdentity(path: string): string`, returning a lexically resolved absolute identity.
- Consumes: `bookOverviewPath()`, `bookChapterOutputPath()`, `ChapterInventoryRow`, and the existing observed/current-run relative path sets.
- Produces for Task 2: one Book owner map keyed by `projectPathIdentity()` and retaining `{ path, chapter }`.

- [ ] **Step 1: Add failing first-pass regressions**

Add these tests beside the existing Book audit repair tests:

```python
def test_book_absolute_owned_chapter_audit_path_routes_repair() -> None:
    diagnostic = {
        "path": str(ROOT / "vault/books/exact-book/ch01-opening.md"),
        "kind": "block_kind_mismatch_soft",
        "reason": "金句要点 must use a blockquote list.",
    }
    report = run_book(
        canonical_book_input(
            manifest=True,
            chapter_outputs=(True, True),
        ),
        [
            audit_complete(escalated=[diagnostic]),
            chapter_repair_complete(),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit",
        "chapter.analyse",
        "book.audit",
    ]
    repair = report["calls"][1]["request"]
    assert repair["identity"]["chapter_slot"] == "01"
    assert repair["repair_diagnostics"] == [diagnostic]
    assert report["result"]["terminal"] == "complete"


def test_book_absolute_owned_overview_audit_path_routes_repair() -> None:
    diagnostic = {
        "path": str(ROOT / "vault/books/exact-book/00-overview.md"),
        "kind": "frontmatter",
        "reason": "The overview metadata is incomplete.",
    }
    report = run_book(
        canonical_book_input(
            manifest=True,
            chapter_outputs=(True, True),
        ),
        [
            audit_complete(escalated=[diagnostic]),
            book_synthesise_complete("repair"),
            audit_complete(),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit",
        "book.synthesise",
        "book.audit",
    ]
    assert report["calls"][1]["request"]["repair_diagnostics"] == [diagnostic]
    assert report["result"]["terminal"] == "complete"


def test_book_absolute_foreign_audit_path_remains_owner_ambiguity() -> None:
    diagnostic = {
        "path": str(ROOT / "vault/books/another-book/ch01-opening.md"),
        "kind": "missing-section",
        "reason": "Foreign Book.",
    }
    report = run_book(
        canonical_book_input(
            manifest=True,
            chapter_outputs=(True, True),
        ),
        [audit_complete(escalated=[diagnostic])],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit"
    ]
    assert report["result"]["issue"]["code"] == "workflow.owner_ambiguity"
```

- [ ] **Step 2: Run the first-pass tests and verify RED**

Run:

```bash
/private/tmp/quasi-release-env/.venv/bin/python -m pytest \
  tests/test_material_plans.py::test_book_absolute_owned_chapter_audit_path_routes_repair \
  tests/test_material_plans.py::test_book_absolute_owned_overview_audit_path_routes_repair \
  tests/test_material_plans.py::test_book_absolute_foreign_audit_path_remains_owner_ambiguity \
  -q
```

Expected: the two owned-path tests fail with `workflow.owner_ambiguity`; the foreign-path guard passes.

- [ ] **Step 3: Add the pure project-path identity helper**

Create `scripts/workflows/shared/project-path.mts`:

```typescript
import { resolve } from "node:path";

const projectRoot = (): string => {
  const configured = process.env.CLAUDE_PROJECT_DIR;
  return configured && configured.trim().length > 0
    ? configured
    : process.cwd();
};

export const projectPathIdentity = (path: string): string =>
  resolve(projectRoot(), path);
```

- [ ] **Step 4: Index first-pass Book owners by resolved identity**

Import `projectPathIdentity` in `scripts/workflows/plans/book.mts`. Replace the raw `chapterOwners`/`ownedOverview` comparison and lookup with an exact owner inventory:

```typescript
interface BookAuditOwner {
  path: string;
  chapter: ChapterInventoryRow | null;
}

const owners = [
  { path: bookOverviewPath(slug), chapter: null },
  ...chapters.map((chapter) => ({
    path: bookChapterOutputPath(slug, chapter),
    chapter,
  })),
] satisfies BookAuditOwner[];
const ownersByIdentity = new Map(
  owners.map((owner) => [projectPathIdentity(owner.path), owner]),
);
const ownerForAuditPath = (path: string): BookAuditOwner | undefined =>
  ownersByIdentity.get(projectPathIdentity(path));
```

Use `ownerForAuditPath(path)` to reject foreign first-pass paths. Select the first repair owner through that function, group diagnostics with `projectPathIdentity(path) === projectPathIdentity(repairOwner.path)`, route on `repairOwner.chapter`, and use `repairOwner.path` for observed/current-run evidence checks. Pass the original `diagnostics` objects unchanged.

- [ ] **Step 5: Regenerate the Book bundle**

Run:

```bash
npm run build:workflows
```

Expected: all seven generated Workflow bundles rebuild successfully; only source-derived bundle changes are accepted.

- [ ] **Step 6: Run the first-pass tests and existing relative-path guards**

Run:

```bash
/private/tmp/quasi-release-env/.venv/bin/python -m pytest \
  tests/test_material_plans.py::test_book_absolute_owned_chapter_audit_path_routes_repair \
  tests/test_material_plans.py::test_book_absolute_owned_overview_audit_path_routes_repair \
  tests/test_material_plans.py::test_book_absolute_foreign_audit_path_remains_owner_ambiguity \
  tests/test_material_plans.py::test_book_repairs_a_newly_written_chapter_once_then_reaudits \
  tests/test_material_plans.py::test_book_repairs_the_owned_overview_once_then_reaudits \
  -q
```

Expected: `5 passed`.

- [ ] **Step 7: Commit Task 1**

```bash
git add scripts/workflows/shared/project-path.mts scripts/workflows/plans/book.mts tests/test_material_plans.py workflows/book.mjs
git commit -m "fix(workflow): resolve Book audit owner paths"
```

### Task 2: Apply the same identity rule to the second audit

**Files:**
- Modify: `scripts/workflows/plans/book.mts:365-395`
- Test: `tests/test_material_plans.py:2020-2140`
- Generate: `workflows/book.mjs`

**Interfaces:**
- Consumes: Task 1's `ownerForAuditPath(path: string): BookAuditOwner | undefined` closure.
- Produces: second-pass classification that distinguishes an owned residual violation from a foreign target.

- [ ] **Step 1: Add the failing second-pass regression**

```python
def test_book_second_absolute_owned_escalation_is_repair_exhausted() -> None:
    diagnostic = {
        "path": str(ROOT / "vault/books/exact-book/ch01-opening.md"),
        "kind": "block_kind_mismatch_soft",
        "reason": "金句要点 still has mixed blocks.",
    }
    report = run_book(
        canonical_book_input(
            manifest=True,
            chapter_outputs=(True, True),
        ),
        [
            audit_complete(escalated=[diagnostic]),
            chapter_repair_complete(),
            audit_complete(escalated=[diagnostic]),
        ],
    )

    assert [call["request"]["operation"] for call in report["calls"]] == [
        "book.audit",
        "chapter.analyse",
        "book.audit",
    ]
    assert report["result"]["terminal"] == "blocked"
    assert report["result"]["issue"]["code"] == "workflow.repair_exhausted"
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
/private/tmp/quasi-release-env/.venv/bin/python -m pytest \
  tests/test_material_plans.py::test_book_second_absolute_owned_escalation_is_repair_exhausted \
  -q
```

Expected: FAIL because the second raw-string owner check returns `workflow.owner_ambiguity`.

- [ ] **Step 3: Reuse the owner lookup in the second-pass check**

Replace the second audit's raw `path !== ownedOverview && !chapterOwners.has(path)` predicate with:

```typescript
(secondReceipt.escalated as Array<{ path: string }>).some(
  ({ path }) => ownerForAuditPath(path) === undefined,
)
```

Do not change the subsequent zero-violation or repair-exhaustion branches.

- [ ] **Step 4: Regenerate and verify the second-pass behavior**

Run:

```bash
npm run build:workflows
/private/tmp/quasi-release-env/.venv/bin/python -m pytest \
  tests/test_material_plans.py::test_book_second_absolute_owned_escalation_is_repair_exhausted \
  -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit Task 2**

```bash
git add scripts/workflows/plans/book.mts tests/test_material_plans.py workflows/book.mjs
git commit -m "fix(workflow): classify owned Book re-audit paths"
```

### Task 3: Verify the complete Workflow change

**Files:**
- Verify only: `scripts/workflows/shared/project-path.mts`
- Verify only: `scripts/workflows/plans/book.mts`
- Verify only: `tests/test_material_plans.py`
- Verify only: `workflows/book.mjs`

**Interfaces:**
- Consumes: Tasks 1 and 2 as committed.
- Produces: release-ready evidence; no new runtime behavior.

- [ ] **Step 1: Run the complete material-plan suite**

```bash
/private/tmp/quasi-release-env/.venv/bin/python -m pytest tests/test_material_plans.py -q
```

Expected: all material-plan tests pass with zero failures.

- [ ] **Step 2: Verify generated Workflow and TypeScript parity**

```bash
npm run check:workflows
```

Expected: every bundle is current and `tsc --noEmit` exits zero.

- [ ] **Step 3: Run the full Python suite outside restricted sandboxing**

```bash
/private/tmp/quasi-release-env/.venv/bin/python -m pytest -q
```

Expected: all collected tests pass; macOS WebKit tests may require loopback and compiler-cache access.

- [ ] **Step 4: Run repository consistency checks**

```bash
claude plugin validate .
git diff --check
cmp -s CLAUDE.md AGENTS.md
git status --short --branch
```

Expected: plugin validation, whitespace check, and instruction mirror check exit zero; status shows only intentional commits/changes.

- [ ] **Step 5: Inspect final commit scope**

```bash
git log -3 --oneline
git show --stat --oneline HEAD~1..HEAD
```

Expected: implementation commits contain only the shared helper, Book plan source, Book generated bundle, and material-plan regressions; no unrelated user changes are included.

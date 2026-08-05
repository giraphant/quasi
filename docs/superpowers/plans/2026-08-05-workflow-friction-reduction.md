# Workflow Friction Reduction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task by task.

**Goal:** Remove the three production-proven orchestration frictions in Paper/Book Acquire, legacy Book chapter manifests, and leaf gate resume input without weakening provenance or adding recovery machinery.

**Architecture:** Keep each fix at its current owner. Descriptor rows own the Acquire receipt, the schema layer owns the chapter page-pair predicate, the transactional extractor owns safe replacement, and the driving Skill owns the generic `UserDecision` wrapper. Generated Workflow bundles remain build outputs.

**Tech Stack:** TypeScript workflow rows built with esbuild, strict `tsc`, Python 3/pytest, Markdown Skill contracts, Claude Code plugin validator.

**Design:** `docs/superpowers/specs/2026-08-05-workflow-friction-reduction-design.md`

---

### Task 1: Make `write_state` the sole Paper/Book Acquire effect claim

**Files:**

- Modify: `tests/test_workflow_dispatch.py`
- Modify: `tests/test_material_plans.py`
- Modify: `scripts/workflows/operations/rows/paper.mts`
- Modify: `scripts/workflows/operations/rows/book.mts`
- Modify: `agents/download-agent.md`

**Step 1: Write the failing contract tests**

Change the branch-local schema test so that Paper and Book `terminal.complete` require `source` but do not define or require `disposition`. Add a dispatch regression using the production-shaped successful testimony:

```python
{
    "write_state": "written",
    "identity_verified": True,
    "terminal": {
        "status": "complete",
        "issue": None,
        "source": "existing_file",
    },
}
```

The exact stamped path fields still come from the host. Also cover a schema-valid `terminal.complete` with `write_state:"unknown"` and assert that the owning completion predicate returns `incoherent_complete`.

**Step 2: Run the tests to verify RED**

Run:

```bash
pytest tests/test_workflow_dispatch.py -q -k 'acquire and (effect or write_state or terminal_fields)'
```

Expected: the new schema assertion and production-shaped success fail because `disposition` is still required.

**Step 3: Implement the minimal row contract**

In both Acquire rows:

- remove `disposition` from the complete terminal schema;
- keep `source` branch-local and required;
- replace the paired `dispositionCoherent` condition with `write_state === "written" || write_state === "not_written"`;
- leave exact output/format, identity verification, attempts, and Book year evidence unchanged.

Update `download-agent.md` to describe the effect only once: a new accepted source reports `written`; a verified existing target reports `not_written` and `source:"existing_file"`. Do not add a new synonym or compatibility field.

**Step 4: Update existing fixtures and verify GREEN**

Remove obsolete Acquire-only `terminal.disposition` values from workflow-plan fixtures. Do not touch other operations whose `disposition` or `action` fields have separate semantics.

Run:

```bash
npm run build:workflows
pytest tests/test_workflow_dispatch.py tests/test_material_plans.py tests/test_material_result.py -q
npm run check:workflows
```

Expected: all pass, and generated named Workflow bundles are current.

**Step 5: Commit**

```bash
git add scripts/workflows/operations/rows/paper.mts scripts/workflows/operations/rows/book.mts agents/download-agent.md tests/test_workflow_dispatch.py tests/test_material_plans.py workflows scripts/workflows/artifact-contracts
git commit -m "fix: simplify acquire outcome testimony"
```

### Task 2: Rebuild only ownership-safe legacy manifests with unpaired pages

**Files:**

- Create: `scripts/schemas/chapter_manifest.py`
- Modify: `scripts/status/status.py`
- Modify: `scripts/extract/chapter_commit.py`
- Modify: `tests/test_extract_cli.py`
- Verify unchanged behavior: `tests/test_status_cli.py`

**Step 1: Write the failing public extractor regression**

After one successful manual split, edit only its first durable manifest row from a paired range to `start_page:1, end_page:null`, keeping the request fingerprint, source identity, filename, file bytes, and hash intact. Run the identical split again and assert:

```python
assert receipt["status"] == "ok"
assert receipt["disposition"] == "replaced"
assert row["start_page"] == row["end_page"] == 1
```

This is one causal test: a same-request legacy generation must be rebuilt, not reused.

**Step 2: Run the test to verify RED**

Run:

```bash
pytest tests/test_extract_cli.py -q -k 'unpaired_page_range'
```

Expected: current code returns `status:"existing"` and leaves `end_page:null`.

**Step 3: Add the single schema-owned predicate**

Create a dependency-free `valid_chapter_page_pair(start, end) -> bool` in `scripts/schemas/chapter_manifest.py` implementing only:

```python
both None or (both exact ints and 1 <= start <= end)
```

Import it from `status.py` and delete the local duplicate.

**Step 4: Separate ownership safety from canonical validity**

In `chapter_commit.py`, retain the current filename/file/hash checks as the ownership-safe validation used by `_owned_snapshot`. Make full `validate_manifest` call that safety validation and then reject an invalid page pair with one classified `ChapterFailure` code such as `manifest_page_range_invalid`.

At each same-fingerprint reconciliation fast path:

- return `existing` when full validation passes;
- continue into the existing staged build only when the classified failure is `manifest_page_range_invalid` and ownership safety has passed;
- propagate every other failure unchanged.

The staged generation still passes full validation before manifest-last publication. Source identity checks, lock/fingerprint checks, snapshot conflict checks, unmanaged-output checks, and rollback behavior remain untouched.

**Step 5: Verify GREEN and retained strictness**

Run:

```bash
pytest tests/test_extract_cli.py -q -k 'identical_rerun or unpaired_page_range or manifest_change or publish_failure'
pytest tests/test_status_cli.py -q -k 'book_status_rejects_an_unpaired_manifest_page_range'
```

Expected: all pass; status still rejects the legacy manifest before extraction repairs it.

**Step 6: Commit**

```bash
git add scripts/schemas/chapter_manifest.py scripts/status/status.py scripts/extract/chapter_commit.py tests/test_extract_cli.py
git commit -m "fix: rebuild legacy chapter page ranges"
```

### Task 3: Give the driving Skill one generic decision envelope

**Files:**

- Modify: `skills/collect-material/SKILL.md`
- Modify: `tests/test_skill_orchestration.py`

**Step 1: Write the failing semantic Skill test**

Parse fenced Python blocks with `ast.parse`, find the assignment to `user_decision`, and assert its dictionary keys are exactly:

```python
{"material_key", "operation", "value"}
```

Do not assert a Chinese sentence, line position, gate catalogue, or exact formatting.

**Step 2: Run the test to verify RED**

Run:

```bash
pytest tests/test_skill_orchestration.py -q -k 'generic_user_decision'
```

Expected: failure because no generic machine-facing assignment exists yet.

**Step 3: Add the minimal wrapper**

Immediately before the existing gate-specific value rules, add one Python pseudocode block:

```python
user_decision = {
    "material_key": gate.material_key,
    "operation": gate.operation,
    "value": gate_owned_value,
}
workflow_input["userDecision"] = user_decision
```

Keep the four existing descriptions of `gate_owned_value`; do not add a per-stage literal catalogue or inspect generated Workflow code.

**Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_skill_orchestration.py -q
```

Expected: all orchestration coherence tests pass.

**Step 5: Commit**

```bash
git add skills/collect-material/SKILL.md tests/test_skill_orchestration.py
git commit -m "fix: make gate resume envelope explicit"
```

### Task 4: Integrate, verify, and publish 0.65.2

**Files:**

- Modify: `docs/CHANGELOG.md`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Generated by build: `workflows/*.mjs`

**Step 1: Review the integrated diff**

Confirm the changes match the design non-goals: no retry, replay, inferred end page, hidden state, gate catalogue, or title-specific branch. Confirm only Paper/Book Acquire lost `disposition`.

**Step 2: Run focused and structural verification**

```bash
npm run build:workflows
npm run check:workflows
pytest tests/test_workflow_dispatch.py tests/test_material_plans.py tests/test_material_result.py tests/test_extract_cli.py tests/test_status_cli.py tests/test_skill_orchestration.py -q
cmp -s CLAUDE.md AGENTS.md
git diff --check
```

Expected: every command succeeds.

**Step 3: Run the complete suite**

```bash
pytest -q -rsxX -p no:cacheprovider
```

Expected baseline: 692 existing tests plus the small number of new causal rows, all passing; the known environment warnings may remain but no failures, skips, xfails, or xpasses.

**Step 4: Prepare release metadata**

Add a concise 0.65.2 changelog entry describing the production incidents and the three owner-local fixes. Set both plugin manifests to `0.65.2`, then run:

```bash
claude plugin validate .
```

**Step 5: Commit and push main**

```bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json docs/CHANGELOG.md workflows
git commit -m "release: quasi 0.65.2"
git push origin main
```

Report the pushed commit, exact test count, Workflow/type-check result, plugin validation result, and any remaining warnings.

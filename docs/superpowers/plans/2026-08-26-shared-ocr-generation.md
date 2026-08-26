# Shared OCR Generation Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unshipped Paper-only OCR state machine and the active Book fixed-path resume path with one source/profile-bound OCR generation mechanism, while retaining thin Paper/Book adapters and one-way completion of released Book progress.

**Architecture:** A single `ocr_generation.py` capability derives material-safe roots, profiles, generation keys, progress, immutable PDF/text/manifest publication, and observation for Paper and Book. Workflow retains separate `paper.ocr` and `book.ocr` operation names, but both are produced by one TypeScript row factory and use the same receipt shape; Prepare remains material-specific. Released Book legacy progress stays behind an explicit compatibility observer/executor and is never created for new work.

**Tech Stack:** Python 3.9, PyMuPDF, POSIX `flock`/hard-link/fsync publication, TypeScript ES2022 Workflow sources, JSON Schema draft-07, pytest, esbuild, Claude Code plugin validation.

**Spec:** `docs/superpowers/specs/2026-08-26-shared-ocr-generation-design.md`

## Global Constraints

- New OCR generations are sequential; no Pipeline fan-out, background process, hidden cursor, or blind replay.
- `dsocr2-text` commits at most 16 pages; `tesseract-text` commits at most 32 pages.
- DS OCR2 fallback to Tesseract stays inside the same 16-page range and records the actual engine.
- Final publication is immutable `ocr.pdf`, `ocr.txt`, then `manifest.json` last.
- Paper roots are `processing/papers/{slug}`; Book roots are `processing/chapters/{slug}`.
- Translation `--layout`, Talk, and Webpage behavior remain unchanged.
- Fixed legacy Paper/Book OCR artifacts are never overwritten.
- Existing Book progress may finish through the legacy executor; no new legacy progress is created.
- Generated Workflow contracts and bundles are rebuilt, never edited by hand.
- `CLAUDE.md` and `AGENTS.md` remain byte-for-byte identical.

---

### Task 1: Shared deterministic OCR generation core

**Files:**
- Create: `scripts/extract/ocr_generation.py`
- Delete after GREEN: `scripts/extract/paper_ocr.py`
- Preserve for legacy only: `scripts/extract/ocr_resume.py`
- Modify: `tests/test_extract_cli.py`

**Interfaces:**
- Consumes: exact project root, material kind, slug, accepted PDF, expected source SHA-256, expected generation key, named profile.
- Produces:

```python
PROFILES: dict[tuple[str, str], dict[str, object]]

def resolve_profile(kind: str, profile_name: str) -> dict[str, object]: ...

def generation_key(
    *, kind: str, slug: str, source_path: str,
    source_sha256: str, profile_name: str
) -> str: ...

def paths_for(
    *, project_root: Path, kind: str, slug: str, generation: str
) -> dict[str, Path]: ...

def observe_generation(
    *, project_root: Path, kind: str, slug: str,
    source_sha256: str, source_size: int, source_pages: int,
    generation: str, profile_name: str
) -> dict[str, Any]: ...

def run_transaction(
    *, project_root: Path, kind: str, slug: str, source_file: Path,
    expected_source_sha256: str, expected_generation_key: str,
    profile_name: str, runner: Callable[..., EngineResult] | None = None
) -> dict[str, Any]: ...
```

- `EngineResult` is a frozen record containing `engine: Literal["dsocr2", "tesseract"]` and `returncode: int`.
- The receipt schema is `quasi.operation.ocr-generation.receipt/0.1`, with status, disposition, material/source/profile identity, paths, state, progress, final artifact facts, and failure.

- [ ] **Step 1: Replace Paper-specific unit tests with shared parameterized RED tests**

Add parameterized tests for both material roots:

```python
@pytest.mark.parametrize(
    ("kind", "root"),
    [("paper", "processing/papers"), ("book", "processing/chapters")],
)
def test_ocr_generation_key_and_paths_are_material_safe(kind, root, tmp_path):
    source_sha = "a" * 64
    key = ocr_generation.generation_key(
        kind=kind,
        slug="exact-material",
        source_path="sources/exact-material.pdf",
        source_sha256=source_sha,
        profile_name="dsocr2-text",
    )
    paths = ocr_generation.paths_for(
        project_root=tmp_path,
        kind=kind,
        slug="exact-material",
        generation=key,
    )
    assert paths["generation_dir"].relative_to(tmp_path).as_posix() == (
        f"{root}/exact-material/ocr-generations/{key}"
    )
```

Assert profile sizes exactly:

```python
assert resolve_profile("paper", "dsocr2-text")["chunk_pages"] == 16
assert resolve_profile("book", "dsocr2-text")["chunk_pages"] == 16
assert resolve_profile("paper", "tesseract-text")["chunk_pages"] == 32
assert resolve_profile("book", "tesseract-text")["chunk_pages"] == 32
```

Parameterize one-range progress, committed publication, source drift, lock contention, corrupt part, exact orphan reconciliation, unknown inventory, committed reconciliation, and fixed legacy-path non-mutation. Require each range to record `start_page`, `end_page`, `engine`, `path`, `sha256`, and `pages`.

- [ ] **Step 2: Run the new shared tests and record RED**

Run:

```bash
python3 -m pytest tests/test_extract_cli.py -q -k 'ocr_generation'
```

Expected: collected assertion failures because the shared module, profiles, Book roots, and 16/32-page records do not exist. Use a guarded test import so intended assertions collect; an import error alone is not sufficient RED.

- [ ] **Step 3: Implement closed profiles and material-safe paths**

Implement:

```python
PROFILE_BASE = {
    "schema_version": "quasi.ocr.profile/0.2",
    "language": "chi_sim+eng",
    "text_extractor": "pymupdf",
}
PROFILE_ENGINES = {
    "dsocr2-text": {"engine_order": ["dsocr2", "tesseract"], "chunk_pages": 16},
    "tesseract-text": {"engine_order": ["tesseract"], "chunk_pages": 32},
}
VALIDATION_POLICIES = {
    "paper": "paper-text-v1",
    "book": "book-pdf-v1",
}
```

`resolve_profile()` returns the canonical merge and rejects unknown names/kinds. `generation_key()` hashes canonical JSON containing material key, exact source path/SHA-256, and resolved profile. `paths_for()` derives only the two allowed processing roots and rejects symlinked components.

- [ ] **Step 4: Implement shared observation and progress validation**

Port deterministic state logic from the uncommitted Paper implementation, replacing `paper.ocr_*` failures with `ocr.generation_*`. Define one closed progress schema containing source/profile identity, total/completed/next page, and ordered range records. Observation returns the same exact keys for Paper and Book:

```python
{
    "state": "missing|in_progress|committed|invalid|unknown",
    "material_key": f"{kind}:{slug}",
    "kind": kind,
    "slug": slug,
    "generation_key": generation,
    "profile": resolved_profile,
    "config_fingerprint": fingerprint(resolved_profile),
    "source": {"path": ..., "sha256": ..., "size": ..., "pages": ...},
    "paths": {...},
    "progress": None | {...},
    "manifest": {...},
    "recovery_pdf": {...},
    "normalized_text": {...},
    "failure": None | "ocr.generation_*",
}
```

- [ ] **Step 5: Implement one-range engine execution and actual-engine records**

Select the source slice from the profile. DS OCR2 runs first only for `dsocr2-text`; nonzero exit or declared quality rejection removes the candidate and runs Tesseract on the same slice. Return `EngineResult(engine=..., returncode=0)` and persist that engine. Publish/fsync the part before atomically replacing progress. Do not call `ocr_resume.run_ocr_step()` for new work.

- [ ] **Step 6: Implement immutable final publication**

Merge ordered parts, require the exact source page count, extract normalized UTF-8 text, and build a manifest containing source, profile, ranges, recovery PDF facts, and text facts. Create the immutable directory, hard-link PDF and text, fsync, hard-link the manifest last, fsync, then re-observe. Clean only after `state == "committed"`.

- [ ] **Step 7: Run shared-core GREEN and extraction regression**

Run:

```bash
python3 -m pytest tests/test_extract_cli.py -q -k 'ocr_generation or ocr_resume'
python3 -m pytest tests/test_extract_cli.py -q
```

Expected: all pass, and `rg -n 'paper_ocr|paper-ocr' scripts/extract tests/test_extract_cli.py` has no active reference.

- [ ] **Step 8: Commit the shared core**

```bash
git add scripts/extract/ocr_generation.py scripts/extract/ocr_resume.py scripts/extract/paper_ocr.py tests/test_extract_cli.py
git commit -m "refactor(extract): share OCR generation transactions"
```

---

### Task 2: Public CLI and shared status projection

**Files:**
- Modify: `scripts/extract/extract.py`
- Modify: `scripts/status/status.py`
- Modify: `tests/test_extract_cli.py`
- Modify: `tests/test_status_cli.py`

**Interfaces:**
- Consumes: Task 1 `generation_key()`, `observe_generation()`, and `run_transaction()`.
- Produces: `quasi-extract ocr-generation ... --json`; identical Paper/Book `facts.ocr_generation`; explicit Book-only `facts.legacy_ocr`.

- [ ] **Step 1: Add CLI/status RED tests**

Run the public command for both kinds and assert one JSON receipt:

```text
quasi-extract ocr-generation --kind paper --slug exact-paper \
  --source-file sources/exact-paper.pdf \
  --expected-source-sha256 <sha> --generation-key <key> \
  --profile dsocr2-text --json
```

Reject unsafe slug, source role, kind, profile, fingerprint, generation key, and arbitrary output targets at zero engine calls. Status tests assert byte-equivalent capsule key sets for both kinds and all five states. Paper fixed OCR paths never count as current; Book legacy progress appears only under `legacy_ocr`.

- [ ] **Step 2: Run CLI/status RED**

```bash
python3 -m pytest tests/test_extract_cli.py tests/test_status_cli.py -q -k 'ocr_generation or legacy_ocr'
```

Expected: collected failures for the missing route and Book projection.

- [ ] **Step 3: Replace the Paper-only route with `ocr-generation`**

Remove `paper-ocr`, add the closed `ocr-generation` parser, and delegate to `run_transaction()`. Keep `ocr --resume` reachable only for explicit legacy Book continuation; help text must state it does not start current generations.

- [ ] **Step 4: Project the common observer from status**

Use one helper taking `(kind, slug, PDF candidate)` for Paper and Book. Parse released Book progress in a separate `legacy_ocr` fact and never expose it for Paper.

- [ ] **Step 5: Run CLI/status GREEN**

```bash
python3 -m pytest tests/test_extract_cli.py tests/test_status_cli.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit CLI/status**

```bash
git add scripts/extract/extract.py scripts/status/status.py tests/test_extract_cli.py tests/test_status_cli.py
git commit -m "feat(status): observe shared OCR generations"
```

---

### Task 3: Shared Workflow OCR operation contract

**Files:**
- Create: `scripts/workflows/operations/rows/ocr-generation.mts`
- Create: `scripts/workflows/contracts/ocr-generation.mts`
- Modify: `scripts/schemas/operations.py`
- Modify: `scripts/workflows/operations/catalogs/paper.mts`
- Modify: `scripts/workflows/operations/catalogs/book.mts`
- Modify: `scripts/workflows/operations/rows/paper.mts`
- Modify: `scripts/workflows/operations/rows/book.mts`
- Modify: `tests/test_workflow_dispatch.py`

**Interfaces:**
- Consumes: shared status capsule from Task 2.
- Produces:

```ts
export const makeOcrGenerationRow = (config: {
  operation: "paper.ocr" | "book.ocr";
  kind: "paper" | "book";
  validationPolicy: "paper-text-v1" | "book-pdf-v1";
}): OperationRow => ...;

export const parseOcrGenerationObservation = (
  value: unknown,
  expected: { kind: "paper" | "book"; slug: string },
): OcrGenerationObservation | null => ...;
```

- [ ] **Step 1: Write factory/descriptor RED tests**

Parameterize dispatch tests across `paper.ocr` and `book.ocr`. Both accept only current `missing|in_progress`, own exact generation paths, expose one exact `ocr-generation` capability, accept coherent `partial|created|reconciled`, reject source/profile/path/progress drift, and never expose generic new-work OCR or fixed legacy outputs.

- [ ] **Step 2: Run Workflow operation RED**

```bash
python3 -m pytest tests/test_workflow_dispatch.py -q -k 'ocr_generation'
```

Expected: failures because `book.ocr` and the shared factory do not exist.

- [ ] **Step 3: Register both operation identities**

Keep `paper.ocr`, add `book.ocr`, and give both the shared source/lock/work/generation templates. Remove OCR writer targets from both Prepare rows.

- [ ] **Step 4: Implement `makeOcrGenerationRow()`**

Move generic request, receipt, coherence, and capability logic out of the Paper row. Stamp operation/kind through config. Exact material, generation, path, and profile values remain host-stamped or `const`-bound. Put the one closed capsule parser and shared TypeScript types in `contracts/ocr-generation.mts`. Instantiate the factory once per catalog and delete duplicated Paper OCR schema helpers.

- [ ] **Step 5: Run operation GREEN and TypeScript check**

```bash
python3 -m pytest tests/test_workflow_dispatch.py -q -k 'ocr_generation or paper_prepare or book_prepare'
npx tsc --noEmit
```

Expected: tests and TypeScript pass.

- [ ] **Step 6: Commit the shared operation contract**

```bash
git add scripts/schemas/operations.py scripts/workflows/operations/rows/ocr-generation.mts \
  scripts/workflows/contracts/ocr-generation.mts \
  scripts/workflows/operations/rows/paper.mts scripts/workflows/operations/rows/book.mts \
  scripts/workflows/operations/catalogs/paper.mts scripts/workflows/operations/catalogs/book.mts \
  tests/test_workflow_dispatch.py
git commit -m "refactor(workflow): share OCR operation contracts"
```

---

### Task 4: Paper adapter migration

**Files:**
- Modify: `scripts/workflows/contracts/paper.mts`
- Modify: `scripts/workflows/operations/rows/paper.mts`
- Modify: `scripts/workflows/plans/paper.mts`
- Modify: `scripts/workflows/shared/material-result.mts`
- Modify: `tests/test_material_result.py`
- Modify: `tests/test_material_plans.py`

**Interfaces:**
- Consumes: shared generation status and `paper.ocr` row.
- Produces: Paper Prepare `prepared|ocr_required`; committed generation-text verification; one OCR transaction followed by `needs_observation`.

- [ ] **Step 1: Rewrite Paper RED journeys against the common capsule**

Keep useful uncommitted journeys for direct text, `ocr_required`, partial progress, committed generation text, invalid/unknown stop, acquire-observe, source selection, and final artifacts. Replace `paper.ocr.request/0.1`, Paper-only profile/path logic, and `paper-ocr` assertions with common names.

Add a 33-page Tesseract-only journey proving `32 -> 33 -> committed`, and a 17-page DS journey proving `16 -> 17 -> committed`. Each writer completion returns `needs_observation` before another operation.

- [ ] **Step 2: Run Paper RED**

```bash
python3 -m pytest tests/test_material_result.py tests/test_material_plans.py -q -k 'paper and ocr'
```

Expected: failures while Paper still parses the Paper-only capsule.

- [ ] **Step 3: Bind Paper to the shared capsule**

Remove Paper-owned generation-key/profile parsing. Introduce one shared Workflow capsule parser for Paper and Book. Admit status only when material key, source, profile, generation key, and derived Paper root match the exact observation.

- [ ] **Step 4: Keep Paper Prepare thin**

`paper.prepare` writes only `processing/papers/{slug}/source.txt` for a direct source. It returns `ocr_required` only for an unreadable direct PDF. For `generation_text`, it reads immutable text and returns `prepared` without copying it. Fixed legacy recovery files remain read-only and unselectable.

- [ ] **Step 5: Route one transaction per invocation**

Implement this control shape:

```ts
if (generation.state === "in_progress") {
  await dispatch("paper.ocr", generation);
  return needsObservation(route);
}
const prepared = await dispatch("paper.prepare", input);
if (prepared.terminal.disposition === "ocr_required") {
  await dispatch("paper.ocr", missingGeneration);
  return needsObservation(route);
}
```

Committed generation text enters Analyse. Invalid/unknown stops. Acquire completion observes the new source before Prepare.

- [ ] **Step 6: Run Paper GREEN and regressions**

```bash
python3 -m pytest tests/test_material_result.py tests/test_material_plans.py -q
```

Expected: all pass, including owner continuation, source selection, Audit stability, Author, and Paper tests.

- [ ] **Step 7: Commit Paper adapter**

```bash
git add scripts/workflows/contracts/paper.mts scripts/workflows/operations/rows/paper.mts \
  scripts/workflows/plans/paper.mts scripts/workflows/shared/material-result.mts \
  tests/test_material_result.py tests/test_material_plans.py
git commit -m "refactor(paper): consume shared OCR generations"
```

---

### Task 5: Book adapter and released-progress migration

**Files:**
- Modify: `scripts/workflows/contracts/book.mts`
- Modify: `scripts/workflows/operations/rows/book.mts`
- Modify: `scripts/workflows/plans/book.mts`
- Modify: `scripts/status/status.py`
- Modify: `tests/test_material_plans.py`
- Modify: `tests/test_material_result.py`
- Modify: `tests/test_status_cli.py`
- Modify: `tests/test_workflow_dispatch.py`

**Interfaces:**
- Consumes: shared generation capsule, `book.ocr` row, explicit `legacy_ocr` status.
- Produces: Book Prepare `ocr_required`; generation PDF/text input; legacy progress completion without new legacy state.

- [ ] **Step 1: Add Book generation and legacy RED journeys**

Add tests proving readable direct PDF skips OCR; unreadable PDF returns `ocr_required`; committed generation enters chapter planning; invalid/unknown stops; released legacy progress uses only the legacy executor; no legacy progress starts a current generation; a completed fixed recovery is reused only when a usable chapter manifest binds its exact input identity; and Paper/Book capsule parsers accept the same keys.

- [ ] **Step 2: Run Book RED**

```bash
python3 -m pytest tests/test_material_plans.py tests/test_material_result.py \
  tests/test_status_cli.py tests/test_workflow_dispatch.py -q -k 'book and ocr'
```

Expected: failures because Book still embeds fixed-path OCR in `book.prepare`.

- [ ] **Step 3: Add common capsule and explicit legacy parsing**

Admit `facts.ocr_generation` through the shared parser. Parse `legacy_ocr` separately and require its released schema, source SHA/path, output, pages, part inventory, and current source identity.

- [ ] **Step 4: Make Book Prepare return `ocr_required`**

Remove active generic OCR from new Book Prepare requests. A direct unreadable PDF returns complete `disposition="ocr_required"` with no chapter output. A committed generation supplies exact recovery PDF/text while retaining TOC, pattern, manual structure, chapter commit, and manifest behavior.

- [ ] **Step 5: Route current and legacy OCR without overlap**

Use this precedence:

1. usable existing chapter manifest/output set;
2. valid active legacy progress -> one legacy range -> `needs_observation`;
3. committed current generation -> Book Prepare;
4. in-progress generation -> one `book.ocr` -> `needs_observation`;
5. direct Prepare -> `ocr_required` -> one `book.ocr` -> `needs_observation`.

An observation exposing both writable legacy progress and a current generation returns `workflow.incoherent_observation` without a writer.

The compatibility action in step 2 remains an explicitly bounded `book.prepare` mode because the released command writes Book's fixed recovery paths and cannot satisfy the shared `book.ocr` row. Only a validated `legacy_ocr` observation enables its exact `quasi-extract ocr --resume ...` capability. Its receipt disposition is `legacy_partial|legacy_completed`; either result immediately returns `needs_observation`. Normal Book Prepare requests never include that capability and cannot create legacy progress.

- [ ] **Step 6: Run Book GREEN and chapter regressions**

```bash
python3 -m pytest tests/test_material_plans.py tests/test_material_result.py \
  tests/test_status_cli.py tests/test_workflow_dispatch.py -q
```

Expected: all pass, including Book identity/year gates, chapter recovery, Author, and Topic.

- [ ] **Step 7: Commit Book adapter**

```bash
git add scripts/workflows/contracts/book.mts scripts/workflows/operations/rows/book.mts \
  scripts/workflows/plans/book.mts scripts/status/status.py tests/test_material_plans.py \
  tests/test_material_result.py tests/test_status_cli.py tests/test_workflow_dispatch.py
git commit -m "refactor(book): migrate to shared OCR generations"
```

---

### Task 6: Runtime guidance, generated artifacts, and orchestration coherence

**Files:**
- Modify: `agents/extract-agent.md`
- Modify: `skills/collect-material/SKILL.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/PDF_PIPELINE.md`
- Modify: `tests/test_skill_orchestration.py`
- Regenerate: `scripts/workflows/artifact-contracts/generated.mjs`
- Regenerate: `scripts/workflows/artifact-contracts/generated.d.mts`
- Regenerate: `workflows/*.mjs`

**Interfaces:**
- Consumes: shared core and both adapters.
- Produces: current runtime guidance, artifact projections, named bundles, and exact Collect verification.

- [ ] **Step 1: Add orchestration/docs RED assertions**

Assert active guidance names one `ocr-generation` capability, DS 16/Tesseract 32 ownership, sequential fresh observation, and material-specific consumers. Assert no active `paper-ocr`, no new-work fixed Book resume, and no background OCR. Keep tests semantic rather than matching prose sentences.

- [ ] **Step 2: Run orchestration RED**

```bash
python3 -m pytest tests/test_skill_orchestration.py tests/test_dead_names.py -q
```

Expected: failures because current guidance names Paper-only OCR and active fixed Book resume.

- [ ] **Step 3: Update Agent, Skill, and maintainer contracts**

Give Extract Agent one common OCR transaction method: run the exact capability once, preserve CLI evidence, and return. Keep Paper/Book Prepare sections for professional readability/chapter decisions. Collect observes the shared capsule and verifies selected Paper text or Book chapter artifacts, never private parts. Document Translation layout exclusion and released Book legacy completion. Apply identical AGENTS/CLAUDE edits.

- [ ] **Step 4: Build generated contracts and bundles**

```bash
npm run build:workflows
npm run check:workflows
```

Expected: seven bundles and artifact projections are current; TypeScript passes.

- [ ] **Step 5: Run orchestration GREEN**

```bash
python3 -m pytest tests/test_skill_orchestration.py tests/test_dead_names.py -q
cmp -s CLAUDE.md AGENTS.md
```

Expected: tests pass and `cmp` exits 0.

- [ ] **Step 6: Commit runtime/build coherence**

```bash
git add agents/extract-agent.md skills/collect-material/SKILL.md AGENTS.md CLAUDE.md \
  docs/ARCHITECTURE.md docs/PDF_PIPELINE.md tests/test_skill_orchestration.py \
  scripts/workflows/artifact-contracts/generated.mjs \
  scripts/workflows/artifact-contracts/generated.d.mts workflows
git commit -m "docs: define shared OCR generation runtime"
```

---

### Task 7: Completion audit and 0.65.30 release

**Files:**
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `docs/CHANGELOG.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified 0.65.30 on `origin/main` with a clean worktree.

- [ ] **Step 1: Audit every spec completion criterion**

```bash
test ! -e scripts/extract/paper_ocr.py
! rg -n 'paper-ocr' agents skills scripts workflows AGENTS.md CLAUDE.md docs/ARCHITECTURE.md docs/PDF_PIPELINE.md
rg -n 'chunk_pages.*16|"chunk_pages": 16' scripts tests docs
rg -n 'chunk_pages.*32|"chunk_pages": 32' scripts tests docs
rg -n 'makeOcrGenerationRow' scripts/workflows/operations
rg -n 'quasi-extract ocr .*--resume' scripts/workflows agents skills
```

The last search may contain only an explicitly labelled legacy executor reference; no new-work capability may invoke it.

- [ ] **Step 2: Run focused release suites**

```bash
python3 -m pytest -q \
  tests/test_extract_cli.py tests/test_status_cli.py tests/test_workflow_dispatch.py \
  tests/test_material_result.py tests/test_material_plans.py tests/test_topic_plan.py \
  tests/test_skill_orchestration.py tests/test_dead_names.py
npm run check:workflows
```

Expected: all pass and no generated file is stale.

- [ ] **Step 3: Run the full plugin-environment suite**

```bash
env PYTHONPATH=/Users/ramudai/Library/Python/3.9/lib/python/site-packages \
  CLAUDE_PLUGIN_DATA=/private/tmp/quasi-release-06530 \
  /Users/ramudai/.claude/plugins/data/quasi-ramu/.venv/bin/python -m pytest -q
```

Expected: every collected test passes. Third-party warnings may be reported, but no test failure or silent platform-contract skip is acceptable.

- [ ] **Step 4: Bump and validate 0.65.30**

Set both manifest versions to `0.65.30`. Prepend a dated changelog entry describing the shared generation core, 16/32 ranges, thin adapters, immutable bundle, and one-way Book legacy recovery.

```bash
claude plugin validate .
cmp -s CLAUDE.md AGENTS.md
git diff --check
npm run check:workflows
```

Expected: all exit 0.

- [ ] **Step 5: Commit the release**

```bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json docs/CHANGELOG.md
git commit -m "release: 0.65.30"
```

- [ ] **Step 6: Push and prove remote completion**

```bash
git push origin main
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

Expected: push succeeds, status is empty, and local/remote hashes match.

# Material Success Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make long scanned Book OCR resumable and make Paper acquisition reliably deliver verified PDF or text sources with bounded, typed failure and Webpage routing.

**Architecture:** Book OCR becomes a declared status-backed sequence of atomic foreground page-range transactions; Paper source becomes a closed PDF/TXT alternative selected by status and Workflow. Download validation and deadline ownership remain deterministic CLI responsibilities, while material routing remains a typed Workflow result transported by Collect.

**Tech Stack:** Python 3.9, PyMuPDF, pytest, TypeScript ES2022 Workflow sources, JSON Schema draft-07, esbuild, Claude Code plugin Skills/Agents.

**Spec:** `docs/superpowers/specs/2026-08-24-material-success-reliability-design.md`

## Global Constraints

- No detached process, daemon, `nohup`, TLS-verification bypass, or browser challenge automation.
- Translation `--layout` OCR remains unchanged.
- Book OCR progress must be an exact status-projected artifact, not a Skill cursor.
- Paper source is exactly one usable `sources/{slug}.pdf` or `sources/{slug}.txt`; both is an error.
- Every new writer uses sibling staging, fsync, exact output validation, and atomic publication.
- Generated Workflow files are changed only through `npm run build:workflows`.
- `CLAUDE.md` and `AGENTS.md` remain byte-for-byte identical.
- Each behavior change follows RED, verified failure, minimal GREEN, then regression verification.

---

### Task 1: Resumable OCR transaction engine

**Files:**
- Create: `scripts/extract/ocr_resume.py`
- Modify: `scripts/extract/extract.py`
- Modify: `bin/quasi-extract`
- Test: `tests/test_extract_cli.py`

**Interfaces:**
- Consumes: readable input PDF, exact output PDF, exact progress JSON, engine, chunk size.
- Produces: `run_ocr_step(input_path, output_path, progress_path, engine, chunk_pages, language) -> dict` and CLI JSON status `partial|ok|existing|failed`.

- [ ] **Step 1: Write failing CLI and transaction tests**

Add tests which invoke real Python functions with a fake range OCR runner and assert:

```python
assert first["status"] == "partial"
assert first["progress"]["completed_pages"] == 2
assert second["status"] == "partial"
assert second["progress"]["completed_pages"] == 4
assert third["status"] == "ok"
assert fitz.open(output).page_count == 5
```

Also assert one range per call, exact page order, `--resume` argument closure,
source hash mismatch rejection, corrupt part rejection, no-clobber collision,
lock contention, killed-range recovery, and progress/parts cleanup only after
final publication.

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest tests/test_extract_cli.py -q -k 'ocr_resume or ocr_step'
```

Expected: collected assertion failures because resumable flags/module/status do not exist.

- [ ] **Step 3: Implement closed progress parsing and atomic JSON writes**

Create `OcrProgress` validation for exactly:

```python
{
    "schema_version": "quasi.ocr.progress/0.1",
    "input_path": str,
    "output_path": str,
    "source_sha256": r"[0-9a-f]{64}",
    "engine": "dsocr2" | "tesseract",
    "chunk_pages": int,
    "total_pages": int,
    "completed_pages": int,
    "next_page": int | None,
}
```

Use an adjacent flock, a sibling temporary JSON, `flush+fsync`, `os.replace`,
and parent-directory fsync. Reject symlink/non-regular progress, output, part,
or lock targets.

- [ ] **Step 4: Implement one-range extraction, validation, and merge**

Slice the next page range with PyMuPDF, invoke the existing OCR engine through
an injectable runner, require a readable PDF with the exact range page count,
atomically publish the part, then update progress. Merge validated parts with
`insert_pdf`; publish the final only when merged page count equals source page
count. Preserve existing ordinary `_run_ocr` behavior when `--resume` is absent.

- [ ] **Step 5: Verify GREEN and ordinary OCR regression**

Run:

```bash
python3 -m pytest tests/test_extract_cli.py -q
```

Expected: all extraction tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/extract/ocr_resume.py scripts/extract/extract.py bin/quasi-extract tests/test_extract_cli.py
git commit -m "feat(extract): resume book OCR by page range"
```

### Task 2: Project OCR progress through Book status and Workflow

**Files:**
- Modify: `scripts/schemas/operations.py`
- Modify: `scripts/status/status.py`
- Modify: `scripts/workflows/contracts/book.mts`
- Modify: `scripts/workflows/operations/rows/book.mts`
- Modify: `scripts/workflows/plans/book.mts`
- Modify: `agents/extract-agent.md`
- Modify: `docs/PDF_PIPELINE.md`
- Test: `tests/test_status_cli.py`
- Test: `tests/test_material_result.py`
- Test: `tests/test_workflow_dispatch.py`
- Test: `tests/test_material_plans.py`

**Interfaces:**
- Consumes: `processing/chapters/{slug}/ocr.progress.json`.
- Produces: Book status `facts.ocr_progress` and exact plan transition from `book.prepare.ocr_in_progress` to `needs_observation`.

- [ ] **Step 1: Write failing status, request, and plan tests**

Assert a valid progress document projects:

```json
{
  "path": "processing/chapters/exact-book/ocr.progress.json",
  "present": true,
  "usable": true,
  "source_sha256": "...",
  "total_pages": 100,
  "completed_pages": 8,
  "next_page": 9
}
```

Assert malformed progress is present/unusable; partial Prepare returns
`needs_observation` for the same Book route; retryable false and other issue
codes remain blocked; the next observation with higher `completed_pages`
dispatches Prepare again.

- [ ] **Step 2: Verify RED**

```bash
python3 -m pytest tests/test_status_cli.py tests/test_material_result.py tests/test_workflow_dispatch.py tests/test_material_plans.py -q -k 'ocr_progress or ocr_in_progress'
```

Expected: assertion failures for missing artifact/facts/transition.

- [ ] **Step 3: Add the catalog and status projection**

Add `ocrProgress: processing/chapters/{slug}/ocr.progress.json` to
`book.prepare`. Parse the closed document without following symlinks and expose
the fixed progress projection. Extend `BookStatusFacts` and its exact parser.

- [ ] **Step 4: Add the specialist and plan contract**

Add the resumable command and progress ref to the Book Prepare envelope. The
Extract Agent executes one step and returns exact retryable issue
`book.prepare.ocr_in_progress` on `partial`. Match only that qualified code in
the Book plan and return `needsObservationMaterialResult` with the canonical
Book route and existing continuation.

- [ ] **Step 5: Build and verify GREEN**

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_status_cli.py tests/test_material_result.py tests/test_workflow_dispatch.py tests/test_material_plans.py -q
```

Expected: build/current checks pass and affected tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/schemas/operations.py scripts/status/status.py scripts/workflows/contracts/book.mts scripts/workflows/operations/rows/book.mts scripts/workflows/plans/book.mts agents/extract-agent.md docs/PDF_PIPELINE.md tests workflows
git commit -m "feat(book): recover OCR through exact status"
```

### Task 3: Make PDF and text first-class Paper source alternatives

**Files:**
- Modify: `scripts/schemas/operations.py`
- Modify: `scripts/status/status.py`
- Modify: `scripts/workflows/contracts/paper.mts`
- Modify: `scripts/workflows/operations/rows/paper.mts`
- Modify: `scripts/workflows/plans/paper.mts`
- Modify: `agents/download-agent.md`
- Modify: `agents/extract-agent.md`
- Modify: `skills/collect-material/SKILL.md`
- Test: `tests/test_status_cli.py`
- Test: `tests/test_material_result.py`
- Test: `tests/test_workflow_dispatch.py`
- Test: `tests/test_material_plans.py`
- Test: `tests/test_skill_orchestration.py`

**Interfaces:**
- Consumes: fixed observations for `sources/{slug}.pdf` and `.txt`.
- Produces: selected exact Paper source or typed `paper.source_conflict`.

- [ ] **Step 1: Write failing source-alternative tests**

Cover no source, PDF only, text only, and both. Assert Acquire receives both
exact outputs, may complete with either, Prepare receives the selected path,
complete returns that same source, and both usable paths stop before any Agent
dispatch with `paper.source_conflict`.

- [ ] **Step 2: Verify RED**

```bash
python3 -m pytest tests/test_status_cli.py tests/test_material_result.py tests/test_workflow_dispatch.py tests/test_material_plans.py tests/test_skill_orchestration.py -q -k 'paper and (text_source or source_conflict or source_alternative)'
```

Expected: assertion failures because Paper status and rows still require one PDF.

- [ ] **Step 3: Change the artifact/status contract**

Define `outputPdf`, `outputText`, `sourcePdf`, and `sourceText` catalog roles.
Project `facts.sources` as ordered `pdf,text` rows. Parse exactly those rows and
add one helper which returns zero/one selected usable source or conflict.

- [ ] **Step 4: Change Acquire and Prepare envelopes**

Acquire write scope contains both exact paths and complete `output_path` is an
enum of the pair. Prepare context receives `source` from the plan and verifies
it is one of its fixed PDF/TXT source refs. Update Agent prose and Collect's
post-status artifact matching without putting selection policy in the Skill.

- [ ] **Step 5: Verify GREEN and build**

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_status_cli.py tests/test_material_result.py tests/test_workflow_dispatch.py tests/test_material_plans.py tests/test_skill_orchestration.py -q
```

- [ ] **Step 6: Commit**

```bash
git add scripts/schemas/operations.py scripts/status/status.py scripts/workflows/contracts/paper.mts scripts/workflows/operations/rows/paper.mts scripts/workflows/plans/paper.mts agents/download-agent.md agents/extract-agent.md skills/collect-material/SKILL.md tests workflows
git commit -m "feat(paper): accept verified text sources"
```

### Task 4: Normalize text sources and retain scholarly HTML from any host

**Files:**
- Modify: `scripts/extract/extract_text.py`
- Modify: `scripts/download/download.py`
- Test: `tests/test_extract_cli.py`
- Test: `tests/test_download_cli.py`

**Interfaces:**
- Consumes: UTF-8 `.txt` or article-like HTTP body with expected identity.
- Produces: atomic normalized text or fenced exact text candidate.

- [ ] **Step 1: Write failing normalization and HTML tests**

Assert UTF-8 text normalizes CRLF and final newline atomically without calling
`pdftotext`. Assert article HTML from an unrecognized repository host is saved
when full title+author and article structure match. Assert metadata-only,
paywall, login, challenge, wrong-title, and navigation-heavy HTML are rejected.

- [ ] **Step 2: Verify RED**

```bash
python3 -m pytest tests/test_extract_cli.py tests/test_download_cli.py -q -k 'text_input or generic_article_html or article_text_fallback'
```

- [ ] **Step 3: Implement text normalization**

Branch on `.txt`; decode strict UTF-8, normalize `\r\n|\r` to `\n`, add one
final newline, fsync a sibling stage, replace exact output, and emit existing
signals. PDF behavior remains byte-for-byte routed through `pdftotext`.

- [ ] **Step 4: Remove host-name gating from text fallback**

Offer the existing evidence predicate to every non-PDF response in direct and
EZProxy routes. Preserve exact identity and article markers; do not lower the
500-character threshold or admit login/challenge MIME shapes. Ensure returned
text enters existing uncertain/verified candidate and cleanup handling.

- [ ] **Step 5: Verify GREEN**

```bash
python3 -m pytest tests/test_extract_cli.py tests/test_download_cli.py -q
```

- [ ] **Step 6: Commit**

```bash
git add scripts/extract/extract_text.py scripts/download/download.py tests/test_extract_cli.py tests/test_download_cli.py
git commit -m "feat(paper): preserve verified article text"
```

### Task 5: Strong PDF validation and bounded Paper fetch

**Files:**
- Modify: `scripts/download/download.py`
- Modify: `agents/download-agent.md`
- Modify: `scripts/workflows/operations/rows/paper.mts`
- Test: `tests/test_download_cli.py`
- Test: `tests/test_workflow_dispatch.py`

**Interfaces:**
- Consumes: provider response bytes and monotonic fetch budget.
- Produces: readable PDF candidate, `download_failed`, or `budget_exhausted` JSON.

- [ ] **Step 1: Write failing validation and budget tests**

Use a large HTML-free garbage payload with `application/pdf`, a truncated PDF,
and a valid one-page PDF. Assert only the valid PDF passes every provider
boundary and `_accept_to_output(kind="paper")`. Inject a clock/request that
crosses the deadline and assert JSON `budget_exhausted`, non-zero exit, cleanup,
and no later provider calls. Assert certificate-verification errors get one
attempt for the affected mirror.

- [ ] **Step 2: Verify RED**

```bash
python3 -m pytest tests/test_download_cli.py tests/test_workflow_dispatch.py -q -k 'readable_pdf or paper_budget or certificate_failure'
```

- [ ] **Step 3: Implement one readable-PDF predicate**

Require a header within the PDF prefix, `fitz.open(stream=...,filetype="pdf")`,
and positive page count. Use it in response classification, Sci-Hub, provider
temp writes, and paper accept under the output lock. Keep Book container rules
unchanged.

- [ ] **Step 4: Implement the deadline**

Add `PaperFetchBudget`, `--budget-seconds` parsing (30–540, default 480), and
remaining-time capping for network timeout, retry delay, EZProxy wait, and
provider transitions. Return the exact budget terminal before attempting work
that cannot fit. Preserve completed uncertain candidates in the returned
envelope; delete incomplete current writes.

- [ ] **Step 5: Map the typed outcome**

Document the Agent mapping to `paper.acquire_blocked + retryable:true` and add
the exact capability flag to the Paper request. Ensure a budget result is not
called `all_sources_failed` and is not automatically replayed in one Agent.

- [ ] **Step 6: Verify GREEN**

```bash
python3 -m pytest tests/test_download_cli.py tests/test_workflow_dispatch.py -q
```

- [ ] **Step 7: Commit**

```bash
git add scripts/download/download.py agents/download-agent.md scripts/workflows/operations/rows/paper.mts tests/test_download_cli.py tests/test_workflow_dispatch.py
git commit -m "fix(download): validate and bound paper fetches"
```

### Task 6: Route verified web articles to Webpage

**Files:**
- Modify: `scripts/workflows/shared/material-result.mts`
- Modify: `scripts/workflows/operations/rows/search.mts`
- Modify: `scripts/workflows/plans/paper.mts`
- Modify: `scripts/workflows/plans/author.mts`
- Modify: `scripts/workflows/plans/topic.mts`
- Modify: `agents/metadata-agent.md`
- Modify: `skills/collect-material/SKILL.md`
- Test: `tests/test_material_result.py`
- Test: `tests/test_workflow_dispatch.py`
- Test: `tests/test_material_plans.py`
- Test: `tests/test_topic_plan.py`
- Test: `tests/test_skill_orchestration.py`

**Interfaces:**
- Consumes: failed Search terminal `material.webpage_redirect` with one exact public URL.
- Produces: direct Paper result `next:{kind:"webpage",url}`; compositions stop instead of silently substituting.

- [ ] **Step 1: Write failing redirect tests**

Cover URL validation, missing URL incoherence, direct Paper next route, Collect
Webpage provisional envelope, and Author/Topic refusal to treat the redirect as
a representative Paper. Keep thesis/working-paper unsupported failures unchanged.

- [ ] **Step 2: Verify RED**

```bash
python3 -m pytest tests/test_material_result.py tests/test_workflow_dispatch.py tests/test_material_plans.py tests/test_topic_plan.py tests/test_skill_orchestration.py -q -k 'webpage_redirect'
```

- [ ] **Step 3: Extend the closed contracts**

Add optional `webpage_url` only to Paper Search failed terminal schema and
cross-field validation requiring it for the exact redirect code. Extend
`MaterialNextRoute` with `{kind:"webpage",url:string}`. Validate public HTTP(S)
URL using the existing Webpage URL parser rather than duplicating URL policy.

- [ ] **Step 4: Implement direct and composed behavior**

Direct Paper converts the qualified failed receipt to complete/no artifacts/
Webpage next. Collect starts the existing Webpage provisional flow. Author and
Topic return a typed unsupported-member issue without changing membership or
creating a child Webpage.

- [ ] **Step 5: Verify GREEN and build**

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_material_result.py tests/test_workflow_dispatch.py tests/test_material_plans.py tests/test_topic_plan.py tests/test_skill_orchestration.py -q
```

- [ ] **Step 6: Commit**

```bash
git add scripts/workflows agents/metadata-agent.md skills/collect-material/SKILL.md tests workflows
git commit -m "feat(collect): route web articles to webpage"
```

### Task 7: Documentation, release, and end-to-end verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/PDF_PIPELINE.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Test: relevant existing test suites

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: released plugin version with synchronized docs/manifests/generated bundles.

- [ ] **Step 1: Update maintained contracts**

Document Paper PDF/TXT source alternatives, Book resumable OCR progress, typed
Paper budget terminal, and Webpage next route. Add one newest-first changelog
entry explaining the observed incidents and why no background job was added.
Mirror AGENTS/CLAUDE byte-for-byte.

- [ ] **Step 2: Bump release metadata**

Bump patch version in both plugin manifests to the same new version. Do not
change `.codex-plugin/plugin.json`.

- [ ] **Step 3: Rebuild and run focused suites**

```bash
npm run build:workflows
npm run check:workflows
python3 -m pytest tests/test_extract_cli.py tests/test_download_cli.py tests/test_status_cli.py tests/test_material_result.py tests/test_workflow_dispatch.py tests/test_material_plans.py tests/test_topic_plan.py tests/test_skill_orchestration.py tests/test_workflow_entries.py -q
```

- [ ] **Step 4: Run complete release gates**

```bash
python3 -m pytest -q
npm run check:workflows
cmp -s CLAUDE.md AGENTS.md
claude plugin validate .
git diff --check
```

Expected: all commands exit 0; macOS-gated tests execute on this host rather
than being skipped for missing platform support.

- [ ] **Step 5: Audit requirements against the spec**

For each numbered acceptance item in the design, record the exact test name or
command output that proves it. Confirm no new process remains, no source/temp
artifact was created in the repository, generated bundles are current, and
only intended tracked files changed.

- [ ] **Step 6: Commit and push**

```bash
git add AGENTS.md CLAUDE.md docs .claude-plugin scripts agents skills tests workflows bin
git commit -m "release: quasi 0.65.27"
git push origin main
```


# Book Prepare Boundary Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Book Prepare from rejecting valid generations because of absolute receipt paths or choosing normalized text as a split input, and classify rejected private staging manifests as known failures.

**Architecture:** Keep exact-path validation in the owning Book descriptor row and express its project-relative path rule in the model-facing schema. Bind split commands to the two exact PDF refs in the request envelope. Reclassify only `ChapterFailure` raised by private staged-manifest preparation; do not change durable-manifest validation.

**Tech Stack:** TypeScript `.mts` Workflow sources built with esbuild/tsc, Python chapter transaction code, pytest, Claude Code plugin manifests.

## Global Constraints

- Release version is exactly `0.65.4`.
- No backward-compatibility reader, migration, retry, replay, cleanup command, hidden state, or book-specific heuristic.
- Do not relax manifest validation or convert model-returned absolute paths in the host.
- `source.txt` and `ocr.txt` are reading evidence, never `quasi-extract split` positional inputs.
- Split positional inputs are only the request's exact accepted PDF or exact OCR recovery PDF.
- Existing invalid durable manifests remain ownership-unsafe and retain their current blocked/unknown classification.
- `CLAUDE.md` and `AGENTS.md` remain byte-for-byte identical.

---

### Task 1: Close the Book Prepare Workflow boundary

**Files:**
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `scripts/workflows/operations/rows/book.mts`
- Generated: `workflows/book.mjs`

**Interfaces:**
- Consumes: Book Prepare refs `source`, `normalized`, `recoverySource`, `recoveryText`, `outputDir`, and `manifest`.
- Produces: a model-facing artifact `path` schema that rejects POSIX absolute paths, and request capabilities whose split commands name only `source` or `recoverySource` as the positional input.

- [ ] **Step 1: Write failing Workflow contract tests**

Add `import re` and two tests. The first reads the runtime-produced Book Prepare schema and applies its artifact-path pattern to hand-derived examples:

```python
def test_book_prepare_artifact_schema_requires_project_relative_paths() -> None:
    prepared = _prepare(
        "book.prepare",
        context=_context(format="pdf", source="sources/exact-material.pdf"),
    )
    path_schema = prepared["options"]["schema"]["properties"]["artifacts"][
        "items"
    ]["properties"]["path"]

    assert path_schema["minLength"] == 1
    assert re.search(
        path_schema["pattern"],
        "processing/chapters/exact-material/01-opening.txt",
    )
    assert not re.search(
        path_schema["pattern"],
        "/Users/example/vault/processing/chapters/exact-material/01-opening.txt",
    )
```

The second reads the actual JSON request, isolates split capabilities, and checks their positional inputs:

```python
def test_book_prepare_split_capabilities_bind_exact_pdf_inputs() -> None:
    prepared = _prepare(
        "book.prepare",
        context=_context(format="pdf", source="sources/exact-material.pdf"),
    )
    request = _prompt_request(prepared["prompt"])
    split = [
        capability
        for capability in request["capabilities"]
        if capability.startswith("quasi-extract split ")
    ]
    source_prefix = "quasi-extract split 'sources/exact-material.pdf' "
    recovery_prefix = (
        "quasi-extract split "
        "'processing/chapters/exact-material/ocr.pdf' "
    )

    assert split
    assert any(capability.startswith(source_prefix) for capability in split)
    assert any(capability.startswith(recovery_prefix) for capability in split)
    assert all(
        capability.startswith((source_prefix, recovery_prefix))
        for capability in split
    )
    assert all("source.txt" not in capability for capability in split)
    assert all("ocr.txt" not in capability for capability in split)
```

- [ ] **Step 2: Run the two tests and verify RED**

Run:

```bash
pytest tests/test_workflow_dispatch.py -q -k 'book_prepare_artifact_schema_requires_project_relative_paths or book_prepare_split_capabilities_bind_exact_pdf_inputs'
```

Expected: both tests fail because the path schema is unrestricted and split capabilities still advertise a generic `INPUT`.

- [ ] **Step 3: Implement the minimum descriptor-row change**

In `preparedArtifactSchema`, keep `type: "string"` and add only the constraints needed for a non-empty POSIX project-relative value:

```typescript
path: { type: "string", minLength: 1, pattern: "^[^/]" },
```

In the Book Prepare envelope, replace the three generic split capabilities with PDF-only capabilities produced for `[refs.source, refs.recoverySource]`. Quote each exact input and `refs.outputDir` with the existing `posixSingleQuote`; keep the three existing forms (`--method toc|pattern`, `--chapters JSON`, and single-range repair). Do not add a new parser, validator, retry, or prose rule.

- [ ] **Step 4: Build and verify GREEN**

Run:

```bash
npm run build:workflows
pytest tests/test_workflow_dispatch.py -q -k 'book_prepare_artifact_schema_requires_project_relative_paths or book_prepare_split_capabilities_bind_exact_pdf_inputs'
npm run check:workflows
```

Expected: focused tests pass, generated bundle is current, and strict TypeScript checking passes.

- [ ] **Step 5: Commit Task 1**

```bash
git add tests/test_workflow_dispatch.py scripts/workflows/operations/rows/book.mts workflows/book.mjs
git commit -m "fix: bind book prepare paths and split inputs"
```

---

### Task 2: Make private staged-manifest rejection a known failure

**Files:**
- Modify: `tests/test_extract_cli.py`
- Modify: `scripts/extract/chapter_commit.py`

**Interfaces:**
- Consumes: `_prepare_staged_manifest(stage_dir, manifest, fingerprint, initial_identity)` and its classified `ChapterFailure`.
- Produces: the same failure code/message/exit code at the transaction boundary, but with terminal matrix `failed/known`; the canonical output remains untouched.

- [ ] **Step 1: Replace the defensive malformed-writer test with the observed staging-validation case**

Rename `test_book_malformed_stage_is_blocked_unknown_without_final_writes` to `test_book_invalid_private_stage_is_failed_known_without_final_writes`. Replace its builder with this literal duplicate-slot generation:

```python
def build(stage: Path, _previous: dict | None) -> dict:
    (stage / "09_Contents.txt").write_text("contents chapter", encoding="utf-8")
    (stage / "09_Body.txt").write_text("body chapter", encoding="utf-8")
    return {
        "chapters": [
            {
                "slot": "09",
                "title": "Chapter 9 (Contents)",
                "filename": "09_Contents.txt",
                "start_page": 1,
                "end_page": 1,
            },
            {
                "slot": "09",
                "title": "Chapter 9",
                "filename": "09_Body.txt",
                "start_page": 1,
                "end_page": 1,
            },
        ],
        "skipped": [],
    }

rc, receipt = chapter_commit.commit_chapter_set(
    input_path=pdf,
    output_dir=output,
    mode="pattern",
    options={"pattern": "default"},
    max_chapters=50,
    build_stage=build,
)

assert rc == 1
assert receipt["status"] == "failed"
assert receipt["failure"]["code"] == "manifest_invalid"
assert receipt["failure"]["outcome"] == "known"
assert receipt["manifest_exists"] is False
assert receipt["manifest_fingerprint"] is None
assert output.exists() is False
assert list(tmp_path.glob(".chapters.stage-*")) == []
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
pytest tests/test_extract_cli.py::test_book_invalid_private_stage_is_failed_known_without_final_writes -q
```

Expected: it fails with actual `status == "blocked"` and `failure.outcome == "unknown"`.

- [ ] **Step 3: Reclassify at the private-stage boundary**

Wrap only the `_prepare_staged_manifest(...)` call:

```python
try:
    staged_manifest = _prepare_staged_manifest(
        stage_dir, staged_manifest, fingerprint, initial_identity
    )
except ChapterFailure as exc:
    raise ChapterFailure(
        exc.code,
        exc.message,
        exit_code=exc.exit_code,
    ) from exc
```

Do not change `validate_manifest`, `_publish`, existing-manifest paths, or generic exception handling.

- [ ] **Step 4: Verify GREEN and adjacent transaction behavior**

Run:

```bash
pytest tests/test_extract_cli.py::test_book_invalid_private_stage_is_failed_known_without_final_writes -q
pytest tests/test_extract_cli.py -q
```

Expected: the regression and complete extractor suite pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add tests/test_extract_cli.py scripts/extract/chapter_commit.py
git commit -m "fix: classify rejected chapter stages as known"
```

---

### Task 3: Release and verify 0.65.4

**Files:**
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `docs/CHANGELOG.md`

**Interfaces:**
- Consumes: passing Task 1 and Task 2 behavior.
- Produces: synchronized `0.65.4` plugin metadata and a changelog entry describing the two observed failures and the three boundary corrections.

- [ ] **Step 1: Update release metadata and changelog**

Set both manifest versions to `0.65.4`. Add the newest changelog entry stating:

- valid Book TOC generations can no longer be rejected merely because a specialist tries to echo absolute artifact paths; StructuredOutput requires project-relative paths;
- split capabilities bind the accepted/recovery PDF and never advertise normalized text as input;
- invalid private staging manifests are `failed/known` because publication has not begun, while durable invalid manifests remain blocked/unknown;
- no retry, compatibility, cleanup, or relaxed manifest path was added.

- [ ] **Step 2: Run release verification**

Run fresh, complete commands:

```bash
npm run build:workflows
npm run check:workflows
pytest -q
pytest tests/test_dead_names.py tests/test_skill_orchestration.py -q
claude plugin validate .
cmp -s CLAUDE.md AGENTS.md
git diff --check
```

Expected: every command exits 0 with no test failures; both manifest versions are `0.65.4`; generated bundles are current.

- [ ] **Step 3: Commit the release**

```bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json docs/CHANGELOG.md workflows/book.mjs
git commit -m "release: quasi 0.65.4"
```

- [ ] **Step 4: Final review and push**

Review the complete range from `c27a380` through release HEAD, rerun any verification affected by review fixes, then push `main` to `origin/main` and confirm local HEAD equals the remote-tracking HEAD.

# Test Suite Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the test suite's maintenance burden without weakening protection for real regressions or adding speculative failure matrices.

**Architecture:** Keep tests at public behavior and real safety boundaries. Use one pytest collection entry, convert genuinely repeated cases to data tables, migrate Workflow coverage to shared-dispatch and material-plan tests, and delete runners, demos, prose snapshots, and duplicate cases only after equivalent behavior is proven.

**Tech Stack:** pytest, Python standard library AST/subprocess tools, existing shell shims, Node Workflow harness from the material refactor.

## Global Constraints

- Execute this plan only after the material-oriented Workflow refactor plan has completed through its Workflow-test migration and `run-stage` retirement. Task 6 depends on that final state; do not interleave these cleanup commits with the runtime migration.
- Test-line reduction is an outcome, not a target. Preserve every observed production regression and expensive artifact-safety boundary.
- Do not add a material × terminal Cartesian matrix. Test the four terminals once at shared dispatch and only real branches per plan.
- Do not test exact prose, arbitrary source layout, private helper calls, or live provider domain lists when a semantic/public assertion exists.
- Keep atomic replacement, crash fencing, writer serialization, symlink/path rejection, PDF layout, translation coverage, identity validation, schema closure, Crossref venue authority, and secret-out-of-argv coverage.
- A deleted private-helper case must first have equivalent public behavior coverage.
- Run each slice independently and commit it before the next cleanup slice.

---

### Task 1: Establish one pytest entry and remove non-pytest runners

**Files:**

- Create: `pytest.ini`
- Modify: `scripts/search/tests/test_main.py`
- Modify: `scripts/search/tests/test_merge.py`
- Modify: `scripts/search/tests/test_schemas.py`
- Modify: `scripts/search/tests/test_douban_cn_en2zh.py`
- Modify: `scripts/search/tests/test_source_amazon.py`
- Modify: `scripts/search/tests/test_source_crossref.py`
- Modify: `scripts/search/tests/test_source_douban_cn.py`
- Modify: `scripts/search/tests/test_source_goodreads.py`
- Modify: `scripts/search/tests/test_source_googlebooks.py`
- Modify: `scripts/search/tests/test_source_openalex.py`
- Modify: `scripts/search/tests/test_source_openlibrary.py`
- Modify: `scripts/search/tests/test_source_scholar.py`
- Modify: `scripts/search/tests/test_source_storygraph.py`
- Delete: `tests/fixtures/make_synthetic_book.py`
- Delete: `tests/fixtures/make_synthetic_talk.py`
- Delete: `tests/fixtures/make_synthetic_translation_pdf.py`

- [ ] Capture the exact current collection count:

```bash
python3 -m pytest --collect-only -q
```

- [ ] Add root configuration that collects all three existing roots. Do not declare unused markers or speculative fixture infrastructure:

```ini
[pytest]
testpaths = tests scripts/core/tests scripts/search/tests
```

- [ ] Do not add a nine-shim `--help` smoke matrix: it would duplicate existing CLI behavior tests while coupling collection cleanup to bootstrap, Keychain, and venv internals. Preserve the existing process-level `quasi-doctor` shim coverage and the public behavior tests for each Python dispatcher; add a new bin-level test only if collection reveals a concrete untested shim regression.

- [ ] Delete only `main()`, `if __name__ == "__main__"`, and imports used solely by those runners from the 13 nested search test files. Preserve every pytest test function.

- [ ] Confirm the three synthetic generators have no repository or maintained-document references, then delete them. Do not replace them with a new framework.

- [ ] Verify collection still includes all roots and run the suite:

```bash
python3 -m pytest --collect-only -q
python3 -m pytest scripts/core/tests scripts/search/tests -q
python3 -m pytest -q
```

- [ ] Commit.

```bash
git add pytest.ini scripts/search/tests tests/fixtures
git commit -m "test: standardize pytest collection"
```

### Task 2: Consolidate Douban and dead-name coverage

**Files:**

- Modify: `scripts/search/tests/test_source_douban_cn.py`
- Delete: `scripts/search/tests/test_douban_cn_en2zh.py`
- Modify: `tests/test_dead_names.py`
- Modify: `tests/test_doctor_cli.py`
- Modify: `scripts/search/tests/test_source_googlebooks.py`
- Verify: `tests/test_search_cli.py`

- [ ] Move these six unique behavior cases into `test_source_douban_cn.py` before deleting the duplicate module:

```text
test_parse_subject_page_zh_translation_fields
test_parse_subject_page_en_original
test_normalise_zh_translation_to_book_record
test_normalise_handles_missing_fields
test_search_book_english_title_kagi_path_returns_results
test_search_book_blocked_returns_error
```

- [ ] Confirm the main module already covers subject-page Kagi/BeautifulSoup routing, empty query, CJK detection, block detection, canonical subject URL, and original-title queries. Delete the duplicate versions rather than parameterizing two implementations of the same fact.

- [ ] Put the retired Dokobot names and exact active-code scope into `tests/test_dead_names.py`. Remove the now-duplicate `test_doctor_does_not_report_dokobot`, `test_source_googlebooks.py::test_no_dokobot_helpers_remain`, and `test_source_douban_cn.py::test_douban_cn_source_and_tests_have_no_doko_fallback_references`. Keep Doctor JSON, exit-code, dependency, version-drift, and all source behavior tests.

- [ ] Run and commit.

```bash
python3 -m pytest scripts/search/tests/test_source_douban_cn.py tests/test_search_cli.py tests/test_dead_names.py tests/test_doctor_cli.py -q
git add scripts/search/tests tests/test_dead_names.py tests/test_doctor_cli.py
git commit -m "test: consolidate Douban and retired-name coverage"
```

### Task 3: Replace tautologies and prose snapshots with semantic checks

**Files:**

- Modify: `tests/test_translate_coverage.py`
- Modify: `tests/test_tounicode.py`
- Modify: `tests/test_extract_cli.py`
- Modify: `tests/test_subagent_statusline.py`
- Modify: `tests/test_skill_orchestration.py`
- Modify: `tests/test_schema_registry.py`
- Modify: `tests/test_audit_cli.py`
- Modify: `tests/test_citation_review_cards.py`
- Modify: `tests/test_proofread_helper.py`

- [ ] Delete the two wrapper cases that only call production self-assertions:

```text
tests/test_translate_coverage.py::test_self_check
tests/test_tounicode.py::test_self_check
```

- [ ] Replace the backend source-substring ordering assertion with an AST call-order helper that finds `repair_tounicode(outputs...)` and `check_coverage(outputs...)` in the same backend function body and asserts repair precedes coverage. It must fail if either call is missing.

- [ ] Preserve the DS OCR2 invariant with one nested AST-backed test: parse the outer module, extract the literal string assigned to `_RUNNER`, parse that string as Python, locate `load(model_id, None)`, and assert no call supplies `trust_remote_code=True`. Delete overlapping raw-string checks; never relax the invariant.

- [ ] Replace statusline source blacklists with AST boundaries: the refresh path imports only standard-library modules and does not call subprocess/network entry points. Assert runtime output behavior separately.

- [ ] Relax frontmatter routing-hint tests to YAML-parseable, non-empty, single-line descriptions. Remove fixed English prefixes and arbitrary minimum lengths.

- [ ] Keep Talk's literal clickable timestamp shape (`[mm:ss]` and `[h:mm:ss]`) but stop snapshotting surrounding Chinese wording.

- [ ] Keep Audit JSON shape, book/chapter order, fields, and read-only behavior; remove exact Chinese guidance and Markdown spacing snapshots.

- [ ] Remove only the incidental stdout checks `"wrote" in stdout` and `"records_block: existing"`; keep emitted artifacts, idempotence, and parsed content assertions.

- [ ] Run and commit.

```bash
python3 -m pytest tests/test_translate_coverage.py tests/test_tounicode.py tests/test_extract_cli.py tests/test_subagent_statusline.py tests/test_skill_orchestration.py tests/test_schema_registry.py tests/test_audit_cli.py tests/test_citation_review_cards.py tests/test_proofread_helper.py -q
git add tests
git commit -m "test: assert semantics instead of implementation prose"
```

### Task 4: Parameterize repeated download cases while preserving safety partitions

**Files:**

- Modify: `tests/test_download_cli.py`

- [ ] Convert the five existing single-process EZProxy throttle cases into one table with the same setup, clock, sleep, and persisted-timestamp assertions: first call/no wait; remaining interval; future timestamp capped to one interval; zero interval/no-op; corrupt state/no prior call. Keep the cross-process serialization test standalone.

- [ ] Data-drive only the existing pure-function assertions, grouped by the named production function: five `_jstor_pdf_urls_from_article_url` rows (bare stable id, DOI stable id, already-proxied PDF, root miss, foreign-host miss); three `_unproxy_host` rows; four `_is_publisher_host` rows; two `_doi_from_url_path` rows; two `_publisher_pdf_urls_from_article_url` rows; three `_pdf_urls_from_article_url` dispatcher-family rows; and three `_ezproxy_host_suffix` fallback rows. Preserve every expected value. Do not merge `_ezproxy_request_urls`, any HTTP/subprocess test, or transaction/fault tests into these tables.

- [ ] Replace the exact current AA mirror-domain list with the stable runtime contract. Define both variables from the loaded module; require nonempty unique HTTPS URLs whose parsed hostname starts with `annas-archive.` and has a nonempty suffix, and prove runtime defaults equal static defaults:

```py
static_mirrors = mod.STATIC_AA_MIRRORS
runtime_defaults = mod.DEFAULT_AA_MIRRORS
assert static_mirrors
assert len(static_mirrors) == len(set(static_mirrors))
for url in static_mirrors:
    parsed = urllib.parse.urlsplit(url)
    assert parsed.scheme == "https"
    assert parsed.hostname and parsed.hostname.startswith("annas-archive.")
    assert parsed.hostname.removeprefix("annas-archive.")
assert runtime_defaults == static_mirrors
```

- [ ] Verify these named safety groups remain standalone and unchanged in meaning: atomic accept, pre/post-replace fault, writer serialization, cross-process throttle, identity verification, cache deletion, and cache reuse.

- [ ] Run focused high-risk cases and the module:

```bash
python3 -m pytest tests/test_download_cli.py -q
python3 -m pytest tests/test_download_cli.py::test_ezproxy_throttle_serializes_across_processes -q
```

- [ ] Commit.

```bash
git add tests/test_download_cli.py
git commit -m "test: data-drive repeated download cases"
```

### Task 5: Parameterize extraction validation without merging fault tests

**Files:**

- Modify: `tests/test_extract_cli.py`

- [ ] Extract one local `forbid_engine_launch` sentinel fixture and use it only in these existing tests: `test_ocr_duplicate_engine_is_rejected_before_subprocess`; all three rows of `test_ocr_duplicate_flags_are_rejected_before_subprocess` (`--json`, `--no-clobber`, `--layout` duplicates); and all three rows of `test_ocr_json_invalid_arguments_echo_parsed_caller_paths` (unknown option, missing engine value, duplicate engine spelling). Preserve each row, caller-path echo, single-JSON-line assertion, and exit code. Keep `test_ocr_json_help_combination_is_one_invalid_arguments_object`, `test_ocr_rejects_unknown_engine`, and `test_ocr_engine_requires_value` as their existing public-process tests rather than folding them into the fixture.

- [ ] Keep the PDF layout regression group and the reconcile/race/fingerprint/rollback/symlink/fsync group as separate named tests. Do not combine fault injection points into one broad table whose failure hides the exact boundary.

- [ ] Run the full module plus the two concurrency regressions:

```bash
python3 -m pytest tests/test_extract_cli.py -q
python3 -m pytest tests/test_extract_cli.py::test_ocr_no_clobber_two_processes_create_once_without_overwrite tests/test_extract_cli.py::test_book_two_process_same_output_race_has_one_generation -q
```

- [ ] Commit.

```bash
git add tests/test_extract_cli.py
git commit -m "test: centralize extraction launch sentinels"
```

### Task 6: Audit Workflow-test retirement against the migration ledger

**Files:**

- Verify: `docs/superpowers/plans/2026-08-04-run-stage-test-migration-map.md`
- Verify: `tests/test_workflow_dispatch.py`
- Verify: `tests/test_material_plans.py`
- Verify: `tests/test_workflow_entries.py`
- Verify: `tests/test_status_cli.py`
- Verify: `tests/test_skill_orchestration.py`
- Verify absence: `tests/test_run_stage.py`

- [ ] Check every ledger replacement test exists and passes. Confirm exact-ref/write-target ownership replaced prompt-equality duplicate checks and that Book's mixed fan-out case proves all launched chapters settle, unknown dominates blocked/failed siblings, and no later stage starts. Chapter Analyse has no user gate.

- [ ] Confirm only retired syntax cases disappeared: generic kind/stage errors, `until` range validation, `units` envelope behavior, compatibility log prose, and batch error envelopes.

- [ ] Audit every test added during the material-Workflow refactor, not only the retired compatibility ledger. Keep a case only when it owns one distinct public behavior, real safety/ownership boundary, or reproduced regression. Keep generic terminal/unknown mapping at the shared dispatch boundary; prefer malformed-input coverage through each public entry; delete private-parser field permutations and repeated stop/repair/binding proofs already established by a shared boundary. Record the retained behavior beside each grouped test family rather than targeting a count.

- [ ] Run the Workflow slice:

```bash
npm run check:workflows
python3 -m pytest tests/test_workflow_dispatch.py tests/test_material_plans.py tests/test_workflow_entries.py tests/test_status_cli.py tests/test_skill_orchestration.py tests/test_dead_names.py -q
```

- [ ] Record the new collection count next to the baseline. Explain reductions by category (runners, duplicate cases, demos, prose/private coupling, retired modes), not by a target percentage.

- [ ] Commit any ledger completion notes.

```bash
git add docs/superpowers/plans/2026-08-04-run-stage-test-migration-map.md tests
git commit -m "test: complete material workflow coverage migration"
```

### Task 7: Final suite audit

**Files:**

- Modify if needed: `docs/CHANGELOG.md`

- [ ] Run the complete collection and suite from the root entry:

```bash
python3 -m pytest --collect-only -q
npm run check:workflows
python3 -m pytest -q
git diff --check
```

- [ ] Review skipped and xfailed tests. Every skip/xfail must name an actual optional dependency or integration boundary; delete stale ones rather than broadening their conditions.

- [ ] Search for remaining homemade runners, production demo wrappers, and exact Skill prose snapshots:

```bash
rg -n '^def main\(|if __name__ == ["'"']__main__["'"']' scripts/core/tests scripts/search/tests tests
rg -n 'demo\(\)|read_text\(.*SKILL|in skill_text|in source' tests scripts/core/tests scripts/search/tests
```

Review each hit; do not mechanically delete legitimate CLI fixture programs or semantic source/AST tests.

- [ ] Append the test-maintenance rationale and verified commands to the newest changelog entry. Commit only if this task changes files.

```bash
git add docs/CHANGELOG.md tests scripts/core/tests scripts/search/tests pytest.ini
git commit -m "test: finish maintainability audit"
```

# Claude Workflow refactor: Paper-stage verification

Date: 2026-07-30
Scope: Claude Code side only; Pi and Codex adapters were treated as regression
boundaries, not redesigned.

## Source baseline and repository state

- Branch: `main`
- Baseline commit: `cfb82147de0bba9466b667202b3ab3441ead1ddf`
- The starting worktree already contained extensive modified and untracked work.
  It was preserved; no reset, checkout, commit, push, PR, release, or deployment
  was performed.
- The final implementation remains a local dirty-worktree change.

## Architecture outcome

- `workflow-src/` is the maintainable Workflow Universe:
  - `materials/` owns Paper, Book, and Talk loops.
  - `collections/` owns Author and Journal loops.
  - `research/` owns Topic research.
  - `operations/` owns one-edge Operation prompts and schemas.
  - shared runtime code owns only host-neutral orchestration mechanics.
- `scripts/build-workflows.mjs` builds that source into the single Claude plugin
  runtime artifact `workflows/process-material.mjs`.
- A loop calls one Operation per edge. An Operation calls one specialist Agent,
  including thin Agent wrappers for deterministic `quasi-*` commands.
- Paper is the first strict vertical slice:
  acquire → normalize text → semantic readability assessment → at most one OCR
  recovery → re-normalize/reassess → analyse → audit/one bounded repair.
- Analysis uses one `analyse-agent`; Paper/Chapter/Talk differences are runtime
  prompt packs rather than separate Agent families.
- Workflow owns branching, retries, recovery, reconciliation, and typed receipts.
  Agents own semantic judgement or the exact filesystem/CLI action named by their
  contract.
- Root `settings.json` and `scripts/subagent-statusline.py` add a fail-soft
  quasi-only subagent row. Claude Code 2.1.211 provides model/context fields but
  predates the 2.1.214 per-task `effort` field, so missing effort is handled.

## Official Claude constraints applied

- A Workflow script owns loops, branches, and intermediate variables.
- Workflow code has no direct filesystem or shell access; Agents perform those
  effects.
- A running Workflow cannot stop for ordinary user input.
- Resume is same-session, and cached results stop at the first unfinished Agent
  in start order; later Agents rerun.
- Plugin Workflows live at root `workflows/`; plugin default
  `subagentStatusLine` lives in root `settings.json`.
- Claude Code 2.1.211 rejected a top-level `anyOf` in an Agent structured-output
  tool schema with API 400. The Paper audit schema therefore uses one flat object
  schema; Workflow runtime code enforces the `clean|partial|error` cross-field
  matrix and exact diagnostic-count equality.

## Review findings corrected

The orchestrated adversarial reviews found and the coordinator corrected:

1. unsafe shell/path quoting in thin command relays;
2. download and analysis reconciliation gaps for pre-existing writer outputs;
3. malformed writer receipts being reported as known failures;
4. OCR output publication races and possible overwrite;
5. OCR arbitrary invented failure codes being accepted as known;
6. incomplete text-extraction failure receipts lacking page metrics;
7. readability `message` schema/runtime disagreement;
8. audit `clean|partial|error` count/diagnostic matrix gaps;
9. initial-clean audit skipping its required final deterministic validation;
10. a top-level `anyOf` accepted by mock/schema tests but rejected by the real
    Claude Code 2.1.211 structured-output API.

The final read-only recheck confirmed that OCR accepts only:

- `paper.ocr_failed` as a known failed command mapping;
- `paper.writer_receipt_mismatch` as blocked/unknown;
- `output_exists_requires_reconcile` as blocked/unknown only with
  `exit=0`, `exists=true`, and a non-empty existing output.

## Verification evidence

Passed on the final source snapshot:

- `npm run build:workflows`
- `npm run check:workflows`
- `uv run --python 3.12 --with pytest --with-requirements scripts/requirements.txt pytest -q`
  - `560 passed`, 5 third-party SWIG deprecation warnings
- focused Paper/OCR/workflow build suite
  - `112 passed`
- final reviewer Paper suite
  - `62 passed`
- `cmp -s AGENTS.md CLAUDE.md`
- `claude plugin validate .`
- `git diff --check`
- ZIP integrity check with `unzip -tq`

The macOS system `python3` is 3.9.6 and cannot collect
`tests/test_codex_agents.py` because stdlib `tomllib` starts in Python 3.11.
The authoritative full suite was therefore run under Python 3.12.13.

Real native Claude Workflow evidence is recorded in
`docs/reviews/2026-07-30-claude-workflow-e2e.md`. A final-snapshot BTS run first
exposed the unsupported top-level `anyOf` at the audit Agent. After the minimal
schema correction and bundle rebuild, a fresh native run completed seven Agents:
existing-source reconcile, deterministic normalization, semantic readability,
safe analysis-output reconcile, audit escalation, one analysis repair, and a
clean second audit.

## Source package

- Path: `/Users/ramudai/Vibe/quasi-claude-workflow-review-20260730.zip`
- Size: `752969` bytes
- SHA-256:
  `edebe2130d1771986ad75accd9e42e6a55bad7bb56a08dfb67922ab1d016c604`
- Contents: 196 source/context files plus `SOURCE_PACKAGE_MANIFEST.txt`
- Excludes Git data, dependencies, caches, build/runtime/browser state, user
  vault/source/processing data, databases, logs, JSONL transcripts, credentials,
  environment files, private-key formats, archives, and media/documents.
- `gitleaks`, `trufflehog`, and `detect-secrets` were unavailable. A fallback
  content scan checked private-key headers, AWS IDs, GitHub/service tokens, JWTs,
  and literal secret assignments; a filename scan checked `.env` and common key
  containers. Both reported zero matches.
- The package was produced before the final native audit-schema correction and
  is retained only as an interim review artifact. It no longer represents the
  current worktree and must be regenerated before final handoff.
- The temporary `node_modules/` was restored from Trash to rebuild the Workflow
  bundle after the native finding.

## External review and remaining risk

- A detailed ChatGPT Pro review brief was prepared at
  `docs/reviews/2026-07-30-claude-workflow-pro-review-brief.md`.
- The in-app browser backend was not exposed to this Codex thread, so the brief
  could not be sent and there is no ChatGPT Pro conversation link. No Pro review
  is claimed.
- Compensating review used independent read-only Orca workers plus coordinator
  reproduction and full local verification.
- Still not verified with a final-snapshot native Claude run:
  - real scanned-PDF OCR recovery;
  - native pause/resume replay ordering.
- The final Paper audit schema, exact-output reconcile, bounded audit repair, and
  clean second audit are now verified against live Claude structured-output
  requests.
- A SIGKILL can leave an OCR staging directory, but cannot overwrite the final
  output; this is a low-severity cleanup residual.
- The explicitly named legacy download/audit composite nodes and broader
  Book/Author/Topic legacy paths remain compatibility debt for later slices.

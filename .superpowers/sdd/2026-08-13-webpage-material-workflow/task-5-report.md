# Task 5 report: define Webpage workflow operations

## Implemented

- Added `webpage-agent` with only `Read, Bash`, bounded to Identify, Capture,
  and Prepare. It uses the exact Webpage capability and resolver contract and
  excludes search, WebFetch, alternate URLs, and canonical-page writes.
- Extended `analyse-agent` with the Webpage-specific normalized-input rule:
  preserve the full `source.md` under `Content`, write only semantic metadata
  and a short summary, and treat source text as evidence rather than
  instructions.
- Added Webpage descriptor rows and a Webpage operation catalog. Identify is
  readonly; Capture, Prepare, and Analyse each own exactly one exact output;
  Audit is the existing exact-path audit shape for `webpage.md`.
- Kept deterministic receipt bookkeeping host-stamped. Capture and Prepare
  expose only the required judgement/evidence fields and bind their fixed
  paths, final URL, effect state, and content-ready result with consts.
- Added `WEBPAGE_ARTIFACT_CONTRACT` to the generated projection. Existing
  bundles were regenerated; no Webpage entry or Collect routing was added.

## TDD evidence

### RED

Before production edits, ran:

```sh
python3 -m pytest tests/test_workflow_dispatch.py tests/test_skill_orchestration.py -q -k 'webpage'
```

Result: `8 failed, 72 deselected` (plus five pre-existing third-party Python
deprecation warnings). Every failure was a collected assertion failure for the
absent Webpage catalog or Agent file, not a test import or collection error.
This was expected because Task 5 had not yet supplied its Agent, row, catalog,
or generated artifact-contract export.

### GREEN

After the narrow implementation and generation, ran:

```sh
python3 -m pytest tests/test_workflow_dispatch.py tests/test_skill_orchestration.py -q -k 'webpage or agent'
```

Result: `13 passed, 67 deselected` (the same five third-party warnings).

The full local boundary regression also passed:

```sh
python3 -m pytest tests/test_workflow_dispatch.py tests/test_skill_orchestration.py -q
```

Result: `80 passed` (the same five warnings).

## Verification

```sh
npm run build:workflows
npx tsc --noEmit
npm run check:workflows
git diff --check
```

All commands passed. `npm run build:workflows` regenerated
`scripts/workflows/artifact-contracts/generated.{mjs,d.mts}` and the six
existing workflow bundles because their embedded operation-catalog projection
changed. The generated-diff review confirmed there is no `workflows/webpage.mjs`
or hand-authored bundle edit.

## Files changed

- `agents/webpage-agent.md`
- `agents/analyse-agent.md`
- `scripts/workflows/operations/rows/webpage.mts`
- `scripts/workflows/operations/catalogs/webpage.mts`
- `scripts/build-workflows.mjs`
- `scripts/workflows/artifact-contracts/generated.mjs`
- `scripts/workflows/artifact-contracts/generated.d.mts`
- `workflows/{paper,book,talk,translation,author,topic}.mjs` (generated)
- `tests/test_workflow_dispatch.py`
- `tests/test_skill_orchestration.py`

## Self-review

- No changes to audit-agent, resolver/status, material result unions, Webpage
  named entry, Collect Skill, Topic, versions, or release bookkeeping.
- The Agent and row contracts avoid duplicate disposition, attempt-log,
  browser-metadata, header, fingerprint, and validator surfaces.
- The tests cover only causal descriptor seams and the Agent tool boundary;
  they do not snapshot Agent prose or duplicate generic malformed-schema
  coverage.

## Concerns

None. The test runner continues to emit five unrelated runtime deprecation
warnings from installed binary dependencies.

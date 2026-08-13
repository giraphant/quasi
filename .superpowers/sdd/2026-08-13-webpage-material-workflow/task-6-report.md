# Task 6 report: add the typed named Webpage Workflow

## Implemented

- Extended only the shared leaf material boundary with `webpage` status,
  material, observation route/key, exact `snapshot` artifact role, and one
  canonical Webpage `LeafResumeSeed`. Webpage was not added to Author/Topic
  composition or any gate union.
- Added the closed Webpage input contract. Provisional intake accepts only an
  exact credential-free HTTP(S) URL envelope with null observation and empty
  options. Canonical processing accepts one exact Webpage status, validates
  its three owned paths and whole-second UTC capture timestamp, binds the
  route/slug/normalized URL owner, and adopts observed title/site metadata.
- Added the linear named plan and entry for Search, Acquire, Prepare, Analyse,
  and Audit. Identify returns an exact observation route; Capture/Prepare/
  Analyse ambiguity returns `needs_observation`; schema-valid stops pass
  through; durable progress skips completed work while reconciling Prepare
  when Analyse needs exact hash/size testimony; no `pipeline()` is used.
- Preserved the intentional two-load boundary: Capture may replace title/site
  while slug and URL ownership remain fixed, and Analyse receives the Capture
  metadata and capture timestamp.
- Added one owner-correct Analyse repair and one re-audit. Foreign audit
  targets block, and a second dirty audit returns
  `workflow.repair_exhausted`.
- Registered and generated `workflows/webpage.mjs`. Existing bundles were
  regenerated because they embed the shared observation-route parser.

## TDD evidence

### Initial RED

Before production edits:

```sh
python3 -m pytest tests/test_material_result.py tests/test_webpage_plan.py tests/test_workflow_entries.py -q -k 'webpage'
```

Result: `21 failed, 1 passed, 83 deselected`. All failures were collected
in-test assertion failures from the absent Webpage contract, plan, entry, or
route support; there was no collection/import failure. The one passing test
was the runtime material-result constructor shape; compile-time acceptance of
its new `snapshot` role remained RED until the TypeScript union changed.

### Additional RED/GREEN cycles

- A durable-progress case with usable snapshot/canonical but missing
  `source.md` failed because the initial plan skipped Prepare. After the plan
  selected any missing projection before audit, that focused case passed.
- `https://@example.org/page` was initially accepted because the JavaScript
  URL constructor erased the empty credential marker. After inspecting the
  raw authority before normalization, the four invalid-URL cases passed.

### GREEN

```sh
python3 -m pytest tests/test_material_result.py tests/test_webpage_plan.py tests/test_workflow_entries.py -q -k 'webpage'
```

Result: `31 passed, 83 deselected`.

The fresh full relevant workflow regression was:

```sh
python3 -m pytest tests/test_material_plans.py tests/test_material_result.py tests/test_topic_plan.py tests/test_webpage_plan.py tests/test_workflow_dispatch.py tests/test_workflow_entries.py -q
```

Result: `263 passed`.

## Verification

```sh
npm run build:workflows
npm run check:workflows
git diff --check
cmp -s CLAUDE.md AGENTS.md
```

All commands exited successfully. `check:workflows` reported all seven named
workflow bundles current and completed strict `tsc --noEmit` checking.

## Files changed

Hand-authored source and tests:

- `scripts/workflows/contracts/webpage.mts`
- `scripts/workflows/plans/webpage.mts`
- `scripts/workflows/webpage.entry.mts`
- `scripts/workflows/shared/material-input.mts`
- `scripts/workflows/shared/material-result.mts`
- `scripts/build-workflows.mjs`
- `tests/test_material_result.py`
- `tests/test_webpage_plan.py`
- `tests/test_workflow_entries.py`

Generated outputs:

- `workflows/webpage.mjs`
- `workflows/paper.mjs`
- `workflows/book.mjs`
- `workflows/talk.mjs`
- `workflows/translation.mjs`
- `workflows/author.mjs`
- `workflows/topic.mjs`

## Self-review

- Re-read the Task 6 brief against the diff and verified exact three-ref
  completion, null requested slug, local-owner observation handoff, empty
  options, closed status facts, and bounded repair semantics.
- Confirmed there is no Webpage `LeafGate`, `userDecision`, composition union,
  generic retry/reconciliation framework, or `pipeline()` call.
- Confirmed no resolver/status, Agent/operation-row, Collect, Topic/Author,
  version/release, progress-ledger, manifest, or unrelated source edit.
- Mutation review is covered at the causal seams: wrong route/slug/URL/path/
  timestamp, dropped Capture metadata, skipped durable stage, writer
  ambiguity, failure reinterpretation, foreign audit owner, repeated repair,
  entry isolation, and generated/source ABI drift all fail focused tests.

## Concerns

None.

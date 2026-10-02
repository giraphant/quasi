# Annual Reviews Paper invocation regression

Date: 2026-09-26. Task: `task_bec32bf3ec26`.

## Scope and environment

- Requested source: <https://www.annualreviews.org/content/journals/10.1146/annurev.anthro.30.1.109> — Laura M. Ahearn, *Language and Agency* (2001).
- Actual vault/cwd: `/Users/ramudai/Documents/Learn/bts`.
- Installed Claude plugin: `/Users/ramudai/.claude/plugins/cache/ramu/quasi/0.67.7`; BTS enables `quasi@ramu`.
- Maintainer checkout: `/Users/ramudai/Vibe/quasi`, manifest version `0.68.0`.
- Claude Code: `2.1.280`.
- Existing vault artifacts and installed plugin files were not edited by the maintainer. No commit, push, plugin installation, or external publication was performed.

## Original failure and root cause

The original BTS transcript is:

```text
/Users/ramudai/.claude/projects/-Users-ramudai-Documents-Learn-bts/af3576d4-c286-4179-9212-ab3c0e2601ec.jsonl
```

Read the actual tool-input objects, not the assistant's subsequent diagnosis:

| Transcript line | UTC time | Tool-level keys | `args` keys | Outcome |
| --- | --- | --- | --- | --- |
| 52 | 15:56:00.695 | `scriptPath,args,options` | `seed,observation` | Tool rejected unknown top-level `options` |
| 110 | 16:00:09.535 | `scriptPath,args,options` | `seed,observation` | Same rejection |
| 315 | 16:03:57.560 | `scriptPath,args` | `seed,observation` | Workflow launched, then material parser rejected the incomplete envelope |

Exact tool failure at lines 53/111:

```text
InputValidationError: Workflow failed due to the following issue:
An unexpected parameter `options` was provided
```

The first two calls had this shape (seed and fresh status contents abbreviated):

```json
{"scriptPath":".../workflows/paper.mjs","args":{"seed":{},"observation":{}},"options":{}}
```

The correction moves `options` into `args`:

```json
{"scriptPath":".../workflows/paper.mjs","args":{"seed":{},"observation":{},"options":{}}}
```

These abbreviated seed/status objects are structural illustrations, not valid material input. Actual execution supplies the complete provisional seed and exact `quasi-status` observation.

The previous diagnosis that Claude Code rejected `args.options` was contradicted by its own saved call objects. No failing call in that sequence contained `args.options`. Deleting the top-level field did not repair the material envelope, so the second failure does not establish a host compatibility defect. Neither initial rejected call dispatched a writer.

The third invocation's completed notification at transcript line 316 contains `terminal:"blocked"`, `issue.code:"material.invalid_input"`. Its Workflow journal at `subagents/workflows/wf_2a5d52a8-5f3/journal.jsonl` contains only `{"type":"launched"}`, with no Agent dispatches/results.

## Read-only BTS observations

Commands ran with cwd `/Users/ramudai/Documents/Learn/bts`:

```sh
/Users/ramudai/Vibe/quasi/bin/quasi-search paper --doi 10.1146/annurev.anthro.30.1.109 --json
/Users/ramudai/Vibe/quasi/bin/quasi-status --kind paper --slug ahearn-language-and-agency-2001 --json
```

Metadata search returned one matching paper from OpenAlex/Crossref, with author Laura M. Ahearn, year 2001, journal *Annual Review of Anthropology*, volume 30, issue 1, pages 109–137. Semantic Scholar returned HTTP 429 after its bounded retries; this did not prevent metadata identification. The exact candidate-slug status had `identity:null`, both source alternatives absent, prepared text absent, no OCR generation, and canonical page absent. A scoped DOI search of the vault's Markdown/JSON/YAML records found no existing matching record before the live collection.

## Fix

`skills/collect-material/SKILL.md` now shows one complete Paper tool call with `options` visibly inside `args`. It explicitly keeps all material/resume fields in that object, retains an empty options object, and distinguishes correction of a proven pre-dispatch parameter rejection from unknown writer outcomes.

The strict TypeScript material parser and generated bundles remain unchanged: their required envelope was correct. The defect was in the executing model's tool-call construction; the durable runtime fix belongs in the Skill that directs those calls.

Regression tests:

- Execute the Skill's literal Python example with the documented two-argument invocation boundary, then send its material object through the generated Paper bundle. Assert one `material.search` dispatch and no pipeline dispatch. This checks the executable cross-file contract rather than prose wording.
- Send a Paper envelope missing `options` through the generated bundle. Assert `material.invalid_input` and zero Agent/pipeline dispatches.

## Local validation

Before the Skill change:

```sh
python3 -m pytest tests/test_skill_orchestration.py -k literal_paper_tool_call -q
```

Result: **1 failed** — the executable full-call regression found no literal nested tool-call example (`assert 0 == 1`). This is the documentation-contract regression; the actual user failure above is independently evidenced by the live transcript.

After the Skill change, the same test passed. Final checks:

```sh
python3 -m pytest tests/test_dead_names.py tests/test_skill_orchestration.py tests/test_workflow_entries.py -q
npm run check:workflows
cmp -s CLAUDE.md AGENTS.md
git diff --check
```

Results: **67 passed** in 5.20 seconds after final example review; workflow generation parity and strict TypeScript checks passed; maintainer instruction mirrors match; no whitespace errors. PyMuPDF emitted five existing SWIG deprecation warnings. The bundled Quasi runtime venv does not contain pytest, so validation used the existing `python3 -m pytest` environment.

The original saved call was also replayed in the existing stubbed Workflow harness, without network access or material writers, using this exact command from the maintainer checkout:

```sh
python3 - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, 'tests')
from workflow_test_support import run_generated_workflow
p = Path('/Users/ramudai/.claude/projects/-Users-ramudai-Documents-Learn-bts/af3576d4-c286-4179-9212-ab3c0e2601ec.jsonl')
record = json.loads(p.read_text().splitlines()[51])
call = next(c['input'] for c in record['message']['content'] if c.get('name') == 'Workflow')
for label, args in [('original_args', call['args']),
                    ('corrected_args', {**call['args'], 'options': call['options']})]:
    report = run_generated_workflow('paper', args, capture_agent_requests=True)
    print(label, report['agentCalls'], report['pipelineCalls'],
          report['value']['issue']['code'],
          [json.loads(r['prompt'])['operation'] for r in report['agentRequests']])
PY
```

Observed results:

```text
original_args 0 0 material.invalid_input []
corrected_args 1 0 workflow.unknown_outcome ['material.search']
```

The harness intentionally supplies no specialist response, so `workflow.unknown_outcome` in the corrected case proves arrival at Search, not a real failed or ambiguous material writer. No material operation runs in this stubbed harness.

## Live verification

The coordinator dispatched Claude in the actual BTS workspace with the existing installed plugin, using `claude --settings /users/ramudai/.agents/models/monster.json --dangerously-skip-permissions`. The task requests non-writing tool-envelope probes followed by normal `collect-material`, permits only new artifacts for this paper, and forbids edits to existing vault content and Quasi code. Its report path is `.quasi/temp/annualreviews-bec32bf3ec26/cc-report.md` within BTS.

**Live result: succeeded.** The coordinator reported Task `task_cbbd01207d6b` / Dispatch `ctx_336cd5464636` complete, and the maintainer read the CC report and canonical Markdown. Evidence is stored at:

```text
/Users/ramudai/Documents/Learn/bts/.quasi/temp/annualreviews-bec32bf3ec26/cc-report.md
```

The real host probes used the existing installed `0.67.7` Paper bundle:

| Probe | Actual shape | Observed result |
| --- | --- | --- |
| A | `Workflow({scriptPath:paper.mjs,args:{seed:null,observation:null},options:{}})` | `InputValidationError: An unexpected parameter options was provided`; no Workflow session or writer |
| B | `Workflow({scriptPath:paper.mjs,args:{seed:null,observation:null,options:{}}})` | Workflow `wf_410add18-f4c` entered the material parser and returned `material.invalid_input`; zero Agents/tools |

The subsequent real intake used request key `annualreviews-bec32bf3ec26` with the caller's exact DOI/URL, the full fresh status object, and `options:{}` inside `args`. Workflow `wf_f5fa7126-939` returned `needs_observation` for canonical route `paper:ahearn-language-and-agency-2001`. After fresh exact status, Workflow `wf_87078be3-40b` consumed the returned canonical seed and empty options and returned:

```json
{
  "schema_version": "quasi.material.result/0.1",
  "terminal": "complete",
  "issue": null,
  "next": null
}
```

This is the relevant terminal projection of the returned result, not a replacement receipt. The completed Paper invocation included the final Audit. Its post-status command, run in BTS, was:

```sh
quasi-status --kind paper --slug ahearn-language-and-agency-2001 --json
```

The report confirms these exact artifacts are all `present:true,usable:true`:

- `/Users/ramudai/Documents/Learn/bts/sources/ahearn-language-and-agency-2001.pdf` — 639,652 bytes, 32 pages, SHA-256 `19562991839024e54e8630e262727dce5891d0b56f3d1da9dcd328876b0a34c8`.
- `/Users/ramudai/Documents/Learn/bts/processing/papers/ahearn-language-and-agency-2001/source.txt`.
- `/Users/ramudai/Documents/Learn/bts/vault/papers/ahearn-language-and-agency-2001.md` — title/author/year/DOI match the request; the maintainer read its analysis and source locators.

Text extraction was usable without OCR; no OCR generation or legacy recovery was required. The worker reports all three material artifacts were new, with no existing vault content or Quasi code changed. No acquisition or collection blocker remains. The PDF is ignored by BTS Git rules, and the new text/analysis remain uncommitted as instructed.

This live run validates the corrected call against the already installed plugin and current host. The maintainer's Skill change remains only in the working checkout; no claim is made that it was installed, released, or exercised by a fresh unprompted model session.

## Modified files

- `skills/collect-material/SKILL.md`
- `tests/test_skill_orchestration.py`
- `tests/test_workflow_entries.py`
- `docs/evals/annualreviews-workflow-args-20260926.md`
- `docs/CHANGELOG.md`

# Claude Workflow Universe — external engineering review brief

Date: 2026-07-30
Repository baseline: `main` at `cfb82147de0bba9466b667202b3ab3441ead1ddf`, plus the supplied dirty worktree
Primary host in scope: Claude Code

## Background and goal

Quasi is a Claude Code plugin for academic material workflows. The current
refactor turns one large workflow script and several broad worker contracts into
one logical Workflow Universe with physically modular source:

```text
Skill / user-facing state machine
  -> Material, Collection, or Research loop
     -> one business Operation per edge
        -> one specialist Agent, or one Agent-wrapped quasi-* CLI
```

The first vertical slice is Paper:

```text
acquire source
  -> deterministic text extraction
  -> Agent readability assessment
  -> optional OCR
  -> deterministic text extraction
  -> Agent readability assessment
  -> common analyse-agent + paper-analysis/1 prompt pack
  -> audit
  -> at most one exact repair by the same analyse-agent
  -> re-audit
```

The review objective is to decide whether this is the smallest reliable
architecture for Claude Code Workflow, especially under native Workflow resume
semantics.

## Current architecture and boundaries that must not break

- `skills/` own input normalisation, local recall, human gates, and user-facing
  state.
- `workflow-src/` is the modular ESM source of the graph.
- `workflows/process-material.mjs` is the single generated, committed Claude
  Workflow artifact. It must remain loadable as an `AsyncFunction` body.
- `agents/` contain worker contracts. Paper and future Chapter/Talk operations
  inject a runtime prompt pack into one common `analyse-agent`.
- `bin/quasi-*` and `scripts/` own deterministic capabilities.
- A Workflow graph does not read files or execute shell directly. A narrow
  Agent may execute one exact public CLI command and return a typed receipt.
- Semantic readability is an Agent judgement. Character counts and extraction
  metrics are evidence, not a deterministic verdict.
- Writer calls with unknown outcomes are never automatically retried. A later
  exact reconciliation step must observe the named artifact.
- Human questions remain outside the Workflow run because Claude Workflow
  cannot ask for mid-run input.
- Do not add a runtime registry, event store, scheduler, custom progress
  journal, or a third-party workflow engine.
- Do not redesign the Pi or Codex adapters in this review. They are regression
  constraints only.
- Preserve the legacy behaviour of Book, Author, and Topic unless a migration
  is explicitly named and characterised.

## Review scope

Review these areas together:

1. `docs/workflow-modularization-master.md`
2. `docs/operation-layer-design.md`
3. `workflow-src/**`
4. generated `workflows/process-material.mjs`
5. `agents/analyse-agent.md`, `agents/audit-agent.md`,
   `agents/download-agent.md`
6. `scripts/extract/extract.py`, `scripts/extract/extract_text.py`, and
   `bin/quasi-extract`
7. Paper, characterization, build, timeout, and agent-contract tests

Answer these design questions:

- Are Loop, Operation, Agent, and deterministic CLI responsibilities separated
  at the right granularity?
- Does the Paper graph handle native Workflow replay without blind writer
  duplication or permanent “output already exists” loops?
- Are typed receipts closed and exact enough to prove the named input, output,
  and target?
- Can a malicious slug, metadata string, URL, or source document escape its
  data boundary or influence shell execution?
- Is repair reconciliation inside the common analyse-agent sufficient, or is a
  heavier generation/staging protocol actually necessary for this first slice?
- Did modularisation change any Book, Author, or Topic observable behaviour?
- Which legacy composite nodes must be split next, and which can remain
  explicitly named debt without making the current slice misleading?

## Required deliverables

1. A severity-ordered review with exact file/line evidence and a minimal
   correction for each finding.
2. A concise final architecture decision, including rejected alternatives and
   why they would be over- or under-engineered here.
3. A source patch only if a correction is necessary. The patch must be minimal,
   complete, and apply to the supplied dirty baseline without resetting other
   work.
4. A test matrix that distinguishes:
   - source/bundle parity,
   - simulated adapter behaviour,
   - real Claude Workflow execution,
   - native pause/resume behaviour.
5. A residual-risk list naming anything that remains unverified.

## Tests that must be executed

At minimum:

```bash
npm ci --ignore-scripts --no-audit --no-fund
npm run check:workflows
python3 -m pytest \
  tests/test_analyse_agent_contract.py \
  tests/test_extract_cli.py \
  tests/test_workflow_build.py \
  tests/test_workflow_characterization.py \
  tests/test_paper_loop.py \
  tests/test_orchestrate_timeout.py \
  tests/test_skill_orchestration.py \
  tests/test_pi_runner.py \
  tests/test_codex_runner.py \
  tests/test_codex_driver.py -q
```

Also run the repository's full pytest suite and `claude plugin validate .`.
Report simulated tests as simulated; they are not evidence of a real Claude
Workflow run.

Real Claude acceptance should cover:

- a local born-digital paper;
- a local image-only paper that takes the OCR recovery edge;
- an existing canonical paper that is reconciled through audit;
- a repair replay in which the first writer completed its side effect but its
  receipt was not observed.

## Prohibited actions and claims

- Do not commit, push, create a PR, deploy, migrate a database, change online
  configuration, or operate on real user data.
- Do not delete or reset unrelated dirty-worktree changes.
- Do not install a third-party workflow compatibility dependency.
- Do not treat an Agent's prose or an output file's mere existence as proof of
  success.
- Do not claim a mocked Pi/Codex runner test is a real Claude Workflow test.
- Do not claim legacy download or audit composite nodes are decomposed until
  their internal control flow is actually represented by graph edges.

## Acceptance criteria

- One modular source tree builds deterministically to one current Workflow
  artifact.
- Paper analysis receives only an exact readable normalized text artifact and a
  self-contained Paper prompt pack.
- The same common `analyse-agent` handles create and exact repair.
- OCR is triggered only by a typed readability signal and is followed by
  re-extraction and re-assessment.
- Unknown writer outcomes block; known existing outputs enter an explicit,
  bounded reconciliation path.
- Slugs and command arguments cannot traverse paths or invoke shell expansion.
- Audit proves the exact target and cannot report clean without zero remaining
  violations.
- Book, Author, and Topic characterised behaviour remains stable.
- All required tests pass, with real and simulated evidence clearly separated.
- The final repository state remains local-only unless separately authorised.

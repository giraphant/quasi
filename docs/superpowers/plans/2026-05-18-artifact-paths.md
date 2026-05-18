# Quasi 0.26.0 Artifact Path Discipline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all plumbing-shaped interim artifacts out of `processing/` and into `.quasi/`, leaving `processing/` as a minimal user-readable-content home (`chapters/` + `translations/`). Consolidate the audit pipeline under `.quasi/audit/`.

**Architecture:** Pure string-substitution refactor across 5 logical change-groups, each one commit. One tiny Python edit (`typecheck.py` `OUT_DIR` constant). No new tests; verification is grep-based (each group has an authoritative grep that must return zero matches post-edit).

**Tech Stack:** Markdown (skill / agent docs), Python (one constant change in typecheck.py), bash (smoke tests).

**Spec:** `plugins/quasi/docs/superpowers/specs/2026-05-18-artifact-paths-design.md`

**Pre-flight context every task needs to know:**

- `wrap-up/SKILL.md` was already partially migrated in 0.22.x — `ct_dir = .quasi/citation/{draft-stem}/` is already set on line 127, and `.quasi/audit/audit-state.json` is already referenced. The remaining wrap-up edits are smaller than the spec implies.
- `scripts/proofread/proofread.py` has **no** `processing/` references despite the spec hinting at lines 15/208. Skip the script edit for Group B.
- `scripts/citation/render.py` is deprecated per 0.22.0 — leave its stale references alone (will be rewritten or deleted in a future minor).
- All `pf_dir` / `ct_dir` references in `wrap-up/SKILL.md` are template variables; `ct_dir` is explicitly defined as `.quasi/citation/{draft-stem}/`; `pf_dir` has no explicit definition and needs one added.

**Bump:** `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json` to `0.26.0`; add a `CLAUDE.md` "Recent Changes" entry as the final task.

---

## Task 1 — Group B: proofread sections move

**Files:**
- Modify: `plugins/quasi/skills/wrap-up/SKILL.md` (add `pf_dir` definition; update cleanup line; update final-products tree)

`pf_dir` is referenced as a template variable at line 73 but never explicitly assigned (unlike `ct_dir` at line 127). Add an explicit assignment next to the proofread split step, swap the cleanup line, and update the 中间产物 tree.

- [ ] **Step 1: Grep current state**

```
rg "processing/proofread" plugins/quasi/
```

Expected output (3 matches, all in `skills/wrap-up/SKILL.md`):
- Line 390 (cleanup): `rm -rf processing/proofread/{stem}/`
- Line ~396 (tree): `├── proofread/{stem}/` under `processing/`
- Plus the spec / plan files themselves (ignore)

- [ ] **Step 2: Add explicit `pf_dir` assignment before the proofread split**

Open `plugins/quasi/skills/wrap-up/SKILL.md`. Find line 73:

```
1. `quasi-helpers proofread split <draft> -o {pf_dir}/sections.json` — 按 H2/H3 切节
```

Insert two lines **immediately above** the Stage A enumeration (i.e. between the current line 70 "**Stage A — sonnet 节串行 + 节内多轮迭代**:" and the blank line before "1. ..."):

```
设 `pf_dir = .quasi/proofread/{draft-stem}/`。

```

(Mirrors the `设 ct_dir = ...` line at 127. This makes pf_dir's value explicit and ties it to the new `.quasi/` layout.)

- [ ] **Step 3: Update cleanup line (line 390)**

Replace the current cleanup bullet:

```
- **执行后**(可选): `rm -rf processing/proofread/{stem}/` 清掉 split 产物
```

with (cleanup goes from optional to required, since `.quasi/` is disposable by definition):

```
- **执行后**: `rm -rf .quasi/proofread/{stem}/` 清掉 split 产物
```

- [ ] **Step 4: Update the 中间 / 终产物 tree (lines ~393-410)**

The current tree shows `processing/` containing `proofread/` + `citation/`. The full tree needs rewriting later under Group A; for **this task** only delete the `proofread/{stem}/` block from under `processing/` and move it under `.quasi/`. Here's the minimal patch — find:

```
```
processing/
├── proofread/{stem}/
│   └── sections.json
├── citation/{stem}/
```

Replace with:

```
```
.quasi/
└── proofread/{stem}/
    └── sections.json

processing/
├── citation/{stem}/
```

(Group A will further rewrite the `processing/citation/` section. Don't touch citation in this task.)

- [ ] **Step 5: Verify**

```
rg "processing/proofread" plugins/quasi/
```

Expected: only matches in `docs/superpowers/specs/2026-05-18-artifact-paths-design.md` and this plan file. Zero matches in skills/agents/scripts.

```
rg "\.quasi/proofread" plugins/quasi/
```

Expected: at least 3 matches in `skills/wrap-up/SKILL.md` (the new `pf_dir` definition, the cleanup line, and the new tree).

- [ ] **Step 6: Commit**

```bash
git add plugins/quasi/skills/wrap-up/SKILL.md
git commit -m "refactor(quasi 0.26.0): move processing/proofread/ → .quasi/proofread/

Group B of the artifact-path discipline refactor.

- Add explicit pf_dir = .quasi/proofread/{draft-stem}/ definition in
  Phase 1 (mirrors existing ct_dir = .quasi/citation/...).
- Cleanup line goes from optional to required (.quasi/ is disposable).
- Update 中间产物 tree.

Spec: docs/superpowers/specs/2026-05-18-artifact-paths-design.md"
```

---

## Task 2 — Group C: temp PDF moves

**Files:**
- Modify: `plugins/quasi/skills/process-journal/SKILL.md` (lines 55, 60, 68, 104)
- Modify: `plugins/quasi/skills/process-topic/SKILL.md` (lines 59, 62, 202)
- Modify: `plugins/quasi/scripts/download/download.py` (line 1096)

- [ ] **Step 1: Grep current state**

```
rg "/tmp/(snowball|journal|topic|.*-pdfs)" plugins/quasi/
```

Expected: 4 matches in process-journal/SKILL.md, 3 in process-topic/SKILL.md, 1 in scripts/download/download.py.

- [ ] **Step 2: Update process-journal/SKILL.md**

In `plugins/quasi/skills/process-journal/SKILL.md`, replace **every** occurrence of `/tmp/{journal_name}-pdfs/` (template form) and `/tmp/{journal-name}-pdfs/` (display form in trees) with `.quasi/temp/journal-pdfs/{journal_name}/` and `.quasi/temp/journal-pdfs/{journal-name}/` respectively. Specific sites:

- Line 55 (`output_dir:` in download dispatch prompt)
- Line 60 (`Glob(f"/tmp/...")`)
- Line 68 (`input:` in analyse-agent dispatch prompt)
- Line 104 (final-products tree display)

Use this sed for the source-text replacements (run from repo root):

```bash
sed -i '' \
  -e 's|/tmp/{journal_name}-pdfs/|.quasi/temp/journal-pdfs/{journal_name}/|g' \
  -e 's|/tmp/{journal-name}-pdfs/|.quasi/temp/journal-pdfs/{journal-name}/|g' \
  plugins/quasi/skills/process-journal/SKILL.md
```

- [ ] **Step 3: Update process-topic/SKILL.md**

Same pattern for topic-pdfs. Sites:

- Line 59 (`output_dir:`)
- Line 62 (`input:`)
- Line 202 (tree)

```bash
sed -i '' \
  -e 's|/tmp/{topic_slug}-pdfs/|.quasi/temp/topic-pdfs/{topic_slug}/|g' \
  -e 's|/tmp/{topic-slug}-pdfs/|.quasi/temp/topic-pdfs/{topic-slug}/|g' \
  plugins/quasi/skills/process-topic/SKILL.md
```

- [ ] **Step 4: Update download.py default**

Open `plugins/quasi/scripts/download/download.py`. Find line 1096:

```python
    pdf_dir = manifest.get("pdf_dir", "/tmp/snowball-pdfs")
```

Replace with:

```python
    pdf_dir = manifest.get("pdf_dir", ".quasi/temp/snowball-pdfs")
```

(Single-line edit; callers passing `pdf_dir` explicitly are unaffected.)

- [ ] **Step 5: Verify**

```
rg "/tmp/.*pdfs" plugins/quasi/
```

Expected: only matches in `docs/superpowers/specs/2026-05-18-artifact-paths-design.md` and this plan. Zero in skills / scripts / agents.

```
rg "\.quasi/temp" plugins/quasi/
```

Expected: 7 matches across the two skill files + 1 in download.py.

- [ ] **Step 6: Commit**

```bash
git add plugins/quasi/skills/process-journal/SKILL.md \
        plugins/quasi/skills/process-topic/SKILL.md \
        plugins/quasi/scripts/download/download.py
git commit -m "refactor(quasi 0.26.0): move /tmp/*-pdfs/ → .quasi/temp/

Group C of the artifact-path discipline refactor.

- process-journal: /tmp/{name}-pdfs/ → .quasi/temp/journal-pdfs/{name}/
- process-topic:   /tmp/{slug}-pdfs/ → .quasi/temp/topic-pdfs/{slug}/
- download.py:     default pdf_dir → .quasi/temp/snowball-pdfs/
  (explicit-arg callers unaffected — both updated skills now pass
   their own path)

Brings temp PDFs into the project tree where they're inspectable
and not subject to macOS /tmp/ reaping.

Spec: docs/superpowers/specs/2026-05-18-artifact-paths-design.md"
```

---

## Task 3 — Group D: audit pipeline consolidation under `.quasi/audit/`

**Files:**
- Modify: `plugins/quasi/scripts/typecheck/typecheck.py` (line 50 + docstring lines 5-6)
- Modify: `plugins/quasi/agents/audit-agent.md` (multiple lines)
- Modify: `plugins/quasi/schemas/book.py` (line 50)
- Modify: `plugins/quasi/docs/ARCHITECTURE.md` (line 317)

Three things drift together: (1) typecheck.py writes results at `.quasi/` top-level instead of `.quasi/audit/`; (2) audit-agent.md cites pre-`.quasi/` paths like `processing/audit/state.json`; (3) schemas/book.py + ARCHITECTURE.md echo the stale paths.

- [ ] **Step 1: Grep current state**

```
rg "(processing/audit|\.quasi/typecheck-)" plugins/quasi/
```

Expected sites:
- `scripts/typecheck/typecheck.py:5,6` — docstring path examples
- `scripts/typecheck/typecheck.py:50` — `OUT_DIR = PROJECT_ROOT / ".quasi"`
- `agents/audit-agent.md:14` — `processing/audit/state.json`
- `agents/audit-agent.md:43,78,462` — `.quasi/typecheck-results.json`
- `agents/audit-agent.md:241,253-255` — `processing/audit/translations.json`
- `schemas/book.py:50` — `processing/audit/translations.json`
- `docs/ARCHITECTURE.md:317` — `processing/audit/state.json`

(Line numbers may have drifted; the grep is authoritative.)

- [ ] **Step 2: Update typecheck.py OUT_DIR (the only code change in the whole plan)**

Open `plugins/quasi/scripts/typecheck/typecheck.py`. Find line 50:

```python
OUT_DIR = PROJECT_ROOT / ".quasi"
```

Replace with:

```python
OUT_DIR = PROJECT_ROOT / ".quasi" / "audit"
```

Then update the docstring at lines 5-6:

```python
  $CLAUDE_PROJECT_DIR/.quasi/typecheck-report.md    — human-readable summary
  $CLAUDE_PROJECT_DIR/.quasi/typecheck-results.json — full per-file detail (for autofix)
```

becomes:

```python
  $CLAUDE_PROJECT_DIR/.quasi/audit/typecheck-report.md    — human-readable summary
  $CLAUDE_PROJECT_DIR/.quasi/audit/typecheck-results.json — full per-file detail (for autofix)
```

- [ ] **Step 3: Smoke-check typecheck.py imports**

```bash
python -c "
import sys
sys.path.insert(0, 'plugins/quasi/scripts/typecheck')
sys.path.insert(0, 'plugins/quasi')
import os
os.environ['QUA_PROJECT_ROOT'] = '/tmp/qua-pathtest'
os.makedirs('/tmp/qua-pathtest/vault', exist_ok=True)
import typecheck
print('OUT_DIR =', typecheck.OUT_DIR)
"
```

Expected: `OUT_DIR = /tmp/qua-pathtest/.quasi/audit`

If you see ImportError on `schemas`, you may need to bootstrap the venv first via `bash plugins/quasi/scripts/bootstrap-venv.sh` — but the constant is verifiable by inspection without running.

- [ ] **Step 4: Update audit-agent.md**

Open `plugins/quasi/agents/audit-agent.md`. Make these replacements:

| Line | Before | After |
|---|---|---|
| 14 | `processing/audit/state.json` | `.quasi/audit/audit-state.json` |
| 43 | `.quasi/typecheck-results.json` | `.quasi/audit/typecheck-results.json` |
| 78 | `.quasi/typecheck-results.json` | `.quasi/audit/typecheck-results.json` |
| 241 | `translations.json` (in table cell — verify context first, may need surrounding path elsewhere) | leave the bare filename alone; the path context is in §4B.5 |
| 255 | `processing/audit/translations.json` | `.quasi/audit/translations.json` |
| 462 | `.quasi/typecheck-results.json` | `.quasi/audit/typecheck-results.json` |

Easiest: use replace-all sed since the patterns are distinct.

```bash
sed -i '' \
  -e 's|processing/audit/state\.json|.quasi/audit/audit-state.json|g' \
  -e 's|processing/audit/translations\.json|.quasi/audit/translations.json|g' \
  -e 's|\.quasi/typecheck-results\.json|.quasi/audit/typecheck-results.json|g' \
  -e 's|\.quasi/typecheck-report\.md|.quasi/audit/typecheck-report.md|g' \
  plugins/quasi/agents/audit-agent.md
```

- [ ] **Step 5: Update schemas/book.py**

Open `plugins/quasi/schemas/book.py`. Find line 50 (inside a description string):

```python
            "$CLAUDE_PROJECT_DIR/processing/audit/translations.json"
```

Replace with:

```python
            "$CLAUDE_PROJECT_DIR/.quasi/audit/translations.json"
```

- [ ] **Step 6: Update docs/ARCHITECTURE.md**

Open `plugins/quasi/docs/ARCHITECTURE.md`. Find line 317:

```
7. **processing/audit/state.json** 落地
```

Replace with:

```
7. **.quasi/audit/audit-state.json** 落地
```

- [ ] **Step 7: Verify**

```
rg "(processing/audit|\.quasi/typecheck-)" plugins/quasi/
```

Expected: zero matches outside `docs/superpowers/specs/` and this plan.

```
rg "\.quasi/audit/" plugins/quasi/
```

Expected: matches in typecheck.py (1), audit-agent.md (≥6), schemas/book.py (1), ARCHITECTURE.md (1), plus whatever existed before in audit.py.

- [ ] **Step 8: Commit**

```bash
git add plugins/quasi/scripts/typecheck/typecheck.py \
        plugins/quasi/agents/audit-agent.md \
        plugins/quasi/schemas/book.py \
        plugins/quasi/docs/ARCHITECTURE.md
git commit -m "refactor(quasi 0.26.0): consolidate audit pipeline under .quasi/audit/

Group D of the artifact-path discipline refactor.

- typecheck.py OUT_DIR: .quasi/ → .quasi/audit/ (one-line code change;
  results.json + report.md now sit alongside audit-state.json).
- audit-agent.md: fix four stale paths
    processing/audit/state.json       → .quasi/audit/audit-state.json
    processing/audit/translations.json → .quasi/audit/translations.json
    .quasi/typecheck-{results,report} → .quasi/audit/typecheck-{results,report}
  audit-agent runtime-writes translations.json per the agent prompt;
  changing the prompt changes the write target.
- schemas/book.py description string updated.
- docs/ARCHITECTURE.md step-7 path updated.

Spec: docs/superpowers/specs/2026-05-18-artifact-paths-design.md"
```

---

## Task 4 — Group E: process-author discovery manifest move

**Files:**
- Modify: `plugins/quasi/skills/process-author/SKILL.md` (lines 51, 234)

The spec mentioned four agent docs (search/download/analyse/synthesis) as potential sites, but a grep across `agents/*.md` for `processing/authors` returned zero hits — the manifest path is only referenced in the skill, and dispatched agents receive it via the prompt-passed path string. So this task only touches one file.

- [ ] **Step 1: Grep current state**

```
rg "processing/authors" plugins/quasi/
```

Expected: 2 matches in `skills/process-author/SKILL.md` (lines 51, 234).

```
rg "processing/authors" plugins/quasi/agents/
```

Expected: zero. (If non-zero — i.e. an agent doc *does* reference the manifest path — extend this task to update those too.)

- [ ] **Step 2: Update process-author/SKILL.md**

Open `plugins/quasi/skills/process-author/SKILL.md`. Two edits:

Line 51:

```python
manifest_path = f"processing/authors/{author_name}/manifest.json"
```

becomes:

```python
manifest_path = f".quasi/authors/{author_name}/manifest.json"
```

Line 234 (inside the 目录结构 fenced block):

```
processing/authors/{author-name}/
└── manifest.json                    ← 采集状态机 + curation reason
```

becomes:

```
.quasi/authors/{author-name}/
└── manifest.json                    ← 采集状态机 + curation reason
```

(Quickest path: single replace-all of `processing/authors/` → `.quasi/authors/` in that file.)

```bash
sed -i '' 's|processing/authors/|.quasi/authors/|g' \
  plugins/quasi/skills/process-author/SKILL.md
```

- [ ] **Step 3: Verify**

```
rg "processing/authors" plugins/quasi/
```

Expected: zero matches outside specs/plans.

```
rg "\.quasi/authors" plugins/quasi/
```

Expected: 2 matches in `skills/process-author/SKILL.md`.

- [ ] **Step 4: Commit**

```bash
git add plugins/quasi/skills/process-author/SKILL.md
git commit -m "refactor(quasi 0.26.0): move processing/authors/ → .quasi/authors/

Group E of the artifact-path discipline refactor.

The discovery manifest drives process-author's phase state machine —
the user never opens it. Per the sharpened principle (processing/
is for user-readable content only), it belongs in .quasi/.

Only one file affected; agents receive the manifest path via the
dispatch prompt and don't hard-code it.

User-visible caveat for 0.26.0 release notes: any author run paused
mid-flight against the old processing/authors/{name}/manifest.json
loses its --resume state; users should finish or abandon before
upgrading.

Spec: docs/superpowers/specs/2026-05-18-artifact-paths-design.md"
```

---

## Task 5 — Group A: citation directory residual cleanup

**Files:**
- Modify: `plugins/quasi/skills/wrap-up/SKILL.md` (lines ~393-410, 中间 / 终产物 tree)
- Modify: `plugins/quasi/scripts/citation/citation.py` (line 15 docstring)
- Modify: `plugins/quasi/agents/citecheck-agent.md` (line 37 example path)

**Key context for this task:** `wrap-up/SKILL.md` already uses `ct_dir = .quasi/citation/{draft-stem}/` (line 127), and all `{ct_dir}` template references throughout Phase 2 resolve correctly. The bulk of Group A's intended scope **was already merged in 0.22.x**. What remains is:

1. The 中间产物 tree (still shows the OLD `processing/citation/` layout).
2. The citation.py module docstring still says `intermediates = {root}/processing/citation/{...}`.
3. The citecheck-agent doc shows `processing/citation/...` in an example.
4. `scripts/citation/render.py:741` has a stale reference too — **leave it alone** (render.py is deprecated per 0.22.0; will be rewritten or deleted separately).

- [ ] **Step 1: Grep current state**

```
rg "processing/citation" plugins/quasi/
```

Expected sites:
- `agents/citecheck-agent.md:37` — example `verdict_out` path
- `scripts/citation/citation.py:15` — docstring
- `scripts/citation/render.py:741` — **leave alone** (deprecated file)
- Plus this plan + the spec (ignore)

- [ ] **Step 2: Update citecheck-agent.md line 37**

Open `plugins/quasi/agents/citecheck-agent.md`. Find line 37:

```
- `verdict_out` — 写出路径,如 `processing/citation/{stem}/verdicts/batch-NNN.json`
```

Replace with:

```
- `verdict_out` — 写出路径,如 `.quasi/citation/{stem}/verdicts/batch-NNN.json`
```

- [ ] **Step 3: Update citation.py docstring**

Open `plugins/quasi/scripts/citation/citation.py`. Find line 15:

```python
    intermediates = {root}/processing/citation/{draft-stem}/
```

Replace with:

```python
    intermediates = {root}/.quasi/citation/{draft-stem}/
```

- [ ] **Step 4: Update wrap-up 中间 / 终产物 tree**

After Group B (Task 1) ran, the tree currently looks like:

```
.quasi/
└── proofread/{stem}/
    └── sections.json

processing/
├── citation/{stem}/
│   ├── biblio.json
│   ├── parse.json
│   ├── manifest.json
│   ├── verdicts/
│   │   ├── batch-001.json     # citecheck-agent context-fit notes
│   │   ├── batch-002.json
│   │   └── recovery-{key}.json # discover-agent online recoveries
│   └── decisions.json         # ← TUI 收集的最终决策
└── (project_root)/
    └── references.bib         # ← 终产物
```

Replace with:

```
.quasi/
├── proofread/{stem}/
│   └── sections.json
└── citation/{stem}/
    ├── biblio.json
    ├── parse.json
    ├── manifest.json
    ├── verdicts/
    │   ├── batch-001.json     # citecheck-agent context-fit notes
    │   ├── batch-002.json
    │   └── recovery-{key}.json # search-agent online recoveries
    └── decisions.json         # ← TUI 收集的最终决策

(project_root)/
└── references.bib             # ← 终产物
```

(Two semantic changes embedded: discover-agent → search-agent in the comment, since the rename happened in 0.25.0; and `processing/` block disappears entirely — `references.bib` lives at project root, not under processing/.)

- [ ] **Step 5: Verify**

```
rg "processing/citation" plugins/quasi/
```

Expected: only `scripts/citation/render.py:741` (deprecated, intentionally skipped) and the spec + plan files. Zero matches in skills / agents / non-deprecated scripts.

- [ ] **Step 6: Commit**

```bash
git add plugins/quasi/skills/wrap-up/SKILL.md \
        plugins/quasi/scripts/citation/citation.py \
        plugins/quasi/agents/citecheck-agent.md
git commit -m "refactor(quasi 0.26.0): citation pipeline path cleanup

Group A of the artifact-path discipline refactor.

The bulk of the citation move (ct_dir = .quasi/citation/...) was
already merged in 0.22.x via wrap-up SKILL Phase 2 refactor. What
remained:

- citecheck-agent.md example verdict_out path.
- citation.py module docstring 'intermediates' line.
- wrap-up/SKILL.md 中间产物 tree (still showed old processing/ layout).

scripts/citation/render.py:741 has a stale path too but render.py is
deprecated per 0.22.0; left untouched for the future rewrite/delete.

Spec: docs/superpowers/specs/2026-05-18-artifact-paths-design.md"
```

---

## Task 6 — Cross-cutting verification + version bump + CLAUDE.md

**Files:**
- Modify: `plugins/quasi/.claude-plugin/plugin.json` (version)
- Modify: `plugins/quasi/.claude-plugin/marketplace.json` (version)
- Modify: `plugins/quasi/CLAUDE.md` (Recent Changes entry)

- [ ] **Step 1: Run the authoritative cross-cutting greps**

```bash
rg -l "processing/(citation|proofread|authors|audit)" plugins/quasi/ | grep -v docs/superpowers
rg -l "/tmp/(snowball|journal|topic|.*-pdfs)" plugins/quasi/ | grep -v docs/superpowers
rg -n "\.quasi/typecheck-(results|report)" plugins/quasi/ | grep -v docs/superpowers
```

Expected for first command: **only** `plugins/quasi/scripts/citation/render.py` (the deprecated file). Nothing else.

Expected for second + third: empty.

If any of these return additional matches, identify and patch them before bumping the version. Do NOT proceed to the bump if greps are dirty.

- [ ] **Step 2: Bump plugin.json**

Read `plugins/quasi/.claude-plugin/plugin.json`. Change the `"version"` field to `"0.26.0"`.

- [ ] **Step 3: Bump marketplace.json**

Read `plugins/quasi/.claude-plugin/marketplace.json`. Change the matching version field to `"0.26.0"`.

- [ ] **Step 4: Run plugin validation**

```bash
claude plugin validate plugins/quasi
```

Expected: no errors / warnings beyond pre-existing ones.

(If `claude` CLI is unavailable in this environment, skip this step and note it for the maintainer to run before tagging.)

- [ ] **Step 5: Add CLAUDE.md Recent Changes entry**

Open `plugins/quasi/CLAUDE.md`. Find the `## Recent Changes` section. Insert this entry **above** the current top entry (`0.25.2`):

```markdown
- **0.26.0** (2026-05-18): **artifact path discipline.** Sharpens the
  `processing/` vs `.quasi/` split on "would the user ever open this
  file?" Everything plumbing-shaped — manifests, indices, audit state,
  dispatch scratch, downloaded temp PDFs — moves into `.quasi/`.
  `processing/` ends minimal: `chapters/` (extracted text the user
  reads when PDFs are unclear) and `translations/` (translated PDFs).
  - Group B: `processing/proofread/{stem}/sections.json` →
    `.quasi/proofread/{stem}/`. Cleanup goes from optional to required.
  - Group C: `/tmp/{journal,topic,snowball}-pdfs/` →
    `.quasi/temp/{journal-pdfs/{name}, topic-pdfs/{name}, snowball-pdfs}/`.
    Brings temp PDFs into the project tree where they're inspectable
    and not subject to macOS /tmp/ reaping.
  - Group D: audit pipeline consolidates under `.quasi/audit/`.
    `scripts/typecheck/typecheck.py` `OUT_DIR` moves from `.quasi/`
    top-level to `.quasi/audit/`. `agents/audit-agent.md` doc paths
    fixed across multiple stale references (state.json,
    translations.json, typecheck-*). `schemas/book.py` description
    string + `docs/ARCHITECTURE.md` echo updated.
  - Group E: `processing/authors/{name}/manifest.json` →
    `.quasi/authors/{name}/manifest.json`. Driver file for the
    process-author phase state machine; user never opens.
  - Group A: residual cleanup. The bulk of the citation move was
    already merged in 0.22.x (`ct_dir = .quasi/citation/...`); this
    release finishes the trailing edges — citecheck-agent example,
    citation.py docstring, wrap-up 中间产物 tree. `render.py:741`
    has a stale reference too but render.py is deprecated per 0.22.0
    and skipped here.
  - User-disk migration: only `authors/{name}/manifest.json` carries
    a real caveat — any author run paused mid-flight loses its
    `--resume` state on upgrade. Finish or abandon before upgrading.
    Other stale dirs (`processing/citation/`, `processing/proofread/`,
    `processing/audit/`, top-level `.quasi/typecheck-*`) become
    harmless orphans the user can `rm -rf` at leisure.
  - Spec: `docs/superpowers/specs/2026-05-18-artifact-paths-design.md`.
    Plan: `docs/superpowers/plans/2026-05-18-artifact-paths.md`.
```

- [ ] **Step 6: Commit**

```bash
git add plugins/quasi/.claude-plugin/plugin.json \
        plugins/quasi/.claude-plugin/marketplace.json \
        plugins/quasi/CLAUDE.md
git commit -m "chore(quasi 0.26.0): version bump + CLAUDE.md changelog

Wraps up the artifact-path discipline refactor (Groups A-E).

Spec: docs/superpowers/specs/2026-05-18-artifact-paths-design.md
Plan: docs/superpowers/plans/2026-05-18-artifact-paths.md"
```

---

## Task 7 — End-to-end smoke test (manual; maintainer-run)

This is a verification task for the maintainer (the user) to run against their actual research project, where real drafts / vault / book corpus exist. The implementer may not have access to such data, so skip this if so and surface as a maintainer todo.

- [ ] **Step 1: wrap-up full pipeline**

In a user research project directory containing a draft with citations:

```bash
quasi:wrap-up path/to/draft.md
```

Expected: produces `.quasi/proofread/<stem>/sections.json`,
`.quasi/citation/<stem>/{parse,manifest,biblio,decisions}.json`, and
`.quasi/citation/<stem>/verdicts/batch-*.json`. Final references.bib
at project root. No files written to `processing/citation/` or
`processing/proofread/`.

- [ ] **Step 2: wrap-up --citation-only re-run**

```bash
quasi:wrap-up path/to/draft.md --citation-only
```

Expected: re-runs Phase 2 cleanly using paths under `.quasi/citation/`.

- [ ] **Step 3: process-author small case**

Pick an author with ≤3 works.

```bash
quasi:process-author author-name "Full Name"
```

Expected: creates `.quasi/authors/<name>/manifest.json` and the phase chain (search → download → extract → analyse → synthesis → audit) completes without errors. No `processing/authors/` directory created.

- [ ] **Step 4: process-topic small snowball**

```bash
quasi:process-topic 10.xxxx/seed-doi
```

Expected: PDFs land under `.quasi/temp/topic-pdfs/<slug>/`, not `/tmp/`.

- [ ] **Step 5: audit on the vault**

```bash
quasi-audit check --path vault
```

Expected: writes `.quasi/audit/typecheck-results.json` and `.quasi/audit/typecheck-report.md`. No files at `.quasi/typecheck-*` top level. No files at `processing/audit/`.

- [ ] **Step 6: Final `ls` of `.quasi/` and `processing/`**

```bash
ls -R .quasi/
ls -R processing/
```

Expected `.quasi/` shape (subset visible — directories appear as the relevant skills run):

```
.quasi/
├── audit/
├── authors/
├── citation/
├── proofread/
└── temp/
```

Expected `processing/` shape:

```
processing/
├── chapters/
└── translations/
```

If extras appear in `processing/` (e.g. lingering `processing/citation/` from a stale run), `rm -rf` them — they're orphans, not produced by 0.26.0 code.

---

## Self-Review Checklist (for the plan author)

- [x] Every change-group in the spec maps to a task: B → Task 1, C → Task 2, D → Task 3, E → Task 4, A → Task 5, verification + bump → Task 6, smoke → Task 7.
- [x] No placeholders ("TBD" / "implement later" / generic "add error handling"). All edits show before/after.
- [x] Each task has its own grep verification.
- [x] Commit message per task with consistent `refactor(quasi 0.26.0): ...` prefix and spec reference.
- [x] render.py:741 explicitly flagged as **intentionally skipped** (deprecated file per 0.22.0), so the final cross-cutting grep allows this single exception.
- [x] Migration order respected: B → C → D → E → A → bump (low-risk doc-only first, citation residual last).
- [x] Spec's "matching `processing/`" minimal shape (`chapters/` + `translations/` only) is what the smoke test verifies.

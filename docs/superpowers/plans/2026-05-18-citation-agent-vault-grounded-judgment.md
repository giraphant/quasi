# citation-agent vault-grounded judgment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-ground `citation-agent`'s context-fit judgment in actual vault summary files (`vault/papers/{slug}.md`, `vault/books/{slug}/00-overview.md`) instead of biblio.json metadata + LLM prior knowledge, and drop `biblio.json` from the agent's input contract.

**Architecture:** Pure prompt + skill text edit. `manifest.json` already carries `candidate.path`; the agent will `Read` that path directly to access the user's curated summary. No Python script changes — `biblio.py` / `resolve.py` / `emit_bib.py` keep their existing roles (biblio.json still feeds `resolve.py` and `emit_bib.py`, just not the agent).

**Tech Stack:** Markdown (agent prompt, skill prompt), JSON (plugin manifest version bump). No new dependencies.

**Spec:** `plugins/quasi/docs/superpowers/specs/2026-05-18-citation-agent-vault-grounded-judgment-design.md`

**Working directory:** All paths below are relative to `/Users/ramudai/.agents/`.

---

## File Map

| File                                         | Action  | Why                                                                 |
|----------------------------------------------|---------|---------------------------------------------------------------------|
| `plugins/quasi/agents/citation-agent.md`     | Modify  | Drop `biblio` input, rewrite execution steps + judgment guidance     |
| `plugins/quasi/skills/wrap-up/SKILL.md`      | Modify  | Drop `biblio:` line from Phase 2.2 dispatch prompt                   |
| `plugins/quasi/.claude-plugin/plugin.json`   | Modify  | Version 0.25.0 → 0.25.1                                              |
| `plugins/quasi/.claude-plugin/marketplace.json` | Modify | Mirror version                                                      |
| `plugins/quasi/CLAUDE.md`                    | Modify  | Add 0.25.1 entry to Recent Changes                                   |

---

## Task 1: Rewrite citation-agent input contract

**Files:**
- Modify: `plugins/quasi/agents/citation-agent.md`

The frontmatter `description` field and the `## 输入参数` section both mention reading vault candidate **元数据** — that wording is the old contract. Drop the `biblio` input and update the description to reflect summary-content judgment.

- [ ] **Step 1: Update frontmatter description**

Read `plugins/quasi/agents/citation-agent.md`. Find the `description:` line in frontmatter (line 3). Replace:

```
description: 校对 draft 引用的 LLM context-fit 判断者 —— 对一批 single-hit / multi-hit 引用, 读 mention 上下文 vs vault candidate 元数据, 判断主题契合 / 挑最契合的候选, 输出极简 note。完全离线, 不带 web 工具, 不出 verdict 枚举。被 wrap-up skill Phase 2 分批 dispatch。
```

With:

```
description: 校对 draft 引用的 LLM context-fit 判断者 —— 对一批 single-hit / multi-hit 引用, 读 mention 上下文 vs vault 摘要正文 (vault/papers/{slug}.md 或 vault/books/{slug}/00-overview.md), 判断主题契合 / 挑最契合的候选, 输出极简 note。完全离线, 不带 web 工具, 不出 verdict 枚举。被 wrap-up skill Phase 2 分批 dispatch。
```

- [ ] **Step 2: Update 输入参数 section**

Find the `## 输入参数` section (line 34-40). Replace the bullet list with:

```
调用方在 prompt 里提供:

- `manifest` — manifest.json 绝对路径(含 candidates + mentions; 每个 candidate 自带 `path` 指向 vault 摘要文件)
- `batch_keys` — 这批要处理的 citation key 列表(一般 8 条; 都是 status=single-hit 或 multi-hit, miss 不会传给你)
- `verdict_out` — 写出路径,如 `processing/citation/{stem}/verdicts/batch-NNN.json`
```

Note: `biblio` bullet is **removed** entirely.

- [ ] **Step 3: Verify file**

Read `plugins/quasi/agents/citation-agent.md`. Confirm:
- Frontmatter `description` mentions "vault 摘要正文"
- `## 输入参数` section has 3 bullets (manifest / batch_keys / verdict_out), no `biblio`

Do NOT commit yet — Tasks 2 and 3 also edit this same file.

---

## Task 2: Rewrite citation-agent execution steps

**Files:**
- Modify: `plugins/quasi/agents/citation-agent.md`

Replace the `## 执行步骤` section (currently lines 94-102) to make the agent Read each candidate's vault summary instead of reading biblio.

- [ ] **Step 1: Edit 执行步骤 section**

Find the `## 执行步骤` block. Replace the entire numbered list with:

```
1. **Read `manifest`** 取出 entries 里 key ∈ batch_keys 的那几条
2. 对每条 entry:
   - 对每个 candidate, **Read `$CLAUDE_PROJECT_DIR/{candidate.path}`** 拿到 vault 摘要正文
   - 单 candidate (single-hit) → picked_slug = 唯一那条, 比对 mention 上下文 vs 摘要内容 → 判契合 → ok / review
   - 多 candidate (multi-hit) → 比对每个候选的摘要内容跟 mention, 挑主题最贴的那条作为 picked_slug, 选好之后再判契合 → ok / review
   - 若 `candidate.path` 文件读不到 (文件缺失或为空) → flag=review, note 注明"vault 摘要 {path} 读不到, 无法基于真实内容判断"
3. Write 一次 `verdict_out`,结束
```

- [ ] **Step 2: Verify file**

Read the modified section. Confirm:
- Step 1 reads manifest only
- Step 2 explicitly says `Read $CLAUDE_PROJECT_DIR/{candidate.path}` per candidate
- Missing-summary fallback is documented

Do NOT commit yet — Task 3 also edits this file.

---

## Task 3: Rewrite 契合度判断要点

**Files:**
- Modify: `plugins/quasi/agents/citation-agent.md`

The current judgment guidance (lines 104-113) directs the agent to look at `title / journal / themes / publisher` fields and lean on LLM prior knowledge. Replace with guidance that forbids metadata-only / prior-knowledge judgment and grounds it in the summary file content.

- [ ] **Step 1: Edit 契合度判断要点 section**

Find the `## 契合度判断要点` section. Replace the entire body with:

```
读 mention 上下文 + candidate 的真实摘要内容 (vault 里那个 .md 文件正文),
问自己: mention 谈的, 跟这本书/篇摘要里写的核心议题对得上吗?

- 摘要明确讨论 mention 谈的概念 / 论点 / 案例 → flag=ok
- 摘要核心议题跟 mention 不在一个 topic → flag=review, note 里说为什么
- multi-hit 时, 挑摘要内容跟 mention 最贴的那条作为 picked_slug
- 若所有 candidates 摘要都不太贴 mention, 挑相对最近的, 仍 flag=review
- **严禁仅凭 title / publisher / LLM 先验知识判断, 必须以 vault 摘要正文为依据**
- 若 vault 摘要读到了但内容明显是空 / 占位 / 只剩 frontmatter → flag=review, note 注明"vault 摘要为占位, 无法判断"
```

- [ ] **Step 2: Verify file**

Read the modified section. Confirm:
- The "严禁仅凭..." line is present (this is the load-bearing instruction)
- No remaining reference to "LLM 知识库提示" guesses
- Placeholder-summary edge case is documented

- [ ] **Step 3: Commit Tasks 1+2+3 together**

```bash
git add plugins/quasi/agents/citation-agent.md
git commit -m "$(cat <<'EOF'
refactor(quasi citation-agent): ground judgment in vault summary, drop biblio input

Drops biblio.json from the agent's input contract. The agent now Reads
each candidate's vault summary file directly via candidate.path (already
present in manifest), and judges context fit against actual summary
content instead of metadata fields + LLM prior knowledge.

Spec: plugins/quasi/docs/superpowers/specs/2026-05-18-citation-agent-vault-grounded-judgment-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Run `git show --stat HEAD` and confirm one file changed (`citation-agent.md`).

---

## Task 4: Drop biblio from wrap-up Phase 2.2 dispatch

**Files:**
- Modify: `plugins/quasi/skills/wrap-up/SKILL.md` (line 155)

The wrap-up skill's Phase 2.2 dispatch prompt currently passes `biblio:` to the agent. With the agent contract change, that argument is no longer used. Drop the one line.

- [ ] **Step 1: Edit Phase 2.2 dispatch block**

Read `plugins/quasi/skills/wrap-up/SKILL.md` around line 152-158. Find the dispatch block:

```
Agent("quasi:citation-agent", background=True,
      prompt=f"manifest: {ct_dir}/manifest.json\n"
             f"biblio: {ct_dir}/biblio.json\n"
             f"batch_keys: {batch_keys_json}\n"
             f"verdict_out: {ct_dir}/verdicts/batch-{NNN}.json")
```

Remove the `biblio:` line so the block becomes:

```
Agent("quasi:citation-agent", background=True,
      prompt=f"manifest: {ct_dir}/manifest.json\n"
             f"batch_keys: {batch_keys_json}\n"
             f"verdict_out: {ct_dir}/verdicts/batch-{NNN}.json")
```

- [ ] **Step 2: Sanity-check other biblio references are unchanged**

`biblio.json` is still used by `resolve.py` (line 134) and `emit_bib.py` (line 352) and listed in the artefact tree (line 400). Run:

```bash
grep -n "biblio" plugins/quasi/skills/wrap-up/SKILL.md
```

Expected lines remaining: 134, 137, 352, 400 (resolve + emit-bib + artefact tree). Line 155 should be **gone**.

- [ ] **Step 3: Commit**

```bash
git add plugins/quasi/skills/wrap-up/SKILL.md
git commit -m "$(cat <<'EOF'
refactor(quasi wrap-up): drop biblio from Phase 2.2 citation-agent dispatch

Pairs with citation-agent's vault-grounded judgment change — biblio.json
is no longer in the agent's input contract.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Version bump 0.25.0 → 0.25.1

**Files:**
- Modify: `plugins/quasi/.claude-plugin/plugin.json` (line 5)
- Modify: `plugins/quasi/.claude-plugin/marketplace.json` (line 11)

Per `plugins/quasi/CLAUDE.md` Release checklist: bump both files in lockstep.

- [ ] **Step 1: Bump plugin.json**

In `plugins/quasi/.claude-plugin/plugin.json` change:

```
"version": "0.25.0",
```

to:

```
"version": "0.25.1",
```

- [ ] **Step 2: Bump marketplace.json**

In `plugins/quasi/.claude-plugin/marketplace.json` line 11, same change: `0.25.0` → `0.25.1`.

- [ ] **Step 3: Validate plugin**

Run:

```bash
claude plugin validate plugins/quasi
```

Expected: validation passes with no warnings about version drift. If `claude` CLI is not available in this environment, skip and proceed.

- [ ] **Step 4: Commit version bump**

```bash
git add plugins/quasi/.claude-plugin/plugin.json plugins/quasi/.claude-plugin/marketplace.json
git commit -m "$(cat <<'EOF'
chore(quasi 0.25.1): version bump for citation-agent vault-grounded judgment

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Update Recent Changes in plugin CLAUDE.md

**Files:**
- Modify: `plugins/quasi/CLAUDE.md` (Recent Changes section)

Add a 0.25.1 entry at the top of the Recent Changes list (the section starts after "## Recent Changes" and lists newest first).

- [ ] **Step 1: Insert 0.25.1 entry**

Find the line `## Recent Changes` in `plugins/quasi/CLAUDE.md`. The next non-blank line is the existing top entry (`- **0.25.0** (2026-05-18): ...`). Insert directly above it:

```
- **0.25.1** (2026-05-18): **citation-agent vault-grounded judgment.**
  Phase 2.2 of `quasi:wrap-up` historically had `citation-agent` judge
  context-fit by reading `biblio.json` metadata fields
  (`title / journal / themes / publisher`) plus LLM prior knowledge.
  That meant judgments for obscure / non-English / idiosyncratically-read
  works degraded into hallucination. Re-grounded:
  - `agents/citation-agent.md` rewritten so each candidate is judged by
    reading the user's actual vault summary file (`vault/papers/{slug}.md`
    or `vault/books/{slug}/00-overview.md`) via `candidate.path` — already
    present in manifest since 0.17.0. New "严禁仅凭 title / publisher /
    LLM 先验知识判断" guard in the judgment guidance.
  - `biblio.json` dropped from the agent's input contract.
    `skills/wrap-up/SKILL.md` Phase 2.2 dispatch no longer passes
    `biblio:` to the agent. `biblio.json` is still produced upstream and
    consumed by `resolve.py` (for manifest building) and `emit_bib.py`
    (for the final .bib) — those uses are unchanged.
  - No Python script changes. `path` field on candidate was already
    propagated from `biblio.py:230` → `resolve.py:101` since the 0.17.0
    citation refactor; this release just starts using it.
  - Token cost: net byte volume to the agent goes **down** (drops a
    whole-vault frontmatter index, picks up a handful of scoped summary
    reads per batch). Main-process context unaffected — same prompt
    shape with one fewer path.
  - Spec: `docs/superpowers/specs/2026-05-18-citation-agent-vault-grounded-judgment-design.md`.
    Plan: `docs/superpowers/plans/2026-05-18-citation-agent-vault-grounded-judgment.md`.
```

- [ ] **Step 2: Verify**

```bash
head -30 plugins/quasi/CLAUDE.md | grep -A2 "## Recent Changes"
```

Expected: the 0.25.1 entry appears immediately under `## Recent Changes`, above 0.25.0.

- [ ] **Step 3: Commit**

```bash
git add plugins/quasi/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(quasi CLAUDE.md): 0.25.1 entry — citation-agent vault-grounded judgment

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Final verification

- [ ] **Step 1: Check commit log**

Run:

```bash
git log --oneline -5
```

Expected (newest first):
- `docs(quasi CLAUDE.md): 0.25.1 entry — ...`
- `chore(quasi 0.25.1): version bump ...`
- `refactor(quasi wrap-up): drop biblio from Phase 2.2 ...`
- `refactor(quasi citation-agent): ground judgment in vault summary ...`
- (earlier — spec commits / unrelated)

- [ ] **Step 2: Confirm no stray edits**

Run:

```bash
git status
```

Expected: tree clean (or only untracked files unrelated to this work, e.g. `models/`, `skills/manage-coolify/`, `skills/use-spark/`, the pre-existing `plugins/quasi/docs/` deletions from the search-refactor cleanup).

- [ ] **Step 3: Print summary**

Print a short final summary listing the 4 functional commits + paths to spec & plan.

No further commit. End of plan.

---

## Out-of-scope (deliberately not in this plan)

- End-to-end smoke test against a real draft + vault. Worth doing manually after merge, but requires a draft in flight; not gated.
- Test fixtures for the agent. The agent is an LLM judgment unit — meaningful tests would be eval-style (test suite of `mention + candidates → expected verdict` cases) which is a separate engineering effort, not blocked on this change.
- `render.py` (already marked stale in 0.22.0). Not touched.
- Updating `--citation-only` flag docs. Behaviour identical — flag still skips Phase 0/1/3 only.

# process-book / process-author reorchestration + process-paper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewire process-book Step 0 and process-author Phase 1/2 around the post-0.24.0 search-bin + post-0.25.0 agent contracts, lift YEAR_TRIAGE into structured `year_evidence` in download-agent's output protocol, and add a new single-paper skill.

**Architecture:** Pure agent-prompt + skill-orchestration edits in `plugins/quasi/`. No bin changes, no Python changes. New skill `process-paper` glues existing agents (search-agent, download-agent, analyse-agent type=B, audit-agent, translate-agent) with no new agent. Version bump to 0.28.0.

**Tech Stack:** Markdown agent definitions + SKILL.md orchestration prose; JSON plugin manifests. Tests are operational ("run the skill") — no automated test framework for skill orchestration in quasi, so this plan uses cheap verification (grep, `claude plugin validate`, file presence) at each step rather than TDD.

**Spec reference:** `plugins/quasi/docs/superpowers/specs/2026-05-18-process-book-author-paper-reorchestration-design.md`. Sections §A through §F drive Tasks 1-7 respectively.

---

## File Map

- **Modify** `plugins/quasi/agents/download-agent.md` — add `year_evidence` protocol section + verdict computation rule (drives §A).
- **Modify** `plugins/quasi/skills/process-book/SKILL.md` — replace Step 0 inline prompt (~80 lines) with thin agent dispatch + verdict branch (drives §B).
- **Modify** `plugins/quasi/skills/process-author/SKILL.md` — rewrite Phase 1 to two structured search-agent calls, Phase 2 to two structured download-agent calls + manifest merge with year_warning (drives §C).
- **Create** `plugins/quasi/skills/process-paper/SKILL.md` — new skill (drives §D).
- **Modify** `plugins/quasi/.claude-plugin/plugin.json` — version `0.27.0` → `0.28.0` (drives §E; skills auto-discovered, no list to update).
- **Modify** `plugins/quasi/.claude-plugin/marketplace.json` — version mirror `0.27.0` → `0.28.0`.
- **Modify** `plugins/quasi/CLAUDE.md` — prepend 0.28.0 changelog entry.

All tasks operate within the quasi subtree (`plugins/quasi/`). Commits stay on branch `qua-29-process-book-author`; do not push subtree changes upstream as part of this plan (the subtree push is a maintainer step, not implementation).

---

### Task 1: download-agent.md — extend output protocol with `year_evidence`

**Files:**
- Modify: `plugins/quasi/agents/download-agent.md` (the `## 行为` and `## 输出` sections)

**Spec ref:** §A.

- [ ] **Step 1: Read current download-agent.md**

Run: read `plugins/quasi/agents/download-agent.md` (77 lines, all sections).

Confirm current `## 输出` section is:

```
DOWNLOAD_RESULT:
- acquired: N
- failed: K
- per_item:
    - {kind, slug, status, path?, source?, verdict_note?}
    - ...
```

and `## 行为` section ends at "**同源**下载间隔 ≥10 秒...跨源可并发。"

- [ ] **Step 2: Append `### 书的 year_evidence` subsection under `## 行为`**

Edit the file to add this block AFTER the existing "**同源**下载间隔 ≥10 秒..." line and BEFORE the `## 凭据故障` section:

```markdown
### 书的 year_evidence（kind=book 专用）

下书时除了"是不是这个作者的这本书"的身份验证，还要收集 year 证据并算 verdict，让 caller 决定怎么用（单本：弹给用户；batch：写进 manifest 静默继续）。

**证据来源**：
- `source_years` ← `quasi-search book --json` 的 `diagnostics.conflicts[]` 中 `field == "year"` 那条的 `evidence` 字典。**只收实际返了 year 的 source**；search bin 的 `errors[]` 里的源不出现在这里。如果 search 那次没产生 year conflict（所有源一致），`source_years` 就是单元素字典 `{<source>: <year>}` 或者干脆空（caller 端把空当作"无歧义"处理）。
- `pdf_signals` ← `quasi-download book get` 回返的 `metadata.year_signals`（含 `first_published / copyright_year / original_year / other_years`）。

**verdict 计算规则**（codified — caller 依赖此规则的确定性）：

1. 计算 `recommended_year`，按优先级：
   - 优先 `pdf_signals.first_published`（若非 null）。
   - 否则取 `source_years` 中的众数（≥2 个源一致的年）；众数并列时取最早。
   - 否则用 `pdf_signals.copyright_year`。
   - 翻译书显式排除 `pdf_signals.original_year`（那是原文年，不是本版年）。
2. `verdict`：
   - `MATCH` ⇔ `slug_year == recommended_year` AND 至少 2 个来源（source_years + pdf_signals 合并计数）支持 `recommended_year`。
   - `MISMATCH` ⇔ `slug_year != recommended_year` AND `recommended_year` 候选明确（一个清楚的赢家）。
   - `AMBIGUOUS` ⇔ 证据散到选不出 `recommended_year`（典型：三源各异且无 pdf signal 仲裁）。
3. `recommendation_reason`：一行说明为什么选这个（如 `"first_published beats copyright by 1y (Q4 press lag); 3/4 sources agree"`）。

**verdict 与 status 映射**：

| verdict | status | path/tmp_path |
|---|---|---|
| `MATCH` | `ok` | mv tmp → final，`path` set，`tmp_path` 不出现 |
| `MISMATCH` | `year_mismatch` | 不 mv，`tmp_path` set，`path` 不出现 |
| `AMBIGUOUS` | `year_ambiguous` | 同上 |
| (下载本身失败) | `download_failed` | 都不出现，也不带 year_evidence |

**论文（kind=paper）不带 year_evidence** —— DOI 一对一，无版本歧义。
```

- [ ] **Step 3: Replace `## 输出` section**

Replace the existing `## 输出` block (lines 68-77) with:

```markdown
## 输出

```
DOWNLOAD_RESULT:
- acquired: N           # status == ok 的计数
- failed: K             # status in {download_failed, year_mismatch, year_ambiguous} 的计数
                        # 注：year_* 不是下载失败，但文件未 finalize；caller 自己根据 status 区分
- per_item:
    - kind: book
      slug: simondon-imagination-and-invention-2017
      status: ok | year_mismatch | year_ambiguous | download_failed
      path: sources/{slug}.{ext}            # status == ok 时存在
      tmp_path: sources/{slug}.tmp.{ext}    # status in {year_mismatch, year_ambiguous} 时存在
      source: anna_archive | ...
      verdict_note: ...                     # 可选；身份验证失败的简述
      year_evidence:                        # kind=book 时总是出现，除非 status==download_failed
        slug_year: 2017
        source_years:
          openlibrary: 2023
          openalex: 2023
        pdf_signals:
          first_published: 2023
          copyright_year: 2022
          original_year: 1965
          other_years: []
        recommended_year: 2023
        recommendation_reason: "..."
        verdict: MATCH | MISMATCH | AMBIGUOUS
    - kind: paper
      slug: ...
      status: ok | download_failed
      path: sources/{slug}.pdf              # status == ok
      source: oa | ezproxy | wayback | ...
      verdict_note: ...                     # 可选
      # 论文无 year_evidence 字段
```
```

- [ ] **Step 4: Verify edits**

Run: `grep -n "year_evidence\|verdict\|recommended_year" plugins/quasi/agents/download-agent.md`

Expected: at least 10 lines, covering the new subsection + the output protocol.

Run: `grep -c "^## " plugins/quasi/agents/download-agent.md`

Expected: 6 (路径 / 工具 / AA 文件搜索 / 行为 / 凭据故障 / 输出).

- [ ] **Step 5: Commit**

```bash
git add plugins/quasi/agents/download-agent.md
git commit -m "$(cat <<'EOF'
feat(quasi/download-agent): structured year_evidence in output protocol

QUA-29 §A. Lifts YEAR_TRIAGE from a process-book prompt addendum into
a first-class field in DOWNLOAD_RESULT.per_item for kind=book. Codifies
verdict computation rule (recommended_year preference order + MATCH /
MISMATCH / AMBIGUOUS criteria). Adds year_mismatch and year_ambiguous
to the status enum; tmp_path is exposed in those cases so callers
can decide whether to pause-and-ask (process-book) or
record-and-continue (process-author batch).
EOF
)"
```

---

### Task 2: process-book/SKILL.md — Step 0 thin caller

**Files:**
- Modify: `plugins/quasi/skills/process-book/SKILL.md` (Step 0 section, currently lines 63-150)

**Spec ref:** §B.

- [ ] **Step 1: Read current Step 0 block**

Confirm the current Step 0 block in `plugins/quasi/skills/process-book/SKILL.md` spans roughly lines 63-150 — from `# Step 0: ACQUIRE & VERIFY` comment through the end of the `if not source_file:` branch (the `source_file = Glob(...)` re-check at line 147 and the `if not source_file:` failure branch at 148-150).

- [ ] **Step 2: Replace the Step 0 block**

Replace lines 63-150 with this thin-caller version:

```python
# Step 0: ACQUIRE & VERIFY
# 调 download-agent;agent 内部做 search → download → identity verify + 算 year_evidence。
# 主进程只做：拿 verdict、按 verdict 分支（MATCH 继续 / 否则弹给用户）。
if not source_file:
    # slug 反解: {author-surname}-{title}-{year}，year 是末尾 4 位数字 segment
    parts = book_slug.rsplit("-", 1)
    slug_year = int(parts[1]) if parts[1].isdigit() and len(parts[1]) == 4 else None
    # author 通常是首 segment（多 segment 姓如 fausto-sterling 需要更长 prefix，
    # 但单 segment 覆盖绝大多数 case；download-agent 自己用 author+title 模糊匹配，
    # 这里给个起手 hint 即可）
    body = parts[0]
    body_parts = body.split("-")
    expected_author = body_parts[0]
    expected_title = " ".join(body_parts[1:])

    result = Agent("quasi:download-agent", foreground=True, prompt=f"""\
kind: book
items:
  - slug: {book_slug}
    expected_author: {expected_author}
    expected_title: {expected_title}
output_dir: sources/
""")

    item = result.per_item[0]
    if item.status == "ok":
        source_file = item.path        # agent 已 mv tmp → final
    elif item.status in ("year_mismatch", "year_ambiguous"):
        # 把 year_evidence 整块原样递给用户（含 tmp_path），让用户拍板：
        # 1) 改 slug 中的 year 重跑（slug 重命名 → 触发 download-agent 重新 finalize）
        # 2) 接受 recommended_year，手动 mv tmp_path → 正式名 + 重跑（跳过 Step 0）
        report(f"""\
YEAR_TRIAGE for {book_slug}: verdict={item.year_evidence.verdict}
- slug_year:        {item.year_evidence.slug_year}
- source_years:     {item.year_evidence.source_years}
- pdf_signals:      {item.year_evidence.pdf_signals}
- recommended_year: {item.year_evidence.recommended_year}
- reason:           {item.year_evidence.recommendation_reason}
- tmp_file:         {item.tmp_path}

Action: 改 slug 的 year 重跑，或手动 mv {item.tmp_path} 到正确路径后重跑。
""")
        return
    else:  # download_failed
        report(f"download-agent failed to acquire {book_slug}: {item.get('verdict_note', 'no details')}")
        return
```

- [ ] **Step 3: Verify edits**

Run: `grep -n "year_evidence\|year_mismatch\|year_ambiguous" plugins/quasi/skills/process-book/SKILL.md`

Expected: ≥ 5 lines, all in the Step 0 block.

Run: `grep -c "YEAR_TRIAGE\|N-source\|discover (quasi-search\|finalize ——" plugins/quasi/skills/process-book/SKILL.md`

Expected: 0 or 1 (the comment header "YEAR_TRIAGE for {book_slug}: ..." in the report() call may keep "YEAR_TRIAGE" as a string; nothing else from the old inline prompt should survive).

Run: `grep -c "## 编排架构\|# Step 0" plugins/quasi/skills/process-book/SKILL.md`

Expected: ≥ 2 (orchestration diagram + step header preserved).

- [ ] **Step 4: Commit**

```bash
git add plugins/quasi/skills/process-book/SKILL.md
git commit -m "$(cat <<'EOF'
refactor(quasi/process-book): Step 0 → thin caller of download-agent

QUA-29 §B. Drops the ~80-line inline YEAR_TRIAGE prompt; consumes the
new structured year_evidence from download-agent's output protocol
(Task 1). Branch on item.status: ok → continue, year_mismatch /
year_ambiguous → report evidence to user verbatim, download_failed →
fail. No more string-match parsing of agent reply prose.
EOF
)"
```

---

### Task 3: process-author/SKILL.md — Phase 1 two structured search-agent dispatches

**Files:**
- Modify: `plugins/quasi/skills/process-author/SKILL.md` (Phase 1 block, currently lines 54-86)

**Spec ref:** §C (Phase 1 only — Phase 2 in Task 4).

- [ ] **Step 1: Confirm Phase 1 block boundaries**

The current Phase 1 dispatches a single search-agent against narrative prompt (lines 54-86), terminated by the closing `""")` before the `# 2. ACQUIRE` comment.

- [ ] **Step 2: Replace Phase 1 block**

Replace lines 54-86 with two structured search-agent dispatches plus a merge step:

```python
# 1. DISCOVER — two structured search-agent calls (kind=book + kind=paper),
# skill main process merges results into the manifest the existing Phase 2+
# code expects.
if not exists(manifest_path):
    books_path  = f".quasi/authors/{author_name}/books.json"
    papers_path = f".quasi/authors/{author_name}/papers.json"

    if not exists(books_path):
        Agent("quasi:search-agent", foreground=True, prompt=f"""\
task: find top representative books by {full_name} on topic {topic}, sorted by citations
context:
  kind: book
  author: {full_name}
  topic: {topic}
constraints:
  count: 5
  sort: citations
  write_policy: create
output_path: {books_path}
output_schema:
  - slug         # canonical {{author-surname}}-{{short-title}}-{{year}}
  - title
  - year
  - isbn_13
  - authors
  - citation_count
  - reason       # 一行 curation 理由 (代表作判断)
""")

    if not exists(papers_path):
        Agent("quasi:search-agent", foreground=True, prompt=f"""\
task: find top representative papers by {full_name} on topic {topic}, sorted by citations
context:
  kind: paper
  author: {full_name}
  topic: {topic}
constraints:
  count: 10
  sort: citations
  write_policy: create
output_path: {papers_path}
output_schema:
  - slug         # canonical {{author-surname}}-{{short-title}}-{{year}}
  - title
  - year
  - doi
  - journal
  - authors
  - citation_count
  - reason
""")

    # Merge into the manifest shape Phase 2+ expects.
    books_raw  = read_json(books_path)
    papers_raw = read_json(papers_path)

    manifest = {
        "author": full_name,
        "slug":   author_name,
        "discovered": today_iso(),
        "books": [
            {**b, "status": "discovered", "md5": None}
            for b in (books_raw if isinstance(books_raw, list) else books_raw.get("results", []))
        ],
        "papers": [
            {**p, "status": "discovered", "oa_url": None}
            for p in (papers_raw if isinstance(papers_raw, list) else papers_raw.get("results", []))
        ],
    }
    write_json(manifest_path, manifest)
```

Note for the executor: `today_iso()`, `read_json`, `write_json` are pseudo-code placeholders matching the rest of this SKILL.md's pseudo-code style. The actual skill body is interpreted by Claude at runtime, not executed as Python — these are instructions for what the LLM should do (use Read tool → parse JSON → Write tool).

- [ ] **Step 3: Verify**

Run: `grep -n "kind: book\|kind: paper\|write_policy: create" plugins/quasi/skills/process-author/SKILL.md`

Expected: ≥ 4 lines (2 each from Phase 1's two dispatches).

Run: `grep -c "Phase 1: search-agent" plugins/quasi/skills/process-author/SKILL.md`

Expected: 1 (the orchestration diagram description; should still mention search-agent).

- [ ] **Step 4: Commit**

```bash
git add plugins/quasi/skills/process-author/SKILL.md
git commit -m "$(cat <<'EOF'
refactor(quasi/process-author): Phase 1 → two structured search-agent calls

QUA-29 §C (Phase 1). Replaces single narrative search-agent dispatch
with two strict-contract dispatches (kind=book + kind=paper), one per
quasi-search verb. Skill main process merges the two result files into
the existing .quasi/authors/{slug}/manifest.json shape so Phase 2+
code keeps working unchanged. Aligns with search-agent's 5-field input
contract (task / context.kind / constraints.write_policy / output_path
/ output_schema) introduced in 0.25.0.
EOF
)"
```

---

### Task 4: process-author/SKILL.md — Phase 2 split book/paper download + year_warning merge

**Files:**
- Modify: `plugins/quasi/skills/process-author/SKILL.md` (Phase 2 block, currently lines 88-104)

**Spec ref:** §C (Phase 2).

- [ ] **Step 1: Confirm Phase 2 block boundaries**

Current Phase 2 (lines 88-104) is the single `Agent("quasi:download-agent", ...)` dispatch with `mode: both` followed by the commented-out DOI liveness section.

- [ ] **Step 2: Replace Phase 2 block**

Replace lines 88-104 with two structured download-agent dispatches + manifest merge:

```python
# 2. ACQUIRE — two structured download-agent calls (kind=book + kind=paper),
# skill merges per-item status + year_evidence back into the manifest.
# Batch policy: year_mismatch / year_ambiguous books DO NOT pause; skill
# mv's tmp_path → sources/{slug}.{ext} (slug authoritative) and records
# year_evidence in manifest.books[i].year_warning for end-of-run report.
manifest = read_json(manifest_path)

# 2a. Books
discovered_books = [b for b in manifest["books"] if b["status"] == "discovered"]
if discovered_books:
    book_result = Agent("quasi:download-agent", foreground=True, prompt=f"""\
kind: book
items:
{format_yaml_list([
    {"slug": b["slug"],
     "expected_author": full_name,
     "expected_title": b["title"]}
    for b in discovered_books
])}
output_dir: sources/
""")
    # Merge per_item back into manifest.books. Agent status → manifest status:
    #   ok → acquired, year_mismatch/year_ambiguous → same name, download_failed → failed.
    for item in book_result.per_item:
        i = index_of(manifest["books"], slug=item["slug"])
        if item["status"] == "ok":
            manifest["books"][i]["status"] = "acquired"
        elif item["status"] in ("year_mismatch", "year_ambiguous"):
            # Override agent's "keep as tmp" — batch mode finalizes anyway,
            # records the year_evidence for offline review.
            Bash(f"mv {item['tmp_path']} sources/{item['slug']}." + extension_of(item["tmp_path"]))
            manifest["books"][i]["status"] = item["status"]
            manifest["books"][i]["year_evidence"] = item["year_evidence"]
            manifest["books"][i]["year_warning"] = (
                f"slug_year={item['year_evidence']['slug_year']} but "
                f"recommended_year={item['year_evidence']['recommended_year']} "
                f"({item['year_evidence']['recommendation_reason']}); "
                f"file finalised under slug — re-run /quasi:process-book {item['slug']} "
                f"to override if you want recommended_year"
            )
        else:  # download_failed
            manifest["books"][i]["status"] = "failed"
            manifest["books"][i]["failure_note"] = item.get("verdict_note", "download_failed")
    write_json(manifest_path, manifest)

# 2b. Papers
discovered_papers = [p for p in manifest["papers"] if p["status"] == "discovered"]
if discovered_papers:
    paper_result = Agent("quasi:download-agent", foreground=True, prompt=f"""\
kind: paper
items:
{format_yaml_list([
    {"slug": p["slug"],
     "expected_author": full_name,
     "expected_title": p["title"],
     "identifiers": {"doi": p["doi"]}}
    for p in discovered_papers
])}
output_dir: sources/
""")
    # Papers: no year_evidence; status is just ok | download_failed.
    for item in paper_result.per_item:
        i = index_of(manifest["papers"], slug=item["slug"])
        if item["status"] == "ok":
            manifest["papers"][i]["status"]     = "acquired"
            manifest["papers"][i]["local_path"] = item["path"]
        else:
            manifest["papers"][i]["status"]       = "failed"
            manifest["papers"][i]["failure_note"] = item.get("verdict_note", "download_failed")
    write_json(manifest_path, manifest)

# End-of-acquire summary (printed by skill main process for visibility):
n_year_warned = sum(1 for b in manifest["books"]
                    if b["status"] in ("year_mismatch", "year_ambiguous"))
n_paper_failed = sum(1 for p in manifest["papers"] if p["status"] == "failed")
if n_year_warned or n_paper_failed:
    report(f"Acquire summary: {n_year_warned} book year warnings, "
           f"{n_paper_failed} paper download failures — review {manifest_path}")
```

- [ ] **Step 3: Update orchestration diagram**

The orchestration ASCII art (around line 32-46) currently shows:

```
├─ Phase 2: download-agent (sonnet, 前台) → 下载
```

Change to:

```
├─ Phase 2: download-agent (sonnet, 前台) × 2 → kind=book + kind=paper
```

- [ ] **Step 4: Update Phase 2 row in the 断点续跑 table**

Current row (around line 231):

```
| Phase 2 | manifest `status` | acquired/failed 跳过 |
```

Change to:

```
| Phase 2 | manifest `status` | acquired / year_mismatch / year_ambiguous / failed 跳过（重跑只处理 discovered）|
```

- [ ] **Step 5: Verify**

Run: `grep -n "kind: book\|kind: paper" plugins/quasi/skills/process-author/SKILL.md`

Expected: ≥ 6 lines (Phase 1's 2 dispatches + Phase 2's 2 dispatches + a stray ones in comments).

Run: `grep -c "mode: both" plugins/quasi/skills/process-author/SKILL.md`

Expected: 0 (old shape fully removed).

Run: `grep -c "year_warning\|year_evidence" plugins/quasi/skills/process-author/SKILL.md`

Expected: ≥ 4 (new fields referenced in the merge code).

- [ ] **Step 6: Commit**

```bash
git add plugins/quasi/skills/process-author/SKILL.md
git commit -m "$(cat <<'EOF'
refactor(quasi/process-author): Phase 2 → split book/paper download + year_warning

QUA-29 §C (Phase 2). Replaces single download-agent dispatch with
mode=both (no longer supported by agent contract) with two strict-
contract dispatches (kind=book + kind=paper). Skill merges per_item
results back into manifest. Batch policy: year_mismatch /
year_ambiguous books do not pause — skill overrides agent's "keep as
tmp" signal, mv's tmp to final under slug-authoritative name, records
year_evidence + a one-line year_warning for end-of-run report. Paper
failures (fail-fast, no candidate retry) recorded with failure_note.
EOF
)"
```

---

### Task 5: process-paper/SKILL.md — new skill

**Files:**
- Create: `plugins/quasi/skills/process-paper/SKILL.md`

**Spec ref:** §D.

- [ ] **Step 1: Verify directory does not yet exist**

Run: `ls plugins/quasi/skills/process-paper/ 2>&1 | head -5`

Expected: `No such file or directory` or similar.

- [ ] **Step 2: Create the skill file**

Write `plugins/quasi/skills/process-paper/SKILL.md` with the following content:

```markdown
---
name: quasi:process-paper
description: >
  Use when the user says "处理这篇论文", "process paper", "跑这篇 paper",
  "summarize this paper", or wants to process a single academic paper
  (search → download → analyse) into vault/papers/{slug}.md.
---

# Process Paper — 单论文处理

最薄的论文处理 skill：复用 search-agent / download-agent / analyse-agent
(type=B) / 可选 translate-agent。无 synthesis 步骤（analyse-agent type=B
一次出全文）。

## 调用方式

```
/quasi:process-paper --doi {doi}
/quasi:process-paper --slug {slug}          # PDF 已在 sources/{slug}.pdf
/quasi:process-paper --title {title} --author {author}
/quasi:process-paper --doi {doi} --translate
```

`{slug}` canonical 格式：`{author-surname}-{short-title}-{year}`（全库
唯一，与 process-author Phase 4 落地的 vault/papers/{slug}.md 同名空间）。

## ⚠ 硬约束

- 单论文流程，无并行后台 agent，无 Glob 轮询。
- 不做 synthesis，不做章节切分（论文非书）。
- `--translate` 走 translate-agent，输出在 `processing/translations/`。

## 编排架构

```
主进程 (dispatcher)
├─ Step 0: ENSURE METADATA + SOURCED
│   ├─ 若 --slug 且 sources/{slug}.pdf 已存在 → 跳过 search/download
│   │   ├─ 若 vault/papers/{slug}.md 存在 → 读 frontmatter 拿 metadata
│   │   └─ 否则 → search-agent (write_policy=verify-only) 取 metadata
│   └─ 否则 → search-agent (create) + download-agent (kind=paper, items=[1])
├─ Step 1: analyse-agent (type=B, 前台) → vault/papers/{slug}.md
├─ Step 2: audit-agent (前台) → 校验 + 一次重做循环
└─ Step 3: translate-agent (前台, 仅 --translate)
```

## 执行流程

```python
args = parse_args()  # --doi / --slug / --title+--author / --translate
project = "$CLAUDE_PROJECT_DIR"

# Step 0: ENSURE METADATA + SOURCED
if args.slug and Glob(f"sources/{args.slug}.pdf"):
    slug = args.slug
    if exists(f"vault/papers/{slug}.md"):
        # 已有 vault 文件 → frontmatter 拿 metadata（题目/作者/年/doi/journal）
        paper_meta = read_frontmatter(f"vault/papers/{slug}.md")
    else:
        # 没 vault 文件 → search-agent verify-only 取 metadata（不写 vault；
        # 写一份临时对比 JSON 到 .quasi/papers/{slug}.search.json 供下游读）
        Agent("quasi:search-agent", foreground=True, prompt=f"""\
task: fetch metadata for paper with slug {slug}
context:
  kind: paper
  slug: {slug}                         # search-agent 从 slug 反解 author/title/year
constraints:
  count: 1
  write_policy: verify-only
output_path: .quasi/papers/{slug}.search.json
output_schema:
  - slug
  - title
  - authors
  - year
  - doi
  - journal
""")
        paper_meta = read_json(f".quasi/papers/{slug}.search.json")["observed"]
    source_pdf = f"sources/{slug}.pdf"
else:
    # 完整 search + download 路径
    # 用临时 search 输出路径，因 slug 在 search 结果里才定稿
    provisional_key = args.doi.replace("/", "_") if args.doi else hash_short(args.title + args.author)
    search_out = f".quasi/papers/_pending-{provisional_key}.search.json"

    Agent("quasi:search-agent", foreground=True, prompt=f"""\
task: find this paper by {'doi=' + args.doi if args.doi else 'title+author=' + args.title + ' / ' + args.author}
context:
  kind: paper
{'  doi: ' + args.doi if args.doi else '  title: ' + args.title + '\\n  author: ' + args.author}
constraints:
  count: 1
  write_policy: create
output_path: {search_out}
output_schema:
  - slug
  - title
  - authors
  - year
  - doi
  - journal
""")
    paper_meta = read_json(search_out)
    if isinstance(paper_meta, list):
        paper_meta = paper_meta[0]
    slug = paper_meta["slug"]

    # download-agent kind=paper, items=[1]
    download_result = Agent("quasi:download-agent", foreground=True, prompt=f"""\
kind: paper
items:
  - slug: {slug}
    expected_author: {paper_meta['authors'][0] if paper_meta.get('authors') else ''}
    expected_title: {paper_meta['title']}
    identifiers:
      doi: {paper_meta.get('doi', '')}
output_dir: sources/
""")
    item = download_result.per_item[0]
    if item["status"] != "ok":
        report(f"download failed for {slug}: {item.get('verdict_note', 'no details')}"); return
    source_pdf = item["path"]

    # 把 search 临时输出迁到 canonical 命名（清理 _pending-）
    Bash(f"mv {search_out} .quasi/papers/{slug}.search.json")

# Step 1: ANALYSE
output_path = f"vault/papers/{slug}.md"
if not exists(output_path):
    analyse = Agent("quasi:analyse-agent", foreground=True,
                    prompt=f"""\
type: B
title:   {paper_meta['title']}
authors: {paper_meta['authors']}
year:    {paper_meta['year']}
journal: {paper_meta.get('journal', '')}
doi:     {paper_meta.get('doi', '')}
input:   {source_pdf}
output:  {output_path}
topic:   {args.topic if args.topic else paper_meta.get('topic', '')}
""")
    if analyse.status == "failed":
        report(f"analyse-agent failed for {slug}"); return

# Step 2: AUDIT (always-on, cheap)
audit = Agent("quasi:audit-agent", foreground=True, prompt=f"path: {output_path}")
if audit.audit_result.escalated:
    for item in audit.audit_result.escalated:
        Agent("quasi:analyse-agent", foreground=True, prompt=f"""\
type: B
title:   {paper_meta['title']}
authors: {paper_meta['authors']}
year:    {paper_meta['year']}
journal: {paper_meta.get('journal', '')}
doi:     {paper_meta.get('doi', '')}
input:   {source_pdf}
output:  {output_path}
topic:   {args.topic if args.topic else paper_meta.get('topic', '')}
overwrite: true
reason:  audit escalated {item.kind}: {item.reason}
""")
    audit = Agent("quasi:audit-agent", foreground=True, prompt=f"path: {output_path}")
    if audit.audit_result.escalated:
        report(f"audit still escalated for {output_path} after one regeneration pass"); return

# Step 3: TRANSLATE (opt-in)
if args.translate:
    Agent("quasi:translate-agent", foreground=True, prompt=f"slug: {slug}")

print(f"Done: vault/papers/{slug}.md" + (" + translation" if args.translate else ""))
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 0 search | `.quasi/papers/{slug}.search.json` | 存在则跳过 search-agent |
| Step 0 download | `sources/{slug}.pdf` | 存在则跳过 download-agent |
| Step 1 | `vault/papers/{slug}.md` | 存在则跳过 analyse-agent |
| Step 2 | 无 —— 幂等 | 上次 audit clean 时几乎无成本 |
| Step 3 | `processing/translations/{slug}-*.pdf` | 存在则 translate-agent 跳过 |

## 目录结构

```
sources/{paper-slug}.pdf                            ← 原 PDF
.quasi/papers/{paper-slug}.search.json              ← search 结果缓存
vault/papers/{paper-slug}.md                        ← 终产物
processing/translations/{paper-slug}-zh.pdf         ← 可选翻译
```

paper-slug 与 process-author Phase 4 / process-topic 共享全库扁平命名
空间 (`{author-surname}-{short-title}-{year}`)。
```

- [ ] **Step 3: Verify**

Run: `ls plugins/quasi/skills/process-paper/SKILL.md`

Expected: file exists.

Run: `grep -c "^## \|^---$" plugins/quasi/skills/process-paper/SKILL.md`

Expected: ≥ 10 (frontmatter delimiters + section headers).

Run: `head -5 plugins/quasi/skills/process-paper/SKILL.md`

Expected: starts with `---\nname: quasi:process-paper\n...`.

- [ ] **Step 4: Commit**

```bash
git add plugins/quasi/skills/process-paper/SKILL.md
git commit -m "$(cat <<'EOF'
feat(quasi/process-paper): new skill for single-paper end-to-end

QUA-29 §D. Glues existing agents (search-agent, download-agent,
analyse-agent type=B, audit-agent, translate-agent) for the
"I have one paper" granularity. Three entry shapes: --doi (preferred),
--slug (PDF already in sources/), --title+--author (fallback). Opt-in
--translate hits translate-agent for a bilingual PDF. No synthesis
step; analyse-agent type=B already produces the full vault/papers/{slug}.md.
EOF
)"
```

---

### Task 6: Version bump 0.27.0 → 0.28.0

**Files:**
- Modify: `plugins/quasi/.claude-plugin/plugin.json` (line 5)
- Modify: `plugins/quasi/.claude-plugin/marketplace.json` (line 11)

**Spec ref:** §E.

- [ ] **Step 1: Edit plugin.json**

In `plugins/quasi/.claude-plugin/plugin.json` line 5, change:

```
  "version": "0.27.0",
```

to:

```
  "version": "0.28.0",
```

- [ ] **Step 2: Edit marketplace.json**

In `plugins/quasi/.claude-plugin/marketplace.json` line 11, change:

```
      "version": "0.27.0",
```

to:

```
      "version": "0.28.0",
```

- [ ] **Step 3: Verify versions match**

Run: `grep '"version"' plugins/quasi/.claude-plugin/plugin.json plugins/quasi/.claude-plugin/marketplace.json`

Expected: both files show `"version": "0.28.0"`.

- [ ] **Step 4: Validate plugin**

Run: `claude plugin validate plugins/quasi`

Expected: validation passes (or warns only — no errors). If errors surface, fix inline before committing.

- [ ] **Step 5: Commit (skips — combine with Task 7 changelog so the version bump and its changelog land together)**

Defer commit to Task 7.

---

### Task 7: CLAUDE.md changelog entry

**Files:**
- Modify: `plugins/quasi/CLAUDE.md` (prepend to "Recent Changes" list)

**Spec ref:** §E.

- [ ] **Step 1: Locate insertion point**

`plugins/quasi/CLAUDE.md` has a `## Recent Changes` section. The most recent entry is `- **0.27.0** (2026-05-18): **local-agent for cndouban backfill...**`. The new entry goes ABOVE that one (most recent first).

- [ ] **Step 2: Prepend the 0.28.0 entry**

Edit `plugins/quasi/CLAUDE.md`: just before the line `- **0.27.0** (2026-05-18): **local-agent for cndouban backfill +`, insert:

```markdown
- **0.28.0** (2026-05-18): **process-book/author reorchestration +
  new process-paper skill.** Rewires process-book Step 0 and
  process-author Phase 1/2 around the post-0.24.0 search-bin and
  post-0.25.0 agent contracts, and lifts YEAR_TRIAGE out of skill
  prose into a structured field in download-agent's output protocol.
  - `agents/download-agent.md`: `DOWNLOAD_RESULT.per_item` for
    `kind=book` gains a `year_evidence` sub-object
    (`slug_year`, `source_years`, `pdf_signals`, `recommended_year`,
    `recommendation_reason`, `verdict`). Status enum grows
    `year_mismatch` and `year_ambiguous`; `tmp_path` exposed in those
    cases. Verdict computation rule codified in the agent prompt:
    `recommended_year` prefers `pdf.first_published` > multi-source
    mode > `pdf.copyright_year`; translation books exclude
    `original_year`; MATCH iff `slug_year == recommended_year` and
    ≥2 corroborating signals. Papers (`kind=paper`) explicitly do not
    carry `year_evidence` — DOIs are one-to-one, no version ambiguity.
  - `skills/process-book/SKILL.md`: Step 0 shrinks from ~80-line
    inline prompt (replicating search→download→finalize chain inside
    download-agent's prompt) to a thin caller — dispatch download-agent
    with `{kind: book, items: [1]}`, branch on `item.status`. `ok` →
    continue to EXTRACT, `year_mismatch`/`year_ambiguous` → report
    `year_evidence` verbatim to user (user changes slug or manually mv
    tmp), `download_failed` → fail. No more string-match parsing of
    agent reply prose.
  - `skills/process-author/SKILL.md`: Phase 1 replaces single
    narrative search-agent dispatch with two strict-contract
    dispatches (kind=book + kind=paper) writing
    `.quasi/authors/{slug}/{books,papers}.json`; skill merges into the
    canonical `manifest.json` shape Phase 2+ already expects. Phase 2
    replaces single `mode=both` download-agent dispatch (no longer
    supported by agent contract) with two structured dispatches
    (kind=book + kind=paper). Batch policy on book year mismatch:
    do NOT pause — skill overrides agent's "keep as tmp" signal,
    `mv`s tmp → final under slug-authoritative name, records
    `year_evidence` + a one-line `year_warning` for end-of-run report.
    Paper failures (fail-fast, no candidate retry) recorded with
    `failure_note`. Manifest status enum grows `year_mismatch` and
    `year_ambiguous`; resume-skip rules updated accordingly.
  - `skills/process-paper/SKILL.md` (new): single-paper end-to-end
    skill — `--doi` (preferred), `--slug` (PDF already in
    `sources/`), or `--title --author` (fallback). Opt-in `--translate`
    flag dispatches translate-agent. Reuses search-agent,
    download-agent, analyse-agent type=B, audit-agent, translate-agent
    with no new agent. No synthesis step; analyse-agent type=B
    already produces the full `vault/papers/{slug}.md`.
  - Spec:
    `docs/superpowers/specs/2026-05-18-process-book-author-paper-reorchestration-design.md`.
    Plan:
    `docs/superpowers/plans/2026-05-18-process-book-author-paper-reorchestration.md`.
  - No bin changes, no Python changes, no user-disk migration.
    process-author manifests with `status: acquired` from earlier
    runs are consumed unchanged; new `status: year_mismatch` /
    `year_ambiguous` entries are treated as `acquired` by downstream
    Phase 3+ (file is on disk, just with a year warning attached).
```

- [ ] **Step 3: Verify**

Run: `grep -n "0\\.28\\.0\\|0\\.27\\.0" plugins/quasi/CLAUDE.md | head -5`

Expected: 0.28.0 line precedes 0.27.0 line.

- [ ] **Step 4: Commit (combined with Task 6 version bump)**

```bash
git add plugins/quasi/.claude-plugin/plugin.json plugins/quasi/.claude-plugin/marketplace.json plugins/quasi/CLAUDE.md
git commit -m "$(cat <<'EOF'
chore(quasi 0.28.0): version bump + CLAUDE.md changelog

QUA-29. process-book/author reorchestration around post-0.24.0
search-bin + post-0.25.0 agent contracts; YEAR_TRIAGE lifted into
structured year_evidence in download-agent's output protocol; new
process-paper skill for single-paper end-to-end. Detailed entry in
CLAUDE.md Recent Changes.
EOF
)"
```

---

### Task 8: Final sanity sweep

**Files:**
- Read-only verification across the repo.

- [ ] **Step 1: Plugin validate**

Run: `claude plugin validate plugins/quasi`

Expected: no errors. Warnings (e.g. about subtree git config) are acceptable.

- [ ] **Step 2: Grep sweep — old shape gone**

Run: `grep -rn "mode: both" plugins/quasi/skills/ plugins/quasi/agents/`

Expected: 0 hits (old download-agent invocation form fully purged).

Run: `grep -rn "YEAR_TRIAGE" plugins/quasi/skills/ plugins/quasi/agents/`

Expected: 0-1 hits (allowed: the human-readable label `"YEAR_TRIAGE for {book_slug}:"` in process-book's report() call; not allowed: inline prompt instructions to the agent telling it to "emit YEAR_TRIAGE block").

- [ ] **Step 3: Grep sweep — new shape present**

Run: `grep -rn "year_evidence" plugins/quasi/`

Expected: ≥ 10 hits across download-agent.md, process-book/SKILL.md, process-author/SKILL.md, changelog, spec, plan.

Run: `grep -rln "quasi:download-agent\|quasi:search-agent" plugins/quasi/skills/`

Expected: 4 files — process-book, process-author, process-paper (new), and possibly wrap-up (untouched in this work; OK).

- [ ] **Step 4: Confirm skills load order intact**

Run: `ls plugins/quasi/skills/`

Expected: includes `process-paper/` alongside `process-book/`, `process-author/`, `process-topic/`, `process-journal/`, `wrap-up/`.

- [ ] **Step 5: Confirm version**

Run: `grep -h '"version"' plugins/quasi/.claude-plugin/*.json`

Expected: both `0.28.0`.

- [ ] **Step 6: Branch state check**

Run: `git log --oneline -8`

Expected: 7 new commits ahead of the original `de83df1` baseline — spec (already there from earlier), plan, Task 1 (download-agent), Task 2 (process-book), Task 3 (process-author Phase 1), Task 4 (process-author Phase 2), Task 5 (process-paper), Task 6+7 combined (version + changelog).

- [ ] **Step 7: Commit this plan file**

```bash
git add plugins/quasi/docs/superpowers/plans/2026-05-18-process-book-author-paper-reorchestration.md
git commit -m "$(cat <<'EOF'
plan(quasi): implementation plan for process-book/author/paper reorchestration

QUA-29 implementation plan, drives Tasks 1-8. Paired with the spec
committed in 75f06c4.
EOF
)"
```

(If this plan file was already committed in a prior step, skip Step 7.)

- [ ] **Step 8: Final summary report to user**

Print to user:

- 7 commits land on `qua-29-process-book-author`
- Files modified: 5 (download-agent.md, process-book/SKILL.md, process-author/SKILL.md, plugin.json, marketplace.json, CLAUDE.md)
- Files created: 2 (process-paper/SKILL.md, this plan doc)
- Operational test pending: user runs `/quasi:process-paper --doi <test-doi>` to smoke-test the new skill; user runs `/quasi:process-book` against an existing slug to confirm Step 0 still acquires correctly.
- Branch ready for review / PR / subtree push back to giraphant/quasi (subtree push is a maintainer step, NOT auto-performed).

---

## Out of Scope (reaffirmed from spec §F)

- No bin (Python) changes. quasi-search and quasi-download are stable post-0.24.0.
- No search-agent rewrite. Its 5-field contract is already in place since 0.25.0; this work updates callers only.
- No changes to process-topic, process-journal, or wrap-up. They have their own download/search call sites that may benefit from similar treatment, but that is a separate ticket.
- No `AskUserQuestion`-on-each-book in process-author batch mode. Year warnings live in the manifest for offline review.
- No vault schema changes. process-paper produces files indistinguishable from process-author Phase 4 / process-topic outputs.

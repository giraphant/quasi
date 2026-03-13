# Extract Subagent Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the main-process Bash extraction in `process-book/SKILL.md` with a subagent-driven extract→verify→repair loop.

**Architecture:** Two new subagent roles (Extract Agent on Sonnet, Verify Agent on Haiku) replace the direct Bash call in Step 1. The coordinator prompt gets a minor addition for chapter quality feedback. All changes are in one file: `skills/process-book/SKILL.md`.

**Tech Stack:** Claude Code Agent tool, Sonnet/Haiku models, existing Python extraction scripts (unchanged).

**Spec:** `docs/superpowers/specs/2026-03-13-extract-subagent-design.md`

---

## Chunk 1: Update process-book/SKILL.md

This is a single-file change to a skill document (markdown). No code scripts are modified. No tests apply — this is a prompt/workflow specification.

### Task 1: Update frontmatter and header section

**Files:**
- Modify: `skills/process-book/SKILL.md:1-44`

- [ ] **Step 1: Update the frontmatter description**

Change `description` to reflect the new subagent-driven extraction:

```yaml
---
name: quasi:process-book
type: workflow
description: >
  Composite skill: processes a book from EPUB/PDF to structured summaries.
  Subagent-driven: main process dispatches extract agent (Sonnet) + verify agent (Haiku)
  for chapter extraction, then book-coordinator (Opus) for analysis.
  Use when the user says "处理这本书", "跑一下这本handbook", "总结这本".
argument-hint: "[book-name]"
---
```

- [ ] **Step 2: Update the architecture diagram (lines 30-36)**

Replace the current diagram:

```
主进程 (dispatcher, ~3 次工具调用)
│
├─ Step 1: extract (Bash)            [前台, 等待完成]
├─ Step 2: book-coordinator          [前台/后台, 等待完成]
└─ Step 3: kb-update-agent (可选)    [前台, 等待完成]
```

With:

```
主进程 (dispatcher, ~3-6 次工具调用，0 次读取文件内容)
│
├─ Step 1: 提取章节（子代理驱动）
│   ├─ 1a. 断点检查: manifest.json 存在 → 跳到 1c
│   ├─ 1b. 提取代理 (Sonnet, 前台)
│   ├─ 1c. 验证代理 (Haiku, 前台)
│   └─ 1d. [验证失败] 提取代理修复 + 再验证，最多 2 轮
├─ Step 2: book-coordinator (Opus, 前台)
│   └─ coordinator 发现章节质量问题 → 报告主进程 → 主进程派提取代理修复
└─ Step 3: kb-update-agent (可选, 前台)
```

- [ ] **Step 3: Update the "主进程禁止做的事" list**

Add a new item:
```
- 读取 PDF/txt 文件内容（全部交给提取代理和验证代理）
```

- [ ] **Step 4: Commit**

```bash
git add skills/process-book/SKILL.md
git commit -m "refactor(process-book): update header and architecture for subagent extraction"
```

---

### Task 2: Replace Step 1 with subagent-driven extraction

**Files:**
- Modify: `skills/process-book/SKILL.md:47-69` (current Step 1 section)

- [ ] **Step 1: Replace the entire Step 1 section (lines 47-69)**

Replace everything from `## Step 1: 提取章节（extract）` to the `---` before Step 2 with:

```markdown
## Step 1: 提取章节（子代理驱动）

**调度方式**：主进程派发提取代理 + 验证代理（不直接执行脚本）

### Step 1a: 断点检查

`processing/chapters/{book-name}/manifest.json` 存在 → 跳到 Step 1c（验证）。

### Step 1b: 提取代理 (Sonnet, 前台)

提取代理负责：读取 PDF TOC → 决策提取模式 → 运行脚本 → 碎片化自修。

**子代理 prompt 模板**：

` ` `
你是章节提取代理。任务：从学术书籍中提取章节级纯文本。

文件信息：
- 源文件: {source_file}
- 格式: {format} (epub/pdf)
- 输出目录: {chapters_dir}
- 脚本路径: {script_base}/process_epub.py, {script_base}/split_chapters.py

{repair_section}

执行步骤：

如果格式是 EPUB：
  1. 直接运行: python3 {script_base}/process_epub.py {source_file} {chapters_dir}
  2. 检查输出，报告结果

如果格式是 PDF：
  1. 用 Read 工具读取 PDF 前 8 页，找到目录（TOC）页
  2. 判断 PDF 结构：
     - 目录清晰、章节边界明确 → 用自动模式
     - 目录模糊、脚注密集、结构复杂 → 构造 --chapters JSON 用手动模式
  3. 运行提取:
     自动模式: python3 {script_base}/split_chapters.py {source_file} --output-dir {chapters_dir} --max-chapters 150
     手动模式: python3 {script_base}/split_chapters.py {source_file} --output-dir {chapters_dir} --chapters '<JSON>'
     --chapters JSON 格式: [{"title": "...", "start": 页码, "end": 页码}, ...]
  4. 检查输出：如果章节数 >100，说明碎片化。从 TOC 构造 --chapters JSON，用手动模式重跑
  5. 如果提取脚本无输出或报错，检查是否为扫描版 PDF（无可选文本），报告需要 OCR

如果存在手动 manifest（manifest.json 中有 chapters 和 start_page/end_page 字段）：
  注意：manifest 使用 start_page/end_page 键名，但 --chapters 参数需要 start/end 键名
  需要做映射：start_page → start, end_page → end
  使用映射后的页码范围，以手动模式运行 split_chapters.py

输出格式（最后一条消息必须包含）：
EXTRACT_RESULT:
- status: success | partial | failed
- chapter_count: N
- method: auto | manual | epub
- notes: ...
` ` `

修复模式下 `{repair_section}` 替换为：
` ` `
这是修复模式。上一轮验证发现以下问题：
{problem_list}

请根据问题类型决定：
- 个别章节有问题 → 用 --pages 和 --title 参数重新提取指定章节
- 大面积问题 → 全量重跑（删除输出目录后重新提取）
` ` `

**主进程收到**：EXTRACT_RESULT 摘要（几行文字，无文件内容）

### Step 1c: 验证代理 (Haiku, 前台)

验证代理负责：读取每个 txt 头尾 100 行 → 结构校验 → 报告 pass/fail。

**注意**：即使 manifest 已存在（断点续跑），也必须运行验证。

**子代理 prompt 模板**：

` ` `
你是章节验证代理。任务：检查提取的章节文本质量。

目录: {chapters_dir}
Manifest: {chapters_dir}/manifest.json

执行步骤：

1. 读取 manifest.json，记录章节列表和总数
2. 用 Glob 列出 {chapters_dir}/*.txt，确认文件数与 manifest 一致
3. 对每个 txt 文件：
   - 用 Read 读取前 100 行（offset=0, limit=100）
   - 对于尾部：先用 Bash 运行 wc -l 获取行数，再用 Read 读取最后 100 行
   - 如果文件不足 200 行，直接一次读完整个文件即可
   - 检查：
     a) 开头是否有章节起始标志（标题、章节号、作者名等）
     b) 结尾是否自然结束（不是句子截断）
     c) 内容是否可读（非乱码、非二进制）
     d) 文件是否非空且有合理长度（>50 词）
4. 碎片化检查：如果总章节数 >100，标记为碎片化问题
5. 汇总问题

输出格式（最后一条消息必须包含）：
VERIFY_RESULT:
- status: pass | fail
- total_chapters: N
- problems: [
    {file: "filename.txt", issue: "description"},
    ...
  ]

如果没有问题，problems 为空列表，status 为 pass。
` ` `

**主进程收到**：VERIFY_RESULT 摘要（pass/fail + 问题列表）

### Step 1d: 修复循环（最多 2 轮）

如果验证失败：
1. 派发提取代理（Sonnet），prompt 中附上问题列表（修复模式）
2. 再派发验证代理（Haiku）
3. 最多重复 2 轮。仍失败则报告用户，需人工介入。
```

- [ ] **Step 2: Commit**

```bash
git add skills/process-book/SKILL.md
git commit -m "refactor(process-book): replace Step 1 Bash with extract+verify subagents"
```

---

### Task 3: Update coordinator prompt for chapter quality feedback

**Files:**
- Modify: `skills/process-book/SKILL.md:80-125` (coordinator prompt template)

- [ ] **Step 1: Add quality monitoring and update completion report in coordinator prompt**

In the coordinator prompt template (lines 80-125):

1. After 步骤 4 (生成概览, line 122), add:
```
步骤 5 — 章节质量监控：
  在分析过程中，如果发现某章节文本有明显质量问题（截断、乱码、空白过多），
  在完成报告中列出问题章节。
```

2. Replace the existing closing line (line 124, `完成后报告：N 章已分析、概览已生成。`) with:
```
完成后报告格式（最后一条消息必须包含）：
- chapters_analyzed: N
- overview: generated | skipped
- chapter_problems: [
    {file: "ch05_xxx.txt", issue: "text appears truncated at page boundary"},
    ...
  ]
  如果无质量问题，chapter_problems 为空列表。
```

3. On line 101, replace `Task tool` with `Agent tool` (align with new convention).

- [ ] **Step 1b: Also update line 101 reference from `Task tool` to `Agent tool`**

Change: `对不存在的，启动 1 个后台子代理（Task tool）：` → `对不存在的，启动 1 个后台子代理（Agent tool）：`

- [ ] **Step 2: Commit**

```bash
git add skills/process-book/SKILL.md
git commit -m "feat(process-book): add chapter quality feedback to coordinator prompt"
```

---

### Task 4: Update pseudocode, checkpoint table, and core principles

**Files:**
- Modify: `skills/process-book/SKILL.md:142-211` (pseudocode, checkpoint table, principles)

- [ ] **Step 1: Replace the pseudocode section (主进程完整执行流程)**

```python
# 伪代码 — 主进程只做调度

# 0. 读参数
book_name = parse_args()  # kebab-case
source_file = find("sources/{book_name}.epub") or find("sources/{book_name}.pdf")
format = "epub" if source_file.endswith(".epub") else "pdf"
chapters_dir = f"processing/chapters/{book_name}/"
# output_dir 由书籍类型决定：
#   - Handbook/编著 → vault/handbooks/{book_name}/
#   - 单一作者专著 → vault/monographs/{book_name}/
output_dir = determine_output_dir(book_name)

# 1. EXTRACT（子代理驱动）
# 1a. 断点检查
if not exists(f"{chapters_dir}/manifest.json"):
    # 1b. 提取代理 (Sonnet, 前台)
    Agent(extract_prompt.format(...), model="sonnet", foreground=True)

# 1c. 验证代理 (Haiku, 前台) — 即使断点续跑也必须验证
verify_result = Agent(verify_prompt.format(...), model="haiku", foreground=True)

# 1d. 修复循环（最多 2 轮）
retries = 0
while verify_result.status == "fail" and retries < 2:
    Agent(extract_fix_prompt.format(problems=verify_result.problems),
          model="sonnet", foreground=True)
    verify_result = Agent(verify_prompt.format(...), model="haiku", foreground=True)
    retries += 1

if verify_result.status == "fail":
    report_to_user("提取经过 2 轮修复仍有问题，需要人工检查")
    return

# 2. BOOK-COORDINATOR [前台]
if not exists(f"{output_dir}/00-overview.md"):
    coordinator_result = Agent(book_coordinator_prompt, model="opus", foreground=True)

    # Step 2 反馈：coordinator 报告章节质量问题（最多 1 轮修复）
    if coordinator_result.has_chapter_problems:
        Agent(extract_fix_prompt.format(problems=coordinator_result.problems),
              model="sonnet", foreground=True)
        Agent(verify_prompt.format(...), model="haiku", foreground=True)
        # 重新派发 coordinator（断点续跑，只处理未完成的章节）
        Agent(book_coordinator_prompt, model="opus", foreground=True)

# 3. KB UPDATE [前台, 可选]
if user_requests_kb_update:
    Agent(kb_update_prompt, model="opus", foreground=True)

# 4. 报告完成
summary_count = len(Glob(f"{output_dir}/ch*.md"))
print(f"Done: {summary_count} chapters analyzed, overview generated")
```

- [ ] **Step 2: Replace the checkpoint table (断点续跑汇总)**

```markdown
| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 1b (提取) | `processing/chapters/{book-name}/manifest.json` | 存在则跳过提取 |
| Step 1c (验证) | 不跳过 | 即使 manifest 已存在也必须验证 |
| Step 1d (修复) | 验证通过 | 通过则跳过修复 |
| Step 2 (整体) | `{output_dir}/00-overview.md` | 存在则跳过整个 coordinator |
| Step 2 (逐章) | `{output_dir}/ch{NN}-*.md` | 存在则跳过该章分析（coordinator 内部检查） |
| Step 2 反馈 | coordinator 报告问题 | 仅在 coordinator 报告质量问题时执行 |
| Step 3 | — | 用户手动决定 |
```

- [ ] **Step 3: Update core principles (核心原则)**

Replace with:

```markdown
## 核心原则

1. **主进程只做 dispatcher**：~3-6 次工具调用，不读取任何文件内容
2. **提取由子代理完成**：提取代理 (Sonnet) 负责智能提取 + 碎片化自修，验证代理 (Haiku) 负责质量校验
3. **两层防线**：提取代理自修碎片化，验证代理兜底检查
4. **有限重试**：修复最多 2 轮，超过则报告用户
5. **断点续跑时仍验证**：即使 manifest 已存在，也运行验证代理确保质量
6. **book-coordinator 有独立上下文**：章节筛选、分析派发、轮询、概览生成全在 coordinator 内完成
7. **coordinator 可反馈章节质量问题**：主进程根据反馈派修复代理，最多 1 轮
8. **每章 1 个分析代理**，`model: "opus"`，由 coordinator 并行启动
9. **完成检查用 Glob**：不用 TaskOutput（避免导入子代理 transcript）
10. **正确的模型选型**：Sonnet/Haiku 做结构性任务，Opus 做分析性任务
```

- [ ] **Step 4: Commit**

```bash
git add skills/process-book/SKILL.md
git commit -m "refactor(process-book): update pseudocode, checkpoints, and principles for subagent extraction"
```

---

### Task 5: Final review and version bump

**Files:**
- Modify: `skills/process-book/SKILL.md` (full file review)
- Modify: `CLAUDE.md` (version bump + release notes)

- [ ] **Step 1: Read the full updated SKILL.md and verify internal consistency**

Check:
- Architecture diagram matches pseudocode
- Prompt templates match spec
- Checkpoint table matches flow logic
- No references to old "Bash 直接执行" pattern remain

- [ ] **Step 2: Update CLAUDE.md with version bump and release notes**

Add to Recent Major Features:
```
- v0.3.2: Refactor process-book Step 1 — subagent-driven extraction (Sonnet extract + Haiku verify) replaces direct Bash execution, freeing main process context window
```

- [ ] **Step 3: Commit**

```bash
git add skills/process-book/SKILL.md CLAUDE.md
git commit -m "chore: bump version to 0.3.2, release notes for subagent extraction"
```

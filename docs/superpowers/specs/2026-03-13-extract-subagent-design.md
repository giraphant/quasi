# Extract Subagent Redesign

## Problem

In `process-book`, Step 1 (chapter extraction) runs directly in the main process via Bash. PDF content and script output fill the main context window, wasting tokens on content the main process never uses for decision-making.

## Solution

Delegate extraction to subagents. Two roles:

- **Extract Agent** (Sonnet): intelligent extraction + repair
- **Verify Agent** (Haiku): structural validation

Main process sees only structured summaries — zero PDF/txt content.

## Architecture

```
Step 1: Chapter Extraction (subagent-driven)

Main process (~3-6 tool calls, 0 file content reads)
│
├─ 1a. Checkpoint: manifest.json exists → skip to 1c
├─ 1b. Dispatch Extract Agent (Sonnet, foreground)
├─ 1c. Dispatch Verify Agent (Haiku, foreground)
├─ 1d. [verify fail] Dispatch Extract Agent with problem list (Sonnet, foreground)
│      └─ Re-dispatch Verify Agent (Haiku), max 2 repair rounds
└─ Verify pass → proceed to Step 2

Step 2 feedback loop (within coordinator completion message):
  book-coordinator discovers chapter quality issues during analysis
  → includes problem list in completion report
  → main process dispatches Extract Agent to fix specific chapters
  → re-dispatches Verify Agent
  → main process re-dispatches coordinator (checkpoint resumes from unfinished chapters)
```

## Extract Agent (Sonnet)

### Responsibilities

- Extract chapters from EPUB/PDF
- For PDF: read TOC pages (typically pages 3-8, use Read tool on PDF) to judge structure
- Decide extraction mode: auto (let script detect) vs manual (`--chapters` JSON with explicit page ranges)
- Run extraction scripts (`process_epub.py` / `split_chapters.py`)
- Self-repair on fragmentation: if >100 fragments, construct `--chapters` JSON from TOC reading and re-run in manual mode. Note: `split_chapters.py` has a built-in `--max-chapters` default of 50 and will attempt auto-recovery at that threshold. Pass `--max-chapters 150` to let the agent handle fragmentation detection at the >100 level instead of the script's default
- Accept problem list from verify agent and perform targeted (single chapter `--pages`) or full re-extraction
- For EPUB: straightforward — just run `process_epub.py`, no special decision-making needed

### Input (via prompt)

- Source file path, output directory, file format (epub/pdf)
- Script paths (relative to skill base directory)
- [On repair] Problem list from verify agent

### Manual mode `--chapters` JSON schema

When constructing manual chapter definitions, use this exact format:
```json
[
  {"title": "Introduction", "start": 1, "end": 15},
  {"title": "Chapter 1 - Networks", "start": 16, "end": 45}
]
```
Keys: `title` (string), `start` (int, page number), `end` (int, page number).

### Output (structured, last message)

```
EXTRACT_RESULT:
- status: success | partial | failed
- chapter_count: N
- method: auto | manual | epub
- notes: free text (e.g., "fragmentation detected, switched to manual mode")
```

### Edge cases

- **Zero output**: If extraction script produces no files (encrypted PDF, corrupted file, missing dependencies), report `status: failed` with error details.
- **Scanned PDF (no selectable text)**: If auto mode produces empty/garbled text, note in output that OCR may be needed. Do NOT run `ocr_pdf.sh` automatically — report back and let main process decide (OCR is slow and may need user confirmation).
- **Manual manifest already exists**: If `manifest.json` already exists with `"format": "pdf"` and `"chapters"` containing page ranges (user-created manual manifest), use those page ranges in manual mode rather than auto-detecting.

### Prompt Template

```
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
```

修复模式的 `{repair_section}` 替换为：
```
这是修复模式。上一轮验证发现以下问题：
{problem_list}

请根据问题类型决定：
- 个别章节有问题 → 用 --pages 和 --title 参数重新提取指定章节
- 大面积问题 → 全量重跑（删除输出目录后重新提取）
```

## Verify Agent (Haiku)

### Responsibilities

- Read `manifest.json`, check structural completeness
- For each txt file: read first 100 lines + last 100 lines (for files <200 lines, read entire file)
- Validate:
  - Chapter opening has reasonable markers (heading, chapter number, etc.)
  - Ending is not truncated mid-sentence
  - File is non-empty and has reasonable length
  - Content appears coherent (not garbled/encoded)
- Fragmentation check: flag if >100 chapters
- Cross-check: number of txt files matches manifest chapter count
- Report structured result

### Input (via prompt)

- Chapter directory path
- manifest.json path

### Output (structured, last message)

```
VERIFY_RESULT:
- status: pass | fail
- total_chapters: N
- problems: [
    {file: "ch03_xxx.txt", issue: "truncated ending"},
    {file: "ch07_xxx.txt", issue: "empty file"},
    ...
  ]
```

### Tool call note

For a book with N chapters, the verify agent makes ~2N Read calls (head + tail per file) plus 1 for manifest. For short files (<200 lines) only 1 Read call. This is cheap with Haiku.

### Prompt Template

```
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
```

## Tool Naming Convention

The pseudocode uses `Agent()` which maps to the Claude Code `Agent` tool. The existing `process-book/SKILL.md` uses `Task()` in pseudocode — when implementing, update the SKILL.md to use `Agent()` consistently, as that is the actual tool name.

## Main Process Flow (pseudocode)

```python
book_name = parse_args()
source_file = find_source(book_name)  # .epub or .pdf
chapters_dir = f"processing/chapters/{book_name}/"
format = "epub" if source_file.endswith(".epub") else "pdf"

# === Step 1: Extract (subagent-driven) ===

# 1a. Checkpoint
if not exists(f"{chapters_dir}/manifest.json"):
    # 1b. Extract Agent (Sonnet, foreground)
    Agent(extract_prompt.format(...), model="sonnet", foreground=True)

# 1c. Verify Agent (Haiku, foreground)
verify_result = Agent(verify_prompt.format(...), model="haiku", foreground=True)

# 1d. Repair loop (max 2 rounds)
retries = 0
while verify_result.status == "fail" and retries < 2:
    Agent(extract_fix_prompt.format(problems=verify_result.problems),
          model="sonnet", foreground=True)
    verify_result = Agent(verify_prompt.format(...), model="haiku", foreground=True)
    retries += 1

if verify_result.status == "fail":
    report_to_user("提取经过 2 轮修复仍有问题，需要人工检查")
    return

# === Step 2: Book Coordinator (existing logic) ===
if not exists(f"{output_dir}/00-overview.md"):
    coordinator_result = Agent(book_coordinator_prompt, model="opus", foreground=True)

    # Step 2 feedback: coordinator may report chapter quality issues (max 1 feedback cycle)
    if coordinator_result.has_chapter_problems:
        Agent(extract_fix_prompt.format(problems=coordinator_result.problems),
              model="sonnet", foreground=True)
        Agent(verify_prompt.format(...), model="haiku", foreground=True)
        # Re-dispatch coordinator (checkpoint resumes from unfinished chapters)
        Agent(book_coordinator_prompt, model="opus", foreground=True)

# === Step 3: KB update (optional, unchanged) ===
```

## Checkpoint Behavior

| Stage | Check | Skip condition |
|-------|-------|----------------|
| 1b (extract) | `manifest.json` exists | Skip extraction |
| 1c (verify) | Never skipped | Always verify, even on resume |
| 1d (repair) | Verify passes | Skip repair |
| Step 2 | `00-overview.md` exists | Skip coordinator |
| Step 2 feedback | Coordinator reports problems | Only if coordinator flags issues |

Key: on resume, extraction is skipped but verification always runs to ensure quality.

Note: if `00-overview.md` exists from a previous run, Step 2 is skipped entirely (including feedback). This is correct — if the overview was already generated, any chapter quality issues were either acceptable or already resolved.

## Step 2 Feedback Integration

The book-coordinator may discover chapter quality issues during analysis (e.g., a chapter's text is truncated or garbled). The coordinator already has a completion report format — we add a `chapter_problems` field:

```
Coordinator completion report (last message):
- chapters_analyzed: N
- overview: generated | skipped
- chapter_problems: [
    {file: "ch05_xxx.txt", issue: "text appears truncated at page boundary"},
    ...
  ]
```

If `chapter_problems` is non-empty, main process:
1. Dispatches Extract Agent (Sonnet) with the problem list
2. Dispatches Verify Agent (Haiku) to re-check affected files
3. Re-dispatches coordinator — existing per-chapter checkpoints mean it only re-analyzes the fixed chapters

This requires a minor update to the book-coordinator prompt template in `process-book/SKILL.md` to include quality monitoring instructions.

## Changes to Existing Skills

### `process-book/SKILL.md`

- Replace Step 1 Bash execution with subagent dispatch pattern
- Add verify-repair loop logic to Step 1
- Add Step 2 feedback handling after coordinator returns
- Update pseudocode and architecture diagram
- Add `chapter_problems` field to coordinator prompt template

### `extract/SKILL.md`

- No changes needed (scripts unchanged)
- Extract agent uses existing scripts as-is

### Prompt templates

Embedded in `process-book/SKILL.md` (consistent with existing pattern where coordinator prompt is inline).

## Model Selection Rationale

| Agent | Model | Rationale |
|-------|-------|-----------|
| Extract Agent | Sonnet | Needs to read PDF TOC, make decisions about extraction mode, construct JSON — requires reasoning but not deep analysis |
| Verify Agent | Haiku | Straightforward pattern matching on text heads/tails — cheapest model sufficient |
| Book Coordinator | Opus (unchanged) | Complex multi-step orchestration with academic judgment calls |
| Per-chapter Analysis | Opus (unchanged) | Deep academic analysis requiring nuanced understanding |

This is a new pattern in the codebase — existing agents all use Opus. The extraction/verification tasks are qualitatively different (structural, not analytical) and don't need Opus-level reasoning.

## Cost Impact

- Extract agent (Sonnet): reads ~8 PDF pages for TOC + script execution. Comparable cost to current Bash output, but in a subagent context instead of main process.
- Verify agent (Haiku): ~2N Read calls for N chapters, 200 lines each. For a 30-chapter book: ~60 Read calls, trivial cost.
- Net effect: slightly more tokens total, but **main process context freed significantly** — the main process no longer ingests any PDF/txt content.

## Design Principles

1. **Main process = pure dispatcher**: sees only structured summaries, never file content
2. **Two-layer defense**: extract agent self-repairs fragmentation, verify agent catches what extract missed
3. **Cheap verification**: Haiku model, 200 lines per file, negligible cost
4. **Bounded retries**: max 2 repair rounds, then escalate to user
5. **Always verify on resume**: even if manifest exists, run verify to ensure quality
6. **Step 2 feedback loop**: coordinator can trigger re-extraction for specific chapters
7. **Right model for the job**: Sonnet/Haiku for structural tasks, Opus reserved for analytical tasks

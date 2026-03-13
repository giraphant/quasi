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

> **路径约定**：本技能引用其他技能的脚本时，基于系统提供的 base directory 拼接。例如 `../extract/scripts/X.py` → `python3 {base_directory}/../extract/scripts/X.py`。

# Process Book — 书籍处理（复合技能）

从 EPUB/PDF 到结构化摘要的完整流程。主进程直接调度，轮询与概览委托给监控代理。

## 调用方式

```
/quasi:process-book {book-name}
```

`{book-name}` 为 kebab-case 名称。源文件应在 `sources/{book-name}.epub` 或 `.pdf`。

## ⚠ 架构约束（必读）

**Agent 工具不支持嵌套**：由 Agent 工具派发的子代理**没有 Agent 工具**，只有 Read/Write/Edit/Glob/Grep/Bash 等基础工具。因此：
- ❌ coordinator 模式无效（coordinator 无法再派子代理）
- ❌ 子代理内用 Task 工具无效（Task 只能跑 Bash，无法用 Claude 工具）
- ✅ **主进程用 Agent 工具直接并行派发分析代理**（已有 allow 权限，不弹提示）

## 编排模式：主进程直接调度 + 监控代理

**上下文优化策略**：
- 主进程只做轻量调度（读 manifest、筛选、派发），不读章节内容
- 分析代理自己读模板和章节文本（不在主进程展开）
- **轮询和概览委托给"监控+概览"代理**——在子代理上下文里完成，不污染主进程

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

**主进程禁止做的事**：
- 读取 manifest.json 内容或筛选章节（交给 book-coordinator）
- 循环派发 analyze agents（交给 book-coordinator）
- 读取分析产出 .md 文件（只用 Glob 检查数量）
- 手动生成概览（交给 book-coordinator 内的 overview 子代理）
- 对 manifest 做任何判断逻辑（coordinator 自己决策）
- 读取 PDF/txt 文件内容（全部交给提取代理和验证代理）

---

## Step 1: 提取章节（子代理驱动）

**调度方式**：主进程派发提取代理 + 验证代理（不直接执行脚本）

### Step 1a: 断点检查

`processing/chapters/{book-name}/manifest.json` 存在 → 跳到 Step 1c（验证）。

### Step 1b: 提取代理 (Sonnet, 前台)

提取代理负责：读取 PDF TOC → 决策提取模式 → 运行脚本 → 碎片化自修。

**子代理 prompt 模板**：

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
```

修复模式下 `{repair_section}` 替换为：
```
这是修复模式。上一轮验证发现以下问题：
{problem_list}

请根据问题类型决定：
- 个别章节有问题 → 用 --pages 和 --title 参数重新提取指定章节
- 大面积问题 → 全量重跑（删除输出目录后重新提取）
```

**主进程收到**：EXTRACT_RESULT 摘要（几行文字，无文件内容）

### Step 1c: 验证代理 (Haiku, 前台)

验证代理负责：读取每个 txt 头尾 100 行 → 结构校验 → 报告 pass/fail。

**注意**：即使 manifest 已存在（断点续跑），也必须运行验证。

**子代理 prompt 模板**：

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

**主进程收到**：VERIFY_RESULT 摘要（pass/fail + 问题列表）

### Step 1d: 修复循环（最多 2 轮）

如果验证失败：
1. 派发提取代理（Sonnet），prompt 中附上问题列表（修复模式）
2. 再派发验证代理（Haiku）
3. 最多重复 2 轮。仍失败则报告用户，需人工介入。

### 断点续跑
`processing/chapters/{book-name}/manifest.json` 存在 → 跳过提取（Step 1b），但仍执行验证（Step 1c）。

---

## Step 2: 筛选章节（主进程）

**主进程自己做**（轻量操作，~2 次工具调用）：

1. 读取 `processing/chapters/{book-name}/manifest.json`
2. 根据主题（从 CLAUDE.md §1.3 获取 topic）评估每章相关性：
   - **跳过**：纯索引、致谢、封面、目录、版权页、contributor biographies 等无分析价值的文件
   - **选中**：与 topic 相关的实质章节
3. 用 Glob 检查 `{output_dir}/ch{NN}-*.md` 是否已存在（断点续跑），从待分析列表中移除已完成的
4. 向用户报告选中章节列表和已跳过的章节，**等待确认后继续**

**子代理 prompt 模板**：

```
你是书籍处理协调代理。任务：协调一本学术书籍的章节分析和概览生成。

书籍信息：
- book-name: {book-name}
- book_title: {book_title}
- editors: {editors}（如无编者则填作者）
- publisher: {publisher}
- year: {year}
- book_short_name: {book_short_name}（用于 frontmatter 的简称）
- 章节目录: processing/chapters/{book-name}/
- 分析输出: {output_dir}/（由主进程确定，见下方说明）

步骤 1 — 筛选章节：
  读取 processing/chapters/{book-name}/manifest.json（或用 Glob 列出 *.txt 文件）。
  根据主题"技术、AI、媒介与具身化"评估每章相关性。
  跳过纯索引/致谢/封面等无分析价值的章节。
  记录选中章节及理由。

步骤 2 — 并行分析：
  对每个选中章节，检查 {output_dir}/ch{NN}-{title-slug}.md 是否已存在（断点续跑）。
  对不存在的，启动 1 个后台子代理（Agent tool）：
  - subagent_type: "general-purpose"
  - model: "opus"
  - run_in_background: true
  - prompt: 读取 ../analyze/prompts/text-analysis.md 模板，
    选用 A 类（书籍章节）元数据格式，根据模板中的占位符填入相应值，
    生成分析写入 {output_dir}/ch{NN}-{title-slug}.md。
    值来源：
    - preamble/topic: 从 CLAUDE.md §1.3 获取
    - 书籍元数据 (book_title, editors, publisher, year, book_short_name): 上方书籍信息
    - 章节元数据 (ch_num, chapter_title, author): 从 manifest 或章节文本推断
    - input_instruction: 读取 processing/chapters/{book-name}/{chapter_file}
    - extra_sections: ""

步骤 3 — 等待完成：
  用 Glob 检查 {output_dir}/ch*.md 数量是否等于选中章节数。
  每 30 秒检查一次，直到全部完成。

步骤 4 — 生成概览：
  启动 1 个前台子代理（opus），读取 {output_dir}/ 下所有 ch*.md，
  生成 {output_dir}/00-overview.md。
  概览应包含：全书核心论点、章节间逻辑、关键概念表、与"技术、AI、媒介与具身化"的关联。

步骤 5 — 章节质量监控：
  在分析过程中，如果发现某章节文本有明显质量问题（截断、乱码、空白过多），
  在完成报告中列出问题章节。

完成后报告格式（最后一条消息必须包含）：
- chapters_analyzed: N
- overview: generated | skipped
- chapter_problems: [
    {file: "ch05_xxx.txt", issue: "text appears truncated at page boundary"},
    ...
  ]
  如果无质量问题，chapter_problems 为空列表。
```

**主进程收到**：完成报告（N 章分析 + 概览状态）

### 断点续跑
`{output_dir}/00-overview.md` 存在 → 跳过 Step 2。

---

## Step 3: 并行派发分析代理

**调度方式**：主进程用 Agent 工具直接派发，每个 `run_in_background: true`

**分批策略**：每批最多 5 个后台代理，一次性发出（同一条消息中多个 Agent 调用）。超过 5 个时分批，但**不需要等上一批完成再发下一批**——直接连续发即可，API 会自行排队。

**分析代理 prompt 模板**（主进程为每章填入元数据后发出）：

```
你是学术文本分析代理。

重要规则：禁止在一条 Bash 命令中使用 &&、||、;、管道 |。

步骤：
1. 读取分析模板：{base_directory}/../analyze/prompts/text-analysis.md
2. 选用 A 类（书籍章节）元数据格式，填入以下值：
   - preamble: {preamble}
   - topic: {topic}
   - book_title: {book_title}
   - editors: {editors}
   - publisher: {publisher}
   - year: {year}
   - book_short_name: {book_short_name}
   - ch_num: {ch_num}
   - chapter_title: {chapter_title}
   - author: {author}
   - input_instruction: 读取 processing/chapters/{book-name}/{chapter_file}
   - extra_sections: ""
3. 读取章节文本文件
4. 按模板生成完整分析
5. 写入 {output_dir}/ch{NN}-{title-slug}.md
```

**上下文开销**：每个 Agent dispatch ~5 行 prompt + 完成后 ~1 行通知。N 章 ≈ 6N 行。

---

## Step 4: 监控 + 概览代理

**调度方式**：1 个前台 Agent（opus），阻塞等待

**关键设计**：轮询和概览生成都在这个子代理的上下文里完成，主进程不参与。

**prompt 模板**：

```
你是书籍处理的监控与概览代理。

重要规则：禁止在一条 Bash 命令中使用 &&、||、;、管道 |。

任务分两阶段：

阶段 1 — 等待分析完成：
  - 目标：{output_dir}/ 下应有 {expected_count} 个 ch*.md 文件
  - 用 Glob 检查 "{output_dir}/ch*.md" 的文件数量
  - 如果数量不足，等待 60 秒后再次检查（用 Bash 的 sleep 60）
  - 重复直到数量达标，或超过 30 分钟后报告未完成的章节

阶段 2 — 生成概览：
  - 读取 {output_dir}/ 下所有 ch*.md 文件
  - 生成 {output_dir}/00-overview.md
  - 概览包含：
    - 全书信息（标题、编者、出版社、年份）
    - 各章核心论点概要（按 Part 分组）
    - 关键概念索引表
    - 与"{topic}"的关联分析
    - 高价值章节推荐（标注星级）

完成后报告：已完成 N 章确认 + 概览生成状态。
```

**上下文开销（主进程侧）**：1 次 dispatch + 1 次返回结果 ≈ 10 行。

---

## Step 5: 更新知识库（可选）

由用户决定是否执行。参见 `quasi:synthesize` 的「知识库更新」模式。

---

## 主进程完整执行流程

```python
# 伪代码 — 主进程只做调度

# 0. 确定参数
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

# 4. MONITOR + OVERVIEW [Agent × 1, 前台]
Agent(
    description="Monitor and generate overview",
    model="opus",
    prompt=monitor_overview_prompt(
        output_dir=output_dir,
        expected_count=len(selected) + len(existing_ch_files),
        topic=topic,
        book_info=book_info
    )
)

# 5. KB UPDATE [可选]
if user_requests:
    Agent(kb_update_prompt, model="opus")

# 6. 报告完成
print(f"Done: {total} chapters analyzed, overview generated")
```

## 断点续跑汇总

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 1b (提取) | `processing/chapters/{book-name}/manifest.json` | 存在则跳过提取 |
| Step 1c (验证) | 不跳过 | 即使 manifest 已存在也必须验证 |
| Step 1d (修复) | 验证通过 | 通过则跳过修复 |
| Step 2 (整体) | `{output_dir}/00-overview.md` | 存在则跳过整个 coordinator |
| Step 2 (逐章) | `{output_dir}/ch{NN}-*.md` | 存在则跳过该章分析（coordinator 内部检查） |
| Step 2 反馈 | coordinator 报告问题 | 仅在 coordinator 报告质量问题时执行 |
| Step 3 | — | 用户手动决定 |

## 目录结构

```
sources/{book-name}.epub|.pdf            <- 源文件
processing/chapters/{book-name}/        <- 提取的章节文本
├── manifest.json
└── *.txt
vault/handbooks/{book-name}/            <- Handbook/编著
├── 00-overview.md
└── ch{NN}-{title}.md
vault/monographs/{book-name}/           <- 单一作者专著
├── 00-overview.md
└── ch{NN}-{title}.md
```

**output_dir 选择规则**：
- Handbook、Oxford/Cambridge/Routledge 手册、编著论文集 → `vault/handbooks/{book-name}/`
- 单一作者或少数共同作者的专著 → `vault/monographs/{book-name}/`

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

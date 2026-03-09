---
name: quasi:process-book
type: workflow
description: >
  Composite skill: processes a book from EPUB/PDF to structured summaries.
  Subagent-driven: main process only dispatches ~3 tool calls (extract script,
  book-coordinator, optional KB update). Use when the user says
  "处理这本书", "跑一下这本handbook", "总结这本".
argument-hint: "[book-name]"
---

# Process Book — 书籍处理（复合技能）

从 EPUB/PDF 到结构化摘要的完整流程。子代理驱动架构。

## 调用方式

```
/quasi:process-book {book-name}
```

`{book-name}` 为 kebab-case 名称。源文件应在 `sources/{book-name}.epub` 或 `.pdf`。

## 编排模式：子代理驱动

**核心原则**：主进程只做 dispatcher，不做循环、不读 manifest 细节、不筛选章节、不派发分析代理。所有重活交给 book-coordinator 子代理，coordinator 有独立的上下文预算。

```
主进程 (dispatcher, ~3 次工具调用)
│
├─ Step 1: extract (Bash)            [前台, 等待完成]
├─ Step 2: book-coordinator          [前台/后台, 等待完成]
└─ Step 3: kb-update-agent (可选)    [前台, 等待完成]
```

**主进程禁止做的事**：
- 读取 manifest.json 内容或筛选章节（交给 book-coordinator）
- 循环派发 analyze agents（交给 book-coordinator）
- 读取分析产出 .md 文件（只用 Glob 检查数量）
- 手动生成概览（交给 book-coordinator 内的 overview 子代理）
- 对 manifest 做任何判断逻辑（coordinator 自己决策）

---

## Step 1: 提取章节（extract）

**调度方式**：主进程直接执行 Bash 命令（1 次工具调用）

```bash
# EPUB
python3 quasi/skills/extract/scripts/process_epub.py \
    sources/{book-name}.epub processing/chapters/{book-name}/

# PDF
python3 quasi/skills/extract/scripts/split_chapters.py \
    sources/{book-name}.pdf --output-dir processing/chapters/{book-name}/
```

**主进程收到**：脚本输出（确认章节数量）

**⚠ PDF 碎片化问题**：`split_chapters.py` 对脚注密集的人文类 PDF（如许煜 5 本书产出 747 片段）会过度切分。如果章节数量异常多（>100），替代方案：
- 跳过 Step 1 提取，直接在 Step 2 中让 book-coordinator 整本 PDF 读取生成 00-overview.md
- 或手动检查切分结果后删除碎片，保留完整章节

### 断点续跑
`processing/chapters/{book-name}/manifest.json` 存在 → 跳过 Step 1。

---

## Step 2: 书籍协调（book-coordinator）

**调度方式**：1 个前台子代理（opus）

book-coordinator 独立完成全部工作：读取 manifest → 筛选章节 → 派发 N 个分析代理 → Glob 轮询 → 派发概览代理。

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
  对不存在的，启动 1 个后台子代理（Task tool）：
  - subagent_type: "general-purpose"
  - model: "opus"
  - run_in_background: true
  - prompt: 读取 quasi/skills/analyze/prompts/text-analysis.md 模板，
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

完成后报告：N 章已分析、概览已生成。
```

**主进程收到**：完成报告（N 章分析 + 概览状态）

### 断点续跑
`{output_dir}/00-overview.md` 存在 → 跳过 Step 2。

---

## Step 3: 更新知识库（可选）

**调度方式**：1 个前台子代理（opus），由用户决定是否执行

参见 `quasi:synthesize` 的「知识库更新」模式。

---

## 主进程完整执行流程

```python
# 伪代码 — 主进程只做调度

# 0. 读参数
book_name = parse_args()  # kebab-case
source_file = find("sources/{book_name}.epub") or find("sources/{book_name}.pdf")
chapters_dir = f"processing/chapters/{book_name}/"
# output_dir 由书籍类型决定：
#   - Handbook/编著 → vault/handbooks/{book_name}/
#   - 单一作者专著 → vault/monographs/{book_name}/
output_dir = determine_output_dir(book_name)  # 主进程根据书籍类型决定

# 1. EXTRACT [前台, Bash]
if not exists(f"{chapters_dir}/manifest.json"):
    Bash(f"python3 quasi/skills/extract/scripts/process_epub.py {source_file} {chapters_dir}")
    # 或 split_chapters.py for PDF

# 2. BOOK-COORDINATOR [前台]
if not exists(f"{output_dir}/00-overview.md"):
    Task(book_coordinator_prompt, foreground=True, model="opus")
    # coordinator 内部: 筛选章节 → dispatch N analyze agents → Glob poll → overview agent

# 3. KB UPDATE [前台, 可选]
if user_requests_kb_update:
    Task(kb_update_prompt, foreground=True, model="opus")

# 4. 报告完成
summary_count = len(Glob(f"{output_dir}/ch*.md"))
print(f"Done: {summary_count} chapters analyzed, overview generated")
```

## 断点续跑汇总

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 1 | `processing/chapters/{book-name}/manifest.json` | 存在则跳过提取 |
| Step 2 (整体) | `{output_dir}/00-overview.md` | 存在则跳过整个 coordinator |
| Step 2 (逐章) | `{output_dir}/ch{NN}-*.md` | 存在则跳过该章分析（coordinator 内部检查） |
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

1. **主进程只做 dispatcher**：~3 次工具调用（extract + coordinator + 可选 KB），不做循环
2. **book-coordinator 有独立上下文**：章节筛选、分析派发、轮询、概览生成全在 coordinator 内完成
3. **每章 1 个分析代理**，`model: "opus"`，由 coordinator 并行启动
4. **完成检查用 Glob**：不用 TaskOutput（避免导入子代理 transcript）
5. **概览由 coordinator 内的子代理生成**：不回传到主进程
6. **从 CLAUDE.md §1.3 获取 preamble/topic 参数**

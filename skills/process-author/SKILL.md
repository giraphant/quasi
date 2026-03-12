---
name: quasi:process-author
type: workflow
description: >
  Composite skill: discovers a scholar's representative works (up to 5 books +
  10 papers), acquires, analyzes, and synthesizes into an author-level profile.
  Subagent-driven: main process only dispatches 5 coordinator agents.
  Use when the user says "处理作者", "process author", "跑一下这个学者".
argument-hint: "{author-name}"
---

> **路径约定**：本技能引用其他技能的脚本时，基于系统提供的 base directory 拼接。例如 `../search/scripts/X.py` → `python3 {base_directory}/../search/scripts/X.py`。

# Process Author — 作者处理（复合技能）

系统性处理一位核心学者的代表作，生成作者级综合文档。

## 调用方式

```
/quasi:process-author {author-name}
```

`{author-name}` 为 kebab-case（如 `donna-haraway`）。

## ⚠ 架构约束

**Agent 工具不支持嵌套**：由 Agent 工具派发的子代理没有 Agent 工具。因此：
- Phase 3 的 book-coordinator **自己顺序完成章节分析**（不尝试派发子代理）
- Phase 4 的 paper-coordinator **自己顺序完成论文分析**（不尝试派发子代理）

## 编排模式：子代理驱动

**核心原则**：主进程只做 dispatcher，不做循环、不读分析产出、不管 manifest 细节。所有重活交给 coordinator 子代理，每个 coordinator 有独立的上下文预算。

```
主进程 (dispatcher, ≤10 次工具调用)
│
├─ Phase 1: discover-agent        [前台, 等待完成]
├─ Phase 2: download-coordinator  [前台, 等待完成]
├─ Phase 3: book-coordinator ×N   [后台, 并行]
├─ Phase 4: paper-coordinator     [后台, 与 Phase 3 并行]
├─ (轮询等待 Phase 3+4 完成)
└─ Phase 5: profile-agent         [前台, 等待完成]
```

**主进程禁止做的事**：
- 循环调用 download.py（交给 download-coordinator）
- 循环派发 analyze agents（交给 book/paper-coordinator）
- 读取分析产出 .md 文件（只用 Glob 检查数量）
- 手动更新 manifest 状态（coordinator 自己更新）

## Phase 1: DISCOVER（discover-agent）

**调度方式**：1 个前台子代理（opus）

**子代理 prompt 模板**：

```
你是学术文献发现代理。任务：为作者 {Full Name} 发现最重要的代表作。

步骤：
1. 搜索书籍候选池：
   python3 ../search/scripts/search.py books --author "{Full Name}" --limit 20
2. 搜索论文候选池：
   python3 ../search/scripts/search.py papers --author "{Full Name}" --limit 30
3. 按「引用量 × 与"{topic}"相关性」筛选：
   - 5 本最重要的书（附选择理由）
   - 10 篇最重要的论文（附选择理由）
4. 写入 vault/authors/{author-name}/manifest.json

manifest 结构见下方。status 统一为 "discovered"。

{manifest_schema}
```

**manifest 结构**：
```json
{
  "author": "Full Name",
  "slug": "author-name",
  "discovered": "YYYY-MM-DD",
  "books": [
    {"title": "...", "year": 2016, "slug": "author-title-year",
     "isbn": "...", "md5": null, "status": "discovered", "reason": "..."}
  ],
  "papers": [
    {"title": "...", "doi": "10.xxx/yyy", "year": 2023,
     "citations": 1234, "oa_url": null, "status": "discovered", "reason": "..."}
  ]
}
```

**主进程收到**：manifest.json 路径（确认成功）

### 断点续跑
`vault/authors/{author-name}/manifest.json` 存在 → 跳过 Phase 1。

---

## Phase 2: ACQUIRE（download-coordinator）

**调度方式**：1 个前台子代理（opus）

**子代理 prompt 模板**：

```
你是文献下载协调代理。任务：下载 manifest 中所有 "discovered" 条目。

读取 vault/authors/{author-name}/manifest.json。

书籍下载流程（对每本 status="discovered" 的书）：
1. python3 ../search/scripts/search.py books --source aa "{title}" --author "{author}" --limit 5
2. 从结果中找到匹配的 MD5
3. python3 ../download/scripts/download.py --md5 {md5} --filename {book-slug} -o sources/
4. 成功 → 更新 manifest: status="acquired", md5="{md5}"
5. 失败 → status="failed"

论文下载流程（对每篇 status="discovered" 的论文）：
1. python3 ../download/scripts/download.py --doi "{doi}" --output-dir vault/authors/{author-name}/papers/ --filename {doi-slug}
2. 成功 → status="acquired", file="vault/authors/{author-name}/papers/{slug}.pdf"
3. 失败 → status="failed"

每次下载后立即更新 manifest.json（保存进度）。
下载间隔至少 5 秒。
完成后报告：N 本书获取、M 篇论文获取、K 个失败。
```

**主进程收到**：获取统计摘要

### 断点续跑
manifest 中 `status` 为 `acquired` 或 `failed` 的条目 → 跳过。coordinator 自动处理。

---

## Phase 3: PROCESS BOOKS（book-coordinator ×N）

**调度方式**：每本 `acquired` 书启动 1 个后台子代理（opus），最多 5 个并行

**子代理 prompt 模板**（每本书一份）：

```
你是书籍处理协调代理。任务：处理一本学术专著的完整流程。

书籍信息：
- 标题: {book_title}
- slug: {book-slug}
- 源文件: sources/{book-slug}.{epub|pdf}
- 章节输出: processing/chapters/{book-slug}/
- 分析输出: vault/monographs/{book-slug}/

步骤 1 — 提取章节：
  # EPUB
  python3 ../extract/scripts/process_epub.py \
      sources/{book-slug}.epub processing/chapters/{book-slug}/
  # 或 PDF
  python3 ../extract/scripts/split_chapters.py \
      sources/{book-slug}.pdf --output-dir processing/chapters/{book-slug}/

步骤 2 — 筛选章节：
  读取 processing/chapters/{book-slug}/ 下的 manifest.json 或文件列表。
  根据主题"{topic}"评估每章相关性，跳过纯方法论/索引/前言等低相关章节。
  记录选中章节及理由。

步骤 3 — 逐章分析（自己顺序完成，不派发子代理）：
  对每个选中章节，检查 vault/monographs/{book-slug}/ch{NN}-*.md 是否已存在（跳过已完成）。
  对每个未完成章节：
  - 读取 ../analyze/prompts/text-analysis.md 模板
  - 选用 A 类（书籍章节）元数据格式，根据模板中的占位符填入相应值
  - 读取章节文本：processing/chapters/{book-slug}/{chapter_file}
  - 生成分析写入 vault/monographs/{book-slug}/ch{NN}-{title-slug}.md
  - 值来源：
    - preamble/topic: 从 CLAUDE.md §1.3 获取
    - 书籍元数据 (book_title 等): 上方书籍信息
    - 章节元数据 (ch_num, chapter_title, author): 从章节文本推断
    - input_instruction: 读取 processing/chapters/{book-slug}/{chapter_file}
    - extra_sections: ""

步骤 4 — 生成概览：
  读取所有 ch*.md，生成 vault/monographs/{book-slug}/00-overview.md。
  概览应包含：全书核心论点、章节间逻辑、关键概念表、与"{topic}"的关联。
```

**主进程收到**：无（后台运行，通过 Glob 检查 00-overview.md 是否存在来确认完成）

### 断点续跑
`vault/monographs/{book-slug}/00-overview.md` 存在 → 跳过该书。

---

## Phase 4: PROCESS PAPERS（paper-coordinator）

**调度方式**：1 个后台子代理（opus），与 Phase 3 并行启动

**子代理 prompt 模板**：

```
你是论文处理协调代理。任务：分析 manifest 中所有已获取的论文。

读取 vault/authors/{author-name}/manifest.json，找到 papers 中 status="acquired" 的条目。

逐篇分析（自己顺序完成，不派发子代理）：
对每篇 status="acquired" 的论文，检查 vault/authors/{author-name}/papers/{slug}.md 是否已存在（跳过已完成）。
对每篇未完成的论文：
- 读取 ../analyze/prompts/text-analysis.md 模板
- 选用 B 类（论文）元数据格式，根据模板中的占位符填入相应值
- 读取 PDF：{pdf_path}
- 生成分析写入 vault/authors/{author-name}/papers/{slug}.md
- 值来源：
  - preamble/topic: 从 CLAUDE.md §1.3 获取
  - 论文元数据 (title, author, year, doi, source): 从 manifest 获取
  - input_instruction: 读取 {pdf_path}
  - extra_sections: ""

对 status="abstract_only" 的论文：
  在 input_instruction 中传入摘要文本（从 manifest 的 abstract 字段获取），
  标注"基于摘要的分析，非全文"。
```

**主进程收到**：无（后台运行，通过 Glob 检查 .md 数量确认完成）

### 断点续跑
`vault/authors/{author-name}/papers/{doi-slug}.md` 存在 → 跳过该论文。coordinator 自动处理。

---

## Phase 5: AUTHOR SYNTHESIS（profile-agent）

**调度方式**：1 个前台子代理（opus），Phase 3+4 全部完成后启动

**子代理 prompt 模板**：

```
你是作者综合代理。任务：为 {Full Name} 生成综合学术档案。

读取以下所有文件：
- vault/monographs/{book-slug-1}/00-overview.md
- vault/monographs/{book-slug-2}/00-overview.md
  ... (所有已处理书籍的概览)
- vault/authors/{author-name}/papers/*.md (所有论文分析)

生成 vault/authors/{author-name}/profile.md，格式如下：

---
type: author-profile
rating:
themes: []
author: "{Full Name}"
title: "{Full Name}"
year:
source:
---
# {Full Name}

## 学术轨迹
（从早期到最近的理论演化，按时间线梳理）

## 核心概念谱系
| 概念 | 首次提出 | 演化 | 来源作品 |
|------|---------|------|---------|

## 与本项目主题的关联
（"技术、AI、媒介与具身化"各子题的具体关联）

## 代表作概览
| 书/论文 | 年份 | 核心论点 | 链接 |
|---------|------|---------|------|

## 理论网络
（与哪些学者对话、继承、批判）

## 可引用观点
（综述写作时可直接使用的关键论述，含页码/章节出处）
```

**主进程收到**：profile.md 路径（确认成功）

---

## 主进程完整执行流程

```python
# 伪代码 — 主进程只做调度

# 0. 读参数
author_name, full_name = parse_args()
manifest_path = f"vault/authors/{author_name}/manifest.json"
topic = "技术、AI、媒介与具身化"
preamble = "这是人文/理论类文本..."

# 1. DISCOVER [前台]
if not exists(manifest_path):
    Task(discover_agent_prompt, foreground=True)  # → manifest.json

# 2. ACQUIRE [前台]
manifest = read(manifest_path)
if any(status == "discovered" in manifest):
    Task(download_coordinator_prompt, foreground=True)  # → 更新 manifest

# 3+4. PROCESS [后台, 并行]
manifest = read(manifest_path)  # 刷新
book_agents = []
for book in manifest.books where status == "acquired":
    if not exists(f"vault/monographs/{book.slug}/00-overview.md"):
        agent = Task(book_coordinator_prompt(book), background=True)
        book_agents.append(agent)

paper_agent = None
if any papers need processing:
    paper_agent = Task(paper_coordinator_prompt, background=True)

# 等待完成 (Glob 轮询, 不用 TaskOutput)
expected_overviews = len(book_agents)
expected_papers = count(acquired papers without .md)
while not all_done:
    overview_count = len(Glob("vault/monographs/*/00-overview.md"))  # 过滤相关的
    paper_md_count = len(Glob("vault/authors/{name}/papers/*.md"))
    sleep(60)

# 5. SYNTHESIS [前台]
Task(profile_agent_prompt, foreground=True)  # → profile.md

# 6. 报告完成
print("Done: N books, M papers, profile.md")
```

## 断点续跑汇总

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 1 | `vault/authors/{name}/manifest.json` | 存在则跳过 |
| Phase 2 | manifest 条目 `status` | `acquired`/`failed` 则跳过 |
| Phase 3 | `vault/monographs/{slug}/00-overview.md` | 存在则跳过该书 |
| Phase 4 | `vault/authors/{name}/papers/{doi}.md` | 存在则跳过该论文 |
| Phase 5 | `vault/authors/{name}/profile.md` | 存在则跳过（`--force` 重生成） |

## 目录结构

```
sources/{book-slug}.epub|.pdf          ← 源文件
processing/chapters/{book-slug}/       ← 提取的章节文本
vault/monographs/{book-slug}/          ← 专著章节分析
├── 00-overview.md
└── ch{NN}-{title}.md
vault/authors/{author-name}/           ← 作者级
├── manifest.json
├── profile.md                         ← 核心产出
└── papers/
    ├── {slug}.pdf
    └── {slug}.md
```

## 核心原则

1. **主进程只做 dispatcher**：≤10 次工具调用，不做循环
2. **每个 coordinator 有独立上下文**：互不污染
3. **每章/每篇 1 个分析代理**，`model: "opus"`
4. **book-coordinator 并行**：5 本书同时处理
5. **完成检查用 Glob**：不用 TaskOutput（避免导入子代理 transcript）
6. **manifest 是唯一状态源**：coordinator 直接读写
7. **从 CLAUDE.md §1.3 获取 preamble/topic 参数**

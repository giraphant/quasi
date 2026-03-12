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
- Phase 1/2 的 coordinator **自己完成所有工作**（不尝试派发子代理）
- Phase 3/4 的分析**由主进程直接用 Agent 工具并行派发**（不经 coordinator）

## 编排模式：子代理 + 主进程直接调度混合

```
主进程 (dispatcher)
│
├─ Phase 1: discover-agent              [前台] - 搜索+筛选+生成manifest（自己完成）
├─ Phase 2: download-coordinator        [前台] - 下载书籍+论文（自己完成）
├─ Phase 3: PROCESS BOOKS（主进程直接调度）
│   ├─ 对每本书: Bash extract
│   ├─ 读 manifest + 筛选章节
│   ├─ 派发 N 个章节分析代理             [后台, 分批]
│   └─ 派发"监控+概览"代理              [前台, 等待完成]
├─ Phase 4: PROCESS PAPERS（主进程直接调度）
│   ├─ 从 manifest 提取待分析论文列表
│   ├─ 派发 M 个论文分析代理             [后台, 分批]
│   └─ 派发"监控"代理                   [前台, 等待完成]
└─ Phase 5: profile-agent              [前台, 等待完成]
```

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

## Phase 3: PROCESS BOOKS（主进程直接调度）

**调度方式**：主进程对每本 `acquired` 书执行 extract → 筛选 → 派发 N 个分析代理（后台）+ 监控+概览代理（前台）

**主进程步骤**：

1. 读取 manifest，找到所有 status="acquired" 的书
2. 对每本书，跳过已有 `vault/monographs/{book-slug}/00-overview.md` 的
3. 对每本未完成的书：
   a. **提取章节**（Bash）：
      ```
      python3 ../extract/scripts/process_epub.py sources/{book-slug}.epub processing/chapters/{book-slug}/
      # 或 PDF:
      python3 ../extract/scripts/split_chapters.py sources/{book-slug}.pdf --output-dir processing/chapters/{book-slug}/
      ```
   b. **筛选章节**（主进程）：读取 manifest.json，根据"{topic}"评估相关性，排除已有分析
   c. **派发章节分析代理**（后台，分批 ≤5）：
      每个代理 prompt：
      - 读取 ../analyze/prompts/text-analysis.md 模板
      - 选用 A 类（书籍章节）元数据格式
      - 值来源：preamble/topic 从 CLAUDE.md §1.3，书籍元数据从 manifest
      - input_instruction: 读取 processing/chapters/{book-slug}/{chapter_file}
      - 写入 vault/monographs/{book-slug}/ch{NN}-{title-slug}.md
   d. **派发"监控+概览"代理**（前台，阻塞等待）：
      - Glob 轮询 vault/monographs/{book-slug}/ch*.md 数量
      - 全部完成后读取所有 ch*.md，生成 00-overview.md

### 断点续跑
`vault/monographs/{book-slug}/00-overview.md` 存在 → 跳过该书。

---

## Phase 4: PROCESS PAPERS（主进程直接调度）

**调度方式**：主进程从 manifest 提取待分析论文 → 派发 M 个分析代理（后台）+ 监控代理（前台）

**主进程步骤**：

1. 读取 manifest，找到 papers 中 status="acquired" 的条目
2. 用 Glob 检查 vault/authors/{author-name}/papers/{slug}.md，排除已分析的
3. 对每篇需分析的论文，派发 1 个后台分析代理（分批 ≤5）：
   - 读取 ../analyze/prompts/text-analysis.md 模板
   - 选用 B 类（论文）元数据格式
   - 值来源：preamble/topic 从 CLAUDE.md §1.3，论文元数据从 manifest
   - input_instruction: 读取 {pdf_path}
   - 写入 vault/authors/{author-name}/papers/{slug}.md
4. 对 status="abstract_only" 的论文：input_instruction 传入摘要文本，标注"基于摘要的分析"
5. 派发 1 个前台"监控"代理：Glob 轮询 papers/*.md 数量，全部完成后报告

### 断点续跑
`vault/authors/{author-name}/papers/{doi-slug}.md` 存在 → 主进程自动排除。

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
    Agent(discover_agent_prompt, foreground=True, model="opus")  # → manifest.json

# 2. ACQUIRE [前台]
manifest = read(manifest_path)
if any(status == "discovered" in manifest):
    Agent(download_coordinator_prompt, foreground=True, model="opus")  # → 更新 manifest

# 3. PROCESS BOOKS [主进程直接调度]
manifest = read(manifest_path)  # 刷新
for book in manifest.books where status == "acquired":
    if exists(f"vault/monographs/{book.slug}/00-overview.md"):
        continue  # 跳过已完成
    Bash(f"python3 ../extract/scripts/... {book.source} processing/chapters/{book.slug}/")
    chapters = filter_relevant(Read(f"processing/chapters/{book.slug}/manifest.json"))
    existing = Glob(f"vault/monographs/{book.slug}/ch*.md")
    to_analyze = chapters - existing
    for batch in chunks(to_analyze, 5):
        for ch in batch:
            Agent(analyze_chapter_prompt(ch), background=True, model="opus")
    Agent(monitor_overview_prompt(book), foreground=True, model="opus")  # 阻塞等待

# 4. PROCESS PAPERS [主进程直接调度]
manifest = read(manifest_path)
papers = [p for p in manifest.papers if p.status == "acquired"]
existing = Glob(f"vault/authors/{author_name}/papers/*.md")
to_analyze = papers - existing
for batch in chunks(to_analyze, 5):
    for p in batch:
        Agent(analyze_paper_prompt(p), background=True, model="opus")
Agent(monitor_prompt(expected=len(to_analyze)+len(existing)), foreground=True, model="opus")

# 5. SYNTHESIS [前台]
Agent(profile_agent_prompt, foreground=True, model="opus")  # → profile.md

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

1. **Phase 1/2 coordinator 自己完成所有工作**：不尝试派发子代理（Agent 嵌套不可用）
2. **Phase 3/4 由主进程直接派发分析代理**：每章/每篇 1 个 Agent，`model: "opus"`，`run_in_background: true`
3. **监控代理处理轮询和概览**：主进程不做循环，委托前台监控代理 Glob 检查
4. **分批派发**：每批 ≤5 个分析代理，连续发出不等待
5. **完成检查用 Glob**：不用 TaskOutput（避免导入子代理 transcript）
6. **manifest 是唯一状态源**：coordinator 直接读写
7. **从 CLAUDE.md §1.3 获取 preamble/topic 参数**

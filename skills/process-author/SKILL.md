---
name: quasi:process-author
type: workflow
description: >
  Composite skill: discovers a scholar's representative works (up to 5 books +
  10 papers), acquires, analyzes, and synthesizes into an author-level profile.
  Use when the user says "处理作者", "process author", "跑一下这个学者".
argument-hint: "{author-name}"
---

# Process Author — 作者处理

系统性处理一位核心学者的代表作 → 作者级综合文档。扁平 agent 调度。

## 调用方式

```
/quasi:process-author {author-name}
```

`{author-name}` 为 kebab-case（如 `donna-haraway`）。

## ⚠ 硬约束

- **禁止用 TaskOutput 检查后台 agent**：会报 "No task found"，导致卡住
- **必须用 Glob 轮询输出文件**来判断完成

## 编排架构

```
主进程 (dispatcher)
├─ Phase 1: discover-agent (opus, 前台) → manifest
├─ Phase 2: download-agent (sonnet, 前台) → 下载
├─ Phase 3: 书籍处理
│   ├─ 逐本: extract-agent (sonnet, 前台)
│   ├─ 主进程: 读 manifest → 筛选章节
│   ├─ analyze-agent ×N (opus, 后台, 跨书并行)
│   ├─ Glob 轮询
│   └─ 逐本: overview-agent (opus, 前台)
├─ Phase 4: analyze-agent ×M (opus, 后台) → 论文
└─ Phase 5: profile-agent (opus, 前台) → profile.md
```

## 执行流程

```python
author_name, full_name = parse_args()
manifest_path = f"vault/authors/{author_name}/manifest.json"

# 1. DISCOVER
if not exists(manifest_path):
    Agent("quasi:discover-agent", foreground=True,
          prompt=f"author_name: {author_name}, full_name: {full_name}, topic: ...")

# 2. ACQUIRE
manifest = read_json(manifest_path)
if any(status == "discovered"):
    Agent("quasi:download-agent", foreground=True,
          prompt=f"manifest_path: {manifest_path}, mode: both")

# 3. PROCESS BOOKS
manifest = read_json(manifest_path)

# 3a. 逐本提取（extract-agent 自含验证+修复）
for book in manifest.books where status == "acquired":
    chapters_dir = f"processing/chapters/{book.slug}/"
    if not exists(f"{chapters_dir}/manifest.json"):
        Agent("quasi:extract-agent", foreground=True,
              prompt=f"source_file: sources/{book.slug}.*, chapters_dir: {chapters_dir}")

# 3b. 筛选 + 跨书并行分析
all_chapters = []
for book in acquired_books:
    if exists(f"vault/monographs/{book.slug}/00-overview.md"):
        continue
    book_manifest = Read(f"processing/chapters/{book.slug}/manifest.json")
    all_chapters.extend(filter_by_topic(book_manifest))

for ch in all_chapters:
    if not exists(ch.output_path):
        Agent("quasi:analyze-agent", background=True,
              prompt=f"type: A, book_title: ..., ch_num: ..., "
                     f"input: ..., output: ..., topic: ...")

while not all_done:
    sleep(30)

# 3c. 逐本概览
for book in acquired_books:
    if not exists(f"vault/monographs/{book.slug}/00-overview.md"):
        Agent("quasi:overview-agent", foreground=True,
              prompt=f"output_dir: vault/monographs/{book.slug}/, book_title: ..., topic: ...")

# 4. PROCESS PAPERS
for paper in manifest.papers where status == "acquired":
    if not exists(paper_analysis_path):
        Agent("quasi:analyze-agent", background=True,
              prompt=f"type: B, title: ..., doi: ..., input: ..., output: ..., topic: ...")

while not all_papers_done:
    sleep(30)

# 5. SYNTHESIS
if not exists(f"vault/authors/{author_name}/profile.md"):
    Agent("quasi:profile-agent", foreground=True,
          prompt=f"author_name: {author_name}, full_name: {full_name}, topic: ..., "
                 f"book_overview_paths: [...], papers_dir: vault/authors/{author_name}/papers/")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 1 | `manifest.json` | 存在则跳过 |
| Phase 2 | manifest `status` | acquired/failed 跳过 |
| Phase 3a | `{chapters_dir}/manifest.json` | 存在则跳过提取 |
| Phase 3b | `ch{NN}-*.md` | 存在则跳过该章 |
| Phase 3c | `00-overview.md` | 存在则跳过该书 |
| Phase 4 | `{doi}.md` | 存在则跳过 |
| Phase 5 | `profile.md` | 存在则跳过 |

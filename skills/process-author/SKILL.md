---
name: quasi:process-author
description: >
  Use when the user says "处理作者", "process author", "跑一下这个学者",
  or wants to systematically process a scholar's representative works into a profile.
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
- **每个文本独立 dispatch 一个 analyze-agent**：禁止把多章/多篇论文合并到一个 agent 调用中。一个文本 = 一个 Agent() 调用。
- **Dispatcher context 卫生**：
  - Glob 轮询只关注完成数 vs 总数，不要逐一列举文件名
  - 后台 agent 完成通知是冗余信息，收到后不需要额外处理
  - 每个阶段完成后不要回顾前序输出，关键状态已在磁盘上

## 编排架构

```
主进程 (dispatcher)
├─ Phase 1: discover-agent (opus, 前台) → manifest
├─ Phase 2: download-agent (sonnet, 前台) → 下载
├─ Phase 3: 书籍处理
│   ├─ 逐本: extract-agent (sonnet, 前台)
│   ├─ 主进程: 读 manifest → 全部章节
│   ├─ analyze-agent ×N (opus, 后台, 跨书并行)
│   ├─ Glob 轮询
│   └─ 逐本: overview-agent (opus, 前台)
├─ Phase 4: analyze-agent ×M (opus, 后台) → 论文
└─ Phase 5: profile-agent (opus, 前台) → profile.md
```

## 执行流程

```python
author_name, full_name = parse_args()
manifest_path = f"processing/authors/{author_name}/manifest.json"

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

# 3b. 跨书并行分析（每本书全部章节，不筛选）
all_chapters = []
for book in acquired_books:
    if exists(f"vault/books/{book.slug}/00-overview.md"):
        continue
    book_manifest = Read(f"processing/chapters/{book.slug}/manifest.json")
    all_chapters.extend(book_manifest.chapters)

for ch in all_chapters:
    # slot: "01".."99" 真章 / "00a" 前言 / "99a" 后记 / "01b" 章间插曲
    # chapter_label: 由 slot + title 推导的人类可读标签（"第3章" / "前言" / "后记" / "第2章（附）"）
    if not exists(ch.output_path):
        Agent("quasi:analyze-agent", background=True,
              prompt=f"type: A, book_title: ..., slot: {ch.slot}, chapter_label: ..., "
                     f"input: ..., output: ..., topic: ...")

while not all_done:
    sleep(30)

# 3c. 逐本概览
for book in acquired_books:
    if not exists(f"vault/books/{book.slug}/00-overview.md"):
        Agent("quasi:overview-agent", foreground=True,
              prompt=f"output_dir: vault/books/{book.slug}/, book_title: ..., topic: ...")

# 4. PROCESS PAPERS
# paper.slug 必须形如 {author-surname}-{title}-{year}（全局唯一）
# 所有论文产出均落到扁平 vault/papers/，与全库共享 slug 命名空间
for paper in manifest.papers where status == "acquired":
    output_path = f"vault/papers/{paper.slug}.md"
    if not exists(output_path):
        Agent("quasi:analyze-agent", background=True,
              prompt=f"type: B, title: ..., doi: ..., input: ..., "
                     f"output: {output_path}, topic: ...")

while not all_papers_done:
    sleep(30)

# 5. SYNTHESIS
profile_path = f"vault/authors/{author_name}.md"
if not exists(profile_path):
    paper_paths = [f"vault/papers/{p.slug}.md" for p in manifest.papers if status == "acquired"]
    book_overview_paths = [f"vault/books/{b.slug}/00-overview.md" for b in acquired_books]
    Agent("quasi:profile-agent", foreground=True,
          prompt=f"author_name: {author_name}, full_name: {full_name}, topic: ..., "
                 f"output_path: {profile_path}, "
                 f"book_overview_paths: {book_overview_paths}, paper_paths: {paper_paths}")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 1 | `manifest.json` | 存在则跳过 |
| Phase 2 | manifest `status` | acquired/failed 跳过 |
| Phase 3a | `{chapters_dir}/manifest.json` | 存在则跳过提取 |
| Phase 3b | `ch{NN}-*.md` | 存在则跳过该章 |
| Phase 3c | `00-overview.md` | 存在则跳过该书 |
| Phase 4 | `vault/papers/{paper.slug}.md` | 存在则跳过 |
| Phase 5 | `vault/authors/{author-name}.md` | 存在则跳过 |

## 目录结构

```
processing/authors/{author-name}/
└── manifest.json                    ← 采集状态机 + curation reason
vault/authors/{author-name}.md       ← 单文件 profile（扁平）
vault/papers/{paper-slug}.md         ← 该作者所有论文分析（与全库扁平共享）
vault/books/{book-slug}/             ← 该作者所有书的逐章分析
├── 00-overview.md
└── ch{NN}-{title}.md
processing/chapters/{book-slug}/
├── manifest.json
└── *.txt
sources/{book-slug}.*
```

paper.slug 与 book.slug 均为 `{author-surname}-{title}-{year}`，全库唯一。

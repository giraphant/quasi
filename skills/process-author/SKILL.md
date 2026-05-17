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
- **每个文本独立 dispatch 一个 analyse-agent**：禁止把多章/多篇论文合并到一个 agent 调用中。一个文本 = 一个 Agent() 调用。
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
│   ├─ analyse-agent ×N (opus, 后台, 跨书并行)
│   ├─ Glob 轮询
│   └─ 逐本: synthesis-agent(mode=book) (opus, 前台)
├─ Phase 4: analyse-agent ×M (opus, 后台) → 论文
├─ Phase 5: synthesis-agent(mode=author) (opus, 前台) → profile.md
└─ Phase 6: audit-agent (sonnet, 前台) → 校验 + 修复所有生成文件
```

## 执行流程

```python
author_name, full_name = parse_args()
manifest_path = f"processing/authors/{author_name}/manifest.json"

# 1. DISCOVER
if not exists(manifest_path):
    Agent("quasi:new-discover-agent", foreground=True,
          prompt=f"""
task: discover this author's representative works on the given topic

context:
  author_name: {author_name}     # kebab slug
  full_name: {full_name}
  topic: ...                     # 主进程从 args / 对话收集，不要让 agent 猜

constraints:
  n_books: 5
  n_papers: 10
  sort_by: citations

output_path: {manifest_path}

output_schema (example):
{{
  "author": "{full_name}",
  "slug": "{author_name}",
  "discovered": "YYYY-MM-DD",
  "books": [
    {{"title": "...", "year": 0, "slug": "{author_name}-...-YYYY",
      "isbn": "...", "md5": null, "status": "discovered", "reason": "..."}}
  ],
  "papers": [
    {{"title": "...", "doi": "...", "year": 0, "citations": 0,
      "oa_url": null, "status": "discovered", "reason": "..."}}
  ]
}}
""")

# 2. ACQUIRE
manifest = read_json(manifest_path)
if any(status == "discovered"):
    Agent("quasi:download-agent", foreground=True,
          prompt=f"manifest_path: {manifest_path}, mode: both")

# 2a. DOI liveness (optional, caller-side)
# If you want to verify every DOI in the manifest resolves, loop:
# for key, paper in manifest['papers'].items():
#     doi = paper.get('doi')
#     if not doi:
#         continue
#     rc = subprocess.call(['curl', '-sI', '--max-time', '10',
#                            f'https://doi.org/{doi}'],
#                           stdout=subprocess.DEVNULL)
#     paper['doi_status'] = 'live' if rc == 0 else 'dead'
# bin 不再提供 batch validate;caller 自行决定 liveness 检查策略。

# 3. PROCESS BOOKS
# Phase 2 结束时 download-agent 已对每本书调用 --finalize-book，manifest 中
# books[*].slug 与 sources/{slug}.{ext} 均已是 canonical。Phase 3 起所有路径
# 直接复用 book.slug，不再重新派生。
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
        Agent("quasi:analyse-agent", background=True,
              prompt=f"type: A, book_title: ..., slot: {ch.slot}, chapter_label: ..., "
                     f"input: ..., output: ..., topic: ...")

while not all_done:
    sleep(30)

# 3c. 逐本概览(走大一统 synthesis-agent, mode=book)
for book in acquired_books:
    if not exists(f"vault/books/{book.slug}/00-overview.md"):
        Agent("quasi:synthesis-agent", foreground=True,
              prompt=f"mode: book\noutput_dir: vault/books/{book.slug}/\nbook_title: ...\ntopic: ...")

# 4. PROCESS PAPERS
# paper.slug 必须形如 {author-surname}-{title}-{year}（全局唯一）
# 所有论文产出均落到扁平 vault/papers/，与全库共享 slug 命名空间
for paper in manifest.papers where status == "acquired":
    output_path = f"vault/papers/{paper.slug}.md"
    if not exists(output_path):
        Agent("quasi:analyse-agent", background=True,
              prompt=f"type: B, title: ..., doi: ..., input: ..., "
                     f"output: {output_path}, topic: ...")

while not all_papers_done:
    sleep(30)

# 5. SYNTHESIS (mode=author 走大一统 synthesis-agent)
profile_path = f"vault/authors/{author_name}.md"
if not exists(profile_path):
    paper_paths = [f"vault/papers/{p.slug}.md" for p in manifest.papers if status == "acquired"]
    book_overview_paths = [f"vault/books/{b.slug}/00-overview.md" for b in acquired_books]
    Agent("quasi:synthesis-agent", foreground=True,
          prompt=f"mode: author\nauthor_name: {author_name}\nfull_name: {full_name}\ntopic: ...\n"
                 f"output_path: {profile_path}\n"
                 f"book_overview_paths: {book_overview_paths}\npaper_paths: {paper_paths}")

# 6. AUDIT
# 校验 + 修复所有本次生成的文件,在源头止住 schema 漂移。
# 每个 path 一个独立 Agent() 调用,顺序前台跑(audit-agent 单文件 ~30-60s)。
audit_targets = [profile_path]
for b in acquired_books:
    audit_targets.append(f"vault/books/{b.slug}/")  # overview + 所有章节
for p in manifest.papers where status == "acquired":
    audit_targets.append(f"vault/papers/{p.slug}.md")

for path in audit_targets:
    audit = Agent("quasi:audit-agent", foreground=True,
                  prompt=f"path: {path}")

    # audit-agent only performs local minimal repairs. Escalated items mean the
    # owning generation step must redo the corresponding file/subtree.
    if audit.audit_result.escalated:
        for item in audit.audit_result.escalated:
            p = item.path
            if p == profile_path:
                Agent("quasi:synthesis-agent", foreground=True,
                      prompt=f"mode: author\nauthor_name: {author_name}\nfull_name: {full_name}\ntopic: ...\n"
                             f"output_path: {profile_path}\n"
                             f"book_overview_paths: {book_overview_paths}\npaper_paths: {paper_paths}\n"
                             f"overwrite: true\nreason: audit escalated {item.kind}: {item.reason}")
            elif "/vault/books/" in p and p.endswith("/00-overview.md"):
                b = find_book_for_overview(acquired_books, p)
                Agent("quasi:synthesis-agent", foreground=True,
                      prompt=f"mode: book\noutput_dir: vault/books/{b.slug}\nbook_title: {b.title}\ntopic: ...\n"
                             f"overwrite: true\nreason: audit escalated {item.kind}: {item.reason}")
            elif "/vault/books/" in p and "/ch" in basename(p):
                b, ch = find_book_chapter_for_output(acquired_books, p)
                Agent("quasi:analyse-agent", foreground=True,
                      prompt=f"type: A, book_title: {b.title}, slot: {ch.slot}, chapter_label: {chapter_label}, "
                             f"input: processing/chapters/{b.slug}/{ch.filename}, "
                             f"output: {p}, topic: ...\n"
                             f"overwrite: true\nreason: audit escalated {item.kind}: {item.reason}")
            elif "/vault/papers/" in p:
                paper = find_manifest_paper_for_output(manifest, p)
                Agent("quasi:analyse-agent", foreground=True,
                      prompt=f"type: B, title: {paper.title}, doi: {paper.doi}, "
                             f"input: {paper.local_path}, output: {p}, topic: ...\n"
                             f"overwrite: true\nreason: audit escalated {item.kind}: {item.reason}")
            else:
                report(f"audit escalated unknown author-processing path: {p}")

        audit = Agent("quasi:audit-agent", foreground=True,
                      prompt=f"path: {path}")
        if audit.audit_result.escalated:
            report(f"audit still escalated for {path} after one regeneration pass")
            return
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
| Phase 6 | 无 —— 幂等,可重复跑 | 上次 typecheck clean 时几乎无成本 |

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

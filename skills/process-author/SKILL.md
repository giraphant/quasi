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
├─ Phase 1: search-agent (opus, 前台) → manifest
├─ Phase 2: download-agent (sonnet, 前台) × 2 → kind=book + kind=paper
├─ Phase 3: 书籍处理
│   ├─ 逐本: extract-agent (sonnet, 前台)
│   ├─ 主进程: 读 manifest → 全部章节
│   ├─ analyse-agent ×N (opus, 后台, 跨书并行)
│   ├─ Glob 轮询
│   └─ 逐本: synthesis-agent(mode=book) (opus, 前台)
├─ Phase 4: analyse-agent ×M (opus, 后台) → 论文
├─ Phase 5: synthesis-agent(mode=author) (opus, 前台) → profile.md
├─ Phase 6: audit-agent (sonnet, 前台) → 校验 + 修复所有生成文件
└─ Phase 7: local-agent (sonnet, 前台) → 中译本 metadata 回填
```

## 执行流程

```python
author_name, full_name = parse_args()
manifest_path = f".quasi/authors/{author_name}/manifest.json"

# 1. DISCOVER — two structured search-agent calls (kind=book + kind=paper),
# skill main process merges results into the manifest the existing Phase 2+
# code expects. search-agent contract since 0.25.0 demands {task, context,
# constraints, output_path, output_schema} as structured fields;
# narrative prompts no longer parse.
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
    # (Pseudocode — at runtime: Read books_path + papers_path with Read tool,
    #  parse JSON, build manifest dict, Write to manifest_path.)
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
    # Fail-fast (download-agent paper flow has no candidate retry — single DOI).
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

# DOI liveness check is opt-in caller responsibility (bin no longer ships
# batch validate verb). If you want it, loop manifest.papers and
# `curl -sI --max-time 10 https://doi.org/{doi}` per entry.

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

# 7. LOCALISE
# 只对本次获得的 book overview 回填中译本 / 中文版本 metadata。
# local-agent 幂等:已有 cndouban: [] 或 [..] 会跳过。
for b in acquired_books:
    Agent("quasi:local-agent", foreground=True,
          prompt=f"path: vault/books/{b.slug}/\nmode: cndouban")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 1 | `manifest.json` | 存在则跳过 |
| Phase 2 | manifest `status` | acquired / year_mismatch / year_ambiguous / failed 跳过（重跑只处理 discovered） |
| Phase 3a | `{chapters_dir}/manifest.json` | 存在则跳过提取 |
| Phase 3b | `ch{NN}-*.md` | 存在则跳过该章 |
| Phase 3c | `00-overview.md` | 存在则跳过该书 |
| Phase 4 | `vault/papers/{paper.slug}.md` | 存在则跳过 |
| Phase 5 | `vault/authors/{author-name}.md` | 存在则跳过 |
| Phase 6 | 无 —— 幂等,可重复跑 | 上次 typecheck clean 时几乎无成本 |
| Phase 7 | book frontmatter `cndouban` | 已有 `[]` 或 `[id]` 则 local-agent 跳过 |

## 目录结构

```
.quasi/authors/{author-name}/
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

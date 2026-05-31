---
name: quasi: process-author
description: Use when the user wants to build an author profile from a scholar's representative books and papers.
---

# Process Author — 作者处理

## 任务

搜索、下载、分析并综合用户指定作者的代表作。

## 输入

从用户请求中归一化出:

- `author_name`:kebab-case,如 `donna-haraway`
- `full_name`:可由用户显式给出,否则由 `author_name` 反推后交给 search-agent 校正
- `topic`:可选范围提示

## Agent / Helper 合同

- 主进程 owns state:`.quasi/authors/{author_name}/manifest.json`。
- search/download/analyse/synthesis/audit/localise 只作为专业工种被调度。
- manifest `status` 控制 downstream phase;warning 字段不能替代可消费状态。
- 书籍子流程必须保持和 `process-book` 的 chapter manifest / output 命名一致。
- 本 skill 允许跨书/论文 background fan-out,但同一文件只能由一个 agent 写。
- analyse/synthesis 按目标类型产出语义完整、metadata 可靠的 Markdown；本 workflow 在 Phase 6 统一运行 audit-agent。

## 硬约束

- **禁止用 TaskOutput 检查后台 agent**：会报 "No task found"，导致卡住
- **必须用 Glob 轮询输出文件**来判断完成
- **每个文本独立 dispatch 一个 analyse-agent**：禁止把多章/多篇论文合并到一个 agent 调用中。一个文本 = 一个 Agent() 调用。
- **Dispatcher context 卫生**：
  - Glob 轮询只关注完成数 vs 总数，不要逐一列举文件名
  - 后台 agent 完成通知是冗余信息，收到后不需要额外处理
  - 每个阶段完成后不要回顾前序输出，关键状态已在磁盘上

## 工作流

```
主进程 (dispatcher)
├─ Phase 0: local author/work recall + manifest/cache resume
├─ Phase 1: search-agent (opus, 前台, only missing discovery) → manifest
├─ Phase 2: local representative-work reconcile → download-agent (sonnet, 前台) × 2
├─ Phase 3: 书籍处理
│   ├─ 逐本: extract-agent (sonnet, 前台)
│   ├─ 主进程: 读 manifest → 全部章节
│   ├─ analyse-agent ×N (opus, 后台, 跨书并行)
│   ├─ Glob 轮询
│   └─ 逐本: synthesis-agent(mode=book) (opus, 前台)
├─ Phase 4: analyse-agent ×M (opus, 后台) → 论文
├─ Phase 5: synthesis-agent(mode=author) (opus, 前台) → profile.md
├─ Phase 6: audit-agent (sonnet, 前台) → 校验 + 修复所有生成文件
└─ Phase 7: search-agent + quasi-helpers localise → 中译本 metadata 回填
```

## 执行流程

```python
author_name, full_name = parse_args()
profile_path = f"vault/authors/{author_name}.md"
manifest_path = f".quasi/authors/{author_name}/manifest.json"
books_path  = f".quasi/authors/{author_name}/books.json"
papers_path = f".quasi/authors/{author_name}/papers.json"

# 0. LOCAL AUTHOR/WORK RECALL — before search-agent/download-agent.
# 先看 author profile / manifest / discovery caches;exact miss 后在 authors/books/papers/sources
# 做一把 rg fuzzy recall。高置信 profile 直接跳过;高置信 manifest/cache 则续跑。
if exists(profile_path):
    report(f"已有作者 profile,无需重复处理: {profile_path}"); return

if not exists(manifest_path):
    inspected_author = inspect_author_candidates(rg_fuzzy_recall(
        tokens=[full_name, author_name, author_surname(full_name), topic],
        paths=["vault/authors/*.md", "vault/books/*/00-overview.md", "vault/papers/*.md",
               "sources/*", ".quasi/authors/*/manifest.json"],
    ))
    if inspected_author.high_confidence_profile:
        report(f"已有作者 profile,无需重复处理: {inspected_author.profile_path}"); return
    if inspected_author.high_confidence_manifest:
        manifest_path = inspected_author.manifest_path
    elif inspected_author.candidates:
        report_candidate_list(inspected_author.candidates, note="local author recall only; do not blindly skip")

# 1. DISCOVER — two structured search-agent calls (kind=book + kind=paper), only for missing caches.
# search-agent only returns curated JSON; it never writes files. The skill main
# process may cache those JSON payloads, then merges them into the manifest that
# Phase 2+ expects.
if not exists(manifest_path):

    if not exists(books_path):
        books_search = Agent("quasi:search-agent", foreground=True, prompt=f"""\
task: find top representative books by {full_name} on topic {topic}, sorted by citations
context:
  kind: book
  author: {full_name}
  topic: {topic}
constraints:
  count: 5
  sort: citations
""")
        write_json(books_path, books_search)

    if not exists(papers_path):
        papers_search = Agent("quasi:search-agent", foreground=True, prompt=f"""\
task: find top representative papers by {full_name} on topic {topic}, sorted by citations
context:
  kind: paper
  author: {full_name}
  topic: {topic}
constraints:
  count: 10
  sort: citations
""")
        write_json(papers_path, papers_search)

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
            for b in (books_raw if isinstance(books_raw, list) else books_raw.get("candidates") or books_raw.get("results", []))
        ],
        "papers": [
            {**p, "status": "discovered", "oa_url": None}
            for p in (papers_raw if isinstance(papers_raw, list) else papers_raw.get("candidates") or papers_raw.get("results", []))
        ],
    }
    write_json(manifest_path, manifest)

# 2. ACQUIRE — 先 reconcile representative works 的本地 final/source/partial artifacts,
# 再 download 仍是 discovered 且没有本地 output/source 的 item。completed/partial 从 artifact 推断,
# 不新增 manifest status。
manifest = reconcile_representative_works_with_local_artifacts(manifest)
# skill merges per-item status + year_evidence back into the manifest.
# Batch policy: year_mismatch / year_ambiguous books DO NOT pause; skill
# accepts tmp_path → sources/{slug}.{ext} (slug authoritative), keeps
# status="acquired" so Phase 3 consumes the book, and records year_review /
# year_evidence / year_warning for end-of-run report.
write_json(manifest_path, manifest)
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
    #   ok/year_* accepted into sources → acquired; download_failed → failed.
    for item in book_result.per_item:
        i = index_of(manifest["books"], slug=item["slug"])
        if item["status"] == "ok":
            manifest["books"][i]["status"] = "acquired"
        elif item["status"] in ("year_mismatch", "year_ambiguous"):
            # Override agent's "keep as tmp" — author batch accepts into sources
            # anyway, but records the year evidence for offline review.
            Bash(f"quasi-download accept --path {item['tmp_path']} --slug {item['slug']} --kind book --json")
            manifest["books"][i]["status"] = "acquired"
            manifest["books"][i]["year_review"] = item["status"]
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
n_year_warned = sum(1 for b in manifest["books"] if b.get("year_review"))
n_paper_failed = sum(1 for p in manifest["papers"] if p["status"] == "failed")
if n_year_warned or n_paper_failed:
    report(f"Acquire summary: {n_year_warned} book year warnings, "
           f"{n_paper_failed} paper download failures — review {manifest_path}")

# DOI liveness check is opt-in caller responsibility (bin no longer ships
# batch validate verb). If you want it, loop manifest.papers and
# `curl -sI --max-time 10 https://doi.org/{doi}` per entry.

# 3. PROCESS BOOKS
# Phase 2 结束时 download-agent 已对每本书调用 `quasi-download accept`，manifest 中
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
              prompt=f"""\
type: A
book_slug: {book.slug}
book_title: {book.title}
slot: {ch.slot}
chapter_label: {ch.chapter_label}
chapter_title: {ch.title}
year: {book.year}
chapter_authors: {ch.authors or book.authors}
input: processing/chapters/{book.slug}/{ch.filename}
output: {ch.output_path}
topic: {topic}
""")

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
              prompt=f"""\
type: B
title: {paper.title}
authors: {paper.authors}
year: {paper.year}
journal: {paper.journal}
doi: {paper.doi}
input: {paper.local_path}
output: {output_path}
topic: {topic}
""")

while not all_papers_done:
    sleep(30)

# 5. SYNTHESIS (mode=author 走大一统 synthesis-agent)
# 如果作者 profile 不存在但代表作已有 final outputs,直接复用这些 outputs 做 synthesis,
# 不因为旧 slug/本次 slug 微差而重新下载或分析。vault/authors/{author_name}.md 才表示作者完成。
profile_path = f"vault/authors/{author_name}.md"
if not exists(profile_path):
    paper_paths = [f"vault/papers/{p.slug}.md" for p in manifest.papers if status == "acquired"]
    book_overview_paths = [f"vault/books/{b.slug}/00-overview.md" for b in acquired_books]
    Agent("quasi:synthesis-agent", foreground=True,
          prompt=f"mode: author\nauthor_name: {author_name}\nfull_name: {full_name}\ntopic: ...\n"
                 f"output_path: {profile_path}\n"
                 f"book_overview_paths: {book_overview_paths}\npaper_paths: {paper_paths}")

# 6. AUDIT
# 对本次生成文件运行 audit-agent。
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
                      prompt=f"""\
type: A
book_slug: {b.slug}
book_title: {b.title}
slot: {ch.slot}
chapter_label: {ch.chapter_label}
chapter_title: {ch.title}
year: {b.year}
chapter_authors: {ch.authors or b.authors}
input: processing/chapters/{b.slug}/{ch.filename}
output: {p}
topic: {topic}
overwrite: true
reason: audit escalated {item.kind}: {item.reason}
""")
            elif "/vault/papers/" in p:
                paper = find_manifest_paper_for_output(manifest, p)
                Agent("quasi:analyse-agent", foreground=True,
                      prompt=f"""\
type: B
title: {paper.title}
authors: {paper.authors}
year: {paper.year}
journal: {paper.journal}
doi: {paper.doi}
input: {paper.local_path}
output: {p}
topic: {topic}
overwrite: true
reason: audit escalated {item.kind}: {item.reason}
""")
            else:
                report(f"audit escalated unknown author-processing path: {p}")

        audit = Agent("quasi:audit-agent", foreground=True,
                      prompt=f"path: {path}")
        if audit.audit_result.escalated:
            report(f"audit still escalated for {path} after one regeneration pass")
            return

# 7. LOCALISE
# 只对本次获得的 book overview 回填中译本 / 中文版本 metadata。
# search-agent 返回核验过的 localisations.zh.candidates;顶层调用 helper
# 写入 .quasi/localise/cndouban.json。helper 按原书 ISBN 幂等。
for b in acquired_books:
    scan = Bash(f"quasi-helpers localise scan --path vault/books/{b.slug}/ --json")
    if scan.pending == 0:
        continue
    search = Agent("quasi:search-agent", foreground=True,
                   prompt=f"kind: book\ncontext: read vault/books/{b.slug}/00-overview.md and search metadata/localisations")
    candidates_file = write_temp_json(search.localisations.zh.candidates)
    Bash("quasi-helpers localise write "
         f"--book-path vault/books/{b.slug}/00-overview.md "
         f"--candidates-file {candidates_file}")

# 8. OPEN IN MARPLE (best-effort UX)
# Open the final author profile. This must never fail the workflow; on failure,
# print the manual command and continue.
Bash(f"/opt/homebrew/bin/marple-cli open '{profile_path}' || marple-cli open '{profile_path}' || echo 'Marple open skipped; run: marple-cli open {profile_path}'")
```

## 状态

`.quasi/authors/{author_name}/manifest.json` 由本 skill 主进程维护。

`completed` / `partial` 不写成新的 manifest status; completed/partial is inferred from artifact:
`vault/authors/{author_name}.md`、`vault/books/{book.slug}/00-overview.md`、`vault/papers/{paper.slug}.md`
是 final outputs;`sources/*`、`processing/chapters/*/manifest.json`、`ch*.md` 是可续跑 state。

Book status:
- `discovered` — 已由 search-agent 选入代表作清单,尚未获取文件。
- `acquired` — `sources/{slug}.{ext}` 已可供 Phase 3 使用。
- `failed` — 获取失败,带 `failure_note`。

Book year ambiguity 不改变 `status`:已 accept 入库的书仍是 `acquired`,
另写 `year_review ∈ {year_mismatch, year_ambiguous}`、`year_evidence`、
`year_warning` 供收尾报告和人工复查。

Paper status:
- `discovered` — 已入清单,尚未获取 PDF。
- `acquired` — `local_path` 指向稳定 PDF。
- `failed` — 获取失败,带 `failure_note`。

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 0/1 | local recall: `vault/authors/{author_name}.md` / manifest / discovery caches | profile 已有则跳过;manifest/cache 已有则续跑或只 search 缺的一侧;候选低置信度只列证据 |
| Phase 2 | representative works local reconcile | 已有 book/paper final output、source、chapter manifest 或 paper cache 时先复用/续跑;只有仍缺 source/output 的 discovered item 才 download |
| Phase 3a | `{chapters_dir}/manifest.json` | 存在则跳过提取 |
| Phase 3b | `ch{NN}-*.md` | 存在则跳过该章 |
| Phase 3c | `00-overview.md` | 存在则跳过该书 |
| Phase 4 | `vault/papers/{paper.slug}.md` | 存在则跳过 |
| Phase 5 | `vault/authors/{author-name}.md` | 存在则跳过；若 profile 不存在但代表作 outputs 已存在,直接复用 outputs synthesis |
| Phase 6 | 无 —— 幂等,可重复跑 | 上次 audit clean 时几乎无成本 |
| Phase 7 | `.quasi/localise/cndouban.json#by_isbn[isbn]` | 已存在 entry(status found/none)则 helper scan 跳过 |

## 输出

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

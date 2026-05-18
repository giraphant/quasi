---
name: quasi:process-book
description: >
  Use when the user says "处理这本书", "跑一下这本handbook", "总结这本",
  or wants to process an EPUB/PDF book into structured chapter summaries.
---

# Process Book — 书籍处理

## 任务

下载、切分、逐章分析并综合用户提供的书。

## 输入

从用户请求中提取可用于搜索和定位源文件的线索:

- `title` 或自然语言 `query`
- `author`:可选,但强烈优先使用
- `year_hint`:可选
- `isbn`:可选
- `source_path` 或 `slug_hint`:可选,用于命中已有 `sources/` 文件
- `topic`:可选,传给 analyse/synthesis

## 状态

- 无独立 book workflow manifest。
- `book_slug` 是 Step 0 产物,由 search/download/source filename 确定;
  canonical 格式为 `{author-surname}-{short-title}-{year}`。
- 主进程 owns state:`processing/chapters/{book_slug}/manifest.json` 的消费、
  `vault/books/{book_slug}/` 的完成判断、以及 localise cache 写入触发。
- `sources/{book_slug}.{epub,pdf}` 存在表示 acquisition 已完成。
- `vault/books/{book_slug}/00-overview.md` 存在表示整本书生成完成。

## Agent / Helper 合同

- `download-agent` 只负责 acquisition 判断和 accept;year ambiguity 是 human gate。
- `extract-agent` 负责提取、验证、修复,并产出统一 chapter manifest
  (`slot/title/filename/word_count`)。
- `analyse-agent` 每章一个 background worker,不得合并多章。
- `synthesis-agent` 只写 `00-overview.md`;audit escalated 由本 skill 路由回生成阶段。

## 硬约束

- **禁止用 TaskOutput 检查后台 agent**：TaskOutput 会报 "No task found"，导致卡住
- **必须用 Glob 轮询输出文件**：检查 `{output_dir}/ch*.md` 数量来判断完成
- 后台 agent 完成时会自动通知，但如果错过通知，Glob 是唯一可靠的检查方式
- **每个文本独立 dispatch 一个 analyse-agent**：禁止把多章合并到一个 agent 调用中。一章 = 一个 Agent() 调用。
- **Dispatcher context 卫生**：
  - Glob 轮询只关注完成数 vs 总数，不要逐一列举文件名
  - 后台 agent 完成通知是冗余信息，收到后不需要额外处理
  - 每个阶段完成后不要回顾前序输出，关键状态已在磁盘上

## 工作流

```
主进程 (dispatcher)
├─ Step 0: 定位 source + search metadata + 必要时 download-agent
├─ Step 1: extract-agent (sonnet, 前台) → 提取+验证+修复
├─ Step 2: 主进程读 manifest.json → 筛选章节
├─ Step 3: analyse-agent ×N (opus, 后台并行) → Glob 轮询
├─ Step 4: synthesis-agent(mode=book) (opus, 前台)
├─ Step 5: audit-agent (sonnet, 前台) → 校验
└─ Step 6: search-agent + quasi-helpers localise → 中译本 metadata 回填
```

## 执行流程

```python
# 0. 从用户请求提取搜索线索。book_slug 不是输入,而是 Step 0 的结果。
request = parse_user_request()  # title/query, author?, year_hint?, isbn?, source_path?, slug_hint?, topic?

# Step 0: SOURCE + METADATA
# 先用 source_path/slug_hint/query 在 sources/ 中找已存在源文件;再用 search-agent
# 补齐 metadata 和 canonical slug。找不到源文件时,用 search 结果交给 download-agent 获取。
source_file = find_existing_source(
    source_path=request.source_path,
    slug_hint=request.slug_hint,
    title=request.title or request.query,
    author=request.author,
)

search = Agent("quasi:search-agent", foreground=True, prompt=f"""\
task: find canonical metadata for this book
context:
  kind: book
  title: {request.title or request.query}
  author: {request.author or ""}
  year_hint: {request.year_hint or ""}
  isbn: {request.isbn or ""}
constraints:
  count: 1
""")
book_meta = search.picked
book_slug = book_meta["slug"]

if not source_file:
    source_file = Glob(f"sources/{book_slug}.epub") or Glob(f"sources/{book_slug}.pdf")

if not source_file:
    # download-agent 内部完成 fetch → inspect → accept,并返回 year_evidence。
    # 主进程只根据 per_item[0].status 分支。

    result = Agent("quasi:download-agent", foreground=True, prompt=f"""\
kind: book
items:
  - slug: {book_slug}
    expected_author: {book_meta.get('authors', [''])[0] if book_meta.get('authors') else request.author or ''}
    expected_title: {book_meta.get('title') or request.title or request.query}
    identifiers:
      isbn: {book_meta.get('isbn') or request.isbn or ''}
output_dir: sources/
""")

    item = result.per_item[0]
    if item.status == "ok":
        source_file = item.path        # agent 已 accept temp → sources/{slug}.{ext}
    elif item.status in ("year_mismatch", "year_ambiguous"):
        # 把 year_evidence 整块原样递给用户（含 tmp_path），让用户拍板：
        # 1) 改 slug 中的 year 重跑（slug 重命名 → 触发 download-agent 重新 accept）
        # 2) 接受 recommended_year，手动 mv tmp_path → 正式名 + 重跑（跳过 Step 0）
        report(f"""\
YEAR_TRIAGE for {book_slug}: verdict={item.year_evidence.verdict}
- slug_year:        {item.year_evidence.slug_year}
- source_years:     {item.year_evidence.source_years}
- pdf_signals:      {item.year_evidence.pdf_signals}
- recommended_year: {item.year_evidence.recommended_year}
- reason:           {item.year_evidence.recommendation_reason}
- tmp_file:         {item.tmp_path}

Action: 改 slug 的 year 重跑，或手动 mv {item.tmp_path} 到正确路径后重跑。
""")
        return
    else:  # download_failed
        report(f"download-agent failed to acquire {book_slug}: {item.get('verdict_note', 'no details')}")
        return

chapters_dir = f"processing/chapters/{book_slug}/"

# 1. EXTRACT（一次调用完成提取+验证+修复）
if not exists(f"{chapters_dir}/manifest.json"):
    result = Agent("quasi:extract-agent", foreground=True,
                   prompt=f"source_file: {source_file}, chapters_dir: {chapters_dir}")
    if result.status == "failed":
        report("需人工检查"); return

# 2. 读取章节清单（全部章节，不筛选）
manifest = Read(f"{chapters_dir}/manifest.json")
selected = manifest.chapters   # 每项含 slot, title, filename, word_count
output_dir = f"vault/books/{book_slug}"

# 3. 并行分析
# slot 格式："01".."99" 真章节 / "00a".."00z" 前言 / "99a".."99z" 后记 / "{N}b".."{N}z" 章间插曲
# 根据 slot 推导人类可读的 chapter_label 传给 analyse-agent：
#   slot 纯数字 N       → chapter_label = f"第{int(slot)}章"
#   slot 以 "00" 开头   → chapter_label = "前言"（或根据 title：Foreword/Preface/Introduction）
#   slot 以 "99" 开头   → chapter_label = "后记"（或根据 title：Afterword/Epilogue/Appendix）
#   slot 形如 "{N}{x}" → chapter_label = f"第{N}章（附）"
for ch in selected:
    if not exists(f"{output_dir}/ch{ch.slot}-{ch.slug}.md"):
        Agent("quasi:analyse-agent", background=True,
              prompt=f"type: A, book_title: ..., slot: {ch.slot}, chapter_label: {chapter_label}, "
                     f"input: {chapters_dir}/{ch.filename}, "
                     f"output: {output_dir}/ch{ch.slot}-{ch.slug}.md, topic: ...")

while Glob(f"{output_dir}/ch*.md").count < len(selected):
    sleep(30)

# 4. 概览(走大一统 synthesis-agent, mode=book)
if not exists(f"{output_dir}/00-overview.md"):
    Agent("quasi:synthesis-agent", foreground=True,
          prompt=f"mode: book\noutput_dir: {output_dir}\nbook_title: ...\ntopic: ...")

# Step 5: AUDIT
# 校验 + 修复整本书目录(overview + 所有章节),在源头止住 schema 漂移。
audit = Agent("quasi:audit-agent", foreground=True,
              prompt=f"path: {output_dir}")

# audit-agent 只做本地最小修复。若返回 escalated,说明对应内容需要由本 workflow
# 的生成阶段重做,不要让 audit-agent 补写内容。
if audit.audit_result.escalated:
    for item in audit.audit_result.escalated:
        path = item.path
        if path.endswith("/00-overview.md"):
            Agent("quasi:synthesis-agent", foreground=True,
                  prompt=f"mode: book\noutput_dir: {output_dir}\nbook_title: ...\ntopic: ...\n"
                         f"overwrite: true\nreason: audit escalated {item.kind}: {item.reason}")
        elif basename(path).startswith("ch"):
            ch = find_manifest_chapter_for_output(manifest, path)
            Agent("quasi:analyse-agent", foreground=True,
                  prompt=f"type: A, book_title: ..., slot: {ch.slot}, chapter_label: {chapter_label}, "
                         f"input: {chapters_dir}/{ch.filename}, "
                         f"output: {path}, topic: ...\n"
                         f"overwrite: true\nreason: audit escalated {item.kind}: {item.reason}")
        else:
            report(f"audit escalated unknown book path: {path}")

    audit = Agent("quasi:audit-agent", foreground=True,
                  prompt=f"path: {output_dir}")
    if audit.audit_result.escalated:
        report("audit still has escalated items after one regeneration pass; hand off to user")
        return

# Step 6: LOCALISE
# 只回填中译本 / 中文版本 metadata。search-agent 返回核验过的
# localisations.zh.candidates,顶层用 helper 写入 .quasi/localise/cndouban.json。
# helper 按原书 ISBN 幂等:已查过的 ISBN 不重复跑。
localise_scan = Bash(f"quasi-helpers localise scan --path {output_dir} --json")
if localise_scan.pending > 0:
    search = Agent("quasi:search-agent", foreground=True,
                   prompt=f"kind: book\ncontext: read {output_dir}/00-overview.md and search metadata/localisations")
    candidates_file = write_temp_json(search.localisations.zh.candidates)
    Bash("quasi-helpers localise write "
         f"--book-path {output_dir}/00-overview.md "
         f"--candidates-file {candidates_file}")

print(f"Done: {len(selected)} chapters, overview generated, typechecked, localised")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 0 | `sources/{slug}.{epub,pdf}` | 存在则跳过 download-agent |
| Step 1 | `{chapters_dir}/manifest.json` | 存在则跳过 extract-agent |
| Step 3 | `ch{slot}-*.md` | 存在则跳过该章 |
| Step 4 | `00-overview.md` | 存在则跳过 |
| Step 5 | 无 —— 幂等,可重复跑 | 上次 audit clean 时几乎无成本 |
| Step 6 | `.quasi/localise/cndouban.json#by_isbn[isbn]` | 已存在 entry(status found/none)则 helper scan 跳过 |

## 输出

```
sources/{book-slug}.epub|.pdf          ← canonical slug 对应的源文件
processing/chapters/{book-slug}/       ← 规范 slug: {author}-{title}-{year}
├── manifest.json
└── *.txt
vault/books/{book-slug}/               ← 含原 monographs 与 handbooks，统一归位
├── 00-overview.md
└── ch{slot}-{title}.md                ← slot 见 manifest.json（"01".."99"/"00a"/"99a"/...）
```

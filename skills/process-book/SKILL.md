---
name: quasi:process-book
description: >
  Use when the user says "处理这本书", "跑一下这本handbook", "总结这本",
  or wants to process an EPUB/PDF book into structured chapter summaries.
---

# Process Book — 书籍处理

从 EPUB/PDF 到结构化摘要。扁平 agent 调度。

## 调用方式

```
/quasi:process-book {book-slug}
```

`{book-slug}` 必须是 canonical 格式：`{author-surname}-{short-title}-{year}`。
源文件落在 `sources/{book-slug}.{epub,pdf}`。

**没有源文件时,本 skill 自己 dispatch download-agent 去拿** —— 不要求调用方先准备。download-agent **复刻 process-author 的"discover → download → finalize"三阶段**,只是 N=1:
1. **discover** (pre-download): `quasi-search books` 拿 GB/OL/OA/AA 候选,每个 source 单独记录 year (不混叫 `ol_year`),记 best-match 的 md5
2. **download**: `quasi-download book --md5 {md5}`
3. **finalize** (post-download): Read PDF 前 3 页(版权页/titlepage)抽多种 year signal (first_published / copyright_year / original_year),与 slug_year + 各 source year 一起报回主进程裁决

这套验证不是 process-book 特有的——它就是 process-author Phase 1+2 那条 chain 的单本切片。N-source contract 把"次次取一个糊名 year"换成"每个源单独列",让多源分歧(典型: AA 抄版权页 2022,OL editions 全 2023)在主进程面前显形而不是被压成单值。

## ⚠ 硬约束

- **禁止用 TaskOutput 检查后台 agent**：TaskOutput 会报 "No task found"，导致卡住
- **必须用 Glob 轮询输出文件**：检查 `{output_dir}/ch*.md` 数量来判断完成
- 后台 agent 完成时会自动通知，但如果错过通知，Glob 是唯一可靠的检查方式
- **每个文本独立 dispatch 一个 analyse-agent**：禁止把多章合并到一个 agent 调用中。一章 = 一个 Agent() 调用。
- **Dispatcher context 卫生**：
  - Glob 轮询只关注完成数 vs 总数，不要逐一列举文件名
  - 后台 agent 完成通知是冗余信息，收到后不需要额外处理
  - 每个阶段完成后不要回顾前序输出，关键状态已在磁盘上

## 编排架构

```
主进程 (dispatcher)
├─ Step 0: download-agent (sonnet, 前台) → 没源文件时,自己去拿
├─ Step 1: extract-agent (sonnet, 前台) → 提取+验证+修复
├─ Step 2: 主进程读 manifest.json → 筛选章节
├─ Step 3: analyse-agent ×N (opus, 后台并行) → Glob 轮询
├─ Step 4: synthesis-agent(mode=book) (opus, 前台)
└─ Step 5: audit-agent (sonnet, 前台) → 校验
```

## 执行流程

```python
# 0. 使用已定稿 slug
# 输入约定：book_slug 必须是 canonical 格式 {author-surname}-{short-title}-{year}
# - 通过 process-author 调用：上游 download-agent 已 finalize，slug 在 manifest 中定稿
# - 用户直接调用：用户给定的 book_slug 即视为 canonical，sources/ 文件名应同名
# 本 skill 不再重新派生 slug，所有路径直接基于 book_slug。
book_slug = parse_args()
source_file = Glob(f"sources/{book_slug}.epub") or Glob(f"sources/{book_slug}.pdf")

# Step 0: ACQUIRE & VERIFY
# 复刻 process-author Phase 1+2 那条 chain,N=1 版:
#   discover (quasi-search 拿 OL/CR/AA year) → download → finalize (PDF 首页 year)
#   → 三方 year 对比 (slug / OL / PDF)
# 不接 --doi/--md5/--url 等 flag(那是 download-agent 内部要管的事)。
if not source_file:
    result = Agent("quasi:download-agent", foreground=True, prompt=f"""\
intent: single book with N-source year triage
book_slug: {book_slug}
output_dir: sources/

steps (复刻 process-author 的 discover → download → finalize 三段):

1. **discover** —— 从 slug 反解 (author, title, year_in_slug);
   `quasi-search books --author X --title Y --limit 5 --json` 拿候选;
   该命令默认 --source all,内部并发 Google Books / OpenLibrary / OpenAlex,
   再单独 `--source aa` 拿 Anna's Archive (含 MD5).
   **每个 source 单独记录命中的 year**,不要合并成一个值:
     - gb_year (Google Books publishedDate[:4])
     - ol_year (OpenLibrary first_publish_year)
     - oa_year (OpenAlex publication_year)
     - aa_year (Anna's Archive table cell)
   挑 best-match (title overlap >=0.7 + author surname 必须出现) 拿 md5,
   md5 来自哪个源就标在 best_match_source 字段里.

2. **download** —— `quasi-download book --md5 {{md5}} -o sources/ --filename {book_slug}`
   先下到 sources/{book_slug}.tmp.{{ext}} (临时名,等 triage 完再 finalize)

3. **finalize** —— Read 临时文件前 3 页 (版权页 / titlepage);
   抽多种 year signal,不要直接归并成单值:
     - first_published: 命中 "First published in {{year}}" / "First edition {{year}}" / "Published {{year}}" 模式
     - copyright_year: 命中 "Copyright © {{year}}" / "Copyright {{year}}" 模式
     - original_year: 命中 "Originally published as ... {{year}}" / "Translated from ... {{year}}" (翻译书原版年)
     - other_years: 前 3 页里其余 1900-2099 数字
   并把版权页相关那段原文 (≤120 字) 放到 pdf_evidence 字段里.

4. **N-source triage** —— 不强求"全一致"。按下面格式报告,让主进程裁决:

   YEAR_TRIAGE:
   - slug_year: {{year_in_slug}}
   - source_years:
       google_books: {{gb_year or null}}
       openlibrary:  {{ol_year or null}}
       openalex:     {{oa_year or null}}
       anna_archive: {{aa_year or null}}
   - best_match_source: {{which source the md5 came from}}
   - pdf_signals:
       first_published: {{int or null}}
       copyright_year:  {{int or null}}
       original_year:   {{int or null}}
       other_years:     [..]
   - pdf_evidence: "..."
   - recommended_year: {{int}}
     # 偏好顺序: pdf.first_published > 多源众数 > pdf.copyright_year
     # 翻译书: original_year 不应作为 recommended (那是原文年,不是本版年)
   - recommendation_reason: "{{one line: 为什么选这个而不是其他}}"
   - verdict: MATCH | MISMATCH | AMBIGUOUS
     # MATCH:  slug_year == recommended_year && (至少 2 个 source/pdf signal 一致 recommended_year)
     # MISMATCH: slug_year != recommended_year 且证据明确
     # AMBIGUOUS: 证据太散无法定论
   - tmp_file: sources/{book_slug}.tmp.{{ext}}  (仅 MISMATCH/AMBIGUOUS 时保留)

   verdict=MATCH 时,mv tmp file 到 sources/{book_slug}.{{ext}} 并改输出头为:
     DOWNLOAD_OK:
     - year: {{recommended_year}}
     - source: sources/{book_slug}.{{ext}}
     - source_years: {{...}}
     - pdf_signals: {{...}}

   verdict ∈ {{MISMATCH, AMBIGUOUS}}: 不要 mv,临时文件保留,完整 YEAR_TRIAGE 块照报.
""")

    # 检查 download-agent 的输出
    if result.contains("YEAR_TRIAGE") and (result.contains("MISMATCH") or result.contains("AMBIGUOUS")):
        # 主进程把 YEAR_TRIAGE 整块原样递给用户,让用户基于 source_years + pdf_signals 拍板.
        # 用户改 slug 重跑,或手动 mv tmp 文件 + 接受 recommended_year.
        report(f"year triage — 见上方 YEAR_TRIAGE 块,改 slug 后重跑")
        return
    source_file = Glob(f"sources/{book_slug}.epub") or Glob(f"sources/{book_slug}.pdf")
    if not source_file:
        report(f"download-agent 没拿到 sources/{book_slug}.{{epub,pdf}};检查 slug 是否准确")
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
Agent("quasi:audit-agent", foreground=True,
      prompt=f"path: {output_dir}\nmode: full")

print(f"Done: {len(selected)} chapters, overview generated, typechecked")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 0 | `sources/{slug}.{epub,pdf}` | 存在则跳过 download-agent |
| Step 1 | `{chapters_dir}/manifest.json` | 存在则跳过 extract-agent |
| Step 3 | `ch{slot}-*.md` | 存在则跳过该章 |
| Step 4 | `00-overview.md` | 存在则跳过 |
| Step 5 | 无 —— 幂等,可重复跑 | 上次 audit clean 时几乎无成本 |

## 目录结构

```
sources/{book-slug}.epub|.pdf          ← canonical slug 对应的源文件
processing/chapters/{book-slug}/       ← 规范 slug: {author}-{title}-{year}
├── manifest.json
└── *.txt
vault/books/{book-slug}/               ← 含原 monographs 与 handbooks，统一归位
├── 00-overview.md
└── ch{slot}-{title}.md                ← slot 见 manifest.json（"01".."99"/"00a"/"99a"/...）
```

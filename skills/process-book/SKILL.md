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

**没有源文件时,本 skill 自己 dispatch download-agent 去拿** —— 不要求调用方先准备。download-agent 内部会用 quasi-search 找 md5/DOI 再下,具体策略它自己定。这跟 process-author 内部"逐本下载 → 处理"是同一段子流程的拆分。

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

本质上是 process-author 内部"逐本下载 → 处理"子流程的单本切片,所以编排形态对齐。

## 执行流程

```python
# 0. 使用已定稿 slug
# 输入约定：book_slug 必须是 canonical 格式 {author-surname}-{short-title}-{year}
# - 通过 process-author 调用：上游 download-agent 已 finalize，slug 在 manifest 中定稿
# - 用户直接调用：用户给定的 book_slug 即视为 canonical，sources/ 文件名应同名
# 本 skill 不再重新派生 slug，所有路径直接基于 book_slug。
book_slug = parse_args()
source_file = Glob(f"sources/{book_slug}.epub") or Glob(f"sources/{book_slug}.pdf")

# Step 0: ACQUIRE — sources/ 没有源文件时,dispatch download-agent 去拿
# 不要求调用方先准备源文件;不接 --doi/--md5/--url 等 flag(那是 download-agent 内部要管的事)。
# 注意:这跟 process-author Phase 2 的 download-agent 是同一段子流程,只不过这里 N=1。
if not source_file:
    Agent("quasi:download-agent", foreground=True,
          prompt=f"intent: single book\nbook_slug: {book_slug}\noutput_dir: sources/\n"
                 f"hints: 从 slug 推断 author/title/year,先用 quasi-search books 找候选(含 AA),"
                 f"再 quasi-download book --md5 拿到文件,最后 quasi-download finalize 定稿到 "
                 f"sources/{book_slug}.{{ext}}")
    source_file = Glob(f"sources/{book_slug}.epub") or Glob(f"sources/{book_slug}.pdf")
    if not source_file:
        report(f"download-agent 没能拿到 sources/{book_slug}.{{epub,pdf}};检查 slug 是否准确,"
               f"或手动放文件后重跑")
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

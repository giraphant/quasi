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

**没有源文件时,本 skill 自己 dispatch download-agent 去拿** —— 不要求调用方先准备。download-agent 内部完成 search → download → 身份验证 → 算 year_evidence；主进程只读 `per_item[0].status` 决定继续 / 弹给用户 / 失败。具体 year 证据收集与 verdict 计算规则见 `agents/download-agent.md` 的 `year_evidence` 段。

`status` 分支：
- `ok` —— agent 已 mv tmp → final，继续 EXTRACT。
- `year_mismatch` / `year_ambiguous` —— 不继续；把 `year_evidence`（含 `tmp_path`）原样递给用户。用户改 slug 中的 year 重跑，或手动 mv tmp 到正确路径后重跑。
- `download_failed` —— 报错退出。

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
├─ Step 5: audit-agent (sonnet, 前台) → 校验
└─ Step 6: local-agent (sonnet, 前台) → 中译本 metadata 回填
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
# 调 download-agent;agent 内部做 search → download → identity verify + 算 year_evidence。
# 主进程只做：拿 verdict、按 verdict 分支（MATCH 继续 / 否则弹给用户）。
if not source_file:
    # slug 反解: {author-surname}-{title}-{year}，year 是末尾 4 位数字 segment
    parts = book_slug.rsplit("-", 1)
    slug_year = int(parts[1]) if parts[1].isdigit() and len(parts[1]) == 4 else None
    # author 通常是首 segment（多 segment 姓如 fausto-sterling 需要更长 prefix，
    # 但单 segment 覆盖绝大多数 case；download-agent 自己用 author+title 模糊匹配，
    # 这里给个起手 hint 即可）
    body = parts[0]
    body_parts = body.split("-")
    expected_author = body_parts[0]
    expected_title = " ".join(body_parts[1:])

    result = Agent("quasi:download-agent", foreground=True, prompt=f"""\
kind: book
items:
  - slug: {book_slug}
    expected_author: {expected_author}
    expected_title: {expected_title}
output_dir: sources/
""")

    item = result.per_item[0]
    if item.status == "ok":
        source_file = item.path        # agent 已 mv tmp → final
    elif item.status in ("year_mismatch", "year_ambiguous"):
        # 把 year_evidence 整块原样递给用户（含 tmp_path），让用户拍板：
        # 1) 改 slug 中的 year 重跑（slug 重命名 → 触发 download-agent 重新 finalize）
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
# 只回填中译本 / 中文版本 metadata,全外挂写进 .quasi/audit/translations.json
# (by_book + by_douban_id),不动 book frontmatter。
# local-agent 幂等:audit needs_backfill 已基于 by_book[slug] 判定,已查过的书不会再跑。
Agent("quasi:local-agent", foreground=True,
      prompt=f"path: {output_dir}\nmode: cndouban")

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
| Step 6 | `.quasi/audit/translations.json#by_book[slug]` | 已存在 entry(verdict found/none)则 local-agent 跳过 |

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

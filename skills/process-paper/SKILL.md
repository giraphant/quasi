---
name: quasi:process-paper
description: >
  Use when the user says "处理这篇论文", "process paper", "跑这篇 paper",
  "summarize this paper", or wants to process a single academic paper
  (search → download → analyse) into vault/papers/{slug}.md.
---

# Process Paper — 单论文处理

## 任务

搜索、下载和分析用户提供的论文。

## 输入

从用户请求中归一化出以下输入:

- `doi`,或
- `slug`(`sources/{slug}.pdf` 已存在时),或
- `title + author`
- `translate`:可选布尔值

`slug` canonical 格式:`{author-surname}-{short-title}-{year}`（全库唯一,
与 process-author Phase 4 落地的 `vault/papers/{slug}.md` 同名空间）。

## 状态

- 无 paper manifest。
- 主进程 owns state:`.quasi/papers/{slug}.search.json` 和最终成功/失败报告。
- `vault/papers/{slug}.md` 存在表示 analyse 已完成。

## Agent / Helper 合同

- `search-agent` 只返回 `picked/candidates/localisations`,不写文件。
- `download-agent` 负责 fetch + inspect + accept,成功后返回稳定 `sources/{slug}.pdf`。
- `analyse-agent` 只写 `vault/papers/{slug}.md`;audit escalated 时由本 skill 触发一次重做。

## 硬约束

- 单论文流程，无并行后台 agent，无 Glob 轮询。
- 多篇论文则每篇论文一个 agent。

## 工作流

```
主进程 (dispatcher)
├─ Step 0: ENSURE METADATA + SOURCED
│   ├─ 若 --slug 且 sources/{slug}.pdf 已存在 → 跳过 search/download
│   │   ├─ 若 vault/papers/{slug}.md 存在 → 读 frontmatter 拿 metadata
│   │   └─ 否则 → search-agent 返回 metadata,主进程可写 `.quasi/papers/{slug}.search.json` 缓存
│   └─ 否则 → search-agent 返回 metadata + download-agent (kind=paper, items=[1])
├─ Step 1: analyse-agent (type=B, 前台) → vault/papers/{slug}.md
└─Step 2: audit-agent (前台) → 校验 + 一次重做循环
```

## 执行流程

```python
args = parse_args()  # --doi / --slug / --title+--author / --translate
project = "$CLAUDE_PROJECT_DIR"

# Step 0: ENSURE METADATA + SOURCED
if args.slug and Glob(f"sources/{args.slug}.pdf"):
    slug = args.slug
    if exists(f"vault/papers/{slug}.md"):
        # 已有 vault 文件 → frontmatter 拿 metadata（题目/作者/年/doi/journal）
        paper_meta = read_frontmatter(f"vault/papers/{slug}.md")
    else:
        # 没 vault 文件 → search-agent 只返回 metadata；落盘缓存由本 skill 写。
        search = Agent("quasi:search-agent", foreground=True, prompt=f"""\
task: fetch metadata for paper with slug {slug}
context:
  kind: paper
  slug: {slug}                         # search-agent 从 slug 反解 author/title/year
constraints:
  count: 1
""")
        paper_meta = search.picked
        write_json(f".quasi/papers/{slug}.search.json", search)
    source_pdf = f"sources/{slug}.pdf"
else:
    # 完整 search + download 路径
    search = Agent("quasi:search-agent", foreground=True, prompt=f"""\
task: find this paper by {'doi=' + args.doi if args.doi else 'title+author=' + args.title + ' / ' + args.author}
context:
  kind: paper
{'  doi: ' + args.doi if args.doi else '  title: ' + args.title + chr(10) + '  author: ' + args.author}
constraints:
  count: 1
""")
    paper_meta = search.picked
    slug = paper_meta["slug"]
    write_json(f".quasi/papers/{slug}.search.json", search)

    # download-agent kind=paper, items=[1]
    download_result = Agent("quasi:download-agent", foreground=True, prompt=f"""\
kind: paper
items:
  - slug: {slug}
    expected_author: {paper_meta['authors'][0] if paper_meta.get('authors') else ''}
    expected_title: {paper_meta['title']}
    identifiers:
      doi: {paper_meta.get('doi', '')}
output_dir: sources/
""")
    item = download_result.per_item[0]
    if item["status"] != "ok":
        report(f"download failed for {slug}: {item.get('verdict_note', 'no details')}"); return
    source_pdf = item["path"]

# Step 1: ANALYSE
output_path = f"vault/papers/{slug}.md"
if not exists(output_path):
    analyse = Agent("quasi:analyse-agent", foreground=True,
                    prompt=f"""\
type: B
title:   {paper_meta['title']}
authors: {paper_meta['authors']}
year:    {paper_meta['year']}
journal: {paper_meta.get('journal', '')}
doi:     {paper_meta.get('doi', '')}
input:   {source_pdf}
output:  {output_path}
topic:   {args.topic if args.topic else paper_meta.get('topic', '')}
""")
    if analyse.status == "failed":
        report(f"analyse-agent failed for {slug}"); return

# Step 2: AUDIT (always-on, cheap)
audit = Agent("quasi:audit-agent", foreground=True, prompt=f"path: {output_path}")
if audit.audit_result.escalated:
    for item in audit.audit_result.escalated:
        Agent("quasi:analyse-agent", foreground=True, prompt=f"""\
type: B
title:   {paper_meta['title']}
authors: {paper_meta['authors']}
year:    {paper_meta['year']}
journal: {paper_meta.get('journal', '')}
doi:     {paper_meta.get('doi', '')}
input:   {source_pdf}
output:  {output_path}
topic:   {args.topic if args.topic else paper_meta.get('topic', '')}
overwrite: true
reason:  audit escalated {item.kind}: {item.reason}
""")
    audit = Agent("quasi:audit-agent", foreground=True, prompt=f"path: {output_path}")
    if audit.audit_result.escalated:
        report(f"audit still escalated for {output_path} after one regeneration pass"); return
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 0 search | `.quasi/papers/{slug}.search.json` | 存在则跳过 search-agent |
| Step 0 download | `sources/{slug}.pdf` | 存在则跳过 download-agent |
| Step 1 | `vault/papers/{slug}.md` | 存在则跳过 analyse-agent |
| Step 2 | 无 —— 幂等 | 上次 audit clean 时几乎无成本 |

## 输出

```
sources/{paper-slug}.pdf                            ← 原 PDF
.quasi/papers/{paper-slug}.search.json              ← search 结果缓存
vault/papers/{paper-slug}.md                        ← 最终输出
processing/translations/{paper-slug}-zh.pdf         ← 可选翻译
```

paper-slug 与 process-author Phase 4 / process-topic 共享全库扁平命名
空间 (`{author-surname}-{short-title}-{year}`)。

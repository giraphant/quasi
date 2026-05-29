---
name: quasi:process-paper
description: Use when the user wants to search, download, and analyse a single academic paper from a DOI, title, author, or existing source file.
---

# Process Paper — 论文处理

## 任务

搜索、下载和分析用户提供的论文。

## 输入

从用户请求中归一化出以下输入:

- `doi`,或
- `slug`(`sources/{slug}.pdf` 或 `sources/{slug}.txt` 已存在时),或
- `title + author`
- `translate`:可选布尔值

`slug` canonical 格式:`{author-surname}-{short-title}-{year}`（全库唯一,
与 process-author Phase 4 落地的 `vault/papers/{slug}.md` 同名空间）。

## 状态

- 无 paper manifest。
- 主进程 owns state:`.quasi/papers/{slug}.search.json` 和最终成功/失败报告。
- `vault/papers/{slug}.md` 存在表示 analyse 已完成。

## Agent / Helper 合同

- `search-agent` 只返回 `picked/candidates/localisations`,不写文件。picked 的 `oa_url`/`url` 传给 download-agent。
- `download-agent` 负责 fetch + inspect + accept,成功后返回稳定 `sources/{slug}.pdf` 或 `sources/{slug}.txt`。PDF 优先;ScienceDirect PDF 被浏览器中间页拦住时允许 `.txt` 正文兜底。接收 `oa_url`/`url` 作为 hint URL。
- `analyse-agent` 只写 `vault/papers/{slug}.md`;输入可为 `.pdf` 或 `.txt`;audit escalated 时由本 skill 触发一次重做。
- `analyse-agent` 按 paper 目标结构写出完整分析和可靠 metadata。
- 事实 metadata (`title/authors/year/journal/doi`) 必须由 search/frontmatter/PDF 证据传入或核读获得。

## 硬约束

- 单论文流程，无并行后台 agent，无 Glob 轮询。
- 多篇论文则每篇论文一个 agent。

## 工作流

```
主进程 (dispatcher)
├─ Step 0: ENSURE METADATA + SOURCED
│   ├─ 若 --slug 且 sources/{slug}.pdf 或 sources/{slug}.txt 已存在 → 跳过 search/download
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

existing_pdf = f"sources/{args.slug}.pdf" if args.slug and Glob(f"sources/{args.slug}.pdf") else None
existing_txt = f"sources/{args.slug}.txt" if args.slug and Glob(f"sources/{args.slug}.txt") else None
existing_source = existing_pdf or existing_txt

# Step 0: ENSURE METADATA + SOURCED
if args.slug and existing_source:
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
    source_file = existing_source
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
      oa_url: {paper_meta.get('oa_url', '')}
      url: {paper_meta.get('url', '')}
output_dir: sources/
""")
    item = download_result.per_item[0]
    if item["status"] != "ok":
        report(f"download failed for {slug}: {item.get('verdict_note', 'no details')}"); return
    source_file = item["path"]

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
input:   {source_file}
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
input:   {source_file}
output:  {output_path}
topic:   {args.topic if args.topic else paper_meta.get('topic', '')}
overwrite: true
reason:  audit escalated {item.kind}: {item.reason}
""")
    audit = Agent("quasi:audit-agent", foreground=True, prompt=f"path: {output_path}")
    if audit.audit_result.escalated:
        report(f"audit still escalated for {output_path} after one regeneration pass"); return

# Step 3: OPEN IN MARPLE (best-effort UX)
# Open the final paper page if Marple CLI is available. This must never fail the workflow;
# on failure, print the manual command and continue.
Bash(f"/opt/homebrew/bin/marple-cli open '{output_path}' || marple-cli open '{output_path}' || echo 'Marple open skipped; run: marple-cli open {output_path}'")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 0 search | `.quasi/papers/{slug}.search.json` | 存在则跳过 search-agent |
| Step 0 download | `sources/{slug}.pdf` 或 `sources/{slug}.txt` | 存在则跳过 download-agent；两者都存在时优先 `.pdf` |
| Step 1 | `vault/papers/{slug}.md` | 存在则跳过 analyse-agent |
| Step 2 | 无 —— 幂等 | 上次 audit clean 时几乎无成本 |

## 输出

```
sources/{paper-slug}.pdf 或 sources/{paper-slug}.txt       ← 原 PDF 或 ScienceDirect 正文兜底
.quasi/papers/{paper-slug}.search.json                    ← search 结果缓存
vault/papers/{paper-slug}.md                              ← 最终输出
processing/translations/{paper-slug}-zh.pdf               ← 可选翻译
```

paper-slug 与 process-author Phase 4 / process-topic 共享全库扁平命名
空间 (`{author-surname}-{short-title}-{year}`)。

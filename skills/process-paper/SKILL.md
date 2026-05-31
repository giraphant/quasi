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
- `year_hint`:可选,用于 Step 0 rg fuzzy recall
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
├─ Step 0: LOCAL DUPLICATE/RESUME RECALL + METADATA/SOURCE
│   ├─ exact local: vault/papers/{slug}.md / sources/{slug}.pdf|txt / .quasi/papers/{slug}.search.json
│   ├─ exact miss → rg fuzzy recall (`vault/papers`, `sources`, `.quasi/papers`) → inspect frontmatter/cache/source evidence
│   └─ 无 high-confidence completed/source/cache 候选时 → search-agent + download-agent
├─ Step 1: analyse-agent (type=B, 前台) → vault/papers/{slug}.md
└─Step 2: audit-agent (前台) → 校验 + 一次重做循环
```

## 执行流程

```python
args = parse_args()  # --doi / --slug / --title+--author / --translate
project = "$CLAUDE_PROJECT_DIR"

# Step 0: LOCAL RECALL + METADATA/SOURCE
# 先查本地成果/缓存/source: vault/papers/{slug}.md、sources/{slug}.pdf|txt、
# .quasi/papers/{slug}.search.json。exact miss 后用 DOI/author/year/title keywords
# 在 vault/papers、sources、.quasi/papers 做 rg fuzzy recall;只高置信复用,不要盲目跳过。
local = find_local_paper_state(args)

if local.high_confidence:
    slug = local.slug
    paper_meta = local.metadata
    source_file = local.pdf or local.txt
    if local.vault_path:
        report(f"已有论文页面,无需重复处理: {local.vault_path}"); return
elif local.candidates:
    report_candidate_list(local.candidates, note="rg fuzzy recall only; do not blindly skip")

if local.high_confidence and source_file:
    # high-confidence source/cache candidate but no vault output: skip download;
    # 若 metadata cache/frontmatter 足够,直接 analyse;只有缺必要 metadata 时才 search-agent。
    if not paper_meta or missing_required_metadata(paper_meta):
        search = Agent("quasi:search-agent", foreground=True, prompt=f"kind: paper\nslug: {slug}\nmetadata only")
        paper_meta = search.picked
        write_json(f".quasi/papers/{slug}.search.json", search)

if not local.high_confidence:
    # 本地没有 completed/source/cache high-confidence 候选时,才完整 search + download。
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
| Step 0 | local recall: `vault/papers/{slug}.md` / `sources/{slug}.pdf|txt` / `.quasi/papers/{slug}.search.json`; exact miss 后 `rg fuzzy recall` | 在 search/download/analyse 前确认是否已完成或已有 source/cache;PDF 优先,cache 只补 metadata,多候选只列证据 |
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

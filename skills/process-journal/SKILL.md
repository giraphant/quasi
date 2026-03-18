---
name: quasi:process-journal
type: workflow
description: >
  Use when the user says "处理期刊", "journal scan", or wants to scan,
  download, and analyze a journal issue end-to-end.
  Flat agent dispatch: scan-agent, download-agent, analyze-agent ×N, synthesis-agent.
argument-hint: "<journal-name> [--threshold <score>]"
---

# Process Journal — 期刊处理

抓取 → 评分 → 下载 → 分析 → 综合。扁平 agent 调度。

## 调用方式

```
/quasi:process-journal {journal-name} [--threshold 7.0]
```

## ⚠ 硬约束

- **禁止用 TaskOutput 检查后台 agent**：会报 "No task found"，导致卡住
- **必须用 Glob 轮询输出文件**来判断完成
- 后台 agent 完成时会自动通知，但 Glob 是唯一可靠的兜底
- **每篇论文独立 dispatch 一个 analyze-agent**：禁止把多篇论文合并到一个 agent 调用中。一篇 = 一个 Agent() 调用。
- **Dispatcher context 卫生**：
  - Glob 轮询只关注完成数 vs 总数，不要逐一列举文件名
  - 后台 agent 完成通知是冗余信息，收到后不需要额外处理
  - 每个阶段完成后不要回顾前序输出，关键状态已在磁盘上

## 编排架构

```
主进程 (dispatcher)
├─ Step 1: scan-agent (opus, 前台) → scan.md
├─ Step 2: download-agent (sonnet, 前台) → PDFs
├─ Step 3: 主进程读 scan.md → 匹配 PDF → 待分析列表
├─ Step 4: analyze-agent ×N (opus, 后台) → Glob 轮询
└─ Step 5: synthesis-agent (opus, 前台) → synthesis.md
```

## 执行流程

```python
journal_name = parse_args()
threshold = 7.0

# 1. SCAN
if not exists(f"vault/journals/{journal_name}-scan.md"):
    Agent("quasi:scan-agent", foreground=True,
          prompt=f"journal_name: {journal_name}, journal_full_name: ..., "
                 f"output_path: vault/journals/{journal_name}-scan.md")

# 2. ACQUIRE
Agent("quasi:download-agent", foreground=True,
      prompt=f"scan_path: vault/journals/{journal_name}-scan.md, "
             f"threshold: {threshold}, output_dir: /tmp/{journal_name}-pdfs/, "
             f"analysis_dir: vault/journals/{journal_name}/")

# 3. 确定待分析列表
scan = Read(f"vault/journals/{journal_name}-scan.md")
pdfs = Glob(f"/tmp/{journal_name}-pdfs/*.pdf")
existing = Glob(f"vault/journals/{journal_name}/*.md")
to_analyze = match_and_filter(scan, pdfs, existing, threshold)

# 4. ANALYZE
for paper in to_analyze:
    Agent("quasi:analyze-agent", background=True,
          prompt=f"type: B, title: {paper.title}, doi: {paper.doi}, "
                 f"input: /tmp/{journal_name}-pdfs/{paper.slug}.pdf, "
                 f"output: vault/journals/{journal_name}/{paper.slug}.md, topic: ...")

while not all_done:
    sleep(30)

# 5. SYNTHESIZE
if not exists(f"vault/journals/{journal_name}-synthesis.md"):
    Agent("quasi:synthesis-agent", foreground=True,
          prompt=f"source_name: ..., analysis_dir: vault/journals/{journal_name}/, "
                 f"output_path: vault/journals/{journal_name}-synthesis.md, "
                 f"reading_list_path: vault/journals/{journal_name}-reading-list.md, topic: ...")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 1 | `{name}-scan.md` | 存在则跳过 |
| Step 4 | `{name}/{doi}.md` | 存在则跳过 |
| Step 5 | `{name}-synthesis.md` | 存在则跳过 |

## 目录结构

```
vault/journals/{journal-name}-scan.md
vault/journals/{journal-name}-synthesis.md
vault/journals/{journal-name}-reading-list.md
vault/journals/{journal-name}/
└── {slug}.md
/tmp/{journal-name}-pdfs/
└── *.pdf
```

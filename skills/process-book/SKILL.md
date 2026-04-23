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
/quasi:process-book {book-name}
```

`{book-name}` 为 kebab-case。源文件应在 `sources/{book-name}.epub` 或 `.pdf`。

## ⚠ 硬约束

- **禁止用 TaskOutput 检查后台 agent**：TaskOutput 会报 "No task found"，导致卡住
- **必须用 Glob 轮询输出文件**：检查 `{output_dir}/ch*.md` 数量来判断完成
- 后台 agent 完成时会自动通知，但如果错过通知，Glob 是唯一可靠的检查方式
- **每个文本独立 dispatch 一个 analyze-agent**：禁止把多章合并到一个 agent 调用中。一章 = 一个 Agent() 调用。
- **Dispatcher context 卫生**：
  - Glob 轮询只关注完成数 vs 总数，不要逐一列举文件名
  - 后台 agent 完成通知是冗余信息，收到后不需要额外处理
  - 每个阶段完成后不要回顾前序输出，关键状态已在磁盘上

## 编排架构

```
主进程 (dispatcher)
├─ Step 1: extract-agent (sonnet, 前台) → 提取+验证+修复
├─ Step 2: 主进程读 manifest.json → 筛选章节
├─ Step 3: analyze-agent ×N (opus, 后台并行) → Glob 轮询
├─ Step 4: overview-agent (opus, 前台)
└─ Step 5: synthesis-agent (可选, KB 更新)
```

## 执行流程

```python
# 0. 读参数
book_name = parse_args()
source_file = Glob("sources/{book_name}.epub|.pdf")
chapters_dir = f"processing/chapters/{book_name}/"

# 1. EXTRACT（一次调用完成提取+验证+修复）
if not exists(f"{chapters_dir}/manifest.json"):
    result = Agent("quasi:extract-agent", foreground=True,
                   prompt=f"source_file: {source_file}, chapters_dir: {chapters_dir}")
    if result.status == "failed":
        report("需人工检查"); return

# 2. 读取章节清单（全部章节，不筛选）
manifest = Read(f"{chapters_dir}/manifest.json")
selected = manifest.chapters
output_dir = "vault/handbooks/" or "vault/monographs/" + book_name

# 3. 并行分析
for ch in selected:
    if not exists(f"{output_dir}/ch{ch.num:02d}-{ch.slug}.md"):
        Agent("quasi:analyze-agent", background=True,
              prompt=f"type: A, book_title: ..., ch_num: {ch.num}, "
                     f"input: {chapters_dir}/{ch.file}, "
                     f"output: {output_dir}/ch{ch.num:02d}-{ch.slug}.md, topic: ...")

while Glob(f"{output_dir}/ch*.md").count < len(selected):
    sleep(30)

# 4. 概览
if not exists(f"{output_dir}/00-overview.md"):
    Agent("quasi:overview-agent", foreground=True,
          prompt=f"output_dir: {output_dir}, book_title: ..., topic: ...")

print(f"Done: {len(selected)} chapters, overview generated")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 1 | `{chapters_dir}/manifest.json` | 存在则跳过 |
| Step 3 | `ch{NN}-*.md` | 存在则跳过该章 |
| Step 4 | `00-overview.md` | 存在则跳过 |

## 目录结构

```
sources/{book-name}.epub|.pdf
processing/chapters/{book-name}/
├── manifest.json
└── *.txt
vault/handbooks/{book-name}/     ← 或 vault/monographs/
├── 00-overview.md
└── ch{NN}-{title}.md
```

output_dir 规则：Handbook/编著 → `handbooks/`，专著 → `monographs/`

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
# 0. 确定规范 slug
book_name = parse_args()                    # 用户输入，可能不完整
source_file = Glob("sources/{book_name}.epub|.pdf")

# 从源文件中确认书籍的作者（姓氏）、简短标题、出版年份
# 方法不限：读首页/版权页、查 EPUB 元数据、翻目录、用 search.py 搜索等
# 构造规范 slug: {author_surname}-{short_title}-{year}（全小写 kebab-case）
# 示例: "shew-against-technoableism-2023"
# 如果 slug 与 book_name 不同，后续所有路径使用 slug
book_slug = derive_slug(source_file)        # 伪代码，agent 自行实现
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
output_dir = "vault/handbooks/" or "vault/monographs/" + book_slug

# 3. 并行分析
# slot 格式："01".."99" 真章节 / "00a".."00z" 前言 / "99a".."99z" 后记 / "{N}b".."{N}z" 章间插曲
# 根据 slot 推导人类可读的 chapter_label 传给 analyze-agent：
#   slot 纯数字 N       → chapter_label = f"第{int(slot)}章"
#   slot 以 "00" 开头   → chapter_label = "前言"（或根据 title：Foreword/Preface/Introduction）
#   slot 以 "99" 开头   → chapter_label = "后记"（或根据 title：Afterword/Epilogue/Appendix）
#   slot 形如 "{N}{x}" → chapter_label = f"第{N}章（附）"
for ch in selected:
    if not exists(f"{output_dir}/ch{ch.slot}-{ch.slug}.md"):
        Agent("quasi:analyze-agent", background=True,
              prompt=f"type: A, book_title: ..., slot: {ch.slot}, chapter_label: {chapter_label}, "
                     f"input: {chapters_dir}/{ch.filename}, "
                     f"output: {output_dir}/ch{ch.slot}-{ch.slug}.md, topic: ...")

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
| Step 3 | `ch{slot}-*.md` | 存在则跳过该章 |
| Step 4 | `00-overview.md` | 存在则跳过 |

## 目录结构

```
sources/{book-name}.epub|.pdf          ← 用户输入的原始文件名
processing/chapters/{book-slug}/       ← 规范 slug: {author}-{title}-{year}
├── manifest.json
└── *.txt
vault/handbooks/{book-slug}/           ← 或 vault/monographs/
├── 00-overview.md
└── ch{slot}-{title}.md                ← slot 见 manifest.json（"01".."99"/"00a"/"99a"/...）
```

output_dir 规则：Handbook/编著 → `handbooks/`，专著 → `monographs/`

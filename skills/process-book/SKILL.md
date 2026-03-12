---
name: quasi:process-book
type: workflow
description: >
  Composite skill: processes a book from EPUB/PDF to structured summaries.
  Main process dispatches extract + N parallel analysis agents + monitor/overview agent.
  Use when the user says "处理这本书", "跑一下这本handbook", "总结这本".
argument-hint: "[book-name]"
---

> **路径约定**：本技能引用其他技能的脚本时，基于系统提供的 base directory 拼接。例如 `../extract/scripts/X.py` → `python3 {base_directory}/../extract/scripts/X.py`。

# Process Book — 书籍处理（复合技能）

从 EPUB/PDF 到结构化摘要的完整流程。主进程直接调度，轮询与概览委托给监控代理。

## 调用方式

```
/quasi:process-book {book-name}
```

`{book-name}` 为 kebab-case 名称。源文件应在 `sources/{book-name}.epub` 或 `.pdf`。

## ⚠ 架构约束（必读）

**Agent 工具不支持嵌套**：由 Agent 工具派发的子代理**没有 Agent 工具**，只有 Read/Write/Edit/Glob/Grep/Bash 等基础工具。因此：
- ❌ coordinator 模式无效（coordinator 无法再派子代理）
- ❌ 子代理内用 Task 工具无效（Task 只能跑 Bash，无法用 Claude 工具）
- ✅ **主进程用 Agent 工具直接并行派发分析代理**（已有 allow 权限，不弹提示）

## 编排模式：主进程直接调度 + 监控代理

**上下文优化策略**：
- 主进程只做轻量调度（读 manifest、筛选、派发），不读章节内容
- 分析代理自己读模板和章节文本（不在主进程展开）
- **轮询和概览委托给"监控+概览"代理**——在子代理上下文里完成，不污染主进程

```
主进程 (dispatcher, 轻量)
│
├─ Step 1: extract (Bash)                         [前台]
├─ Step 2: 读 manifest + 筛选章节 + 确认          [主进程, ~2 次工具调用]
├─ Step 3: 派发 N 个分析代理 (Agent ×N)           [后台, 分批]
├─ Step 4: 派发"监控+概览"代理 (Agent ×1)         [前台, 阻塞等待]
└─ Step 5: kb-update (可选)                       [前台]
```

---

## Step 1: 提取章节（extract）

**调度方式**：主进程直接执行 Bash 命令（1 次工具调用）

```bash
# EPUB
python3 ../extract/scripts/process_epub.py \
    sources/{book-name}.epub processing/chapters/{book-name}/

# PDF（默认 toc-level 1）
python3 ../extract/scripts/split_chapters.py \
    sources/{book-name}.pdf --output-dir processing/chapters/{book-name}/
```

**⚠ TOC level**：Handbook 类 PDF 的目录通常 level 1 = Part、level 2 = Chapter。默认切分可能把整个 Part 合为一个文件。**如果产出文件数远少于预期章节数，用 `--toc-level 2` 重新切分**。

**⚠ PDF 碎片化**：脚注密集的人文类 PDF 可能过度切分（>100 片段）。替代方案：
- 手动检查切分结果，删除碎片保留完整章节
- 或跳过提取，让分析代理直接读 PDF 指定页范围

### 断点续跑
`processing/chapters/{book-name}/manifest.json` 存在 → 跳过 Step 1。

---

## Step 2: 筛选章节（主进程）

**主进程自己做**（轻量操作，~2 次工具调用）：

1. 读取 `processing/chapters/{book-name}/manifest.json`
2. 根据主题（从 CLAUDE.md §1.3 获取 topic）评估每章相关性：
   - **跳过**：纯索引、致谢、封面、目录、版权页、contributor biographies 等无分析价值的文件
   - **选中**：与 topic 相关的实质章节
3. 用 Glob 检查 `{output_dir}/ch{NN}-*.md` 是否已存在（断点续跑），从待分析列表中移除已完成的
4. 向用户报告选中章节列表和已跳过的章节，**等待确认后继续**

**上下文开销**：1 次 Read（manifest）+ 1 次 Glob（已有产出）+ 文本输出。

---

## Step 3: 并行派发分析代理

**调度方式**：主进程用 Agent 工具直接派发，每个 `run_in_background: true`

**分批策略**：每批最多 5 个后台代理，一次性发出（同一条消息中多个 Agent 调用）。超过 5 个时分批，但**不需要等上一批完成再发下一批**——直接连续发即可，API 会自行排队。

**分析代理 prompt 模板**（主进程为每章填入元数据后发出）：

```
你是学术文本分析代理。

重要规则：禁止在一条 Bash 命令中使用 &&、||、;、管道 |。

步骤：
1. 读取分析模板：{base_directory}/../analyze/prompts/text-analysis.md
2. 选用 A 类（书籍章节）元数据格式，填入以下值：
   - preamble: {preamble}
   - topic: {topic}
   - book_title: {book_title}
   - editors: {editors}
   - publisher: {publisher}
   - year: {year}
   - book_short_name: {book_short_name}
   - ch_num: {ch_num}
   - chapter_title: {chapter_title}
   - author: {author}
   - input_instruction: 读取 processing/chapters/{book-name}/{chapter_file}
   - extra_sections: ""
3. 读取章节文本文件
4. 按模板生成完整分析
5. 写入 {output_dir}/ch{NN}-{title-slug}.md
```

**上下文开销**：每个 Agent dispatch ~5 行 prompt + 完成后 ~1 行通知。N 章 ≈ 6N 行。

---

## Step 4: 监控 + 概览代理

**调度方式**：1 个前台 Agent（opus），阻塞等待

**关键设计**：轮询和概览生成都在这个子代理的上下文里完成，主进程不参与。

**prompt 模板**：

```
你是书籍处理的监控与概览代理。

重要规则：禁止在一条 Bash 命令中使用 &&、||、;、管道 |。

任务分两阶段：

阶段 1 — 等待分析完成：
  - 目标：{output_dir}/ 下应有 {expected_count} 个 ch*.md 文件
  - 用 Glob 检查 "{output_dir}/ch*.md" 的文件数量
  - 如果数量不足，等待 60 秒后再次检查（用 Bash 的 sleep 60）
  - 重复直到数量达标，或超过 30 分钟后报告未完成的章节

阶段 2 — 生成概览：
  - 读取 {output_dir}/ 下所有 ch*.md 文件
  - 生成 {output_dir}/00-overview.md
  - 概览包含：
    - 全书信息（标题、编者、出版社、年份）
    - 各章核心论点概要（按 Part 分组）
    - 关键概念索引表
    - 与"{topic}"的关联分析
    - 高价值章节推荐（标注星级）

完成后报告：已完成 N 章确认 + 概览生成状态。
```

**上下文开销（主进程侧）**：1 次 dispatch + 1 次返回结果 ≈ 10 行。

---

## Step 5: 更新知识库（可选）

由用户决定是否执行。参见 `quasi:synthesize` 的「知识库更新」模式。

---

## 主进程完整执行流程

```python
# 伪代码 — 主进程只做调度

# 0. 确定参数
book_name = parse_args()  # kebab-case
source_file = find("sources/{book_name}.epub|.pdf")
chapters_dir = f"processing/chapters/{book_name}/"
output_dir = determine_output_dir(book_name)
#   Handbook/编著 → vault/handbooks/{book_name}/
#   单一作者专著 → vault/monographs/{book_name}/

# 1. EXTRACT [Bash, 前台]
if not exists(f"{chapters_dir}/manifest.json"):
    Bash("python3 ../extract/scripts/... {source_file} {chapters_dir}")

# 2. SELECT [主进程, 轻量]
manifest = Read(f"{chapters_dir}/manifest.json")
existing = Glob(f"{output_dir}/ch*.md")
selected = filter_relevant(manifest) - already_done(existing)
# → 向用户报告选中列表，等待确认

# 3. DISPATCH [Agent × N, 后台, 分批]
for batch in chunks(selected, 5):
    for ch in batch:
        Agent(
            description=f"Analyze ch{ch.num} {ch.short_title}",
            model="opus",
            run_in_background=True,
            prompt=analyze_prompt(ch)  # 只含元数据+路径，不含章节内容
        )

# 4. MONITOR + OVERVIEW [Agent × 1, 前台]
Agent(
    description="Monitor and generate overview",
    model="opus",
    prompt=monitor_overview_prompt(
        output_dir=output_dir,
        expected_count=len(selected) + len(existing_ch_files),
        topic=topic,
        book_info=book_info
    )
)

# 5. KB UPDATE [可选]
if user_requests:
    Agent(kb_update_prompt, model="opus")

# 6. 报告完成
print(f"Done: {total} chapters analyzed, overview generated")
```

## 断点续跑汇总

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 1 | `processing/chapters/{book-name}/manifest.json` | 存在则跳过提取 |
| Step 2 | — | 主进程自动 Glob 排除已完成章节 |
| Step 3 (逐章) | `{output_dir}/ch{NN}-*.md` | 已存在的不派发 |
| Step 4 | `{output_dir}/00-overview.md` | 存在则跳过监控+概览 |
| Step 5 | — | 用户手动决定 |

## 目录结构

```
sources/{book-name}.epub|.pdf            <- 源文件
processing/chapters/{book-name}/        <- 提取的章节文本
├── manifest.json
└── *.txt
vault/handbooks/{book-name}/            <- Handbook/编著
├── 00-overview.md
└── ch{NN}-{title}.md
vault/monographs/{book-name}/           <- 单一作者专著
├── 00-overview.md
└── ch{NN}-{title}.md
```

**output_dir 选择规则**：
- Handbook、Oxford/Cambridge/Routledge 手册、编著论文集 → `vault/handbooks/{book-name}/`
- 单一作者或少数共同作者的专著 → `vault/monographs/{book-name}/`

## 核心原则

1. **主进程直接调度**：不用 coordinator（因 Agent 嵌套不可用）
2. **上下文最优**：主进程只处理元数据，轮询+概览委托给监控代理
3. **每章 1 个 Agent**，`model: "opus"`，`run_in_background: true`
4. **分批派发**：每批 ≤5 个，连续发出不等待
5. **完成检查用 Glob**：不用 TaskOutput（避免导入子代理 transcript）
6. **从 CLAUDE.md §1.3 获取 preamble/topic 参数**
7. **分析代理自读模板和章节**：主进程只传路径和元数据

---
name: quasi:process-journal
type: workflow
description: >
  Composite skill: acquires papers from a journal scan report, analyzes them, and
  synthesizes findings. Subagent-driven: main process only dispatches 3 coordinator
  agents. Use when the user says "处理期刊", "journal scan".
argument-hint: "<journal-name> [--threshold <score>]"
---

# Process Journal — 期刊处理（复合技能）

从已有评分报告出发 → 获取全文 → 逐篇分析 → 综合报告。主进程只做 dispatcher。

## 调用方式

```
/quasi:process-journal {journal-name} [--threshold 7.0]
```

`{journal-name}` 为 kebab-case（如 `british-journal-of-sociology`）。

## 前置条件

1. **reeder 已配置**：期刊已添加、抓取、评分
2. 评分报告已生成：`vault/journals/{journal-name}-scan.md`

## 编排模式：子代理驱动

**核心原则**：主进程只做 dispatcher，不做循环、不读分析产出、不管下载细节。所有重活交给 coordinator 子代理，每个 coordinator 有独立的上下文预算。

```
主进程 (dispatcher, ~4 次工具调用)
│
├─ Phase 1: SCAN（前置，用户通过 reeder 完成，不在本技能范围）
├─ Phase 2: download-coordinator  [前台, 等待完成]
├─ Phase 3: analyze-coordinator   [前台, 等待完成]
└─ Phase 4: synthesis-agent       [前台, 等待完成]
```

**主进程禁止做的事**：
- 循环调用 download.py（交给 download-coordinator）
- 循环派发 analyze agents（交给 analyze-coordinator）
- 读取分析产出 .md 文件（只用 Glob 检查数量）
- 解析 scan.md 提取 DOI 列表（coordinator 自己读取和解析）
- 手动构造 analyze prompt（coordinator 按模板派发）

---

## Phase 1: SCAN（前置，通过 reeder）

不在本技能范围。用户通过 reeder CLI 完成。产出 `vault/journals/{journal-name}-scan.md`。

---

## Phase 2: ACQUIRE（download-coordinator）

**调度方式**：1 个前台子代理（opus）

**子代理 prompt 模板**：

```
你是文献下载协调代理。任务：从期刊评分报告中下载所有高分论文。

步骤：
1. 读取 vault/journals/{journal-name}-scan.md
2. 提取所有平均分 >= {threshold} 的论文（默认 7.0），收集其 DOI
3. 对每个 DOI，检查 vault/journals/{journal-name}/{doi-slug}.md 是否已存在
   - 已存在 → 跳过（已分析过）
4. 对每个需下载的 DOI：
   python3 quasi/skills/download/scripts/download.py \
       --doi "{doi}" --output-dir /tmp/{journal-name}-pdfs/ --filename {doi-slug}
   - doi-slug 格式：将 DOI 中的 / 替换为 _（如 10.1111/1468-4446.12918 → 10_1111_1468-4446_12918）
   - 成功 → 记录 {doi: pdf_path}
   - 失败 → 记录 {doi: "failed"}，继续下一篇
   - 下载间隔至少 5 秒
5. 完成后报告：N 篇成功下载、M 篇失败、K 篇已有分析（跳过）。
   列出所有成功下载的 {doi: pdf_path} 映射。
```

**主进程收到**：下载统计摘要

### 断点续跑
`vault/journals/{journal-name}/{doi-slug}.md` 存在 → 跳过。coordinator 自动处理。

---

## Phase 3: ANALYZE（analyze-coordinator）

**调度方式**：1 个前台子代理（opus）

**子代理 prompt 模板**：

```
你是论文分析协调代理。任务：对所有已下载的期刊论文启动并行分析。

⚠ 硬约束：
- 只分析已成功下载PDF的论文 — 禁止对仅有摘要或下载失败的论文生成分析
- 必须检查 PDF 文件实际存在于 /tmp/{journal-name}-pdfs/ 才能启动分析
- 如果 PDF 不存在，跳过该论文，不要自行生成内容

期刊全名：{Journal Full Name}（从 scan.md 标题或首行提取，用于 B 类模板的 source_name）

步骤：
1. 用 Glob 扫描 /tmp/{journal-name}-pdfs/*.pdf，获取所有待分析 PDF 列表
2. 对每个 PDF，检查 vault/journals/{journal-name}/{doi-slug}.md 是否已存在
   - 已存在 → 跳过
3. 对每个需分析的 PDF，启动 1 个后台子代理（Task tool）：
   - subagent_type: "general-purpose"
   - model: "opus"
   - run_in_background: true
   - prompt: |
       读取 quasi/skills/analyze/prompts/text-analysis.md 模板，
       选用 B 类（期刊论文）元数据格式，根据模板中的占位符填入相应值，
       生成分析写入 vault/journals/{journal-name}/{doi-slug}.md。
       值来源：
       - preamble/topic: 从 CLAUDE.md §1.3 获取
       - 论文元数据 (title, author, year, doi, source): 从 scan.md 提取
       - input_instruction: "读取 {pdf_path}"
       - extra_sections: ""

4. 等待完成：
   用 Glob 检查 vault/journals/{journal-name}/*.md 数量。
   每 30 秒检查一次，直到全部完成（数量 = 已有 + 新分析）。

5. 完成后报告：N 篇分析完成、M 篇跳过。
```

**主进程收到**：分析完成统计

### 断点续跑
`vault/journals/{journal-name}/{doi-slug}.md` 存在 → 跳过。coordinator 自动处理。

---

## Phase 4: SYNTHESIZE（synthesis-agent）

**调度方式**：1 个前台子代理（opus），Phase 3 完成后启动

**子代理 prompt 模板**：

```
你是期刊综合代理。任务：为 {journal-name} 生成综合报告和阅读列表。

步骤：
1. 聚合参考文献：
   python3 quasi/skills/synthesize/scripts/aggregate_refs.py \
       vault/journals/{journal-name}/ \
       --output vault/journals/{journal-name}-reading-list.md

2. 读取 vault/journals/{journal-name}/ 下所有 .md 分析文件

3. 生成综合报告 vault/journals/{journal-name}-synthesis.md，格式如下：

   ---
   type: journal-synthesis
   journal: "{Journal Full Name}"
   papers_analyzed: {N}
   topic: "技术、AI、媒介与具身化"
   ---
   # {Journal Full Name} — 综合报告

   ## 主题聚类
   （将分析的论文按主题归类，识别交叉主题）

   ## 理论贡献汇总
   | 概念/框架 | 提出者 | 来源论文 | 与本项目关联 |
   |-----------|--------|---------|-------------|

   ## 方法论特征
   （该期刊在本主题下的方法偏好、经验/理论比例）

   ## 与本项目主题的关联
   （"技术、AI、媒介与具身化"各子题的具体关联）

   ## 关键发现
   （跨论文的重要发现和趋势）

   ## 可引用观点
   （综述写作时可直接使用的关键论述，含 DOI 出处）

   ## 推荐精读
   （按优先级排序，附推荐理由）
```

**主进程收到**：synthesis.md 路径（确认成功）

---

## 主进程完整执行流程

```python
# 伪代码 — 主进程只做调度

# 0. 读参数
journal_name = parse_args()  # kebab-case
threshold = parse_threshold(default=7.0)
scan_path = f"vault/journals/{journal_name}-scan.md"
topic = "技术、AI、媒介与具身化"
preamble = "这是人文/理论类文本，不是实证研究。不要寻找"数据"、"样本量"或"因果推断"。聚焦于理论论证、概念贡献和学术对话。"

# 1. 前置检查
assert exists(scan_path), "请先通过 reeder 生成评分报告"

# 2. ACQUIRE [前台]
Task(download_coordinator_prompt, foreground=True)  # → 下载统计

# 3. ANALYZE [前台]
Task(analyze_coordinator_prompt, foreground=True)  # → 分析完成统计

# 4. SYNTHESIZE [前台]
if not exists(f"vault/journals/{journal_name}-synthesis.md"):
    Task(synthesis_agent_prompt, foreground=True)  # → synthesis.md

# 5. 报告完成
print(f"Done: vault/journals/{journal_name}-synthesis.md")
```

## 断点续跑汇总

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 1 | `vault/journals/{name}-scan.md` | 前置条件，必须存在 |
| Phase 2 | `vault/journals/{name}/{doi-slug}.md` | 已有分析则跳过下载 |
| Phase 3 | `vault/journals/{name}/{doi-slug}.md` | 存在则跳过该论文 |
| Phase 4 | `vault/journals/{name}-synthesis.md` | 存在则跳过（`--force` 重生成） |

## 目录结构

```
vault/journals/
├── {journal-name}-scan.md              ← Phase 1 评分排名（前置）
├── {journal-name}/                     ← Phase 3 逐篇分析
│   └── {doi-slug}.md
├── {journal-name}-synthesis.md         ← Phase 4 综合报告
└── {journal-name}-reading-list.md      ← Phase 4 阅读列表

/tmp/{journal-name}-pdfs/               ← Phase 2 临时 PDF 存储
└── {doi-slug}.pdf
```

## 核心原则

1. **主进程只做 dispatcher**：~4 次工具调用，不做循环
2. **每个 coordinator 有独立上下文**：互不污染
3. **每篇论文 1 个分析代理**，`model: "opus"`
4. **完成检查用 Glob**：不用 TaskOutput（避免导入子代理 transcript）
5. **scan.md 是输入源**：coordinator 自己读取和解析
6. **从 CLAUDE.md §1.3 获取 preamble/topic 参数**

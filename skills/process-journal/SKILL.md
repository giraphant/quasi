---
name: quasi:process-journal
type: workflow
description: >
  Composite skill: end-to-end journal processing from OpenAlex fetch to synthesis.
  Subagent-driven: main process dispatches 4 coordinator agents (scan, download, analyze, synthesize).
  Use when the user says "处理期刊", "journal scan".
argument-hint: "<journal-name> [--threshold <score>]"
---

> **路径约定**：本技能引用其他技能的脚本时，基于系统提供的 base directory 拼接。例如 `../download/scripts/X.py` → `python3 {base_directory}/../download/scripts/X.py`。

# Process Journal — 期刊处理（复合技能）

端到端流程：抓取期刊 → 评分 → 获取全文 → 逐篇分析 → 综合报告。主进程只做 dispatcher。

## 调用方式

```
/quasi:process-journal {journal-name} [--threshold 7.0]
```

`{journal-name}` 为期刊名称（如 "Critical Inquiry"）或 kebab-case（如 `critical-inquiry`）。

## 前置条件

1. **CLAUDE.md §1.3 已配置**：包含 Research Interests
2. **无需外部工具**：所有功能已集成

## ⚠ 架构约束

**Agent 工具不支持嵌套**：由 Agent 工具派发的子代理没有 Agent 工具。因此：
- Phase 1/2 的 coordinator **自己完成所有工作**（不尝试派发子代理）
- Phase 3 的分析**由主进程直接用 Agent 工具并行派发**（不经 coordinator）

## 编排模式：子代理 + 主进程直接调度混合

```
主进程 (dispatcher)
│
├─ Phase 1: scan-coordinator       [前台] - 抓取+评分+生成scan.md（自己完成）
├─ Phase 2: download-coordinator   [前台] - 下载PDF（自己完成）
├─ Phase 3: 主进程读 scan.md + Glob PDFs → 派发 N 个分析代理 [后台]
│           → 派发"监控"代理 [前台, 等待完成]
└─ Phase 4: synthesis-agent        [前台] - 综合报告
```

---

## Phase 1: SCAN（scan-coordinator）

**调度方式**：1 个前台子代理（opus）

**子代理 prompt 模板**：

```
你是期刊扫描协调代理。任务：抓取期刊论文 → 评分 → 生成报告。

步骤：
1. 抓取论文：
   python3 skills/process-journal/scripts/fetch_papers.py \
       --journal-name "{journal_name}" \
       --days-back 3650 \
       --output /tmp/{journal-name}-papers.json

2. 读取 CLAUDE.md §1.3 获取 research_interests（### Research Interests 行）

3. 逐篇评分（自己完成，不派发子代理）：
   - 读取 skills/process-journal/prompts/score-single-paper.md
   - 对每篇论文：填入 paper 元数据 + research_interests，生成评分
   - 输出：/tmp/{journal-name}-scores/{paper_id}.json
   - 检查已有评分，跳过已完成的论文

4. 生成报告：
   python3 skills/process-journal/scripts/generate_scan_report.py \
       --papers /tmp/{journal-name}-papers.json \
       --scores /tmp/{journal-name}-scores/ \
       --output vault/journals/{journal-name}-scan.md
```

**主进程收到**：scan.md 路径（确认成功）

### 断点续跑
`vault/journals/{journal-name}-scan.md` 存在 → 跳过 Phase 1。coordinator 内部也会跳过已有评分。

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
   python3 ../download/scripts/download.py \
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

## Phase 3: ANALYZE（主进程直接调度）

**调度方式**：主进程读 scan.md + Glob PDFs → 派发 N 个分析代理（后台）+ 1 个监控代理（前台）

⚠ 硬约束：
- 只分析已成功下载PDF的论文 — 禁止对仅有摘要或下载失败的论文生成分析
- 必须检查 PDF 文件实际存在于 /tmp/{journal-name}-pdfs/ 才能启动分析

**主进程步骤**：

1. 读取 vault/journals/{journal-name}-scan.md，提取所有高分论文元数据
2. 用 Glob 扫描 /tmp/{journal-name}-pdfs/*.pdf，获取已下载 PDF 列表
3. 用 Glob 检查 vault/journals/{journal-name}/{doi-slug}.md，排除已分析的
4. 对每篇需分析的论文，用 Agent 工具派发 1 个后台分析代理：
   - subagent_type: "general-purpose"
   - model: "opus"
   - run_in_background: true
   - prompt: 读取 ../analyze/prompts/text-analysis.md 模板，
     选用 B 类（期刊论文）元数据格式，根据模板中的占位符填入相应值，
     生成分析写入 vault/journals/{journal-name}/{doi-slug}.md。
     值来源：
     - preamble/topic: 从 CLAUDE.md §1.3 获取
     - 论文元数据 (title, author, year, doi, source): 从 scan.md 提取
     - input_instruction: "读取 {pdf_path}"
     - extra_sections: ""
5. 分批派发（每批 ≤5），连续发出不等待
6. 派发 1 个前台"监控"代理（opus），阻塞等待：
   - 用 Glob 检查 vault/journals/{journal-name}/*.md 数量
   - 每 60 秒检查一次，直到全部完成
   - 完成后报告：N 篇分析完成、M 篇跳过

### 断点续跑
`vault/journals/{journal-name}/{doi-slug}.md` 存在 → 主进程自动排除。

---

## Phase 4: SYNTHESIZE（synthesis-agent）

**调度方式**：1 个前台子代理（opus），Phase 3 完成后启动

**子代理 prompt 模板**：

```
你是期刊综合代理。任务：为 {journal-name} 生成综合报告和阅读列表。

步骤：
1. 聚合参考文献：
   python3 ../synthesize/scripts/aggregate_refs.py \
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

# 1. SCAN [前台] - 如果 scan.md 不存在
if not exists(scan_path):
    Agent(scan_coordinator_prompt, foreground=True, model="opus")  # → scan.md

# 2. ACQUIRE [前台]
Agent(download_coordinator_prompt, foreground=True, model="opus")  # → 下载统计

# 3. ANALYZE [主进程直接调度]
scan_data = Read(scan_path)  # 提取高分论文元数据
pdfs = Glob("/tmp/{journal_name}-pdfs/*.pdf")
existing = Glob(f"vault/journals/{journal_name}/*.md")
to_analyze = filter(pdfs, existing)

for batch in chunks(to_analyze, 5):
    for paper in batch:
        Agent(analyze_prompt(paper), background=True, model="opus")

Agent(monitor_prompt(expected=len(to_analyze)+len(existing)), foreground=True, model="opus")

# 4. SYNTHESIZE [前台]
if not exists(f"vault/journals/{journal_name}-synthesis.md"):
    Agent(synthesis_agent_prompt, foreground=True, model="opus")  # → synthesis.md

# 5. 报告完成
print(f"Done: vault/journals/{journal_name}-synthesis.md")
```

## 断点续跑汇总

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 1 | `vault/journals/{name}-scan.md` | 存在则跳过 Phase 1 |
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

1. **Phase 1/2 coordinator 自己完成所有工作**：不尝试派发子代理（Agent 嵌套不可用）
2. **Phase 3 由主进程直接派发分析代理**：每篇 1 个 Agent，`model: "opus"`，`run_in_background: true`
3. **监控代理处理轮询**：主进程不做循环，委托前台监控代理 Glob 检查
4. **完成检查用 Glob**：不用 TaskOutput（避免导入子代理 transcript）
5. **scan.md 是输入源**：Phase 1 coordinator 和主进程都从中读取
6. **从 CLAUDE.md §1.3 获取 preamble/topic 参数**
7. **分批派发**：每批 ≤5 个分析代理，连续发出不等待

---
name: quasi:citation-snowball
type: workflow
description: >
  Composite skill: builds a topic-focused reading corpus by chaining citations
  from a seed paper, round by round, until saturation. Subagent-driven:
  main process dispatches 1 seed-coordinator + R round-coordinators +
  1 synthesis-agent (~3+R tool calls). Each round-coordinator has fresh context
  and handles search, download, analyze dispatch, citation extraction, and
  manifest update internally.
  Use when the user says "滚雪球", "citation chain", "expand references".
argument-hint: "<topic-slug> --seed <doi-or-pdf> --topic \"<description>\""
---

> **路径约定**：本技能引用其他技能的脚本时，基于系统提供的 base directory 拼接。例如 `../search/scripts/X.py` → `python3 {base_directory}/../search/scripts/X.py`。

# Citation Snowball — 引用滚雪球（复合技能）

从种子论文出发，沿引用链逐轮扩展主题相关文献，直到饱和。

## 调用方式

```
/quasi:citation-snowball {topic-slug} --seed {doi} --topic "{description}"
```

## ⚠ 架构约束

**Agent 工具不支持嵌套**：由 Agent 工具派发的子代理没有 Agent 工具。因此：
- seed-coordinator 和 round-coordinator **自己顺序完成分析工作**（不尝试派发子代理）

## 编排模式：子代理驱动（round-coordinator）

**核心原则**：主进程只做 dispatcher + 循环判断，不做搜索、不做下载、不派发分析代理、不读分析产出。所有重活交给 coordinator 子代理，每个 coordinator 有独立的上下文预算。

```
主进程 (dispatcher, ~3+R 次工具调用, R = 轮数)
│
├─ seed-coordinator           [前台, opus]
│   └─ Download seed → analyze(opus) → extract citations → create manifest
│
├─ round-coordinator ×R       [前台, opus, 逐轮串行]
│   ├─ metadata search → download → dispatch analyze agents(opus, 后台) → Glob-poll
│   ├─ Read analysis .md → extract citations from snowball-extra section → deduplicate
│   └─ Add new refs to manifest (round+1, discovered) → return new_refs_count
│
├─ (主进程检查: new_refs_count == 0 ? 停止 : 下一轮)
│
└─ synthesis-agent            [前台, opus]
    └─ Read all analysis .md → generate synthesis report + reading list
```

**主进程禁止做的事**：
- 调用 search.py / download.py（交给 seed/round-coordinator）
- 循环派发 analyze agents（交给 round-coordinator）
- 读取分析产出 .md 文件（只用 Glob 检查数量；round-coordinator 内部读取并提取引用）
- 手动解析引用、去重、更新 manifest 条目（coordinator 自己处理）
- 直接执行 snowball-extra 模板的引用提取逻辑（coordinator 内部完成）

---

## Phase 0: SEED（seed-coordinator）

**调度方式**：1 个前台子代理（opus）

**子代理 prompt 模板**：

```
你是引用滚雪球种子处理代理。任务：处理种子论文并初始化 manifest。

参数：
- topic_slug: {topic-slug}
- topic: {topic}
- seed: {doi-or-pdf}
- output_dir: vault/journals/{topic-slug}
- pdf_dir: /tmp/{topic-slug}-pdfs

步骤：

1. 创建目录：
   mkdir -p vault/journals/{topic-slug}
   mkdir -p /tmp/{topic-slug}-pdfs

2. 获取种子论文 PDF：
   - 如果 seed 是 DOI：
     python3 ../download/scripts/download.py \
       --doi "{doi}" --output-dir /tmp/{topic-slug}-pdfs/ --filename seed
   - 如果 seed 是本地 PDF 路径：直接使用

3. 分析种子论文（自己直接完成，不派发子代理）：
   读取 ../analyze/prompts/text-analysis.md 模板，
   选用 B 类（论文）元数据格式，根据模板中的占位符填入相应值，
   读取种子论文 PDF，生成分析写入 vault/journals/{topic-slug}/{seed-key}.md。
   值来源：
   - preamble/topic: 从 CLAUDE.md §1.3 获取
   - 论文元数据 (title, author, year, doi, source): 从种子论文 PDF 或用户输入获取
   - input_instruction: 读取 {pdf_path}
   - extra_sections: 读取 ../analyze/prompts/snowball-extra.md，
     将 {{topic}} 替换为 "{topic}"

4. 从分析产出中提取引用：
   读取 vault/journals/{topic-slug}/{seed-key}.md 的
   「直接相关的{topic}引用文献」段落（由 snowball-extra 模板生成）。
   解析每条引用的 Author, Year, Title, DOI。

5. 创建 manifest.json：
   写入 vault/journals/{topic-slug}/manifest.json，格式见下方 Manifest 结构。
   - 种子论文：round=0, status="refs_extracted"
   - 提取的引用：round=1, status="discovered"

6. 对新发现的引用批量查元数据：
   python3 ../search/scripts/search.py metadata \
     --manifest vault/journals/{topic-slug}/manifest.json --all

7. 报告：种子论文标题、提取到 N 条引用、manifest 路径。
```

**主进程收到**：manifest.json 路径 + 新引用数量

### 断点续跑
`vault/journals/{topic-slug}/manifest.json` 存在且 `rounds_completed >= 0` → 跳过 Phase 0。

---

## Phase 1-N: EXPAND（round-coordinator ×R）

**调度方式**：每轮 1 个前台子代理（opus），串行执行。主进程逐轮启动，根据返回的 `new_refs_count` 决定是否继续。

**子代理 prompt 模板**（每轮一份，由主进程填入当前轮号）：

```
你是引用滚雪球第 {round_num} 轮协调代理。任务：处理本轮所有待处理论文，
分析后提取新引用，更新 manifest。

参数：
- topic_slug: {topic-slug}
- topic: {topic}
- preamble: {preamble}
- round_num: {round_num}
- manifest_path: vault/journals/{topic-slug}/manifest.json
- output_dir: vault/journals/{topic-slug}
- pdf_dir: /tmp/{topic-slug}-pdfs

步骤：

1. SEARCH — 查元数据：
   读取 manifest.json，找到本轮 (round={round_num}, status="discovered") 的条目。
   python3 ../search/scripts/search.py metadata \
     --manifest vault/journals/{topic-slug}/manifest.json --all
   更新 manifest 中的 doi, oa_url, abstract 等字段。

2. ACQUIRE — 下载 PDF：
   python3 ../download/scripts/download.py \
     --manifest vault/journals/{topic-slug}/manifest.json --batch --retry-wayback
   成功 → status="acquired"；失败 → status="failed"。
   每次下载后更新 manifest。

3. ANALYZE — 并行分析：
   ⚠ 只分析 status="acquired"（有完整PDF）的论文，禁止分析仅有摘要或下载失败的论文。

   对每篇 status="acquired" 的本轮论文，自己顺序完成分析（不派发子代理）：
   - 检查 vault/journals/{topic-slug}/{key}.md 是否已存在（跳过已完成）
   - 读取 ../analyze/prompts/text-analysis.md 模板
   - 选用 B 类（论文）元数据格式，根据模板中的占位符填入相应值
   - 读取 PDF：{pdf_path}
   - 生成分析写入 vault/journals/{topic-slug}/{key}.md
   - 值来源：
     - preamble/topic: 从 CLAUDE.md §1.3 获取
     - 论文元数据 (title, author, year, doi, source): 从 manifest 获取
     - input_instruction: 读取 {pdf_path}
     - extra_sections: 读取 ../analyze/prompts/snowball-extra.md，
       将 {{topic}} 替换为 "{topic}"

4. EXTRACT — 提取新引用：
   对每篇本轮完成分析的 .md 文件：
   a) 读取「直接相关的{topic}引用文献」段落
   b) 解析 Author, Year, Title, DOI
   c) 与 manifest 已有论文去重（按 author+year+title 归一化）
   d) 新引用加入 manifest：round={round_num+1}, status="discovered",
      cited_by=[当前论文 key]
   e) 更新当前论文：status="refs_extracted", new_refs_found={count}

6. METADATA — 对新引用查元数据：
   如果有新引用：
   python3 ../search/scripts/search.py metadata \
     --manifest vault/journals/{topic-slug}/manifest.json --all

7. 更新 manifest：rounds_completed = {round_num}

8. 报告（必须包含以下字段供主进程解析）：
   - round: {round_num}
   - papers_analyzed: N
   - new_refs_count: M
   - total_papers: K
```

**主进程收到**：`new_refs_count`（新发现引用数）。`new_refs_count == 0` → 饱和，跳到 SYNTHESIZE。

### 断点续跑
manifest 中 `rounds_completed >= N` → 跳过第 N 轮及之前。round-coordinator 内部也跳过已有 analysis .md 的论文。

---

## Phase FINAL: SYNTHESIZE（synthesis-agent）

**调度方式**：1 个前台子代理（opus），所有轮次完成后启动

**子代理 prompt 模板**：

```
你是引用滚雪球综合代理。任务：为 "{topic}" 生成综合报告和阅读清单。

读取以下文件：
- vault/journals/{topic-slug}/manifest.json（获取全部论文列表和元数据）
- vault/journals/{topic-slug}/*.md（所有分析产出）

生成两个文件：

1. vault/journals/{topic-slug}-synthesis.md
---
type: snowball-synthesis
topic: "{topic}"
topic_slug: "{topic-slug}"
rounds: {R}
papers_total: {N}
---
# {topic} — 引用滚雪球综合报告

## 主题概览
（本滚雪球覆盖的研究领域全貌）

## 核心文献图谱
（按引用关系梳理文献间的脉络，标注 seed → round 1 → round 2 ...）

## 理论聚类
（将文献按理论取向/研究问题分组，每组总结核心论点）

## 关键概念谱系
| 概念 | 提出者 | 年份 | 来源 | 定义/用法 |
|------|-------|------|------|----------|

## 研究前沿与缺口
（尚未充分探讨的问题、矛盾观点、可能的研究方向）

## 与本项目主题的关联
（与"技术、AI、媒介与具身化"各子题的具体关联）

## 可引用观点
（综述写作时可直接使用的关键论述，含出处）

2. vault/journals/{topic-slug}-reading-list.md
---
type: reading-list
topic: "{topic}"
---
# {topic} — 阅读清单

## 核心文献（必读）
| # | 作者 | 年份 | 标题 | 引用关系 | 分析链接 |
|---|------|------|------|---------|---------|

## 扩展文献（推荐）
（本轮未获取全文但值得关注的文献）

## 引用网络统计
- 种子论文：{seed}
- 总轮数：{R}
- 已分析论文：{N}
- 被引最多的论文 Top 5
```

**主进程收到**：synthesis.md + reading-list.md 路径

---

## 主进程完整执行流程

```python
# 伪代码 — 主进程只做调度 + 循环判断

# 0. 读参数
topic_slug, seed, topic_desc = parse_args()
manifest_path = f"vault/journals/{topic_slug}/manifest.json"
topic = "技术、AI、媒介与具身化"          # 从 CLAUDE.md §1.3
preamble = "这是人文/理论类文本，不是实证研究。不要寻找"数据"、"样本量"或"因果推断"。聚焦于理论论证、概念贡献和学术对话。"  # 从 CLAUDE.md §1.3
MAX_ROUNDS = 5

# Phase 0: SEED [前台]
if not exists(manifest_path):
    result = Task(seed_coordinator_prompt, foreground=True, model="opus")
    # → manifest.json created, new_refs_count returned

# Phase 1-N: EXPAND [前台, 逐轮串行]
manifest = read_json(manifest_path)
start_round = manifest["rounds_completed"] + 1

for round_num in range(start_round, start_round + MAX_ROUNDS):
    # 检查是否还有 discovered 条目
    discovered = [p for p in manifest["papers"].values()
                  if p["round"] == round_num and p["status"] == "discovered"]
    if len(discovered) == 0:
        break  # 饱和

    result = Task(
        round_coordinator_prompt(round_num=round_num),
        foreground=True,  # 前台，等待完成
        model="opus"
    )
    # → result 包含 new_refs_count

    new_refs_count = parse_result(result, "new_refs_count")
    if new_refs_count == 0:
        break  # 饱和

    manifest = read_json(manifest_path)  # 刷新

# Phase FINAL: SYNTHESIZE [前台]
Task(synthesis_agent_prompt, foreground=True, model="opus")

# 报告完成
print(f"Done: {rounds} rounds, {total} papers, synthesis + reading-list generated")
```

---

## Manifest 格式

```json
{
  "topic": "{topic description}",
  "topic_slug": "{topic-slug}",
  "seed_doi": "{doi}",
  "output_dir": "vault/journals/{topic-slug}",
  "pdf_dir": "/tmp/{topic-slug}-pdfs",
  "rounds_completed": 0,
  "papers": {
    "<key>": {
      "title": "...",
      "authors": "...",
      "year": 2023,
      "doi": "10.xxx/yyy",
      "cited_by": ["key-of-citing-paper"],
      "status": "discovered|metadata_found|acquired|abstract_only|refs_extracted|failed",
      "round": 1,
      "pdf_path": null,
      "analysis_path": null,
      "oa_url": null,
      "wayback_url": null,
      "abstract": null,
      "new_refs_found": 0
    }
  }
}
```

**Status 流转**：`discovered` → `metadata_found` → `acquired`/`abstract_only`/`failed` → `refs_extracted`
（分析完成后直接由 round-coordinator 读取产出、提取引用、设为 `refs_extracted`）

---

## 断点续跑汇总

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 0 (Seed) | `vault/journals/{topic-slug}/manifest.json` | 存在且 `rounds_completed >= 0` 则跳过 |
| Phase 1-N (Expand) | manifest `rounds_completed` | `>= N` 则跳过第 N 轮；轮内已有 .md 的论文也跳过 |
| Phase FINAL (Synthesize) | `vault/journals/{topic-slug}-synthesis.md` | 存在则跳过（`--force` 重生成） |

---

## 目录结构

```
/tmp/{topic-slug}-pdfs/                    <- 下载的 PDF（临时）
vault/journals/{topic-slug}/
├── manifest.json                          <- 唯一状态源
├── {key}.md                               <- 逐篇分析
└── ...
vault/journals/{topic-slug}-synthesis.md   <- 综合报告
vault/journals/{topic-slug}-reading-list.md <- 阅读清单
```

---

## 核心原则

1. **主进程只做 dispatcher + 循环判断**：~3+R 次工具调用（R=轮数），不做搜索/下载/分析
2. **每个 round-coordinator 有独立上下文**：一轮的全部工作（搜索+下载+分析+引用提取）封装在一个 coordinator 里，互不污染
3. **每篇论文 1 个分析代理**，`model: "opus"`
4. **主进程不读分析产出**：只看 manifest + Glob 检查文件数量；round-coordinator 内部读取 .md 提取引用
5. **manifest.json 是唯一状态源**：coordinator 直接读写
6. **饱和即停**：`new_refs_count == 0` 时停止扩展
7. **topic filter 严格**：只收录核心主题文献（snowball-extra 模板要求"标题/内容明确讨论 {topic}"）
8. **从 CLAUDE.md §1.3 获取 preamble/topic 参数**
9. **所有下载用 Python 脚本**：不手动 curl/wget

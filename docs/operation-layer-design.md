# Operation / Workflow / Agent / Bin 设计笔记

状态：**Paper vertical slice 已实现，按同一边界继续扩展**

日期：2026-07-30

范围：这份笔记只负责执行层拆分。Material Loop Protocol 由另一条设计线负责；本文向它提供可调用的 Operation Catalog、handler 合同和分层边界。

## 1. 已确认的核心设计

上层 Graph 调用具名 Operation：

```text
paper.analyse
chapter.analyse
talk.analyse
```

Graph 不再调用一个带 `type: A | B | T` 分支的肥 `analyse-agent`。

三个 Operation 都调用同一个 `analyse-agent`。这个 Agent 只保存 common analyse role；
各 Operation 在运行时注入完整、独立的 Prompt Pack：

```text
Workflow
  └─ paperAnalyse(request)
       ├─ handler: analyse-agent
       ├─ prompt_pack: paper-analysis
       ├─ input_schema: PaperAnalysisRequest
       └─ output_schema: PaperAnalysisReceipt
```

这里没有运行时 Registry：Operation 是源码中的窄函数边界。Operation-specific
knowledge 归 Operation 所有；Workflow 只选择 Operation，不拥有 Paper/Chapter/Talk
的长篇语义指令。Prompt Pack 最终是内嵌、加载还是构建时合成，属于 handler 的物理
实现选择。

## 2. 分层判断规则

判断依据不是代码或 prompt 的长度，而是复杂度的性质。

### Workflow 拥有控制流

满足任一条件的步骤应提升为 Graph node 或 subgraph：

- 结果决定下一个 Operation；
- 有独立 artifact 或 receipt；
- 有自己的失败、重试或恢复路径；
- 可以独立并行；
- 会被多个 Material Loop 复用；
- 有明显费用或外部副作用；
- Reconcile 需要单独判断它是否已完成。

典型内容：

- Operation 选择和顺序；
- fan-out / join；
- OCR、repair、fallback 等恢复边；
- retry budget；
- terminal status；
- audit 后回到哪个 producer。

Claude Workflow 运行中不能向用户提问，所以 human gate 不属于某个 Agent node。Skill
持有用户状态，在 gate 前结束一个 Workflow stage，取得用户决定后再启动下一个 stage。
不能把 `AskUserQuestion` 藏进长 Workflow，也不需要为此自建暂停协议。

### Agent 拥有语义判断

Agent 完成一次边界清楚的、不可完全确定化的判断或转换：

- 判断提取文本是否真实可读；
- 判断下载候选是否为目标版本；
- 分析一篇 Paper 或一个 Chapter；
- 校正多引擎 Talk transcript；
- 综合已有材料；
- 修复已明确诊断的语义问题。

Agent 不拥有业务循环，不选择下一个 Operation，不调用另一个业务 Agent，也不向用户提问。

### Bin 拥有确定执行

Bin 负责可以稳定重放和机器验证的动作：

- 下载、移动和接受文件；
- PDF/text/OCR/章节切分等转换；
- 统计字符和提取结构信号；
- schema validation；
- mechanical repair；
- manifest、hash、路径和格式处理。

Bin 可以提供判断信号，但不必包办最终语义判断。例如字符数是确定值，“正文是否足够可读”仍可由 Agent 结合 preview 判断。

### Contract 不属于任何单个 Handler

Operation 的 request、receipt、artifact、side effect 和 retry policy 是跨实现合同。Agent 与 Bin 都只是 Handler。

## 3. Handler 不能隐藏的性质

Graph 可以不关心 Handler 是 Agent 还是 CLI wrapper，但必须知道 Operation 的执行性质：

```text
OperationSpec
  name
  input_schema
  output_schema
  effect: readonly | writer
  retry: safe | fenced | forbidden
  cost: local | network | paid
  handler
```

这些字段决定超时、重试、并发和恢复行为，不能因统一 Handler Map 而丢失。

Claude 的同-session resume 会从第一个未完成 Agent 起重放后续调用；因此 `writer`
Operation 必须把重复执行当成正常输入条件，用稳定 key、exact output path 和
create/repair 模式先对账 artifact。原生 resume cache 不等于 exactly-once，也不替代
typed receipt。

## 4. 分析前统一 Normalize

所有分析都应接收已经准备好的、可寻址的规范化 artifact，而不是让分析 Agent 自己判断原文件类型并运行转换命令。

```text
Raw Source
  → extract / transcribe / normalize
  → assess
  → NormalizedArtifactRef
  → *.analyse
```

Workflow 传的是 artifact reference，不把大段正文装进 Graph receipt：

```text
NormalizedArtifactRef
  artifact_id
  kind
  path
  media_type
  generation
  producer_receipt
```

对文档定义显式 Workflow 子图，而不是组合 Operation：

```text
document.extract-text
  → command-relay Agent: 调一次 quasi-extract text，返回机器信号
document.assess-readability
  → Agent: 结合 preview 判断 readable / needs_ocr / invalid_source
```

Workflow 消费结果：

```text
extract → assess
  ├─ readable       → paper.analyse / chapter.analyse
  ├─ needs_ocr      → document.ocr → extract → assess
  └─ invalid_source → BLOCKED / FAILED
```

因此：

- 现有确定性 extract/OCR 能力继续复用；
- “长度、乱码、正文质量”不被错误简化成纯确定性规则；
- OCR 恢复边从 `analyse-agent` 移入 Workflow；
- `*.analyse` 只处理已经可读的输入。

Talk 采用同一原则：

```text
media
  → transcribe × engines
  → reconcile transcripts
  → NormalizedTranscriptRef
  → talk.analyse
```

如果 transcript reconciliation 需要独立复用、重试或 generation，就成为独立 Agent Operation；否则可暂时保留在 `talk-analysis` Prompt Pack。

## 5. Common Analyse Role

唯一的 `analyse-agent` 只保留共同执行纪律：

```text
1. 读取 request 指定的 normalized artifact；
2. 只依据实际读取到的证据；
3. 执行注入的 Operation contract；
4. 写入唯一指定的 output；
5. 返回 typed receipt；
6. 不搜索、不 OCR、不重试、不决定下一步。
```

长输出的分段 Write 属于 Handler 内部实现，不进入 Graph。

这里没有三个 analysis Agent，也没有单独的 Executor 层。运行时只有一次 Agent
调用，完整指令由三部分组成：

```text
common analyse role
+ operation-specific Prompt Pack
+ runtime request
```

`analyse-agent` 也不扩张成能执行 download、audit、synthesis 的万能 Agent；这些是不同
Operation，对应其他 Agent role 或 Bin handler。

## 6. 三个 Analyse Prompt Pack

### `paper-analysis`

- Paper 证据纪律与分析方法；
- title/authors/year/journal/DOI metadata 合同；
- 核心论点、理论框架、分节摘要、关键概念和引用结构；
- Paper output schema 与 receipt。

### `chapter-analysis`

- 父书、chapter label/title、book slug；
- chapter authors 的语义识别；
- Chapter 专属 metadata、引用与正文结构；
- Chapter output schema 与 receipt。

### `talk-analysis`

- transcript artifact 的使用规则；
- speaker/themes/时间戳；
- Talk 专属分析与输出结构；
- Talk output schema 与 receipt。

`topic` 与 `## 项目关联` 不属于任何 canonical analysis pack；Topic 关系由 Topic Loop 的 outline、dossier 或 membership 持有。

## 7. 当前 `analyse-agent` 的迁移映射

| 当前职责 | 目标归属 |
| --- | --- |
| A/B/T 分派 | Material Loop 选择具名 Operation |
| 根据类型决定输入和输出路径 | Material Loop |
| PDF → text | extract/normalize Operation |
| 文本可读性判断 | judgement Agent Operation |
| `needs_ocr → OCR → re-analyse` | Workflow |
| 深度阅读与结构化分析 | analyse-agent + Prompt Pack |
| Paper/Chapter/Talk 模板 | 对应 Prompt Pack |
| 长输出分段写入 | analyse-agent 内部 |
| output schema validation | audit/validation Operation |
| topic-specific 项目关联 | Topic Loop |

目标不是把 392 行机械拆成三个文件，而是消除 Agent 内的类型分派和恢复图，使每次 Agent 调用只完成一个明确的语义 Operation。

## 8. `extract-agent` 的初步判断

当前 `extract-agent` 不是简单 CLI wrapper。它内部包含：

```text
extract
  → inspect TOC / choose plan
  → validate chapters
  → OCR or replan
  → repair selected chapters
  → validate again
```

这里同时存在确定执行、语义判断和恢复控制流，后续应拆成 Book Loop 内的 extract subgraph，而不是把整个 Agent 直接改成 Bin。

初步 Operation 划分：

```text
document.extract.run          Bin
document.extract.assess       Agent
document.extract.plan         Agent（仅复杂 TOC 需要）
document.ocr                  Bin
document.extract.repair       Bin
```

Workflow 拥有：

- EPUB/PDF 路由；
- `extract → assess`；
- `needs_ocr → ocr → extract`；
- `fragmented/bad-boundary → replan/repair → assess`；
- 最多几轮以及最终 `COMPLETE | BLOCKED | FAILED`。

Agent 仍负责：

- 复杂 TOC 到 chapter plan 的判断；
- 章节头尾是否截断、串章或只有页眉页脚；
- 系统性失败与局部边界错误的语义诊断。

Paper slice 已验证 `quasi-extract text` 可承担统一 normalise，readability 仍由只读
judgement Agent 判定，OCR 恢复边由 Workflow 持有。下一轮在 Book extract subgraph
逐项核对 EPUB split、chapter manifest、边界修复与 OCR 所需的机器信号，避免重复创建
能力。

## 9. 推进方式：顶层骨架 + Vertical Slice

不需要先写完所有顶层图，也不应在完全没有公共合同的情况下逐个随意拆 Agent。采用 walking skeleton：

1. 只固定 Paper slice 真正需要的最小字段：
   - operation name；
   - input/output artifact path；
   - typed result；
   - writer/readonly 与能否重试；
2. 以 Paper 做第一条端到端 vertical slice：
   - source → prepare-readable-text
   - OCR recovery
   - `paper.analyse`
   - validate/audit
3. 从现有 `analyse-agent` 提取 common analyse role 与 `paper-analysis` Prompt Pack；
4. 写 characterization/contract tests，验证新旧 Paper 产物合同；
5. 扩展到 Chapter/Book，验证 fan-out、join 和 extract subgraph；
6. 扩展到 Talk，验证 transcript reconciliation 与 generation；
7. 再依次审查 download、audit、synthesis、search 等肥 Agent。

每完成一条 vertical slice，就把发现反馈到顶层 Material Protocol；只有跨类型反复出现的概念才提升为公共协议。这样既不会先做一套未经验证的大图，也不会让局部重构产生互不兼容的小协议。

## 10. 当前结果与下一项

Paper vertical slice 已经落实：

- `document.extract-text`、`document.assess-readability` 和 `document.ocr` 使用严格
  request/receipt；
- `paper.analyse` 向同一个 common `analyse-agent` 注入 `paper-analysis/1` envelope；
- born-digital 与 OCR recovery 共享同一个 analyse 接口；
- writer 的 null、取消、超时或畸形 receipt 都按 unknown outcome 阻断，通过 exact
  artifact reconcile 恢复，不能自动重投；
- material disposition 区分 `created / reused / repaired`；
- Claude 运行产物从模块化 `scripts/workflows/` 确定性构建。

下一项是 Book 的 extract/chapter vertical slice：先把现有 `extract-agent` 中的
extract → assess → OCR/replan/repair → reassess 控制流提升进图，再让
`chapter.analyse` 复用同一 common analyse role。Talk 在 Book 证明 fan-out/join 与
chapter artifact 合同后再接入。

## 11. Workflow 源码基本结构

Loop 的三类物理归属已经清楚，可以先固定：

```text
scripts/workflows/
  process-material.entry.mjs
  runtime.mjs
  materials/                    # 各种 Material Loop
    dispatch.mjs
    paper.mjs
    book.mjs

  collections/                  # 聚合多个 Material 的 Loop
    author.mjs

  research/                     # 研究迭代 Loop
    topic.mjs

  operations/                   # Loop 直接调用的 handler 边界
    analyse.mjs
    acquire.mjs
    extract.mjs
    synthesise.mjs
    audit.mjs

workflows/
  process-material.mjs          # 构建生成的唯一 Claude Workflow 入口
```

只创建当前已经运行的 book/paper/author/topic；Talk、Web、Image、Note、Journal 在对应
vertical slice 开始时再加，不预建空文件。

### Loop 文件

`materials/`、`collections/`、`research/` 中的文件拥有：

- 调用哪些 Operation；
- 调用顺序、分支、并行和有限循环；
- recovery edge；
- Reconcile 与 terminal status；
- 子 Loop receipt 的聚合。

例如 `materials/paper.mjs` 可以写：

```text
source.acquire
→ document.extract
→ document.assess
    └─ needs_ocr → document.ocr → document.extract → document.assess
→ paper.analyse
→ artifact.audit
```

### Operation 文件

`operations/` 对应 Loop 可以直接调用的一次 handler 边界。一个 Operation 负责：

- operation name；
- 输入字段；
- Prompt Pack 或 CLI 参数构造；
- 选择语义 Agent，或让窄 command-relay Agent 调一次 exact wrapped CLI；
- typed receipt schema。

它不决定接下来调用谁，也不拥有 retry loop。

例如 `operations/analyse.mjs` 暴露：

```text
paper.analyse
  → analyse-agent + paperAnalysePrompt(request)

chapter.analyse
  → analyse-agent + chapterAnalysePrompt(request)

talk.analyse
  → analyse-agent + talkAnalysePrompt(request)
```

三个 Operation 都调用同一个 `agents/analyse-agent.md`。这个 Agent 只有 common analyse
role；类型差异全部来自 Operation 在 runtime 注入的 Prompt Pack。

`operations/extract.mjs` 可以同时暴露：

```text
document.extract    → wrapped quasi-extract
document.assess     → judgement agent
document.ocr        → wrapped quasi-extract
chapter.plan        → judgement agent
```

Book Loop 决定这些 Operation 如何组成 extract/replan/repair 流程。

### Contract 的物理归属

Contract 是 Loop 与 Operation、Operation 与 Handler 之间交换的数据形状，不是一个必须
单独存在的运行层。第一版把合同放在拥有它的文件旁边：

```text
operations/analyse.mjs
  ├─ PaperAnalyseRequest
  ├─ PaperAnalyseReceipt
  ├─ paperAnalysePrompt()
  └─ paperAnalyse()

materials/paper.mjs
  ├─ PaperLoopRequest
  ├─ PaperLoopReceipt
  └─ processPaper()
```

只有 `ArtifactRef`、terminal status 等合同被三处以上共同使用时，才抽出很小的
`contracts.mjs`；现在不预建 `contracts/` 目录。

依赖方向是：

```text
research / collections
  → materials
    → operations
      → Agent | wrapped CLI
```

如果以后发现一串 Operation 被多个 Loop 原样复用，再新增 `shared/` 放可复用 subloop；
不要提前把 composite flow 塞进 Operation。

# Quasi Material Loop Architecture

状态：**accepted architecture**
日期：2026-07-30

执行合同见 [`material-loop-protocol.md`](material-loop-protocol.md)；Operation / Agent / Bin 的拆分规则见 [`operation-layer-design.md`](operation-layer-design.md)。

## 1. 一句话结构

Quasi 逻辑上是一张 Workflow Universe，但物理上由多个有界业务 Loop 组成。Paper、Book、Talk、Web、Image、Note 是 Material Loop；Author、Journal 是高阶聚合 Loop；Topic 是迭代 Research Loop。所有 Loop 调用具名 Operation，Agent 和 Bin 只是不同 Handler。

## 2. 业务结构

```text
Direct Material Request ───────────────┐
                                      │
Author Loop ───────┐                   │
                   ├─ Material Demand ├─→ MATERIAL LOOP MAP
Journal Loop ──────┘                   │       ├─ Paper Loop
                                      │       ├─ Book Loop
Topic Loop ────────────────────────────┘       ├─ Talk Loop
  ├─ recall / diagnose gaps                   ├─ Web Loop
  ├─ produce demands                          ├─ Image Loop
  ├─ wait for MaterialReceipts                └─ Note Loop
  ├─ update research state                         │
  └─ decide next round                             ▼
                                            OPERATION MAP
                                             ├─ Agent Handler
                                             ├─ Bin Handler
                                             └─ Composite Handler
```

所有 Loop 共同读写：

```text
sources/        processing/        vault/
```

这些目录是持久 artifact 空间，不是另一层 Workflow，也不是一个名为“Material Library”的执行器。

## 3. Loop 分类

### Material Loop

一份具体材料的完整业务生命周期：

```text
reconcile
  → operation
  → reconcile
  → audit
  → bounded repair backedge
  → complete | blocked | failed
```

Material Loop 必须隐藏自己的内部实现，只向上返回 MaterialReceipt。

### Collection Loop

Author 与 Journal 负责发现和维护成员关系：

```text
discover membership
  → Material Loop × N
  → consume MaterialReceipts
  → aggregate synthesis
  → audit
```

它们不能理解 Paper/Book 的下载、OCR 或分析细节。

### Research Loop

Topic 只负责：

```text
recall library
  → diagnose gaps
  → produce material demands
  → wait for child receipts
  → update outline / dossiers / notes
  → continue or synthesize
```

Topic 不处理材料内部步骤，也不把 Web evidence、Paper、Book、Talk 的具体生产链内联进自身。

## 4. Operation 与 Handler

Graph 调用业务目的，不调用物理实现：

```text
paper.analyse
chapter.analyse
talk.analyse
document.ocr
source.fetch
```

每个 Operation 必须暴露影响控制流的性质：

```text
input/output schema
effect: control | readonly | writer
retry: safe | fenced | forbidden
artifact ownership
handler
```

- 需要模糊判断时派 Agent。
- 确定执行优先使用 Bin。
- Graph 明确选择 Operation 和 mode；Agent 不自行选择业务模式或下一条边。

## 5. 物理实现原则

逻辑上允许子图嵌套，物理上不启动子 Workflow runner：

```text
one entry skill
  → one Workflow run
  → same-run JavaScript function calls
  → shared scheduler / concurrency / cancellation boundary
```

当前 `workflows/process-material.mjs` 仍是一个 host-neutral bundle，只使用注入的 `agent`、`parallel`、`phase`、`log`、`args`。只有在跨 Workflow 复用或维护数据证明必要时，才引入源码分片与统一打包；不能让 Claude、Pi、Codex 各自执行不同的图。

## 6. Material Loop Protocol

共同协议必须定义：

```text
request
state
operation spec / receipt
reconcile
audit
repair
terminal MaterialReceipt
```

单份 Material 的终态只有：

```text
complete | blocked | failed
```

`partial` 只属于 Author、Journal、Topic 等 aggregator。

规范与 Paper reference implementation 见 [`material-loop-protocol.md`](material-loop-protocol.md)。

## 7. 类型定位

| 对象 | 类型 | 说明 |
| --- | --- | --- |
| Paper | Material Loop | 第一条 reference implementation |
| Book | Material Loop | 验证 fan-out、join、refill、synthesis 与 repair routing |
| Talk | Material Loop | 验证 generation、昂贵 operation、媒体更新与部分复用 |
| Web | Material Loop | canonical 网页归档；Topic evidence card 是其研究视角派生物，不是网页本体 |
| Image | Material Loop | 后续定义 identity、operations、artifacts、audit |
| Note | Material Loop | imported standalone note 可成为材料；Topic-local note 仍是研究 artifact |
| Author | Collection Loop | 发现作品并消费 MaterialReceipts |
| Journal | Collection Loop | 维护 Paper membership 并消费 MaterialReceipts |
| Topic | Research Loop | 产生需求、等待 receipts、更新研究状态并决定下一轮 |
| Translation | Derivative | 现有 Material 的可选表示，不是新的 Material kind |

## 8. 人闸与状态

- Graph 不直接询问用户。
- Graph 返回 typed `blocked` receipt。
- Skill 展示 gate、取得决定并重新提交。
- 续跑从 `reconcile` 重建，不依赖 JS cursor。
- v0.1 不建设 append-only workflow journal。
- generation/fingerprint 在 Talk 接入前成为必要扩展，但不阻塞 Paper control protocol。

## 9. 实施顺序

```text
1. Material Loop Protocol v0.1
2. Paper Loop
   identify → download → analyse → OCR recovery → audit
3. Book Loop
   fan-out → join → missing chapter refill → synthesis → exact repair routing
4. Talk Loop
   multi-engine → expensive operation → media generation → partial reuse
5. Web / Image / Note
6. Author / Journal
7. Topic
```

前三个 Material Loop 都成立后，才能认为 Protocol 不是 Paper-specific abstraction。

## 10. 明确不做

- 多个 Workflow runner 在运行时互调；
- Agent 启动 Workflow 或替 Skill 提问；
- 让 Author/Journal 理解 Material 内部步骤；
- 让 Topic 内联下载、OCR、分析或 Talk 转写链；
- 把 library 画成一个执行层；
- 在 Paper v0.1 之前建设完整 DAG、event store 或统一 generation；
- 为了目录好看而一次拆出整棵 runtime/registry/contracts 基础设施。

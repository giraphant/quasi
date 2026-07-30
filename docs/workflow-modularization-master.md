# Claude Workflow 模块化主设计

状态：**implementation baseline**

日期：2026-07-30

范围：以 Claude Code 为第一验收宿主，改造 quasi 的共享 host-neutral 业务 Graph、
Operation 与 Agent 合同。Pi / Codex 适配器源码保持只读；它们只作为同一 bundle 的
兼容回归约束，不在本轮重设计或扩展，也不能代替 Claude E2E。

关联文档：

- [`workflow-universe-rfc.md`](workflow-universe-rfc.md)：业务 Loop 全景；
- [`material-loop-protocol.md`](material-loop-protocol.md)：Material 控制协议；
- [`operation-layer-design.md`](operation-layer-design.md)：Workflow / Operation /
  Agent / Bin 分层规则。

官方运行时依据：

- [Dynamic workflows](https://code.claude.com/docs/en/workflows)；
- [Subagent status lines](https://code.claude.com/docs/en/statusline#subagent-status-lines)；
- [Plugin settings / component paths](https://code.claude.com/docs/en/plugins-reference)。

## 1. 最终裁决

Quasi 保留一张逻辑上的 Workflow Universe，但源码按业务所有权拆分。开发源码是正常
ESM；Claude Code 运行时继续只执行一个构建产物：

```text
scripts/workflows/**/*.mjs
       │
       │ deterministic build
       ▼
workflows/process-material.mjs
       │
       │ one Workflow invocation
       ▼
agent · parallel · phase · log · args
```

因此同时满足：

1. 开发时可以按 `materials / collections / research / operations` 维护；
2. Claude 当前 `AsyncFunction` 入口不需要支持 `import/export`；
3. 所有 Loop 仍共享同一个 scheduler、并发、取消与 continuation 边界；
4. 不产生 Claude、Pi、Codex 三份不同的图；
5. 不创建运行时 registry、子 Workflow runner 或完整 event store。

`workflows/process-material.mjs` 是提交入库的唯一运行产物，禁止手改。构建命令必须有
`--check` 模式，逐字验证生成物与源码一致。

### 1.1 Claude 原生运行时边界

Claude Code 官方 Workflow 运行时已经负责：

- 在隔离 JavaScript 环境中保存脚本变量和中间结果；
- 记录每次 `agent()` 的结果，并在同一 Claude session 内支持暂停 / 恢复；
- 用 `phase()`、agent `label` 和可选的 `meta.phases` 提供进度视图；
- 通过 `agent(..., {schema})` 约束结构化结果；
- 提供 `parallel()`，以及适合“上一阶段每完成一项就进入下一阶段”的原生
  `pipeline()`。

因此 quasi 不再自建第二套 Workflow journal、scheduler 或 progress event store。
Typed receipt 仍然必须存在，因为它是业务和 artifact 合同，不是调度器状态。

官方运行时同时明确：

- Workflow 脚本不能直接读写文件或执行 shell；文件与 CLI 都必须由 Agent 完成；
- 运行中不能向用户提问；人工确认必须由 Skill 在两个 Workflow stage 之间持有；
- 最多 16 个 Agent 并发、每次 run 最多 1000 个 Agent；
- 恢复只在同一 session 内成立，退出 Claude Code 后重新运行不是 durable resume。

Claude 原生 `pipeline()` 是可用能力，不是“不支持”。G1 仍只使用当前 bundle 已有的
`agent / parallel / phase / log / args`，原因是这一波要求零行为变化，而且 Paper
walking skeleton 是有恢复边的线性链，`pipeline()` 没有额外价值。以后 Book / Topic
出现真正的逐项多阶段流时，再以 Claude 语义为基线评估采用；不能为了形式统一把线性
writer 链改写成 pipeline，也不能把 pipeline 当成 CLI 执行 primitive。

## 2. 最小源码树

只创建当前已经运行的业务，不预建 Talk、Web、Image、Note、Journal 空壳：

```text
scripts/workflows/
  process-material.entry.mjs
  runtime.mjs
  materials/
    dispatch.mjs
    paper.mjs
    book.mjs
  collections/
    author.mjs
  research/
    topic.mjs
  operations/
    acquire.mjs
    extract.mjs
    analyse.mjs
    synthesise.mjs
    steer.mjs
    audit.mjs

workflows/
  process-material.mjs

scripts/
  build-workflows.mjs
```

目录含义：

- `materials/`：一份 Paper 或 Book 的完整业务 Loop；
- `collections/`：Author 等成员集合 Loop，只消费 Material receipt；
- `research/`：Topic 的迭代研究 Loop；
- `operations/`：Graph 到单个 Handler 的直接边界；
- `runtime.mjs`：统一执行 Operation、超时、typed receipt 校验与 retry policy；
- `process-material.entry.mjs`：装配依赖和顶层 dispatch，不承载业务细节。

跨三个真实调用方重复之前，contract 与所属 Loop / Operation 共置；当前不创建独立的
`contracts/`、`registry/`、`shared/` 目录。

## 3. Operation 的精确定义

一个 Operation 是一次业务动作、一个 Handler、一个 typed receipt：

```text
OperationSpec
  key
  version
  input_schema
  output_schema
  effect: control | readonly | writer
  retry: safe | fenced | forbidden
  cost: local | network | paid
  artifact_ownership
  handler
```

Handler 可以是语义 Agent 或 command-relay Agent，但不能在一次调用里隐藏下一步选择、
恢复回边、fan-out/join 或另一个业务 Operation。

当前 quasi bundle 只使用 `agent / parallel / phase / log / args`；Claude 原生运行时还
提供 `pipeline()`，但同样没有 shell/exec primitive。
因此“Bin Operation”是逻辑能力分类，不表示 Graph 直接启动进程。它的物理路径固定为：

```text
Graph
  → agent(agentType: general-purpose, exact command envelope)
       → one exact public quasi-* CLI command
       → JSON receipt
```

command-relay Agent 不做语义判断、候选选择或恢复；Operation 负责 exact argv、允许的输出
路径和 receipt 校验。不得为此修改 Pi / Codex adapter 或给不同宿主增加不同 primitive。

这意味着：

- `paper.analyse` 可以把 common role、Paper Prompt Pack 和 runtime request 一次交给
  `analyse-agent`；
- `document.extract-text` 是一次逻辑 Bin Operation，物理上由窄 command-relay Agent
  执行一次 `quasi-extract text`；
- `document.assess-readability` 是一次 Agent Operation；
- `document.ocr` 是一次 Bin Operation；
- `extract-text → assess → OCR → extract-text → assess` 属于 Workflow 子图，不叫一个
  composite Operation；
- Agent 不调用另一个业务 Agent，也不自行选择下一条边；
- Operation wrapper 只构造 exact command envelope、校验 receipt，不复制现有
  `quasi-*` CLI 能力。

## 4. Agent 的目标形态

Agent 只保存稳定的共同角色与能力边界。Material-specific 知识由 Operation 在运行时
完整注入。

唯一的 `analyse-agent`：

```text
common analyse role
  + selected operation prompt pack
  + runtime request
  = one agent invocation
```

Common role 只要求：

1. 读取 request 指定的 normalized artifact；
2. 证据只来自实际读取到的内容；
3. 执行注入的 operation contract；
4. 只写 exact output path；
5. 返回 typed receipt；
6. 不搜索、不转 PDF、不 OCR、不重试、不决定下一步。

Operation Prompt Pack：

```text
paper.analyse   → paper-analysis/1
chapter.analyse → chapter-analysis/1
talk.analyse    → talk-analysis/1
```

三者不是三个 Agent。`topic` 和 `## 项目关联` 不属于 canonical material analysis；
它们归 Topic Loop 的 membership / dossier。

同样的规则逐步用于其他肥 Agent：

| 当前 Agent | 目标 |
| --- | --- |
| `download-agent` | acquisition Loop 外移；Agent 只做一次 source identity / edition judgement |
| `extract-agent` | extract / assess / plan / OCR / repair 显式成图；Agent 只做 TOC 与边界语义判断 |
| `audit-agent` | Graph 持有 audit → repair → re-audit；Agent 一次只修 exact path 的允许问题 |
| `steer-agent` | Graph/helper 持有 round、quota、recovery；Agent 只提议或评估一次 |
| `synthesis-agent` | 按 book/author/topic operation 注入模板和预算，不在 Agent 内 mode dispatch |

## 5. Paper walking skeleton

Paper 是第一个 vertical slice。目标不是先实现全部 Material Protocol，而是验证目录、
Operation、单 Agent 注入、恢复边和生成 bundle 能一起成立。

第一轮只宣称新的核心骨架成立：

```text
document.extract-text
→ document.assess-readability
→ document.ocr recovery
→ paper.analyse
```

当前 `download-agent` 和 `audit-agent` 都内藏多步控制流。第一轮通过显式命名的
`paper.download.legacy` 与 `paper.audit.legacy` 兼容调用复用它们，不能把这两个节点
计作已经完成纯 Operation 化，也不能据此宣称 Paper Material Protocol 全部完成。
Acquire 与 Audit 后续各自做 vertical slice 后，再去掉 `.legacy`。

### 5.1 Artifact

```text
raw source          sources/{slug}.pdf
raw text            processing/papers/{slug}/source.txt
OCR source          processing/papers/{slug}/ocr.pdf
OCR text            processing/papers/{slug}/ocr.txt
canonical analysis  vault/papers/{slug}.md
```

旧 `.quasi/temp/{slug}.ocr.pdf` 在迁移期可作为只读 recovery observation 复用，不移动、
不删除；新运行不再写该路径。

### 5.2 Operation sequence

```text
reconcile
  ├─ canonical exists ───────────────────────────────→ paper.audit.legacy
  ├─ recovery source exists → document.extract-text → document.assess-readability
  ├─ raw source exists ─────→ document.extract-text → document.assess-readability
  └─ no source ──────────────────────────────────────→ paper.download.legacy

document.assess-readability
  ├─ readable ───────────────────────────────────────→ paper.analyse
  ├─ needs_ocr + budget ─→ document.ocr ─→ extract-text ─→ assess
  ├─ needs_ocr exhausted ────────────────────────────→ failed
  └─ invalid_source ─────────────────────────────────→ failed

paper.analyse
  ├─ succeeded ──────────────────────────────────────→ paper.audit.legacy
  ├─ known failure ──────────────────────────────────→ failed
  └─ unknown writer outcome ─────────────────────────→ blocked

paper.audit.legacy
  ├─ clean ──────────────────────────────────────────→ complete
  ├─ exact producer escalation + budget → paper.analyse(repair) → audit
  ├─ repair exhausted ───────────────────────────────→ failed
  └─ unknown owner/path ─────────────────────────────→ failed
```

`paper.analyse` 的输入只能是已经被 assessor 判为 readable 的 `.txt`。它的 receipt 不再有
`needs_ocr`。OCR 只由 `document.assess-readability.signal` 的枚举值触发，绝不检查
`notes`、`output` 或错误文本里的 “OCR / scan / 扫描”。

字符数、页数和乱码比例是 Bin 提供的机器信号，不是最终可读性判决。
`document.assess-readability` 必须实际读取分层 preview 或 normalized text，返回：

```text
readable | needs_ocr | invalid_source
```

### 5.3 Writer safety

现有 `retryNull` 不能继续无差别重投所有 Agent：

- `readonly + safe` 可以有界重试；
- `writer` 明确失败后是否可重试由 Operation 声明；
- `writer` 的 null、timeout 或取消未确认一律返回 `blocked`；
- 不能因为某个宿主能发 cancel，就让同一张图在另一个宿主自动重复写；
- Paper slice 先使用新的 operation runner，Book/Topic legacy 行为不在同一步骤大改。

v0.1 没有 lease/fencing，所以 `retry: fenced` 只是未来保留值，Paper Operation 不得
选择它。第一轮的执行表：

| Operation | effect | retry |
| --- | --- | --- |
| `paper.download.legacy` | writer | forbidden |
| `document.extract-text` | writer | safe only after known failure and no live writer |
| `document.assess-readability` | readonly | safe |
| `document.ocr` | writer | forbidden |
| `paper.analyse` | writer | forbidden |
| `paper.audit.legacy` | writer | forbidden |

任何 writer null/timeout/cancel unknown 都直接 blocked；`safe` 也不允许用 null 当成
“已知失败”。

Claude 原生 resume 也不能被误当成 exactly-once：缓存按 Agent 的**启动顺序**回放，
在第一个未完成 Agent 之后启动的所有 Agent 都会重跑，即使它们在暂停前已经完成。
因此每个可能写文件的 Operation 还必须满足：

- request 带稳定 `material_key + operation key + exact output path + mode`；
- Agent 启动前观察 exact output，区分 `create / repair / already-complete`；
- 相同 request 被 replay 时，要么证明 artifact 已完整并返回同一 receipt，要么
  返回 `blocked`，不能盲写；
- 并行 fan-out 的 writer 只能写互不重叠的 exact paths；共享文件必须在 barrier 后由
  单一 writer 更新；
- 原生缓存是同 session 的性能与恢复能力，不是跨 session 的幂等依据。

### 5.4 Compatibility

第一版 `runPaperLoop()` 返回内部 MaterialReceipt；旧 `processPaper()` 暂作兼容 adapter：

```text
complete                                      → status: ok
paper.download_failed                        → status: download_failed
paper.year_mismatch / paper.year_ambiguous    → 原样 legacy year status
paper.analysis_failed                        → status: analysis_failed
paper.ocr_failed                             → status: ocr_failed
paper.audit_escalated / repair_exhausted      → status: audit_escalated
paper.writer_outcome_unknown                  → status: blocked
every branch                                 → material_receipt: full receipt
```

Author、Topic 和 public skills 在同一迁移窗口仍消费旧 status。真实 Claude Workflow
通过后，再让上层直接消费 MaterialReceipt；在此之前不删除 legacy path。

### 5.5 Artifact ownership

| Artifact | Primary producer / owner |
| --- | --- |
| `sources/{slug}.pdf` | `paper.download.legacy`，后续迁至 acquisition Operation |
| `processing/papers/{slug}/source.txt` | `document.extract-text` |
| `processing/papers/{slug}/ocr.pdf` | `document.ocr` |
| `processing/papers/{slug}/ocr.txt` | `document.extract-text` |
| `vault/papers/{slug}.md` | primary `paper.analyse`; `paper.audit.legacy` 只作为受限 secondary mutator |
| `.quasi/temp/{slug}.ocr.pdf` | legacy read-only observation；producer unknown |

## 6. 实现结果与保留 debt

Paper vertical slice 已关闭原清单中的主要安全缺口：

- common `analyse-agent` 在 operation path 使用 exact `Write`，不再依赖不存在的 Edit；
- operation envelope 显式传入，临时产物改为
  `processing/papers/{slug}/...`，不再碰撞 `/tmp/{basename}`；
- analyse、extract、readability、OCR、download、audit receipt 都按 exact
  identity、字段和状态矩阵校验；畸形 writer receipt 是 unknown outcome；
- OCR CLI 的 JSON receipt 保留真实 engine/fallback exit，并以同目录 staging +
  atomic no-replace commit 实现 `--no-clobber`；
- audit clean 同时要求合法 status、零 remaining violations、零 escalations；
- Paper download receipt 保留逐源 attempts 和 actual source，并对 existing target
  先做 identity reconcile；
- 同 run 同一 `material.kind + ":" + canonical slug` 使用一条 promise，identity
  冲突 fail closed。settled promise 在本次 run 生命周期内保留，使稍后出现的重复需求
  仍复用同一结果；它不会跨 Workflow run 持久化。

仍然明确保留的 debt：

1. legacy A/B/T 路径仍有旧分块写法和较宽工具权限，不能据此宣称所有 Agent 已完成
   common-role least privilege；
2. `batch_accept_year` 与完整 acquisition catalog 的统一合同留给 Acquire slice；
3. extract `--pages` 的 manifest/旧 txt 一致性留给 Book Extract slice；
4. 其他 legacy 图的 audit/repair 控制权仍需在各自 vertical slice 收回；Paper 只允许
   一个 legacy composite audit transaction（其中包含 audit-agent 合同要求的最终
   validation），Graph 不再启动第二个并发 audit transaction；
5. scan→OCR、audit repair 以及 pause/resume 仍需真实 Claude Workflow E2E，mock 和
   adapter 回归不能替代。

## 7. 实施波次与文件所有权

### G0：基线与 characterization

- 从当前 dirty bundle 记录行为 trace，不覆盖在途修改；
- 新增 Paper/Book/Author/Topic happy 与 failure/recovery characterization；
- 只增加测试，不改变 runtime 行为。

Owner 只新增 characterization 文件，不编辑 bundle。

### G1：可复现源码与 bundle

- 创建 `scripts/workflows/`；
- 创建固定版本的 build dependency 和 lock；
- 创建 `scripts/build-workflows.mjs --check`；
- 从当前 bundle 零行为变化地生成同一入口；
- 新增 bundle freshness、唯一 meta export / 无其他 import-export、AsyncFunction smoke
  与 source/bundle parity。

红区文件只有一个集成人可写：

```text
workflows/process-material.mjs
scripts/workflows/process-material.entry.mjs
scripts/build-workflows.mjs
package.json / lock
tests/test_skill_orchestration.py
tests/test_orchestrate_timeout.py
```

### G2：Paper / Analyse slice

并行文件所有权：

- Normalize owner：`scripts/extract/extract_text.py`、`scripts/extract/extract.py`、
  `tests/test_extract_cli.py`；
- Analyse owner：`agents/analyse-agent.md`、`scripts/workflows/operations/analyse.mjs` 及其新测试；
- Paper 集成 owner：`scripts/workflows/runtime.mjs`、`scripts/workflows/materials/paper.mjs`、
  `scripts/workflows/operations/{extract,analyse,acquire,audit}.mjs`、entry、bundle 与新
  Paper loop 行为测试；
- readability assessor 在 v0.1 使用 `general-purpose` + operation-owned prompt，
  不新增一个材料类型 Agent；
- `paper.download.legacy` / `paper.audit.legacy` 只做兼容接线；本波不重写完整
  acquisition 或 audit subsystem。

完成后由 bundle 集成人串行接入 entry、生成 bundle、迁移必要的 brittle source tests。

### G3：交叉审查与修正

至少进行三类独立审查：

1. contract / schema drift；
2. writer safety、重试、并发、路径和 secret boundary；
3. source / bundle / Claude runtime parity。

审查者不得用“测试绿”替代源码合同检查。

### G0–G3 实现状态

G0 characterization、G1 模块化源码与 deterministic bundle、G2 Paper/Analyse slice
和 G3 多轮安全审查均已落地。最终源码保留一个 `agent(prompt, opts)` primitive
入口；legacy/readonly 调用可以受 guard 约束，Paper writer 则完整 await 单次 Agent，
避免 timeout race 留下后台 writer。构建、合同、characterization、Pi/Codex
兼容回归和完整 Python 测试都是门禁；适配器只作回归约束，没有在本轮重设计。

### G4：Claude 验收

按顺序执行：

1. instruction mirror 与静态 guards；
2. unit / contract / characterization tests；
3. bundle `--check` 和 AsyncFunction compile；bundle ABI 必须是：
   - 恰好一个 `export const meta`；
   - 无 `import`；
   - 除 meta 外无其他 `export`；
   - 无 `fs / require / dynamic import`；
   - 保留 AsyncFunction body 的顶层 `return`，不能用不返回结果的 IIFE 包掉；
4. plugin validate；
5. 真实 Claude Workflow：
   - born-digital Paper happy path；
   - scan → OCR → analyse；
   - audit escalation → one repair → clean。
6. 对至少一个可回放 writer 场景执行 pause / resume，证明 artifact 不重复、不截断；
7. 在测试 vault 中核对 permission 行为：Workflow subagent 以 `acceptEdits` 运行，
   `quasi-*` 命令若不在 allowlist 可能仍触发权限提示，不能把提示等待误报为死锁。

Adapter runner、mock Agent 或 synthetic trace 不能声称为真实 Claude Workflow E2E。

当前已有一条隔离测试 vault 上的真实 Claude Workflow born-digital Paper happy path：
native run `wf_a10ebf24-df4` 完成 download reconcile → extract-text → readability →
analyse → audit，共 5 个 Agent。证据、artifact SHA-256 与权限观察记录在
[`reviews/2026-07-30-claude-workflow-e2e.md`](reviews/2026-07-30-claude-workflow-e2e.md)。
它不覆盖 scan/OCR、audit repair 或 pause/resume；这些仍是 G4 未完成项。

## 8. 后续顺序

Paper 验证目录与操作模型后：

```text
Book
  → Extract subgraph
  → chapter.analyse
  → synthesis
  → exact audit repair

Talk
  → transcribe × engines
  → reconcile transcript
  → talk.analyse

Author
  → consume MaterialReceipts only

Topic
  → produce demands
  → consume MaterialReceipts
  → steer / dossier / spine
```

Acquire、Extract、Audit 可以按互斥文件边界并行实现，但统一 Graph 只能由一个集成人
串行接线。

## 9. Claude-native 可观测性

Claude Code 的 `subagentStatusLine` 很适合显示这张图，但它是 UI projection，不是
Workflow state、receipt 或新的执行 primitive。

插件根已经加入：

```text
settings.json
scripts/subagent-statusline.py
tests/test_subagent_statusline.py
```

只覆盖 quasi 自己的 subagent row，并从 Claude 提供的 `tasks[]` 读取：

```text
label · status · model · effort? · tokenCount/contextWindowSize
```

因此 Operation label 必须稳定且短，例如：

```text
paper.extract-text:{slug}
paper.assess:{slug}
paper.ocr:{slug}
paper.analyse:{slug}
paper.audit:{slug}
```

约束：

- 当前本机 Claude Code 是 `2.1.211`：per-task model/context 字段可用；
- per-task effort 需要 `2.1.214+`，脚本必须允许字段缺失；
- 脚本每个 refresh tick 都运行，不能做 git scan、网络请求或读大文件；
- 非 quasi task 不输出 override，让 Claude 保留默认 row；
- status line 不能被当成续跑状态源，也不能代替 Claude 原生 run history / typed receipt；
- 插件默认 `settings.json` 只覆盖 quasi task id/label 匹配的行；非 quasi task 不输出，
  坏输入也不向 stdout 泄漏日志。它已通过独立 mock 输入测试，但仍只是 UI projection，
  不参与 Graph 分支或续跑。

同一批 Claude-native 新能力（Task/Subagent hooks、monitor、agent effort 等）后续逐项按
“能否减少自建 runtime”评估；只有稳定公开字段进入合同，UI 字段不反向驱动业务分支。

## 10. 禁止事项

- 不让运行时直接 import sibling workflow modules；
- 不修改 Claude loader 来创造 host-specific graph；
- 不让 Loop 启动另一个 Workflow runner；
- 不让 Agent 启动业务 Agent 或选择恢复边；
- 不在 Operation wrapper 或 command-relay Agent 重写已有下载、OCR、split、audit 实现；
- 不在一个大改里同时切 bundle 格式、public receipt、所有 Agent prompt 与 runner；
- 不为未来类型预建空文件和统一 registry；
- 不把 mock / Pi / Codex adapter 测试报告成 Claude E2E；
- 本轮不提交、不推送、不部署、不发版。

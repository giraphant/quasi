# quasi 插件瘦身审计（2026-08-01）

> 范围：只读审计当前工作树；唯一新增文件是本报告。没有修改任何运行时代码、测试、manifest 或生成物。
>
> 快照说明：审计开始时 manifest 为 0.57.8；共享工作树随后并发落入 0.57.9 的 Talk contract 改动。本报告已对最终可见快照重新计数和重跑基线；这些并发代码改动不是本审计产生的。

## 结论摘要

- `scripts/workflows/` 的 5,230 行由 **4,087 行可编辑 `.mjs` 源码**和 **1,143 行生成的 artifact-contract module** 构成；另有生成的 `workflows/run-stage.mjs` 90 行。4,087 行源码中，校验约 2,385 行（58.4%）、流程界定 693 行（17.0%）、prompt 组装 739 行（18.1%）、胶水 270 行（6.6%）。
- 八个 row 文件共 3,418 行。按“可以被同一个带参数 helper/factory 替代”的保守口径，**1,043 行（30.5%）是重复形状**；Paper 为 43.5%，Talk 为 43.4%，Book 为 36.4%，Author 为 33.1%。
- 最大的真实源码瘦身不在 workflow：两个无调用方的一次性 migration 共 2,601 行；在“不留向下兼容”的方针下可直接删除。其次是 strict/legacy 双 CLI 表面（约 450–550 行）和 rows 的共享 fragment/factory（约 300–380 行）。
- `topic` 目前并未进入 material 状态树：schema 有 `TopicSchema`，但 `TOPIC_BODY` 为空、生成器不导出 Topic contract、`quasi-status` 不接受 topic，而 Topic row/skill/agent 各自重述产品结构与路径。这正是并树前最强的重复证据。
- `npm run check:workflows` 通过。字面命令 `pytest ...` 因当前 shell 没有 `pytest` 可执行文件而 exit 127；同一解释器下 `python3 -m pytest ...` 为 **13 passed**。

## 0. 口径与总量

### 0.1 行数口径

- 均为 `wc -l` 的 physical lines；包含空行和注释。
- 语义分类是互斥主分类：`F` 流程界定、`V` 校验、`P` prompt 组装、`G` 胶水/import/常量，四项之和等于文件行数。
- `D`（跨文件重复样板）是一个**叠加维度**，会与 F/V/P/G 重叠；它不参与四项求和。只有当一段能被同一个带参数 helper/factory 替代时才计入，单纯的括号、`required` 等低信息相似行不计。
- 生成物 `scripts/workflows/artifact-contracts/generated.mjs` 与 `workflows/run-stage.mjs` 只记输出体积，不对其内容逐行归责；对应审计对象是 `scripts/schemas/*.py`、`scripts/build-workflows.mjs` 和 `scripts/workflows/run-stage.entry.mjs`。

### 0.2 全插件盘点（排除 vendored/vendor、`.venv`、`__pycache__`）

| 层 | 文件数 | physical lines | 构成 |
|---|---:|---:|---|
| `skills/` | 4 | 1,025 | 4 个 Markdown（其中 `collect-material/references/talk.md` 108 行） |
| `agents/` | 14 | 856 | 14 个 Markdown |
| `bin/` | 9 | 314 | 9 个无扩展名 shell shim |
| `scripts/` | 127 | 38,833 | Python 101/32,123；MJS 18/5,445；Markdown 3/994；shell 3/178；Swift 1/68；TOML 1/18；txt 1/7 |

`scripts/` 最大文件包括 `scripts/download/download.py` 3,179 行、`scripts/translate/translate_commit.py` 1,595 行、生成的 artifact contracts 1,143 行、`scripts/transcribe/transcribe.py` 1,069 行。

生成链的可编辑源与输出：

| 角色 | 路径 | 行数 |
|---|---|---:|
| artifact schema 源 | `scripts/schemas/*.py` | 1,236 |
| workflow build 源 | `scripts/build-workflows.mjs` | 215 |
| run-stage entry 源 | `scripts/workflows/run-stage.entry.mjs` | 113 |
| 生成输出 | `scripts/workflows/artifact-contracts/generated.mjs` | 1,143 |
| 生成输出 | `workflows/run-stage.mjs` | 90 |

## ① workflow 逐文件行数分类

### 1.1 可编辑 `.mjs` 源（生成的 `artifact-contracts/generated.mjs` 除外）

| 文件（相对 `scripts/workflows/`） | 总行 | F 流程界定 | V 校验 | P prompt | G 胶水 | D 重复样板（叠加） |
|---|---:|---:|---:|---:|---:|---:|
| `runtime.mjs` | 51 | 0 (0.0%) | 47 (92.2%) | 0 | 4 (7.8%) | 0 |
| `stage.mjs` | 168 | 19 (11.3%) | 138 (82.1%) | 0 | 11 (6.5%) | 0 |
| `run-stage-context.mjs` | 217 | 203 (93.5%) | 0 | 0 | 14 (6.5%) | 0 |
| `run-stage.entry.mjs` | 113 | 56 (49.6%) | 25 (22.1%) | 7 (6.2%) | 25 (22.1%) | 0 |
| `operations/shared.mjs` | 11 | 0 | 5 (45.5%) | 0 | 6 (54.5%) | 0 |
| `operations/steer.mjs` | 10 | 3 (30.0%) | 7 (70.0%) | 0 | 0 | 0 |
| `operations/define.mjs` | 48 | 17 (35.4%) | 16 (33.3%) | 6 (12.5%) | 9 (18.8%) | 0 |
| `operations/book-year-evidence.mjs` | 51 | 0 | 47 (92.2%) | 0 | 4 (7.8%) | 0 |
| `operations/rows/author.mjs` | 481 | 74 (15.4%) | 278 (57.8%) | 98 (20.4%) | 31 (6.4%) | 159 (33.1%) |
| `operations/rows/book.mjs` | 738 | 52 (7.0%) | 482 (65.3%) | 176 (23.8%) | 28 (3.8%) | 269 (36.4%) |
| `operations/rows/member.mjs` | 113 | 11 (9.7%) | 75 (66.4%) | 15 (13.3%) | 12 (10.6%) | 6 (5.3%) |
| `operations/rows/paper.mjs` | 398 | 30 (7.5%) | 240 (60.3%) | 107 (26.9%) | 21 (5.3%) | 173 (43.5%) |
| `operations/rows/search.mjs` | 214 | 13 (6.1%) | 118 (55.1%) | 48 (22.4%) | 35 (16.4%) | 60 (28.0%) |
| `operations/rows/talk.mjs` | 371 | 39 (10.5%) | 224 (60.4%) | 91 (24.5%) | 17 (4.6%) | 161 (43.4%) |
| `operations/rows/topic.mjs` | 784 | 151 (19.3%) | 432 (55.1%) | 159 (20.3%) | 42 (5.4%) | 197 (25.1%) |
| `operations/rows/translation.mjs` | 319 | 25 (7.8%) | 251 (78.7%) | 32 (10.0%) | 11 (3.4%) | 18 (5.6%) |
| **合计** | **4,087** | **693 (17.0%)** | **2,385 (58.4%)** | **739 (18.1%)** | **270 (6.6%)** | **1,043 (25.5%)** |

主要分界锚点（便于复核分类判断）：

- `run-stage-context.mjs:16-217` 是 operation→context/path 的大 switch；`run-stage.entry.mjs:12-50,74-113` 是 descriptor registry、解析与一次 dispatch。
- `stage.mjs:15-138,144-168` 和 `define.mjs:25-46` 是共享 receipt schema、cross-terminal contract 与 schema/prompt 生成。
- row 文件中，`payloadProperties`、`terminalPayloads`、`complete` 计 V；`envelope`、`promptText` 计 P；descriptor header 与 `refs` 计 F；import、兼容 export、纯常量/空行计 G。

### 1.2 生成源审计，而非生成物审计

- `scripts/build-workflows.mjs:29-35` 明确列出仅 Author/Paper/Chapter/Book/Talk 五种 contract；`scripts/build-workflows.mjs:110-152` 调 Python exporter 并以 pretty JSON 生成 module；`scripts/build-workflows.mjs:55-108` 打包 entry。
- `scripts/schemas/contracts.py:16-79` 从 registry/Pydantic/BodySchema 投影 producer contract；这是 1,143 行 generated module 的语义来源。
- `scripts/schemas/body.py:84-450` 是五类 material 的正文结构来源；`scripts/schemas/body.py:453` 却把 Topic 定义成空 sections。`scripts/schemas/topic.py:20-80` 有 frontmatter/outline 结构，但没有进入 build 列表。
- `scripts/workflows/run-stage.entry.mjs:25-50` 手写一份 kind+stage registry，同时每个 row 又写 `operation`/`stage`；`run-stage-context.mjs:16-215` 再手写第三份 operation 列表。这是 generation source 中最明显的路由重复。
- `scripts/build-workflows.mjs:141-150` 的 `JSON.stringify(value, null, 2)` 只制造 1,143 行 pretty generated JSON；若改为 compact emission，语义不变，生成物约可降至 10–20 行。必须改 build 源后运行 `npm run build:workflows`，绝不能手改 generated module。

## ② rows 重复度分析与抽取方案

### 2.1 八文件重复比例

| row 文件 | 行数 | 可替代重复形状 | 比例 | 主要重复来源 |
|---|---:|---:|---:|---|
| `topic.mjs` | 784 | 197 | 25.1% | standalone recall API、action terminal、audit row、request header、尾部实例 export |
| `book.mjs` | 738 | 269 | 36.4% | attempts/step schema、action terminal、Analyse/Synthesise writer、Audit、尾部实例 export |
| `author.mjs` | 481 | 159 | 33.1% | action terminal、Synthesise writer、Audit、尾部实例 export |
| `paper.mjs` | 398 | 173 | 43.5% | attempts/step schema、action terminal、Analyse writer、Audit、尾部实例 export |
| `talk.mjs` | 371 | 161 | 43.4% | step schema、action terminal、Analyse writer、Audit、尾部实例 export |
| `translation.mjs` | 319 | 18 | 5.6% | step schema、尾部实例 export |
| `search.mjs` | 214 | 60 | 28.0% | Book/Paper identity shape、standalone schema/prompt/contract API |
| `member.mjs` | 113 | 6 | 5.3% | 尾部实例 export；但整个 operation 可能已无 caller（见 §4） |
| **合计** | **3,418** | **1,043** | **30.5%** |  |

这个 30.5% 是保守“可抽取形状”而不是文本 clone 率；例如 Book 与 Paper acquisition 的业务判断不同，不因都有 `attempts` 就把完整 row 计为重复。

### 2.2 具体可共享片段

| 重复块 | 当前行号 | 建议归属 | 预计净省行 |
|---|---|---|---:|
| attempts schema | `book.mjs:10-23`; `paper.mjs:5-18` | `operations/shared.mjs` 的常量 | 11–13 |
| step schema | `book.mjs:48-60`; `paper.mjs:39-51`; `talk.mjs:48-60`; `translation.mjs:143-155` | `stepSchema(outcomes)`；各 row 只给 enum | 35–42 |
| writer action terminals | `author.mjs:125-146`; `book.mjs:172-207`; `paper.mjs:72-93`; `talk.mjs:62-83`; `topic.mjs:403-410,556-566` | `actionTerminalPayloads({mode, writeState, allowed})` | 70–90 |
| audit diagnostic item | `author.mjs:148-157`; `book.mjs:209-218`; `paper.mjs:95-104`; `talk.mjs:85-94`; `topic.mjs:613-624` | `auditDiagnosticSchema({exactPath?})` | 32–38 |
| common Audit row | `author.mjs:414-465`; `book.mjs:680-727`; `paper.mjs:343-388`; `talk.mjs:311-362`; `topic.mjs:595-639,746-770` | 新建 `operations/common-rows.mjs::makeAuditRow`；参数只有 operation、target role、exact-path policy、extra envelope fields | 140–170 |
| canonical Analyse/Synthesise writer skeleton | `author.mjs:351-413`; `book.mjs:541-679`; `paper.mjs:283-342`; `talk.mjs:254-310`; `topic.mjs:492-593,730-745` | `makeCanonicalWriterRow` 只统一 refs/payload/action/complete/mode；identity、artifact contract、evidence rules 仍由 row callback 提供 | 85–120 |
| request envelope header | 所有 `envelope`，例如 `paper.mjs:163-170,261-268,308-314,378-386`; `book.mjs:342-348,505-511,582-587,647-650,718-725` | `defineOperation` 在 prompt 前注入统一 `{schema_version,operation,stage,material_key,effect}`；row 只返回 operation body | 75–100 |
| 未被外部引用的 instantiated exports | `author.mjs:469-481`; `book.mjs:730-738`; `paper.mjs:391-398`; `talk.mjs:365-371`; `translation.mjs:315-319`; `topic.mjs:773-784`; `search.mjs:190-214` | 直接删除；entry 只需要 `*OperationRows` | 120–130 |

### 2.3 如何使用只有 48 行的 `define.mjs`

不建议把 material policy 塞进 `defineOperation`。合理边界是：

1. 在 `define.mjs:8-47` 增加**纯协议默认值**：统一 request header、默认 JSON prompt、默认 action coherence hook；不处理 year evidence、OCR、chapter 或 topic 方法。
2. 在 `operations/shared.mjs:4-11` 或新的 `operations/schema-fragments.mjs` 放纯 schema fragment（attempt、step、action、audit diagnostic）。
3. 在新的 `operations/common-rows.mjs` 放 `makeAuditRow` / `makeCanonicalWriterRow`；callback 仍由具体 row 提供 identity、artifact contract、exact refs 和 operation-only cross-field checks。
4. 先删死 API，再抽 fragments，再抽 row factory；按这个顺序，八个 rows 预计可由 3,418 行降至约 **2,800–2,900 行**（净省 500–620 行，包含 dead API；其中共享/factory 本身约 300–380 行）。

这不会违反 ownership：artifact 的 frontmatter/H1/sections/block shape 仍只来自 `scripts/schemas/`。尤其不能为了 factory 方便，把 `PAPER_ARTIFACT_CONTRACT`、`CHAPTER_ARTIFACT_CONTRACT` 等结构复制回 rows。

### 2.4 Skill / Agent 合同重复

- 两个驱动 skill 重复了 shared Stage 协议与 writer ambiguity：`collect-material/SKILL.md:28-81,158-175,191-200` 对应 `research-topic/SKILL.md:28-79,170-179,199-213`。建议在每个 skill 保留一段最短 driver rule，Topic 文件只补 round/seed/card 差异，预计省 35–55 行。
- `collect-material/references/talk.md:20-63,65-108` 重述主 skill 的 `collect-material/SKILL.md:28-81,91-95,135-175,191-200`，同时又摘要 `transcribe-agent.md:12-58`、`analyse-agent.md:30-42` 与 `audit-agent.md:12-39`。该 reference 没有从 active skill 链接，整文件 108 行可删。
- `research-topic/SKILL.md:97-104,139-179,181-197` 必须保留 caller 的 gate/terminal 处理，但无需再转述 specialist 的 exact path/method；这些内容已由 `steer-agent.md:10-39`、`webcard-agent.md:10-32` 和 row schema 约束。可压约 15–25 行。
- row 也在重述 Agent 方法：`search.mjs:172-185` 与 `metadata-agent.md:8-63` 重复 completion/method/scope；`topic.mjs:713-728` 与 `webcard-agent.md:12-32` 重复 verified/unchanged/empty 语义。descriptor 应只给 goal、capabilities、exact refs 和 operation-only evidence rule，专业 stopping/method 留给 Agent，预计再省 20–30 行。
- 不建议创建 Agent 兼容 include 层：Claude plugin 没有可靠的 agent-markdown include contract。应直接删除重复 prose，并确保每个 Agent 文件本身仍自足。

## ③ 精简机会 Top 清单

> 按当前工作树的预计物理省行数从高到低排序。估算有重叠处已注明；“重建”指是否要运行 `npm run build:workflows`。任何生成物都只能由源重建。

| 排名 | 机会 | 预计省行 | 风险 | 涉及生成物 | 源文件与行号 | 重建 |
|---:|---|---:|---|---|---|---|
| 1 | 删除无调用方的一次性迁移工具（不保留兼容入口） | **2,601** | 低；风险仅是有人在仓库外手工调用 | 否 | 两个旧脚本整体删除；仓库内除自身无引用 | 否 |
| 2 | artifact-contract generated module 改为 compact emission | **约 1,120–1,130（全为生成行）** | 低；语义/bytes 不增 | 是 | 改 `scripts/build-workflows.mjs:131-150`，特别是 `JSON.stringify(..., null, 2)`；不要改 `artifact-contracts/generated.mjs` | **是** |
| 3 | 删除 extract/transcribe/translate 的 strict/legacy 双表面，只留闭合 JSON operation | **约 450–550** | 中；会立即断开旧人工 CLI，符合本轮方针 | 否 | `split_chapters.py:284-503,874-885`; `process_epub.py:495-541`; `transcribe.py:533-566,827-888,923-1001`; `translate.py:185-195,242-279,299-331`; `bin/quasi-translate:23-53`; `bin/quasi-transcribe:12-14`; `talk/compress_media.py:54-64,399-423,552-565`; `transcribe/silent.py:84-96` | 否 |
| 4 | rows 共享 schema fragments + Audit/Writer factories（不含死 API） | **约 300–380** | 中；cross-field check 不能被泛化掉 | 是 | §2.2 所列 `author/book/paper/talk/topic/translation` 区间；factory 源为 `define.mjs:8-47`、`shared.mjs:4-11` | **是** |
| 5 | 删除未引用的 workflow standalone/instantiated API | **约 120–130** | 低；`rg` 结果均只命中定义文件自身 | 是 | `search.mjs:190-214`; `topic.mjs:167-207,773-784`; `author.mjs:469-481`; `book.mjs:730-738`; `paper.mjs:391-398`; `talk.mjs:365-371`; `translation.mjs:315-319`，并删相应 `defineOperation`/`stageContract` import | **是** |
| 6 | 把 Topic 并入 material 状态/contract 树，移除平行 admission/path/schema | **净约 120–220**（在 #4 后） | 高；是结构性改造 | 是 | `status/status.py:518-593`; `research-topic/SKILL.md:90-104,124-137,152-179,199-213`; `topic.mjs:131-165,209-304,305-340,492-527,595-638`; `schemas/topic.py:20-80`; `schemas/body.py:453`; `build-workflows.mjs:29-35`; `webcard-agent.md:12-24` | **是** |
| 7 | 删除或裁决 `member.admission-probe` relay 的合同漂移 | **约 120** | 中高；`CLAUDE.md` 与 active skill 相互矛盾 | 是 | `member.mjs:1-113`; `run-stage-context.mjs:208-213`; `run-stage.entry.mjs:4,17,48`; `collect-material/SKILL.md:73-76`; `research-topic/SKILL.md:90-104`; `CLAUDE.md/AGENTS.md:35` | **是**；若改根指南，两个文件必须字节一致 |
| 8 | 删除未被 `collect-material` 引用且内容重复的 Talk reference | **108** | 低；active skill 已包含同一 loop | 否 | 删除 `skills/collect-material/references/talk.md:1-108`; `docs/ARCHITECTURE.md:133` 同步移除说明 | 否 |
| 9 | 删除 deprecated type alias 迁移链 | **约 80–110** | 中；旧 vault 会从“可自动改”变成 unknown，符合无兼容方针 | 否（canonical contract 不变） | `schemas/registry.py:47-86`; `schemas/__init__.py:32-39,54-57`; `typecheck/typecheck.py:332-349`; `typecheck/autofix_mechanical.py:215-224,400-419`; `audit/field_distribution.py:80-100,128-140,232-243`; 更新相应 tests/SPEC | 否；仍应跑 `check:workflows` 验证输出未漂移 |
| 10 | 共享 Paper/Chapter 正文 section 定义 | **约 50–65** | 中；必须保证投影完全相同 | 是 | `schemas/body.py:226-298` 与 `303-378` 基本同形；提取 `ACADEMIC_ANALYSIS_SECTIONS`，保留不同 identity/h1 | **是** |
| 11 | 合并 8 个 Python shim 的 venv/bootstrap 前缀 | **约 45–60** | 低 | 否 | `bin/quasi-audit:10-20`, `quasi-download:11-21`, `quasi-extract:21-31`, `quasi-search:8-18`, `quasi-status:8-17`, `quasi-transcribe:16-26`, `quasi-translate:13-21`, `quasi-helpers:32-40`; 由一个 source-only shell helper 提供 | 否 |
| 12 | skill 去重：只在驱动层保留一次 Stage terminal/writer-ambiguity 规则 | **约 35–55**（#8 之外） | 中低 | 否 | `collect-material/SKILL.md:28-81,158-175,191-200` 与 `research-topic/SKILL.md:28-79,170-179,199-213`；保留 topic 特有 round/gate，不重述 Agent 方法 | 否 |

### Topic 并树与 skill 改名的具体前置方案

1. 给 `quasi-status` 增加 canonical `kind:topic`，让 overview/resources/outline/cards 的存在、identity 与 repair evidence 走与 material 相同的 observation envelope；当前只允许 `paper|book|talk|translation`（`scripts/status/status.py:571-593`）。
2. 完成 Topic 的 schema 投影：`TopicSchema` 已在 `scripts/schemas/topic.py:20-80`，但 `TOPIC_BODY` 为空（`body.py:453`）且 build 列表缺 Topic（`build-workflows.mjs:29-35`）。先让 schema 成为唯一产品结构，再删除 `topic.mjs:209-304,601-632` 与 `webcard-agent.md:20` 对结构的手写重复。
3. 把 material admission 的 canonical path 从 status 返回值直接消费，删除 `topic.mjs:131-165` 的第二套 `topicMemberPath`/path proof，并合并 `steerRefs`/`synthesisRefs` 中重复的 member/card projection（`topic.mjs:305-340,492-527`）。
4. 当前真正的 public skill 名是 `research-topic`；`precise-topic` 只剩 dead-name 测试哨兵（`tests/test_dead_names.py:46,145`），没有 live skill。为避免 skill 意图与 `type:topic` artifact 混名，建议**直接把 `skills/research-topic` 改名为 `skills/research-question`**（不保留 alias），同步 `SKILL.md:1-4`、`README.md:16`、`docs/ARCHITECTURE.md:128-134`、`tests/test_skill_orchestration.py:122-140`，以及 `CLAUDE.md/AGENTS.md:35`。若选择别的最终名也应一次性替换，不能留下 `precise-topic` 或 `research-topic` 兼容层。
5. 根指南同步时，`CLAUDE.md` 与 `AGENTS.md` 必须 byte-for-byte 相同；本轮审计已确认 `cmp -s` 返回 0。

## ④ 死引用与 legacy 残留

### 4.1 已证实无仓库内消费者

| 项目 | 证据 | 建议 |
|---|---|---|
| row 的 instantiated exports | `paperAcquire`、`bookPrepare`、`talkAudit`、`topicOverview`、`materialSearchPrompt` 等每个符号经 `rg` 都只命中定义文件自己；范围见 §2.2 | 直接删，只导出 `*OperationRows` |
| `topicRecallStageSchema` / `TOPIC_RECALL_SCHEMA` / `topicRecallOperationPrompt` / `TOPIC_RECALL_CONTRACT` | `topic.mjs:167-207` 只自引用；run-stage 用 row descriptor | 直接删，不留 standalone adapter |
| 一次性迁移工具 | 两个脚本在 README/docs/skills/agents/bin/active scripts/tests 均无调用点 | 直接删除 |
| `skills/collect-material/references/talk.md` | active skill 没有链接它；唯一外部提及为 `docs/ARCHITECTURE.md:133` | 删除 reference 与该说明 |

### 4.2 合同漂移/疑似死 operation

- `member.admission-probe`：根指南 `CLAUDE.md/AGENTS.md:35` 说 collection/research 应通过该 receipt admission；但 active `collect-material/SKILL.md:73-76` 明确“不要调用”，`research-topic/SKILL.md:90-104` 直接调用 `quasi-status --identity`，全仓没有 skill dispatch `kind:"member"`。应先选定唯一合同：按当前 skill 行为则删 `member.mjs`、entry/context registry 和根指南旧句；若根指南才是目标，则这不是瘦身项而是 skill regression。不要同时保留两条路径。
- `translate` kind alias：`run-stage.entry.mjs:50,80` 把 `translate` 映射到 `translation`，测试 `tests/test_run_stage.py:120-137` 仍只登记 `translate`；这是明确兼容 alias。无兼容方针下只保留 `translation` 并同步 tests/skill caller。
- request schema tag 漂移：同一个 Stage request boundary 同时存在 `quasi.stage.request/0.2` 和 13 个 `...request/0.1|0.2` 名称（例如 `paper.mjs:164,262,309,379`; `book.mjs:342,505,582,647,718`; `talk.mjs:218,288,350`）。这些 tag 当前没有通用 validator，除 Topic agents 明确要求 `quasi.stage.request/0.2` 外也无分派用途。建议无兼容升级为一个 `quasi.stage.request/0.2`，由 `defineOperation` 注入；不要保留旧 tag alias。当前 `quasi.stage.receipt/0.2` 是 live shared receipt，不是旧版本。

### 4.3 明确 legacy 兼容实现

- Translation：`bin/quasi-translate:23-53` 接受旧直接 `SLUG [--backend]` 表面并改写为 `legacy`；`scripts/translate/translate.py:185-195,242-279,299-331` 是完整 compatibility adapter/prose renderer。它还与“backend selection 只能来自 config”合同冲突。
- Extraction：`scripts/extract/split_chapters.py:284-503,874-885` 保留 legacy prose route 和另一套 auto/pages builder；`process_epub.py:495-541` 保留 historical renderer。
- Transcription/Talk：`bin/quasi-transcribe:12-14` 宣告 legacy calls；`transcribe.py:533-566,827-888,923-1001` 为每个 command 保留非 strict 输出；`talk/compress_media.py:62,406-423` 保留 `--force`/legacy skip；`transcribe/silent.py:84-96` 是 legacy helper。
- Schema aliases：`schemas/registry.py:47-86`、typecheck/autofix/audit consumers 仍为旧 type 做 diagnostics/migration。
- Path root：`scripts/core/core.py:52-59` 仍接受 `QUA_PROJECT_ROOT` 作为 legacy compatibility override；对应 tests 为 `scripts/core/tests/test_core.py:24-35`。
- 旧 field：`scripts/typecheck/autofix_mechanical.py:171` 仍把 singular `topic` 作为 legacy field 丢弃；应在 Topic/material 合并时确认新树只使用 `topics` 或新的统一关系字段，不保留双读。
- 旧 operation/statusline regex：`scripts/subagent-statusline.py:39` 仍匹配 `paper.download.legacy|extract-text|assess|ocr|analyse|audit` 的历史 label。当前 workflow label 由 `run-stage.entry.mjs:107-112` 生成 `{slug}:{stage}`，这条 regex 是 legacy UI adapter，应直接删并更新相关测试。
- Search flags：`scripts/search/search.py:671,685` 的 `--json` 明说“Accepted for compatibility; output is always JSON”；可把 `--json` 从 parser 删除并让 callers 不再传，或反过来规定 `--json` 为唯一强制表面；不要继续接受无效果 flag。

### 4.4 旧 bin 名与 precise-topic 扫描结果

- `quasi-citation`、`quasi-proofread`、`quasi-download batch` 没有重新出现在 active skills/agents/prompts。命中只存在于 `CLAUDE.md/AGENTS.md:78` 的负面禁令、`docs/ARCHITECTURE.md:49-50` 的迁移说明和 dead-name tests；基线测试亦通过。
- `precise-topic` 没有 live component；只存在于 `tests/test_dead_names.py:46,145` 的禁止名单。当前 live skill 是 `research-topic`。
- 因本轮方针不保留兼容，可在完成改名后继续保留 dead-name test 作为“不得复活”的哨兵；这不是兼容层。若要瘦 active docs，可删 `CLAUDE.md/AGENTS.md:78` 与 architecture 的旧命令迁移段，但两份根指南必须同时且字节一致修改。

## ⑤ 基线测试结果

| 命令 | 结果 |
|---|---|
| `npm run check:workflows` | **PASS**；输出 `run-stage workflow bundle is current` |
| `pytest tests/test_dead_names.py tests/test_skill_orchestration.py -q` | **未执行成功（exit 127）**；当前 shell 没有 `pytest` executable：`zsh: command not found: pytest` |
| `python3 -m pytest tests/test_dead_names.py tests/test_skill_orchestration.py -q` | **PASS**；`13 passed in 0.01s` |
| `cmp -s CLAUDE.md AGENTS.md` | **PASS**；返回 0，当前两文件字节一致 |

## 建议实施顺序

1. 先删无调用方 migrations、row standalone APIs 和明确 strict/legacy adapters；这些动作最符合“不留向下兼容”，也会让后续重复率更真实。
2. 再抽 schema fragments、Audit factory、canonical writer factory，运行 `npm run build:workflows` 与完整 workflow tests。
3. 然后完成 Topic schema projection + `quasi-status kind:topic`，把 Topic 纳入 material observation/admission 树；同一批次直接改名 public skill，不留 alias。
4. 最后做 compact generated emission、BodySchema 公共 sections、bin bootstrap 等低风险机械瘦身。

任何涉及 `scripts/schemas/`、descriptor rows、`run-stage.entry.mjs`、`run-stage-context.mjs` 或 build 源的实现都应由 `npm run build:workflows` 重建；`scripts/workflows/artifact-contracts/generated.mjs` 与 `workflows/run-stage.mjs` 不可手改。

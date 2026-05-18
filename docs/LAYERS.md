# Quasi 层次设计 — 思考用工作文档

date: 2026-05-17
status: **决策已收齐,可作落地依据**
配套阅读:
- `Quasi 当前结构 snapshot — 编辑用.md` —— 实物清单 + 合并意图
- `EXPERIENCE-vault-metadata-backfill.md` —— 多源 metadata chain 的实战经验,Q6/Q7b 的依据

---

## 0. 这份文档解决什么

snapshot.md 已经把实物清单 + 你打算的合并写下来了。
这份只回答一个问题: **"为什么有三层?"** —— 没有这个,合并/拆分都是凭手感。

---

## 1. 三层模型 — 以"上下文/并发"为存在意义

层的价值不是"职责分离",是 **上下文经济 + 并发**。

| 层 | 定位 | 存在的真正理由 | 复用关系 |
|---|---|---|---|
| **L0 / bin** | 封装好的基础能力(I/O 工具) | 提供原子操作,任何上层都可以拼装 | **一对多**: 一个 bin 可被 N 个 agent 复用;agent 可调 N 个 bin |
| **L1 / agent** | 子代理派遣单元 | **隔离上下文** + **并发** —— 通过 Task dispatch 把工作压到子上下文,主进程不被污染;多份能并跑 | **一对多**: 一个 agent 可被 N 个 skill 编排,内部可调 N 个 bin |
| **L2 / skill** | 用户场景编排 | 用户入口 + 工作流脚本 | 一个 skill 编排若干 agent |

### 1.1 推导出来的硬规则

由"agent 存在 = 上下文隔离 + 并发"出发,以下规则**不是品味问题,是定义自洽问题**:

| 规则 | 推导 |
|---|---|
| **bin 追求"原子且通用"**,数量越克制越好 | bin 是 share 单位,合理粒度让 agent 能自由拼装 |
| **agent 不必有专属 bin** | agent 是上下文边界,跟 bin 是正交概念;一个 agent 可以只调别人的 bin、或纯 LLM 不调 bin |
| **bin 也不必有对应 agent** | 如果一项 I/O 主进程直接 Bash 调更经济(短输出、低噪音),就不必为它封 agent |
| **skill 不直调 bin** | 除非该任务**不需要上下文隔离**(短、确定、无后续 LLM 判断)。这是例外不是常态 |
| **同名不必强求** | `audit-agent` 调 `quasi-typecheck + quasi-search` 完全合理 —— bin 是能力名,agent 是上下文名 |
| **两种 agent-bin 关系并存** | A. agent 包 bin (download); C. 纯 LLM agent (analyse/synthesis/proofread/citation)。原 Pattern B 通过 `quasi-helpers` 聚合化解。详见 ARCHITECTURE.md §2.0 |
| **helper bin 例外** | `quasi-helpers` 是给 skill 主进程用、不给 agent 用的特殊 bin。封装 map-reduce 形态的 setup/teardown |

### 1.2 agent 数 vs bin 数:不同优化目标

- **bin 数** 优化目标: **能被多处复用**。少而通用 > 多而专用。一个 bin 只服务一个 agent 是反模式(除非这个 bin 就是大块、不可拆)。
- **agent 数** 优化目标: **上下文边界合理**。"这件事单开子上下文做收益大吗?需要并发吗?" 答 yes 才设 agent。
- 后果: bin 和 agent **没有 1:1 对应,也不应该追求 1:1**。

---

## 2. 当前结构按新模型重审

以 snapshot.md 你那版的 A/C/D 表为基线,逐项 audit:

### 2.1 bin 层 — 终态 6 bin (分两类)

#### Agent-callable atomic (5)

| bin | subcommand | 由什么合来 / 扩了什么 |
|---|---|---|
| **`quasi-search`** | `books` · `papers` · `metadata` · `validate` + **`scholar`**(新) | metadata 吸收 bts/scripts 8 脚本多源 chain; scholar 走 dokobot。**`journal` subcmd 推后**(整条 journal 链待重做) |
| **`quasi-audit`** | `check` · `fix` · `emit-bib` | 旧 typecheck + autofix + citation biblio(vault 级) 合一 |
| **`quasi-download`** | **`paper` · `book` · `batch` · `finalize`** | flag → subcommand;每 subcommand 内跑自己的 fallback chain |
| `quasi-extract` | `epub` · `ocr` · `split` | 三 subcmd 分别对应原 3 个 bin |
| `quasi-translate` | — | (不动) |

#### Skill-orchestration helpers (1)

| bin | subcommand (nested) | 干什么 |
|---|---|---|
| **`quasi-helpers`** | `proofread {split\|init\|cleanup}` · `citation {parse\|resolve\|render\|emit-bib}` | **聚合所有 skill 主进程要直调的 helper**。原 quasi-proofread + quasi-citation 全部进来 |

**已砍**(本轮):
- `quasi-typecheck` (并入 audit) / `quasi-autofix-mechanical` (并入 audit)
- `quasi-proofread` 删 → `quasi-helpers proofread *`
- `quasi-citation` 删 → `quasi-helpers citation *`

**延后/不动**(本轮):
- `quasi-journal-fetch` · `quasi-journal-report` —— 整条 journal 链待重做
- `quasi-synthesize-refs` —— 等 process-topic 重做
- `scan-agent` · `process-journal` skill · `setup-agent` —— 全部 hold

> **emit-bib 同名分域(Q1 答"保留两个")**:
> - `quasi-audit emit-bib` = 从 vault frontmatter 派生全量参考文献
> - `quasi-citation emit-bib` = 从单 draft 派生其引用子集
> - biblio **不需要独立 cache** —— vault frontmatter 是 source of truth, 两个 emit-bib 都是 view

### 2.2 agent 层(snapshot C 表: 9 活跃 + 2 暂废)

按"上下文隔离 + 并发"重审每个 agent 是否值得存在:

| agent | 隔离上下文? | 并发? | 评价 |
|---|---|---|---|
| `analyse-agent` | ✓ per-section LLM,主进程吃不下 | ✓ N 个 section 并行 | **强存在理由** |
| `synthesis-agent` (大一统) | ✓ 一组文本 → 综述,输入很多 | ✓ 多任务并行(per-book × N) | **强存在理由** |
| `discover-agent` | ✓ search 结果很多噪音 | △ 一次一作者 | **存在理由(上下文为主)** |
| `download-agent` | △ 输出短 | ✓ N 篇并行 | **存在理由(并发为主)** |
| `extract-agent` | ✓ 中间产物大 | ✓ N 本/篇并行 | **强存在理由** |
| `translate-agent` | ✓ PDF 很大 | △ 一次一篇 | **存在理由(上下文为主)** |
| `proofread-agent` | ✓ per-节 in-place edit | ✓ 多节并行 | **强存在理由** |
| `citation-agent` | ✓ 校引用判断 | ✓ 批并行 | **强存在理由** |
| `audit-agent` (≈ 旧 typecheck-agent + metadata 回填) | ✓ online verify 噪音大 + 多源结果合并复杂 | △ 暂时 | **存在理由(上下文为主)**。**职责**: 本地 schema check/fix (调 `quasi-audit`) + 在线检索元数据 (调 `quasi-search`,即多源 chain) + 回写决策 (regex 清洗 / 字段合并 / merge 策略) |
| ~~`scan-agent`~~ | 你判定: search 归 discover, 评分回主进程 | — | **砍** (见 §3.Q4) |
| ~~`overview-agent`~~ | 合入 synthesis-agent | — | **合** (见 §3.Q5) |
| ~~`profile-agent`~~ | 合入 synthesis-agent | — | **合** (见 §3.Q5) |
| ~~`setup-agent`~~ | 你暂废 | — | 暂搁 |

### 2.3 skill 层 — agent 名级联更新

| skill | dispatch 改动 |
|---|---|
| `/quasi:process-book` | overview-agent → **synthesis-agent** |
| `/quasi:process-author` | profile-agent + overview-agent → **synthesis-agent** (多次/多种 caller mode) |
| `/quasi:process-journal` | scan-agent → **discover-agent + 主进程评分循环** |
| `/quasi:citation-snowball` → **改名 `/quasi:process-topic`** | scan-agent → **discover-agent**;内部重做留给后续 |
| `/quasi:wrap-up` | (0.17.0 subcommand 对齐 + Phase 0 audit) |

---

## 3. 决策记录

### ✅ Q1. `quasi-typecheck` → **改名 `quasi-audit`**
subcommand: `check` / `fix` / `emit-bib`。bin 名 = 能力域,跟 audit-agent 自然对齐。

### ⏸ Q2. journal bin → **整条 journal 链推后,本轮不动**
方向不变(journal-fetch 进 search journal, journal-report 进 skill 主进程),
但用户(2026-05-17)决定整体推后跟 process-journal skill 一起重做。
本轮: `quasi-journal-fetch` · `quasi-journal-report` 保持现状不动。

### ✅ Q5. synthesis-agent 大一统 → **caller 传 mode**
synthesis-agent 接 `mode = book | author | journal | ...`,内部 switch 加载子 prompt。
合并 overview + profile + 原 synthesis 三处。维护友好。

### ✅ Q6. audit-agent 调哪些 bin → **编排 `quasi-audit` + `quasi-search`**
**职责切分**(参考 `EXPERIENCE-vault-metadata-backfill.md`):
- **检索 = `quasi-search` 的能力**: 多源 fallback chain (CR / AA / OL) **固化进 `quasi-search`** —— 把 `bts/scripts/sweep-book-fm-*` 8 个脚本的检索逻辑吸收。可能扩 subcommand 如 `quasi-search metadata --slug X` 或类似形态,具体接口实现时定。
- **回写 = audit-agent 的能力**: 拿到多源候选后,本地 regex 清洗(参考 EXPERIENCE §4.4)、字段选取、imprint vs parent 决策、写回 vault。**这部分不下放 bin,在 agent 里做**。
- **`quasi-audit`** 提供本地 check/fix/emit-bib,无 verify-online subcommand。

### ⏸ Q3. `quasi-synthesize-refs` 砍后,refs 抽取归宿 → **延后到 snowball 重做时**
**倾向**: 作为 `quasi-extract` 的一个机械子命令 —— "从文本抽 refs" 跟 extract 现有心智模型一致(原始输入 → 结构化输出)。
落地: snowball 重做时一起做,届时再决定是否加 `quasi-extract refs`。

### ⏸ Q4. scan-agent + process-journal 评分 → **跟 journal 链一起推后**
方向不变(评分回 skill 主进程,scan-agent 砍),
但本轮不动。scan-agent 跟 setup-agent 一起标"暂废待重构"。

### ✅ Q7a. audit state → **per-vault 全扫**
单 `processing/audit/state.json`。audit 每次全扫,简单,不做增量。

### ✅ Q7b. biblio 缓存粒度 → **不缓存,vault frontmatter 即 source of truth**
biblio 不是独立 cache,是 vault 派生 view。`quasi-audit emit-bib` 和 `quasi-citation emit-bib` 都是查询输出。
所谓"复杂计划"其实是底下要有**多源 metadata 子系统**(Q6 已落:固化到 `quasi-search` + audit-agent 回写)。

### ⏸ setup-agent → **暂搁,后续重构**
本轮不动。

### ⏸ citation-snowball skill → **改名 `process-topic`,本轮不重做**
仅级联改名,不动内部逻辑。重做留给后续。

---

## 4. 不在本次范围(防 scope creep)

- Python 源码层 DRY(HTTP headers、slugify、frontmatter 解析等)
- agent prompt 模板化
- bin shim 模板化

层次稳定后再做。

---

## 5. 实物落地顺序

按"风险低 → 影响面小 → 单点改动"先做,各步互不阻塞:

1. **bin 命名/合并**(纯重命名/合并,无逻辑变化)
   - `quasi-typecheck` + `quasi-autofix-mechanical` + `quasi-citation biblio` → `quasi-audit {check,fix,emit-bib}`
   - `quasi-journal-fetch` + `quasi-journal-report` → `quasi-journal {fetch,report}`
   - `quasi-extract` 内化 epub/ocr/split (snapshot 已落)
2. **`quasi-search` 扩多源 metadata chain**
   - 把 `bts/scripts/sweep-book-fm-*` 8 个脚本的检索逻辑固化为 `quasi-search` 的能力
   - 具体 subcommand 形态(`metadata` / `backfill` / 改 search 既有 flag)实现时定
   - 不含回写、不含本地 regex 清洗(那是 audit-agent 的事)
3. **agent 重塑**
   - `typecheck-agent` → `audit-agent`;新增"调 `quasi-search` 拿元数据 + 本地清洗 + 回写 vault"职责
   - `discover-agent` 剥 inline search,改调 `quasi-search`
   - `overview-agent` + `profile-agent` + `synthesis-agent` → 大一统 `synthesis-agent`,caller 传 `mode`
   - `scan-agent` 砍 / `setup-agent` 暂废
4. **skill 级联更新**
   - process-book / process-author: overview/profile → synthesis-agent
   - process-journal: scan-agent 砍,SKILL.md 写主进程评分循环
   - citation-snowball → **改名 `/quasi:process-topic`**: scan-agent 砍,改用 discover-agent;内部重做留给后续
   - wrap-up: 对齐 0.17.0 subcommand + 加 Phase 0 audit-agent run
5. **processing/ 约定**
   - `processing/audit/state.json` per-vault 全扫(Q7a)
   - biblio 不独立 cache(Q7b 已答)
6. **延后事项**(本轮不动)
   - Q3 refs 抽取归宿 → 等 `process-topic` 重做
   - `setup-agent` 重构
   - `process-topic` (原 snowball) 内部逻辑重做

---

## 6. 决策汇总表

| 编号 | 决策 | 状态 |
|---|---|---|
| Q1 | bin 改名 `quasi-audit` (subcommand check/fix/emit-bib) | ✅ |
| Q2 | journal 整条链推后,本轮不动 | ⏸ |
| Q3 | refs 抽取归宿(倾向 extract bin,等 process-topic 重做时定) | ⏸ |
| Q4 | journal 评分回 skill 主进程(推后) | ⏸ |
| Q5 | synthesis-agent 大一统,caller 传 mode | ✅ |
| Q6 | audit-agent = `quasi-search` 检索 + `quasi-audit` 本地 + agent 内回写决策 | ✅ |
| Q7a | audit state per-vault `state.json` | ✅ |
| Q7b | biblio 不独立 cache,vault frontmatter 是 truth | ✅ |
| 撞名 | `audit emit-bib` / `citation emit-bib` 同名分域 | ✅ |
| 新增 | `quasi-search` 加 `scholar` + `journal` subcmd, metadata 吸收 bts/scripts 8 脚本多源 chain | ✅ |
| 新增 | `quasi-download` flag → subcommand `paper`/`book`/`batch`/`finalize` | ✅ |
| 新增 | `quasi-extract` 加 `epub`/`ocr`/`split` subcommand | ✅ |
| 新增 | `quasi-helpers` 聚合 skill helper (proofread + citation),原两 bin 删 | ✅ |
| 改名 | `/quasi:citation-snowball` → `/quasi:process-topic` (本轮仅改名) | ✅ |
| setup-agent | 暂废,本轮不动 | ⏸ |

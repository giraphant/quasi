# ADR-002 — Quasi capability-driven 重构

- **日期**: 2026-05-16
- **状态**: draft(尚未实施;跟 ADR-001 共存,本文档是更顶层的全局视图)
- **关系**: ADR-001(citation 与 vault 解耦)是本文档的子集 / 前身。ADR-001 里关于 citation 流程的结论在本文档继承,但范围扩到整个 plugin。

---

## 1. Context

### 1.1 v1 痛点(详见 ADR-001)

- citation-agent 一条 verdict 同时承担"draft 引用是否正确"、"vault 元数据是否准确"、"vault 是否完整"三件事,schema 漂移、agent 过载、关注点不分离。
- 多个 agent(discover / scan / citation v1)各自重复实现 web 搜索逻辑,版本散落。
- `quasi-citation run` 一键 pipeline 把 orchestration 藏在 CLI 里,wrap-up skill 看不见全流程。

### 1.2 抽象问题

- **封装错位**:discover-agent 把"搜索 + 业务挑选 + 写 manifest"粘成一坨,搜索能力被业务壳子锁死。
- **能力重复**:3 个 agent 各自有一份 crossref/openlib 调用,bug 各自修,可靠性参差。
- **边界模糊**:`quasi-typecheck` 只管 schema 漂移;原计划的 `quasi-vault audit` 跟它做的事高度重叠;两者都扫 frontmatter,逻辑上是同一类事。
- **中间产物没暴露**:typecheck 内部本来就要做 "frontmatter → 结构化中间产物",这个产物(实质就是 biblio.json)被埋在脚本里,citation 流程没法复用。

### 1.3 重构目标

把"做什么"(capability)和"怎么实现"(layer)分开。同类能力 facade 统一,内部分层。skill 重新拿回 orchestration 主权,bin 只做 I/O,agent 只做 LLM 判断。

---

## 2. 设计原则

### 2.1 三步思考法

```
   step 1                   step 2                step 3
┌──────────────┐         ┌──────────────┐      ┌─────────────────┐
│ 底层能力清单 │  ───→  │ 上层工作流   │ ──→ │ 找共享 / 重复 / │
│  (capability)│         │ (workflow)   │      │ 错位 / 缺失      │
└──────────────┘         └──────────────┘      └─────────────────┘
```

先列原子化能力,再看上层工作流如何组合它们,最后定位"两个地方各自实现一遍"或"该共享却没共享"的位置。

### 2.2 四层架构

```
skill 层    orchestration                  /quasi:wrap-up 之类
   │           dispatch agent / 直接调 bin
   ▼
agent 层    LLM 业务判断                   citation-agent / audit-agent
   │           Bash 调 bin (按需)
   ▼
bin 层      CLI facade (对 agent 暴露)     quasi-search / quasi-audit
   │           Python import scripts
   ▼
scripts 层  实现细节 (agent 不感知)         scripts/search/crossref.py
   │           HTTP / fs / subprocess
   ▼
外部世界    Crossref / OpenLibrary / 豆瓣 / vault files / Anna's...
```

### 2.3 I/O 型 vs LLM 型

- **I/O 型能力**(搜索、扫描、解析、下载、抽取、渲染、apply 等)走 bin/scripts,deterministic、可缓存、易测试。
- **LLM 型能力**(分析、综述、主题契合、在线交叉验证等)走 agent,内部尽量自包含。

### 2.4 facade 原则:对外统一、内部分层

`quasi-search` 是个 facade:对 agent 看是一个命令,内部 dispatch 到 crossref / openalex / openlibrary / google-books / dokobot-豆瓣等 source 适配器。Agent 不感知 source 切换,内部加新 source 不破坏调用方。

### 2.5 skill 显式编排,不藏 mini-pipeline

`quasi-citation run` 这类"一键 pipeline"是反模式 —— orchestration 应该在 skill 层显式列出每步,这样:
- skill 自己看得见全流程,能在任一步插埋点、重跑、debug
- 中间产物可以被人手单独使用
- 流程改动不需要改 CLI

### 2.6 有意识破例:skill 直接调 bin

skill 不必每一步都通过 agent。纯 I/O 步骤(如 `quasi-audit emit` / `quasi-citation parse`)skill 直接 Bash 调,不加 agent dispatch。理由:
- 这些步骤无业务判断
- agent dispatch 是 LLM 调用,有 token 成本和不可预测性
- skill 显式调 bin 反而更清晰

---

## 3. 四层清单

### Layer 0: Capability(底层能力)

| capability | 类型 | 实现层 | 内部归属 | 谁消费它 |
|---|---|---|---|---|
| **search** | I/O | bin `quasi-search` | `scripts/search/*` | discover-agent · scan-agent · vault-cross-check-agent |
| **audit** | I/O | bin `quasi-audit` | `scripts/audit/*` | audit-agent · `/quasi:wrap-up`(direct) · `/quasi:cross-check`(direct) |
| **citation** | I/O | bin `quasi-citation` | `scripts/citation/*` | `/quasi:wrap-up`(direct) |
| **download** | I/O | bin `quasi-download` | `scripts/download/*` | download-agent |
| **extract** | I/O | bin `quasi-extract` | `scripts/extract/*` | extract-agent |
| **proofread** | I/O | bin `quasi-proofread` | `scripts/proofread/*` | proofread-agent |
| **translate** | I/O | bin `quasi-translate` | `scripts/translate/*` | translate-agent |
| **analyze** | LLM | (无 bin) | agent 自含 | process-book / process-author / process-journal |
| **synthesize** | LLM | (无 bin) | agent 自含 | process-journal · citation-snowball · process-author(profile) |
| **topic-match** | LLM | (无 bin) | citation-agent v2 | `/quasi:wrap-up` |
| **cross-check-online** | LLM + 工具 | (无 bin) | vault-cross-check-agent(调 quasi-search) | `/quasi:cross-check` |

7 个 I/O 型能力 → 7 个 bin。4 个 LLM 型能力 → 由 agent 承载,不暴露为 bin。

### Layer 1: bin → scripts

| bin | 子命令 | scripts/ 路径 |
|---|---|---|
| `quasi-search` | `papers` / `books` / `cjk-books` / `bibinfo` / `fulltext` / `person` | `scripts/search/{search,crossref,openalex,openlibrary,google_books,google_scholar,annas_archive,dokobot_douban,dedupe}.py` |
| `quasi-audit` | (default) / `emit` / `check` / `fix` | `scripts/audit/{audit,scan,schema,autofix,bibtex}.py` |
| `quasi-citation` | `parse` / `resolve` / `render` / `apply` | `scripts/citation/{citation,parse,resolve,render,apply}.py` |
| `quasi-download` | (default) | `scripts/download/{download,annas,oa,ezproxy,wayback}.py` |
| `quasi-extract` | (default) | `scripts/extract/{extract,pdf,epub}.py` |
| `quasi-proofread` | (default) | `scripts/proofread/proofread.py` |
| `quasi-translate` | (default) | `scripts/translate/translate.py` |

### Layer 2: agent → bin

14 个 agent。9 个纯 LLM 不调 bin;5 个调 bin。

| agent | 调 bin | 备注 |
|---|---|---|
| **audit-agent** ✎ (原 typecheck-agent) | `quasi-audit fix` / `check` | 跑 audit 修复 + 报告 |
| **citation-agent v2** ✎ 重写 | (无) | 纯 LLM,离线判主题契合 |
| **vault-cross-check-agent** ★ 新 | `quasi-search bibinfo` · `quasi-audit emit`(读 biblio.json) | Phase B 唯一在线核实者 |
| **proofread-agent** | (无) | in-place edit |
| **analyze-agent** | (无) | per-section LLM |
| **overview-agent** | (无) | per-book LLM |
| **profile-agent** | (无) | per-author LLM |
| **synthesis-agent** | (无) | multi-text LLM |
| **discover-agent** | 当前内嵌 search 逻辑 → 第四波改调 `quasi-search` | 暂不动 |
| **scan-agent** | 同上 | 暂不动 |
| **download-agent** | `quasi-download` | |
| **extract-agent** | `quasi-extract` | |
| **translate-agent** | `quasi-translate` | |
| **setup-agent** | 环境检查 | 不属业务能力 |

### Layer 3: skill → agent + bin

7 个 user-facing skill。

| skill | dispatch agents | direct bin calls | 用途 |
|---|---|---|---|
| **`/quasi:wrap-up`** ✎ 重写 | proofread-agent × 节 · citation-agent × 批 | `quasi-audit emit` · `quasi-citation parse` / `resolve` / `render` | draft → review.html + .bib |
| **`/quasi:cross-check`** ★ 新 | vault-cross-check-agent × 批 | `quasi-audit emit` | vault ↔ 在线交叉验证 |
| **`/quasi:process-book`** | download-agent · extract-agent · analyze-agent × 章 · overview-agent | (无) | input → vault,一本书 |
| **`/quasi:process-author`** | discover-agent · download-agent × N · extract-agent × N · analyze-agent × N · overview-agent × N · profile-agent | (无) | input → vault,一位作者 |
| **`/quasi:process-journal`** | scan-agent · download-agent × N · extract-agent × N · analyze-agent × N · synthesis-agent | (无) | input → vault,一本期刊 |
| **`/quasi:citation-snowball`** | download-agent · extract-agent · scan-agent · download-agent × refs · extract-agent × refs · analyze-agent × refs · synthesis-agent | (无) | input → vault,从种子论文滚雪球 |
| **`/quasi:setup`** | setup-agent | (无) | infra setup |

### 关键变化对照

| 维度 | 老 | 新 |
|---|---|---|
| bin 数量 | 8(含 `quasi-typecheck` · `quasi-immersive-translate`,无 `quasi-citation apply`) | 7(typecheck → audit 改名扩职 · translate 改名 · citation 加 apply) |
| `typecheck` 角色 | 单职责 schema 校验 | `audit`:扫 + emit biblio + check schema + check slug↔fm + fix |
| `quasi-vault` | 计划引入 | **不引入**(biblio 进 audit,citation 改 read biblio.json) |
| `quasi-citation` 内部 | parse/resolve/render + run + 自己扫 vault | parse/resolve/render/apply;不扫 vault |
| citation-agent | 在线 + 全能(verify+vault+draft 多角色) | 离线 + 仅主题契合 |
| skill orchestration | `quasi-citation run` 一键 | wrap-up 显式编排:`audit emit` → `parse` → `resolve` → dispatch agent → `render` |
| vault-audit skill | 计划引入,跟 `quasi-audit` 重名 | 改名 `/quasi:cross-check`,只管在线交叉验证 |
| `quasi-immersive-translate` | 名字过长 | 改名 `quasi-translate` |

---

## 4. 端到端调用拓扑

### 4.1 `/quasi:wrap-up` 全链路

```
user → /quasi:wrap-up drafts/03-writing/差异.md
  │
  ▼ Phase 1 proofread
  └─ dispatch proofread-agent × 节(并发)
       └─ in-place edit + 校对记录块写到 draft 尾
  │
  ▼ Phase 2 citation
  ├─ step 0:  if biblio.json 缺失或过期:
  │           Bash: quasi-audit emit <vault-root>
  │              └─ scripts/audit/scan.py + bibtex.py
  │                 → vault-biblio.json (+ vault.bib if --emit-bib)
  ├─ step 1:  Bash: quasi-citation parse drafts/* -o parse.json
  │              └─ scripts/citation/parse.py
  ├─ step 2:  Bash: quasi-citation resolve parse.json
  │                  --biblio vault-biblio.json -o manifest.json
  │              └─ scripts/citation/resolve.py
  │                 4 层 fuzzy fallback (Tier 1-4)
  ├─ step 3:  Agent dispatch: citation-agent × M(batch_keys 分批,并发)
  │              └─ agent 内部:
  │                  · Read manifest.json + vault-biblio.json + mention context
  │                  · LLM 判主题契合(离线,无 web tool)
  │                  · Write verdict-NNN.json
  ├─ step 4:  Bash: quasi-citation render manifest.json verdicts/
  │                  -o review.html
  │              └─ scripts/citation/render.py
  │
  ▼ 用户审 review.html,导出 decisions.json
  │
  ├─ step 5:  Bash: quasi-citation apply decisions.json manifest.json
  │                  verdicts/ vault-biblio.json
  │              └─ scripts/citation/apply.py
  │                 → draft.patch + references.bib
  │
  ▼ Phase 3 summary
  └─ 出 wrap-up.html 串起 proofread 报告 + citation review
```

### 4.2 `/quasi:cross-check`(Phase B)

```
user → /quasi:cross-check
  │
  ├─ Bash: quasi-audit emit <vault-root>
  │       → vault-biblio.json
  │
  ├─ Agent dispatch: vault-cross-check-agent × M(并发)
  │       agent 内部:
  │       · Read vault-biblio.json 的本批 entries
  │       · Bash: quasi-search bibinfo --author X --year Y [--title T]
  │           ← scripts/search/* 多源 query + dedupe
  │       · 对照 vault 元数据 vs 在线 candidates,出 diff
  │       · Write cross-check-NNN.json
  │
  └─ 合 vault-online-diff.md → 人工审,改完重跑 quasi-audit emit 更新 biblio
```

### 4.3 input → vault 类 skill

`process-book` / `process-author` / `process-journal` / `citation-snowball` 共享 backbone:

```
discover/scan → download → extract → analyze → overview/profile/synthesis
```

各 skill 在前置(discover vs scan vs 无)和后置(单本 overview vs 全作者 profile vs 期刊 synthesis vs snowball 拓展)上有差异。第四波重构后,内部的 search 调用统一切到 `quasi-search`,不再各自实现。

---

## 5. 重构动作分组

### Group A — 底层补齐(纯新,不动现有 agent)

| # | 动作 | 尺寸 |
|---|---|---|
| A1 | bin `quasi-search`(系列子命令)+ `scripts/search/*` | M |
| A2 | bin `quasi-audit emit` 子命令 + `scripts/audit/{scan,bibtex}.py`(从 typecheck 内部抽出来) | S |
| A3 | bin `quasi-citation apply` 子命令 + `scripts/citation/apply.py` | S |
| A4 | agent `vault-cross-check-agent` | S |
| A5 | skill `/quasi:cross-check` | S |

### Group B — 中层瘦身(改现有 agent / scripts)

| # | 动作 | 尺寸 |
|---|---|---|
| B1 | rename `typecheck` → `audit`(bin · scripts · agent · 文档) | S |
| B2 | rename `quasi-immersive-translate` → `quasi-translate` | XS |
| B3 | rewrite `citation-agent` 为离线主题契合版 | S |
| B4 | `scripts/citation/resolve.py`:输入改读 `biblio.json`,加 Tier 3 fuzzy fallback | S |
| B5 | `scripts/citation/render.py`:重写,单决策列 + bib chooser 简化 | M |
| B6 | (第四波)`discover-agent` / `scan-agent` 内部 web 调用替换为 `quasi-search` | M |

### Group C — 上层显式编排

| # | 动作 | 尺寸 |
|---|---|---|
| C1 | `quasi-citation` 删 `run` 子命令 | XS |
| C2 | `/quasi:wrap-up` SKILL.md 重写,显式列 Phase 2 每步 | M |

---

## 6. 渐进路径(波次)

```
当前进行中
  └─ BTS 5 节 proofread + 旧 citation 跑完, 出第一版 .bib
     (用户人审,验收旧版可用性,锁定问题清单)

第一波:底层补齐 (Group A 全部 + B1/B2 改名)         ~1 周
  ├─ A2  quasi-audit emit          (biblio.json 落地)
  ├─ A1  quasi-search              (从 discover/scan 抽 search 逻辑, 不删它们)
  ├─ A3  quasi-citation apply
  ├─ B1  typecheck → audit 改名
  ├─ B2  immersive-translate → translate 改名
  └─ 不动任何上层 skill, 现有 skill 继续按旧路径跑

第二波:citation 链重写 (B3 + B4 + B5 + C1 + C2)     ~1 周
  └─ wrap-up::citation 切到新链,
     走 biblio.json + 离线 agent + 显式 orchestration
     ── 验收 = 重跑差异.md 跟旧版对比

第三波:Phase B (A4 + A5)                              ~3-5 天
  └─ /quasi:cross-check 上线,
     处理 vault ↔ 在线漂移
     ── 不阻塞主路

第四波(可选, 顺手做):discover/scan 重构 (B6)         不专门排期
  └─ 等它们各自要扩展功能时, 把内部 search 调用替换为 quasi-search
```

---

## 7. Trade-offs 与备选方案

### 7.1 为什么不全 rewrite

quasi 已有 12+ agent / 多个稳定 skill,全 rewrite 风险大、产出周期长、还要 regression。**渐进重构**:新链按新原则建,旧链顺手重构;新工作走新路径,旧 agent 等下次它们要改时再动。

### 7.2 为什么搜索沉 CLI 不做 search-agent

绝大多数搜索需求是 **structured query**(给定 author/year/title 找权威条目),CLI 已经能干。引入 search-agent 反而是无价值中间层 overhead。等出现 LLM-driven free-form search 需求(e.g. "找跟动物劳动相关的近五年专著")再考虑加。

### 7.3 为什么取消 `quasi-vault`,把 biblio 进 `audit`

`quasi-vault` 一开始的设想是 `biblio` + `audit` 两个子命令。深想:
- `audit` 跟 `typecheck` 做的事高度重叠(都扫 frontmatter 判健康),逻辑上是同一类
- `biblio` 是 audit 内部本来就要做的"frontmatter → 结构化中间产物",顺手暴露即可
- 单独起 `quasi-vault` 是无意义的命名层次

合并到 `quasi-audit` 后 bin 数从 8 减到 7,认知开销更小。

### 7.4 为什么 `typecheck` 改名 `audit` 而不是反过来

- "typecheck" 描述太窄,只暗示 schema 校验。新职责包括 emit biblio、slug↔fm 一致性、必填字段、autofix,合起来是"审计"
- "audit" 在英文里直接表达"全面体检",符合扩职后的实际能力
- agent 也跟着改名 `audit-agent`

### 7.5 为什么 vault 维护跟 wrap-up 解耦

vault 是跨 draft 复用的 ground truth,不应被某次写稿子任务驱动维护。绑定 wrap-up 会:
- 每次跑 wrap-up 都顺手改 vault,踩踏不同 session 的判断
- vault 跟在线不一致变成 wrap-up 阻塞

解耦后:
- vault 健康检查 = `quasi-audit`(本地,任何时候随手跑)
- vault 跟在线一致性 = `/quasi:cross-check`(周期性 / 怀疑时)
- draft 引用校对 = `/quasi:wrap-up`(写稿时)

三条路各自独立触发,只通过 `biblio.json` 这个 artifact 通信。

### 7.6 为什么 wrap-up 直接调 bin 而不全部经过 agent

`/quasi:wrap-up` 内部步骤 `quasi-audit emit` / `quasi-citation parse` / `resolve` / `render` 是纯 I/O,无业务判断。加 agent dispatch 会:
- 增加 token 成本
- 增加不可预测性(agent 可能误读 prompt)
- 反而模糊"这一步是机械操作"的事实

skill 显式 Bash 调 bin 更清晰。这是有意识的破例,跟"agent 是业务判断"原则不冲突 —— 因为这些步骤本来就**不是业务判断**。

---

## 8. Open Questions

待具体实现时再 iterate:

1. **`quasi-search` 多 source 优先级 / dedupe 策略可配置化**
   - 当前思路:source 命中同 DOI / 同 ISBN 时按硬编码优先级合并(crossref > openalex > openlibrary 等)。要不要做成 userConfig 可配置?

2. **`biblio.json` drift 检测策略**
   - wrap-up skill 怎么判断 biblio 过期?用 mtime 比 vault file? hash diff?定 TTL?
   - 缓存路径放 `<vault>/.quasi/biblio.json` 还是 `$CLAUDE_PLUGIN_DATA/biblio-cache/<vault-hash>.json`?倾向前者(跟着 vault 走)。

3. **多 draft `.bib` 全局合并**
   - 整本书 6 节各产 references.bib,如何 dedupe 合并成一个 master?走 apply 时合 / 走独立 CLI / wrap-up 自动?

4. **`quasi-citation` 是否提供 `--vault <root>` sugar**
   - 手动调用方便,但 wrap-up 用显式 `--biblio` 形式。要不要支持?

5. **`agent` dispatch `agent` 的能力**
   - 当前只 skill 能 dispatch agent。如果 `vault-cross-check-agent` 内部需要 dispatch 一个子 agent 做 fuzzy 消歧,如何做?目前唯一可行:skill 层做编排,agent 不嵌套。

6. **`quasi-search bibinfo` 的 source 选择参数**
   - `--kind paper|book|auto` 怎么定?默认 auto 时按 author/title 启发还是先查 crossref(快)再 fallback?

7. **`discover-agent` / `scan-agent` 第四波重构的具体迁移触发**
   - "顺手做"什么算"顺手"?要不要定一个 trigger:下次它们 schema 漂移或 bug 时一并改?

---

## 9. Acceptance Criteria

**主验收**:用重构后的 quasi 把 **BTS 整书(03-writing 下 6 节)跑通**,产出:

- 整书 `references.bib` 喂 LaTeX 编译无 missing key
- 每节 `review.html` 信息密度合理,审稿时间 ≤ 旧版的 70%
- `vault-biblio.json` 跟 vault 文件 schema 100% 合规(typecheck 等价行为)
- 无 v1 schema 漂移 bug(agent 自创字段 / JSON 转义错误)

**次验收**:

- `quasi-search bibinfo` 单 invoke 拿到 ≥ 3 source 的 candidates,dedupe 合理
- `/quasi:cross-check` 能在 BTS vault 上跑通,识别已知漂移条目(simondon-2017 / russell-1951 / bellacasa-2016 等)
- discover-agent / scan-agent 第四波重构前后行为一致(regression 通过)

---

## 10. 相关文档

- [ADR-001: citation 与 vault 解耦](./ADR-001-citation-vs-vault.md)(本文档的子集 / 前身,结论继承)
- `plugins/quasi/CLAUDE.md`(plugin 维护指南,版本历史)
- `skills/wrap-up/SKILL.md`(现状,第二波后更新)
- `agents/citation-agent.md`(v1,第二波后重写为 v2)

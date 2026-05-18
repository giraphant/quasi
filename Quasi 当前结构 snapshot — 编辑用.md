# Quasi 当前结构 snapshot — 编辑用

date: 2026-05-17
plugin version: 0.17.0
purpose: 一份当下真实状态的清单(不是 ADR/不是 future plan)。**右侧"备注 / 想改"列空白,你直接手写编辑或合并 ──**

---

## A. 所有 bin(实物) — 13 个

| bin                    | 内部 scripts         | 子命令                                          | 干啥                                                      | 备注                        |
| ---------------------- | ------------------ | -------------------------------------------- | ------------------------------------------------------- | ------------------------- |
| `quasi-search`         | scripts/search/    | (default)                                    | crossref / openlib / scholar 等多源搜索                      | 原本的期刊论文列表抓取相关功能本质上是这个的变体。 |
| `quasi-typecheck`      | scripts/typecheck/ | (default)                                    | vault schema 校验（纯脚本） vault 机械修复(全角半角等) vault 元数据生成 bib  |                           |
| `quasi-download`       | scripts/download/  | (default)                                    | OA / Anna's / EZProxy / Wayback 下载                      |                           |
| `quasi-extract`        | scripts/extract/   | (default)                                    | 1. 将各种原始文件（EPUB类）以及PDF类处理成MD 2. 切分章节回填目录                |                           |
| `quasi-translate`      | scripts/translate/ | (default)                                    | PDF 翻译                                                  |                           |
| `quasi-proofread`      | scripts/proofread/ | split / init / cleanup                       | 切节 + 校对记录块管理                                            |                           |
| `quasi-citation`       | scripts/citation/  | biblio / parse / resolve / render / emit-bib | 0.17.0 重构,biblio 扫 vault + draft 校引用                    |                           |
| `quasi-journal-fetch`  | scripts/journal/   | (default)                                    | 期刊论文列表抓取                                                |                           |
| `quasi-journal-report` | scripts/journal/   | (default)                                    | 期刊扫描评分报告                                                |                           |

## C. 所有 agent(实物) — 13 个

| agent             | 主要工作                             | 调哪些 bin                        | 被哪些 skill dispatch              | 备注 / 想改                                                        |
| ----------------- | -------------------------------- | ------------------------------ | ------------------------------- | -------------------------------------------------------------- |
| `analyse-agent`   | per-section LLM 分析               | (无)                            | process-book / author / journal | 名称改英式拼写                                                        |
| `citation-agent`  | 校 draft 引用,主题契合判断 (0.17.0 v2 离线) | (无)                            | wrap-up                         |                                                                |
| `discover-agent`  | 给定特定搜索关键词，找到相关结果并生成结构化响应         | search                         | process-author / snowball       |                                                                |
| `download-agent`  | 多源下载 OA/Anna's/EZProxy/Wayback   | quasi-download                 | process-\* / snowball           |                                                                |
| `extract-agent`   | PDF/EPUB → 章节 md                 | quasi-extract-\*               | process-\* / snowball           |                                                                |
| `synthesis-agent` | 各种综述                             | (无)                            | process-book / author           | 感觉有可能和 `profile-agent` 合并？需要优化 prompt；应该所有需要合成的任务都可以用这个来合成。    |
| `proofread-agent` | per-节 LLM 校对 (in-place edit)     | (无)                            | wrap-up                         |                                                                |
| `scan-agent`      | 期刊论文评分                           | (内嵌 search 逻辑)                 | process-journal                 | 暂时废弃，核心search部分应该可以用discover接手，journal 相关逻辑则可以在主进程处理。相关调整之后进行。 |
| `setup-agent`     | 环境检查 / 权限同步                      | (各种环境检查)                       | (手动)                            | 暂时废弃，之后准备重构                                                    |
| `synthesis-agent` | 多文本综述                            | (无)                            | process-journal / snowball      | 暂时废弃，之后准备重构 snowball 技能                                        |
| `translate-agent` | 沉浸式翻译 PDF                        | quasi-translate                | 用户 / process-author             |                                                                |
| `audit-agent`     | vault schema 漂移修复                | quasi-search / quasi-typecheck | 用户人手                            |                                                                |

---

## D. 所有 skill(实物) — 5 个

| skill                      | 调哪些 agent                                                                                                                           | 直接调哪些 bin                                                                    | 干啥                  | 备注 / 想改                   |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------- | ------------------------- |
| `/quasi:wrap-up`           | proofread-agent × 节 · citation-agent × 批                                                                                            | quasi-proofread · quasi-citation (0.17.0 后 subcommand 变了, SKILL.md **尚未更新**) | draft 收尾(校文字 + 校引用) | SKILL.md 跟 0.17.0 不匹配,要重写 |
| `/quasi:process-book`      | download-agent · extract-agent · analyze-agent × 章 · overview-agent                                                                 | (无,通过 agent 调)                                                               | 一本书入 vault          |                           |
| `/quasi:process-author`    | discover-agent · download-agent × N · extract-agent × N · analyze-agent × N · overview-agent × N · profile-agent                    | (无)                                                                          | 一位作者入 vault         |                           |
| `/quasi:process-journal`   | scan-agent · download-agent × N · extract-agent × N · analyze-agent × N · synthesis-agent                                           | (无)                                                                          | 一本期刊入 vault         |                           |
| `/quasi:citation-snowball` | download-agent · extract-agent · scan-agent · download-agent × refs · extract-agent × refs · analyze-agent × refs · synthesis-agent | (无)                                                                          | 从种子论文滚雪球            |                           |

---

## E. 你脑子里"打算改"的清单(放空白让你填)

### E1. 命名 / 合并

	(随便填,例如:)
	- quasi-extract-{epub,ocr,split} → 合到 quasi-extract,子命令 epub/ocr/split
	- quasi-autofix-mechanical → 并入 quasi-typecheck(or quasi-audit)
	- quasi-typecheck → 改名 quasi-audit, 扩职责
	- quasi-citation biblio 子命令 → 迁到 quasi-audit
	- quasi-journal-{fetch,report} → 合到 quasi-search 还是单独?

### E2. 新工具 / 新能力

	- bin/quasi-audit (新): emit / check / verify (online) / fix
	- bin/quasi-helpers (??): 强耦合 wrap-up 的 split/merge 类

### E3. agent 增删

	- audit-agent (新?) — 在线 cross-check vault
	- citation-agent v2 prompt 砍 bib-verify mode stub
	- discover-agent / scan-agent 内部 search 剥离到 quasi-search

### E4. skill 增删

	- /quasi:cross-check (新? 砍?)
	- /quasi:wrap-up SKILL.md 重写 (0.17.0 subcommand 对齐)
	- /quasi:wrap-up 加 Phase 0 vault audit 检查

### E5. processing/ 目录约定

	- processing/audit/{slug}.json (新) — 每个 vault entry 一份 audit state
	   schema: last_audited_at + checks.local + checks.online
	- processing/citation/{draft-stem}/biblio.json (现状: 跟 draft 强绑)
	   → 是不是应该升级到 vault 级别的 cache (一个 vault 一个 biblio)?

---

## F. 自由区(你写)

	(在这里写流程图 / 决策 / 任何想法,我会读这个 file 拿你的合并意图)

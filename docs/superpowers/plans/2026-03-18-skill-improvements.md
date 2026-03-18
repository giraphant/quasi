# Quasi Skill & Agent 改进计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 Anthropic 官方 skill 最佳实践，系统改进 quasi 的 skill 和 agent 质量。

**Architecture:** 分 7 个任务。核心改动：补硬约束、评分模板去重（唯一真相）、修复损坏引用、优化 description 触发条件、dispatcher context 卫生、agent/skill 文档结构标准化。

**Tech Stack:** Markdown only, no code changes.

---

## Chunk 1: 硬约束与 Gotchas

### Task 1: 补充 "每文本独立 agent" 硬约束

所有涉及并行 analyze-agent dispatch 的 skill 都缺少一条显式硬约束：禁止把多个文本合并到一个 analyze-agent 调用中。这导致 dispatcher 偶尔错误分派。

**Files:**
- Modify: `skills/process-book/SKILL.md`
- Modify: `skills/process-journal/SKILL.md`
- Modify: `skills/process-author/SKILL.md`
- Modify: `skills/citation-snowball/SKILL.md`

- [ ] **Step 1: 在 process-book/SKILL.md 的 `⚠ 硬约束` 段追加**

在现有三条硬约束之后添加：

```markdown
- **每个文本独立 dispatch 一个 analyze-agent**：禁止把多章合并到一个 agent 调用中。一章 = 一个 Agent() 调用。
```

- [ ] **Step 2: 在 process-journal/SKILL.md 的 `⚠ 硬约束` 段追加**

```markdown
- **每篇论文独立 dispatch 一个 analyze-agent**：禁止把多篇论文合并到一个 agent 调用中。一篇 = 一个 Agent() 调用。
```

- [ ] **Step 3: 在 process-author/SKILL.md 的 `⚠ 硬约束` 段追加**

```markdown
- **每个文本独立 dispatch 一个 analyze-agent**：禁止把多章/多篇论文合并到一个 agent 调用中。一个文本 = 一个 Agent() 调用。
```

- [ ] **Step 4: 在 citation-snowball/SKILL.md 的 `⚠ 硬约束` 段追加**

```markdown
- **每篇论文独立 dispatch 一个 analyze-agent**：禁止把多篇论文合并到一个 agent 调用中。一篇 = 一个 Agent() 调用。
```

- [ ] **Step 5: Commit**

```bash
git add skills/*/SKILL.md
git commit -m "fix: add explicit one-text-per-agent constraint to all workflow skills"
```

---

## Chunk 2: 模板去重与引用修复

当前问题：
- scan-agent.md 内嵌评分模板，与 `skills/process-journal/prompts/score-single-paper.md` 重复且内容略有不同
- shared/output-format.md 引用了不存在的 `skills/analyze/prompts/text-analysis.md`

注意：analyze-agent.md 的分析模板保持内嵌不变。子 agent 启动时模板必须在 context 中，抽取为外部文件会增加不遵循模板的风险。

### Task 2: 删除重复评分模板 + 修复损坏引用

**Files:**
- Delete: `skills/process-journal/prompts/score-single-paper.md`
- Modify: `shared/output-format.md`

评分模板只有 scan-agent 在用，唯一真相就是 scan-agent.md 内嵌的版本。删除多余的外部副本。同时修复 output-format.md 中指向不存在文件的引用。

- [ ] **Step 1: 删除 `skills/process-journal/prompts/score-single-paper.md`**

```bash
git rm skills/process-journal/prompts/score-single-paper.md
```

如果 `prompts/` 目录变空，一并删除。

- [ ] **Step 2: 修复 shared/output-format.md 的损坏引用**

将：
```
正文结构的权威定义见 `skills/analyze/prompts/text-analysis.md`。
```
改为：
```
正文结构的权威定义见 `agents/analyze-agent.md` 的「分析模板」段。
```

- [ ] **Step 3: Commit**

```bash
git add -A skills/process-journal/prompts/ shared/output-format.md
git commit -m "fix: remove duplicate scoring template, fix broken reference in output-format"
```

---

## Chunk 3: Skill Description 优化

当前的 description 描述的是"做什么"，但根据最佳实践，description 应该描述"什么时候触发"。Claude 在会话开始时扫描 description 来决定是否调用 skill。

### Task 3: 优化所有 skill 和 agent 的 description

**Files:**
- Modify: `skills/process-book/SKILL.md`
- Modify: `skills/process-journal/SKILL.md`
- Modify: `skills/process-author/SKILL.md`
- Modify: `skills/citation-snowball/SKILL.md`
- Modify: `agents/analyze-agent.md`
- Modify: `agents/extract-agent.md`
- Modify: `agents/download-agent.md`
- Modify: `agents/scan-agent.md`
- Modify: `agents/overview-agent.md`
- Modify: `agents/profile-agent.md`
- Modify: `agents/synthesis-agent.md`
- Modify: `agents/discover-agent.md`
- Modify: `agents/permissions-agent.md`

- [ ] **Step 1: 更新 4 个 skill 的 description**

process-book:
```yaml
description: >
  Use when the user says "处理这本书", "跑一下这本handbook", "总结这本",
  or wants to process an EPUB/PDF book into structured chapter summaries.
  Flat agent dispatch: extract-agent, analyze-agent ×N, overview-agent.
```

process-journal:
```yaml
description: >
  Use when the user says "处理期刊", "journal scan", or wants to scan,
  download, and analyze a journal issue end-to-end.
  Flat agent dispatch: scan-agent, download-agent, analyze-agent ×N, synthesis-agent.
```

process-author:
```yaml
description: >
  Use when the user says "处理作者", "process author", "跑一下这个学者",
  or wants to systematically process a scholar's representative works into a profile.
  Flat agent dispatch: discover, download, extract, analyze ×N, overview, profile.
```

citation-snowball:
```yaml
description: >
  Use when the user says "滚雪球", "citation chain", "expand references",
  or wants to build a reading corpus by iteratively tracing citations from a seed paper.
  Flat agent dispatch: download, analyze ×N per round, synthesis.
```

- [ ] **Step 2: 更新 9 个 agent 的 description（frontmatter）**

以下只列出变更的 description 值：

analyze-agent:
```
description: 分析单个学术文本（书籍章节或论文），生成结构化 markdown。由 workflow skill 的并行调度触发，每次只处理一个文本。
```

extract-agent:
```
description: 从 EPUB/PDF 提取章节级纯文本。由 process-book/process-author 在提取阶段前台调用。自包含提取+验证+修复。
```

download-agent:
```
description: 按 DOI/MD5/manifest/scan.md 下载学术文件。由各 workflow skill 在获取阶段前台调用。支持 OA 级联、Anna's Archive、EZProxy、Wayback。
```

scan-agent:
```
description: 抓取期刊论文列表并逐篇评分，生成 scan.md 报告。由 process-journal Step 1 前台调用。
```

overview-agent:
```
description: 读取一本书的所有章节分析 (ch*.md)，生成全书概览 (00-overview.md)。由 process-book/process-author 在分析完成后前台调用。
```

profile-agent:
```
description: 读取所有书籍概览和论文分析，生成作者级学术档案 profile.md。由 process-author Phase 5 前台调用。
```

synthesis-agent:
```
description: 读取多篇分析生成综合报告+阅读列表。由 process-journal/citation-snowball 最终阶段前台调用。也支持知识库更新模式。
```

discover-agent:
```
description: 为指定作者搜索最重要的书籍和论文，生成 manifest.json。由 process-author Phase 1 前台调用。
```

permissions-agent:
```
description: 读取 .claude/settings.local.json，合并 quasi 所需权限，清理废弃权限。手动调用。幂等运行。
```

- [ ] **Step 3: Commit**

```bash
git add skills/*/SKILL.md agents/*.md
git commit -m "refactor: rewrite descriptions as trigger conditions per skill best practices"
```

---

## Chunk 4: Dispatcher Context 卫生

### Task 5: 添加 context 卫生硬约束

Dispatcher 在轮询和接收通知时会累积无用的 context。通过硬约束指令提醒 dispatcher 保持 context 干净。零架构改动。

如果未来 context 问题严重到指令层面不够用，参考 `docs/references/2026-03-18-harness-engineering-learn-cc.md` 中的 events.jsonl push 模型方案。

**Files:**
- Modify: `skills/process-book/SKILL.md`
- Modify: `skills/process-journal/SKILL.md`
- Modify: `skills/process-author/SKILL.md`
- Modify: `skills/citation-snowball/SKILL.md`

- [ ] **Step 1: 在所有 4 个 skill 的 `⚠ 硬约束` 段追加 context 卫生规则**

```markdown
- **Dispatcher context 卫生**：
  - Glob 轮询只关注完成数 vs 总数，不要逐一列举文件名
  - 后台 agent 完成通知是冗余信息，收到后不需要额外处理
  - 每个阶段完成后不要回顾前序输出，关键状态已在磁盘上
```

- [ ] **Step 2: Commit**

```bash
git add skills/*/SKILL.md
git commit -m "fix: add context hygiene rules to dispatcher skills"
```

---

## Chunk 5: Agent 文档结构标准化

### Task 6: 统一 agent markdown 结构

审计发现 9 个 agent 的段落命名、顺序、覆盖范围都不一致。制定标准模板并统一。

**标准 Agent 模板结构：**

```
---
frontmatter (name, description, tools, model)
---

一句话角色定义

## 输入参数（调用方在 prompt 中提供）

## 脚本                    ← 有外部脚本调用时才需要
## 执行流程                ← 统一用"执行流程"，不用"执行"/"执行步骤"
⚠ 路径提醒放在执行流程开头  ← 统一位置

## [模板段]                ← agent 特有的模板（分析模板/评分模板/输出格式/综合报告模板等）
                            保持各 agent 的特有名称，不强制统一

## 输出协议                ← 所有 agent 都要有
```

**原则：**
- 只做重命名和补缺，不改内容
- 各 agent 的特有段落（分析模板、评分模板、manifest 格式等）保留原名
- 不加不需要的段落（没有脚本调用就不加脚本段）

**Files:** 所有 9 个 agent .md 文件

- [ ] **Step 1: 统一段落命名**

| Agent | 当前 | 改为 |
|-------|------|------|
| analyze-agent | `## 执行` | `## 执行流程` |
| download-agent | `## 执行` | `## 执行流程` |
| scan-agent | `## 执行` | `## 执行流程` |
| discover-agent | `## 执行` | `## 执行流程` |
| synthesis-agent | `## 执行` | `## 执行流程` |（注：含子段 `### synthesis 模式` / `### kb-update 模式`，保留不动）
| overview-agent | `## 执行步骤` | `## 执行流程` |
| profile-agent | `## 执行步骤` | `## 执行流程` |

extract-agent 和 permissions-agent 已经是 `## 执行流程`，不用改。

- [ ] **Step 2: 统一 ⚠ 路径提醒位置**

所有有路径提醒的 agent（analyze, extract, download, scan, overview, profile, synthesis, discover），将 `⚠ **Write/Read 工具要求绝对路径**` 统一放在 `## 执行流程` 段的第一行。当前有的在输入参数后、有的在脚本后，移到统一位置。

- [ ] **Step 3: 补缺输出协议**

以下 6 个 agent 缺少输出协议，添加：

**scan-agent** — 添加在评分模板之后：
```markdown
## 输出协议

生成的 scan.md 报告即为输出。最后一条消息包含：

\```
SCAN_RESULT:
- papers_found: N
- papers_scored: M
- output: {output_path}
- status: success | error
\```
```

**overview-agent** — 添加在输出格式之后：
```markdown
## 输出协议

\```
OVERVIEW_RESULT:
- chapters_analyzed: N
- output: {output_dir}/00-overview.md
- status: success | error
\```
```

**profile-agent** — 添加在输出格式之后：
```markdown
## 输出协议

\```
PROFILE_RESULT:
- books_covered: N
- papers_covered: M
- output: {output_path}
- status: success | error
\```
```

**synthesis-agent** — 添加在知识库更新模板之后：
```markdown
## 输出协议

\```
SYNTHESIS_RESULT:
- papers_analyzed: N
- output: {output_path}
- reading_list: {reading_list_path}
- status: success | error
\```
```

**discover-agent** — 添加在 manifest 格式之后：
```markdown
## 输出协议

\```
DISCOVER_RESULT:
- books_found: N
- papers_found: M
- output: {manifest_path}
- status: success | error
\```
```

**analyze-agent** — 添加在写作要求之后：
```markdown
## 输出协议

\```
ANALYZE_RESULT:
- output: {output 路径}
- type: A | B
- status: success | error
\```
```

- [ ] **Step 4: Commit**

```bash
git add agents/*.md
git commit -m "refactor: standardize agent doc structure — unified headings, path warnings, output protocols"
```

---

## Chunk 6: Skill 文档补齐

### Task 7: 补齐 skill 缺失段落

process-book 有"目录结构"段，其他 3 个 skill 没有。补齐。

**Files:**
- Modify: `skills/process-journal/SKILL.md`
- Modify: `skills/process-author/SKILL.md`
- Modify: `skills/citation-snowball/SKILL.md`

- [ ] **Step 1: 为 process-journal 添加目录结构段**

在断点续跑之后添加：

```markdown
## 目录结构

\```
vault/journals/{journal-name}-scan.md
vault/journals/{journal-name}-synthesis.md
vault/journals/{journal-name}-reading-list.md
vault/journals/{journal-name}/
└── {slug}.md
/tmp/{journal-name}-pdfs/
└── *.pdf
\```
```

- [ ] **Step 2: 为 process-author 添加目录结构段**

```markdown
## 目录结构

\```
vault/authors/{author-name}/
├── manifest.json
├── profile.md
└── papers/
    └── {slug}.md
vault/monographs/{book-slug}/
├── 00-overview.md
└── ch{NN}-{title}.md
processing/chapters/{book-slug}/
├── manifest.json
└── *.txt
sources/{book-slug}.*
\```
```

- [ ] **Step 3: 为 citation-snowball 添加目录结构段**

```markdown
## 目录结构

\```
vault/journals/{topic-slug}/
├── manifest.json
├── seed.md
├── {paper-key}.md
├── {topic-slug}-synthesis.md
└── {topic-slug}-reading-list.md
/tmp/{topic-slug}-pdfs/
└── *.pdf
\```
```

- [ ] **Step 4: Commit**

```bash
git add skills/*/SKILL.md
git commit -m "docs: add directory structure section to all workflow skills"
```

---

## Chunk 7: marketplace.json 版本同步

### Task 8: 修复版本不一致

marketplace.json 还是 0.4.2，plugin.json 已经是 0.4.3。

**Files:**
- Modify: `.claude-plugin/marketplace.json`
- Modify: `.claude-plugin/plugin.json` (version bump to 0.5.0)

- [ ] **Step 1: 读取 marketplace.json 当前内容**

- [ ] **Step 2: 将 plugin.json 和 marketplace.json 的版本统一更新为 0.5.0**

这次改动涉及多个 skill 和 agent 的结构性改进，值得 minor 版本号跳升。

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore: bump version to 0.5.0 — skill improvements based on Anthropic best practices"
```

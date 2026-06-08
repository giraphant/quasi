---
name: quasi:process-topic
description: Use when the user wants to build a navigable topic review and reading-list index over the vault from a research question, theme, or optional seed paper.
---

# Process Topic — 话题处理

## 任务

用滚雪球（snowball）研究法发现与梳理文献脉络。

## 输入

从用户请求中归一化出:

- `topic_slug`: topic 目录名(`vault/topics/{topic_slug}/`)。
- `topic_desc` / 研究问题: 主题描述(主入口)。
- `seed`(可选): 种子论文 DOI;不再是必需入口。
- `mode`: `generate`(首次生成,默认) 或 `refine`(对已有 topic 页做续写/改写/重构)。
  用户明确要求"更新/改写/重做/换框架/续写"已有 topic,或目标文件已存在且请求是修订,即 `refine`。

## 硬约束

- **主进程只编排。** 归主进程的:发现候选、写 manifest、读已落地条目的核心引用做滚雪球、收口。`process-paper` / `process-book` / `process-author` / `synthesis` / `audit` 及其任何子步骤,一律经 `superset agents create` 委派(见 Dispatch 模板)。本 skill 的全部价值就是 tree dispatch。
- **委派异步 fire,完成靠产物判。** `superset agents create` 发完即返回 `sessionId`;完成判定靠 vault 产物——首次生成看文件存在,续写/改写(`refine`)看哨兵文件出现且目标 mtime 变新(见 poll-agent 合同)。
- **完成判定交给 poll-agent。** 每批委派后派一个干净上下文的 `general-purpose` poll-agent 轮询产物(见 Agent / Helper 合同),它在自己上下文里循环,只回传紧凑的 `{present, missing}`/`{done, pending}`。poll 超时即视为该批失败,报告用户并按 mode 重派。
- **长任务走 prompt 文件。** 综述 / 审计 / 续写这类长 prompt 写到 `.quasi/process-topic-runs/{slug}.prompt.md`,再用一句短 prompt 让 agent 读它执行(见 prompt-file 形态)。
- `$SUPERSET_WORKSPACE_ID` 由会话注入,缺失即报错并停。

## 状态

主进程 owns `vault/topics/{topic_slug}/manifest.json`:

```json
{
  "topic": "...",
  "topic_slug": "...",
  "topic_desc": "...",
  "seed_doi": null,
  "mode": "generate | refine",
  "rounds_completed": 0,
  "final_status": "missing | generated | needs_update | updated",
  "discovery_rounds": [
    { "round": 0, "queries": ["..."], "source": "paper_query" }
  ],
  "items": {
    "<slug>": {
      "kind": "paper | book | author",
      "source": "paper_query | kagi | citation | user",
      "vault_path": "...",
      "title": "...", "authors": ["..."], "year": 2023, "doi": "...",
      "round": 1,
      "status": "discovered | processing | analysed | failed",
      "failure_note": null
    }
  }
}
```

item status enum:

- `discovered` — 候选,还没委派处理。
- `processing` — 已 fire `superset agents create`,等 vault 产物落地。
- `analysed` — 已落 vault(`vault_path` 存在),可读核心理论段取引用。
- `failed` — 委派/分析失败,带 `failure_note`。

`final_status` enum(收口页 `00-overview.md` / `01-resources.md` 的状态):

- `missing` — 还没生成。
- `generated` — 首次生成已落地。
- `needs_update` — 用户请求续写/改写,现有页需更新(`mode=refine` 时进入此态)。
- `updated` — 续写/改写已落地并经哨兵 + mtime 确认。

vault_path by kind:

| kind | vault_path | 首次判完成信号 |
|------|-----------|-----------|
| paper | `vault/papers/{slug}.md` | 文件存在 |
| book | `vault/books/{slug}/00-overview.md` | 文件存在 |
| author | `vault/authors/{slug}.md` | 文件存在 |

单条目(paper/book/author)是首次生成,用"文件存在"判完成即可。收口页在 `refine` 下是改写已有文件,改用哨兵 + mtime(见 poll-agent 合同)。

`round` 控制本轮扩展;`rounds_completed` 只在本轮全部 analysed + 引用提取完成后递增。

## Agent / Helper 合同

| 委派对象 | 怎么派 | 职责 | 返回 |
|---------|--------|------|------|
| `search-agent` | `Agent("quasi:search-agent", foreground=True)` | Phase 0 发现候选论文 | `SEARCH_RESULT`,主进程写 manifest |
| `process-paper` / `process-book` / `process-author` / `synthesis` / `audit` | `superset agents create`(Dispatch 模板) | 单条目处理 / 综述 / 审计——异步 fire,不阻塞 | 产物落 vault,完成信号见 poll-agent 合同 |
| `poll-agent` | `Agent("general-purpose")`(每批一个) | 在干净上下文里轮询本批 vault 产物是否落地,完成或超时即返回 | `{present:[...], missing:[...], elapsed_s}` 或 refine 模式 `{done:[...], pending:[...], elapsed_s}` |

**poll-agent 合同**:主进程 fire 完一批 `superset agents create` 后,派**一个** `general-purpose` agent,把本批的判完成规格交给它。轮询循环都在 agent 自己的上下文里,主进程只收一个紧凑结果。poll-agent **只读不写**:不碰 manifest、不碰 vault,只回报完成性。

poll-agent 支持三种判完成模式,主进程按任务选:

- `exists`(首次生成,单条目 / 首次收口):给它一组 `vault_path`,每 60s `test -f` 检查;全部出现或 1800s(30 分钟)超时即停,回 `{present, missing, elapsed_s}`。
- `mtime_changed`(改写已有文件):给它一组 `{path, baseline_mtime}`(baseline = fire 前主进程记录的 mtime);每 60s 检查 `mtime > baseline_mtime`;全部变新或超时即停,回 `{done, pending, elapsed_s}`。
- `sentinel`(续写/改写收口):给它哨兵路径 `.quasi/process-topic-runs/{run_id}.json` 和目标文件的 `{path, baseline_mtime}`;哨兵出现**且**每个目标 mtime 变新才算 done(两者合判:mtime 是改动落地的确证)。

主进程拿到结果后:完成的条目升 `analysed` / `final_status=updated`;未完成的留 `processing` / `needs_update`,交下一轮 / 断点续跑重 fire,或(poll 超时)按硬约束当失败处理报告用户。

## 工作流

```
输入: topic_slug + topic_desc + mode (seed DOI 可选)
│
├─ Phase 0  DISCOVER
│   Agent("quasi:search-agent", foreground=True) → 候选论文
│   主进程补充: 搜不到/非结构化 → kagi + dokobot → 补 book / author 条目
│   → 候选写 manifest.items (status=discovered)
│
├─ Phase 1-N  SNOWBALL (循环, 最多 5 轮)
│   │
│   ├─ DISPATCH: 对每个 status=discovered 的条目:
│   │     kind == paper  → dispatch process-paper in Superset CLI
│   │     kind == book   → dispatch process-book  in Superset CLI
│   │     kind == author → dispatch process-author in Superset CLI
│   │     → manifest status=processing (并发上限 5)
│   │
│   ├─ POLL: 派 poll-agent(mode=exists)轮询本批 vault 产物 → present 升 status=analysed
│   │
│   ├─ SNOWBALL: 读各条目核心引用 → dedupe 新条目进 manifest (新 round, source=citation)
│   │
│   └─ new_refs == 0 → 退出循环
│
├─ DEAD-END  RE-DISCOVER (用户闸门)
│   AskUserQuestion 提议查询词
│   → 拒 → FINAL;  选 → 回 DISCOVER 新种子 → 回 SNOWBALL
│
├─ FINAL  dispatch synthesis in Superset CLI
│   mode=generate → 写 00-overview.md ([[wikilink]]) + 01-resources.md
│                   → poll-agent(mode=exists) → final_status=generated
│   mode=refine   → 写 prompt 文件,prompt-file 委派改写已有两页 + 写哨兵
│                   → poll-agent(mode=sentinel+mtime) → final_status=updated
│
└─ AUDIT  dispatch audit in Superset CLI
    → Marple open 00-overview.md
```

## Dispatch 模板

所有委派都用 `superset agents create`,异步 fire,完成靠 poll-agent 判。

所有 dispatch prompt 必须以前置约束开头,防止下游 agent 把内容处理任务误判为软件开发分支工作:

```text
This is a vault/content processing task, not a software development task. Do not create, enter, or switch git worktrees or branches. Do not run git worktree, git switch, or git checkout. Work only in the current checkout and write only the requested vault outputs. If you believe a separate branch/worktree is needed, stop and report cwd + branch instead.
```

### 短 prompt 形态(首次生成单条目 / 首次收口)

短任务直接把 prompt 放 argv。

#### kind == paper → dispatch process-paper in Superset CLI

```bash
superset agents create \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "This is a vault/content processing task, not a software development task. Do not create, enter, or switch git worktrees or branches. Do not run git worktree, git switch, or git checkout. Work only in the current checkout and write only the requested vault outputs. If you believe a separate branch/worktree is needed, stop and report cwd + branch instead. Run /quasi:process-paper for DOI {doi} (slug {slug}). Write vault/papers/{slug}.md; tag frontmatter topics: [{topic_slug}]; report final path + status." \
  --json --quiet
```

#### kind == book → dispatch process-book in Superset CLI

```bash
superset agents create \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "This is a vault/content processing task, not a software development task. Do not create, enter, or switch git worktrees or branches. Do not run git worktree, git switch, or git checkout. Work only in the current checkout and write only the requested vault outputs. If you believe a separate branch/worktree is needed, stop and report cwd + branch instead. Run /quasi:process-book for slug {slug} (title {title}, authors {authors}). Write vault/books/{slug}/00-overview.md; tag frontmatter topics: [{topic_slug}]; report final path + status." \
  --json --quiet
```

#### kind == author → dispatch process-author in Superset CLI

```bash
superset agents create \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "This is a vault/content processing task, not a software development task. Do not create, enter, or switch git worktrees or branches. Do not run git worktree, git switch, or git checkout. Work only in the current checkout and write only the requested vault outputs. If you believe a separate branch/worktree is needed, stop and report cwd + branch instead. Run /quasi:process-author for author {slug} (full_name {authors}). Build author profile from representative books and papers. Write vault/authors/{slug}.md; tag frontmatter topics: [{topic_slug}]; report final path + status." \
  --json --quiet
```

### prompt-file 形态(长任务 / 续写改写)

主进程先把完整任务写到 `.quasi/process-topic-runs/{slug}.prompt.md`,再用一句短 prompt 让 agent 读它执行。任务文件里写明:覆盖目标文件、改完写哨兵。

```bash
# 1. 主进程写任务文件 .quasi/process-topic-runs/{slug}.prompt.md(含完整改写说明、目标文件清单、哨兵写法)
# 2. fire 短 prompt:
superset agents create \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "This is a vault/content processing task, not a software development task. Do not create, enter, or switch git worktrees or branches. Do not run git worktree, git switch, or git checkout. Work only in the current checkout and write only the requested vault outputs. If you believe a separate branch/worktree is needed, stop and report cwd + branch instead. Read .quasi/process-topic-runs/{slug}.prompt.md and perform it exactly. Write the sentinel .quasi/process-topic-runs/{run_id}.json when complete." \
  --json --quiet
```

替代形态:`--attachment <task_file>` + 短 prompt `Read the attached task file and perform it exactly.`。Superset 会把附件上传到 host 并在 prompt 里注入一段 `# Attached files` 给出绝对路径,agent 据此读取。优先用 prompt-file(路径确定),附件形态作备选。

### 哨兵约定

续写/改写任务的任务文件要让 agent 在改完后写哨兵 `.quasi/process-topic-runs/{run_id}.json`:

```json
{"status":"done","topic_slug":"{topic_slug}","updated":["vault/topics/{topic_slug}/00-overview.md","vault/topics/{topic_slug}/01-resources.md"]}
```

poll-agent 用 `sentinel`+`mtime_changed` 合判:哨兵出现且每个 `updated` 文件 mtime 变新才算 done。

### FINAL → dispatch synthesis in Superset CLI

#### mode == generate(首次生成,短 prompt)

```bash
superset agents create \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "This is a vault/content processing task, not a software development task. Do not create, enter, or switch git worktrees or branches. Do not run git worktree, git switch, or git checkout. Work only in the current checkout and write only the requested vault outputs. If you believe a separate branch/worktree is needed, stop and report cwd + branch instead. Synthesize topic review for '{topic_desc}' (slug {topic_slug}). Read vault/papers/ and vault/books/ entries tagged topics: [{topic_slug}]. Write vault/topics/{topic_slug}/00-overview.md (frontmatter: {type: topic, title: {topic}, kind: overview}) with [[wikilink]] references to vault entries. Write vault/topics/{topic_slug}/01-resources.md (frontmatter: {type: topic, title: {topic}, kind: resources}) with categorized reading list. title 必填,与 H1 一致。report final path + status." \
  --json --quiet
```

完成:poll-agent(mode=exists,两页路径)→ `final_status=generated`。

#### mode == refine(续写/改写,prompt-file + 哨兵)

主进程先把改写说明(新框架 `topic_desc`、要改的具体两页、保留/重写哪些段、写哨兵)写进 `.quasi/process-topic-runs/{slug}.prompt.md`,记录两页 fire 前的 `baseline_mtime`,再:

```bash
superset agents create \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "This is a vault/content processing task, not a software development task. Do not create, enter, or switch git worktrees or branches. Do not run git worktree, git switch, or git checkout. Work only in the current checkout and write only the requested vault outputs. If you believe a separate branch/worktree is needed, stop and report cwd + branch instead. Read .quasi/process-topic-runs/{slug}.prompt.md and perform it exactly. Overwrite vault/topics/{topic_slug}/00-overview.md and 01-resources.md with the new framing. Write the sentinel .quasi/process-topic-runs/{run_id}.json when done." \
  --json --quiet
```

完成:poll-agent(mode=sentinel+mtime,两页 + 哨兵)→ `final_status=updated`。

### AUDIT → dispatch audit in Superset CLI

```bash
superset agents create \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "This is a vault/content processing task, not a software development task. Do not create, enter, or switch git worktrees or branches. Do not run git worktree, git switch, or git checkout. Work only in the current checkout and write only the requested vault outputs. If you believe a separate branch/worktree is needed, stop and report cwd + branch instead. Run /quasi:audit on path vault/topics/{topic_slug}/. Check all generated topic pages. Apply local fixes if safe, escalate if not. report path + status." \
  --json --quiet
```

### POLL → dispatch poll-agent(general-purpose,每批一个)

```
Agent("general-purpose", prompt:
  "只读轮询本批委派产物是否落地。每 60 秒检查一遍,
   全部完成或累计 1800 秒(30 分钟)超时即停。

   mode=exists(首次生成):用 `test -f` 检查这些路径是否存在:
   {batch_vault_paths}
   回传 {present:[已存在], missing:[仍缺], elapsed_s:N}。

   mode=sentinel+mtime(续写/改写收口):
   哨兵: .quasi/process-topic-runs/{run_id}.json
   目标(path 与 fire 前 baseline_mtime):
   {targets_with_baseline_mtime}
   只有哨兵存在 *且* 每个目标的当前 mtime > 其 baseline_mtime 才算 done。
   回传 {done:[已更新], pending:[未更新], elapsed_s:N}。")
```

主进程拿到结果后按 status 更新 manifest;超时未完成的当失败报告并按 mode 重派。

## 执行流程

```
1. 检查 $SUPERSET_WORKSPACE_ID — 缺失即报错并停
2. 读取或创建 manifest.json;归一化 mode(generate / refine)与 final_status
3. Phase 0: Agent("quasi:search-agent") 发现候选 → 写 manifest
   搜不到 → 主进程 kagi + dokobot 补充 book/author 条目
4. SNOWBALL 循环 (最多 5 轮):
   a. 收集 status=discovered + stranded processing 条目
   b. 按 kind 选择 dispatch 模板(短 prompt 形态)→ superset agents create(异步 fire)
   c. 并发控制: processing 数 >= 5 时先派 poll-agent 等一批落地
   d. 派 poll-agent(mode=exists,本批 vault_path)轮询 → present 升 status=analysed,missing 留 processing
   e. 读各 analysed 条目的核心引用 → dedupe 新条目 (新 round)
   f. new_refs == 0 → 退出
5. DEAD-END: AskUserQuestion 问用户是否再发现
6. FINAL:
   mode=generate → dispatch synthesis(短 prompt)→ poll-agent(exists)等两页落地 → final_status=generated
   mode=refine   → 写 .quasi/process-topic-runs/{slug}.prompt.md + 记录两页 baseline_mtime
                   → dispatch synthesis(prompt-file + 哨兵)→ poll-agent(sentinel+mtime)→ final_status=updated
7. AUDIT: dispatch audit in Superset CLI
8. Bash: marple-cli open vault/topics/{slug}/00-overview.md
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 0 | `manifest.json` 存在且有 `items` | 存在则跳发现 |
| Phase N | `rounds_completed >= N` | 跳已完成轮 |
| 单条目 | `items[slug].status == analysed` 且 vault_path 存在 | 跳已处理(不重复委派) |
| FINAL | `final_status` 状态机 | `generated`/`updated` 跳;`missing`/`needs_update` 不跳 |
| AUDIT | 幂等,可重复跑 | clean 时几乎无成本 |

**FINAL 跳过规则**:`final_status ∈ {generated, updated}` 才跳综述。`mode=refine`(用户要续写/改写)时 `final_status` 置 `needs_update`,走 FINAL 改写;改写经哨兵 + mtime 确认后置 `updated`。

委派是异步 fire:续跑时把 `status == processing` 但 vault_path 已存在的条目提升为 `analysed`;仍缺产物的重新 fire。`refine` 收口的续跑:哨兵在且两页 mtime 已变新 → `updated`;否则重写 prompt 文件重 fire。

## 输出

```
vault/topics/{slug}/
├── manifest.json        ← 编排状态(不渲染给用户)
├── 00-overview.md       ← 综述(核心产物,带 [[wikilink]] 跳转)
├── 01-resources.md      ← 阅读清单总目(带跳转)
└── 02+ (按需子页)        ← type: topic / kind: resources
vault/papers/{slug}.md            ← 论文(委派 process-paper,frontmatter 带 topics:[slug])
vault/books/{slug}/00-overview.md ← 书(委派 process-book,frontmatter 带 topics:[slug])
vault/authors/{slug}.md           ← 作者(委派 process-author,frontmatter 带 topics:[slug])
.quasi/process-topic-runs/{slug}.prompt.md   ← refine 任务文件(prompt-file 委派用,编排中间产物)
.quasi/process-topic-runs/{run_id}.json      ← 完成哨兵(编排中间产物,不渲染给用户)
```

topic 目录只放 manifest + 索引页,不囤分析副本(分析在 vault/papers/ 和 vault/books/ 里)。`vault/topics/` 与 `vault/journals/` 严格分层。

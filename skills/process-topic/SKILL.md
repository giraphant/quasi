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

## 硬约束

- **主进程只编排,绝不亲自处理。** 归主进程的只有:发现候选、写 manifest、读已落地条目的核心引用做滚雪球、收口。`process-paper` / `process-book` / `process-author` / `synthesis` / `audit` 以及它们的任何子步骤,**一律**经 `superset agents run` 委派(见 Dispatch 模板)——主进程不得自行 `Run /quasi:process-*`,不得直接跑 `quasi-*` 处理管线。本 skill 的全部价值就是 tree dispatch;主进程亲自下场是最常见的失稳来源,务必克制。
- `$SUPERSET_WORKSPACE_ID` 由会话注入;**缺失即报错并停**,不要用 `superset workspaces list --local` 猜。
- **禁止用 TaskOutput 检查委派**:会卡住。完成判定改派一个上下文干净的 `poll-agent`(`general-purpose`)轮询 vault 产物(见 Agent / Helper 合同),主进程**不**在自己上下文里 Glob 轮询——委派任务可能跑很久,逐轮 Glob 的目录列表会把主进程上下文撑爆且费 token。poll-agent 在自己的上下文里循环,只回传一个紧凑的 `{present, missing}`。

## 状态

主进程 owns `vault/topics/{topic_slug}/manifest.json`:

```json
{
  "topic": "...",
  "topic_slug": "...",
  "topic_desc": "...",
  "seed_doi": null,
  "rounds_completed": 0,
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

status enum:

- `discovered` — 候选,还没委派处理。
- `processing` — 已 fire `superset agents run`,等 vault 产物落地。
- `analysed` — 已落 vault(`vault_path` 存在),可读核心理论段取引用。
- `failed` — 委派/分析失败,带 `failure_note`。

vault_path by kind:

| kind | vault_path | 判完成信号 |
|------|-----------|-----------|
| paper | `vault/papers/{slug}.md` | 文件存在 |
| book | `vault/books/{slug}/00-overview.md` | 文件存在 |
| author | `vault/authors/{slug}.md` | 文件存在 |

`round` 控制本轮扩展;`rounds_completed` 只在本轮全部 analysed + 引用提取完成后递增。

## Agent / Helper 合同

| 委派对象 | 怎么派 | 职责 | 返回 |
|---------|--------|------|------|
| `search-agent` | `Agent("quasi:search-agent", foreground=True)` | Phase 0 发现候选论文 | `SEARCH_RESULT`,主进程写 manifest |
| `process-paper` / `process-book` / `process-author` / `synthesis` / `audit` | `superset agents run`(Dispatch 模板) | 单条目处理 / 综述 / 审计——异步 fire,不阻塞 | 产物落 vault,完成信号 = vault_path 存在 |
| `poll-agent` | `Agent("general-purpose")`(每批一个) | 在干净上下文里轮询本批 vault 产物是否落地,完成或超时即返回 | `{present:[...], missing:[...], elapsed_s}` |

**poll-agent 合同**:主进程 fire 完一批 `superset agents run` 后,派**一个** `general-purpose` agent,把本批每个条目的 `vault_path` 清单交给它。agent 的任务:每 60s 用 `ls`/`test -f` 检查每个路径,全部出现或累计 30 分钟(1800s)超时即停,回传 `{present, missing, elapsed_s}`。轮询循环都在 agent 自己的上下文里,主进程只收一个紧凑结果。主进程据此把 `present` 条目升为 `analysed`,`missing` 留 `processing`(交给下一轮 / 断点续跑重 fire)。poll-agent **只读不写**:不碰 manifest、不碰 vault,只回报路径存在性。

## 工作流

```
输入: topic_slug + topic_desc (seed DOI 可选)
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
│   ├─ POLL: 派 poll-agent 轮询本批 vault 产物 → present 升 status=analysed
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
│   → 00-overview.md ([[wikilink]]) + 01-resources.md
│
└─ AUDIT  dispatch audit in Superset CLI
    → Marple open 00-overview.md
```

## Dispatch 模板

### kind == paper → dispatch process-paper in Superset CLI

```bash
superset agents run \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "Run /quasi:process-paper for DOI {doi} (slug {slug}). Write vault/papers/{slug}.md; tag frontmatter topics: [{topic_slug}]; report final path + status." \
  --json --quiet
```

### kind == book → dispatch process-book in Superset CLI

```bash
superset agents run \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "Run /quasi:process-book for slug {slug} (title {title}, authors {authors}). Write vault/books/{slug}/00-overview.md; tag frontmatter topics: [{topic_slug}]; report final path + status." \
  --json --quiet
```

### kind == author → dispatch process-author in Superset CLI

```bash
superset agents run \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "Run /quasi:process-author for author {slug} (full_name {authors}). Build author profile from representative books and papers. Write vault/authors/{slug}.md; tag frontmatter topics: [{topic_slug}]; report final path + status." \
  --json --quiet
```

### FINAL → dispatch synthesis in Superset CLI

```bash
superset agents run \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "Synthesize topic review for '{topic_desc}' (slug {topic_slug}). Read vault/papers/ and vault/books/ entries tagged topics: [{topic_slug}]. Write vault/topics/{topic_slug}/00-overview.md (frontmatter: {type: topic, title: {topic}, kind: overview}) with [[wikilink]] references to vault entries. Write vault/topics/{topic_slug}/01-resources.md (frontmatter: {type: topic, title: {topic}, kind: resources}) with categorized reading list. title 必填,与 H1 一致。report final path + status." \
  --json --quiet
```

### AUDIT → dispatch audit in Superset CLI

```bash
superset agents run \
  --workspace "$SUPERSET_WORKSPACE_ID" \
  --agent "${QUASI_SUPERSET_AGENT:-copilot}" \
  --prompt "Run /quasi:audit on path vault/topics/{topic_slug}/. Check all generated topic pages. Apply local fixes if safe, escalate if not. report path + status." \
  --json --quiet
```

### POLL → dispatch poll-agent(general-purpose,每批一个)

```
Agent("general-purpose", prompt:
  "轮询以下 vault 产物路径是否落地,不要修改任何文件。
   每 60 秒用 `ls`/`test -f` 检查一遍;全部存在,或累计 1800 秒(30 分钟)超时,即停。
   路径清单:
   {batch_vault_paths}        # 本批每条目的 vault_path,一行一个
   最后只回传一个 JSON:{present:[已存在路径], missing:[仍缺路径], elapsed_s:N}。")
```

主进程拿到结果后:`present` → manifest status=analysed;`missing` → 留 processing,交下一轮 / 断点续跑重 fire。

## 执行流程

```
1. 检查 $SUPERSET_WORKSPACE_ID — 缺失即报错并停
2. 读取或创建 manifest.json
3. Phase 0: Agent("quasi:search-agent") 发现候选 → 写 manifest
   搜不到 → 主进程 kagi + dokobot 补充 book/author 条目
4. SNOWBALL 循环 (最多 5 轮):
   a. 收集 status=discovered + stranded processing 条目
   b. 按 kind 选择 dispatch 模板 → superset agents run(异步 fire)
   c. 并发控制: processing 数 >= 5 时先派 poll-agent 等一批落地
   d. 派 poll-agent(本批 vault_path 清单)轮询 → present 升 status=analysed,missing 留 processing
   e. 读各 analysed 条目的核心引用 → dedupe 新条目 (新 round)
   f. new_refs == 0 → 退出
5. DEAD-END: AskUserQuestion 问用户是否再发现
6. FINAL: dispatch synthesis in Superset CLI → 派 poll-agent 等 00-overview.md 落地
7. AUDIT: dispatch audit in Superset CLI
8. Bash: marple-cli open vault/topics/{slug}/00-overview.md
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Phase 0 | `manifest.json` 存在且有 `items` | 存在则跳发现 |
| Phase N | `rounds_completed >= N` | 跳已完成轮 |
| 单条目 | `items[slug].status == analysed` 且 vault_path 存在 | 跳已处理(不重复委派) |
| FINAL | `00-overview.md` 存在 | 存在则跳综述 |
| AUDIT | 幂等,可重复跑 | clean 时几乎无成本 |

委派是异步 fire:续跑时把 `status == processing` 但 vault_path 已存在的条目提升为 `analysed`;仍缺产物的重新 fire。

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
```

topic 目录只放 manifest + 索引页,不囤分析副本(分析在 vault/papers/ 和 vault/books/ 里)。`vault/topics/` 与 `vault/journals/` 严格分层。

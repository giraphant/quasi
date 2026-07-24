---
name: quasi:process-material
description: Use when the user wants to acquire and analyse a book, paper, author, or topic through the unified orchestration graph (experimental, runs alongside the per-kind process-* skills).
---

# Process Material — 统一材料处理(实验,新旧并行)

## 任务

用一张确定性编排图,把一份材料(paper / book / author / topic)从采集跑到分析。

## 输入

显式调用(不抢旧 skill 的自动路由)。从用户请求归一化出:

- `kind`:`book` | `paper` | `author` | `topic`
- 该 kind 的参数,统一塞进 `args`:
  - book:`slug`(可由 title+author 先经 search 定)、`meta{title,authors,isbn,year,topic}`
  - paper:`doi` 或 `title+author`(v0 未实现)
  - author:`author_name`(v0 未实现)
  - topic:`topic_slug + topic_desc`(v0 未实现)

**v0 只实现 `kind=book`;其余 kind 图内直接抛"未实现"。** 见 `docs/process-material-design.md` §7。

## 硬约束

- **实验性,与 `process-{book,paper,author,topic}` 并行存在,不删任何旧 skill。**
- **talk / draft 不走本 skill**——它们不是采集→分析主干(talk 用 transcribe 原语、draft 是交互审定)。
- **新旧不要对同一个 slug 并发跑**(会抢同一批文件);拿没处理过的材料测,跟旧 skill 输出对眼。
- 编排在 Workflow 里跑,主进程只做:Step 0 本地召回/去重 + 归一化输入 + 处理图冒泡上来的人工卡点 + LOCALISE 回填 + 报告(采集→分析 spine 全在图里)。

## 状态

- 图产物照常落 `vault/` `processing/` `sources/`——与旧 skill 同命名空间、同幂等续跑。
- **编排状态活在 Workflow 内,不落 skill manifest。** 续跑靠文件幂等(agent 见 output 存在即 no-op),不靠 Workflow 自身 resume。
- LOCALISE 中译本缓存写入 `.quasi/localise/cndouban.json`,按原书 ISBN 幂等(与 `process-book` Step 6 一致)。

## Agent / Helper 合同

- 通过 **Workflow 工具**调 `$CLAUDE_PLUGIN_ROOT/skills/process-material/orchestrate.mjs`,把 `{kind, ...}` 作为 `args` 传入。
- 图内用 `agent(prompt, {agentType:'quasi:<name>'})` 起既有 worker agent(download/extract/analyse/synthesis/audit),契约与旧 skill 一致。
  - ⚠ 若 spike(设计文档 §8)证明 `agentType:'quasi:*'` 在 Workflow 内不解析,则改为 inline prompt 承载 agent 指令;图结构不变。
- 图不写 skill 状态文件;人工卡点由本 skill 主进程用 `AskUserQuestion` 处理。
- **Step 0 召回与 LOCALISE 是主进程(图外)的活**:图无 fs、不能调 bin,所以本地召回/去重、`quasi-helpers localise scan|write` 都由本 skill 主进程执行。
- LOCALISE 时按需 dispatch `search-agent`(kind=book,读 overview 搜 `localisations.zh.candidates`),主进程再用 `quasi-helpers localise write` 落盘;幂等于原书 ISBN。

## 工作流

```
主进程(瘦入口:召回 + 编排 + 卡点 + 回填)
├─ 归一化 kind + args
├─ Step 0 本地召回/去重(图外,主进程)
│    ├─ vault/books/{slug}/00-overview.md 存在 → 已完成,报告并 return(不跑图)
│    ├─ exact miss → rg 模糊召回近似 slug → 命中则列候选,提示可能重复(勿盲目新建)
│    └─ 否则继续
├─ Workflow(orchestrate.mjs, {kind, ...args}) → 后台跑 spine(采集→分析),完成回 result
├─ 读 result.status:
│    ├─ ok               → 继续 LOCALISE
│    ├─ year_ambiguous   → AskUserQuestion(把 year_evidence 原样给用户)→ 带决定重投(改 slug 或接受 recommended_year)
│    ├─ audit_escalated  → 报告 escalated,交人工
│    └─ *_failed         → 报告失败原因
├─ LOCALISE(仅 ok 后,图外):quasi-helpers localise scan → 有 pending 则 search-agent → quasi-helpers localise write
└─ marple open 最终产物(best-effort)
```

## 执行流程

```python
args = parse_request()   # kind + 该 kind 参数
if args.kind not in ("book",):   # v0
    report(f"process-material v0 只支持 kind=book;{args.kind} 待实现"); return

slug = args.slug
overview = f"vault/books/{slug}/00-overview.md"

# Step 0: 本地召回/去重(主进程,图外)——mirror process-book Step 0
if exists(overview):
    report(f"已有书籍页面,无需重复处理: {overview}"); return
# exact miss → rg 模糊召回,catch slug 漂移导致的重复;只列候选,不盲目新建
dup = rg_fuzzy_recall(slug, args.meta)   # vault/books、sources、processing 里近似命中
if dup.candidates:
    report_candidate_list(dup.candidates, note="rg fuzzy recall only; 可能重复,勿盲目新建")

# 后台跑 spine。Workflow 返回 runId,完成时通知;拿到最终 result。
result = Workflow(
    scriptPath="$CLAUDE_PLUGIN_ROOT/skills/process-material/orchestrate.mjs",
    args={"kind": args.kind, "slug": slug, "meta": args.meta},
)

# 图冒泡上来的人工卡点
if result.status == "year_ambiguous":
    # 把 result.year_evidence 原样给用户(含 tmp_path),让其改 slug 的 year 或接受 recommended_year
    decision = AskUserQuestion(present=result.year_evidence)
    result = Workflow(scriptPath="...", args={"kind": "book", "slug": decision.slug, "meta": args.meta,
                                              "year_decision": decision.choice})

if result.status == "audit_escalated":
    report(f"audit 仍 escalated:{result.escalated};交人工"); return
if result.status.endswith("_failed"):
    report(f"失败:{result.status}"); return

# 成功
slug = result.slug
overview = f"vault/books/{slug}/00-overview.md"
if result.get("year_warning"):
    report(f"完成,但年份存疑:{result.year_warning}")

# Step 6: LOCALISE 中译本 metadata 回填(主进程调 bin + 按需 search-agent;按原书 ISBN 幂等)
scan = Bash(f"quasi-helpers localise scan --path vault/books/{slug} --json")
if scan.pending > 0:
    search = Agent("quasi:search-agent", foreground=True,
                   prompt=f"kind: book\ncontext: read {overview} and search metadata/localisations")
    candidates_file = write_temp_json(search.localisations.zh.candidates)   # .quasi/temp/
    Bash(f"quasi-helpers localise write --book-path {overview} --candidates-file {candidates_file}")

# marple open(best-effort UX;失败不影响流程)
Bash(f"/opt/homebrew/bin/marple-cli open '{overview}' || marple-cli open '{overview}' || echo skip")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 0 召回 | `vault/books/{slug}/00-overview.md`;exact miss 后 rg 模糊召回 | overview 存在则**跳过整跑**;模糊命中只列候选 |
| spine(图) | 文件即状态:`sources/{slug}.*` / `processing/chapters/{slug}/` / `vault/books/{slug}/` | 重跑 skill,图内 agent 见 output 存在即 no-op;做完的章/概览秒过 |
| 卡点重投 | `year_decision` | 用户拍板后带决定重投,只补未定的一步 |
| LOCALISE | `.quasi/localise/cndouban.json#by_isbn[isbn]` | 已有 entry(found/none)则 helper scan 跳过 |

## 输出

与 `process-book` 等旧 skill **完全相同**的产物(同命名空间):

```
sources/{book-slug}.{epub,pdf}
processing/chapters/{book-slug}/{manifest.json,*.txt}
vault/books/{book-slug}/{00-overview.md,ch{slot}-*.md}
.quasi/localise/cndouban.json                          ← 中译本缓存(按原书 ISBN 幂等)
```

新旧并行期:哪个 skill 生成的产物无差别——图内调的就是同一批 worker agent、写同一批路径。

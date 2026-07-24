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
- 编排在 Workflow 里跑,主进程只做:归一化输入 + 处理图冒泡上来的人工卡点 + 报告。

## 状态

- 图产物照常落 `vault/` `processing/` `sources/`——与旧 skill 同命名空间、同幂等续跑。
- **编排状态活在 Workflow 内,不落 skill manifest。** 续跑靠文件幂等(agent 见 output 存在即 no-op),不靠 Workflow 自身 resume。

## Agent / Helper 合同

- 通过 **Workflow 工具**调 `$CLAUDE_PLUGIN_ROOT/skills/process-material/orchestrate.mjs`,把 `{kind, ...}` 作为 `args` 传入。
- 图内用 `agent(prompt, {agentType:'quasi:<name>'})` 起既有 worker agent(download/extract/analyse/synthesis/audit),契约与旧 skill 一致。
  - ⚠ 若 spike(设计文档 §8)证明 `agentType:'quasi:*'` 在 Workflow 内不解析,则改为 inline prompt 承载 agent 指令;图结构不变。
- 图不写 skill 状态文件;人工卡点由本 skill 主进程用 `AskUserQuestion` 处理。

## 工作流

```
主进程(瘦入口)
├─ 归一化 kind + args
├─ Workflow(orchestrate.mjs, {kind, ...args}) → 后台跑图,完成回 result
├─ 读 result.status:
│    ├─ ok               → 报告(+ 若有 year_warning,一并列出)
│    ├─ year_ambiguous   → AskUserQuestion(把 year_evidence 原样给用户)→ 带决定重投(改 slug 或接受 recommended_year)
│    ├─ audit_escalated  → 报告 escalated,交人工
│    └─ *_failed         → 报告失败原因
└─ marple open 最终产物(best-effort)
```

## 执行流程

```python
args = parse_request()   # kind + 该 kind 参数
if args.kind not in ("book",):   # v0
    report(f"process-material v0 只支持 kind=book;{args.kind} 待实现"); return

# 后台跑图。Workflow 返回 runId,完成时通知;拿到最终 result。
result = Workflow(
    scriptPath="$CLAUDE_PLUGIN_ROOT/skills/process-material/orchestrate.mjs",
    args={"kind": args.kind, "slug": args.slug, "meta": args.meta},
)

# 图冒泡上来的人工卡点
if result.status == "year_ambiguous":
    # 把 result.year_evidence 原样给用户(含 tmp_path),让其改 slug 的 year 或接受 recommended_year
    decision = AskUserQuestion(present=result.year_evidence)
    # 带决定重投(改 slug → 重跑;或接受 → 图内 accept recommended_year)
    result = Workflow(scriptPath="...", args={"kind": "book", "slug": decision.slug, "meta": args.meta,
                                              "year_decision": decision.choice})

if result.status == "audit_escalated":
    report(f"audit 仍 escalated:{result.escalated};交人工"); return
if result.status.endswith("_failed"):
    report(f"失败:{result.status}"); return

# 成功
if result.get("year_warning"):
    report(f"完成,但年份存疑:{result.year_warning}")
final = f"vault/books/{result.slug}/00-overview.md"
Bash(f"/opt/homebrew/bin/marple-cli open '{final}' || marple-cli open '{final}' || echo skip")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| 全流程 | 文件即状态:`sources/{slug}.*` / `processing/chapters/{slug}/` / `vault/books/{slug}/` | 重跑 skill,图内 agent 见 output 存在即 no-op;做完的章/概览秒过 |
| 卡点重投 | `year_decision` | 用户拍板后带决定重投,只补未定的一步 |

## 输出

与 `process-book` 等旧 skill **完全相同**的产物(同命名空间):

```
sources/{book-slug}.{epub,pdf}
processing/chapters/{book-slug}/{manifest.json,*.txt}
vault/books/{book-slug}/{00-overview.md,ch{slot}-*.md}
```

新旧并行期:哪个 skill 生成的产物无差别——图内调的就是同一批 worker agent、写同一批路径。

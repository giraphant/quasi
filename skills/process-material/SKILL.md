---
name: quasi:process-material
description: Use when the user wants to search, download, and analyse a book, a paper, an author's representative works, or a topic review into structured vault outputs.
---

# Process Material — 统一材料处理

## 任务

用一张确定性编排图,把一份材料(paper / book / author / topic)从采集跑到分析。

## 输入

从用户请求归一化出:

- `kind`:`book` | `paper` | `author` | `topic`
- 该 kind 的参数,统一塞进 `args`:
  - book:`slug`(可由 title+author 先经 search 定)、`meta{title,authors,isbn,year,topic}`
  - paper:`slug` + `meta{doi,title,authors,journal}`;`translate` 可选布尔(产出中译 PDF)
  - author:`name` + `meta{full_name,topic,maxBooks,maxPapers}`
  - topic:`slug` + `meta{desc,maxRounds,maxPerRound,minItems,allowAuthors}`

四个 kind 都由图承担;递归复用是重点——`author` 调 `processBook`/`processPaper`,`topic` 的每个条目走同一个 `router`。

## 硬约束

- **talk / draft 不走本 skill**——它们不是采集→分析主干(talk 用 transcribe 原语、draft 是交互审定)。
- 编排在 Workflow 里跑,主进程只做:Step 0 本地召回/去重 + 归一化输入 + 处理图冒泡上来的人工卡点 + LOCALISE / TRANSLATE 回填 + 报告(采集→分析 spine 全在图里)。

## 状态

- 图产物照常落 `vault/` `processing/` `sources/`——全库统一命名空间、文件幂等续跑。
- **编排状态活在 Workflow 内,不落 skill manifest。** 续跑靠文件幂等(agent 见 output 存在即 no-op),不靠 Workflow 自身 resume。
- LOCALISE 中译本缓存写入 `.quasi/localise/cndouban.json`,按原书 ISBN 幂等。

## Agent / Helper 合同

- 通过 **Workflow 工具**调 `$CLAUDE_PLUGIN_ROOT/skills/process-material/orchestrate.mjs`,把 `{kind, ...}` 作为 `args` 传入。
- 图内用 `agent(prompt, {agentType:'quasi:<name>'})` 起 worker agent(download/extract/analyse/synthesis/audit)。
- 图不写 skill 状态文件;人工卡点由本 skill 主进程用 `AskUserQuestion` 处理。
- **Step 0 召回与 LOCALISE / TRANSLATE 是主进程(图外)的活**:图无 fs、不能调 bin,所以本地召回/去重、`quasi-helpers localise scan|write`、translate-agent 调度都由本 skill 主进程执行。
- LOCALISE 时按需 dispatch `search-agent`(kind=book,读 overview 搜 `localisations.zh.candidates`),主进程再用 `quasi-helpers localise write` 落盘;幂等于原书 ISBN。适用面:单本 book 的产物,和 author 跑落地的每本书(图回执带 `book_slugs` 名单)。
- TRANSLATE(仅 paper,`translate: true` 时):dispatch `quasi:translate-agent`,prompt 只给 `slug`;产出 `processing/translations/{slug}-zh.pdf`。

## 工作流

```
主进程(瘦入口:召回 + 编排 + 卡点 + 回填)
├─ 归一化 kind + args
├─ Step 0 本地召回/去重(图外,主进程)
│    ├─ book/paper:`quasi-helpers vault resolve`(slug 精确 → ISBN/DOI → 标题+作者姓)命中 → return
│    ├─ author/topic:产物存在 → 只提示"增量更新",继续跑(累积型材料,重跑就是为了吸收新条目)
│    ├─ 均 miss → rg 模糊召回近似 key → 命中则列候选,提示可能重复(勿盲目新建)
│    └─ 否则继续
├─ Workflow(orchestrate.mjs, {kind, ...args}) → 后台跑图(采集→分析),完成回 result
├─ 读 result.status:
│    ├─ ok               → 报告(kind 各异)→ LOCALISE
│    ├─ year_ambiguous   → (仅单本 book)AskUserQuestion(year_evidence 原样)→ 带决定重投
│    ├─ needs_seeds      → (仅 topic)AskUserQuestion 要检索词 → 补 seeds 或 final=true 重投
│    ├─ synth_failed     → 原样自动重投一次(条目幂等,重跑秒过);再败才报人工
│    ├─ audit_escalated  → 报告 escalated,交人工
│    └─ 其余一律按失败报出(枚举 ok,不枚举失败态)
├─ LOCALISE(book,及 author / topic 的 book_slugs;ok 后,图外):localise scan → pending 则 search-agent → localise write
├─ TRANSLATE(仅 paper 且 translate=true;ok 后,图外):translate-agent → processing/translations/{slug}-zh.pdf
└─ marple open 最终产物(best-effort)
```

## 执行流程

```python
args = parse_request()   # kind + 该 kind 参数
if args.kind not in ("book", "paper", "author", "topic"):
    report(f"未知 kind: {args.kind}"); return

# 该 kind 的主键 + 最终产物路径
if args.kind == "book":    key, product = args.slug, f"vault/books/{args.slug}/00-overview.md"
elif args.kind == "paper": key, product = args.slug, f"vault/papers/{args.slug}.md"
elif args.kind == "topic": key, product = args.slug, f"vault/topics/{args.slug}/00-overview.md"
else:                      key, product = args.name, f"vault/authors/{args.name}.md"     # author

# Step 0: 本地召回/去重(主进程,图外)——mirror process-{book,paper,author} Step 0
# book/paper 走确定性三级匹配(slug 精确 → ISBN/DOI → 标题+作者姓):同一作品换个 slug 也认得出,
# 不靠 LLM 眼力。title/authors 一定要带上——vault 条目自己没 ISBN/DOI 时前两级必然 miss。
# author/topic 无标识符,用产物路径。
if args.kind in ("book", "paper"):
    ident = {"isbn": args.meta.get("isbn")} if args.kind == "book" else {"doi": args.meta.get("doi")}
    ident |= {"title": args.meta.get("title"), "authors": args.meta.get("authors")}
    hit = bash(f"quasi-helpers vault resolve --items-json "
               f"'{json([{'kind': args.kind, 'slug': key, **ident}])}'")["resolved"][0]
    if hit["vault_slug"]:
        # book/paper 是一次性材料:做过就是做过,重跑只会造重复条目 → 直接返回。
        report(f"已有产物({hit['match']} 命中): {hit['path']}"); return
elif exists(product):
    # author/topic 是**累积型**材料:重跑正是为了把新作品/新文献吸收进已有页面(所以图里这两个
    # synth 是 overwrite 而非幂等)。存在不是终止条件,只提示一声继续跑;图内探针会跳过所有
    # 已入库条目,重跑代价很小(Bowker 二次跑实测 8 个 agent、零 download/extract)。
    report(f"已有产物,本次为增量更新: {product}")
dup = rg_fuzzy_recall(key, args.meta)   # 兜底:候选没带 ISBN/DOI 时的近似命中
if dup.candidates:
    report_candidate_list(dup.candidates, note="rg fuzzy recall only; 可能重复,勿盲目新建")

# 后台跑图。book/paper 传 slug+meta;author 传 name+meta。
wf_args = {"kind": args.kind, "meta": args.meta}
wf_args["slug" if args.kind != "author" else "name"] = key
result = Workflow(scriptPath="$CLAUDE_PLUGIN_ROOT/skills/process-material/orchestrate.mjs", args=wf_args)

# 人工卡点:仅单本 book 会 year_mismatch/year_ambiguous(author 批量自动收、不冒泡)。
# 两者都是"文件下下来了但年份对不上、留在 tmp_path 等人拍板",处理方式相同。
if result.status in ("year_mismatch", "year_ambiguous"):
    decision = AskUserQuestion(present=result.year_evidence)   # 含 tmp_path
    wf_args["slug"], wf_args["year_decision"] = decision.slug, decision.choice
    result = Workflow(scriptPath="...", args=wf_args)

# topic 死胡同:滚雪球滚不动了、语料还太薄。不硬写一篇没底子的综述,问用户要检索词。
# 用户不补 → 带 final=True 原样重投,图直接跳到收口(条目全幂等,重跑几乎零成本)。
if result.status == "needs_seeds":
    decision = AskUserQuestion(present={"已收语料": result.collected, "已收证据卡": result.cards,
                                        "建议检索词": result.suggested_queries})
    wf_args["meta"] |= {"seeds": decision.seeds} if decision.seeds else {"final": True}
    result = Workflow(scriptPath="...", args=wf_args)

# synth_failed 自动重投一次:语料都齐了,死的只是最后的 synth/audit——多半是瞬时 provider 错误
# 连杀本体和 retry(0.48.2 E2E:90 分钟的跑一切都成,synth 双杀后整跑报废)。条目全幂等,
# 重投时召回/探针秒过、直接冲到 synth,代价几分钟。两次都死才是真问题,报人工。
if result.status == "synth_failed":
    result = Workflow(scriptPath="$CLAUDE_PLUGIN_ROOT/skills/process-material/orchestrate.mjs", args=wf_args)
    if result.status == "synth_failed":
        report(f"synth 连续两次失败:{result.get('notes')};交人工"); return

if result.status == "audit_escalated":
    report(f"audit 仍 escalated:{result.escalated};交人工"); return
# chapters_incomplete = 章分析没跑齐(通常是瞬时 API 错误连着打死同一章)。产物本身没坏,
# 重跑本 skill 只会补缺的那几章(已完成的章 agent 见文件即 no-op),所以提示重跑而不是报死。
if result.status == "chapters_incomplete":
    report(f"章节残缺 {result.analysed}/{result.expected};重跑本 skill 只补缺章"); return
# 兜底:枚举**成功**态,不枚举失败态。图里 processBook 把 download-agent 的 status 原样上抛,
# 那个枚举会长(year_mismatch 就这么漏过一次),枚举失败态迟早再漏一个,而漏掉的后果是
# 静默报成功——最坏的一种。不是 ok 就是没跑成,一律报出来。
if result.status != "ok":
    report(f"失败:{result.status}"); return

# 成功报告(kind 各异)
if args.kind == "book" and result.get("year_warning"):
    report(f"完成,但年份存疑:{result.year_warning}")
if args.kind == "author":
    report(f"作者完成:{result.books} 本书 / {result.papers} 篇论文"
           + (f";{len(result.year_warnings)} 本年份存疑" if result.get("year_warnings") else "")
           + (f";{result.book_failures}+{result.paper_failures} 项获取失败" if result.book_failures or result.paper_failures else ""))
if args.kind == "topic":
    report(f"主题完成:{result.items} 条语料 / {result.rounds} 轮滚雪球;大纲 {result.outline}"
           + (f";另有 {result.cards} 张圈外证据卡" if result.get("cards") else "")
           + (f";其中 {result.recalled} 条来自库内召回" if result.get("recalled") else "")
           + (f";{result.failures} 项获取失败" if result.failures else "")
           + (f";专章生成失败:{', '.join(result.dossiers_failed)},重跑一次即补" if result.get("dossiers_failed") else "")
           + (";掌舵判饱和,已收口" if result.get("saturated") else
              ("" if result.dead_end else ";候选未枯竭,可再跑一次继续扩充")))

# LOCALISE 中译本回填:单本 book 用 [key];author / topic 用图回执的 book_slugs 名单(scan 按
# ISBN 幂等,已回填过的书 pending=0 秒过,所以名单里混着历史入库的书也没有代价)。paper 无。
localise_slugs = [key] if args.kind == "book" else (result.get("book_slugs") or [])
for slug in localise_slugs:
    scan = Bash(f"quasi-helpers localise scan --path vault/books/{slug} --json")
    if scan.pending > 0:
        overview = f"vault/books/{slug}/00-overview.md"
        search = Agent("quasi:search-agent", foreground=True,
                       prompt=f"kind: book\ncontext: read {overview} and search metadata/localisations")
        candidates_file = write_temp_json(search.localisations.zh.candidates)   # .quasi/temp/
        Bash(f"quasi-helpers localise write --book-path {overview} --candidates-file {candidates_file}")

# TRANSLATE 中译 PDF:仅 paper 显式要了 translate 才跑;translate-agent 按 slug 自定位 sources/{slug}.pdf。
if args.kind == "paper" and args.get("translate") and not exists(f"processing/translations/{key}-zh.pdf"):
    Agent("quasi:translate-agent", foreground=True, prompt=f"slug: {key}")

# marple open 最终产物(best-effort UX;失败不影响流程)
Bash(f"/opt/homebrew/bin/marple-cli open '{product}' || marple-cli open '{product}' || echo skip")
```

## 断点续跑

| 阶段 | 检查 | 跳过条件 |
|------|------|---------|
| Step 0 召回 | `quasi-helpers vault resolve`(slug 精确 → ISBN/DOI → 标题+作者姓);均 miss 后 rg 模糊召回 | book/paper:`vault_slug` 非 null 则**跳过整跑**(slug 漂移也算已做);author/topic 不跳,走增量;模糊命中只列候选 |
| spine(图) | 文件即状态:`sources/{slug}.*` / `processing/chapters/{slug}/` / `vault/books/{slug}/` | 重跑 skill,图内 agent 见 output 存在即 no-op;做完的章/概览秒过 |
| 批量条目(author/topic) | 图内一次存在性探针(同三级匹配) | 已入库条目不 download / 不 extract / 不重分析,直接计入 synth 语料 |
| 卡点重投 | `year_decision` / `seeds` / `final` | 用户拍板后带决定重投,只补未定的一步 |
| LOCALISE | `.quasi/localise/cndouban.json#by_isbn[isbn]` | 已有 entry(found/none)则 helper scan 跳过 |
| TRANSLATE | `processing/translations/{slug}-zh.pdf` | 文件已存在则跳过 |

## 输出

```
sources/{book-slug}.{epub,pdf}
processing/chapters/{book-slug}/{manifest.json,*.txt}
vault/books/{book-slug}/{00-overview.md,ch{slot}-*.md}
vault/papers/{paper-slug}.md
vault/authors/{author-name}.md
vault/topics/{topic-slug}/{00-overview.md,01-resources.md,02-outline.md,NN-*.md,cards/*.md}
processing/translations/{paper-slug}-zh.pdf            ← 可选(translate: true)
.quasi/localise/cndouban.json                          ← 中译本缓存(按原书 ISBN 幂等)
```

topic 目录 = 三页脊柱(00 门面 / 01 清单 / 02 研究大纲)+ 毕业子问题的专章 NN-*.md
+ `cards/` 圈外证据卡,不囤分析副本——分析在 `vault/papers/`、`vault/books/`、`vault/talks/` 里,各页用
`[[wikilink]]` 指过去(讲座只可能来自图内本地召回,在线发现搜不到它们)。证据卡是例外:它是
webcard-agent 就地写的一手材料(机型、SEC 文件、规章、口述),学术管线拿不到,所以住在主题目录里;
它**不是**分析件,不进语料表,走 outline 的 `cards` 通道。02-outline 是
steer-agent 维护的掌舵状态,**用户可手改**,手改就是下次增量重跑的指令。编排状态活在图里,
条目完成与否由 `router` 的回执直接给出,不靠轮询产物反推。

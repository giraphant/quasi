---
name: research-topic
description: Use when the user wants to research a topic through iterative vault recall, academic discovery, evidence cards, and a structured literature review.
---

# Research Topic — 主题研究

## 任务

围绕一个主题迭代召回、采集和综合证据,形成可继续增量更新的主题研究页。

## 输入

从用户请求归一化出:

- `slug`:主题的稳定 kebab-case 标识。
- `meta.desc`:主题问题或范围说明。
- `meta.maxRounds`:最多滚动轮数,可选;显式 `0` 选择只消费既有
  book/paper/talk canonical 的严格 recall-only 路径。
- `meta.strict`:迁移期严格路径开关。只有显式 `true` 且
  `maxRounds=1,maxCardsPerRound=0` 时,图额外执行一轮有界 Book/Paper
  发现并把候选交给共享 Material Loop;该路径仍不启动 cards 或 dossiers。
- `meta.maxPerRound`:每轮最大候选数,可选。
- `meta.minItems`:允许最终综合所需的最小语料数,可选。
- `meta.allowAuthors`:是否让作者候选进入扩展,可选。
- `meta.seeds`:用户补充的检索词,仅在人工卡点后设置。
- `meta.final`:用户决定不再补种子而直接收口时设为 `true`。

交给图的参数固定为 `{"kind":"topic","slug":slug,"meta":meta}`。不要把 topic 猜成 book、paper 或 author。

## 硬约束

- topic 是“研究问题 → 多轮语料/证据 → 综合”的循环,不是单份材料处理;公开入口由本 skill 独占。
- 仍复用 `$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs`:图内 topic 候选必须走同一个 `router`,从而借用 paper/book 的 search、download、extract、analyse 节点。此处不复制第二套材料管线。
- 主进程不得用通用 web/browser 工具旁路 quasi 的 search/download 合同。圈外证据只走图内 `webcard-agent`;学术候选只走 quasi 搜索合同。
- `needs_seeds` 必须回到用户,不得把过薄语料静默综合成完成。
- 图返回 `research_receipt` 时它是权威终态;`blocked` 表示 writer 结果未知,
  只能从 `topic.reconcile` 观察现有产物,不得自动重投整张图或该 writer。
- 严格一轮路径只把 `material_receipt.status=complete` 且 canonical 与最终
  clean audit 均逐字匹配的 Book/Paper 接入 Topic 语料。失败或 blocked 的
  子材料保留在 `research_receipt.material_results`,不得凭 legacy `ok` 或文件存在接入。
- topic 页面不复制 book/paper/talk 分析正文;它们通过 wikilink 进入语料。`cards/` 是独立证据通道,不算 vault 分析件。

## 状态

- 最终产物落在 `vault/topics/{slug}/`。
- `02-outline.md` 是 steer-agent 唯一维护的研究大纲,但用户可手改;下次增量运行必须把手改视为新指令。
- 图的运行状态只活在本次执行内。断点续跑依赖既有 vault/source/processing 文件和图内存在性探针,不维护另一份 skill manifest。
- 已有 `00-overview.md` 不是完成锁:topic 是累积型产品,重跑表示继续召回或按用户修改的大纲推进。
- LOCALISE 缓存仍写 `.quasi/localise/cndouban.json`,按图回执中的 `book_slugs` 幂等处理。

## Agent / Helper 合同

- Claude Code:用 Workflow 工具运行 `$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs`,args 为 `{kind:"topic",slug,meta}`。
- Pi:把 args 写入 `.quasi/temp/`,运行 `quasi-pi-runner --script "$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs" --args-file <path>`。
- Codex GUI:用长驻 `quasi-codex-driver` 连接当前 thread 的原生 subagents。启动前必须完整读取并遵守 `$CLAUDE_PLUGIN_ROOT/skills/process-material/references/codex-native-driver.md`;没有原生 subagent 或可续写 exec 时才回退 `quasi-codex-runner`。
- 图内 `steer-agent` 独占写 `02-outline.md`;`webcard-agent` 一次只写调用方指定的一张 card;paper/book 候选继续走共享 router。
- 主进程只拥有 Step 0、本轮人工卡点、LOCALISE 回填和最终报告,不写图内研究状态。
- LOCALISE:对 `result.book_slugs` 逐本运行 `quasi-helpers localise scan`;pending 时 dispatch `quasi:search-agent`,再用 `quasi-helpers localise write` 写入。

## 工作流

```text
主进程(topic 入口)
├─ 归一化 slug + meta
├─ Step 0
│  ├─ 已有 topic 产物 → 提示“增量更新”,继续
│  └─ rg 近似 topic → 列出可能重复项,继续前避免盲目新建
├─ 共享 graph(kind=topic)
│  ├─ vault recall:已分析的 book/paper/talk
│  ├─ steer:读取/更新 outline,提出定向候选与 web tasks
│  ├─ strict one-round:每个候选先经 quasi search 得到权威 identity,
│  │  再递归走共享 paper/book router 并只接纳 exact complete MaterialReceipt
│  ├─ legacy router:未迁移的多轮候选继续走现有 paper/book 节点
│  ├─ webcard:独立产出可核验的一手证据卡
│  └─ synthesis + audit:写主题脊柱与毕业子问题专章
├─ needs_seeds → 用户补检索词或选择 final=true → 重投
├─ legacy synth_failed → 兼容路径自动原样重投一次
├─ typed research_receipt blocked/failed → 不重投 writer,fail closed
├─ 非 ok / audit_escalated → fail closed
├─ LOCALISE(result.book_slugs)
└─ 打开 vault/topics/{slug}/00-overview.md
```

## 执行流程

```python
args = parse_request()
if not args.slug or not args.meta.get("desc"):
    report("主题研究需要稳定 slug 和明确的范围说明"); return

wf_args = {"kind": "topic", "slug": args.slug, "meta": args.meta}
product = f"vault/topics/{args.slug}/00-overview.md"

# Step 0: topic 是累积型产品,存在只表示从现有成果继续。
if exists(product):
    report(f"已有产物,本次为增量更新: {product}")
dup = rg_fuzzy_recall(args.slug, args.meta)
if dup.candidates:
    report_candidate_list(dup.candidates,
                          note="rg fuzzy recall only; 可能重复,勿盲目新建")

def run_graph(current_args):
    if env("PI_CODING_AGENT") == "true":
        args_file = write_temp_json(current_args)  # .quasi/temp/
        return parse_json(Bash(
            f"quasi-pi-runner --script '$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs' "
            f"--args-file '{args_file}'").stdout)
    if env("CODEX_THREAD_ID"):
        args_file = write_temp_json(current_args)  # .quasi/temp/
        if has_tools("spawn_agent", "wait_agent", "followup_task",
                     "interrupt_agent", "resumable_exec"):
            # 先完整读取 skills/process-material/references/codex-native-driver.md,
            # 再按其合同驱动。
            return drive_codex_native(
                command=f"quasi-codex-driver --script '$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs' "
                        f"--args-file '{args_file}' --cwd '$CLAUDE_PROJECT_DIR'",
                protocol="quasi-codex-driver/1")
        return parse_json(Bash(
            f"quasi-codex-runner --script '$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs' "
            f"--args-file '{args_file}' --cwd '$CLAUDE_PROJECT_DIR'").stdout)
    return Workflow(
        scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs",
        args=current_args)

result = run_graph(wf_args)

# 滚雪球停止而语料不足时,将图给出的范围和建议原样交给用户。
if result.status == "needs_seeds":
    decision = AskUserQuestion(
        present={"已收语料": result.collected,
                 "已收证据卡": result.cards,
                 "建议检索词": result.suggested_queries})
    wf_args["meta"] |= (
        {"seeds": decision.seeds} if decision.seeds else {"final": True}
    )
    result = run_graph(wf_args)

# 仅未迁移的 legacy Topic 仍保留一次整图兼容重投。严格路径的 writer
# 结果由 research_receipt 证明;未知结果不得重放。
if result.status == "synth_failed" and not result.get("research_receipt"):
    result = run_graph(wf_args)
    if result.status == "synth_failed":
        report(f"synth 连续两次失败:{result.get('notes')};交人工"); return

if result.status == "audit_escalated":
    report(f"audit 仍 escalated:{result.escalated};交人工"); return
if result.status != "ok":
    report(f"失败:{result.status}; "
           f"{result.get('failure_reason') or result.get('notes') or ''}")
    return

if result.get("research_receipt"):
    receipt = result.research_receipt
    if receipt.status not in ["complete", "partial"]:
        report(f"Topic typed 终态不可交付:{receipt.status};"
               f"stage={receipt.stage};failure={receipt.failure}"); return
    if receipt.status == "partial":
        failed_materials = [
            material for material in receipt.material_results
            if material.status != "complete"
        ]
        report("Topic 产物已通过 audit,但部分候选发现或 Material Loop 失败;"
               f"发现失败={receipt.discovery_failures};"
               f"材料失败={failed_materials}")

report(f"主题完成:{result.items} 条语料 / {result.rounds} 轮滚雪球;"
       f"大纲 {result.outline}"
       + (f";另有 {result.cards} 张圈外证据卡" if result.get("cards") else "")
       + (f";其中 {result.recalled} 条来自库内召回" if result.get("recalled") else "")
       + (f";{result.failures} 项获取失败" if result.failures else "")
       + (f";专章生成失败:{', '.join(result.dossiers_failed)},重跑一次即补"
          if result.get("dossiers_failed") else "")
       + (";掌舵判饱和,已收口" if result.get("saturated") else
          ("" if result.dead_end else ";候选未枯竭,可再跑一次继续扩充")))

for slug in result.get("book_slugs") or []:
    scan = Bash(f"quasi-helpers localise scan --path vault/books/{slug} --json")
    if scan.pending > 0:
        overview = f"vault/books/{slug}/00-overview.md"
        search = Agent(
            "quasi:search-agent",
            foreground=True,
            prompt=f"kind: book\ncontext: read {overview} and search metadata/localisations")
        candidates_file = write_temp_json(search.localisations.zh.candidates)
        Bash(f"quasi-helpers localise write --book-path {overview} "
             f"--candidates-file {candidates_file}")

Bash(f"/opt/homebrew/bin/marple-cli open '{product}' "
     f"|| marple-cli open '{product}' || echo skip")
```

## 断点续跑

| 阶段 | 检查 | 跳过/续跑规则 |
| --- | --- | --- |
| Step 0 | `vault/topics/{slug}/00-overview.md` + rg 近似召回 | 精确产物存在仍继续增量;近似项只提示去重 |
| outline | `02-outline.md` | steer 读取现状与用户手改后继续,不新建平行状态 |
| 材料节点 | 图内 vault resolve + 子 MaterialReceipt | 只有 exact complete + clean audit 的 canonical 进入语料;已存在材料仍必须由其 Material Loop reconcile 证明 |
| evidence cards | outline 的 cards 通道和既有 card path | 已完成 card 不重复写;无法核验则 `status: empty` |
| 人工卡点 | `seeds` / `final` | 带用户决定重投,已完成节点由幂等合同跳过 |
| synth | `synth_failed` | 自动重投一次;第二次失败才交人工 |
| LOCALISE | `.quasi/localise/cndouban.json#by_isbn` | 已有 found/none 记录即跳过 |

## 输出

```text
vault/topics/{topic-slug}/00-overview.md
vault/topics/{topic-slug}/01-resources.md
vault/topics/{topic-slug}/02-outline.md
vault/topics/{topic-slug}/NN-*.md
vault/topics/{topic-slug}/cards/*.md
vault/books/... and vault/papers/...              # 共享 router 落地的材料分析
.quasi/localise/cndouban.json                     # 图中书籍的中译本缓存
```

topic 目录的三页脊柱分别是门面、语料清单和可手改研究大纲。毕业子问题写成
`NN-*.md`;圈外一手材料写成 `cards/*.md`。书、论文和本地讲座分析留在各自 vault
命名空间,主题页只通过链接引用它们。

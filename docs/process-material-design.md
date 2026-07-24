# process-material 设计文档 —— 把编排收成一张确定性图

- 日期: 2026-07-24
- 状态: 设计草案(**新旧并行,不删任何旧 skill**)
- 范围: 采集→分析主干(paper / book / author / topic)。**talk 与 draft 不在本图内。**

---

## 1. 背景与动机

harness 变了两件事:

1. 子代理现在**能再派子代理**(以前是叶子,不能再派)。
2. 有了 **Workflow 工具**:一段纯 JS 编排脚本,`agent()` / `parallel()` / `pipeline()` 起子代理,协调是代码、零 model token。

quasi 现有 skill/agent 拆分的**前提**正是"子代理不能再派",所以所有 fan-out、轮询、manifest 消费被迫堆在 skill 主进程里 —— 路由变得很"厚"。这个前提现在塌了。

症状(触发本次重设计):
- `process-book / paper / author / topic` 在新 harness 下不稳。
- 触发退化:贴一个 paper 列表,得手动显式告诉它用哪个 skill。
- 编排逻辑写在 SKILL.md 散文里、由主进程即兴执行 → **不确定 + 烧 context**。`process-book` 274 行里 ~180 行是主进程要即兴跑的伪代码,含 `while Glob(...) sleep(30)` 轮询,以及一整段"禁用 TaskOutput / 必须 Glob 轮询 / Dispatcher context 卫生"的疤痕组织。

**目标**: 把 skill 层的**编排**从「散文 × 主进程即兴」收成「一张确定性 JS 图」。**地基(bins / agents / hooks / schemas)一块不动。**

---

## 2. 核心洞察:底下是一张递归图

这几个流程是**包含关系**,不是并列:

```
topic  ⊃ { author, book, paper }
author ⊃ book(每本) + paper(每篇)
book   ⊃ chapter(每章)
```

证据:`process-author` 现在**内联抄了** book 子流程(只靠散文契约"命名和 process-book 保持一致"绑着);`process-topic` 现在用 `superset agents create` **派** paper/book/author。→ 天然是**一个带 kind-router 的递归图**。

关键区分:**一张图 ≠ 一个 skill。** 合并的是「图」(编排模块),不是把 plugin 溶进 skill 散文。"fat" 放在图上是对的,放在"取代 plugin"上是错的。

---

## 3. 目标架构

### 图一 · 分层栈(胖的只有编排那层,底下全冻结)

```
┌──────────────────────────────────────────────────────────────────┐
│ ENTRY(瘦)   parse intent → kind → 调图;交互式人工卡点住这层        │
│   process-material(显式触发),只做:归一化输入 + 选 kind             │
└───────────────┬──────────────────────────────────────────────────┘
                │  Workflow(orchestrate, { kind, args })
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ ORCHESTRATION GRAPH(胖)   一个 workflow 模块 = 确定性 JS           │
│   fan-out / pipeline / skip / escalation 全是代码 —— 轮询消失       │
│        router(kind) ──► topic │ author │ book │ paper  (递归,图二)  │
│   共享节点函数: search download extract analyse synth audit         │
└───────────────┬──────────────────────────────────────────────────┘
                │  agent(prompt, { agentType, schema })   ← 零 token 协调
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ WORKERS(冻结·工具受限)   agents/                                   │
│   search·download·extract·analyse(A/B/T)·synth(mode)·audit          │
│   translate · proofread · citecheck   ← 每个的工具白名单就是沙箱      │
└───────────────┬──────────────────────────────────────────────────┘
                │  Bash: quasi-*
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ SUBSTRATE(冻结)   bins + scripts + hooks + schemas                │
│   quasi-download(2401 行级联)·quasi-search·quasi-extract·           │
│   quasi-transcribe·quasi-audit·quasi-helpers·quasi-translate        │
│   hooks(userConfig→env 密钥桥)   schemas 0.7.0                      │
└──────────────────────────────────────────────────────────────────┘

STATE(横切·文件即状态·跨天续跑):
   sources/   processing/{chapters,translations,talks}/   .quasi/   vault/
```

### 图二 · 递归图(设计的心脏)

```
router(kind)
│
├─ processTopic(q)                                  [gate: 死胡同重新发现]
│    ├─ search → discover items
│    ├─ pipeline(items):  router(item.kind) ──┐   ← 递归往下派
│    ├─ snowball: 读落地 body 的「## 核心引用」→ 新 item, loop-until-dry
│    └─ synth(topic) → audit                    │
│                                                │
├─ processAuthor(name) ◄─────────────────────────┤            [gate: 无,推迟]
│    ├─ search books + papers
│    ├─ parallel(books):  processBook(b) ──┐     │   ← 复用同一个 book 图
│    ├─ parallel(papers): analyse(B)        │     │
│    └─ synth(author) → audit               │     │
│                                            │     │
├─ processBook(slug) ◄───────────────────────┴─────┤        [gate: year-triage]
│    ├─ download → extract
│    ├─ parallel(chapters): analyse(A)
│    └─ synth(book) → audit → localise             │
│                                                   │
└─ processPaper(doi) ◄──────────────────────────────┘            [gate: 无]
     └─ download → analyse(B) → audit
```

`◄─` 复用箭头是全部价值所在:`author` 不再抄 book,直接调 `processBook`(重复当场消失、localise 白拿);`topic` 的 per-item 也是同一个 router 递归,`superset agents create` 那套跨会话机关整个删掉,换成 `pipeline(items)`。

### 图三 · 卡点处理(决定"多少能塞进后台")

后台跑的图中途**不能** `AskUserQuestion`。三种卡点三种处理:

```
gate 类型              处理方式                             落在哪
─────────────────────  ───────────────────────────────────  ──────────
book: year-triage      推迟:自动取 recommended_year +        图内
                       记 year_warning,跑完在报告里汇总
                       (process-author 现在就这么干,统一到 book)

topic: 死胡同重新发现   图跑到"候选枯竭"→ 返回 {需决策,建议词}    图 → 入口
                       入口 skill 弹 AskUserQuestion → resume

draft: 引文逐条审定     全程交互,根本不进图                   交互层(独立)
```

---

## 4. 什么冻结、什么变

| | 之前 | 之后 |
|---|---|---|
| 编排 | 6 个 SKILL.md 散文 × 主进程即兴 | **1 个 workflow 模块(递归图)** |
| author/book 重复 | author 内联抄 book | author 调 `processBook`,重复没了 |
| topic 派发 | `superset agents create` 跨会话 + sentinel + poll-agent | `pipeline(items)` 同会话,机关全删 |
| 轮询 | 3 种人格(sleep / 通知 / poll-agent) | **原生 parallel/pipeline,轮询消失** |
| 入口 | 6 个 skill | `process-material`(显式)+ talk + draft |
| agents / bins / hooks / schemas | —— | **一块不动** |

---

## 5. 交接模型(关键约束)

**约束: workflow 脚本本身没有文件系统访问**(纯 JS,`JSON` 有,无 `fs` / 无 Node API)。所以脚本手里能有的,只有 `agent()` 的返回值。这反而让交接更干净。

交接分两条,井水不犯河水:

| | 走什么 | 谁碰它 | 变了吗 |
|---|---|---|---|
| **产物内容**(源 PDF、章节文本、vault .md) | **文件** | agent 写,下游 agent 按**路径**读 | **没变** |
| **控制信号**(status / path / slug / year_evidence / 章节列表) | **agent 的返回回执**(小 JSON) | 脚本读回执做路由 | 从"主进程肉眼抠 prose"变成"schema 校验的对象" |

推论:
- **脚本从不持有正文。** fan-out 需要的章节列表,由 `extract-agent` 在**回执**里带回来(它本来就把这个算好写进 `manifest.json` 了,顺手一并 return)。manifest 照样写盘,是给下游 / 续跑 / translate-agent 用的,不是给脚本读的。
- **续跑 = agent 幂等**:output 存在且非 overwrite → agent 自跳过(它有 Read/Glob)。跨天成立,因为文件在盘上。`while Glob sleep(30)` 与 `filter(exists)` 都删掉。
  - ⚠ 需给 analyse-agent / synthesis-agent 契约加一句"output 存在且非 overwrite 就 no-op 返回"。**唯一的 agent 契约改动。**
- **卡点 = 小结构体 return 冒泡**:`{status:'year_ambiguous', year_evidence, tmp_path}` 一路成 workflow 最终结果 → 入口 skill 读到 → `AskUserQuestion` → resume。
- `agent(..., {schema})` 在工具层**强制**回执是校验过的 JSON(retry until valid),比今天主进程读中文回复肉眼抠字段**更可靠**。

---

## 6. v0 节点骨架 —— `processBook`(第一个、也是唯一先写的节点)

```js
// orchestrate.js —— v0 只实现 processBook;topic/author/paper 先留 stub
async function processBook(slug, meta) {
  // ── download ──  回执:status/path/year_evidence   产物:PDF 落 sources/
  const dl = await agent(dlPrompt(slug, meta),
                         { agentType:'quasi:download-agent', schema: DOWNLOAD_RESULT })
  const item = dl.per_item[0]
  if (item.status !== 'ok')                       // 卡点 → 冒泡回入口
    return { slug, status: item.status, year_evidence: item.year_evidence, tmp_path: item.tmp_path }

  // ── extract ──  产物:manifest.json + ch*.txt 落 processing/chapters/
  //   章节列表从「回执」带回(脚本没 fs,不能读 manifest)
  const ex = await agent(exPrompt(item.path, slug),
                         { agentType:'quasi:extract-agent', schema: EXTRACT_RESULT })
  if (ex.status === 'failed') return { slug, status: 'extract_failed' }

  // ── fan-out analyse ×N ──  脚本手里只有 ch={slot,filename,slug} pointer
  //   正文在 processing/;分析写 vault/;脚本从没持有过任何正文
  //   已完成的章:analyse-agent 幂等 no-op = 续跑(取代 while-sleep 轮询)
  await parallel(ex.chapters.map(ch => () =>
    agent(analysePrompt(slug, meta, ch),
          { agentType:'quasi:analyse-agent', schema: ANALYZE_RESULT })))

  // ── synth(book) ──  只递目录/slug;synthesis-agent 自己 Glob vault 的 ch*.md
  await agent(synthPrompt(slug, meta),
              { agentType:'quasi:synthesis-agent', schema: SYNTHESIS_RESULT })

  // ── audit + 一次 escalation 回环 ──
  let au = await agent(`path: vault/books/${slug}`, { agentType:'quasi:audit-agent', schema: AUDIT_RESULT })
  if (au.escalated?.length) {
    await parallel(au.escalated.map(e => () =>
      agent(regenPrompt(slug, meta, e), { agentType: regenAgentFor(e), schema: /* 对应 */ null })))
    au = await agent(`path: vault/books/${slug}`, { agentType:'quasi:audit-agent', schema: AUDIT_RESULT })
    if (au.escalated?.length) return { slug, status:'audit_escalated', escalated: au.escalated }
  }

  // ── localise(可选,v0 可先不做)──  search-agent + quasi-helpers localise
  return { slug, status: 'ok', year_warning: item.year_evidence?.verdict !== 'MATCH' ? item.year_evidence : null }
}

// 顶层入口
async function orchestrate({ kind, args }) {
  switch (kind) {
    case 'book':   return processBook(args.slug, args.meta)
    // v0:其余先抛"未实现",证明 book 一条链能在 Workflow 里活着再长
    default: throw new Error(`kind ${kind} not implemented in v0`)
  }
}
```

---

## 7. 迁移策略 —— 新旧并行

1. **不删任何旧 skill。** 加 `process-material` 在旁边。
2. **从里往外长,别一次铺满整张图。** v0 只实现 `processBook` —— 它一个人就把所有没验证的假设全测了(见 §8)。`author = parallel(books→processBook)`,`topic = pipeline(items→router)`,都是把 book 套进循环,不是新东西。
3. **并行安全是白送的**:共享状态 + 文件幂等 → 后跑的那个 resume/no-op,不会覆盖。
   - **唯一规矩:别对同一个 slug 让新旧并发跑。** 新的拿没处理过的书测,跟旧的输出对眼看质量/稳定性。
4. **入口 explicit-only**:`process-material` 的 frontmatter 描述写成只显式调用,不抢六个旧 skill 的 auto-trigger。旧描述一个字不改。
5. **退役顺序(以后的事)**:
   ```
   process-material book  稳 → 退役 process-book
             + author 分支 稳 → 退役 process-author
             + topic 分支  稳 → 退役 process-topic（superset 一起删）
   process-paper           并入或保留皆可（已够薄）
   talk / draft            永不并入
   ```

---

## 8. 动手写 processBook 之前:先做个 20 分钟 spike

**这个不通,整个 agentType 方案要改。** 一次性丢掉的脚本,验两件事:

- (a) quasi 的 skill 指令里调 Workflow,opt-in 走不走得通;
- (b) `agentType:'quasi:*'` 在 Workflow 里能不能解析到插件 agent。

```js
// spike:换个只读 agent 探路
export const meta = { name:'spike', description:'probe agentType resolution' }
const r = await agent("运行 quasi-doctor --json 并返回结果",
                      { agentType:'quasi:audit-agent' })
return r
```

- **能** → 直接照 §6 写 processBook。
- **不能** → 把 `agentType` 换成在 prompt 里内联 agent 指令(agent 定义仍保留,只是 Workflow 内改用 inline prompt)。设计不变,只是接法变。

---

## 9. 冻结清单(重构绝不能碰)

- `scripts/download/download.py`(2401 行采集级联:OA/Sci-Hub/publisher/EZProxy/Wayback/Kagi、Cloudflare 识别、year 信号、跨进程限流)
- `scripts/search/search.py` 的合并/冲突算法 + `sources/*.py` 爬虫(尤其 `douban_cn.py`)
- `scripts/audit/audit.py` + `autofix_mechanical.py` 的 masking
- `scripts/schemas/` 契约 **0.7.0**(稳定边界)
- **agents 的工具白名单**(search-agent 不能 Write、citecheck 不能 Bash …)= 安全沙箱
- **共享 slug 命名空间** `{author-surname}-{short-title}-{year}`
- **`processing/chapters/{slug}/manifest.json` 三消费者契约**(process-book / process-author / translate-agent)

---

## 10. 开放问题 / 风险

- **§8 spike 结果**决定 agent 接法(agentType vs inline prompt)。动手前必做。
- **卡点 return→resume 的具体协议**:Workflow 自身 resume 是同会话(cache 命中);跨天续跑靠的是**文件幂等**,不是 Workflow resume。两者要说清,别混。
- **analyse/synthesis-agent 幂等自跳过**是唯一的 agent 契约改动,需落到 agent 文件。
- **`audit-agent` 内联手抄了全部 schema**(`audit-agent.md:120-267`)与 `scripts/schemas/` 并存 —— 既存的漂移风险,与本图无关,顺带记一笔。
```

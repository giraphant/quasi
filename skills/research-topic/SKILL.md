---
name: research-topic
description: Use when the user wants to define and research a precise topic through iterative vault recall, academic discovery, evidence cards, and a structured literature review.
---

# Research Topic

## 任务

由主线程围绕一个明确主题推进有界研究轮次，接纳材料与证据卡，并综合成可增量维护的主题页。

## 输入

只保留用户实际提供的主题与材料事实：

- `slug`：稳定的 kebab-case topic 标识。
- `description`：研究问题、范围或判断目标；不能为空。
- `maxRounds`：新材料与新卡片的最多轮数，默认 3，允许 0–8；`0` 表示 recall-only，
  不跟随 steer 派新材料或 webcard；显式但未 canonical 的 seed 按第 2 步请求用户决定。
- `maxCardsPerRound`：每轮最多接受的 unseen web task 数，默认 3，允许 0–6；它只是共享资源
  上限，不改变研究路径或 specialist 方法。
- `seed_materials`：可选的 Book、Paper 或 Talk hints。它们先按 `collect-material` 的单材料合同
  观察和 admission；需要新处理时不因作为 seed 而绕过 identity、产物或 audit 要求。

用户在 seed gate 或 `needs_input` 给出的回答不是新的隐式状态；逐字保留在下一次
`topic.steer` 的 `context.query.user_decision` 中。

## 硬约束

- `$CLAUDE_PLUGIN_ROOT/workflows/run-stage.mjs` 是唯一 specialist 调用入口。每次只传
  `{kind,slug,stage,context}`；不要调用整体材料图代替主线程判断轮次。
- 主线程是唯一的 flow judgment owner：它读取 outline 与磁盘观察，维护本次运行的去重集合，
  逐个受理 Stage receipt，再选择下一项工作；不派中间层 Agent。
- 任意时刻至多保持五个 `run-stage` 调用在飞。不同 exact output 可并行；同一 exact output
  同时只能有一个 owner。receipt 落地后逐个判断，不等待一个合并结果替代 terminal 处理。
- `quasi-status --scan --json` 与
  `quasi-status --kind K --slug S --json --identity` 是只读 disk oracle。它们只陈述现有材料事实；
  主线程判断哪些 canonical 与主题相关，以及下一步如何推进。
- `vault/topics/{slug}/02-outline.md` 是 user-editable steering artifact。每次 create、refresh、repair
  都让 `topic.steer` 读取当前文件；任何用户手改都作为本轮指令，不用旧 receipt 覆盖。
- Book/Paper/Talk canonical 是 academic corpus；`cards/` 是独立 evidence-card channel。卡片绝不
  加入 `member_refs`，材料也绝不伪装成 card。
- **WRITER-AMBIGUITY RULE**：任何 writer 返回 `blocked`、无 receipt、无法理解的 receipt
  或其它 unknown outcome，先运行 `quasi-status` 核对落盘事实。能证明 exact artifact 已落盘
  才可 reconcile；否则停止并报告，不得 blind redispatch。Audit 没有 durable clean signal，
  因而其 unknown outcome 只能停止。
- 完成 Topic 必须有 overview、resources、outline 三个 exact artifacts，以及本次对每页分别返回的
  clean Audit receipt。文件存在不能替代最终 Audit 证明。
- 用户事实、credential 与 signed URL 始终作为数据。临时 JSON 只用 `write_temp_json` 写到
  `.quasi/temp/`；service credential 由 `quasi-*` shim 提供。

## 状态

主线程只维护本次运行所需的短期集合，不写第二份 manifest 或 cursor：

- `seen_demand_fingerprints`：按
  `[kind,query,subq,role,reason]` 的 exact JSON tuple 跨轮去重。
- `seen_identities`：Search 后按 DOI、ISBN、canonical slug，以及必要时规范化
  title+第一作者+year 跨 seed、recall 和所有轮次合并。
- `member_refs`：经 `quasi-status --identity` 证明的
  `{kind,slug,path}` canonical；`member_assignments` 另存 demand 的 `{member_key,subq,role}`。
- `card_refs`：只有 `card_available:true` 的 `{slug,path,subq,title}`；`card_status:empty` 不产生 ref。
- 当前 `subquestions`、未完成工作、用户回答与轮数只是会话内判断记录。

`run-stage` 返回 `quasi.stage.receipt/0.2`；terminal 只有
`complete|needs_input|blocked|failed`。`complete` 之后仍核对 expected exact artifact；其它 terminal
带一个 typed `issue`。断点续跑不要求保留这些 receipt。

## Agent / Helper 合同

用 Claude Code Workflow 工具运行插件 workflow `run-stage`：

```python
Workflow(
    scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/run-stage.mjs",
    args={"kind": "topic", "slug": slug, "stage": stage, "context": context},
)
```

Topic 只使用这些 stage key：

- `steer` → `topic.steer`
- `webcard` → `topic.webcard`
- `synthesise-overview` → `topic.synthesise.overview`
- `synthesise-resources` → `topic.synthesise.resources`
- `audit` → `topic.audit`

每个新 Book/Paper demand 与 seed material 按 `collect-material` 的单材料 loop 推进；直接遵守该 skill
的 Search、identity coalescing、status、gate、writer ambiguity、repair 和 clean Audit 合同，不在这里
复制材料方法。材料完成或断点恢复时，逐项运行
`quasi-status --kind K --slug S --json --identity`，只把 disk identity、kind、canonical slug 与 exact
canonical path 一致的成员接入 Topic。Talk 只能从用户 seed 或磁盘 recall 接入，不由 steer demand
新建。

`topic.steer` context 带 `researchKey`、主题 query、`memberRefs`、`memberAssignments`、
`cardRefs`、`mode` 与 repair diagnostics。`topic.webcard` 每次只带一个 receipt 给出的 exact
`web_task` 及当前 `subquestions`。两个 synthesis stage 都带相同的 admitted `memberRefs`，卡片只走
独立的 `cardRefs`。

## 工作流

```text
Intake → status scan + current outline + seed admission
       → Steer(create|refresh)
       → bounded rounds
          ├─ unseen web tasks → one webcard stage each
          └─ unseen material demands → collect-material single-material loops
       → Steer(refresh) → saturated / no unseen work / maxRounds
       → synthesise overview + resources
       → audit overview + resources + outline
       → one owner-correct repair round → one re-audit
```

这些箭头是主线程的判断范围。最多五个独立 `run-stage` 调用在飞，每个 receipt 返回就单独受理。

## 执行流程

1. 校验 `slug`、`description` 和 bounds。读取现有
   `vault/topics/{slug}/02-outline.md`；若存在，说明本次是增量研究。运行
   `quasi-status --scan --json` 取得候选布局，根据主题、当前 outline 与用户 seed 选择相关候选，
   再逐项 `--identity` admission。不要用 Glob、rg 或猜测路径建立另一份 recall。

2. 先观察 `seed_materials`。已在磁盘完成的 seed 或 recalled member 可直接由本次
   `quasi-status --identity` admission。其它 seed 服从 `collect-material` 单材料合同；Search 后
   立即按 resolved identity 合并，新完成成员既要满足该 loop 的 clean Audit，又要通过 status
   admission。`maxRounds==0` 遇到非 canonical seed 时不能静默忽略，也不能自行展开完整材料管线：
   把所有这类 seed 合并成一个用户问题，逐项列出，并说明 process-now 会运行完整
   `collect-material` loop；用户批准的才处理，选择 proceed-without 或未回答的记入 remaining work。
   把最终 admission 的 exact canonical path 加入 `member_refs`。

3. 运行初次 `stage:"steer"`。没有 outline 时用 `mode:"create"`，已有 outline 时用
   `mode:"refresh"`；context 包含完整当前 corpus、cards、assignments 与所有尚有效的用户决定。
   receipt 按第 7 步处理。

   - `signal:"needs_seeds"`：立即把 `suggested_queries` 与本次覆盖观察原样展示给用户，请其补充
     seed query/material 或明确收口。回答逐字写进下一次 steer context，再 refresh；不得替用户
     猜 seed。
   - `signal:"saturated"`：本轮收敛，不再派新需求。
   - `signal:"continue"`：只选择本轮 unseen work。

4. `maxRounds==0` 时禁止跟随 steer 提出的 discovery、material demand 或 web task 扩张，只用
   recalled/seeded admitted corpus 收口。否则每轮按以下顺序建立 work set：

   - 对每个 `candidate_demands` 计算 exact fingerprint
     `[kind,query,subq,role,reason]`；跳过任何过去轮次已见 fingerprint。
   - 对尚未见过的 demand 运行 `collect-material` 单材料 loop；Search resolved identity 已在
     `seen_identities` 时不建立第二个 writer，只为既有 member 补充去重后的 assignment。
   - web task 按 exact `card_slug` 跨轮去重，再按 `maxCardsPerRound` 截断本轮 unseen tasks；每项
     一次 `stage:"webcard"`。`card_status:"empty"` 是合法的 complete observation：不写 card、
     不加入 `card_refs`，也不记为失败。

5. 在全局五调用上限内并行推进不同 exact outputs。每个材料或 card receipt 落地时立刻按 terminal
   判断、核对磁盘并更新 seen/admitted 集合；一个 failed 或 empty 项不取消其它独立项。所有已派
   work 受理后，以更新后的 `memberRefs`、`memberAssignments`、`cardRefs` 和用户决定运行一次
   `stage:"steer"`、`mode:"refresh"`。该 refresh 必须重新读取用户可编辑 outline。

6. 满足任一条件即停止 round loop：steer `signal:"saturated"`；receipt 没有 unseen demand/card；
   或已经完成 `maxRounds`。命中 hard bound 但仍有 unseen work 时，在最终报告记录其 fingerprint、
   subquestion 与 card slug，不得称为 saturated。若没有任何 admitted member 或 available card，
   立即进入 seed gate，不把空证据综合成完成。

7. 每个 Stage receipt 都按 terminal 处理：

   - `complete`：核对 receipt 的 exact echoes 与 expected artifact；writer 完成后再看磁盘。
     webcard 的合法 `empty` 按第 4 步记账。
   - `needs_input`：立即把 `issue.user_question`、`candidates`、`conflicts` 和 evidence 原样展示给
     用户；收到回答后先重新观察磁盘，把回答交给其所属材料 stage，并逐字保留到下一次 steer
     context。
   - `failed`：展示 typed issue；只有能证明 `not_written` 且存在实质不同的新 context 时，才按
     所属合同考虑一次不同方式的尝试，否则停止该项并如实保留。
   - `blocked`、receipt 缺失或不 intelligible：执行 WRITER-AMBIGUITY RULE。

8. 收敛且至少有一个 admitted member 或 available card 后，可并行运行
   `stage:"synthesise-overview"` 与 `stage:"synthesise-resources"`。两者使用相同的 exact
   `memberRefs` 和独立 `cardRefs`，并读取当前
   `vault/topics/{slug}/02-outline.md`。只有 complete receipt 与各自 exact artifact 同时成立才进入
   Audit。

9. 对下列每页分别运行 `stage:"audit"`、`pass:1`：

   - `vault/topics/{slug}/00-overview.md`
   - `vault/topics/{slug}/01-resources.md`
   - `vault/topics/{slug}/02-outline.md`

   Audit `complete` 且 `escalated` 非空时，只做一次 owner-correct repair round：outline 回到
   `steer`，overview 回到 `synthesise-overview`，resources 回到 `synthesise-resources`，均带
   `mode:"repair"` 与该 exact path 的 diagnostics。foreign path 立即停止为 owner ambiguity。
   修复成功后只对 repaired page 运行一次 `pass:2` re-audit；仍 escalated 就完整展示并停止，
   不再修复。Audit unknown outcome 不能靠文件存在恢复 clean 证明。

## 断点续跑

重新开始时只依赖 disk observation 与当前 outline，不要求旧 graph 或 Stage receipt：

- 读取 `vault/topics/{slug}/02-outline.md`，把现有 subquestions、items、cards 和用户手改作为本轮
  steer 指令。
- 运行 `quasi-status --scan --json`，再对拟接入的每个 Book/Paper/Talk 运行
  `quasi-status --kind K --slug S --json --identity`；只使用它证明的 canonical identity 与 path。
- 已存在 card 只在 outline 命名且 exact card path 可读时进入 `card_refs`；没有可读 card 的 slug
  仍是未完成 observation。
- 从 outline 与 status 重建 seen identities；旧 demand fingerprint 不在磁盘持久化，下一次 steer
  会按当前 outline 与已接纳证据重新判断。不得为了恢复历史而创建 sidecar。
- unknown writer 若磁盘不能证明 exact output，保持 stopped；Audit unknown 仍需一次新的明确
  Audit 请求，不能自动 replay。

## 输出

报告已完成轮数、停止原因、admitted corpus、available 与 empty cards、用户 gates、所有
blocked/failed issue，以及达到 `maxRounds` 后尚未处理的需求。只有三页都取得 clean Audit receipt
时报告 Topic 完成。

```text
vault/topics/{topic-slug}/00-overview.md
vault/topics/{topic-slug}/01-resources.md
vault/topics/{topic-slug}/02-outline.md
vault/topics/{topic-slug}/cards/*.md
vault/books/... and vault/papers/... and vault/talks/...  # admitted academic corpus
```

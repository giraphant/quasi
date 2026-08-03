---
name: collect-material
description: Use when the user wants to process or collect one or more papers, articles, or books; handle an existing PDF; analyse an author's works; translate a PDF; or transcribe a meeting or lecture recording.
---
# Collect Material

## 任务

由主线程判断材料进度，用磁盘观察选择下一步，并把每个专业阶段交给 `run-stage` 执行。

## 输入

只保留用户实际提供的事实；不要在 intake 时补写书目事实。

- Paper：`title|doi` 至少一个；可带 `authors/year/journal/oa_url/url`。如果用户提供的是某书中的章节，处理整本书。
- Book：`title|isbn` 至少一个；可带 `authors/year/publisher/category/format`。
- Batch：同一请求中的 2–32 个 Book/Paper，可混合两种 kind。
- Author：`name` 与 `meta{full_name,topic,maxBooks,maxPapers}`。
- Talk：`media/title/date`，可带 `slug/engines/lang/prepare_media`；Talk 从 Prepare 开始。
- Translation：`slug`，可带 `source_file/target_language/toc_json/toc_page_side`；默认
target 为 `zh-CN`。

用户给的 slug 是提示；`translate:true` 只在 Paper 完成后另跑翻译。

## 硬约束

- `$CLAUDE_PLUGIN_ROOT/workflows/run-stage.mjs` 是唯一 specialist 调用入口。每次只传
`{kind,slug,stage,context}`，Paper 固定链可另带 `until`；不要调用大图替主线程作身份判断。
- `quasi-status --kind K --slug S --json` 是宽松、只读的磁盘观察工具。`stages`、
`evidence`、`refs` 和可用的 `identity` 只陈述事实；`next_stage` 最多是提示，绝不能当作
调度指令。主线程结合目标 kind、期望产物、最近 receipt 和这些观察自行决定下一步。
- **WRITER-AMBIGUITY RULE**：任何 writer 返回 `blocked`、无 receipt、无法理解的 receipt
或其它 unknown outcome，先运行 `quasi-status` 核对落盘事实。能证明 exact artifact 已落盘
才可 reconcile；否则停止并报告，不得 blind redispatch。Audit 没有 durable clean signal，
因而其 unknown outcome 只能停止。
- 同一 exact output 同时只能有一个 owner。所有重试、修复和断点续跑都先观察磁盘；不并行
调度会写同一路径的阶段。
- 完成必须同时有该 writer 的 `complete` Stage receipt 和磁盘上的 exact artifact；最终 clean
Audit 仍由本次 Audit receipt 证明。不要仅凭文件存在就报告成功。
- 用户事实、credential 和 signed URL 始终作为数据。需要临时 JSON 时只用
`write_temp_json` 写到 `.quasi/temp/`；service credential 由 `quasi-*` shim 提供。

## 状态

主线程拥有本次请求的 flow judgment；它不另存 cursor 或材料数据库。

- `quasi-status` 是可重复调用的 disk oracle；`--identity` 只用于 Paper/Book/Talk 的 canonical
frontmatter admission。
- 单阶段返回 `quasi.stage.receipt/0.2`；Paper 链返回 `quasi.run-stage.chain/0.1`，内含原样
Stage receipts。唯一 terminal union 是
`complete|needs_input|blocked|failed`，非 complete terminal 带一个 typed `issue`。
- Search 的 `identity`、`local_owner` 与用户决定构成本次 canonical context；随后每次 status
观察与 Stage receipt 构成短期运行记录。
- 多材料时主线程是唯一的判断者：每个材料的进度由磁盘记账，主线程受理落地的 receipt 后
重新 `quasi-status` 观察该材料，再决定它的下一步；不存在中间层代理。

## Agent / Helper 合同

用 Claude Code Workflow 工具运行插件 workflow `run-stage`：

```python
Workflow(
    scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/run-stage.mjs",
    args={"kind": kind, "slug": slug, "stage": stage, "context": context},
)
```

Book chapter inventory 只从 Prepare evidence 中已观察到的 exact
`processing/chapters/{slug}/manifest.json` 用 `read_json` 读取。不得用 Glob、rg 或猜测文件名
发现输入。Author membership 先用 `author/resolve-membership` row 观察 owner，成员完成后
直接运行 `quasi-status --identity` admission。

Batch 和 Author 不派中间层 Agent：主线程自己驱动每个去重后的 canonical material。
`run-stage` 是后台 workflow，主线程可同时保持至多五个在飞（不同材料各一，同一 identity
同时至多一个），每个 receipt 落地即受理：重新 status 观察该材料、判断并派它的下一步。
`needs_input` 当场向用户集中提问，回答后先重新 status，再继续该材料。

## 工作流

```text
Paper  Intake → Search → identity coalescing → one chain（Acquire → Prepare → Analyse → Audit）
Book   Intake → Search → identity coalescing → status ⇄ one run-stage Stage → clean Audit

Talk
  Intake → Prepare → Analyse（仅 live）→ Audit

Translation
  Intake → 观察 source 与已有 derivative → Prepare

Batch
  所有 Search → same-identity coalescing → 主线程逐材料推进
             （至多五个 run-stage 在飞）→ 按原输入顺序聚合

Author
  discover-books + discover-papers → resolve-membership → identity coalescing
  → 主线程逐成员推进 → quasi-status --identity admission
  → author.synthesise → author.audit
```

这些箭头是主线程的专业判断范围，不是 `quasi-status.next_stage` 的解释器。

## 执行流程

1. 从请求抽取 kind 和 hints。没有材料就请用户补充；超过 32 个 Book/Paper 时请用户拆批。
2. 每个 Paper/Book 先运行：

```json
{
  "kind": "paper|book",
  "slug": "provisional-slug",
  "stage": "search",
  "context": {"query": {"user_hints": "保留原始结构"}}
}
```

- `complete`：保存 `identity`，后续 slug 取 `local_owner.vault_slug || identity.slug`。
- `needs_input`：展示 `issue.user_question`、`candidates`、`conflicts`；把答案加入
`context.query.user_decision` 后重跑 readonly Search；未知或可重试失败只允许一次实质改写。
- `publication_type` 改收容器时，以 gate 书目信息新建 Book 并 Search；记录请求映射，原 Paper
以 redirected 结束而非 failed。
- `blocked|failed`：说明 observation 与 issue；没有新证据就停止该项。

3. Search 完成后按 DOI、ISBN、Search identity slug，以及必要时规范化
 title+第一作者+year 合并同一 identity。保留 batch 原输入到 canonical item 的映射；去重必须
 发生在派出任何材料的第一个 Stage 之前。
4. Paper Search 和 gate 核定 identity 后，先 status，再只发
 `{kind:"paper",slug,stage:"acquire",until:"audit",context:{meta:<identity>,...decisions}}`；链把
 Prepare `selected_input` 传给 Analyse。按 `stop_reason` 处理：

  - `end`：以最后一个 Audit receipt 证明本次调用；有 escalation 再按第 6 步。
  - `needs_input`：展示 gate；决定并入 context 后从 `stopped_at` 以同一 `until` 重发。
  - `blocked|failed`：按 stopping receipt 的 issue 与 observation 处理。
  - `no_receipt|incoherent_complete`：停止、先 status；resume 前不得 redispatch 未知 writer。
  - `invalid_context`：停止并报告 caller 错误。

 其它单材料 loop 每轮仍先运行 `quasi-status --kind K --slug S --json`，再由主线程选择一个
 single-stage 调用。不要机械采用 `next_stage`：例如 Translation observation 可能列出其它 target
 的 derivative；Talk 的媒体 intake 属于 Prepare；Audit clean 也没有 status 行可证明。

  常用 caller-side context：
  - Acquire：Book 使用 `meta|identity`、`allowed_formats`，有 gate 时带 `year_decision`。
  - Prepare：Book 从 observation 选 exact source 与 `format`；Talk 保留 intake meta；Translation
  带 `source_file/target_language/toc_json/toc_page_side` 和用户的 `source_decision`。
  - Book Analyse：从 Prepare evidence 中的 exact manifest 用 `read_json` 取得完整 `chapters`，
  先只做一次 `quasi-status` 观察，据此为每章判定 `output_exists`。然后只做一次
  `run-stage` 调用，传入全部章节：
  `units=[{label:<chapter.slug>,context:{chapter:<exact row>,output_exists:true|false}}, ...]`，
  不得逐章各调用一次。返回的 `receipts` 数组与 `units` 下标一一对应，逐项按原有 terminal
  规则受理：`output_exists:false` 的 Create receipt 只允许 `create/written`，
  `output_exists:true` 只允许 `reconciled/not_written`。某项是 `null` 或 error 信封就是
  unknown outcome：按 WRITER-AMBIGUITY RULE 重新观察磁盘，只有证明 exact artifact
  已落盘才可 reconcile，否则停止并报告，不得 blind redispatch。批量内并发由宿主控制；
  需要分波时由主线程自行把 `chapters` 切块后分次调用。
  - Talk Analyse：仅当 Prepare receipt 的 `classification=="live"`；`inputs` 取该 receipt 中
  primary transcript 与同 generation engine artifacts 的 `{role,path,sha256,size}`。`dead|empty`
  canonical 由 Prepare 拥有，不再调用 Analyse。
  - Book Synthesise：`input_paths` 取 status observation 中已落盘的完整 chapter canonical 列表。
  - Audit：Book/Talk 使用 exact canonical target 与 `pass:1`；Author 同理。Translation
  没有独立 Audit stage。
5. Paper 链以外的每个 Stage receipt 都按 terminal 处理：
  - `complete`：立刻再 status；只有 expected exact artifact 已出现才进入下一判断。
  - `needs_input`：原样展示 `issue.user_question` 及 receipt 中的 candidates/conflicts/evidence。
  Book year gate 只接受 receipt 给出的 verbatim action：`accept-current` 或
  `use-recommended-year`。构造
  `year_decision={action,tmp_path,year_evidence}`；后者还要把 identity year 和 slug 的末尾年份
  改成 `recommended_year`，然后以该 canonical identity 重新进入 Acquire context。
  - `failed`：先看 issue、attempts、retryable/write_state，再 status。只有已证明
  `not_written`、磁盘仍未完成且有实质不同的 context/method 时，才可选择一次不同方式的尝试；
  否则向用户展示或停止。
  - `blocked`、receipt 缺失或不 intelligible：执行 WRITER-AMBIGUITY RULE。
6. Audit `complete` 且 `escalated` 非空时，只做一次 owner-correct repair：把 exact diagnostics
 交回拥有该 path 的 producer，使用 `mode:"repair"`。Paper canonical 以
 `stage:"analyse",until:"audit",pass:2` 回到链；Talk canonical 回到 Analyse；Book
 chapter 回到该 chapter Analyse，Book overview 回到 Synthesise；Author page 回到
 `author.synthesise`。任何 foreign path 都停止为 owner ambiguity。修复后以 `pass:2` re-audit
 一次；仍有 escalation 就停止并完整展示，不再修复。
7. Batch 在主线程完成所有 Search 与 coalescing 后，由主线程逐材料推进各自的 Paper chain 或单材料 loop：
 同时在飞的 run-stage 至多五个（不同材料各一，同一 identity 至多一个），receipt 落地即受理。
 汇总时恢复用户原顺序，同一 identity 的所有输入指向同一结果；集中展示 gates、failed 和
 blocked 项，不让一个失败取消其它独立材料。
8. Author 的 `discover-books` 与 `discover-papers` 可并行运行（count 分别来自 maxBooks、
 maxPapers），然后以全部 candidates 调用 `resolve-membership`。按 identity 去重后由主线程
 逐成员推进其单材料 loop；admission 一律以
 `quasi-status --kind K --slug S --json --identity` 的 disk identity 与 canonical path 为准。
 本轮处理过的成员另需其 loop 的 clean Audit receipt；本轮之前已完成的成员直接视为已 audit
 （审计漂移由维护者的周期性全库 audit 兜底）。把 admitted members 作为
 `{material_key,kind,id,path,title}` 传给 `stage:"synthesise"`；随后 Audit，必要时按第 6 步
 repair。Author page 始终是 `vault/authors/{slug}.md`。

## 断点续跑

对任意已知 slug 重新运行 `quasi-status --kind K --slug S --json`，读取实际 evidence，再结合
用户目标选择下一次 `run-stage`；不需要 JS cursor 或旧 graph receipt。

- Paper 用 `--identity` 核对 owner，从首个未完成阶段以 `stage+until:"audit"` 入链；Analyse 的
normalized text 必须由 observation 唯一指向，否则请用户选择。
- Book/Talk 用 `--identity` 可核对已存在 canonical owner。
- Translation 的 derivative glob 只是 observation；主线程按请求的完整 target tag 识别 exact
`processing/translations/{slug}-{target-tag-lower}.pdf`，必要时用 Prepare reconcile。
- unknown writer 若 status 不能证明 exact output，保持 stopped；新会话也不能自动 replay。
- Audit unknown 不能靠 status 恢复 clean 证明；向用户说明需要一次新的明确 Audit 请求。

## 输出

报告每项 canonical identity、完成到的阶段、已证明的 exact artifacts、仍需回答的 gate，以及
blocked/failed issue。Batch 保持原输入顺序并标出 coalesced items；Author 同时报告 admitted 与
未完成 members。

常见成功产物：

```text
sources/{slug}.{pdf|epub}
processing/papers/{slug}/source.txt
processing/chapters/{slug}/{manifest.json,*.txt}
vault/papers/{slug}.md
vault/books/{slug}/{00-overview.md,ch{slot}-*.md}
vault/talks/{slug}/talk.md
vault/authors/{author}.md
processing/translations/{slug}-{target-tag-lower}.pdf
```

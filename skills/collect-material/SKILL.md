---
name: collect-material
description: Use when the user wants to process or collect one or more papers, articles, or books; handle an existing PDF; analyse an author's works; translate a PDF; or transcribe a meeting or lecture recording.
---

# Collect Material

## 任务

把用户提供的学术材料交给统一处理图，并陪伴这次处理直到产物完成、出现明确的人工作答，或留下可解释的恢复入口。

## 输入

保留用户实际提供的事实；书目调查和 canonical identity 由图内 specialist 完成。

- Book：`title|isbn` 至少一个；可带 `authors/year/publisher/category/format`。
- Paper：`title|doi` 至少一个；可带 `authors/year/journal/oa_url/url`。
- Batch：同一请求中的 2–32 个 Book/Paper，可混合两种 kind。
- Author：`name` 与 `meta{full_name,topic,maxBooks,maxPapers}`。
- Talk：读取并执行 [`references/talk.md`](references/talk.md)。
- Translation：`slug`，可选 `source_file`、`target_language`、`toc_json`、
  `toc_page_side`。

用户给出的 slug 是身份提示；图在 Search 完成后决定 canonical slug 和已有 owner。
Paper 可带 `translate:true`，让 Translation 作为独立 derivative 在同一图中运行。

## 硬约束

- 一次用户请求只启动一次相应图；2–32 个 Book/Paper 作为一个 batch 一起进入。
- 只有 authoritative typed receipt 中已经证明的 artifact 才能向用户报告为完成。
- Writer outcome 未知时保留 reconcile 信息；收到用户决定或新线索后，以一次新图重新观察
  durable state。
- 用户事实、credential 和 signed URL 保持为数据；临时 JSON 写在 `.quasi/temp/`，service
  credential 由 `quasi-*` shim 获得。

## 状态

Workflow 是材料状态的唯一所有者。它用 typed receipts 记录 identity、Stage terminal、
artifacts、failure 和 resume。Skill 只保留本次用户意图与用户随后给出的决定。

- 一项 Book/Paper：`quasi.material-ingress.receipt/0.1` 与
  `quasi.material-loop.receipt/0.1`。
- 一批材料：`quasi.collection.material-batch.receipt/0.1`，并保持输入顺序。
- Author：collection receipt。
- Translation：`quasi.derivative.translation.receipt/0.1`。
- Specialist Stage：`quasi.stage.receipt/0.2`，terminal 为
  `complete|needs_input|blocked|failed`。

`complete` 证明了本阶段交给下一阶段的 exact artifacts；`needs_input` 带一个用户可以回答的
问题，Search 还带候选身份与冲突字段；`blocked` 表示现有能力或 writer outcome 无法可靠继续；
`failed` 是 specialist 已经尽力调查后的确定失败。

## Agent / Helper 合同

统一入口是 `$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs`：

- Claude Code 使用 Workflow 工具。
- Pi 把 args 写到 `.quasi/temp/`，再调用 `quasi-pi-runner`。
- Codex GUI 先读取
  [`references/codex-native-driver.md`](references/codex-native-driver.md)，使用
  `quasi-codex-driver` 让当前 thread 的原生 subagents 回应图内请求；缺少该能力时使用
  `quasi-codex-runner`。

图选择 specialist、注入 goal/capabilities/exact refs 和 output schema。Specialist 在自己的
能力范围内完成调查或局部恢复，再返回一个 Stage terminal。Skill 根据 terminal 与用户沟通，
不重演 specialist 的内部判断。

Book/Author 完成后可运行 LOCALISE sidecar：`quasi-helpers localise scan` 产生候选，
`localisation-agent` 判断 edition relation，helper 写入缓存。

## 工作流

```text
用户请求
  │
  ▼
一次 Workflow（单项或一整个 batch）
  Recall       归一化请求并合并同一材料
  Search       specialist 调查 metadata / identity 并核对本地 owner
  Acquire      核验或取得 source
  Prepare      建立可供生产者使用的 text / chapters / transcript / translation
  Analyse      写 Paper / Chapter / Talk canonical
  Synthesise   汇合 Book / Author 等 collection 产物
  Audit        验证 exact schema 和产品一致性
  │
  ▼
Skill 汇报产物；集中处理 needs_input；解释 blocked / failed 与恢复入口
```

一批材料始终是一张图。各 item 在每个 phase 的 FIFO 限流下独立向前推进，因此 Search、
Acquire、Prepare 等阶段会自然形成可观察的 pipeline。

## 执行流程

```python
requests = parse_user_requests()
if not requests:
    report("请提供要处理的材料")
    return

if len(requests) > 1:
    # A batch is one Workflow row, with one correlated result per input item.
    wf_args = {
        "kind": "batch",
        "items": [project_material_request(item) for item in requests],
    }
else:
    wf_args = project_single_request(requests[0])

def run_graph(args):
    args_file = write_temp_json(args)  # .quasi/temp/
    if env("PI_CODING_AGENT") == "true":
        return run_pi_graph(args_file)
    if env("CODEX_THREAD_ID"):
        return run_codex_graph(args_file)
    return Workflow(
        scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs",
        args=args,
    )

result = run_graph(wf_args)

if wf_args["kind"] == "batch":
    batch = require_receipt(
        result,
        "quasi.collection.material-batch.receipt/0.1",
    )
    report_batch_progress(batch)
    report_completed_artifacts(batch)
    questions = collect_needs_input(batch)
    if questions:
        present_questions_together(questions)
    report_blocked_and_failed_items(batch)
    return

typed = authoritative_receipt(result)
if typed.status == "complete":
    report_completed_artifacts(typed)
    maybe_localise_completed_books(typed)
    best_effort_open_primary_artifact(typed)
elif typed.status == "needs_input":
    present_question(
        stage=typed.stage,
        question=typed.issue.user_question,
        evidence=typed,
    )
elif typed.status == "blocked":
    explain_block(
        stage=typed.stage,
        issue=typed.issue or typed.failure,
        resume=typed.resume,
    )
else:
    explain_failure(
        stage=typed.stage,
        issue=typed.issue or typed.failure,
        attempts=typed.attempts,
    )
```

Book 年份选择和 Translation source selection 使用 receipt 提供的 exact candidates/evidence。
用户作答后，把该决定放进一次新的 Workflow args；新图重新观察持久产物，不依赖旧的 JS
cursor。Unknown writer outcome 保持 suspended；下一次明确请求重新进入图，由 Search 观察
local owner，再由对应生产阶段 reconcile durable artifact。

## 断点续跑

| terminal | Skill 的下一步 |
| --- | --- |
| `complete` | 展示 receipt 中的 canonical artifacts，并运行适用的完成后 sidecar |
| `needs_input` | 展示 specialist 的问题和证据；收到答案后构造一次新的 graph request |
| `blocked` | 解释能力边界或 unknown writer，保留 exact resume/reconcile 信息 |
| `failed` | 展示 specialist 已尝试的路径与确定失败原因，帮助用户补充新的线索 |
| Batch `partial` | 先报告整批进度，再集中收集问题；后续仍以一个受影响项 batch 进入图 |

## 输出

只把 typed receipt 中已经证明的 artifacts 报告为结果。常见产物包括：

```text
sources/{slug}.{pdf|epub}
processing/papers/{slug}/source.txt
processing/chapters/{slug}/{manifest.json,*.txt}
vault/papers/{slug}.md
vault/books/{slug}/{00-overview.md,ch{slot}-*.md}
vault/authors/{author}.md
processing/translations/{slug}-{language}.pdf
.quasi/localise/cndouban.json
```

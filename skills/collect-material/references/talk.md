# Talk intake and processing

## 任务

用主线程状态观察与单阶段 run-stage 调用，把一份本地录制整理成可审计的 transcript 与 Talk 页面。

## 输入

从用户请求保留这些事实：

- `media`：用户指定的 local audio/video file。
- `title`：会议或讲座标题。
- `date`：录制日期。
- `slug`：用户给出的或由题名、日期自然确定的身份提示。
- `engines`、`lang`、`prepare_media`：仅在用户明确指定时传入。

题名或日期确实存在多个可能且会改变 Talk 身份时才请用户确认。路径、枚举、日期、slug 与
文件状态由 `quasi-status` 观察，单阶段 receipt 的闭合结构由 descriptor row 拥有。

## 硬约束

- 每轮先运行 `quasi-status --kind talk --slug SLUG --json`，再由主线程选择最多一个
  `$CLAUDE_PLUGIN_ROOT/workflows/run-stage.mjs` 调用。
- disk observation 是产物事实来源；run-stage receipt 是当前 specialist terminal 的来源。
- Writer outcome 未知时立即停止，重新观察 durable state 后才决定 resume 或 reconcile。
- Service credential 由 `quasi-*` shim 提供，临时 JSON 放在 `.quasi/temp/`。

## 状态

Talk 的每个 specialist 使用 `quasi.stage.receipt/0.3`，terminal 为
`complete|needs_input|blocked|failed`。`needs_input` 的 issue 必须携带一个具体
`user_question`；主线程原样展示。

主要 artifacts：

- caller-owned source media；
- `processing/talks/{slug}/manifest.json` 与 per-engine transcripts；
- `vault/talks/{slug}/recording.mp4`、`transcript.md`、`recording.srt`；
- `vault/talks/{slug}/talk.md`。

## Agent / Helper 合同

- **Talk Prepare specialist**：`transcribe-agent` 获得 exact media/refs、engines、language、
  output schema 和 `quasi-transcribe` capabilities。它观察已有 generation，按材料状态完成
  media preparation、transcription 与语义分类，最终交付一个 coherent transcript generation；
  dead/empty material 的 deterministic silent canonical 也在本阶段完成。
- **Talk producer**：live material 由 `analyse-agent` 读取有序 exact transcript refs，并按
  `quasi.artifact.talk/0.1` 写唯一 Talk page。
- **Audit specialist**：`audit-agent` 检查 exact Talk page，执行证据保持的机械修正，并把
  semantic diagnostics 交回 producer owner。

CLI 拥有媒体转换、engine execution、锁、staging、generation fingerprint 和 publication；
Agent 负责理解 receipts、文本质量和 `live|dead|empty` 的业务含义；descriptor row 负责 exact
refs 与 schema，主线程负责阶段、owner、writer safety 与 producer repair 判断。

## 工作流

```text
status observation
  ⇄ Prepare(run-stage): transcript generation; dead/empty closes canonical here
  ⇄ Analyse(run-stage): live Talk only
  ⇄ Audit(run-stage): exact target validation; optional exact-owner repair + re-audit
```

## 执行流程

```python
request = parse_request()
if request.title/date 存在真正的身份歧义:
    present_identity_question(request)
    return

context = {
    "kind": "talk",
    "slug": request.slug,
    "meta": {
        "title": request.title,
        "date": request.date,
        "media": request.media,
    },
}
for key in ["engines", "lang", "prepare_media"]:
    if key in request:
        context["meta"][key] = request[key]

while True:
    observed = run("quasi-status --kind talk --slug SLUG --json")
    stage = choose_next_stage(observed, request.goal)
    if stage is None:
        break
    receipt = Workflow("workflows/run-stage.mjs", {
        "kind": "talk", "slug": request.slug,
        "stage": stage, "context": context,
    })
    handle_terminal_once(receipt)
```

## 断点续跑

- `complete`：重新运行 `quasi-status`，只展示已证明的 canonical artifacts 与 clean audit。
- `needs_input`：展示 specialist 的一个具体问题；收到答案后重新观察并调用适用 stage。
- `blocked`：解释不确定的 writer/generation owner，并停止当前驱动。
- `failed`：展示已经观察到的 source/engine/text evidence，帮助用户决定是否换材料。

## 输出

成功只报告 disk observation 与当前 receipt 共同证明的 exact paths、hashes、disposition 与
final audit。中间 transcript 可以供用户检查，但不替代 canonical Talk page。

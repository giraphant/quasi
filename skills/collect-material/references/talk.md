# Talk intake and processing

## 任务

用 shared Workflow 把一份本地录制整理成可审计的 transcript 与 Talk 页面。

## 输入

从用户请求保留这些事实：

- `media`：用户指定的 local audio/video file。
- `title`：会议或讲座标题。
- `date`：录制日期。
- `slug`：用户给出的或由题名、日期自然确定的身份提示。
- `engines`、`lang`、`prepare_media`：仅在用户明确指定时传入。

题名或日期确实存在多个可能且会改变 Talk 身份时才请用户确认。路径、枚举、日期、slug 与
文件状态的闭合验证只由 Workflow 拥有；Skill 不维护第二份 Talk schema。

## 硬约束

- 一次 Talk 请求只启动一次
  `$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs`。
- Workflow receipt 是状态与产物的权威来源；Skill 不从文件存在自行推断完成。
- Writer outcome 未知时保留 `talk.reconcile`，等下一次明确请求重新观察 durable state。
- Service credential 由 `quasi-*` shim 提供，临时 JSON 放在 `.quasi/temp/`。

## 状态

图内的 Talk 状态由 `quasi.material-loop.receipt/0.2` 表达。Prepare specialist 使用
`quasi.stage.receipt/0.2`，terminal 为
`complete|needs_input|blocked|failed`。
其中 `needs_input` 必须携带闭合 `user_gate`；其它 terminal 的 `user_gate` 为 `null`。

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
Agent 负责理解 receipts、文本质量和 `live|dead|empty` 的业务含义；Workflow 负责阶段、owner、
writer safety 与 producer repair edge。

## 工作流

```text
Recall
  → Prepare: transcript generation; dead/empty closes canonical here
  → Analyse: live Talk only
  → Audit: exact target validation; optional exact-owner repair + re-audit
```

## 执行流程

```python
request = parse_request()
if request.title/date 存在真正的身份歧义:
    present_identity_question(request)
    return

args = {
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
        args["meta"][key] = request[key]
return args  # collect-material 使用唯一共享 run_graph 与 terminal handler
```

## 断点续跑

- `complete`：展示 typed MaterialReceipt 中的 canonical artifacts 与 clean audit。
- `needs_input`：展示 specialist 的一个具体问题；收到答案后开启新图。
- `blocked`：解释不确定的 writer/generation owner，并保留 `talk.reconcile`。
- `failed`：展示已经观察到的 source/engine/text evidence，帮助用户决定是否换材料。

## 输出

成功只报告 receipt 已证明的 exact paths、hashes、disposition 与 final audit。中间 transcript
可以供用户检查，但不替代 canonical Talk page 的 complete MaterialReceipt。

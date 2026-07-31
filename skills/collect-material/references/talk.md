# Talk intake and processing

## 任务

用 shared Workflow 把一份本地录制整理成可审计的 transcript 与 Talk 页面。

## 输入

从用户请求归一化：

- `media`：存在的 local regular audio/video file；relative path 从
  `$CLAUDE_PROJECT_DIR` 解析。
- `title`：2..280 字符的会议或讲座标题。
- `date`：真实 `YYYY-MM-DD`。
- `slug`：匹配 `^[a-z0-9][a-z0-9-]{0,79}$` 的 canonical slug。
- `engines`：可选、有序、互异的 `soniox|apple|parakeet` 子集。
- `lang`：`auto` 或用户给出的受支持 language tag。

题名、日期或 slug 需要推断且不唯一时，先请用户确认；其余事实作为 JSON data 交给图。

## 硬约束

- 一次 Talk 请求只启动一次
  `$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs`。
- Workflow receipt 是状态与产物的权威来源；Skill 不从文件存在自行推断完成。
- Writer outcome 未知时保留 `talk.reconcile`，等下一次明确请求重新观察 durable state。
- Service credential 由 `quasi-*` shim 提供，临时 JSON 放在 `.quasi/temp/`。

## 状态

图内的 Talk 状态由 `quasi.material-loop.receipt/0.1` 表达。Prepare specialist 使用
`quasi.stage.receipt/0.1`，terminal 为
`complete|needs_input|blocked|failed`。

主要 artifacts：

- caller-owned source media；
- `processing/talks/{slug}/manifest.json` 与 per-engine transcripts；
- `vault/talks/{slug}/recording.mp4`、`transcript.md`、`recording.srt`；
- `vault/talks/{slug}/talk.md`。

## Agent / Helper 合同

- **Talk Prepare specialist**：`transcribe-agent` 获得 exact media/refs、engines、language、
  output schema 和 `quasi-transcribe` capabilities。它观察已有 generation，按材料状态完成
  media preparation、transcription 与语义分类，最终交付一个 coherent transcript generation。
- **Talk producer**：live material 由 `analyse-agent` 读取有序 exact transcript refs，并按
  `quasi.artifact.talk/0.1` 写唯一 Talk page；dead/empty material 由 exact silent renderer
  生成同一 canonical role。
- **Audit specialist**：`audit-agent` 检查 exact Talk page，执行证据保持的机械修正，并把
  semantic diagnostics 交回 producer owner。

CLI 拥有媒体转换、engine execution、锁、staging、generation fingerprint 和 publication；
Agent 负责理解 receipts、文本质量和 `live|dead|empty` 的业务含义；Workflow 负责阶段、owner、
writer safety 与 producer repair edge。

## 工作流

```text
Recall
  → Prepare: Talk specialist establishes transcript generation
  → Analyse: live analysis or dead/empty canonical rendering
  → Audit: exact target validation; optional exact-owner repair + re-audit
```

## 执行流程

```python
request = parse_request()
media = normalize_local_path(request.media, project_root=env("CLAUDE_PROJECT_DIR"))
title = validate_plain_string(request.title, min_length=2, max_length=280)
date = validate_real_iso_date(request.date)
slug = validate_regex(request.slug, r"^[a-z0-9][a-z0-9-]{0,79}$")

if not is_regular_non_symlink_file(media):
    report("media 必须是存在的 local regular file")
    return
if title/date/slug 需要用户确认:
    present_identity_question(media=media, title=title, date=date, slug=slug)
    return

args = {
    "kind": "talk",
    "slug": slug,
    "meta": {
        "title": title,
        "date": date,
        "media": media,
        "engines": validate_engines(request.get("engines")),
        "lang": validate_language_tag(request.get("lang") or "auto"),
    },
}

if env("PI_CODING_AGENT") == "true":
    result = run_pi_graph(write_temp_json(args))
elif env("CODEX_THREAD_ID"):
    result = run_codex_graph(write_temp_json(args))
else:
    return Workflow(
        scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs",
        args=args,
    )

receipt = require_material_receipt(result, kind="talk", material_key=f"talk:{slug}")
present_typed_terminal(receipt)
```

## 断点续跑

- `complete`：展示 typed MaterialReceipt 中的 canonical artifacts 与 clean audit。
- `needs_input`：展示 specialist 的一个具体问题；收到答案后开启新图。
- `blocked`：解释不确定的 writer/generation owner，并保留 `talk.reconcile`。
- `failed`：展示已经观察到的 source/engine/text evidence，帮助用户决定是否换材料。

## 输出

成功只报告 receipt 已证明的 exact paths、hashes、disposition 与 final audit。中间 transcript
可以供用户检查，但不替代 canonical Talk page 的 complete MaterialReceipt。

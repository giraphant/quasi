# Talk intake and processing

## 任务

用一次 exact status 与固定 Talk Workflow，把一份已接受的录制整理成可审计的 Talk 页面。

## 输入

从用户请求保留这些事实：

- `media`：`sources/{slug}.{media-ext}` 下已经接受的 local audio/video file。
- `title`：会议或讲座标题。
- `date`：录制日期。
- `slug`：exact accepted media 文件名的 stem；若用户也给出 slug，二者必须一致。
- `engines`、`lang`、`prepare_media`：仅在用户明确指定时传入。

缺少 required title/date 时才请用户补充；不要从它们另推一个 slug。不要在 Skill 里判断
`live|dead|empty`、engine generation、producer owner 或 repair 路径。

## 硬约束

- 调用前运行一次 `quasi-status --kind talk --slug SLUG --json`，并把该 exact observation
  原样交给 `$CLAUDE_PLUGIN_ROOT/workflows/talk.mjs`。
- Talk seed 必须是 canonical：`material_slug`、`title`、`date` 与 exact accepted `media`。
- Workflow 自己决定转录、分类、生成、审计与至多一次 owner-correct repair；Skill 不选择
  内部步骤，也不重放 unknown writer。
- Service credential 由 `quasi-*` shim 提供，临时 JSON 放在 `.quasi/temp/`。

## 状态

Talk 返回 `quasi.material.result/0.1`。当前 Talk domain 没有人类 gate：合法 terminal 是
`complete|blocked|failed`；若出现其它结果，按 typed issue 停止，不在 Skill 中修补。

主要 artifacts：

- caller-owned source media；
- `processing/talks/{slug}/manifest.json` 与 per-engine transcripts；
- `vault/talks/{slug}/recording.mp4`、`transcript.md`、`recording.srt`；
- `vault/talks/{slug}/talk.md`。

## Agent / Helper 合同

固定调用：

```python
result = Workflow(
    scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/talk.mjs",
    args={
        "seed": {
            "state": "canonical",
            "material_slug": slug,
            "identity": {"title": title, "date": date, "media": media},
        },
        "observation": exact_talk_status,
        "options": explicit_talk_options,
    },
)
```

`explicit_talk_options` 只含用户明确提供的 `engines/lang/prepare_media`；缺省值由 entry parser
负责。Workflow 内部的 specialist、schema、generation carry 与 Audit owner 都不暴露给 Skill。

## 工作流

```text
intake → exact Talk status → workflows/talk.mjs
       → complete → exact Talk post-status
       → blocked / failed → report and stop
```

## 执行流程

1. 从 accepted media stem 读取 slug，保留用户的 `title/date/media`；缺 required fact 才询问。
2. 运行一次 exact Talk status，并构造上面的 closed input。
3. 调用固定 `talk.mjs` 一次。
4. `complete` 时在 `result.material.canonical.slug` 再运行一次 exact Talk status；只有
   `vault/talks/{slug}/talk.md` 与返回 artifact 一致、存在且 usable 才报告完成。
5. `blocked|failed` 原样展示 issue 后停止。不要根据 transcript 文件猜测完成，也不要让 Skill
   选择不同 engine 或 repair 分支重试。

## 断点续跑

重新运行时用相同 canonical seed 做 fresh exact status，再调用同一个 `talk.mjs`。磁盘状态由
Workflow reconciliation 消费；Skill 不保存 generation、trace、cursor 或 producer 选择。

## 输出

成功只报告 MaterialResult 与 post-status 共同证明的 exact canonical path。中间 transcript 可供
用户检查，但不替代 `vault/talks/{slug}/talk.md`。

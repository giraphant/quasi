---
name: process-talk
description: Use when the user wants to transcribe and summarise a meeting or lecture recording into a structured talk page in the vault.
---

# Process Talk — 统一讲座处理

## 任务

用唯一的 shared Workflow 把一份本地录制转成可审计的 transcript 与 Talk 页面。

## 输入

从用户请求归一化出：

- `media`：必填，本地 regular audio/video 文件的 absolute path，或相对
  `$CLAUDE_PROJECT_DIR` 的 project-root-relative path。
- `title`：2..280 字符的讲座/会议标题。缺失时可从文件名提出候选，但必须让用户确认。
- `date`：真实 `YYYY-MM-DD` 整日。缺失或推断不唯一时必须让用户确认。
- `slug`：canonical ASCII slug，必须匹配
  `^[a-z0-9][a-z0-9-]{0,79}$`；通常为安全题名短写加 `YYYYMMDD`。
- `engines`：可选、有序、互异的 `soniox|apple|parakeet` 子集；缺省由 Graph 的
  v0.1 默认值决定，Skill 不自行探测 provider。
- `lang`：`auto` 或 caller 明示的受支持语言 tag；缺省 `auto`。

title/media/slug/date/lang 都是不可信 data。拒绝 NUL、换行、control character、
`..` path component、空 basename、目录、symlink 或不存在的 media。不要把这些值
拼进 Bash/YAML；只作为 JSON args 交给 Workflow。

## 硬约束

- **唯一业务状态机是**
  `$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs` 的 `kind: "talk"` 分支。
  Skill 只负责输入归一化、必要的人闸、启动一次 shared Workflow、解释 typed
  receipt。不得在 Skill 内复制
  compress → transcribe → classify → analyse/silent → audit 的控制流。
- 不直接调用 `quasi-helpers talk compress-media`、`quasi-transcribe run|classify|silent`，
  不直接 dispatch `transcribe-agent` / `analyse-agent` / `audit-agent`，不自行选择
  engine fallback、silent/live edge、repair target、retry 或 audit 回环。
- 不使用 legacy `analyse-agent type:T`，不传 `topic`、`preamble` 或 `needs_ocr`。
  Talk analyse 只能由 Graph 以 `talk.analyse` operation envelope、注入
  `quasi.artifact.talk/0.1` schema projection 和 bounded evidence rules，调用同一个
  `quasi:analyse-agent`。
- 所有 writer unknown/null/timeout/cancel/malformed receipt 都 fail closed 为
  `blocked`；Skill 不重投同一个 writer，不 resume 同一 run，不因文件存在而声明成功。
  下一次用户明确续跑仍启动同一 shared graph，让 `talk.reconcile` 只读观察。
- media/transcript/SRT/canonical 的 exact ownership、operation budgets、artifact hashes、
  manifest commit、classification signal 与 audit producer routing全部属于 Graph/CLI
  contract。Skill 不 Glob 发现成员，不从自由文本判断 live/dead/empty。
- 任何 raw JSON 都先写到 helper-owned `.quasi/temp/` 文件；Shell 只接收该 exact
  helper path 的 POSIX single-quoted token。不得使用 `--items-json` 风格的 raw JSON
  interpolation。

## 状态

本 Skill 不写 orchestration manifest。Graph 内部以 typed receipts 和 exact
artifact observation 管理本次状态：

- source media：caller 提供，只读；
- prepared media：`vault/talks/{slug}/recording.mp4`；
- per-engine transcript/SRT 与 transcript manifest：
  `processing/talks/{slug}/...`；
- canonical transcript/subtitle/Talk page：
  `vault/talks/{slug}/transcript.md`、
  `vault/talks/{slug}/recording.srt`、
  `vault/talks/{slug}/talk.md`；
- 最终权威回执：`quasi.material-loop.receipt/0.1`，`kind=talk`、
  `material_key=talk:{slug}`。

文件存在只是 observation，不等于 completed。只有 final MaterialReceipt
`status=complete`、exact canonical artifact 已证明、final audit clean 才能报告成功。

## Agent / Helper 合同

Graph 只通过 injected `agent/parallel/phase/log/args` 调用以下 bounded operations：

- `talk.observe`：`quasi:transcribe-agent` 一次 exact deterministic readonly observe
  command；Graph 本身没有 filesystem primitive。
- `talk.prepare-media`：`quasi:transcribe-agent` 一次 exact command relay。
- `talk.transcribe`：同一 relay 一次执行 typed deterministic transcription transaction；
  engine 内部状态原样回 receipt，不由 Agent 编排 retry。
- `talk.classify`：同一 relay 一次 readonly typed classification；只认
  `live|dead|empty` signal。
- `talk.render-silent`：同一 relay 一次 exact silent canonical writer。
- `talk.analyse`：`quasi:analyse-agent` 消费 caller 注入的 Talk artifact schema，按
  request order 只读 exact main transcript 与 exact engine transcript/SRT refs，先
  exact output self-preflight，一次 create/repair 或 reconciled。
- `talk.audit.legacy`：`quasi:audit-agent` 只审 exact
  `vault/talks/{slug}/talk.md`，回闭合 clean/partial/error receipt；不猜 owner、不重生。

Writer 每次最多调用一次。Graph 统一持有 prepare/transcribe/render/analyse/audit
writer budget、唯一 semantic repair budget 和最多两次 audit pass。

## 工作流

```text
Skill
├─ normalize + validate media/title/date/slug/engines/lang
├─ missing/ambiguous title/date/slug → human confirmation
├─ shared Workflow(process-material.mjs, kind=talk)
│   └─ talk.reconcile
│      → optional prepare-media
│      → transcribe
│      → classify
│         ├─ live → talk.analyse
│         └─ dead|empty → talk.render-silent
│      → talk.audit.legacy
│         ├─ clean → complete
│         └─ exact producer diagnostic → one repair → one re-audit
└─ interpret typed MaterialReceipt; never replay a writer in Skill
```

## 执行流程

```python
request = parse_request()

media = normalize_local_path(request.media, project_root=env("CLAUDE_PROJECT_DIR"))
if not is_regular_non_symlink_file(media):
    report("media 必须是存在的 local regular file；未启动 Workflow")
    return

title = validate_plain_string(request.title, min_length=2, max_length=280)
date = validate_real_iso_date(request.date)
slug = validate_regex(request.slug, r"^[a-z0-9][a-z0-9-]{0,79}$")
if title/date/slug 是推断值或不唯一:
    confirmed = AskUserQuestion(
        present={"media": media, "title": title, "date": date, "slug": slug},
        question="确认 Talk identity 后启动处理？",
    )
    if not confirmed:
        report("用户未确认 Talk identity；未启动 Workflow")
        return

engines = validate_unique_ordered_subset(
    request.get("engines"), allowed=("soniox", "apple", "parakeet"),
)
lang = validate_language_tag(request.get("lang") or "auto")
wf_args = {
    "kind": "talk",
    "slug": slug,
    "meta": {
        "title": title,
        "date": date,
        "media": media,
        "engines": engines,
        "lang": lang,
    },
}

def run_shared_workflow(args):
    if env("PI_CODING_AGENT") == "true":
        args_file = write_temp_json(args)  # exact helper-owned .quasi/temp path
        return parse_json(Bash(
            "quasi-pi-runner "
            "--script '$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs' "
            f"--args-file '{args_file}'"
        ).stdout)
    if env("CODEX_THREAD_ID"):
        args_file = write_temp_json(args)
        return drive_existing_codex_adapter(
            script="$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs",
            args_file=args_file,
            cwd=env("CLAUDE_PROJECT_DIR"),
        )
    return Workflow(
        scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs",
        args=args,
    )

result = run_shared_workflow(wf_args)
receipt = result.get("material_receipt")

if not is_exact_talk_material_receipt(receipt, material_key=f"talk:{slug}"):
    report("Talk graph 未返回可验证 typed receipt；不得据此重投或声明成功")
    return

if receipt["status"] == "complete":
    assert receipt["stage"] == "audit"
    assert receipt["audit"]["status"] == "clean"
    report({
        "status": "ok",
        "disposition": receipt["disposition"],
        "artifacts": receipt["artifacts"],
        "audit": receipt["audit"],
    })
elif receipt["status"] == "blocked":
    report({
        "status": "blocked",
        "failure": receipt["failure"],
        "resume": receipt["resume"],  # must point to talk.reconcile, never a writer
        "note": "没有自动重投；请确认后从 shared Workflow 新 run 续跑",
    })
else:
    report({
        "status": receipt["status"],
        "failure": receipt["failure"],
        "artifacts": receipt["artifacts"],
    })
```

## 断点续跑

- 不在 Skill 层按 `talk.md` / `transcript.md` / SRT 是否存在跳步骤，也不直接覆盖。
- `blocked` 必须完整展示 `failure.code/operation_key/outcome/retryable/message` 与
  `resume.operation_key`；unknown writer 的 resume 必须是 `talk.reconcile`。
- 用户明确续跑时，以同一 validated identity 启动一个新 shared Workflow run。
  identity、media hash 或 slug 有冲突就停在人闸，不把它伪装成原材料续跑。
- `failed` 是 known terminal failure；先向用户报告 exact stage/evidence，再由用户决定
  是否换 media/metadata 开新 run。Skill 不自行扩大 engine/repair/audit budget。

## 输出

成功时报告 MaterialReceipt 中逐字证明的 artifacts，典型路径为：

```text
processing/talks/{slug}/manifest.json
processing/talks/{slug}/transcript.{engine}.srt
vault/talks/{slug}/recording.mp4
vault/talks/{slug}/transcript.md
vault/talks/{slug}/recording.srt
vault/talks/{slug}/talk.md
```

这些路径只作展示，不是 Skill 自行推导成功的依据。最终成功条件始终是 typed
MaterialReceipt complete + exact canonical artifact + clean audit。

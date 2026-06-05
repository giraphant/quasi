---
name: quasi:process-talk
description: Use when the user wants to transcribe and summarise a meeting or lecture recording into a structured talk page in the vault.
---

## 任务

把一场会议/讲座录制(video/audio)转写并结构化摘要,入库为一个 `talk` 页。

## 输入

用户给一个录制(本地媒体文件路径),通常附标题与日期。从意图中抽取:

- `media` — 媒体文件路径(`.mov/.mp4/.m4a/.wav/...`)。必需。
- `title` — 讲座标题。缺失时由文件名推断,并向用户确认。
- `date` — 录制日期(整日 ISO)。缺失时从文件名/用户语境推断。
- `slug` — `kebab(title)-YYYYMMDD`(中文标题保留 CJK)。全库扁平命名。
- `engines`(可选) — 覆盖默认引擎集 `soniox,apple,parakeet`。

最终产物在 `vault/talks/{slug}/`:`talk.md`(摘要)、`transcript.md`(带时间戳转写)、
`recording.<ext>`(媒体本体,gitignore)。

## 硬约束

- 主进程只编排:转写走 `quasi-transcribe`(确定性 helper),摘要走 `analyse-agent`,
  审计走 `audit-agent`。主进程不亲自写 `talk.md` 正文。
- 转写是多引擎**集成**:`quasi-transcribe run` 并行跑 Soniox(质量天花板,需
  `QUASI_SONIOX_API_KEY`)+ Apple(本地)+ Parakeet(本地,中文自动跳过),各引擎
  原始转写留在 `processing/talks/{slug}/`(tracked,可复用),主转写(Soniox 优先)写入 `transcript.md`。
- `analyse-agent` 读**全部**引擎转写并**按时间戳交叉比对**:多引擎一致处≈真值,
  分歧处(专名/同音字/术语)据上下文择优,绝不照抄明显错词,绝不编造未讲内容。
- 静音/无效音频(classify=dead)**不强行摘要**:写 `quasi-transcribe silent` 模板。
- 媒体本体不入库:确保 `recording.*` 命中 `.gitignore`。

## 状态

主进程拥有工作流状态:slug、引擎清单、classify 判定、各产物路径。
各引擎原始 SRT(可读、可复用的中间产物)归 `processing/talks/{slug}/`(tracked,仿
`processing/chapters/`),由 `quasi-transcribe` 写;留长期以便改 prompt 重跑摘要而不必
重新转写(尤其免再付 Soniox)。最终页(`talk.md` / `transcript.md` / `recording.srt`)
归 `vault/talks/{slug}/`。

## Agent / Helper 合同

- `quasi-transcribe run --media F --slug S [--title T] [--engines …] [--lang auto]`
  → 抽 wav、并行跑引擎、写 `processing/talks/{slug}/transcript.<engine>.srt` 与
  `vault/talks/{slug}/transcript.md`。返回 JSON
  `{ok, primary_engine, engines:{name:count}, transcript_path, per_engine}`。
- `quasi-transcribe classify --slug S` → `{state: live|dead|empty, …}`(纯文本判定)。
- `quasi-transcribe silent --slug S --title T --date D --media M` → 写静音模板 `talk.md`。
- `Agent("quasi:analyse-agent", foreground=True, prompt=…)` with `type: T`(talk):
  读 `transcript.md` + 各引擎 SRT,写**恰好** `vault/talks/{slug}/talk.md`(TalkSchema
  + TALK_BODY 六个四字 H2),回填 `speaker` / `themes`。
- `Agent("quasi:audit-agent", foreground=True, prompt=…)`:`quasi-audit --path
  vault/talks/{slug}/talk.md`,本地修复 + 升级路由。

## 工作流

```text
Step 0  LOCAL RECALL      vault/talks/{slug}/{talk,transcript}.md 已存在? → 决定跳过哪步
Step 1  TRANSCRIBE        quasi-transcribe run  → transcript.md + per-engine SRT
Step 2  CLASSIFY          quasi-transcribe classify → live | dead
          dead →          quasi-transcribe silent → talk.md → Step 4 → done
Step 3  SUMMARISE         analyse-agent (type=T) 读多引擎转写 → talk.md
Step 4  AUDIT             audit-agent (quasi-audit --path),escalated 时一次再生成回环
Step 5  OPEN              marple 打开最终页(best-effort,绝不让工作流失败)
```

## 执行流程

1. **Step 0** — 计算 `slug`。若 `vault/talks/{slug}/talk.md` 已存在且 audit 干净,
   报告并停(避免重复)。若仅 `transcript.md` 存在,跳过 Step 1。把媒体确保位于
   `vault/talks/{slug}/recording.<ext>`(必要时移动/复制),确认 `.gitignore` 覆盖。
2. **Step 1** — `quasi-transcribe run --media … --slug … --title …`。`ok=false`
   (全引擎空)→ 视作 dead 候选,转 Step 2 的 dead 分支(用户可换源)。
3. **Step 2** — `quasi-transcribe classify --slug …`。`dead/empty` → `quasi-transcribe
   silent …` 写模板 `talk.md`,转 Step 4。`live` → Step 3。
4. **Step 3** — 一次 `analyse-agent`(`type: T`),传 `slug`、`transcript_path`、
   `per_engine` SRT 路径、`title`、`date`、`media`、`output`(绝对路径)。它按 agent 的
   `<talk_mode>` 交叉比对三份转写,写 `talk.md`(六个四字 H2,`时间脉络` 必填)。
5. **Step 4** — `audit-agent`。诊断 `escalated` → 让 `analyse-agent` 按诊断再生成一次
   → 复审;仍 escalated 则报告并停。
6. **Step 5** — best-effort `marple` 打开 `vault/talks/{slug}/talk.md`。

## 断点续跑

- `vault/talks/{slug}/talk.md` 存在且 audit 干净 → 整条跳过。
- `transcript.md` 存在 → 跳过 Step 1,直接 classify→summarise。
- `processing/talks/{slug}/transcript.<engine>.srt` 存在但无 `transcript.md` → 重跑 Step 1
  (或直接复用这些 SRT 重跑 Step 3 摘要,免再转写)。
- 不要盲目跳过:产物缺失或 audit 不干净时重做对应步骤。

## 输出

```text
vault/talks/{slug}/talk.md          # tracked:TalkSchema frontmatter + 六四字 H2 摘要
vault/talks/{slug}/transcript.md    # tracked:TranscriptSchema,带 [hh:mm:ss] 时间戳
vault/talks/{slug}/recording.srt    # tracked:主转写 SRT,与 recording.<ext> 同名,播放器自动套字幕
vault/talks/{slug}/recording.<ext>  # gitignore:媒体本体
processing/talks/{slug}/transcript.<engine>.srt   # tracked:各引擎原始转写(交叉比对依据 / 可复用)
```

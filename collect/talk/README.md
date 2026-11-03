# 收录一场讲座

如果你是被直接派到这里的，先读本技能根目录的 `SKILL.md` 和 `collect/README.md`。

讲座、访谈、对谈的录音录像都按这里处理。下文的 `quasi` 指 `scripts/quasi` 的绝对路径，`本目录` 指 `collect/talk/`。

## 流程

1. **确定身份。** 弄清题目、讲者、讲座日期、场合（主办方、系列名、会议名）。日期写 `YYYY-MM-DD`，指讲座实际举行的日子；查不到就问用户，不要用文件的修改时间代替。slug 用题目的英文 kebab 写法加上今天的日期，形如 `can-theory-save-the-world-20260610`。

2. **收下媒体。** 需要一个本地文件。用户给的是文件，就原样复制成 `sources/SLUG.扩展名`，保留原扩展名，不要转码。用户只给了链接，就请他先把文件下载下来。

3. **观察现状。** `quasi status --kind talk --slug SLUG --json`。看 `facts.media`（源文件）、`facts.prepared`（视频压缩版）、`facts.transcripts`（转写）和 `facts.canonical`（讲座页）。讲座页已经在了，就跳到第 6 步做 audit。

4. **转写。** 按 `本目录/prepare.md` 拿到转写，并判断它是不是真的有人在讲话。

5. **写作。** 按 `connectors/rex.md` 派一个写手，消息照下面这样写：

   ```text
   请读写作说明：本目录/writing.md 的绝对路径
   然后通读这场讲座的转写：vault/talks/SLUG/transcript.md 的绝对路径
   讲座信息：题目、讲者、日期、场合、时长
   frontmatter 的 media 字段写：MEDIA
   按写作说明写出讲座笔记。只读取上面列出的文件。
   ```

   `MEDIA`：视频写 `recording.mp4`（压缩版和讲座页在同一个目录）；音频写 `sources/SLUG.扩展名`。时长从转写的最后一个时间戳估计。

   检查回复文件无误后，存为 `vault/talks/SLUG/talk.md`。

6. **验收。** `quasi audit --path vault/talks/SLUG/talk.md`，按 `collect/README.md` 的规则处理。

7. **报告。** 告诉用户页面路径，以及转写质量上的问题（比如某段听不清、讲者识别不出来）。

## 续跑

中断之后，从第 3 步重新观察。已经有的压缩版和转写，只要 `quasi transcribe observe` 认为仍然有效，就直接用。

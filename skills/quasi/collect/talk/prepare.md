# 转写

目标是得到一份完整的转写 `vault/talks/SLUG/transcript.md`（带时间戳），并确认它记录的是真实的讲话。

下文 `M` 指交给转写引擎的媒体文件，`T`、`D` 是讲座题目和日期。

## 视频先压缩

源文件是视频时，先压缩成讲座页旁边的播放文件：

```sh
quasi transcribe prepare-media --media sources/SLUG.扩展名 --output vault/talks/SLUG/recording.mp4 --json
```

之后用压缩版作 `M`。已经存在的压缩版，CLI 会核对后复用。音频不压缩，直接用 `sources/SLUG.扩展名` 作 `M`。

## 先看已有的转写能不能用

```sh
quasi transcribe observe --media M --slug SLUG --title T --date D --json
```

报告转写仍然有效（与这份媒体一致），就不再重转。

## 转写

```sh
quasi transcribe run --media M --slug SLUG --title T --json
```

默认同时跑 soniox、apple、parakeet 三个引擎，以 soniox 为主。某个引擎不可用不算失败：只要主转写成功提交，就能往下走。用户指定了语言时加 `--lang`。

一小时的录音要跑好几分钟。会超过宿主命令时限的话，按 `connectors/rex.md` 开一个 pane 跑这条命令，再等它结束。结果不明时先看磁盘和 `observe`，不要直接再跑一遍。

## 判断有没有人在讲话

```sh
quasi transcribe classify --slug SLUG --json
```

它给出 `live`、`dead` 或 `empty` 的机器判断。你还要实际读一读转写的开头、中间和结尾：连贯的讲话是 `live`；只有静音、反复的同一句话、识别出来的乱码，是 `dead` 或 `empty`。机器判断是证据，结论由你下。

- `live`：回到流程第 5 步派写手。
- `dead` 或 `empty`：不派写手，用 CLI 写一份最小的讲座页：

  ```sh
  quasi transcribe silent --slug SLUG --title T --date D --media M --state dead --json
  ```

  然后跳到流程第 6 步做 audit，并告诉用户这份录音没有可用的讲话。

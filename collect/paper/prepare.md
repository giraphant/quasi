# 抽取正文

目标是得到一份确认可读、内容完整的论文正文，交给写手。

## 抽取

```sh
quasi extract text sources/SLUG.pdf processing/papers/SLUG/source.txt --json
```

源文件是 `.txt` 时，把输入换成 `sources/SLUG.txt`；CLI 会把它规范成严格 UTF-8 并统一换行。

然后**实际读一读**这份正文的开头、中间和结尾。字符数只是线索，要判断的是：

- 正文是否连贯；
- 有没有大面积乱码；
- 是不是只剩页眉页脚；
- 是不是完整的学术正文，而不是摘要、目录、期刊元数据或只有第一段的截断文本。

可读、完整，就用 `processing/papers/SLUG/source.txt` 交给写手。

## 什么时候要 OCR

只有源文件是 PDF、文本层确实不可读（扫描件没有文本层，或者持续乱码）时，才做 OCR。目录切分不理想、偶尔有错字，都不是 OCR 的理由。`.txt` 源文件永远不进 OCR：它不完整或不可读，说明下载的东西不对，回到下载那一步，或者告诉用户。

## 怎么做 OCR

OCR 分段推进，每次调用只处理一段（MinerU 每段 16 页）。

1. 运行 `quasi status --kind paper --slug SLUG --json`，从 `facts.ocr_generation` 里取出 `generation_key`、`source.sha256` 和 `profile.name`。
2. 推进一段：

   ```sh
   quasi extract ocr-generation --kind paper --slug SLUG --source-file sources/SLUG.pdf \
     --expected-source-sha256 SHA256 --generation-key KEY --profile mineru-text --json
   ```

3. 看返回结果：
   - `disposition` 是 `partial`（`state:"in_progress"`）：这一段做完了，回到第 1 步，再推进下一段；
   - `created` 或 `reconciled`（`state:"committed"`）：全部完成，正文在 `processing/papers/SLUG/ocr-generations/KEY/ocr.txt`；
   - `blocked` 或 `failed`：停下来，把 CLI 报的原因告诉用户，不要换引擎，不要换 generation key，也不要自己清理。

每段可能要跑几分钟。会超过宿主命令时限的话，按 `connectors/rex.md` 另开一个会话跑这条命令，再等它结束。

OCR 完成后，同样实际读一读开头、中间和结尾。仍然不可读就停下来告诉用户，不要再 OCR 一遍。MinerU 的 manifest 会记录新旧文本层不一致的段落；这只是提示哪里可能有问题，不能证明识别没有编造。

不要碰 `processing/papers/SLUG/ocr.pdf` 和 `ocr.txt` 这类旧版本留下的文件，也不要在 OCR 过程中启动第二条 OCR 命令。

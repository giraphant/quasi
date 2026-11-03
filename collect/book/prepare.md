# 切章

目标是得到一份可靠的章节清单（`processing/chapters/SLUG/manifest.json`），清单里的每一章都有一个可读的正文文件，顺序与书的阅读顺序一致。

清单只收要写章节笔记的部分。单独成节的参考文献、索引和尾注不进清单：章节写手只读本章正文，用不上它们，给它们写笔记也没有阅读价值。夹在章末的注释是那一章正文的一部分，不用拆出来。

## 已经有清单时

先核对，不要直接复用。读 `manifest.json`，再抽几章读一读开头、结尾和正文。出现下面任何一种情况，都要重新切章：

- 章节标题是文件名或内部资源编号（比如 `Publisher_9780…_epub_c01_r1`），而不是读得懂的标题；
- 混进了非阅读材料：封面、书名页、版权页、目录页、宣传页、作者介绍、"同一作者的其他作品"、插图清单，以及单独成节的参考文献、索引、尾注；
- 顺序乱了：前言、导言排到了正文章节后面，或者注释的顺序和正文对不上。

## EPUB

```sh
quasi extract epub sources/SLUG.epub processing/chapters/SLUG --json
```

然后读 `manifest.json`，以及每章的开头、结尾和一段正文。

确认某一项是非阅读材料时，带上排除项重新跑：每个要排除的标题写一个 `--exclude-title "清单里的原样标题"`，再加 `--expected-manifest-fingerprint 刚读过的清单指纹`。清单的 `skipped` 里如果已经有之前排除的标题，一并带上。

注意：

- 是否排除，要根据实际正文判断，不能看关键词猜。
- 不要手改 manifest，也不要删章节文件。

## PDF

先抽出文本层看看能不能读：

```sh
quasi extract text sources/SLUG.pdf processing/chapters/SLUG/source.txt --json
```

读开头、中间和结尾。正文连贯就可以切章：

```sh
quasi extract split sources/SLUG.pdf -o processing/chapters/SLUG --method auto --json
```

`auto` 先按 PDF 自带的目录切，不行再按标题模式切。切出来的结果里有单独成节的参考文献、索引或尾注时，照着这次的结果写一份切分方案，去掉这几项后重新切。切出来不理想时，读目录页和页码，自己写一份切分方案：`[{"title":"…","start":起始页,"end":结束页}, …]`。页码指 PDF 的物理页序号，不是书上印的页码。把方案存进 `.quasi/temp/` 下的一个文件，用 `--chapters-file` 传进去。

切完之后检查：有没有两章并成一章、有没有截断、有没有碎片、目录页有没有混进去、有没有乱码、页眉页脚有没有污染正文、顺序对不对。章节数量和大小只是线索，要以读到的内容为准。

- 只有个别章的边界不对：用 `--pages "起-止" --slot 槽位 --title 标题 --expected-manifest-fingerprint 清单指纹` 单独修那一章。
- 整体方案就不对：重新切。
- 有两到四种切法都同样说得通：把每种切法的章节列表给用户，请他选。

## 扫描版 PDF：先 OCR

文本层确实不可读（扫描件没有文本层，或者持续乱码）时，先 OCR，再切章。没有目录、边界不理想，都不是 OCR 的理由。

做法和论文一样，只是 `--kind book`：

1. 从 `quasi status --kind book --slug SLUG --json` 的 `facts.ocr_generation` 里取出 `generation_key`、`source.sha256` 和 `profile.name`。
2. 推进一段（每段 16 页）：

   ```sh
   quasi extract ocr-generation --kind book --slug SLUG --source-file sources/SLUG.pdf \
     --expected-source-sha256 SHA256 --generation-key KEY --profile mineru-text --json
   ```

3. 返回 `partial` 就再推进下一段；返回 `created` 或 `reconciled` 就是全部完成；返回 `blocked` 或 `failed` 就停下来，把原因告诉用户，不要换引擎，也不要自己清理。

一本书要推进很多段，每段几分钟。可以按 `connectors/rex.md` 开一个 pane，用 shell 循环反复执行同一条命令，直到结果不再是 `partial`；遇到 `blocked` 或 `failed` 就停。

完成后，用 `facts.ocr_generation.paths.pdf` 指向的 OCR 结果 PDF 来切章，不要再用原 PDF。

不要碰 `processing/chapters/SLUG/ocr.pdf`、`ocr.txt`、`ocr.progress.json` 这类旧版本留下的文件。

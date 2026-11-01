# 收录一篇论文

如果你是被直接派到这里的，先读本技能根目录的 `SKILL.md` 和 `collect/README.md`。

下文的 `quasi` 指 `scripts/quasi` 的绝对路径，`本目录` 指 `collect/paper/`。

## 流程

1. **确定身份。** 按 `本目录/search.md` 弄清题名、作者、年份、期刊、DOI，定下 slug。如果查明它其实是普通网页文章，或者只是某本文集里的一章，就停下来告诉用户，并建议改按对应的材料类型收录。

2. **查重。** 用 `quasi helpers vault resolve --items-file -`，通过 stdin 传入 `[{"kind":"paper","slug":…,"doi":…,"title":…,"authors":[…]}]`。返回了 `vault_slug`，说明这篇论文已经收过，以后都用这个 slug，跳到第 7 步对已有页面做 audit：通过就结束，不再重新抽取或写作。

3. **观察现状。** `quasi status --kind paper --slug SLUG --json`。重点看 `facts.sources`（PDF、TXT 源文件在不在）、`facts.prepared`（正文抽出来没有）和 `facts.ocr_generation`。

4. **源文件。**
   - `sources/SLUG.pdf` 和 `sources/SLUG.txt` 都不存在：按 `本目录/acquire.md` 下载。
   - 存在其中一个：核对它确实是这篇论文（题名、作者、DOI），对得上就用。
   - 两个都存在：问用户用哪个，不要自己删。

5. **正文。** 按 `本目录/prepare.md` 得到一份确认可读的完整正文。

6. **写作。** 按 `connectors/rex.md` 派一个写手，消息照下面这样写：

   ```text
   请读写作说明：本目录/writing.md 的绝对路径
   然后通读这篇论文的全文：正文文件的绝对路径
   书目信息：题名、作者、年份、期刊、卷期页码、DOI
   按写作说明写出论文笔记，把笔记全文作为你的最终回复：从 frontmatter 的第一行 --- 开始，到最后一节结束，前后不要加任何别的文字。只读取上面列出的文件。
   ```

   检查回复无误后，存为 `vault/papers/SLUG.md`。

7. **验收。** `quasi audit --path vault/papers/SLUG.md`，按 `collect/README.md` 的规则处理剩下的诊断。需要返修时，开一个新写手，消息在上面的基础上再加两样：现有页面的路径和 audit 诊断原文，并要求它保留页面中用户自己写的内容。

8. **报告。** 告诉用户页面路径，并说明遗留问题（比如缺页、OCR 存疑）。

## 续跑

中断之后，从第 3 步重新观察：已经存在、核对过的东西不重做。已有页面但没通过 audit 的，从第 7 步接着做。

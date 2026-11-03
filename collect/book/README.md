# 收录一本书

如果你是被直接派到这里的，先读本技能根目录的 `SKILL.md` 和 `collect/README.md`。

下文的 `quasi` 指 `scripts/quasi` 的绝对路径，`本目录` 指 `collect/book/`。

## 流程

1. **确定身份。** 按 `本目录/search.md` 弄清书名（含副标题）、作者或编者、出版年、出版社、ISBN 和类别，定下 slug。用户只想要书中某一章时，先问他是收整本书，还是另想办法。

2. **查重。** 把 `[{"kind":"book","slug":…,"isbn":…,"title":…,"authors":[…]}]` 写进 `.quasi/temp/` 下的一个文件，再运行 `quasi helpers vault resolve --items-file 该文件`。返回了 `vault_slug`，说明这本书已经收过（可能只做了一部分），以后都用这个 slug，接着做第 3 步。

3. **观察现状。** `quasi status --kind book --slug SLUG --json`。重点看：
   - `facts.sources`：EPUB、PDF 在不在；
   - `facts.manifest`：切章清单在不在；
   - `facts.chapters`：每一章的正文（`input`）和章节页（`output`）在不在；
   - `facts.overview`：全书概览在不在；
   - `facts.ocr_generation`：OCR 进度。

   如果所有章节页和概览都在，直接跳到第 8 步，对整本书做 audit。

4. **源文件。**
   - EPUB 和 PDF 都没有：按 `本目录/acquire.md` 下载。
   - 已经有了：打开书名页和版权页，核对书名、作者、版次、年份，确实是这本书就用。
   - 两种都有：这是正常的，分析用 EPUB（文字更干净），PDF 留给以后做译本。

5. **切章。** 按 `本目录/prepare.md` 得到一份可靠的章节清单。

6. **章节写作。** 重新跑一次 `quasi status`，对 `facts.chapters` 里每个章节页不存在的章，各派一个写手（见 `connectors/rex.md`）。可以并行，同时最多开 5 个，做完一批再开下一批。每个写手的消息照下面这样写：

   ```text
   请读写作说明：本目录/chapter.md 的绝对路径
   然后通读这一章的全文：这一章 input 的绝对路径
   全书目录（按顺序）：各章标题，每行一个
   书目信息：书名、作者或编者、出版年、出版社、类别；书的 slug：SLUG
   本章标题：这一章在清单里的 title
   按写作说明写出章节笔记。只读取上面列出的文件。
   ```

   单著时，在书目信息后面加一句"本章作者：除非正文另有署名，否则与全书作者相同"；文集则写"本章作者：请按正文署名确定"。

   每份回复文件检查无误后，存到这一章 `output` 给出的路径，再对这一页跑 `quasi audit --path`，按 `collect/README.md` 的规则处理。

7. **全书概览。** 所有章节页都通过 audit 以后，派一个写手：

   ```text
   请读写作说明：本目录/overview.md 的绝对路径
   书目信息：书名、作者或编者、出版年、出版社、ISBN、类别
   请按顺序读完这些章节笔记：各章节页的绝对路径，每行一个
   按写作说明写出全书概览。只读取上面列出的文件。
   ```

   检查回复文件无误后，存为 `vault/books/SLUG/00-overview.md`。

8. **验收。** `quasi audit --path vault/books/SLUG`，一次检查整本书，按 `collect/README.md` 的规则处理剩下的诊断。

9. **报告。** 告诉用户概览页路径、一共几章，并说明遗留问题（比如某章 OCR 存疑、切章边界不理想）。

## 续跑

中断之后，从第 3 步重新观察。已经存在并通过 audit 的章节页不重写；只补缺的章，再写或重写概览。

# 做一份译本

如果你是被直接派到这里的，先读本技能根目录的 `SKILL.md` 和 `collect/README.md`。

把文库里一篇论文或一本书的 PDF 翻成双页对照的译本（原文页和译文页交替，带书签）。目标语言用户没说就是中文（`zh`）。下文的 `quasi` 指 `scripts/quasi` 的绝对路径，`S` 是这件材料在文库里的 slug，`L` 是目标语言。

这里没有写手：翻译由配置好的后端完成，你负责观察、准备和验收。

## 流程

1. **确认源文件。** 材料要先收进文库，`sources/S.pdf` 要在。书只有 EPUB 的，先按 `collect/book/acquire.md` 取得 PDF 版，EPUB 不能直接翻译。

2. **观察现状。** `quasi status --kind translation --slug S --target-language L --json`。`facts.target_language` 是规范化后的语言标签，后面都用它。`facts.output` 已经存在且可用，就是做好了，直接报告。

3. **检查能不能开跑。**

   ```sh
   quasi translate observe S --target-language L --mode initial --json
   ```

   看返回的 `signal`：

   - `reused`：已有合格的译本，报告即可。
   - `running`：另一个翻译还在跑，等它结束（隔一阵用 `--mode final` 再看），不要再开一个。
   - `configuration_required`：后端配置不全。把缺的配置项告诉用户，停下。
   - `source_selection`：有多个候选源文件。把候选列给用户选，选定后用 `--source-file` 指定再观察。
   - `missing`：可以开跑，到第 5 步。
   - 返回失败、代码是 `translation.layout_required`：这是扫描本，先做第 4 步。

4. **扫描本先重建版面。** 扫描本直接翻译会丢版面，要先用 MinerU 识别、把文字按段落放回页面：

   ```sh
   quasi extract ocr sources/S.pdf processing/translations/S-L-reocr.pdf --layout \
     --recognition-json processing/translations/S-L-recognition.json --no-clobber --json
   ```

   一本书要跑很久，按 `connectors/rex.md` 开一个 pane 跑，等它结束。成功后，用 `--source-file processing/translations/S-L-reocr.pdf --mode recovery` 再观察一次，然后进第 5 步，源文件换成这个重建版。

   排版失败时，识别结果已经存在 `S-L-recognition.json` 里，再跑同一条命令会直接重排，不用重新识别。个别页的错误，可以对照原 PDF 那一页，把修正写进 `processing/translations/S-L-layout-review.json`：`{"source_sha256":"识别结果里的来源 SHA","pages":[{"page":页码,"reason":"依据","blocks":[…修正后的整页块列表…]}]}`，再加 `--review-json` 重排。只改看得清的字，看不清的不要猜。不要删掉整页正文来让检查通过。

5. **开跑。** 先告诉用户页数和后端，再开始。用观察结果里的源文件和它的 SHA-256：

   ```sh
   quasi translate run S --source-file 源文件 --target-language L --attempt 1 \
     --expected-source-sha256 SHA256 --json
   ```

   整本书要跑一小时以上也正常，按 `connectors/rex.md` 开一个 pane 跑，等它结束。日志一时没有更新，不代表失败；结果不明时先用 `--mode final` 观察，不要再开第二个。

   如果返回 `translation.selection_prepare_failed`，先读具体原因。这一步在翻译后端启动前检查原文划选所需的识别与位置。个别段落无法对齐时会保留原段落排版并报告，不必因此重跑整本；来源不匹配、模型不可用或文字丢失则需要先处理。较早的 `S-L-reocr.pdf` 可能没有保存对应的 `S-L-recognition.json`。如果原因明确是识别文件缺失或不能证明与重建版匹配，用下面的另一组固定路径从原文件重新识别，保留原重建版和原识别文件，再用新的源文件和它的 SHA-256 观察、运行：

   ```sh
   quasi extract ocr sources/S.pdf processing/translations/S-L-selection-reocr.pdf --layout \
     --recognition-json processing/translations/S-L-selection-recognition.json --no-clobber --json
   ```

   这组文件已经存在但不匹配、位置检查失败或原因不明时，保留现有文件并报告诊断，不要删除旧成果或反复重跑付费翻译。

6. **验收。** 读运行结果里的验证部分：页数应当是原文的两倍（双页交替），manifest 和哈希对得上，文字层能复制搜索，中文译本的覆盖率检查通过。外观正常但正文大片没翻的，不算完成。再运行第 2 步的 status；`facts.selection` 中列出的回退段落或跳过页保留了原来的排版，报告给用户，不把它们说成已经精确对齐。旧译本没有这项记录时，也不要推断全部对齐。

   覆盖率不过关时，先看它统计了哪些页、最差的是哪几页：书目、索引、独立的注释区会被排除，正文和注释混排的页也可能拉低数值。确认是正文漏译，才用 `--attempt 2` 重跑一次。

7. **报告。** 告诉用户译本路径 `processing/translations/S-L.pdf`、页数和覆盖率；有排除的区段或可疑的页，一并说明。

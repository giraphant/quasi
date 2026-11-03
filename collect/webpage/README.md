# 收录一个网页

如果你是被直接派到这里的，先读本技能根目录的 `SKILL.md` 和 `collect/README.md`。

用户想读、想留下的是这个网页本身时，按这里处理：博客文章、新闻报道、评论、访谈稿。链接其实指向一篇论文或一本书时，改按论文或书收录；要当作原件存档（帖子、档案、需要保存附件和截图），改按档案收录。

下文的 `quasi` 指 `scripts/quasi` 的绝对路径，`本目录` 指 `collect/webpage/`。

## 流程

1. **识别。** `quasi webpage inspect --url URL --json`。它返回跳转之后的最终地址 `final_url`、标题和站点。之后一律用 `final_url`，不要换成别的地址。

2. **定 slug、查重。** 按标题拟一个简短的英文 kebab slug，然后把 `[{"kind":"webpage","slug":…,"url":final_url,"title":…,"site":…}]` 写进 `.quasi/temp/` 下的一个文件，再运行 `quasi helpers vault resolve --items-file 该文件`。已有同一地址的页面，就用它的 slug；没有，就用返回的建议 slug。

3. **观察现状。** `quasi status --kind webpage --slug SLUG --json`。看 `facts.snapshot`（网页快照）、`facts.prepared`（抽出的正文）、`facts.canonical`（阅读页）和 `facts.captured_at`。

4. **快照。** 快照不存在时：

   ```sh
   quasi webpage capture --url URL --expected-final-url FINAL_URL --output vault/webpages/SLUG/snapshot.webarchive --json
   ```

   最终地址变了、或者抓取失败，就停下来告诉用户，不要换地址重试。

5. **抽取正文。** 正文不存在时：

   ```sh
   quasi webpage extract --snapshot vault/webpages/SLUG/snapshot.webarchive --output processing/webpages/SLUG/source.md --json
   ```

   只有这一轮刚重新抓了快照、而旧正文还在时，才加 `--replace-existing`。

   然后实际读一读 `source.md`：它应当是有实质内容的正文，而不是登录页、付费墙、Cookie 提示或只剩导航的空壳。是空壳就停下来告诉用户。

6. **写摘要。** 阅读页由两部分组成：写手写的 frontmatter、标题和摘要，以及原样保留的正文。按 `connectors/rex.md` 派一个写手：

   ```text
   请读写作说明：本目录/writing.md 的绝对路径
   然后通读这个网页的正文：processing/webpages/SLUG/source.md 的绝对路径
   网页信息：标题、最终地址、站点、抓取时间（captured_at）
   按写作说明写出网页笔记的开头部分。只读取上面列出的文件。
   ```

7. **拼成阅读页。** 回复文件检查无误后，在它末尾接上一节 `## Content`，下面放 `source.md` 的全文，一字不改，只把其中的标题整体降级，让最高一级变成三级标题（只改行首的 `#`）。存为 `vault/webpages/SLUG/webpage.md`。

8. **验收。** `quasi audit --path vault/webpages/SLUG/webpage.md`，按 `collect/README.md` 的规则处理。

9. **报告。** 告诉用户页面路径。

## 续跑

中断之后，从第 3 步重新观察。快照和正文已经在、而且读过确认可用的，不再重抓。

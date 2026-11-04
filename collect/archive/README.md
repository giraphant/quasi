# 收录一件档案

如果你是被直接派到这里的，先读本技能根目录的 `SKILL.md` 和 `collect/README.md`。

用户明确要把一件东西当作原件存下来时，按这里处理：论坛帖子、社交媒体讨论串、专利、维修手册、报纸版面、图片、视频。重点是保存原件和出处，而不是写阅读笔记。只想读一篇网页文章的，改按网页收录。

下文的 `quasi` 指 `scripts/quasi` 的绝对路径，`本目录` 指 `collect/archive/`。

## 流程

1. **识别。** 检查用户给的地址：

   ```sh
   quasi archive inspect --url URL --output-dir .quasi/temp/archive-简称-随机后缀
   ```

   输出是 JSON。读完后另外把它写进 `.quasi/temp/` 下的一个文件（不要用重定向），后面要交给写手。它给出页面标题、元数据里的日期线索（`metadata_evidence`）和页面上的链接；地址是 PDF 时，还会给出前几页的预览图和文字层。

   根据材料对象本身定 `kind`：`patent`、`thread`、`post`、`video`、`image`、`webpage`、`document` 之一。看的是这是什么东西，不是它用什么格式保存：帖子的截图仍是 `post`，扫描的维修手册是 `document`。

   PDF 要核对身份时，读返回的预览图（封面、题页、版权页）；需要别的页，就用 `--path` 指向返回的 `cached_pdf`，再加 `--pages` 选页，不要重新下载。PDF 的元数据、文件名只是线索，创建和修改时间不是出版日期。

2. **定 slug、查重。** 拟一个英文 kebab slug，把 `[{"kind":"archive","slug":…,"url":URL}]` 写进 `.quasi/temp/` 下的一个文件，再运行 `quasi helpers vault resolve --items-file 该文件`。已有同一地址的档案，就沿用它的 slug、标题和 kind。

3. **观察现状。** `quasi status --kind archive --slug SLUG --json`。记下 `facts.collection.revision`，发布时要用。已有的档案可能放在某个合集目录里，一律用 status 给出的路径。

4. **挑原件。** inspect 列出的链接只是候选。只挑属于这件材料本身的东西：正文页、附件、组图、视频音频。不要顺着链接往外爬，也不要把别的材料混进来。

   - 网页用 `webarchive` 方式保存，文件名以 `.webarchive` 结尾；
   - PDF、图片、视频、音频用 `download` 方式下载，保留原来的扩展名；
   - 文件名用简短、有指向的 kebab 写法，组图可以编号，比如 `001-screen-discoloration.jpg`；
   - 每件原件写一个 `title`（优先用原标题）和一句 `description`（是什么、讲什么）。没看过的视频音频，只按来源说明它的用途，不要编内容。

   登录才能看、或者暂不支持的流媒体，记下出处，说明没有取得即可。

5. **核实元数据。** `creator`（作者或发布者，数组）、`date`（原材料的完整发布日期 `YYYY-MM-DD`）、`source`（平台或发布机构），只写核实过的，不知道的省略。日期要分清发布日期和更新日期，看页面上可见的日期和 `metadata_evidence`；只有更新日期、部分日期或找不到日期时，不填 `date`，交给写手在正文里说明。抓取日期、版权年份、评论日期都不是发布日期。

6. **写说明。** 按 `connectors/rex.md` 派一个写手：

   ```text
   请读写作说明：本目录/writing.md 的绝对路径
   然后读这件材料的检查结果：inspect 输出文件的绝对路径
   以及这些预览图：各张预览图的绝对路径（没有就不写这一行）
   材料信息：标题、kind、地址、核实过的 creator/date/source；要保存的原件清单（文件名、标题、说明）；没取得的部分
   按写作说明写出档案正文。只读取上面列出的文件。
   ```

7. **发布。** 在 `.quasi/temp/` 下写一个独有名字的请求文件：

   ```json
   {
     "identity": {"slug": "…", "title": "…", "kind": "…", "url": "…"},
     "topics": [],
     "expected_revision": "第 3 步记下的 revision",
     "files": [{"name": "…", "url": "…", "method": "download", "title": "…", "description": "…"}],
     "metadata": {"creator": ["…"], "date": "YYYY-MM-DD", "source": "…"},
     "body": "写手回复文件的全文",
     "coverage": "一句话说明保存范围和缺失；没有可写空字符串"
   }
   ```

   `topics` 写用户指定的 Topic slug，没有就是空数组；`metadata` 里不知道的字段整个省略。然后：

   ```sh
   quasi archive collect --request-file .quasi/temp/请求文件
   ```

   CLI 负责下载原件、写 `manifest.yaml` 和 `archive.md`，并在页尾陈列原件。下载失败的原件记进 coverage，不算整件失败。报告锁被占用、版本已变或结果不明时，停下来重新观察，不要自己重试。

8. **验收。** 对 status 给出的 `archive.md` 路径跑 `quasi audit --path`，按 `collect/README.md` 的规则处理。

9. **报告。** 告诉用户档案路径、保存了几件原件、哪些没取得。

## 续跑

中断之后，从第 3 步重新观察。已经发布的档案不重复采集；用户要补原件时，照第 4–7 步再发布一次，CLI 会保留原有正文和元数据。

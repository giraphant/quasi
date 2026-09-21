# quasi-vault Schema Specification

```
Version : 0.9.0
Status  : active — synchronized with scripts/schemas/ executable contracts
Last    : 2026-09-21
```

## 0. 文档定位

这份 SPEC **是**:
- vault 中「被打 type 的实体文档」的人读契约
- 所有 LLM 生成代理在生成新文档时应当遵循的约定
- `scripts/typecheck/typecheck.py` 与 `scripts/typecheck/autofix_mechanical.py` 的规范说明

这份 SPEC **不是**:
- executable schema 本身；结构权威位于 `scripts/schemas/*.py`，registry 权威位于 `scripts/schemas/registry.py`
- 迁移计划或 vault 当前实际状态报告
- 对默认 audit 自动修改 vault 的授权

SPEC 与 executable schema 不一致时必须先停止数据迁移、核对并同步契约；不得以过期文档覆盖当前 schema。

## 1. 类型系统总览

vault 中的被打 `type` 文档使用 12 个 canonical type。短名是唯一合法 schema；旧的长名（`paper-analysis` / `book-overview` / `chapter-summary` / `author-profile` 等）只作为 deprecated diagnostics 或 migration input，不再是合法 type。类型集合与顺序由 `TYPE_REGISTRY` 派生，不另维护隐藏列表。

| `type`    | 文档                  | 主要路径                                 | 历史快照数量（非契约） |
| --------- | --------------------- | ---------------------------------------- | -------- |
| `author`  | 学者档案              | `vault/authors/<slug>.md`                | 312 |
| `book`    | 一本书的整体分析      | `vault/books/<slug>/00-overview.md`      | 1067 |
| `chapter` | 书的一个章节分析      | `vault/books/<slug>/chXX-*.md`           | 11956 |
| `paper`   | 期刊论文分析          | `vault/papers/*.md`                      | 2244 |
| `journal` | 期刊 overview/resources 页面 | `vault/journals/<slug>/{00-overview,01-resources}.md` | 11 |
| `topic`   | 主题 overview/resources 页面 | `vault/topics/<slug>/{00-overview,01-resources}.md` | 12 |
| `note`    | 自由笔记或批注        | `vault/notes/*.md`                       | 18 |
| `archive` | 单件档案材料 metadata | `vault/archives/<slug>/archive.md` | — |
| `image`   | 本地图片对象 metadata | `vault/images/<slug>/image.md`           | 8 |
| `talk`    | 会议/讲座录制的摘要   | `vault/talks/<slug>/talk.md`             | 0 |
| `transcript` | 讲座的带时间戳转写 | `vault/talks/<slug>/transcript.md`       | 0 |
| `webpage` | 已捕获网页的语义分析页 | `vault/webpages/<slug>/webpage.md`       | — |

### 不在 type 体系内

下列文档仍作为自由格式存在,reader 可展示但不参与 schema 校验:

- `vault/.obsidian/` / `.makemd/` 等编辑器配置
- 未带 frontmatter 或未带 `type` 的临时草稿

## 2. 共享原语 (`primitives.py`)

定义在 `$CLAUDE_PLUGIN_ROOT/scripts/schemas/primitives.py`。**这不是继承基类** —— 是值层面的 Pydantic 验证器原语,被各 type schema 按需复用。每个 type schema 结构独立。

> **实现说明**:本 SPEC 的 schema 代码示例使用 Zod 风格记号(写起来短),
> 实际实现是 Pydantic V2 类。形状一一对应,语法不同。真代码见 `schemas/*.py`。

### `Rating`

```ts
// Canonical(Phase 2 起):
export const Rating = z.number().int().min(1).max(5);

// 迁移期(Phase 1):允许 ★ 字符串自动 transform 为 number
export const RatingLenient = z.union([
  z.number().int().min(1).max(5),
  z.enum(['★','★★','★★★','★★★★','★★★★★']).transform(s => s.length),
]);
```

**Canonical form**:integer 1..5。
存储用数字,**渲染层**(reader)显示为 ★ 字符串。
迁移 autofix 影响:~1200+ 条带 ★ 字符串 → number;~270 条已经是数字 → 保持。
"★★★/5" 等异常字符串 → 取 ★ count 部分。

### `Year`

```ts
export const Year = z.union([
  z.number().int().min(1500).max(2030),
  z.null(),
]);
```

**Canonical form**:integer 或 null。迁移期 autofix:
- 合法 4 位数字字符串(如 `"2010"`)→ number
- `"n.d."` / `"未知"` / 空字符串 → null
- 离群值(如 chapter 里 `range -1..2004` 的异常)→ null + 人工 review

### `Themes`

```ts
export const Themes = z.array(z.string().min(2));
```

**Canonical form**:字符串数组,**hyphen-joined**(`affect-theory` 优于 `affect theory`,后者 lint warn)。
- 空数组 allowed,lint warn`"0 themes 可能漏写"`
- 单字符串值(如 `themes: "STS"`)→ 视为漂移,autofix 包成 `["STS"]`

### `Authors`

**强制数组**(plural,即使单作者也是 1 元素数组)。

```ts
export const Authors = z.array(z.string().min(2)).min(1);
```

理由:消费端代码永远 `.map`,不用分支 `typeof author === 'string' ? ... : author.map(...)`。
单作者也用数组 `["Sara Ahmed"]`,代价 4 个字符。
迁移期 autofix 将所有单字符串包成单元素数组。

### `Title`

```ts
export const Title = z.string().min(2).max(280);
```

可包含中英文、引号、冒号副标题。**280 上限**因为有些书名+副标题很长。

## 3. Type Schemas

每个 type 给出：**简写形状 + frontmatter 示例 + 历史迁移说明**。

以下代码块沿用简洁的 Zod 风格伪代码帮助阅读；实际约束已经由 `scripts/schemas/*.py` 中的 Pydantic V2 model 实现，二者冲突时以 executable schema 为准并同步修正文档。

---

### 3.1 `author`

学者档案。一个作者一份。

```ts
export const AuthorSchema = z.object({
  type:    z.literal('author'),
  name:    Name,                    // 作者全名,作为该 entity 的展示名
  themes:  Themes,                  // 研究方向标签
  topics:  z.array(z.string()).optional(),  // 所属 topic 语料的 slug 数组(可选,默认 [])
  rating:  Rating.optional(),       // 整体学术评分(可选,数字 1..5)
});
// executable schema 使用 ConfigDict(extra="forbid", strict=True)
// wikilink 形式 [[slug|Sara Ahmed]] 由 reader 从文件路径派生,不在 frontmatter
```

**示例 frontmatter**:

```yaml
---
type: author
name: Sara Ahmed
themes:
  - affect-theory
  - queer-phenomenology
  - feminist-theory
  - racism
  - killjoy
rating: 5
---
```

**与现状差异**(229 条):
- `type: author-profile` → `type: author`
- **`title` → `name`**(author 是"人",用 name 更对路;跨 type 统一用 `entry.displayName` accessor)
- **删除字段**:`author`(与 name 冗余;wikilink 由路径派生)、`year`(8% 非空)、`source`(7% 非空)、`has-profile`(3% 非空)
- **新增字段**:`topics`(可选,默认 `[]`)——所属 topic 语料的 slug 数组,格式同 `themes`。供前端阅读器按「`topics` 包含 `<slug>`」反查 topic 成员;与 topic 页的 `[[wikilink]]` 互补(双向可达)。
- **格式收紧**:rating ★ 字符串 → number(~10 条);themes 单字符串 → 数组(~5 条)

---

### 3.2 `book`

一本书的整体分析(通常是 `00-overview.md`)。与 BibTeX `@book` / `@collection` 对齐,
未来可一键导出引文。

```ts
export const BookSchema = z.object({
  type:      z.literal('book'),

  // BibTeX 核心(必填)
  title:     Title,
  authors:   Authors,                             // 合并 authors+editors;角色由 category 决定;永远数组
  year:      Year,
  publisher: z.string().min(2),                   // Phase 1 lint warn,Phase 2 严格必填

  // 唯一识别码 + 书籍类别
  isbn:      z.string().optional(),               // schema 不强制格式,lint 检查
  doi:       z.string().optional(),               // 可选书籍 DOI
  category:  z.enum(['monograph', 'edited-volume', 'handbook', 'other'])
             .default('monograph').optional(),    // 决定 BibTeX export 用 author 还是 editor

  // 学术分析字段
  themes:    Themes.optional(),
  topics:    z.array(z.string()).optional(),       // 所属 topic 语料的 slug 数组(可选,默认 [])
  rating:    Rating.optional(),                   // number 1..5
});
// chapters_analyzed 不存在 schema —— reader 从子章节 count 派生
// edition / note 删除 —— rare,有需要时用 markdown 正文表达
```

**示例 — 专著(monograph,默认)**:

```yaml
---
type: book
title: "Nightwork: Sexuality, Pleasure, and Corporate Masculinity in a Tokyo Hostess Club"
authors:
  - Anne Allison
year: 1994
publisher: "University of Chicago Press"
isbn: "978-0226014876"
category: monograph
themes:
  - japan-studies
  - gender
  - corporate-masculinity
  - ethnography
rating: 4
---
```

**示例 — 文集(edited-volume)**:

```yaml
---
type: book
title: "The Affect Theory Reader"
authors:
  - Melissa Gregg
  - Gregory J. Seigworth
year: 2010
publisher: "Duke University Press"
isbn: "978-0822347767"
category: edited-volume
themes:
  - affect-theory
rating: 5
---
```

**与现状差异**(779 条，44 字段 → 11 字段):
- `type: book-overview` → `type: book`
- **保留并 canonical 化**：`title` / `authors` / `year` / `themes` / `rating` / `publisher`
- **新增字段**：`isbn`、`doi`、`category`（默认 monograph）
- **删除字段**(原有但不再保留):
  - `chapters_analyzed`(83% 在用)—— reader 从子章节 count 派生
  - `edition`(1 条)—— rare,需要时写 note
  - `source`(70 条)—— 与 title 信息重叠
- **新增字段**:`topics`(可选,默认 `[]`)——所属 topic 语料的 slug 数组,格式同 `themes`。供前端阅读器按「`topics` 包含 `<slug>`」反查 topic 成员;与 topic 页的 `[[wikilink]]` 互补(双向可达)。
- **同义字段合并**(autofix):
  - `book_title` / `book_author` / `book_year` → `title` / `authors` / `year`
  - 旧单值 `author` → `authors` 数组
  - `editors` → `authors` + `category: edited-volume`
  - `tags` → `themes`
  - 9 个 `chapters_*` 变体 → 全删(派生)
- **publisher 大量补全**:当前仅 6% 填,fix-agent 调 WorldCat / OpenAlex 批量补
- **删除孤儿字段**:`has-overview` / `analyzed` / `confidence` / `selective_reading` / `selection_note` / `scope_note` / `source_file` / `source_note` / `source_type` / `slug` / `status` / `structure` / `version` / `supersedes` / `overall_rating` / `avg_relevance` / `chapters_missing` / `relevance` / `date` / `concepts` / `book` —— 20+ 个 <1% 字段

---

### 3.3 `chapter`

一本书的一个章节分析。文件位置必须在 `vault/books/<slug>/chXX-*.md`。

```ts
export const ChapterSchema = z.object({
  type:    z.literal('chapter'),
  title:   Title,                              // 章节标题(含"第N章 XXX"前缀)
  authors: Authors,                            // 章作者(永远数组;编著作里可与 book.authors 不同)
  year:    Year,                               // 通常等于父书 year
  book:    z.string().min(2),                  // 父书 slug,如 "allison-nightwork-1994"
  themes:  Themes.optional(),                  // 章节级主题(31% 非空,可空)
  topics:  z.array(z.string()).optional(),     // 所属 topic 语料的 slug 数组(可选,默认 [])
  rating:  Rating.optional(),                  // number 1..5
});
```

**示例**:

```yaml
---
type: chapter
title: "第1章 一种地方类型"
authors:
  - Anne Allison
year: 1994
book: "allison-nightwork-1994"
themes:
  - hostess-club
  - communitas
  - space
rating: 1
---
```

**与现状差异**(8093 条,22 字段 → 8 字段):
- `type: chapter-summary` → `type: chapter`
- **`source` 重命名为 `book`,从书名字符串改为 slug**
  - 当前:`source: "Nightwork: Sexuality, Pleasure, ..."`
  - 迁移后:`book: "allison-nightwork-1994"`
  - 稳定,父书改 title 时章节不动;vault-wide lint 校验 slug 存在性
- **`author` → `authors`**,单字符串 → 单元素数组(去 `[编]` 前缀)
- **删除字段**:
  - `chapter`(68% 在用)—— 序号从 path / title 抽不稳定
  - `slot`(32% 在用)—— 字符串版章节序号,冗余
  - `relevance`(99% 填但有异常值)—— 数据 bug,语义不清
  - `book` / `book_title`(旧)—— 与新 `book` 字段(slug)冲突
  - `chapter_title` / `chapter_label` / `chapter-author` / `editors` / `publisher` / `pages` / `tags` / `topic` / `word_count_est` / `status` —— ~10 个孤儿字段(注:`topics` 已作为支持字段保留,见上方 schema)
- **`year` 必填**:当前 100% 填,直接收紧
- **`themes` 保持 optional**:章节级主题经常没有
- **新增字段**:`topics`(可选,默认 `[]`)——所属 topic 语料的 slug 数组,格式同 `themes`。供前端阅读器按「`topics` 包含 `<slug>`」反查 topic 成员;与 topic 页的 `[[wikilink]]` 互补(双向可达)。

---

### 3.4 `paper`

期刊论文分析。**paper 严格指期刊文章**;书的章节(包括论文集里的章节)归 `chapter` 类型,放在 `vault/books/<slug>/`。

**与 chapter 的关系**:7 个字段完全相同;容器引用分叉,`doi` 仅属于 paper。

| paper | chapter |
| --- | --- |
| `journal` (期刊名) | `book` (父书 slug) |
| `doi` (规则化格式,可选) | — |
| 其余 7 字段相同(`type` / `title` / `authors` / `year` / `themes` / `topics` / `rating`) | 同左 |

```ts
export const PaperSchema = z.object({
  type:    z.literal('paper'),
  title:   Title,
  authors: Authors,                             // 永远数组
  year:    Year,
  journal: z.string().min(2),                   // 必填 —— paper = 期刊论文
  doi:     z.string().regex(/^10\.\d+\//).optional(),
  themes:  Themes,                              // 必填(论文应有主题)
  topics:  z.array(z.string()).optional(),      // 所属 topic 语料的 slug 数组(可选,默认 [])
  rating:  Rating.optional(),                   // number 1..5
});
```

**示例**:

```yaml
---
type: paper
title: "Happy Objects"
authors:
  - Sara Ahmed
year: 2010
journal: "The Affect Theory Reader"
themes:
  - affect-theory
  - happiness
  - queer-theory
  - sticky-affect
  - feminist-killjoy
rating: 2
doi: "10.1215/9780822393047-001"
---
```

> ⚠️ Happy Objects 实际收录于一本论文集(Reader),不是期刊。若严格执行"paper = 期刊论文",这类文件应迁移到 `vault/books/affect-theory-reader/ch-happy-objects.md` 转为 chapter 类型。**autofix 在迁移阶段会做启发式分类**(看 source 像不像书),提议清单等用户 review。

**与现状差异**(1651 条，28 字段 → 9 字段):
- `type: paper-analysis` / `journal-article-analysis` / `article-analysis` / `paper-summary` → `type: paper`
- **`author` → `authors`**(单字符串 → 数组)
- **`source` → `journal`**(语义收紧:paper 只指期刊文章)
- **同义字段合并**:
  - `authors` (旧 array 字段) → `authors`(新字段,Authors 原语)
  - `tags` → `themes`
  - `date` → `year`(50 条;需人工挑出"分析日期"误用)
  - `score` → `rating`(数字)
  - `paper_title` → `title`
- **删除孤儿字段**(~14 个 <2%):`reviewed_book` / `reviewed_author` / `terminal` / `notes` / `note` / `status` / `volume` / `pages` / `citations` / `source_type` / `translators` / `round` / `concepts` / `relevance`(旧 `topic` 单数字段同样删除;复数 `topics` 作为支持字段保留,见上方 schema)
- **doi 校验**:1614 条有 doi,空字符串和格式错的 lint 报告
- **journal 大量补全**:当前只有 10% 显式 `journal` 字段;~140 条 `source: <书名>` 需要 review 决定迁去 chapter 还是改 journal
- **themes hyphen-joined**:`"affect theory"` → `"affect-theory"`

---

### 3.5 `journal`

期刊目录下的 overview/resources 页面。它不是 profile schema;扫描结果、阅读清单、候选论文等内容留在正文 H2 里。

```ts
export const JournalSchema = z.object({
  type:    z.literal('journal'),
  title:   Title,
  kind:    z.enum(['overview', 'resources']),
  journal: z.string().min(2),
}).strict();
```

**示例 — overview**:

```yaml
---
type: journal
title: British Journal of Sociology
kind: overview
journal: British Journal of Sociology
---
```

**示例 — resources**:

```yaml
---
type: journal
title: British Journal of Sociology
kind: resources
journal: British Journal of Sociology
---
```

**规则**:
- `kind` 只允许 `overview` / `resources`
- frontmatter 只允许 `type` / `title` / `kind` / `journal`
- `title` 必填 —— 供前端 / Marple 统一显示页面标题;期刊页 `title` 即期刊名,与 `journal` 字段重复是预期的(所有页面类型一律带 `title`)
- `journal-synthesis` 等旧 type 只作为 deprecated diagnostics,不参与正常 schema 识别

---

### 3.6 `topic`

主题目录下的 overview/resources 页面。研究问题、阅读清单、滚雪球结果和过程记录放在正文 H2 中,不拆成新的 frontmatter `kind`。

```ts
export const TopicSchema = z.object({
  type:  z.literal('topic'),
  title: Title,
  kind:  z.enum(['overview', 'resources']),
}).strict();
```

**示例 — overview**:

```yaml
---
type: topic
title: 密码学的社会建构
kind: overview
---
```

**示例 — resources**:

```yaml
---
type: topic
title: 密码学的社会建构
kind: resources
---
```

**规则**:
- `kind` 只允许 `overview` / `resources`
- topic 页 frontmatter 只允许 `type` / `title` / `kind`。`title` 必填(人读主题标题,
  与 H1 一致),供前端 / Marple 直接显示;文件夹 slug 仍是稳定身份键,不写 `topic` 字段;
  主题成员关系反向挂在实体的 `topics: [slug]` 上。
- `topic-synthesis` / `reading-list` / `research-note` 等旧 type 只作为 deprecated diagnostics,不参与正常 schema 识别

---

### 3.7 `note`

自由笔记或批注。批注用 `annotates` 指向被批注的 vault 文档;普通想法笔记可省略。

```ts
export const NoteSchema = z.object({
  type:      z.literal('note'),
  title:     Title,
  created:   z.coerce.date(),
  annotates: z.string().optional(),
  themes:    Themes.optional(),
}).strict();
```

**示例 — 批注**:

```yaml
---
type: note
title: 对《English and American Tool Builders》的批注
annotates: vault/books/roe-english-american-tool-builders-1916/00-overview.md
created: 2026-05-27
---
```

**示例 — 自由笔记**:

```yaml
---
type: note
title: Sociology of Gap
created: 2026-05-23
---
```

**规则**:
- frontmatter 只允许 `type` / `title` / `created` / `annotates` / `themes`
- `themes` 为空时整行省略,不要写 `themes: []`
- 正文自由格式,不校验 H2 schema

---

### 3.8 `image`

本地图片对象 metadata。图片文件本身不进 frontmatter,由路径约定 `vault/images/<slug>/image.md` 旁边的 `original.<ext>` 表示。

```ts
export const ImageSchema = z.object({
  type:    z.literal('image'),
  title:   Title,
  creator: z.array(Name).default([]),       // 创作者(摄影师/画家),可关联 vault/authors/
  date:    z.string().date().optional(),      // 创作/拍摄日期(整日 ISO)
  source:  z.string().max(500).optional(),   // 出处: URL 或自由文本
  themes:  z.array(z.string()).default([]),
  topics:  z.array(z.string()).default([]),
  rating:  Rating.optional(),
}).strict();
```

**示例**:

```yaml
---
type: image
title: Micrometer
creator:
  - Henry Maudslay
date: 2024-11-08
source: https://en.wikipedia.org/wiki/Micrometer_(device)
themes:
  - measurement
rating: 4
---
```

**规则**:
- frontmatter 只允许 `type` / `title` / `creator` / `date` / `source` / `themes` / `topics` / `rating`;除 `type` / `title` 外全部可选,空值省略整键
- 原图路径由目录约定派生,不写进 frontmatter
- 技术性字段(宽高/格式/文件大小)由阅读器索引时从 `original.<ext>` 现场派生,**绝不**写进 frontmatter(QUA-175)
- 描述(图片讲什么)写正文,不设 frontmatter 字段
- 正文自由格式,不校验 H2 schema

---

### 3.9 `talk`

会议/讲座录制(video/audio)的结构化摘要。转写本体是同目录的 `transcript.md`;
媒体本体 `recording.<ext>` 不入库(gitignore)。由 `collect-material` 的 Talk 分支生成。

```ts
export const TalkSchema = z.object({
  type:    z.literal('talk'),
  title:   Title,
  date:    z.string().date(),          // 录制日期(整日 ISO)
  speaker: z.array(Name).optional(),   // 讲者姓名(可关联 vault/authors/)
  themes:  z.array(z.string()).optional(),  // 复用全库 themes 词表
  rating:  Rating.optional(),
  media:   ShortString,                // 媒体文件名
}).strict();
```

**示例**:

```yaml
---
type: talk
title: "Lajilao"
date: 2024-11-08
speaker:
  - Zhou Pengan
themes:
  - e-waste
  - repair
media: recording.mp4
---
```

**规则**:
- key 顺序:`type → title → date → speaker → themes → rating → media`
- `speaker` / `themes` 为空时**省略整键**(不写 `[]`);静音/失败录制常为空
- 正文为六个固定**四字 H2**(见 §4),顺序字样不得变动,缺内容保留标题写「（…)」

---

### 3.10 `transcript`

讲座的带 `[hh:mm:ss]` 时间戳全文转写(多引擎集成,机器生成,tracked)。
lightweight 类型,正文自由(无固定 H2),`talk` 字段反向引用所属 talk slug。

```ts
export const TranscriptSchema = z.object({
  type:  z.literal('transcript'),
  title: Title,
  talk:  ShortString,                  // 所属 talk 的 slug
}).strict();
```

**规则**:
- frontmatter 只允许 `type` / `title` / `talk`
- 正文自由格式,不校验 H2 schema

---

### 3.11 `webpage`

已捕获 HTTP(S) 网页的语义分析页，原始快照与清洗正文由工作流保存，
不进入 frontmatter。

```ts
export const WebpageSchema = z.object({
  type:        z.literal('webpage'),
  title:       Title,
  url:         WebURL,                 // credential-free HTTP(S) URL
  captured_at: DateTime,                // UTC, whole-second precision
  authors:     z.array(Name).optional(),
  published:   Date.optional(),
  site:        ShortString.optional(),
  themes:      z.array(z.string()).optional(),
  topics:      z.array(z.string()).optional(),
  rating:      Rating.optional(),
}).strict();
```

**规则**:
- canonical path: `vault/webpages/{slug}/webpage.md`
- `url` 只接受不含凭据的 `http` 或 `https` URL；canonical URL normalization 属于 capture capability
- `captured_at` 必须为 UTC 且精确至秒
- 正文先写一个 H1，再按顺序包含必填 `## Summary` 与 `## Content`；`Content` 可保留原始页面的内部 Markdown 结构，内部标题从 H3 开始
- `snapshot`、`format`、`sha256`、`bytes` 等技术采集字段不属于网页的语义 frontmatter

### 3.12 `archive`

单件档案材料：一条帖子及其回复、一段视频及其评论可作为一件，收录范围在正文说明。
已有 `image`、`talk`、`webpage` 类型继续保留，不自动迁移。多次保存同一材料不自动建立新对象。

固定入口为 `vault/archives/<slug>/archive.md`，slug 使用 kebab-case。
必填字段为 `type: archive`、`title`、`kind`、`created`（完整 `YYYY-MM-DD` 建档日期）。
`kind` 描述对象而非保存格式，只接受 `patent|thread|post|video|image|webpage|document`。
截图中的帖子仍为 `post` 或 `thread`，PDF 专利仍为 `patent`。

可选字段：`creator`（姓名字符串数组，沿用 image）、`date`（原材料完整发布日期，
专利为公开日期）、`source`（来源自由文本）、`url`（原始对象直接链接）、
`themes`（主题字符串数组）、`topics`（专题 slug 数组）、`rating`（现有整数 1..5）。
未知字段省略；年份或约略年代写在正文，不补造完整日期。类别专属信息暂放正文。

正文自由，可为空；材料概况、来源与保存、内容与摘录、关联只是建议栏目。
只有元数据和来源链接也有效，不要求附件、OCR、快照或分析。
原件布局和多次保存方案尚未确定，不引入原件路径字段、不假设只有一个原件；
已保存文件可在正文链接。note 的 `annotates` 可指向上述固定入口。
`topics` 支持成员标签，但不把 Archive 自动纳入仅支持 Book/Paper/Talk 的研究 Workflow corpus。

## 4. Body Schemas(正文结构 schema)

### 4.1 概念

vault 中每个文件除了 frontmatter("硬属性"),还有正文 markdown("软属性")。
**Body schema 把正文里每个 `## H2` 段视为一个 typed block**:

- H2 标题即"判别符"(类似 frontmatter `type` 字段)
- H2 之下的 markdown 内容有**期望的 block 形状**(`kind`):`paragraph` / `bullet-list` /
  `numbered-list` / `table` / `blockquote-list` / `definition-list` / `h3-project-tabs` /
  `h3-sections` / `freeform` / `mixed`
- lint 只检查 **(a) 必填 H2 存在 (b) 形状匹配**,**不查字数 / 语义**
- reader 可按 kind **类型化渲染**:table 显示交互表;blockquote 显示引用卡片;
  bullet-list 显示可点击 chips

### 4.2 Block kinds

```ts
type BlockKind =
  | 'paragraph'              // 自由段落
  | 'bullet-list'            // `- item`
  | 'numbered-list'          // `1. item`
  | 'table'                  // markdown table
  | 'blockquote-list'        // 多个 `> quote`
  | 'definition-list'        // **term**: description 模式
  | 'h3-project-tabs'        // H2 下分 H3,每个 H3 是一个 project 子节(reader 渲染为 tabs)
  | 'h3-sections'            // H2 下分 H3,每个 H3 是原文小节
  | 'freeform'               // 已知 H2 内任意非空 Markdown 形状
  | 'mixed';                 // 杂(暂时容忍,长期靠 autofix 收敛)
```

### 4.3 `h3-project-tabs`(多项目模式)

为了支持"同一份 vault 跑多个项目"的工作流,把"与项目主题的关联"这类**跨项目变体**变成结构化:

```markdown
## 与项目主题的关联       <- 固定 H2(不再随项目名变化)
### 技术、AI、媒介与具身化  <- project 1 的 tab
<paragraph 内容>

### Body, Technology and Society  <- project 2 的 tab
<paragraph 内容>

### non-human bodies      <- project 3 的 tab
<paragraph 内容>
```

**架构修复**:LLM 生成时**不要把项目名嵌入 H2**;项目名进 H3。当前 vault 里出现的
"与 X 的关联" 各种长尾标题(`与 数字技术、AI、媒介... 的关联` / `与 BTS 的关联` …)
迁移期 autofix 自动收编为该 H2 下的某个 H3。

reader 端:每个 H3 渲染为一个 tab,用户点 tab 切换项目视角。

### 4.4 当前 executable BodySchema

下表摘要必须与 `scripts/schemas/body.py` 一致；aliases、columns、condition 与 evidence rules 的完整定义以该文件为准。

| Type | 必填 H2（kind） | 可选 H2（kind） |
|---|---|---|
| `author` | `思想肖像`（paragraph）；`学术轨迹`（paragraph）；`关键概念`（table）；`理论网络`（bullet-list）；`金句要点`（blockquote-list）；`项目关联`（h3-project-tabs） | `代表著作`（paragraph） |
| `book` | `核心论点`（paragraph）；`章节逻辑`（paragraph）；`关键概念`（table）；`理论贡献`（paragraph）；`精读章节`（numbered-list） | `项目关联`（h3-project-tabs） |
| `chapter` | `核心论点`（paragraph）；`理论框架`（paragraph）；`分节摘要`（h3-sections）；`关键概念`（table）；`核心引用`（numbered-list） | `金句要点`（blockquote-list）；`项目关联`（h3-project-tabs） |
| `paper` | `核心论点`（paragraph）；`理论框架`（paragraph）；`分节摘要`（h3-sections）；`关键概念`（table）；`核心引用`（numbered-list） | `金句要点`（blockquote-list）；`项目关联`（h3-project-tabs） |
| `talk` | `核心论点`（paragraph）；`分节摘要`（h3-sections）；`关键概念`（table）；`项目关联`（bullet-list）；`文献人物`（bullet-list）；`时间脉络`（bullet-list） | — |
| `webpage` | `Summary`（paragraph）；`Content`（freeform） | — |
| `topic` / `journal` / `note` / `image` / `archive` / `transcript` | 正文自由，不设固定 H2 | — |

所有当前 registry 对象的 `BodySchema.strict` 默认为 `false`。required H2 缺失、heading drift 与 block-kind mismatch 始终是 blocking violation；alias 先解析到 canonical section，再报告可机械规范化的 `h2_alias`；未知 H2 在 `strict: false` 时仅为 advisory warning，在 `strict: true` 时才是 blocking violation。

### 4.5 已经"自然 typed"的高价值 block

数据里发现一批 100% 单形状的 H2,reader 实现类型化渲染时**最优先做这几个**:

| Type · H2 | 量 | 形状 | 渲染建议 |
|---|---:|---|---|
| `author · 关键概念` | 229 | table | 概念表,行可点 → 跳对应论文 |
| `author · 代表著作` | 158 | paragraph | 5 部专著一段(过滤掉论文条目) |
| `book · 关键概念` | 664 | table | 跨 vault `union` → 整库概念图谱 |
| `chapter · 关键概念` | ~7000 | table | 章节级概念表 |
| `paper · 金句要点` | 22 | blockquote-list | 引用卡片,一键复制带源 |
| `chapter · 项目关联` | 3196 | h3-project-tabs | 多项目 tab 切换 |

### 4.6 已收敛的决策

- `author.理论网络` kind = bullet-list(63% 占优)
- `金句要点` kind = blockquote-list(跨 author / chapter / paper 统一)
- `关键概念` kind = table(跨 author / book / chapter / paper 全部统一)
- `项目关联` kind = h3-project-tabs(项目名进 H3,不进 H2)
- `分节摘要` kind = h3-sections(H3 是原文小节,不是项目 tab)
- Reader 的类型化渲染:Phase 1 落地基础渲染(table / blockquote / list / paragraph);
  跨 vault union(全库概念图谱、引用卡片)留后续 reader 0.3+

## 5. Document-level 规则

除 frontmatter schema 和 body H2 schema 外,还有几条**文档级别**的规则:

### 5.1 H1 (`#`) 标题

每个文件必须有且仅有一个 H1。**H1 是实体的展示名,不是装饰标签**:

| Type | Canonical H1 |
|---|---|
| `author`  | `# {name}`(例:`# Sara Ahmed`)|
| `book`    | `# {title}`(完整书名,跟 frontmatter.title 一致)|
| `chapter` | `# {章节展示标题}`(无 `chapter_label` 时逐字使用 manifest title；有时以 label 前缀一次)|
| `paper`   | `# {paper_title}`(译文或英文原标题)|

**禁止形式**:
- `# 全书概览` / `# 学者档案` 这种 generic label(没有实体信息量)
- `# Title — 全书概览` 这种"实体名 + 装饰后缀"

**理由**:H1 给 Obsidian / 文件列表 / 渲染器看,应当告知"这是关于什么的"。

### 5.2 YAML frontmatter 风格

数组用 **block list**(标准 YAML 序列),不用 inline flow form:

```yaml
# ✓ 正确
authors:
  - Sara Ahmed
themes:
  - affect-theory
  - queer-theory

# ✗ 错误(易被 Ulysses 等 Markdown 编辑器破坏成 `[a, b](#)`)
authors: [Sara Ahmed]
themes: [affect-theory, queer-theory]
```

**为什么 block list**:Marple reader 的 vault 文件常被 Ulysses / Bear / iA Writer 等编辑器二次编辑;
这些编辑器把 `[a, b]` 识别为 markdown 链接残骸,会咬成 `[a, b](#)` 损坏数据。
Block list 没有 `[` `]` 触发点,跨编辑器稳定。

**空列表 → 整行省略**(不写 `themes: []`,也不写 `themes: null`):

```yaml
# ✓ 没有 themes 字段就完全不出现
type: chapter
title: ...
authors:
  - Anne Allison
year: 1994
book: ...

# ✗ 错误
themes: []
```

Key 按 **schema 字段声明顺序** 排列(autofix 自动做):

```yaml
# author (canonical order):
type: author
name: Sara Ahmed
themes:
  - affect-theory
  - queer-theory
rating: 5
```

### 5.3 跨 type 同名规则

以下 H2 在多个 type 复用,kind 按 type 分:

| H2 | author | book | chapter | paper |
|---|---|---|---|---|
| `## 关键概念` | table | table | table | table |
| `## 金句要点` | blockquote | — | blockquote | blockquote |
| `## 项目关联` | h3-project-tabs | h3-project-tabs | h3-project-tabs | h3-project-tabs |

reader 看 frontmatter type 决定如何渲染同名 H2。

## 6. 两种 strictness

frontmatter 与正文的 strictness 是两套独立契约，不得混用：

1. **Frontmatter schema**：当前 12 个 Pydantic model 均使用 `ConfigDict(extra="forbid", strict=True)`。未知字段、错误值类型和缺失必填字段属于 blocking validation error，不是 warning。
2. **`BodySchema.strict`**：只控制「未知 H2」的严重性。`false` 时未知 H2 是 non-blocking advisory；`true` 时未知 H2 是 blocking violation。它不改变 required H2、alias 或 block-kind 校验。

只读检查使用 `quasi-audit --report typecheck --format json`。`fields`、`toc` 与 `typecheck` 三种 report 都只写 stdout：不得创建 `.quasi/schema.json`、`.quasi/audit/` 或 project-local temp files。默认不带 `--report` 的 audit 仍是 writer，会执行机械修复并刷新 schema snapshot。

## 7. 决策记录(rationale)

按问答收敛的决策固化:

- **Q1 rating canonical = number 1..5**:存储用数据形式,渲染由前端做(`'★'.repeat(n)`)。排序、过滤、平均值天然支持;LLM 友好;Unicode 无关
- **Q2 themes 空 → warning 不 fail**:author/chapter 大量条目确实没标签,空数组允许;但 paper 必须有
- **Q3 author 的 year/source 删除**:8% / 7% 非空率,语义不明,保留是噪音
- **Q4 孤儿字段一律删**:仅出现于 <2% 文档的字段视为 LLM 临场漂移,无消费方
- **Q5 strictness 分层**：frontmatter 当前严格拒绝 extra fields；`BodySchema.strict` 仅控制未知 H2 是 advisory 还是 failure
- **Q6 topic 入 type 体系但保持轻量**:`type: topic` 只校验 overview/resources 页面的最小 frontmatter;研究内容放正文
- **Q7 primitives.py 保留**:不是继承基类,是值层验证器;现规模不必 inline
- **Q8 journal 入 type 体系但保持轻量**:`type: journal` 只校验 overview/resources 页面的最小 frontmatter;扫描统计放正文
- **Q9 author.title → name**:author 是"人"实体,用 name 比 title 语义对路;
  跨 type 的"展示名"由 reader 侧 `entry.displayName` accessor 统一(`name || title`)
- **Q10 authors 永远数组**:消费端代码无需 `typeof author === 'string' ? ... : author.map(...)`
- **Q11 rating 用数字 1..5**:存储用数据形式;reader 渲染 ★ 字符;排序/平均自然
- **Q12 关键概念 跨 4 type 统一 table**:跨 vault union 可得整库概念图谱
- **Q13 金句要点 跨 author/chapter/paper 统一 blockquote-list**:语义都是"原文金句"
- **Q14 H1 = 实体展示名 不带装饰后缀**:为 Obsidian 标题栏服务
- **Q15 YAML 风格统一**:block list + schema key 顺序 + 空列表省略,跟 SPEC §5.2 对齐
  (block list 而非 flow form 的根因:Ulysses 等编辑器把 `[a, b]` 咬成 `[a, b](#)` 损坏)
- **Q16 bin/ 模式 而非 \$CLAUDE_PLUGIN_ROOT**:后者在 CC 2.1.139 未注入(GitHub #9354);
  bin/ shim 自己用 realpath 找 plugin 根 + 维护 venv,无 env 依赖
- **Q17 pydantic V2 而非 zod**:用户基础设施是 Python,且 Pydantic 错误信息富,LLM 修复 prompt 友好

## 8. 生成代理(`quasi:*`)的约定

LLM 生成新文档时**应当**:

1. `type` 字段必须是 registry 中 12 个 canonical 之一：`archive` / `author` / `book` / `chapter` / `image` / `journal` / `note` / `paper` / `talk` / `topic` / `transcript` / `webpage`
2. 必填字段一定填(参考各 type 的 required 列表)
3. 不引入新字段,除非已经在 SPEC 中
4. **rating 用数字 1..5,不是 ★ 字符串**(reader 渲染层负责显示 ★)
5. themes 用 hyphen-joined 形式(`affect-theory` 不是 `affect theory`)
6. **authors 永远是数组**(单作者也用 block list 单元素,不是 scalar);见 §5.2
7. topic / journal 只写 `kind: overview` 或 `kind: resources`,不要发明 workflow-stage kind
8. note / image / archive 正文自由;frontmatter 只写 schema 明确列出的轻量字段

**Body 约定**:
1. 必填 H2 全部生成，使用 SPEC 列出的 canonical 标题（多数分析类型为四字中文，webpage 为 `Summary` / `Content`），不要发明同义变体
2. H2 之下的 block 形状必须匹配(`kind: table` 就真生成 markdown table,不是描述性段落)
3. 跨项目内容用 `## 项目关联` + `### <项目名>` 嵌套,**不要把项目名写进 H2**
4. **H1 = 实体展示名**,不要装饰后缀(详见 §5.1)
5. **YAML 数组用 block list**(每项 `  - value`),不用 inline flow form;空列表整行省略(详见 §5.2)
6. 长尾自定义 H2 在当前 `BodySchema.strict: false` 下会产生 advisory；若某类型显式改为 `true` 则会被拒，仍应尽量约束在 SPEC 内

**如果发现 SPEC 不覆盖你的需求,先 PR SPEC,不要私自扩展字段或 H2。**

## 9. 实现与验证入口

- `scripts/schemas/registry.py`：12 个 canonical types 的唯一 registry。
- `scripts/schemas/body.py`：正文 section、alias、kind 与 `BodySchema.strict` 的 executable contract。
- `scripts/typecheck/typecheck.py`：纯内存 evaluation、可选 artifact writer 与稳定结果 payload。
- `scripts/typecheck/autofix_mechanical.py`：默认 audit 使用的机械修复层。
- `bin/quasi-audit`：公开入口。`--report fields|toc|typecheck` 为 stdout-only；不带 `--report` 为 writer audit。
- `tests/test_schema_registry.py`、`tests/test_audit_cli.py` 与 typecheck contract tests：schema、strictness、no-write 和 registry coverage 的回归保护。

---

**同步规则**：artifact shape 先改 `scripts/schemas/` executable contract，再在同一变更中同步本 SPEC 与测试。任何 vault 数据迁移、插件发布或已安装 cache 更新都需要独立授权，不由 schema 文档变更自动触发。

# quasi-vault Schema Specification

```
Version : 0.1.0-draft
Status  : 评审中 — 待用户拍板后冻结,作为后续 lint / autofix / 生成约定的事实标准
Last    : 2026-05-11
```

## 0. 文档定位

这份 SPEC **是**:
- vault 中"被打 type 的实体文档"的形状权威定义
- 所有 LLM 生成代理在生成新文档时应当遵循的约定
- `typecheck.mjs` 验证器和 `autofix.mjs` 迁移器(待写)的输入

这份 SPEC **不是**:
- 实现代码(在 `*.schema.ts` 里)
- 迁移计划(在 `MIGRATION.md`,待写)
- vault 当前实际状态(在 `data/schema-inference.md`)

**任何 vault 文件的修改在 SPEC + MIGRATION 双双批准之前都不会发生。**

## 1. 类型系统总览

vault 中的"实体文档"使用 5 个 canonical type:

| `type`    | 实体                  | 主要路径                                 | 当前数量 | 当前命名 |
| --------- | --------------------- | ---------------------------------------- | -------- | -------- |
| `author`  | 学者档案              | `vault/authors/<slug>.md`                | 229      | `author-profile` |
| `book`    | 一本书的整体分析      | `vault/books/<slug>/00-overview.md`      | 779      | `book-overview` |
| `chapter` | 书的一个章节分析      | `vault/books/<slug>/chXX-*.md`           | 8093     | `chapter-summary` |
| `paper`   | 论文分析(含期刊文章)  | `vault/papers/*.md` & `vault/journals/*/<doi>.md` | 1651 | `paper-analysis` / `journal-article-analysis` |
| `journal` | 期刊档案              | `vault/journals/<slug>/00-profile.md`(待建) | 0       | (将由 `journal-synthesis` 升级或新建) |

### 不在 type 体系内

下列文档**不打 `type`,作为自由格式存在**,reader 仍展示但不参与 schema 校验:

- `topic-synthesis` 8 条(在 `vault/topics/`):跨实体的研究综合,语义不属于"实体"轴
- `vault/journals/<slug>/00-scan.md`:原始扫描报告,机器生成,非分析输出
- `vault/.obsidian/` / `.makemd/` 等编辑器配置(已自然跳过)

## 2. 共享原语 (`primitives.py`)

定义在 `$CLAUDE_PLUGIN_ROOT/schemas/primitives.py`。**这不是继承基类** —— 是值层面的 Pydantic 验证器原语,被各 type schema 按需复用。每个 type schema 结构独立。

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

每个 type 给出:**Zod 形状 + frontmatter 示例 + 与现状差异**。

完整 Zod 代码到 `*.schema.ts` 实现时落地,此处用伪 Zod 表达意图。

---

### 3.1 `author`

学者档案。一个作者一份。

```ts
export const AuthorSchema = z.object({
  type:    z.literal('author'),
  name:    Name,                    // 作者全名,作为该 entity 的展示名
  themes:  Themes,                  // 研究方向标签
  rating:  Rating.optional(),       // 整体学术评分(可选,数字 1..5)
});
// 不开 .strict() —— 迁移期保留未知字段为 lint warning
// wikilink 形式 [[slug|Sara Ahmed]] 由 reader 从文件路径派生,不在 frontmatter
```

**示例 frontmatter**:

```yaml
---
type: author
name: Sara Ahmed
themes: [affect-theory, queer-phenomenology, feminist-theory, racism, killjoy]
rating: 5
---
```

**与现状差异**(229 条):
- `type: author-profile` → `type: author`
- **`title` → `name`**(author 是"人",用 name 更对路;跨 type 统一用 `entry.displayName` accessor)
- **删除字段**:`author`(与 name 冗余;wikilink 由路径派生)、`year`(8% 非空)、`source`(7% 非空)、`has-profile`(3% 非空)
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
  category:  z.enum(['monograph', 'edited-volume', 'handbook', 'other'])
             .default('monograph').optional(),    // 决定 BibTeX export 用 author 还是 editor

  // 学术分析字段
  themes:    Themes.optional(),
  rating:    Rating.optional(),                   // number 1..5
});
// chapters_analyzed 不存在 schema —— reader 从子章节 count 派生
// topic 不存在 schema —— 工作流分组通过 themes / topic-synthesis 表达
// edition / note 删除 —— rare,有需要时用 markdown 正文表达
```

**示例 — 专著(monograph,默认)**:

```yaml
---
type: book
title: "Nightwork: Sexuality, Pleasure, and Corporate Masculinity in a Tokyo Hostess Club"
authors: ["Anne Allison"]
year: 1994
publisher: "University of Chicago Press"
isbn: "978-0226014876"
category: monograph
themes: [japan-studies, gender, corporate-masculinity, ethnography]
rating: 4
---
```

**示例 — 文集(edited-volume)**:

```yaml
---
type: book
title: "The Affect Theory Reader"
authors: ["Melissa Gregg", "Gregory J. Seigworth"]
year: 2010
publisher: "Duke University Press"
isbn: "978-0822347767"
category: edited-volume
themes: [affect-theory]
rating: 5
---
```

**与现状差异**(779 条,44 字段 → 9 字段):
- `type: book-overview` → `type: book`
- **保留并 canonical 化**:`title` / `author` / `year` / `themes` / `rating` / `publisher`
- **新增字段**:`isbn`、`category`(默认 monograph)
- **删除字段**(原有但不再保留):
  - `topic`(84% 在用)—— 工作流字段,通过 themes / topic-synthesis 表达
  - `chapters_analyzed`(83% 在用)—— reader 从子章节 count 派生
  - `edition`(1 条)—— rare,需要时写 note
  - `source`(70 条)—— 与 title 信息重叠
- **同义字段合并**(autofix):
  - `book_title` / `book_author` / `book_year` → `title` / `author` / `year`
  - `authors` → `author`
  - `editors` → `author` + `category: edited-volume`
  - `tags` → `themes`
  - 9 个 `chapters_*` 变体 → 全删(派生)
- **publisher 大量补全**:当前仅 6% 填,fix-agent 调 WorldCat / OpenAlex 批量补
- **删除孤儿字段**:`has-overview` / `analyzed` / `confidence` / `selective_reading` / `selection_note` / `scope_note` / `source_file` / `source_note` / `source_type` / `slug` / `status` / `structure` / `version` / `supersedes` / `overall_rating` / `avg_relevance` / `chapters_missing` / `relevance` / `date` / `concepts` / `book` / `topics` —— 20+ 个 <1% 字段

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
  doi:     z.string().regex(/^10\.\d+\//).optional(),  // 部分章节(尤其论文集里的)有 DOI
  themes:  Themes.optional(),                  // 章节级主题(31% 非空,可空)
  rating:  Rating.optional(),                  // number 1..5
});
```

**示例**:

```yaml
---
type: chapter
title: "第1章 一种地方类型"
authors: ["Anne Allison"]
year: 1994
book: "allison-nightwork-1994"
themes: [hostess-club, communitas, space]
rating: 1
---
```

**与现状差异**(8093 条,22 字段 → 7 字段):
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
  - `chapter_title` / `chapter_label` / `chapter-author` / `editors` / `publisher` / `pages` / `tags` / `topic` / `topics` / `word_count_est` / `status` —— ~11 个孤儿字段
- **`year` 必填**:当前 100% 填,直接收紧
- **`themes` 保持 optional**:章节级主题经常没有

---

### 3.4 `paper`

期刊论文分析。**paper 严格指期刊文章**;书的章节(包括论文集里的章节)归 `chapter` 类型,放在 `vault/books/<slug>/`。

**与 chapter 的关系**:几乎是 chapter 的变体 —— 5/8 字段完全相同,只在容器引用处分叉。

| paper | chapter |
| --- | --- |
| `journal` (期刊名) | `book` (父书 slug) |
| `doi` (规则化格式) | — |
| 其余 6 字段相同(`type` / `title` / `authors` / `year` / `themes` / `rating`) | |

```ts
export const PaperSchema = z.object({
  type:    z.literal('paper'),
  title:   Title,
  authors: Authors,                             // 永远数组
  year:    Year,
  journal: z.string().min(2),                   // 必填 —— paper = 期刊论文
  doi:     z.string().regex(/^10\.\d+\//).optional(),
  themes:  Themes,                              // 必填(论文应有主题)
  rating:  Rating.optional(),                   // number 1..5
});
```

**示例**:

```yaml
---
type: paper
title: "Happy Objects"
authors: ["Sara Ahmed"]
year: 2010
journal: "The Affect Theory Reader"
themes: [affect-theory, happiness, queer-theory, sticky-affect, feminist-killjoy]
rating: 2
doi: "10.1215/9780822393047-001"
---
```

> ⚠️ Happy Objects 实际收录于一本论文集(Reader),不是期刊。若严格执行"paper = 期刊论文",这类文件应迁移到 `vault/books/affect-theory-reader/ch-happy-objects.md` 转为 chapter 类型。**autofix 在迁移阶段会做启发式分类**(看 source 像不像书),提议清单等用户 review。

**与现状差异**(1651 条,28 字段 → 8 字段):
- `type: paper-analysis` / `journal-article-analysis` / `article-analysis` / `paper-summary` → `type: paper`
- **`author` → `authors`**(单字符串 → 数组)
- **`source` → `journal`**(语义收紧:paper 只指期刊文章)
- **同义字段合并**:
  - `authors` (旧 array 字段) → `authors`(新字段,Authors 原语)
  - `tags` → `themes`
  - `date` → `year`(50 条;需人工挑出"分析日期"误用)
  - `score` → `rating`(数字)
  - `paper_title` → `title`
- **删除孤儿字段**(~15 个 <2%):`reviewed_book` / `reviewed_author` / `terminal` / `notes` / `note` / `status` / `volume` / `pages` / `citations` / `source_type` / `translators` / `round` / `concepts` / `topic` / `relevance`
- **doi 校验**:1614 条有 doi,空字符串和格式错的 lint 报告
- **journal 大量补全**:当前只有 10% 显式 `journal` 字段;~140 条 `source: <书名>` 需要 review 决定迁去 chapter 还是改 journal
- **themes hyphen-joined**:`"affect theory"` → `"affect-theory"`

---

### 3.5 `journal`

**新增类型**。期刊档案(`vault/journals/<slug>/00-profile.md`)。

> 第一阶段不强制为现有 12 个期刊目录创建 profile。Schema 落地、其他 type 稳定后再决定是否运行 `process-journal` agent 批量生成。

```ts
export const JournalSchema = z.object({
  type:           z.literal('journal'),
  title:          Title,                          // 期刊全名
  themes:         Themes.optional(),              // 期刊主题范围
  rating:         Rating.optional(),              // 期刊整体相关度
  papers_scanned: z.number().int().nonnegative().optional(),  // 已扫描文章数
  papers_kept:    z.number().int().nonnegative().optional(),  // 入库文章数
});
```

**示例**(假设):

```yaml
---
type: journal
title: "British Journal of Sociology"
themes: [sociology, social-theory, uk-academia]
rating: 3
papers_scanned: 852
papers_kept: 16
---
```

**与现状差异**:
- 目前 8 条 `journal-synthesis` 可考虑迁移为 `journal`(或保留为 free-form synthesis)
- 12 个期刊目录中其他 `00-synthesis.md` 文件按需迁移
- **第一阶段**:schema 定义就位但不迁移,等 SPEC 其余部分稳定再启动

## 4. Body Schemas(正文结构 schema)

### 4.1 概念

vault 中每个文件除了 frontmatter("硬属性"),还有正文 markdown("软属性")。
**Body schema 把正文里每个 `## H2` 段视为一个 typed block**:

- H2 标题即"判别符"(类似 frontmatter `type` 字段)
- H2 之下的 markdown 内容有**期望的 block 形状**(`kind`):`paragraph` / `bullet-list` /
  `numbered-list` / `table` / `blockquote-list` / `definition-list` / `h3-project-tabs`
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

### 4.4 BodySchema 起草(v0.2 候选)

> 基于 `reader/data/body-audit.md` 的实际数据起草。每个 type 的"必填 H2"是
> vault 里覆盖 ≥80% 的高频骨架,放心收紧。剩下的归 optional。

```ts
// schemas/author.body.ts
export const AuthorBodySchema = {
  sections: {
    '学术轨迹':           { required: true,  kind: 'paragraph' },
    '核心概念谱系':       { required: true,  kind: 'table' },
    '理论网络':           { required: true,  kind: 'bullet-list',
                          aliases: ['思想肖像'] },
    '可引用观点':         { required: true,  kind: 'numbered-list' },  // TBD: 也可能 blockquote-list
    '与项目主题的关联':   { required: true,  kind: 'h3-project-tabs',
                          childKind: 'paragraph',
                          aliases: [/^与 .+ 的关联$/, /^与"[^"]+"的关联$/, '与本项目主题的关联'] },
    '代表作概览':         { required: false, kind: 'table',
                          aliases: ['代表著作'] },
  },
  strict: false,
};

// schemas/book.body.ts
export const BookBodySchema = {
  sections: {
    '核心论点':           { required: true,  kind: 'paragraph',
                          aliases: ['全书核心论点', '一、全书核心论点'] },
    '关键概念表':         { required: true,  kind: 'table',
                          aliases: ['三、核心概念表', '关键概念谱系', '关键概念'] },
    '章节间逻辑':         { required: true,  kind: 'paragraph' },
    '理论贡献':           { required: true,  kind: 'paragraph',
                          aliases: ['核心理论贡献'] },
    '推荐精读章节':       { required: true,  kind: 'numbered-list' },
    '与项目主题的关联':   { required: false, kind: 'h3-project-tabs',
                          childKind: 'paragraph',
                          aliases: [/^与 .+ 的关联$/] },
  },
  strict: false,
};

// schemas/chapter.body.ts
export const ChapterBodySchema = {
  sections: {
    '核心论点':           { required: true,  kind: 'paragraph' },
    '关键概念':           { required: true,  kind: 'paragraph' },
    '分节摘要':           { required: true,  kind: 'paragraph' },
    '理论框架':           { required: true,  kind: 'paragraph' },
    '价值评估':           { required: true,  kind: 'paragraph' },
    '核心引用文献':       { required: true,  kind: 'numbered-list' },   // 当前 mixed,迁移期归一
    '与项目主题的关联':   { required: false, kind: 'h3-project-tabs',
                          childKind: 'numbered-list',
                          aliases: [/^与 .+ 的关联$/, /^★+ 与 .+/] },
    '相关引用文献':       { required: false, kind: 'h3-project-tabs',
                          childKind: 'paragraph',
                          aliases: [/^直接相关的 .+ 引用文献$/] },
  },
  strict: false,
};

// schemas/paper.body.ts
export const PaperBodySchema = {
  sections: {
    '核心论点':           { required: true,  kind: 'paragraph' },
    '关键概念':           { required: true,  kind: 'paragraph' },
    '理论框架':           { required: true,  kind: 'paragraph' },
    '分节摘要':           { required: true,  kind: 'paragraph' },
    '价值评估':           { required: true,  kind: 'paragraph' },
    '核心引用文献':       { required: true,  kind: 'numbered-list' },
    '可引用段落':         { required: false, kind: 'blockquote-list' },
    '与项目主题的关联':   { required: false, kind: 'h3-project-tabs',
                          childKind: 'numbered-list',
                          aliases: [/^与 .+ 的关联$/, /^★+ 与/] },
  },
  strict: false,
};
```

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
| `chapter` | `# {chapter_label} {title}`(例:`# 第1章 一种地方类型`)|
| `paper`   | `# {paper_title}`(译文或英文原标题)|

**禁止形式**:
- `# 全书概览` / `# 学者档案` 这种 generic label(没有实体信息量)
- `# Title — 全书概览` 这种"实体名 + 装饰后缀"

**理由**:H1 给 Obsidian / 文件列表 / 渲染器看,应当告知"这是关于什么的"。

### 5.2 YAML frontmatter 风格

数组用 **inline flow form**,不用 block list:

```yaml
# ✓ 正确
authors: [Sara Ahmed]
themes: [affect-theory, queer-theory]

# ✗ 错误
authors:
- Sara Ahmed
```

Key 按 **schema 字段声明顺序** 排列(autofix 自动做):

```yaml
# author (canonical order):
type: author
name: Sara Ahmed
themes: [affect-theory, queer-theory]
rating: 5
```

**长数组不折行**(autofix 用 `width=4096`):

```yaml
# ✓ 单行
themes: [affect-theory, happiness, phenomenology, queer-theory, feminist-killjoy]

# ✗ PyYAML 默认 80 字符折行
themes: [affect-theory, happiness, phenomenology, queer-theory,
  feminist-killjoy]
```

### 5.3 跨 type 同名规则

以下 H2 在多个 type 复用,kind 按 type 分:

| H2 | author | book | chapter | paper |
|---|---|---|---|---|
| `## 关键概念` | table | table | table | table |
| `## 金句要点` | blockquote | — | blockquote | blockquote |
| `## 项目关联` | h3-project-tabs | h3-project-tabs | h3-project-tabs | h3-project-tabs |

reader 看 frontmatter type 决定如何渲染同名 H2。

## 6. `.strict()` 渐进开关

不在 SPEC v0.1.0 中开 `.strict()`。分三阶段引入:

| 阶段 | 时间 | 行为 |
|---|---|---|
| **Phase 1**(SPEC 落地后) | 立即 | schema 实现完,跑 typecheck,不开 .strict()。未知字段进 lint warning |
| **Phase 2**(autofix 跑完) | 漂移清理后 | 跑一次大 autofix,清掉同义字段、孤儿字段,人工 review 边界 |
| **Phase 3**(稳态) | autofix 后再观察一周 | 开 .strict()。新出现的未知字段直接 fail,强制干净 |

## 7. 决策记录(rationale)

按问答收敛的决策固化:

- **Q1 rating canonical = number 1..5**:存储用数据形式,渲染由前端做(`'★'.repeat(n)`)。排序、过滤、平均值天然支持;LLM 友好;Unicode 无关
- **Q2 themes 空 → warning 不 fail**:author/chapter 大量条目确实没标签,空数组允许;但 paper 必须有
- **Q3 author 的 year/source 删除**:8% / 7% 非空率,语义不明,保留是噪音
- **Q4 孤儿字段一律删**:仅出现于 <2% 文档的字段视为 LLM 临场漂移,无消费方
- **Q5 .strict() 分三阶段**:一刀切会让 vault 100% 红
- **Q6 topic 暂不入 type 体系**:研究问题 ≠ 实体,先保留为自由文档
- **Q7 primitives.py 保留**:不是继承基类,是值层验证器;现规模不必 inline
- **Q8 journal 第一阶段不迁移**:type 定义就位但目录不动,稳定其余 4 个 type 后再决定
- **Q9 author.title → name**:author 是"人"实体,用 name 比 title 语义对路;
  跨 type 的"展示名"由 reader 侧 `entry.displayName` accessor 统一(`name || title`)
- **Q10 authors 永远数组**:消费端代码无需 `typeof author === 'string' ? ... : author.map(...)`
- **Q11 rating 用数字 1..5**:存储用数据形式;reader 渲染 ★ 字符;排序/平均自然
- **Q12 关键概念 跨 4 type 统一 table**:跨 vault union 可得整库概念图谱
- **Q13 金句要点 跨 author/chapter/paper 统一 blockquote-list**:语义都是"原文金句"
- **Q14 H1 = 实体展示名 不带装饰后缀**:为 Obsidian 标题栏服务
- **Q15 YAML 风格统一**:flow form + schema key 顺序 + 不折行,跟 SPEC 示例对齐
- **Q16 bin/ 模式 而非 \$CLAUDE_PLUGIN_ROOT**:后者在 CC 2.1.139 未注入(GitHub #9354);
  bin/ shim 自己用 realpath 找 plugin 根 + 维护 venv,无 env 依赖
- **Q17 pydantic V2 而非 zod**:用户基础设施是 Python,且 Pydantic 错误信息富,LLM 修复 prompt 友好

## 8. 生成代理(`quasi:*`)的约定

LLM 生成新文档时**应当**:

1. `type` 字段必须是 4 个 canonical 之一(`author` / `book` / `chapter` / `paper`)
2. 必填字段一定填(参考各 type 的 required 列表)
3. 不引入新字段,除非已经在 SPEC 中
4. **rating 用数字 1..5,不是 ★ 字符串**(reader 渲染层负责显示 ★)
5. themes 用 hyphen-joined 形式(`affect-theory` 不是 `affect theory`)
6. **authors 永远是数组**(单作者也用 `["Sara Ahmed"]`,不是 `"Sara Ahmed"`)

**Body 约定**:
1. 必填 H2 全部生成,**用 SPEC 列的 canonical 4 字标题**,不要发明同义变体
2. H2 之下的 block 形状必须匹配(`kind: table` 就真生成 markdown table,不是描述性段落)
3. 跨项目内容用 `## 项目关联` + `### <项目名>` 嵌套,**不要把项目名写进 H2**
4. **H1 = 实体展示名**,不要装饰后缀(详见 §5.1)
5. **YAML 数组用 inline flow form** `[a, b]`,不用 block list(详见 §5.2)
6. 长尾自定义 H2 可以加,但 Phase 3 开 strict 之后会被拒;尽量约束在 SPEC 内

**如果发现 SPEC 不覆盖你的需求,先 PR SPEC,不要私自扩展字段或 H2。**

## 9. 后续工作清单

**已完成**(✓):

- ✓ `schemas/primitives.py` 实现(Pydantic V2)
- ✓ `schemas/{author,book,chapter,paper,body,registry,__init__}.py` 实现
- ✓ `scripts/typecheck/typecheck.py` —— 校验器
- ✓ `scripts/typecheck/autofix_mechanical.py` —— Layer 1 机械修复
- ✓ `bin/quasi-typecheck` + `bin/quasi-autofix-mechanical` —— shim 命令
- ✓ `agents/typecheck-agent.md` —— 自包含 agent
- ✓ 端到端测试:4 个不同 type 的文件全部 clean

**待办**(按依赖排序):

1. **Layer 1 全 vault 机械 sweep**(autofix --write,~分钟,零 LLM 成本)
2. **Layer 2/3 LLM agent 批量 sweep**(分批,前几批小样本 review)
3. **132 个 unknown_type / no_frontmatter 文件单独 review**
4. **`quasi:*` 其他 agent 模板更新**(analyze / overview / profile),让新生成的输出已符合 SPEC
5. **reader UI 适配新 type 名**(`TYPES` 常量) + **rating 数字渲染 ★**
6. **plugin 0.10.0 发布流程**

---

**冻结条件**:用户审阅本 SPEC,确认 5 个 type 形状、primitives 选择、删除字段清单。冻结后这份文档为后续所有工作的事实标准;之后修改需走"先改 SPEC、再改实现"的顺序。

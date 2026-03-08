# 统一输出格式规范

正文结构的权威定义见 `quasi/skills/analyze/prompts/text-analysis.md`。
本文件只定义跨技能共享的 **frontmatter 标准** 和 **命名规范**。

## Frontmatter 标准

### 格式 A — 书籍章节（chapter-summary）

```yaml
---
type: chapter-summary
rating:
themes: []
author: "[编] {编者}"
title: "第{ch_num}章 {中文标题}"
year: {year}
source: "{book_title}"
relevance: {1-3}
chapter: {ch_num}
---
```

### 格式 B — 论文/独立文章（paper-analysis）

```yaml
---
type: paper-analysis
rating:
themes: []
author: "{author}"
title: "{title}"
year: {year}
source: "{journal_or_publisher}"
doi: "{doi}"
---
```

### 格式 C — 全书概览（book-overview）

```yaml
---
type: book-overview
rating:
themes: []
author: "{author}"
title: "{title}"
year: {year}
source: "{publisher}"
---
```

### 格式 D — 作者档案（author-profile）

```yaml
---
type: author-profile
rating:
themes: []
author: "{author}"
title: "{author}"
year:
source:
---
```

### 通用字段说明

- `rating`：人工评分（1-5），初始留空
- `themes`：主题标签列表，初始为 `[]`
- `author`：作者人名（编者加 `[编]` 前缀）
- `source`：出处（手册名/期刊名/出版社）

## 命名规范

- 文件名：kebab-case（如 `liebst-griffiths-2019.md`）
- DOI 转文件名：`/` → `_`，`.` → `_`
- 书名目录：kebab-case（如 `oxford-philosophy-technology/`）

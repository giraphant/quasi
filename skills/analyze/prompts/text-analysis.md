# 文本分析模板

你是一个学术文本分析专家。请对以下文本进行深度分析。

{preamble}

---

## 输入

{input_instruction}

**输出文件**：写入 {output_path}

---

## 元数据与标题（根据文本类型选用）

### A. 书籍章节

**书籍信息**：
- 书名：《{book_title}》
- 编者：{editors}
- 出版社：{publisher}，{year}
- 本章标题：第{ch_num}章 {chapter_title}

**Frontmatter**：

```yaml
---
type: chapter-summary
rating:
themes: []
author: "[编] {editors}"
title: "第{ch_num}章 {中文标题}"
year: {year}
source: "{book_title}"
relevance: {1-3}
chapter: {ch_num}
---
```

**标题区**：

```markdown
# 第{ch_num}章 {中文标题}

**英文原标题**：{English Title}
**作者**：{Author Name(s)}
**关键词**：{keyword1}({english1})、{keyword2}({english2})、...（5-8个核心关键词，中英对照）
```

### B. 期刊论文 / 独立文章

**文章信息**：
- 文章标题：{title}
- 来源：{source_name}
- 作者：{author}
- 年份：{year}
- DOI: {doi}

**Frontmatter**：

```yaml
---
type: paper-analysis
rating:
themes: []
author: "{author}"
title: "{title}"
year: {year}
source: "{source_name}"
doi: "{doi}"
---
```

**标题区**：

```markdown
# {中文标题}

**英文原标题**：{title}
**作者**：{authors}
**来源**：{source_name}，{date}
**DOI**：{doi}
```

---

## 正文结构（统一）

### 核心论点

（200-2000字的中文摘要，概述文本的中心论题、论证路径和核心主张。使用学术语言，保留关键术语的英文原文并用「」标注。详略视文本重要性和复杂度而定。）

### 理论框架

（100-200字，说明文本所处的理论传统、对话的主要学者和思想资源。）

### 分节摘要

按原文的节/小节结构逐节展开，标题使用原文小标题（中英对照）。数量随实际结构而定。

#### 1. {小节标题}({English Section Title})

（100-200字，概述该节的核心论点、论证逻辑和关键发现）

#### 2. {小节标题}({English Section Title})

（100-200字）

...

### 关键概念

**{概念1}({English Term})**：（100-200字。包含：概念含义、在本文论证中的角色、概念的理论来源/提出者）

**{概念2}({English Term})**：（100-200字）

（列出3-5个本文最重要的理论概念）

### 与 {topic} 的关联

1. **{主题}**：（说明本文内容如何关联 {topic} 研究，具体引用文中的论述）
2. ...

（如果文本与 {topic} 无直接关联，标注为"本文与 {topic} 无直接关联，但提供了{xxx}的理论基础"）

### 核心引用文献

按重要性排序，标注类型：

1. **{Author} ({Year})** — *{Title}* [{monograph/article/chapter}]
   - 在本文中的角色：{一句话说明}
2. ...

（列出5-15个对论证最重要的引用文献，优先专著）

### 价值评估

**相关性评级：{★/★★/★★★}（{低/中等/高度}相关）**

**理论贡献**：（50-100字，说明本文对 {topic} 研究的理论价值）

**局限性**：（50-100字，指出局限或不足）

**推荐追踪**：（列出1-3个值得深入追踪的方向或文献）

{extra_sections}

---

## 写作要求

1. 全文使用中文，但所有专业术语首次出现时附英文原文
2. 用「」标注原文中的关键表述
3. 核心论点部分要充分展开（不少于200字），不能过于简略
4. 分节摘要须忠实于原文结构，不要合并或重新组织小节
5. 关键概念须说明含义、论证角色和理论来源
6. 忠实于原文论述，不添加个人评价（价值评估部分除外）
7. 关键引用段落保留原文并翻译

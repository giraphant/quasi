---
name: quasi:analyze
type: template
description: >
  Analyzes a single text (book chapter or paper) using parameterized prompt
  templates. Produces structured markdown analysis. Use when processing
  individual chapters or papers, or when another composite skill needs analysis.
---

> **路径约定**：本技能所有 `prompts/X.md` 路径相对于系统提供的 base directory。读取时拼接为 `{base_directory}/prompts/X.md`。

# Analyze — 单文本分析

对单个文本（书籍章节或论文）进行结构化分析，输出统一格式的 .md 文件。

## 接口

```
名称：analyze
输入：一个文本文件（.txt 章节 或 .pdf 论文）
参数：
  - topic: 分析聚焦的主题（如"技术与具身化"）
  - template: prompt 模板（text-analysis，统一模板）
  - output_path: 输出文件路径
  - language: 输出语言（默认 zh-CN）
  - extra: 附加段落模板（如 snowball-extra）
  - [模板特定参数]: book_title, editors, ch_num, doi 等
输出：结构化 .md 分析文件（统一 frontmatter + 标准段落结构）
```

## Prompt 模板

| 模板 | 适用场景 | 文件 |
|------|----------|------|
| `text-analysis` | 书籍章节 / 期刊论文 / snowball 论文（统一模板） | `prompts/text-analysis.md` |
| `snowball-extra` | 追加到 text-analysis 末尾，提取引用 | `prompts/snowball-extra.md` |

`text-analysis.md` 包含 `{preamble}` 占位符，用于注入项目特定的分析立场（如"人文/理论类"）。各项目在 CLAUDE.md 中定义 preamble 值。模板内定义了两套元数据格式（A=书籍章节, B=期刊论文），调用方根据文本类型选用。

## 标准调用方式

本技能通过 Claude 子代理执行（不是 CLI 脚本）。Workflow 技能（process-book / process-journal / citation-snowball）统一使用以下 Task tool 模式：

```
Task tool:
  subagent_type: "general-purpose"
  model: "opus"
  run_in_background: true
  prompt: |
    读取 prompts/text-analysis.md 模板，
    选用「{A 或 B}」元数据格式，根据模板中的占位符填入相应值，
    生成分析写入 {output_path}。
    值来源：
    - preamble/topic: 从 CLAUDE.md §1.3 获取
    - 元数据: 从上游提供的上下文获取（manifest、scan.md、章节文本等）
    - input_instruction: [读取路径或摘要文本]
    - extra_sections: [空 或 snowball-extra.md 内容]

    text-analysis.md 是参数定义的唯一来源。
    子代理读取模板后自行识别所有占位符并填入。
```

### 变体

| 场景 | 元数据格式 | type 值 | extra_sections |
|------|-----------|---------|----------------|
| 书籍章节 | A | chapter-summary | "" |
| 期刊论文 | B | paper-analysis | "" |
| Snowball 论文 | B | paper-analysis | snowball-extra.md |

## 占位符说明

| 占位符 | 含义 | 示例 |
|--------|------|------|
| `{preamble}` | 项目特定的分析立场（从 CLAUDE.md 获取） | "这是人文/理论类文本…" |
| `{topic}` | 分析聚焦的研究主题（从 CLAUDE.md 获取） | "技术、AI、媒介与具身化" |
| `{input_instruction}` | 输入指令 | "读取 xxx.txt" / "基于以下摘要分析：…" |
| `{output_path}` | 输出文件路径 | `vault/handbooks/xxx/ch01-title.md` |
| `{book_title}` | 书名（A类） | "Oxford Handbook of..." |
| `{title}` | 论文标题（B类） | "Space syntax theory..." |
| `{author}` | 作者 | "Liebst, Griffiths" |
| `{year}` | 出版年份 | 2019 |
| `{source_name}` | 期刊/出版社名（B类） | "Theory, Culture & Society" |
| `{doi}` | DOI（B类） | "10.1177/..." |
| `{extra_sections}` | 附加段落（如 snowball 引用提取） | snowball-extra.md 内容 |

## 核心原则

1. **每个子代理只处理1个文本**（1章或1篇论文）
2. **所有子代理必须 `model: "opus"`**
3. **模板是骨架，参数是灵魂**：换项目只需传入不同 `{preamble}` 和 `{topic}`
4. **统一输出格式**：所有分析结果遵循 `shared/output-format.md` 规范
5. **项目立场外置**：分析立场（如"人文/理论类"）由项目 CLAUDE.md 定义，不硬编码在模板中

## 技能依赖

- 上游：**extract** 产出章节文本 → analyze
- 下游：analyze 产出 .md → **synthesize**（综合/KB更新）
- 调用方：**process-book** / **process-journal** / **citation-snowball**

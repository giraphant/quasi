---
name: quasi:synthesize
type: tool
description: >
  Generates cross-text synthesis reports, aggregated reference lists, and
  knowledge base updates from multiple analysis files. Use after completing
  analysis of multiple texts, or when the user says "综合", "synthesize",
  "生成报告", "更新知识库", "update KB".
---

# Synthesize — 综合报告 + 知识库更新

从多篇分析结果生成跨文本综合报告、参考文献聚合列表，以及知识库更新。

## 接口

```
名称：synthesize
输入：一个目录，包含多个 analyze 产出的 .md 文件
参数：
  - topic: 综合主题
  - output_path: 综合报告输出路径
  - reading_list_path: 阅读列表输出路径（可选）
  - report_type: synthesis / overview / kb-update（默认 synthesis）
  - kb_path: 知识库路径（kb-update 模式，默认 knowledge-base.md）
  - source_name: 来源名称（kb-update 模式）
  - dimensions: 关注维度（kb-update 模式）
输出：
  - 综合报告 .md
  - 推荐阅读列表 .md（可选）
  - 更新后的知识库（kb-update 模式）
```

## 使用方法

### 1. 参考文献聚合

```bash
python3 quasi/skills/synthesize/scripts/aggregate_refs.py \
    vault/journals/{topic-slug}/ \
    --output vault/journals/{topic-slug}-reading-list.md
```

### 2. 综合报告（子代理）

```
Task tool:
  subagent_type: "general-purpose"
  model: "opus"
  prompt: |
    读取 {analysis_dir}/ 下所有分析文件，生成综合报告。
    按 prompts/synthesis.md 模板输出。
    主题：{topic}
    输出：{output_path}
```

### 3. 书籍概览（子代理）

```
Task tool:
  subagent_type: "general-purpose"
  model: "opus"
  prompt: |
    读取 vault/handbooks/{book-name}/ 下所有 ch*.md，生成概览。
    输出：vault/handbooks/{book-name}/00-overview.md
    包含：全书主题概述、章节主题归纳、核心概念表、关联度评估、理论家索引。
```

### 4. 知识库更新（子代理）

将分析结果整合到持久知识库。通用化设计，不限于书/期刊。

```
Task tool:
  subagent_type: "general-purpose"
  model: "opus"
  prompt: |
    读取 quasi/skills/synthesize/prompts/kb-update.md 模板，填入以下参数：
    - topic: "{topic}"
    - source_name: "{来源名称}"
    - analysis_dir: "{分析目录}"
    - kb_path: "knowledge-base.md"
    - dimensions: "{关注维度列表}"

    按模板要求提取关键信息并整合到知识库。
```

**参数说明**：

| 参数 | 含义 | 示例 |
|------|------|------|
| `{topic}` | 研究主题 | "技术、AI、媒介与具身化" |
| `{source_name}` | 来源名称 | "Oxford Material Culture Studies" |
| `{analysis_dir}` | 分析结果目录 | `vault/handbooks/oxford-material-culture/` |
| `{kb_path}` | 知识库路径 | `knowledge-base.md` |
| `{dimensions}` | 关注维度 | "理论框架、核心概念、可引用段落" |

**知识库结构**（参见 `prompts/kb-update.md` 模板）：
- 一、理论框架与核心概念
- 二、关键议题
- 三、核心文献追踪
- 四、可引用段落
- 五、更新日志

**通用化要点**：
1. 不绑定特定主题：`{topic}` 和 `{dimensions}` 由调用者传入
2. 不限来源类型：书籍摘要、期刊分析、snowball 分析都可以
3. 累积性：每次添加新内容，不覆盖旧内容
4. 标注来源：每条信息标注来自哪个分析

## 脚本

| 脚本 | 功能 | 来源 |
|------|------|------|
| `scripts/aggregate_refs.py` | 引用文献交叉聚合 | 迁移自 journal-processor |

## 技能依赖

- 上游：**analyze** 产出多个 .md
- 下游：综合报告 / KB 更新
- 调用方：**process-book** / **process-journal** / **citation-snowball**

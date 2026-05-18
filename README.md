# quasi

> 仿佛读过、仿佛想过、仿佛写过。

Claude Code 知识库插件。quasi 的维护逻辑是: 上层只看
`skills → agents → bin/quasi-*`,底层实现收束在少数大入口脚本里,方便
agent 一次读完整条能力链。

## 层级

```text
skills/          # 用户工作流编排
agents/          # LLM 代理壳,只调用 quasi-* CLI
bin/             # 稳定外部入口
scripts/         # deterministic 能力入口和实现
scripts/schemas/ # vault 领域规范(Pydantic + body schema)
core/            # 极小运行时地基(path/frontmatter/json/module loading)
```

`scripts/schemas/` 不是 agent-facing API。agent 只依赖 CLI; schema 只给
typecheck、audit、citation biblio、migration 等 deterministic scripts 使用。

Skill 写作 schema 的维护者约定见 `docs/SKILL_ORCHESTRATION.md`:skill 主进程
owns state,agent 只做专业工种,每个 phase 必须有明确的 skip/failure/human gate。
active skill 正文只保留运行时需要的信息。

## 当前入口

### Skills

| Skill | 功能 |
|---|---|
| `process-book` | 自动获取图书,提取章节,逐章分析并生成全书综述 |
| `process-paper` | 搜索/下载/分析单篇论文 |
| `process-author` | 获取代表作品并生成学者档案 |
| `process-topic` | 主题语料处理 |
| `wrap-up` | draft 校对 + 引文审查 + references.bib |

`process-journal` 当前已归档到 `deprecated/skills/`,等待 journal acquisition 重新设计。

### Agents

| Agent | 职责 |
|---|---|
| `search-agent` | 将研究意图转成 `quasi-search book|paper` 查询 |
| `download-agent` | 文件获取、候选判断、接受入库 |
| `extract-agent` | EPUB/PDF/OCR/章节切分编排 |
| `analyse-agent` | 论文/章节分析 |
| `synthesis-agent` | book/author/topic 综合报告 |
| `audit-agent` | vault consistency 检查和可修复项处理 |
| `proofread-agent` | draft 局部校对 |
| `citecheck-agent` | 引文 context-fit 审查 |
| `translate-agent` | 双语翻译 |

### CLI

```bash
quasi-search book|paper ...
quasi-download book candidates|fetch ...
quasi-download paper fetch ...
quasi-download accept ...
quasi-extract epub|ocr|split ...
quasi-audit --path ...
quasi-helpers proofread prepare|cleanup ...
quasi-helpers citation parse|biblio|resolve|emit-bib ...
quasi-helpers localise scan|write ...
quasi-translate ...
```

旧 `quasi-citation` 和 `quasi-proofread` bin 已移除;新流程走
`quasi-helpers` 和 `quasi-audit`。

## 文库结构

```text
vault/
  books/{slug}/
  papers/{slug}.md
  authors/{slug}.md
  drafts/
sources/
  {slug}.{epub,pdf}
.quasi/
  audit/
  citation/
  localise/
  proofread/
  temp/
```

## 凭据

通过 `/plugin` → Configure 填入:

| 服务 | 配置字段 |
|---|---|
| Anna's Archive | `anna_donator_key`, `anna_mirrors` |
| CookieCloud / EZProxy | `cookiecloud_*` |
| Immersive Translate | `immersive_auth_key` |
| Google Scholar proxy | `google_scholar_proxy_url` |

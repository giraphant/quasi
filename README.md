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
| `process-material` | 统一采集→分析编排图:book(章节分析+全书综述)/ paper(单篇分析,可选中译)/ author(学者档案)/ topic(主题综述+阅读清单) |
| `process-talk` | 录制转写(多引擎集成)+ 结构化摘要入库 `vault/talks/` |
| `wrap-up` | draft 校对 + 引文审查 + references.bib |

`process-journal` 当前已归档到 `deprecated/skills/`,等待 journal acquisition 重新设计。

### Agents

| Agent | 职责 |
|---|---|
| `search-agent` | 将研究意图转成 `quasi-search book|paper` 查询 |
| `steer-agent` | topic 掌舵:维护 02-outline 研究大纲,返回子问题定向候选 |
| `webcard-agent` | topic 圈外证据卡:一条 web 任务 → 一张核验过的 cards/*.md |
| `download-agent` | 文件获取、候选判断、接受入库 |
| `extract-agent` | EPUB/PDF/OCR/章节切分编排 |
| `analyse-agent` | 论文/章节/讲座转写分析 |
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
quasi-transcribe run|classify|silent ...
quasi-audit --path ...
quasi-helpers proofread prepare|cleanup ...
quasi-helpers citation parse|biblio|resolve|review-cards|emit-bib ...
quasi-helpers localise scan|write ...
quasi-doctor [--json] [--sync] [--profile ...]
quasi-translate SLUG [--backend immersive|pdf2zh] ...
```

`quasi-extract ocr` 默认走 **DS OCR2**（DeepSeek-OCR-2，mlx-vlm，Apple
Silicon 本地）。需要时设 `QUASI_DSOCR2_MODEL` 指向本地 BF16 模型目录，
缺 MLX/模型时自动回退 tesseract（`--engine tesseract` 可强制）。

### PDF 翻译

`quasi-translate` 有两个后端，输出契约相同：
`processing/translations/{slug}-{lang}.pdf`，原文/译文页交替并保留书签。

| 后端 | Configure options | 本地前置条件 |
|---|---|---|
| `immersive`（默认） | `immersive_auth_key` | 无 |
| `pdf2zh` | `translate_base_url`, `translate_api_key`, `translate_model` | `uvx`（首次运行自动下载 `pdf2zh-next`） |

在 `/plugin` → Configure options 把 `translate_backend` 设成 `immersive` 或
`pdf2zh`；未设置时明确默认 `immersive`。`translate_base_url` 可以只填服务根地址：
例如 `https://api.deepseek.com` 会自动变成 `https://api.deepseek.com/v1`。
如果已经填写路径，quasi 会原样保留，因为兼容端点也可能使用
`/api/paas/v4`、`/v1beta/openai` 或 `/openai/v1`。不要包含
`/chat/completions`。

普通 born-digital PDF 走 pdf2zh **不需要** DS OCR2 或 MinerU。只有 coverage
闸发现源文字层过碎、报 `Under-translated` 时，translate agent 才会执行一次
`quasi-extract ocr --layout` 后重试：DS OCR2 需要 Apple Silicon，MinerU2.5-Pro
只负责段落分组；两者由 `uvx`/Hugging Face 首次下载，可分别用
`QUASI_DSOCR2_MODEL`、`QUASI_MINERU_MODEL` 指向本地模型。DS OCR2 不可用会
fail-soft 到 tesseract，MinerU 不可用会退回逐行文本层，因此扫描书的恢复质量会下降。

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
| Anna's Archive | `anna_donator_key` |
| CookieCloud / EZProxy | `cookiecloud_server`, `cookiecloud_uuid`, `cookiecloud_password`, `cookiecloud_ezproxy_domain`, `cookiecloud_ezproxy_base_url` |
| PDF 翻译后端 | `translate_backend`（`immersive` 或 `pdf2zh`） |
| Immersive Translate | `immersive_auth_key` |
| pdf2zh OpenAI-compatible endpoint | `translate_base_url`, `translate_api_key`, `translate_model` |
| Kagi | `kagi_session_token` |
| Google Scholar proxy | `google_scholar_proxy_url` |

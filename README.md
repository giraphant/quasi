# quasi

> 仿佛读过、仿佛想过、仿佛写过。

Claude Code 的知识库插件。quasi 的维护逻辑是: 上层只看
`skills → workflows → agents → bin/quasi-*`,底层实现收束在少数大入口脚本里,方便
agent 一次读完整条能力链。

## 层级

```text
skills/          # 用户入口、状态与人工卡点
workflows/       # 构建生成、供宿主加载的单文件入口
agents/          # LLM 代理壳,只调用 quasi-* CLI
bin/             # 稳定外部入口
scripts/         # deterministic 能力入口、构建源码和实现
  workflows/     # run-stage 源码、descriptor rows 与 schema projections
scripts/schemas/ # vault 领域规范(Pydantic + body schema)
core/            # 极小运行时地基(path/frontmatter/json/module loading)
```

`scripts/schemas/` 是 vault 产物的唯一结构事实源。Agent 不直接 import Python；构建器把
producer/search 所需的 canonical projection 注入 Workflow，typecheck、audit 和 migration
则直接消费同一 registry。历史 aliases 只出现在 audit/migration 投影中。

Skill 写作 schema 的维护者约定见 `docs/SKILL_ORCHESTRATION.md`：Skill 驱动状态与阶段，
run-stage 负责一次 schema-enforced 调用，Agent 负责专业判断，CLI 负责确定性 I/O。Active skill 正文只
保留运行时需要的信息。

Claude Workflow 的源码只在 `scripts/workflows/**/*.mjs` 维护；运行
`npm run build:workflows` 会确定性生成并提交
`workflows/run-stage.mjs`，不要直接修改生成文件。Skill 通过 `quasi-status` 观察磁盘后选择
`Recall → Search → Acquire → Prepare → Analyse → Synthesise → Audit` 中适用的一步；每次
Workflow 只注入 goal、capabilities、exact refs 和 receipt schema，调用一个 goal-owning
specialist，并原样返回 typed terminal。仓库没有自运行材料图。
根目录 `settings.json` 还为 quasi 子代理提供紧凑状态行，其他子代理保持 Claude Code
默认显示。

### Artifact Schema 的维护边界

产物结构只有一个来源：

1. `scripts/schemas/{type}.py` 定义 frontmatter 字段、类型和字段语义；
2. `scripts/schemas/body.py` 定义路径、identity fields、H1、metadata 行、H2 顺序、
   block kind、表格列和 section 语义；
3. `agents/*.md` 只保存 worker 的稳定认识论、读写流程和通用 receipt 协议；
4. `scripts/workflows/operations/*.mjs` 只装配 exact refs、动态 frontmatter seed、
   operation request/receipt 和 schema projection，不再拥有产物模板。

修改 Paper、Chapter、Book overview 或 Talk 的结构时编辑 `scripts/schemas/`，然后运行
`npm run build:workflows`。构建器会更新
`scripts/workflows/artifact-contracts/generated.mjs` 和
`workflows/run-stage.mjs`；两者都是生成物，禁止手改。
acquisition 等非产物结构的行为，由所属 `scripts/workflows/operations/*.mjs`
以结构化 policy 注入，不另建 prose prompt pack。`npm run check:workflows`
检查 Schema、projection、operation 与最终 bundle 的一致性。

## 当前入口

### Skills

| Skill | 功能 |
|---|---|
| `collect-material` | skill-driven 采集→分析:book / paper / author / talk / PDF translation |
| `research-topic` | topic 界定与研究循环:vault 召回、滚雪球、证据卡、研究大纲与主题综合 |
| `finalise-draft` | draft 校对 + 引文审查 + references.bib |

`process-journal` 当前已归档到 `deprecated/skills/`,等待 journal acquisition 重新设计。

### Agents

| Agent | 职责 |
|---|---|
| `metadata-agent` | 调查一份 Book/Paper 请求并核定 canonical 书目身份与本地 owner |
| `discovery-agent` | 为 Author、Topic demand 或缺失引文发现 bounded candidates |
| `localisation-agent` | 为一份 canonical Book 核验中文版本关系 |
| `steer-agent` | topic 掌舵:维护 02-outline 研究大纲,返回子问题定向候选 |
| `webcard-agent` | topic 圈外证据卡:一条 web 任务 → 一张核验过的 cards/*.md |
| `download-agent` | 文件获取、候选判断、接受入库 |
| `extract-agent` | 完成 Paper/Book Prepare：可读文本、OCR 恢复与可靠章节 generation |
| `analyse-agent` | 论文/章节/讲座转写分析 |
| `synthesis-agent` | book/author/topic 综合报告 |
| `audit-agent` | vault consistency 检查和可修复项处理 |
| `proofread-agent` | draft 局部校对 |
| `citecheck-agent` | 引文 context-fit 审查 |
| `transcribe-agent` | 完成 Talk Prepare：媒体、transcript generation、语义分类，以及 dead/empty 的 silent canonical |
| `translate-agent` | 完成 Translation Prepare：source、翻译 generation、恢复与验证 |

### CLI

```bash
quasi-search book|paper ...
quasi-download book candidates|fetch ...
quasi-download paper fetch|diagnose ...
quasi-download accept ...
quasi-extract epub|text|ocr|split ...
quasi-transcribe run|classify|silent ...
quasi-audit --path ...
quasi-status --kind paper|book|talk --slug SLUG --json [--identity]
quasi-status --scan --json
quasi-helpers proofread prepare|cleanup ...
quasi-helpers citation parse|biblio|resolve|review-cards|emit-bib ...
quasi-helpers localise scan|write ...
quasi-helpers vault resolve --items-json|--items-file ...
quasi-doctor [--json] [--sync] [--profile ...]
quasi-translate SLUG [--backend immersive|pdf2zh] ...
```

quasi targets Claude Code only; retired Pi and Codex host adapters are recoverable from git history.
只给题名的单本/论文请求会先由可见 `metadata-agent` 核定 DOI/ISBN、作者顺序、年份和
canonical slug;主线程不会自行 WebSearch 猜 metadata。

`quasi-extract ocr` 默认走 **DS OCR2**（DeepSeek-OCR-2，mlx-vlm，Apple
Silicon 本地）。需要时设 `QUASI_DSOCR2_MODEL` 指向本地 BF16 模型目录，
缺 MLX/模型时自动回退 tesseract（`--engine tesseract` 可强制）。

### PDF 翻译

`quasi-translate` 有两个后端，输出契约相同：
`processing/translations/{slug}-{lang}.pdf`，原文/译文页交替并保留书签。

| 后端 | Configure options | 本地前置条件 |
|---|---| --- |
| `immersive`（默认） | `immersive_auth_key` | 无 |
| `pdf2zh` | `translate_base_url`, `translate_api_key`, `translate_model` | `uvx`（首次运行自动下载 `pdf2zh-next`） |

在 `/plugin` → Configure options 把 `translate_backend` 设成 `immersive` 或
`pdf2zh`；未设置时明确默认 `immersive`。`translate_base_url` 可以只填服务根地址：
例如 `https://api.deepseek.com` 会自动变成 `https://api.deepseek.com/v1`。
如果已经填写路径，quasi 会原样保留，因为兼容端点也可能使用
`/api/paas/v4`、`/v1beta/openai` 或 `/openai/v1`。不要包含
`/chat/completions`。

普通 born-digital PDF 走 pdf2zh **不需要** DS OCR2 或 MinerU。Translate specialist
会结合 coverage 与源文字层证据判断是否使用 caller-scoped
`quasi-extract ocr --layout` recovery：DS OCR2 需要 Apple Silicon，MinerU2.5-Pro
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

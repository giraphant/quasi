# quasi

> 仿佛读过、仿佛想过、仿佛写过。

Claude Code / Codex / Pi 共用的知识库插件。quasi 的维护逻辑是: 上层只看
`skills → workflows → agents → bin/quasi-*`,底层实现收束在少数大入口脚本里,方便
agent 一次读完整条能力链。

## 层级

```text
skills/          # 用户入口、状态与人工卡点
workflows/       # 构建生成、供宿主加载的单文件入口
agents/          # LLM 代理壳,只调用 quasi-* CLI
bin/             # 稳定外部入口
scripts/         # deterministic 能力入口、构建源码和实现
  workflows/     # 模块化 Graph 源码与构建生成的 schema projections
scripts/schemas/ # vault 领域规范(Pydantic + body schema)
core/            # 极小运行时地基(path/frontmatter/json/module loading)
```

`scripts/schemas/` 是 vault 产物的唯一结构事实源。Agent 不直接 import Python；构建器把
producer/search 所需的 canonical projection 注入 Workflow，typecheck、audit 和 migration
则直接消费同一 registry。历史 aliases 只出现在 audit/migration 投影中。

Skill 写作 schema 的维护者约定见 `docs/SKILL_ORCHESTRATION.md`:skill 主进程
owns state,agent 只做专业工种,每个 phase 必须有明确的 skip/failure/human gate。
active skill 正文只保留运行时需要的信息。

Claude Workflow 的源码只在 `scripts/workflows/**/*.mjs` 维护；运行
`npm run build:workflows` 会确定性生成并提交
`workflows/process-material.mjs`，不要直接修改生成文件。当前 Paper 是第一条
Operation vertical slice：所有来源先标准化成 text，再由只读 Agent 判断语义可读性，
必要时沿图进入一次 OCR 恢复，最后由同一个 `analyse-agent` 接收 Paper artifact contract。
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
`workflows/process-material.mjs`；两者都是生成物，禁止手改。
acquisition 等非产物结构的行为，由所属 `scripts/workflows/operations/*.mjs`
以结构化 policy 注入，不另建 prose prompt pack。`npm run check:workflows`
检查 Schema、projection、operation 与最终 bundle 的一致性。

## 当前入口

### Skills

| Skill | 功能 |
|---|---|
| `process-material` | 统一采集→分析编排图:book / paper / author / talk / PDF translation |
| `organise-topic` | topic 独立组织循环:vault 召回、滚雪球、证据卡、研究大纲与主题综合 |
| `finalise-draft` | draft 校对 + 引文审查 + references.bib |

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
quasi-extract epub|text|ocr|split ...
quasi-transcribe run|classify|silent ...
quasi-audit --path ...
quasi-helpers proofread prepare|cleanup ...
quasi-helpers citation parse|biblio|resolve|review-cards|emit-bib ...
quasi-helpers localise scan|write ...
quasi-doctor [--json] [--sync] [--profile ...]
quasi-translate SLUG [--backend immersive|pdf2zh] ...
quasi-pi-runner --script PATH --args-file JSON [--cwd PROJECT] ...
quasi-codex-agents (--project PATH|--user) [--check] [--json]
quasi-codex-driver --script PATH --args-file JSON [--cwd PROJECT] ...
quasi-codex-runner --script PATH --args-file JSON [--cwd PROJECT] ...
```

`quasi-pi-runner` 是 Pi 下的最小 `process-material` 图执行器:直接用 Pi 官方 SDK
加载 `agents/*.md`,只实现现有图使用的 `agent` / `parallel` / `phase` / `log` /
`args`;Claude Code 仍走原 Workflow 工具。

Codex GUI 默认走 `quasi-codex-driver`:driver 只发带临时 `request_path` /
`receipt_path` 的短 JSONL worker 请求,完整合同由当前 thread 的原生 subagent
自行读取,完整回执也经文件返回,所以长 prompt / result 都不会被终端截断;并行分支和
agent 状态则在 GUI 可见。
Codex 插件当前不会从插件包直接注册 `agents/*.md`;运行
`quasi-codex-agents --project /path/to/vault` 可把这些唯一源码生成成该项目的
`.codex/agents/quasi_*.toml` 原生角色（`--user` 则安装到用户级）。driver 会优先请求
这些角色,未安装或当前宿主没有 role selector 时仍回退通用 worker。同步后需开启新的
Codex thread 才会加载新角色。
`quasi-codex-runner` 用独立 `codex exec` worker,保留作 headless / CI fallback。
只给题名的单本/论文请求会先由可见 `search-agent` 核定 DOI/ISBN、作者顺序、年份和
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

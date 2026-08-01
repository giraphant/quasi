# quasi

> 仿佛读过、仿佛想过、仿佛写过。

Claude Code 的学术阅读插件:用自然语言把书、论文、讲座和研究主题收进一个本地
vault——检索元数据、获取全文、抽取成可读文本、逐章分析、跨材料综合,并支持
PDF 翻译、讲座转写和草稿定稿。

## 功能

装好插件后直接对 Claude Code 说话即可,三个入口按意图自动路由:

| Skill | 用途 |
|---|---|
| `collect-material` | 收集并分析一本书 / 一篇论文 / 一位作者 / 一场讲座;处理已有 PDF;PDF 翻译 |
| `research-topic` | 界定一个研究主题并迭代研究:vault 召回、文献发现、网络证据卡、研究大纲与综合 |
| `finalise-draft` | 草稿定稿:逐节校对、引文语境审查、生成 references.bib |

例如:「帮我收一下 Galison 的 Image and Logic」「把这个 PDF 翻译成中文」
「围绕 tacit knowledge 建一个研究主题」。

单本书/论文只给题名也可以:可见的 metadata 专家会先核定 DOI/ISBN、作者顺序、
年份和 canonical slug,主线程不会自行猜测书目信息。

## 安装

```text
/plugin marketplace add giraphant/quasi
/plugin install quasi@ramu
```

Python 依赖在首次会话时自动装入插件数据目录下的 venv,无需手动安装。

可选的系统级依赖(缺失时对应功能自动降级或跳过):

| 依赖 | 用途 |
|---|---|
| `ffmpeg`、`whisper-cli` | 讲座 / 会议录音转写 |
| `uvx` | pdf2zh 翻译后端、DS OCR2 OCR |
| Apple Silicon + `mlx-vlm` | 本地 OCR(DeepSeek-OCR-2;缺失时回退 tesseract) |
| `mineru-vl-utils` | 扫描书翻译的段落级版面恢复 |

## 配置

在 `/plugin` → quasi → Configure 填入需要的凭据:

| 服务 | 配置字段 |
|---|---|
| Anna's Archive | `anna_donator_key` |
| CookieCloud / EZProxy | `cookiecloud_server`, `cookiecloud_uuid`, `cookiecloud_password`, `cookiecloud_ezproxy_domain`, `cookiecloud_ezproxy_base_url` |
| PDF 翻译后端选择 | `translate_backend`(`immersive`,默认;或 `pdf2zh`) |
| Immersive Translate | `immersive_auth_key` |
| pdf2zh(OpenAI 兼容端点) | `translate_base_url`, `translate_api_key`, `translate_model` |
| Kagi 搜索 | `kagi_session_token` |
| Soniox 转写 | `soniox_api_key` |

PDF 翻译输出为原文/译文页交替、保留书签的双语 PDF。`translate_base_url` 只填
服务根地址即可(如 `https://api.deepseek.com` 自动补 `/v1`);已带路径则原样
保留。不要包含 `/chat/completions`。普通 born-digital PDF 走 pdf2zh 不需要
OCR 依赖;扫描书的恢复质量取决于上表的可选依赖是否可用。

## 数据布局

quasi 把当前工作目录当作项目根,产物落在四个目录:

```text
vault/        # 阅读产物:books/ papers/ authors/ talks/ topics/ drafts/
sources/      # 已接受的源文件
processing/   # 可检查的中间产物:chapters/ translations/ talks/
.quasi/       # 编排状态、缓存、审计输出
```

## 维护

维护者合同见 `CLAUDE.md`;分层架构、agent 与 CLI 细节见
`docs/ARCHITECTURE.md`;OCR / 翻译管线的实测经验见 `docs/PDF_PIPELINE.md`;
版本历史见 `docs/CHANGELOG.md`。

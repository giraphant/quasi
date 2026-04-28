# quasi

> 仿佛读过、仿佛想过、仿佛写过。

Claude Code 插件。把一堆 PDF 变成「我读过了」的底气。

搜、下、拆、读、写，五步流水线。丢进去一本 800 页的 Handbook，出来的是逐章分析和全书综述——你只需要假装这些洞见是自己想出来的。

## 工作流

| 技能 | 流程 |
|------|------|
| `process-book` | PDF/EPUB → 拆章 → 逐章分析 → 全书综述 |
| `process-journal` | 期刊扫描报告 → 批量下载 → 逐篇分析 → 综述 |
| `process-author` | 发现代表作（至多 5 书 + 10 文） → 获取 → 分析 → 学者档案 |
| `citation-snowball` | 种子论文 → 沿引用链逐轮扩展 → 主题语料库 + 综述 |

## Agent

工作流由主进程扁平调度 agent 执行。每个 agent 自包含完整逻辑（含模板、验证、修复），调用时只传参数。

| Agent | 模型 | 职责 |
|-------|------|------|
| `extract-agent` | sonnet | EPUB/PDF → 章节文本（含验证+碎片化自修） |
| `analyze-agent` | opus | 单章/单篇 → 结构化分析（内嵌分析模板） |
| `overview-agent` | opus | 全书概览 |
| `translate-agent` | sonnet | 按 slug 定位本地 PDF → 调用沉浸式翻译 Zotero API → 输出双语/译文 PDF |
| `scan-agent` | opus | 期刊抓取 + 评分（内嵌评分模板） |
| `download-agent` | sonnet | DOI/MD5/批量下载 |
| `discover-agent` | opus | 作者文献发现 |
| `profile-agent` | opus | 作者综合档案 |
| `synthesis-agent` | opus | 综合报告 + 知识库更新 |

## 用法

```bash
/quasi:process-book oxford-handbook-sociology-body
/quasi:process-journal critical-inquiry --threshold 7.0
/quasi:citation-snowball posthuman-embodiment --seed 10.xxxx/xxxxx --topic "后人类具身化与数字技术"
/quasi:process-author donna-haraway
```

## 结构

```
quasi/
├── .claude-plugin/          # 插件清单
├── agents/                  # 自包含执行器（所有逻辑在这里）
│   ├── extract-agent.md     # 提取+验证+修复 (sonnet)
│   ├── analyze-agent.md     # 分析，内嵌模板 (opus)
│   ├── overview-agent.md    # 书籍概览 (opus)
│   ├── scan-agent.md        # 期刊扫描+评分 (opus)
│   ├── download-agent.md    # 下载 (sonnet)
│   ├── discover-agent.md    # 文献发现 (opus)
│   ├── profile-agent.md     # 作者档案 (opus)
│   └── synthesis-agent.md   # 综合报告 (opus)
├── scripts/                 # Python 工具（被 agent 调用）
│   ├── extract/             # process_epub.py, split_chapters.py, ocr_pdf.sh
│   ├── translate/           # immersive_translate.py
│   ├── search/              # search.py
│   ├── download/            # download.py
│   ├── journal/             # fetch_papers.py, generate_scan_report.py
│   └── synthesize/          # aggregate_refs.py
├── config/                  # 凭据配置（gitignored）
├── skills/                  # 工作流编排（只有 4 个入口）
│   ├── process-book/
│   ├── process-journal/
│   ├── process-author/
│   └── citation-snowball/
└── shared/
    └── output-format.md     # Frontmatter 规范
```

## 产出落点（在调用方仓库内）

quasi 写入的目录约定与 bts 仓库结构对齐（合并 monographs+handbooks 后的扁平规范）：

| 类型 | 落点 | 写入者 |
|------|------|--------|
| 书的逐章分析 + 全书综述 | `vault/books/{book-slug}/` | process-book / process-author |
| 论文分析（全库扁平） | `vault/papers/{paper-slug}.md` | process-author Phase 4 |
| 作者档案（单文件） | `vault/authors/{author-slug}.md` | process-author Phase 5 |
| 期刊扫描 + 综述 | `vault/journals/{journal}-scan.md`、`vault/journals/{journal}/` | process-journal |
| 主题语料库（引用滚雪球） | `vault/topics/{topic-slug}/` | citation-snowball |
| 采集状态机（manifest） | `processing/authors/{slug}/manifest.json` | discover-agent |
| 章节提取中间产物 | `processing/chapters/{book-slug}/` | extract-agent |
| 原始 PDF/EPUB | `sources/{book-slug}.{epub,pdf}` | download-agent |
| PDF 翻译中间产物 | `processing/translations/{slug}/` | translate-agent |

slug 统一为 `{author-surname}-{short-title}-{year}`，全库唯一。

## 安装

注册为 Claude Code 自定义 marketplace：

```jsonc
// ~/.claude/plugins/known_marketplaces.json
{
  "ramu-toolkit": {
    "source": { "source": "github", "repo": "giraphant/quasi" },
    "autoUpdate": true
  }
}
```

然后：

```bash
claude plugin add quasi --marketplace ramu-toolkit
```

## 配置

凭据放在**调用 quasi 的研究项目根目录**下的 `config/`（gitignored）。脚本通过当前工作目录（`$PWD`）解析配置——你在哪个项目里启动 claude，凭据就在那个项目的 `config/` 里。**不是放在 quasi 自身安装目录下**，每个研究项目互相独立。

**Anna's Archive** — `config/anna-archive.json`：

```json
{
  "donator_key": "你的key",
  "mirrors": ["https://annas-archive.gl", "https://annas-archive.pk", "https://annas-archive.gd"]
}
```

**EZProxy** — `config/ezproxy.json`：

```json
{
  "cookie": "SESSION_VALUE",
  "cookie_name": "yewnoEzProxy",
  "domain": ".your-institution.idm.oclc.org",
  "login_url": "https://login.your-institution.idm.oclc.org/login?url="
}
```

获取方式：浏览器登录 EZProxy → DevTools → Cookies → 复制。过期极快，过期后脚本自动停。

**Immersive Translate** — `config/immersive-translate.json`：

```json
{
  "auth_key": "你的 Zotero 授权码",
  "api_base_url": "https://api2.immersivetranslate.com/zotero",
  "target_language": "zh-CN",
  "translate_model": "kimi+qwen",
  "enhance_compatibility": false,
  "ocr_workaround": "auto",
  "auto_extract_glossary": false,
  "rich_text_translate": true,
  "primary_font_family": "none",
  "dual_mode": "lort",
  "custom_system_prompt": "",
  "layout_model": "version_3"
}
```

可通过 `translate-agent` 或 `python3 scripts/translate/immersive_translate.py {slug}` 使用。默认输出到 `processing/translations/{slug}/`，包含双语版与译文版 PDF。

如果某个授权码对应的服务区域不同，可按需覆盖 `api_base_url`；其余字段保持不变即可。

**Dokobot**（可选）— Google Scholar 兜底搜索：

```bash
npm install -g @dokobot/cli
dokobot install-bridge
```

需要 Chrome 浏览器 + Dokobot 扩展。仅在 API 搜索结果不足时由 discover-agent 自动调用。不可用时自动跳过，不影响核心功能。

### 分析参数

项目 `CLAUDE.md` 提供分析立场：

```yaml
topic: "你的研究主题"
preamble: "项目特定的分析指令"
```

这些值由 analyze-agent 从 CLAUDE.md §1.3 读取。

## License

Private use.

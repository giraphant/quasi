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

凭据放在项目根目录的 `config/` 下（gitignored）：

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

# quasi

> 仿佛读过、仿佛想过、仿佛写过。

Claude Code 知识库插件，打造完整「氛围阅读」流水线，帮助快速理解特定作者、书籍、刊物甚至脉络。大概可能完全没有作用，但书皮学爱好者自会领悟其间真谛。

## 项目架构

插件组织的核心逻辑是以尽可能扁平的结构来实现复杂任务的自动运作。核心资源包括以下三种：

- skills — 工作流编排
- agents — 自包含代理
- scripts — 脚本工具包

### 技能/工作流

| 技能 | 功能 |
|------|------|
| `process-book` | 自动下载图书，逐章摘要并综述 |
| `process-journal` | 全量扫描期刊，逐篇分析并综述 |
| `process-author` | 获取代表作品，生成该学者档案 |
| `citation-snowball` | 文献滚雪球，快速把握研究脉络 |

### 执行/子代理

按流水线阶段排列:发现 → 获取 → 提取 → 分析 → 综合 → 工具。

| Agent | 模型 | 职责 |
|-------|------|------|
| `discover-agent` | opus | 文献发现 |
| `scan-agent` | opus | 期刊扫描 |
| `download-agent` | sonnet | 文献下载 |
| `extract-agent` | sonnet | 文献提取 |
| `analyze-agent` | opus | 文献分析 |
| `overview-agent` | opus | 全书概览 |
| `profile-agent` | opus | 生成作者档案 |
| `synthesis-agent` | opus | 生成综合报告 |
| `translate-agent` | sonnet | 双语翻译 |
| `setup-agent` | sonnet | 项目配置 |

## 文库结构

插件使用固定结构，Obsidian 等管理器可直接读取 vault 目录，但 Claude Code 需要有项目根目录权限。

```
vault/
├── books/{slug}/                  # 逐章分析 + 全书综述 (process-book / process-author)
├── papers/{slug}.md               # 单篇论文分析 (process-author)
├── authors/{slug}.md              # 学者档案 (process-author)
├── journals/
│   ├── {journal}-scan.md          # 期刊扫描报告
│   └── {journal}/                 # 逐篇分析 + 综述
└── topics/{topic-slug}/           # 主题语料库 (citation-snowball)

processing/
├── authors/{slug}/manifest.json   # 作者采集状态机 (discover-agent)
├── chapters/{slug}/               # 章节提取中间产物 (extract-agent)
└── translations/{slug}-{lang}.pdf # PDF 翻译产物 (translate-agent)

sources/
└── {slug}.{epub,pdf}              # 原始文件 (download-agent)
```

## 安装指南

在 Claude Code 内执行:

```
/plugin marketplace add giraphant/quasi
/plugin install quasi@ramu-toolkit
```

### 可选凭据矩阵

本项目随意组装大量其他服务，调用相关服务需要通过 `/plugin` → Configure 填入凭据。

| 服务 | 解锁能力 | 必要等级 | 配置字段 |
|------|---------|--------|----------------|
| Anna's Archive | 自动下载图书 / AA 搜索 | 推荐 | `anna_donator_key`、`anna_mirrors` |
| CookieCloud (EZProxy) | 自动同步 → 批量下载论文 | 可选 | `cookiecloud_*` 5 字段 |
| Immersive Translate | 生成双语翻译 | 可选 | `immersive_auth_key` |
| Dokobot | Google Scholar 兜底 | 可选 | 无 userConfig，独立 CLI 安装 |

> 装完后可选：在研究项目根目录调用 `setup-agent` 同步标准权限和检查系统依赖（Python / pdftotext / ebook-convert）。

## 版权协议

看过我的论文就随便用随便改，没看过就偷着用偷着改。
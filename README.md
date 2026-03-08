# quasi

> 仿佛读过、仿佛想过、仿佛写过。

Claude Code 插件。把一堆 PDF 变成「我读过了」的底气。

搜、下、拆、读、写，五步流水线。丢进去一本 800 页的 Handbook，出来的是逐章分析和全书综述——你只需要假装这些洞见是自己想出来的。

## 技能一览

### 原子技能——干一件事

| 技能 | 干什么 |
|------|--------|
| `search` | 跨 Google Books / OpenLibrary / OpenAlex / Anna's Archive / Unpaywall / Semantic Scholar / Wayback 搜书搜论文 |
| `download` | 给 MD5 下书，给 DOI 下论文，OA → Wayback 逐级降级，总有一款适合你 |
| `extract` | EPUB/PDF 拆成逐章纯文本，扫描件走 OCR |
| `analyze` | 一章或一篇论文 → 结构化分析 Markdown，含理论贡献、核心论证、引用网络 |
| `synthesize` | 多篇分析 → 跨文本综述 + 参考文献汇总 + 知识库更新 |

### 复合技能——一条龙

| 技能 | 流程 |
|------|------|
| `process-book` | PDF/EPUB → 拆章 → 逐章分析 → 全书综述 |
| `process-journal` | 期刊扫描报告 → 批量下载 → 逐篇分析 → 综述 |
| `process-author` | 发现代表作（至多 5 书 + 10 文） → 获取 → 分析 → 学者档案 |
| `citation-snowball` | 种子论文 → 沿引用链逐轮扩展 → 主题语料库 + 综述 |

复合技能由子代理驱动：主进程只管调度，coordinator 代理在独立上下文里干所有重活。你的 token 预算因此得以幸免。

## 用法

```bash
# 处理一本书
/quasi:process-book oxford-handbook-sociology-body

# 搜一个作者的论文
/quasi:search --mode papers --author "Donna Haraway" --year_from 2000

# 用 DOI 下一篇论文
/quasi:download 10.1177/1357034X09337767

# 从种子论文开始滚雪球
/quasi:citation-snowball posthuman-embodiment --seed 10.xxxx/xxxxx --topic "后人类具身化与数字技术"

# 系统性处理一位学者
/quasi:process-author donna-haraway
```

## 结构

```
quasi/
├── .claude-plugin/          # 插件清单
├── shared/
│   └── output-format.md     # Frontmatter 规范 & 命名约定
└── skills/
    ├── search/              # 搜索（多源聚合）
    ├── download/            # 下载（MD5/DOI/URL）
    ├── extract/             # 拆章（EPUB/PDF/OCR）
    ├── analyze/             # 分析（prompt 模板驱动）
    ├── synthesize/          # 综合（跨文本 + 知识库）
    ├── process-book/        # 书籍全流程
    ├── process-journal/     # 期刊全流程
    ├── process-author/      # 学者全流程
    └── citation-snowball/   # 引用链滚雪球
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

### 凭据

搜和下需要两把钥匙，都不进 git。

**Anna's Archive** — 下书用的 donator key：

```jsonc
// ~/.claude/config/anna-archive.json
{
  "donator_key": "你的key",
  "mirrors": ["https://annas-archive.gl", "https://annas-archive.li"]
}
```

没 key 也能搜，但下不了。AA 有每日下载配额，用完了脚本会自动停。

**EZProxy** — 机构代理下付费论文用的 session cookie：

```jsonc
// skills/download/config/ezproxy.json（或 ~/.claude/config/ezproxy.json）
{
  "cookies": {
    "ezproxy": "SESSION_VALUE_1",
    "yewnoEzProxyn": "SESSION_VALUE_2"
  },
  "domain": ".your-institution.idm.oclc.org",
  "login_url": "https://login.your-institution.idm.oclc.org/login?url="
}
```

获取方式：浏览器登录 EZProxy → DevTools → Application → Cookies → 复制对应域下的 cookie。注意这东西过期极快（几分钟到几小时不等），过期后脚本会自动检测、保存进度、停下来骂你。

论文下载的降级路径：OA → Sci-Hub → EZProxy → Wayback。没有 EZProxy cookie 也能用，只是少了一条路。

### 分析参数

每个项目在自己的 `CLAUDE.md` 里提供分析立场：

```yaml
topic: "你���研究主题"
preamble: >
  项目特定的分析指令
  （比如「这是人文理论文本，不要找数据和样本量」）
```

这些值会注入 `analyze/prompts/text-analysis.md` 里的 `{topic}` 和 `{preamble}` 占位符。不同项目、不同学科立场，同一套流水线。

## License

Private use.

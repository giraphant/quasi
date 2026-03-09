---
name: quasi:search
type: tool
description: >
  Unified search for books (Google Books/OpenLibrary/OpenAlex/Anna's Archive)
  and paper metadata (OpenAlex/Unpaywall/Semantic Scholar/Wayback). Use when
  the user says "搜索", "search", "查找文献", or when another skill needs metadata.
---

# Search — 统一搜索

搜索学术书籍（多源含 AA）和论文元数据（OpenAlex/Unpaywall/S2）。

## 接口

```
名称：search
模式：books | metadata | papers
输入：
  books: 查询词/作者/标题/主题
  metadata: DOI/标题/作者 或 manifest 批量
  papers: 作者名（--author）
参数：
  - source: google/openlibrary/openalex/aa/all（书籍）
  - limit: 每源最大结果数
  - year_from/year_to: 年份范围（书籍，非 AA）
  - year_from: 起始年份（papers）
  - sort: 排序方式（papers，默认 cited_by_count:desc）
  - lang: 语言过滤（AA 专用）
  - format: 文件格式过滤（AA 专用，默认 pdf）
输出：
  books: Markdown 或 JSON 格式的搜索结果
  books(aa): Markdown 含 MD5，可直接传给 download --md5
  metadata: JSON 格式的元数据（含 OA URL、引用数、摘要等）
  papers: Markdown 表格或 JSON（含标题、年份、引用数、DOI、OA 状态）
```

## 使用方法

### 搜索书籍（元数据源）

```bash
# 主题搜索（Google Books + OpenLibrary + OpenAlex）
python3 quasi/skills/search/scripts/search.py books "body studies" --limit 20

# 作者搜索
python3 quasi/skills/search/scripts/search.py books --author "Katherine Hayles" --limit 10

# 限定数据源
python3 quasi/skills/search/scripts/search.py books --title "handbook body" --source google

# 限定年份
python3 quasi/skills/search/scripts/search.py books \
    --subject "digital media" --author "Hansen" --year-from 2000 --limit 15

# JSON 输出
python3 quasi/skills/search/scripts/search.py books "body studies" --json

# 输出到文件
python3 quasi/skills/search/scripts/search.py books "body studies" -o results.md
```

### 搜索书籍（Anna's Archive — 文件搜索）

```bash
# 基础搜索
python3 quasi/skills/search/scripts/search.py books \
    "Durkheim social morphology" --source aa

# 限定语言和格式
python3 quasi/skills/search/scripts/search.py books \
    "Seasonal Variations Eskimo" --source aa --lang en --format epub

# 搜索结果含 MD5 → 传给 download.py --md5 下载
```

### 搜索作者论文（按引用量）

```bash
# 按作者搜索论文，默认按引用量降序
python3 quasi/skills/search/scripts/search.py papers --author "Donna Haraway" --limit 30

# 限定起始年份
python3 quasi/skills/search/scripts/search.py papers --author "Donna Haraway" --year-from 2010

# JSON 输出
python3 quasi/skills/search/scripts/search.py papers --author "Donna Haraway" --limit 10 --json

# 输出到文件
python3 quasi/skills/search/scripts/search.py papers --author "Donna Haraway" -o results.md
```

### 搜索论文元数据

```bash
# 按 DOI 查询
python3 quasi/skills/search/scripts/search.py metadata \
    --doi "10.1080/1600910X.2019.1641121"

# 按标题+作者查询
python3 quasi/skills/search/scripts/search.py metadata \
    --title "Space syntax theory" --author "Liebst"

# 批量查询 manifest 中所有 discovered 论文
python3 quasi/skills/search/scripts/search.py metadata \
    --manifest vault/journals/topic-slug/manifest.json --all

# 单篇更新 manifest
python3 quasi/skills/search/scripts/search.py metadata \
    --doi "10.xxx/yyy" --manifest manifest.json --key "author-2023"
```

## 数据源

### 书籍搜索
| API | 特点 | 限制 | `--source` |
|-----|------|------|------------|
| Google Books | 最全面，含目录预览 | 1000 req/day | `google` |
| OpenLibrary | 完全开放，含版本 | 无限制 | `openlibrary` |
| OpenAlex | 学术图书，含引用数 | 无限制 | `openalex` |
| Anna's Archive | 文件搜索，返回 MD5 | 需 donator key | `aa` |

`--source all` = google + openlibrary + openalex（不含 AA）。AA 需要单独指定。

### 论文元数据
| API | 查询顺序 | 提供内容 |
|-----|----------|----------|
| OpenAlex | 1st | 元数据、OA URL、引用数、摘要 |
| Unpaywall | 2nd | OA URL |
| Semantic Scholar | 3rd | 摘要、OA PDF、引用数 |
| Wayback Machine | 4th | 存档 PDF URL |

## 配置

AA 搜索需要 donator key，存放在 `.claude/config/anna-archive.json`（已 gitignore）：

```json
{
  "donator_key": "YOUR_KEY",
  "mirrors": ["https://annas-archive.gl", "https://annas-archive.li"]
}
```

## 依赖

- 标准库 `urllib`（元数据搜索 + Google/OpenLibrary/OpenAlex）
- `requests` + `beautifulsoup4`（仅 AA 搜索，缺失时优雅降级）

## 技能依赖

- 下游：搜索到 MD5 → **download** 获取 | 搜索到 DOI → **download** 获取
- 调用方：**citation-snowball**（SEARCH + EXTRACT 阶段）

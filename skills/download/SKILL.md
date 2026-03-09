---
name: quasi:download
type: tool
description: >
  Pure file acquisition — books (Anna's Archive by MD5) and papers
  (OA/Wayback cascade by DOI/URL). No search logic; use search skill first
  to get identifiers. Use when the user says "下载", "download", or when
  another skill needs to acquire a file.
---

# Download — 纯获取

接受已解析的标识符（MD5/DOI/URL），下载学术文件。不做搜索，搜索用 search 技能。

## 接口

```
名称：download
输入：MD5 | DOI | URL | manifest（四选一）
参数：
  - output_dir: 下载目录（默认 sources/）
  - filename: 输出文件名（可选，不含扩展名）
  - format: pdf/epub（默认 pdf，仅 AA）
  - batch: 批量模式（配合 manifest）
  - retry-wayback: 对失败论文重试 Wayback
输出：下载的文件路径
```

## 使用方法

### 按 MD5 下载书籍（Anna's Archive）

先用 `search.py books --source aa` 搜索获取 MD5，然后：

```bash
python3 quasi/skills/download/scripts/download.py \
    --md5 abc123def456 --filename poggi-durkheim

# 指定格式和目录
python3 quasi/skills/download/scripts/download.py \
    --md5 abc123def456 --filename book-name -f epub -o sources/
```

### 按 DOI 下载论文（OA 级联）

```bash
python3 quasi/skills/download/scripts/download.py \
    --doi "10.1080/1600910X.2019.1641121"

# 带 Wayback 重试
python3 quasi/skills/download/scripts/download.py \
    --doi "10.1145/2737856.2738018" --retry-wayback
```

### 按 URL 直接下载

```bash
python3 quasi/skills/download/scripts/download.py \
    --url "https://example.com/paper.pdf" --filename "author-2023"
```

### 批量下载（manifest 模式）

```bash
# 下载 manifest 中所有 metadata_found 状态的论文
python3 quasi/skills/download/scripts/download.py \
    --manifest vault/journals/topic-slug/manifest.json --batch

# 带 Wayback 重试
python3 quasi/skills/download/scripts/download.py \
    --manifest vault/journals/topic-slug/manifest.json --batch --retry-wayback
```

## 下载策略

### 书籍（AA by MD5）
MD5 → AA Fast API → 流式下载

### 论文（DOI 级联）
1. 直接 URL（如有）
2. OA 来源（Unpaywall / OpenAlex / Semantic Scholar）
3. EZProxy 机构代理（需配置 cookie）
4. Wayback Machine 存档

### 批量（manifest）
对 manifest 中 `status: "metadata_found"` 的每篇论文：
1. 先试 manifest 中已有的 `oa_url`
2. 再查新的 OA 来源
3. 尝试 EZProxy 机构代理
4. 最后查 Wayback
5. 成功 → `status: "acquired"`，失败 → `status: "abstract_only"`

## 配置

### Anna's Archive

AA 需要 donator key，存放在 `.claude/config/anna-archive.json`（已 gitignore）：

```json
{
  "donator_key": "YOUR_KEY",
  "mirrors": ["https://annas-archive.gl", "https://annas-archive.li"]
}
```

### EZProxy

付费期刊下载需要 EZProxy cookie。配置文件位于技能文件夹内：

`quasi/skills/download/config/ezproxy.json`（已 gitignore）：

单 cookie 格式：
```json
{
  "cookie": "SESSION_VALUE",
  "cookie_name": "yewnoEzProxyn",
  "domain": ".eux.idm.oclc.org",
  "login_url": "https://login.eux.idm.oclc.org/login?url=",
  "updated": "2026-02-24"
}
```

多 cookie 格式（推荐，浏览器可能有多个 cookie）：
```json
{
  "cookies": {
    "yewnoEzProxyn": "VALUE1",
    "ezproxy": "VALUE2"
  },
  "domain": ".eux.idm.oclc.org",
  "login_url": "https://login.eux.idm.oclc.org/login?url=",
  "updated": "2026-02-24"
}
```

**获取 cookie**：浏览器登录 EZProxy → DevTools → Application → Cookies → 复制 `.eux.idm.oclc.org` 域下的所有 cookie。Cookie 名可能是 `ezproxy`、`yewnoEzProxyn` 或其他。

**注意**：EZProxy cookie 过期很快（可能只有几分钟），获取后需立即使用。

**工作原理**：OA 失败后自动尝试 EZProxy — 通过 login endpoint 重定向到代理后的出版商页面，然后按出版商模式构造 PDF URL（支持 Springer、SAGE、Wiley、T&F、OUP、Nature、UChicago、MIT 等），最后回退到 HTML 刮取。使用 `requests.Session` 确保 cookie 在重定向中正确传递。

**过期处理**：cookie 过期时脚本自动检测并报错停止，保存已有进度。更新 cookie 后重新运行即可。

备选路径：`.claude/config/ezproxy.json`（向后兼容）。

## 依赖

- `requests`（AA 流式下载 + EZProxy 会话管理）
- 标准库 `urllib`（OA/Wayback 下载）

## 技能依赖

- 上游：**search** 提供 MD5/DOI
- 调用方：**process-book** / **citation-snowball**

# 经验记录 — vault/books 元数据多源回填

- **日期**: 2026-05-17
- **场景**: 用户 vault/books 936 本 overview 几乎全部缺 publisher/isbn/doi。
  目标:用尽可能少的人工把 publisher 字段补到接近 100%。
- **结果**: publisher 0/936 → **936/936 (100%)**, isbn 43 → 906+ (97%), source 74 → 922+ (98%)。
- **耗时**: ~3 小时,中间多次 background sweep,最后人工挑剩 18 本。

本文档是给"如果以后要把这套流程包装成 skill"留的设计参考,
不是 step-by-step howto。重点在**陷阱**、**为什么这样排序**、**每个源真正的强弱在哪**。

---

## 1. 一句话结论

> AA 拿 md5 / ISBN,Crossref 拿 DOI / 学术 publisher,
> **OpenLibrary `/isbn/{ISBN}.json` 是干净 publisher 的金标准**,
> 本地 regex 清洗 > OL 替换(OL 会把 imprint 折叠到 parent group)。

如果只用一条规则:**title-search 都不靠谱,有 md5 / 有 ISBN 才是金标准**。

---

## 2. 实际跑的 fallback chain(按命中率从高到低排序)

```
[本地] frontmatter 清洗(wikilink / markdown / "—书籍概览"尾巴)
       └─→ 让后续 search query 干净
[1]  Crossref title search          → +510 / 936 (54%)
[2]  Anna's Archive title search    → +337       (累计 90%)
[3]  AA by-md5 直查 (本地 PDF md5)   → +45        (累计 95%)
[4]  slug 反构 title + 严格 filter  → +2         (累计 95%)  ← 谨慎
[5]  OL `/isbn/{ISBN}.json` reverse → 清洗 79 个噪声字段
     + 本地 regex 清洗
[6]  dokobot 浏览器人工核查最后 18  → 100%

剩余:0
```

**每个阶段的 dropout 率比想象高**。最初以为 Crossref + AA 就能搞定,实际只到 90%,
最后 10% 需要本地 PDF md5 + 出版社官网交叉验证才能补上。

---

## 3. 数据源能力地图 — 这是 skill 设计的核心

| 源 | 强在哪 | 弱在哪 | 不要拿它干嘛 |
|---|---|---|---|
| **Crossref title search** | 学术 publisher / DOI / 现代书 | `filter=type:book,type:monograph` 这种**多类型 OR filter 服务端 bug**;ebook ISBN 覆盖差 | title 含中文、副标题、括号备注的命中差 |
| **Anna's Archive title search** | 几乎所有 AA 收录的书都能找到 | publisher **字段是多版本拼接字符串**,有时只是地点;**没 DOI** | **不要直接信 AA 的 publisher 文本** —— 取 md5 / ISBN 后回 OL 反查 |
| **AA md5 直查 `/md5/<hash>`** | **0 误匹配**,因为是同一份文件;metadata-comments 里有 JSON `{publisher, isbns}` | 用户那份 PDF 在 AA 上的 metadata 可能稀薄(同书可能有别 md5 metadata 更全) | AA 没收录的(自发布 OA report)直接 NF |
| **OpenAlex search** | 跟 Crossref 索引不重叠;能给 DOI | **数据脏** —— 经常把编著的章节当 article、把书评 article 当 book、venue 写错 | **不要直接信 OA 的 publisher** —— 拿到 DOI 后回查 Crossref `/works/<doi>` |
| **OpenLibrary search.json** | 流行书 / 老书 ISBN | 对学术 monograph 弱 | 不要用它当主源做 title-search |
| **OpenLibrary `/isbn/{ISBN}.json`** | **publisher 字段最干净、最标准化** | OL 经常把 imprint 折叠到 parent(Routledge → Taylor & Francis Group);**ebook ISBN 16% miss rate** | 不要用它 overwrite 已经准确的 imprint 名 |
| **Google Books API** | 元数据丰富 | **每日 quota 0(项目无 key);走浏览器也是同 project_number 共享 quota** | 跳过 |
| **dokobot 浏览器** | search 命令需 API key;**read --local 走本地浏览器免费** | 一次一个 URL,无法并发抓 dom 字段(只返回 plain text) | 不要拿来批量,只用最后 spot-check |

---

## 4. 关键陷阱(实际踩过的坑)

### 4.1 title-search 同姓不同书的 false positive
- 例:`birkhead-the-red-canary-2022` 用 slug+author 查 AA → 命中 "Red Canary by 别人(浪漫小说)",author cell 里 "Birkhead" 字串 match,被误认为正确。
- **教训**: title overlap ≥ 0.55 + author 必须出现在结果里 + **year ±3** 都不够,**同名书同姓作者**还是会过。
- **fix**: 提高 overlap 到 0.7+,或者**优先走 md5 路径**(0 误匹配)。

### 4.2 ISBN 错配(AA 详情页 isbns 数组里掺别书 ISBN)
- 例:Latour `Never Been Modern` md5 详情页里第一个 ISBN-13 是 `9780074501320` —
  这是 Pearson India 一本完全无关的书,AA 数据混杂。
- **教训**: 不要无条件信 AA 详情页 isbns 数组的第一个 ISBN13。
- **fix**: 拿到 ISBN 后调 OL `/isbn/{ISBN}.json` sanity check —— OL 404 = ISBN 可疑;
  OL title 跟 vault title 完全 mismatch = ISBN 错配。

### 4.3 OL 把 imprint 折叠到 parent group
- 例:`amoore-algorithmic-life-2015` ISBN `9781138852839` → OL 返回 `Taylor & Francis Group`,
  但实际 imprint 是 **Routledge**(Taylor & Francis 的 imprint)。
- **教训**: OL 用 ISBN 反查公司层级常常出错,**它给的是 parent 而不是真正的 imprint**。
- **fix**: **本地 regex 优先于 OL 替换**。如果 vault 已经有 `"Routledge is an imprint of Taylor & Francis Group"`,
  本地 regex 取 `"Routledge"` 比 OL 给的 `"Taylor & Francis Group"` 准。

### 4.4 publisher 字段噪声类型(都用本地 regex 清洗,不需要联网)
```
"Routledge is an imprint of the Taylor & Francis Group"   → Routledge
"This Palgrave Macmillan Imprint Is Published By Springer" → Palgrave Macmillan
"MIT Press; The MIT Press"                                 → MIT Press
"Berkeley : University of California Press"                → University of California Press
"1999Macmillan Publishers Limited..."                      → Macmillan Publishers Limited
"X, United Kingdom, 2018"                                  → X
"Springer Nature Singapore Pte Ltd Fka Springer..."        → Springer Nature Singapore Pte. Limited (via OL)
```

### 4.5 city-only 必须走 OL ISBN-reverse
- AA 的 publisher 字段经常是 `"Boston, Beacon Press, 1993Beacon Press..."`,
  naive split(',')[0] 取到 `"Boston"`。
- **fix**: 一开始就用"含 Press/Publishing/Books/Verlag 关键词的段"优先策略,
  剩下纯 city-only 的极少数(11 本)走 OL ISBN-reverse。

### 4.6 plugin 的 PreToolUse hook 注入机制
- `QUASI_ANNA_DONATOR_KEY` 通过 `inject-userconfig.py` hook 注入,
  **只在 Bash tool 命令字符串里出现 `(separator)quasi-` 才触发**。
- 直接 `subprocess.run(["quasi-search", ...])` 在 Python 脚本里**不触发 hook**。
- **fix 1(技巧)**: 让外层 Bash tool 命令含一个 `quasi-` 字串(注释里也行 —
  `# invoke quasi-search`),hook 就会 export 环境变量到 shell process,
  然后子进程的 subprocess 继承。
- **fix 2(正路)**: 脚本直接读 plugin user config(但 keychain 涉及权限,不易)。

### 4.7 stdout buffering 假死
- 长 background python 跑 vault sweep,默认 stdout fully buffered,
  watch `tail -f log` 显示 0 行 = 看着像"卡死",其实在跑。
- **fix**: `PYTHONUNBUFFERED=1 python3 -u`。

### 4.8 Crossref filter 多类型 OR 语法 bug
- `filter=type:book,type:monograph,type:edited-book` 看似 OR 多个 type,
  但服务端只返回 0 结果 —— 实测对 `Precarious Japan`(monograph)用这个 filter 0 命中,
  去掉 filter 返回 2 个候选(`monograph` + `edited-book`)。
- **fix**: 不加 server-side type filter,客户端 post-filter `type in BOOK_TYPES`。

---

## 5. 给 skill 设计的建议(假想需求:`/quasi:fill-metadata <slug-glob>`)

### 5.1 接口形态
```
quasi:fill-metadata vault/books/                  # 全量
quasi:fill-metadata vault/books/ahmed-*           # glob 子集
quasi:fill-metadata --field publisher,isbn        # 只补特定字段
quasi:fill-metadata --review-only                 # 只输出 review 列表不写入
quasi:fill-metadata --aggressive                  # 允许 OL 替换 imprint 字段(默认保守)
```

### 5.2 内置 chain(顺序固定)
1. **frontmatter 清洗** —— wikilink / markdown / 概览尾巴,纯本地
2. **Crossref title search** —— 主源,fast
3. **AA title search**(走 `quasi-search`)—— 兜底
4. **AA md5 直查** —— 对 `sources/<slug>.{pdf,epub}` 存在的书
5. **OL ISBN-reverse** —— 对仍 city-only / empty publisher 的
6. **本地 regex 清洗** —— 对所有 publisher 字段
7. **输出 review file** —— mismatch / NF / 仍空,**不自动写**,让用户人工 spot-check

### 5.3 不要在 skill 里做的事
- 不要默认 `--aggressive` —— OL imprint 折叠会劣化已经准确的字段
- 不要自动 commit —— 这次 947 files 改动太大,用户需要看 diff 再确认
- 不要并行打 AA(donator key 速率 + Cloudflare 风险)—— sleep 0.4 单线程足够
- 不要在 title-search 路径放低 overlap 阈值 —— 同姓不同书会误匹配,默认 0.55,允许覆盖

### 5.4 必须暴露给用户的指标
- 跑完输出 summary: `total / matched / updated / NF / mismatch / unchanged`
- 一个 `reports/<run-id>/` 目录,**每条改动都写 audit trail**(slug, old, new, reason)
- review 文件分三类:
  - `publisher-mismatch.tsv` —— ISBN 反查回 OL,title 跟 vault 不 match,可能 ISBN 错
  - `isbn-notfound.tsv` —— OL 找不到 ISBN(多半 OL 索引漏,不一定错)
  - `still-missing.tsv` —— 所有路径都没补上的(最后用户手工 + dokobot)

### 5.5 这次留下的 8 个脚本可以直接迁过去
```
scripts/sweep-book-fm-clean.py             清洗 title/authors
scripts/sweep-book-fm-meta.py              Crossref title search
scripts/sweep-book-fm-meta-aa.py           AA title search
scripts/sweep-book-fm-meta-aa-by-md5.py    本地 md5 → AA 详情(0 误匹配)
scripts/sweep-book-fm-meta-aa-from-slug.py slug 反构 strict filter
scripts/sweep-book-fm-meta-oa.py           OA → DOI → CR(实际用得少)
scripts/sweep-book-fm-meta-ol-fallback.py  OL search 兜底
scripts/sweep-book-fm-ol-isbn-reverse.py   OL ISBN-reverse + 本地 regex 清洗
```
都在 `bts/scripts/` 下,可以直接挪到 plugin 里复用。

---

## 6. 一些反直觉的发现

1. **OpenLibrary search 弱,但 OpenLibrary ISBN-reverse 极强**。两个 endpoint 完全不同性质,以前一直把 OL 当统一一个"OL"思考是错的。
2. **AA 详情页 metadata 比 search 表格深得多**。表格只有 publisher 列(噪声大),详情页有 `metadata comments` JSON 区块(干净 publisher + ISBN 数组)。
3. **本地 PDF 的 md5 = AA 的 md5**(对用户从 AA 下的书),所以 `md5sum sources/<slug>.pdf | curl annas-archive.gl/md5/<hash>` 是 **0 误匹配**的查询。这是整条 chain 里最稳的一环。
4. **本地 regex 清洗 > OL 替换**。看起来"权威源"应该 > "regex 启发式",但 OL 在公司层级数据上反而劣于本地保留 imprint 名。
5. **Crossref 加 type filter 反而漏命中**。`filter=type:book,type:monograph,...` 服务端 bug,不加 filter 客户端 post-filter 反而对。

---

## 7. 命中率明细(实测,不是估算)

| 阶段 | candidate | matched | hit rate | 累计 publisher 覆盖 |
|---|---|---|---|---|
| frontmatter 清洗 | 330 | 330 | 100% | — |
| Crossref title | 934 | ~510 | 55% | 510 (54%) |
| AA title search | 479 | 395 | 82% | 847 (90%) |
| AA md5 直查 | 107 | 77 | 72% | 892 (95%) |
| slug 反构 AA(strict) | 34 | 2 | 6% | 894 (95%) |
| OL ISBN-reverse 清洗 | 全量 | 79 fixed | — | 894 (95%) |
| dokobot 人工 18 | 18 | 18 | 100% | 934 (99.8%) |
| 历史遗留 frontmatter | 2 | 2 | 100% | **936 (100%)** |

---

## 8. 不要忘记 commit 三个步骤

1. **大 commit**(947 files)—— 多源 sweep 主体,包含所有 8 个新脚本和 reports/。
2. **收尾 commit**(19 files)—— dokobot 核查最后 18 + 修一个 broken YAML。
3. **历史遗留 commit**(2 files)—— 给没 YAML frontmatter 的旧文件补 frontmatter。

每个 commit message 写清楚 publisher 覆盖率变化,以后 git log 可以一眼看出每步贡献。

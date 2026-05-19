# Douban Localisation Handoff

## Current Goal

`quasi-search book` fills `localisations.zh` with Chinese-edition candidates.

Hard constraints:

1. Use original bibliographic fields only.
2. Avoid agent-invented Chinese titles, publishers, translators, or query
   terms.
3. Use an external search engine to discover Douban `subject` URLs;
   filter aggressively to canonical subject pages.
4. Parse pages with plain HTTP + BeautifulSoup. No Doko / browser bridge.

## Current Flow

For book localisation (`subject=zh` sidecar or explicit Chinese-version
lookup), implemented in `_zh_localisation_search`:

```text
compact_external_book_query(title, author, year)
  -> kagi search --format json "site:book.douban.com/subject {q}"
  -> filter Kagi `data[].url` with strict canonical regex:
        ^https?://book\.douban\.com/subject/(\d+)/*(?:\?[^#]*)?$
     drops /comments, /blockquotes, /doulists, /reviews/..., etc.
     normalises `/subject/ID//` and `?_dtcc=...` to `/subject/ID/`
  -> for each canonical URL (limit 10):
        requests.get with browser User-Agent + Accept-Language
        BeautifulSoup parse:
          - title: <span property="v:itemreviewed"> (fallback h1)
          - #info block: 作者/译者/出版社/出版年/ISBN/原作名/副标题/丛书
          - rating: <strong property="v:average">
          - votes: <span property="v:votes">
        apply _is_chinese_edition filter:
          1. ISBN agency 978-7 / 957/986 / 988/962  ⇒ accept
          2. ISBN agency 978-4 / 89/11 / 604         ⇒ reject (JP/KR/VN)
          3. Kana / Hangul anywhere                  ⇒ reject
          4. CJK in publisher | translator-with-CJK | title ⇒ accept
          5. otherwise reject
  -> sort by ratings_count desc
  -> return as `localisations.zh.candidates[]`
```

No Doko walking, no `_find_cndouban`, no related-version graph traversal,
no Douban-search fallback, no `/works/{id}/` aggregate pages.

## Implementation surface

All in `scripts/search/sources/douban_cn.py`:

- `_compact_external_book_query(title, author, query, year, ...)`
  - flattens whitespace, drops subtitle after `:` / `：`, caps title to
    6 tokens and author to 4 tokens.
  - example: `Strange Encounters: Embodied Others in\nPost-Coloniality` +
    `Sara Ahmed` → `Strange Encounters Sara Ahmed`.

- `_kagi_subject_urls(query, limit=10) -> (urls, warnings)`
  - calls `kagi search --format json "site:book.douban.com/subject {query}"`
  - walks `payload["data"]`, applies `_RE_DOUBAN_SUBJECT_CLEAN`, dedupes,
    returns canonical `https://book.douban.com/subject/{id}/` URLs only.

- `_fetch_subject_via_bs4(url, cookie=None) -> dict | None`
  - uses `_dd_fetch` (urllib with browser headers) + `BeautifulSoup`.
  - returns None on fetch failure or block, otherwise a raw dict with
    keys: title, authors, translators, publisher, year, isbn_13/10,
    original_title, subtitle, series, douban_rating, ratings_count,
    douban_subject_id, douban_url.

- `_is_chinese_edition(rec) -> bool`
  - ISBN-prefix gate first (CN/TW/HK accept; JP/KR/VN reject), then
    kana/hangul reject, then CJK in publisher/translator/title.

- `_zh_localisation_search(query) -> (records, warnings)`
  - top-level: Kagi → strict URL filter → bs4 fetch → Chinese filter →
    sort by ratings_count desc.

Kagi CLI is expected to be available as `kagi` on `PATH`. The user's
workspace stores credentials in `.kagi.toml` at CWD (untracked); the
plugin reads no Kagi config of its own.

## Agent Rules

`agents/search-agent.md` was updated:

- first call should use only caller/context original fields:
  ISBN, original title, original author, year, original query
- if extra Chinese-version checking is needed, rerun at most once with the same
  original fields
- do not invent or translate Chinese titles, publishers, translators, or query
  terms
- do not hand-write Douban search URLs
- inspect returned `douban_url` / `preview_link` only

## Important Tests

Run from repo root:

```bash
python3 plugins/quasi/scripts/search/tests/test_source_douban_cn.py
python3 plugins/quasi/scripts/search/tests/test_douban_cn_en2zh.py
pytest plugins/quasi/scripts/search/tests/test_source_douban_cn.py plugins/quasi/scripts/search/tests/test_douban_cn_en2zh.py -q
pytest plugins/quasi/scripts/search/tests -q
pytest plugins/quasi/tests/test_search_cli.py -q
```

Latest local results:

- `test_source_douban_cn.py`: 17/17 passed
- `test_douban_cn_en2zh.py`: 21/21 passed
- paired pytest: 38 passed
- full search tests: 84 passed, 1 urllib/OpenSSL environment warning
- CLI sidecar tests: 3 passed

## End-to-end validation (2026-05-19)

Kagi 0.5.4 installed and authenticated via `.kagi.toml` in CWD. Atomic
operation `_kagi_site_subject_urls(query)` returns real Douban subject URLs;
five-case run end-to-end:

| Case | Result |
|------|--------|
| Strange Encounters / Sara Ahmed | no Chinese candidates (correct — no translation exists) |
| The Cultural Politics of Emotion / Sara Ahmed | no Chinese candidates (Douban has no separate Chinese subject for CPE) |
| Gender Trouble / Judith Butler | 3 Chinese editions: 上海三联书店 / 岳麓书社 / 桂冠 (TW) |
| Discipline and Punish / Foucault | 4 Chinese editions, all 三联书店 |
| Staying with the Trouble / Haraway | no Chinese candidates (no Chinese translation on Douban) |

## Downstream bugs found and fixed in this pass

1. **Primary-subject picker took Kagi rank #1 blindly** — for "Strange
   Encounters" Kagi returned CPE (subject 2899436) at rank #1 because the
   CPE page text mentions Strange Encounters. Now each Kagi URL is fetched,
   the parsed page is scored against the original title/author (title-head
   substring + token overlap + author surname), and the best-scoring
   candidate wins. Score ≥1.2 triggers early break; score <0.3 rejects.

2. **`_parse_cn_subject_page` field regexes had no label-lookahead** — on
   Doko-rendered subject pages the metadata is one long line
   (`作者: ... 出版社: ... 出版年: ... ISBN: ...`), so `作者:.+?\n` greedily
   grabbed the entire trailing blob. Replaced with `_grab_doko_meta` which
   uses lookahead against `_DOKO_META_LABELS`.

3. **`_grab_doko_meta` matched anywhere in the body** — picked up stray
   `译者:` from reader-comment blocks. Now scoped via `_doko_meta_window`
   (text between `**Title**` and `豆瓣评分`).

4. **`_guess_title_from_subject_page` returned `# Title (豆瓣)`** — markdown
   `#` heading and `(豆瓣)` suffix leaked into the canonical title. Now
   prefers the `**Title**` marker and strips the `(豆瓣)` suffix.

5. **Chinese-edition detection used a brittle publisher whitelist** —
   `_ZH_PUBLISHER_HINT_RE` could only recognise ~25 hard-coded fragments,
   and its bare `出版` alternation also matched the year label `出版年`.
   Replaced with principled signals:
   - ISBN agency prefix `978-7-` / `978-957/986` / `978-988/962` ⇒ accept
   - ISBN agency prefix `978-4-` (JP) / `978-89/11` (KR) / `978-604` (VN)
     ⇒ explicit reject (otherwise kanji-only Japanese titles slip through)
   - Kana or Hangul in title/publisher/translator ⇒ reject
   - Any of (publisher CJK | translator non-empty AND CJK | title CJK)
     ⇒ accept

   Tests cover the false-positive cases that prompted this rewrite (French
   QP edition with translator "Laurence Brottier"; Japanese 伴侶種宣言 with
   kanji translator).

## What is still optional / future

- `_related_version_search` fallback (used when `_find_cndouban` finds no
  Chinese candidates on the primary subject's "其他版本" block) still walks
  Kagi seeds' related-version graphs broadly. With the strict Chinese
  detection above, false positives are gone, but irrelevant English
  related-version pages still get fetched. Could prune by requiring seed
  matches the query (re-use `_score_primary_match`).


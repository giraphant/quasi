# Douban Localisation Handoff

## Current Goal

`quasi-search book` fills `localisations.zh` with Chinese-edition candidates.
The desired path is:

1. Use original bibliographic fields only.
2. Avoid agent-invented Chinese titles, publishers, translators, or query terms.
3. Use an external search engine to discover Douban `subject` URLs before falling
   back to Douban's own search.
4. Read concrete Douban pages through Doko.

## Current Flow

For book localisation (`subject=zh` sidecar or explicit Chinese-version lookup):

```text
ISBN direct
  -> Doko read https://book.douban.com/isbn/{isbn}/
  -> if subject found, read that subject page

If no primary subject:
  -> compact title/author into a short external query
  -> Kagi CLI search:
       site:book.douban.com/subject {short query}
  -> extract book.douban.com/subject/{id}/ URLs
  -> Doko read candidate subject page

If still no primary subject:
  -> fallback to Douban search.douban.com via Doko

After primary subject:
  -> parse subject page "other versions" links only
  -> do not read /works/{id}/ aggregate pages
  -> Doko read candidate subject pages
  -> keep records that look Chinese
```

`works` pages were removed from the active path because English and Chinese
editions were observed not to reliably share the same Douban works aggregate.

## Kagi Integration

Implementation file:

- `scripts/search/sources/douban_cn.py`

Relevant functions:

- `_compact_external_book_query(...)`
  - flattens whitespace
  - drops subtitle after `:` / `：`
  - limits title and author token count
  - example:
    `Strange Encounters: Embodied Others in\n Post-Coloniality` + `Sara Ahmed`
    becomes `Strange Encounters Sara Ahmed`

- `_kagi_site_subject_query(query)`
  - returns `site:book.douban.com/subject {query}`
  - no extra `豆瓣读书` suffix

- `_kagi_site_subject_urls(query, limit=5)`
  - calls `kagi search --format json`
  - extracts `book.douban.com/subject/...` URLs from JSON
  - does not invoke Doko
  - if Kagi is missing or returns no subjects, returns warnings and lets caller
    proceed to Douban fallback

Kagi CLI is expected to be available as `kagi` on `PATH`. The current local
workspace has an untracked `.kagi.toml` with credentials; do not commit it.

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


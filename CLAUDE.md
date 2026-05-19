# quasi maintainer guide

quasi is a Claude Code plugin for academic reading workflows: discovery, download, extraction, analysis, synthesis, translation, and schema checking.

## Important plugin-system facts

- Installed plugins load components from root-level `skills/`, `agents/`, `bin/`, `hooks/`, `monitors/`, `.mcp.json`, and `.lsp.json`.
- `.claude-plugin/plugin.json` is metadata only. Do not place components inside `.claude-plugin/`.
- This `CLAUDE.md` helps humans and Claude Code sessions opened inside the quasi source tree, but Claude Code does not load a plugin-root `CLAUDE.md` as context when quasi is installed as a plugin.

## Skill writing schema

`docs/SKILL_ORCHESTRATION.md` is maintainer guidance. Active `SKILL.md` files
should not cite it directly; runtime skill text should contain only information
the executing model needs.

Use this shape for active skills when applicable:

```text
任务
输入
硬约束
状态
Agent / Helper 合同
工作流
执行流程
断点续跑
输出
```

`任务` should be one short positive sentence naming the work. Use `输入` instead
of `调用方式` unless the skill has a real machine-facing invocation API. In normal
plugin use, the frontmatter description and natural language trigger the skill;
the body should define variable extraction and workflow contracts.

Frontmatter `description` is only a routing hint. Skill descriptions should
describe user intent; agent descriptions should describe one worker action and
its main output. Do not put trigger-word lists, history notes, or phase
walkthroughs in descriptions.

## Release checklist

1. Update `.claude-plugin/plugin.json`.
2. Mirror the same version in `.claude-plugin/marketplace.json`.
3. Run:
   ```bash
   claude plugin validate plugins/quasi
   ```
4. If publishing a release tag, prefer:
   ```bash
   claude plugin tag plugins/quasi
   ```

The version in `plugin.json` takes precedence over marketplace entry versions. If these drift, installation still works but validation warns and users can see confusing version information.

## Runtime state

- `CLAUDE_PLUGIN_ROOT` is for reading bundled code and assets only.
- `CLAUDE_PLUGIN_DATA` is for persistent virtualenvs, caches, generated files, and installed dependencies.
- Avoid writing dependency state into the plugin root; installed plugin roots are versioned and may change across updates.

## Python venv bootstrap (since 0.11.0)

Python dependencies are declared in `scripts/requirements.txt` and installed into a
shared venv at `${CLAUDE_PLUGIN_DATA}/.venv` (falls back to `~/.cache/quasi/.venv`
when run outside a plugin context).

Bootstrap is handled by `scripts/bootstrap-venv.sh`, wired to the `SessionStart`
hook in `hooks/hooks.json`. It diffs the bundled `requirements.txt` against the
copy in `$DATA_DIR/requirements.txt` and only reinstalls on change. Each `bin/quasi-*`
shim resolves `$DATA_DIR/.venv/bin/python` and falls back to running bootstrap if
the venv is missing — so shims work even when SessionStart hasn't fired yet
(bare invocation, fresh install).

To bump deps: edit `scripts/requirements.txt`, ship. Next session picks up the diff.

## Recent Changes

- **0.32.8** (2026-05-19): **Douban localisation: Doko walk removed,
  Kagi + BeautifulSoup is the only path.** 10/10 live test books (Foucault
  / Butler / Latour / Anderson / Said / Arendt / Bourdieu / Haraway etc.)
  returned at least one Chinese-edition candidate via the simple flow —
  vindicating the user's diagnosis that the Doko maze was overengineering.
  - **`scripts/search/sources/douban_cn.py`**: 1402 → 678 lines (51% cut).
    Deleted: `_doko_read`, `_find_cndouban`, `_cndouban_works_*`,
    `_related_version_search`, `_fetch_subject_for_related`,
    `_parse_cn_subject_page`, `_parse_doko_subject_page`,
    `_grab_doko_meta`, `_doko_meta_window`, `_clean_doko_title`,
    `_extract_related_version_urls*`, `_version_section_snippets`,
    `_parse_doko_references`, `_extract_manifestations_from_works_page`,
    `_kagi_site_subject_urls`, `_kagi_site_subject_query`,
    `_score_primary_match`, `_normalise_for_match`, plus a dozen helpers.
    Net deletion of the entire Doko subprocess path.
  - **New 3-step path** (`_zh_localisation_search`):
    1. `_compact_external_book_query(title, author)` →
       `_kagi_subject_urls(q)` runs `kagi search --format json
       site:book.douban.com/subject {q}` and filters `data[].url` via
       `_RE_DOUBAN_SUBJECT_CLEAN = r"^https?://book\.douban\.com/subject/
       (\d+)/*(?:\?[^#]*)?$"` — drops `/comments`, `/blockquotes`,
       `/doulists`, `/reviews/...`, normalises `/subject/ID//` and
       `?_dtcc=...` to canonical `/subject/ID/`.
    2. `_fetch_subject_via_bs4(url)` uses plain `urllib` (`_dd_fetch`) +
       `BeautifulSoup` to parse `<span property="v:itemreviewed">` for the
       title and `<div id="info">` for `作者 / 译者 / 出版社 / 出版年 / ISBN
       / 原作名` etc. Field parsing uses label-alt lookahead so the inline
       metadata block doesn't bleed across fields, and stays scoped to
       `#info` so stray `译者:` in reader comments can't leak in.
    3. `_is_chinese_edition(rec)` (unchanged from 0.32.7): ISBN agency
       prefix decisive (CN/TW/HK accept, JP/KR/VN reject), then kana /
       hangul anywhere reject, then CJK in publisher / translator-with-CJK
       / title accept.
  - `search_book(query)` `subject=zh` branch shrinks from a 3-fallback
    cascade (Doko cndouban → kagi-seeded related-version walk → direct
    search → related-version walk) to one call to
    `_zh_localisation_search`.
  - **No new `userConfig`** — `kagi` CLI reads `.kagi.toml` from CWD per
    its own convention; the plugin doesn't bridge or override.
  - **Tests rewritten**: `test_source_douban_cn.py` (29 tests) and
    `test_douban_cn_en2zh.py` (19 tests) target the new functions —
    URL-filter regex (canonical / `/comments` reject / double-slash
    normalisation / dedup / limit), `_compact_external_book_query`
    behaviour, `_kagi_subject_urls` shell-out (kagi missing / nonzero rc
    / site-limiter format), `_fetch_subject_via_bs4` parsing (info-block
    isolation, block detection, fetch-failure handling),
    `_is_chinese_edition` matrix (CN/TW/HK accept, JP reject even with
    kanji, kana/hangul reject, CJK-publisher accept, non-CJK translator
    reject), `_zh_localisation_search` integration (filter mix EN+ZH,
    sort by ratings_count, kagi-warning surface). Full suite: 94 pass.
  - `agents/search-agent.md` zh-localisation note updated:
    `Kagi 不可用或无结果时,bin 会自行走豆瓣兜底` → `Kagi 不可用时,
    localisations.zh.candidates 为空`. No more Doko fallback to misrepresent.
  - `docs/DOUBAN_LOCALISATION_HANDOFF.md` rewritten end-to-end against
    the new 3-step pipeline.

- **0.32.7** (2026-05-19): **Douban Chinese localisation pipeline — end-to-end
  correctness pass.** Builds on 0.32.4–0.32.6 (Kagi-CLI primary subject
  discovery). Five real-book end-to-end runs surfaced five downstream bugs
  that were masking each other; all fixed in `scripts/search/sources/douban_cn.py`:
  - **Primary-subject picker no longer takes Kagi rank #1 blindly.** For
    "Strange Encounters / Sara Ahmed" Kagi ranked *The Cultural Politics of
    Emotion* #1 (CPE's page text mentions SE). Now each Kagi URL is
    Doko-fetched, parsed, and scored against the original title/author
    (`_score_primary_match`: title-head substring ⇒ +1.0; token overlap ≥60%
    ⇒ +0.6; author-surname ⇒ +0.4). Score ≥1.2 early-breaks; <0.3 rejects.
  - **`_parse_cn_subject_page` field extraction rewritten.** Doko renders
    Douban metadata as one long line `作者: ... 出版社: ... 出版年: ... ISBN: ...`,
    so the old `作者:.+?\n` regex greedily grabbed the entire blob. Now uses
    `_grab_doko_meta` with label lookahead against `_DOKO_META_LABELS`.
  - **`_grab_doko_meta` scoped to a metadata window.** Previously matched
    anywhere in the body — picked up stray `译者:` from reader comments far
    below the metadata, producing translator blobs like `"Alice Lian Sara
    Ahmed(2004),The Cultural Politics of Emotion..."`. New helper
    `_doko_meta_window(body)` slices text between `**Title**` and `豆瓣评分`.
  - **Title cleaning.** `_guess_title_from_subject_page` used to return
    `# Title (豆瓣)` with markdown noise. Now prefers the `**Title**` marker
    and strips the `(豆瓣)` suffix via `_clean_doko_title`.
  - **Chinese-edition detection no longer a publisher whitelist.** Old
    `_ZH_PUBLISHER_HINT_RE` enumerated ~25 publisher fragments (`三联|译林|
    上海|...`) — could never keep up with the long tail of academic / indie
    presses, and its bare `出版` alternation also matched the year label
    `出版年` (false positive). Replaced with registry-based signals:
    - ISBN agency prefix `978-7-` (mainland) / `978-957/986` (TW) /
      `978-988/962` (HK) ⇒ accept
    - ISBN prefix `978-4-` (JP) / `978-89/11` (KR) / `978-604` (VN) ⇒
      explicit reject (otherwise kanji-only Japanese titles like 伴侶種宣言
      slip through the generic CJK check)
    - Kana or Hangul anywhere in title / publisher / translator ⇒ reject
    - CJK in publisher | (CJK in translator AND translator non-empty) |
      CJK in title ⇒ accept
    The translator-non-empty alone (which had let through a French CPE
    edition by "Laurence Brottier") now requires CJK to count.
  - **End-to-end validation** in `docs/DOUBAN_LOCALISATION_HANDOFF.md`:
    Gender Trouble returns 3 Chinese editions (上海三联书店 / 岳麓书社 /
    桂冠 TW); Discipline and Punish returns 4 (三联书店 various years);
    Strange Encounters / CPE / Staying with the Trouble correctly return
    no candidates (no Chinese Douban subject for those works exists).
  - Existing 38 `douban_cn` tests still pass; full search suite 84 pass.
  - No new plugin `userConfig` slot — `kagi` CLI auth is read from
    `.kagi.toml` in CWD (user's own setup), not bridged through the
    plugin.

- **0.32.3** (2026-05-18): **book localisation sidecar becomes
  Doko-first and source-independent.** `quasi-search book` now always
  attempts the `localisations.zh` Douban sidecar, even when the caller
  limits canonical metadata search with `--source`. Chinese localisation
  lookup now prefers the Doko-rendered path (ISBN/search → Douban subject
  → other versions / works page → Chinese manifestation subject) before
  falling back to direct HTTP + related-version probing. Doko failures are
  surfaced as `localisations.zh.status="error"` instead of the previous
  false-negative `none`, so callers do not cache "no translation" when the
  browser bridge/API path was unavailable.

- **0.32.1** (2026-05-18): **frontmatter description discipline.**
  Treats `description:` as a routing hint, not a mini-README.
  Skill descriptions normalised to user-intent shape — `Use when
  the user wants to {core task} from/with {likely inputs}.`
  Agent descriptions normalised to worker shape — `Worker for
  {single specialist action}. {Main contract.}` Trigger-word piles,
  history notes (`前身: ...`), and phase walkthroughs (`Phase X →
  ...`) removed across all 5 active skills and all 9 active agents.
  `AGENTS.md`, `CLAUDE.md`, and `docs/SKILL_ORCHESTRATION.md`
  carry the maintainer-facing convention. Enforcement landed as
  `tests/test_skill_orchestration.py::test_frontmatter_descriptions_are_routing_hints`
  (length cap 220, required prefix per kind, forbidden tokens
  `user says / 前身 / Phase / → / 由 ` per kind).

- **0.32.0** (2026-05-18): **skill orchestration schema + bin
  surface trim.** All five active skills rewritten to the
  maintainer schema documented in `docs/SKILL_ORCHESTRATION.md`
  (new file): `任务` (one positive sentence), `输入` (intent →
  variable extraction), `硬约束`, `状态` (skill main process owns
  workflow state), `Agent / Helper 合同`, `工作流`, `执行流程`,
  `断点续跑`, `输出`. `调用方式`-style invocation API blocks are
  removed from runtime skills; natural-language trigger via
  frontmatter description is canonical. `AGENTS.md`, `CLAUDE.md`,
  `README.md`, and `docs/ARCHITECTURE.md` carry the maintainer-facing
  pointer to the schema doc, so active `SKILL.md` files no longer
  link back to maintainer docs.
  - Rewritten: `process-book`, `process-author`, `process-paper`,
    `process-topic`, `wrap-up`. Behaviour preserved end-to-end; the
    rewrite is structural — phases, agent dispatches, and human
    gates are now made explicit per the schema.
  - **BREAKING — `quasi-search`**: `--shape canonical|raw|single`
    and `--output PATH` flags removed; the markdown emitter is
    gone. Output is always canonical JSON to stdout. `--json` is
    accepted as a no-op for compatibility. Callers that needed
    `--shape single` should slice `results[:1]` themselves; the
    `raw` shape was unused.
  - **BREAKING — `quasi-download`**: `batch` subcommand removed
    along with `batch_download_manifest()` and the related glue
    (`_cmd_batch`, parser entry). Batch acquisition is now a skill
    main-process concern — `process-author` / `process-topic`
    dispatch `download-agent` directly with structured items.
  - `quasi-extract` chapter manifest: per-chapter field `file`
    renamed to `filename`; added `extracted_count` (top-level) and
    `word_count` (per chapter). Downstream extract callers and
    `process-book` Step 2 read the new shape.
  - `tests/test_dead_names.py` now scans active markdown plus
    `bin/quasi-*` shims, `README.md`, and `docs/ARCHITECTURE.md`,
    and grows entries for `--shape single|raw`, `--output`,
    `quasi-download batch`, `output_schema`, `citation-agent`
    (post-0.25.2 rename), and `mode: papers` (post-0.24.0 search
    refactor).
  - New tests: `tests/test_search_cli.py` (asserts JSON-only output
    contract, no `--shape`/`--output`), `tests/test_extract_cli.py`
    (asserts new chapter manifest field names),
    `tests/test_skill_orchestration.py` (asserts all five active
    skills carry the schema landmarks).
  - Minor: `scripts/extract/toc_utils.py` gains
    `from __future__ import annotations`; `scripts/citation/emit_bib.py`
    docstring updated to reference the wrap-up review step (not the
    deprecated `review.html` "导出 JSON" button); `quasi-helpers`
    header comment updated to `citecheck-agent` (post-0.25.2).

- **0.31.0** (2026-05-18): **quasi-audit becomes a single
  agent-facing typecheck wrapper.** The active CLI is now
  `quasi-audit --path PATH`. It always runs mechanical autofix,
  typecheck, residual issue classification, and emits JSON. Removed
  the agent-facing `run` verb, `--mode`, and `--json`; there is no
  check-only path in the active workflow. `emit-bib` moved to
  `quasi-helpers citation biblio`, and metadata backfill sweeps are
  maintenance scripts rather than `quasi-audit` subcommands.

- **0.30.0** (2026-05-18): **localise becomes a scale-facing helper,
  keyed by original ISBN.** This supersedes the 0.27/0.29
  local-agent/audit-localise shape. Book search now returns
  `localisations.zh` sidecar candidates; search-agent filters and
  passes those candidates upward but does not write files. The top-level
  skill decides whether to persist them via
  `quasi-helpers localise scan|write`, which writes
  `.quasi/localise/cndouban.json`:
  - `by_isbn[{normalized_original_isbn}]` stores checked state,
    current book path snapshots, and curated `cndouban_ids`.
  - `by_douban_id[{id}]` stores Chinese-edition metadata.
  - `quasi-audit localise` and `agents/local-agent.md` are removed from
    the active surface; audit is back to vault consistency only.

- **0.29.0** (2026-05-18): **cndouban fully externalised + audit
  reverts to a stateless typechecker.** Two intertwined cleanups landed
  together. First: continues 0.26.0's `.quasi/` artifact discipline by
  evicting `cndouban` from book frontmatter — it was the last
  user-facing field that was actually plumbing (an index into
  `.quasi/audit/translations.json`); now both the per-book state
  machine and the per-id metadata cache live in that file. Second:
  audit-agent has no persistent state of its own — it's structurally
  a unit-like typechecker — so its disk-write surface contracts to
  zero, and the cndouban backfill knowledge moves out of audit into
  local-agent's domain entirely.

  **Externalising cndouban:**
  - `scripts/schemas/book.py`: `cndouban` field removed. Comment in its place
    points readers to the external file.
  - `.quasi/audit/translations.json` schema bumped v1 → v2:
    ```json
    {
      "version": 2,
      "by_book": {
        "{slug}": {
          "checked_at": "YYYY-MM-DD",
          "verdict": "found" | "none",
          "douban_ids": [12345, 67890]
        }
      },
      "by_douban_id": {
        "12345": { ...per-id metadata, as before... }
      }
    }
    ```
    `verdict="none"` replaces the old `cndouban: []` semantic (查过、无中
    译本). `by_book[slug]` absent ⇒ 未查 (replaces `cndouban` field-absent
    semantic). v1 flat files are migrated by the script — readers do
    not need to handle v1 directly.
  - `scripts/migrations/cndouban_externalise.py` (new): one-shot
    user-disk migration. Scans `vault/books/**/00-overview.md`,
    converts each `cndouban: [...] / [] / null` field into a
    `by_book` entry (or for the null case, just strips the line —
    "not yet queried" needs no entry), reformats existing
    `translations.json` from v1 flat to v2 if needed, then strips
    the `cndouban:` line from frontmatter. Idempotent on
    already-migrated vaults. Invoke with
    `CLAUDE_PROJECT_DIR=/path/to/vault python "$CLAUDE_PLUGIN_ROOT/scripts/migrations/cndouban_externalise.py"`,
    optionally `--dry-run` first.
  - `agents/audit-agent.md`: book frontmatter `optional` list drops
    `cndouban` with a pointer comment to the external file.

  **Audit runner ⟂ translations.json decoupling + helper subcommands
  for local-agent:**
  - `scripts/audit/audit.py:_scan_needs_backfill` no longer flags
    `cndouban` at all; only structural frontmatter fields
    (publisher/isbn/doi) are reported. The runner doesn't open
    translations.json; cross-domain coupling that briefly slipped
    into `needs_backfill` is gone.
  - `scripts/audit/localise.py` (new) + `quasi-audit localise`
    subcommand: gives local-agent the script support it needs without
    a whole new bin. Two verbs:
    - `quasi-audit localise scan [--path X] [--json]` — enumerate
      `00-overview.md` files under PATH, emit per-book `{slug, path,
      has_entry, title, authors, year, isbn}`. `has_entry=true` means
      `by_book[slug]` is present in translations.json — the agent
      uses this for idempotent gating.
    - `quasi-audit localise write --slug SLUG (--results-json '[...]'
      | --results-file PATH)` — merge one book's localise outcome
      into translations.json. Empty results ⇒ `verdict=none`;
      non-empty ⇒ `verdict=found` + merge per-id metadata
      (`first_seen` preserved on existing keys). v1 flat cache
      auto-migrates to v2 on first write.

    These verbs live under `quasi-audit` purely as the natural home
    for small vault-touching helpers; the runner's analytical output
    stays domain-pure (cf. `feedback_audit_stateless` — runner stays
    decoupled even though bin can ship related helpers).
  - `agents/local-agent.md` rewritten: agent calls
    `quasi-audit localise scan --json` for the work list, dispatches
    `quasi-search book --source douban_cn --subject zh` per pending
    book, and writes results back via `quasi-audit localise write`.
    Agent no longer touches the JSON cache or vault frontmatter
    directly — tool surface trimmed to `Read, Bash`.
  - `skills/{process-book,process-author}/SKILL.md`: Step 6 / Phase 7
    LOCALISE comments + resume tables updated to reference
    `.quasi/audit/translations.json#by_book[slug]`; local-agent's
    self-contained gating noted.

  **Audit CLI dead-code cleanup — audit becomes effectively stateless:**
  - `scripts/audit/audit.py`: `_write_state()` deleted along with its
    `.quasi/audit/audit-state.json` artifact. Nothing programmatic
    read it; the wrap-up SKILL referenced it in pseudocode
    (`audit_state_clean()`) for a Phase 0 gating that was never
    actually implemented.
  - `quasi-audit check` and `quasi-audit fix` subcommands removed —
    they thin-delegated to typecheck.py / autofix_mechanical.py and
    had zero callers (agents use `quasi-audit run --mode {check,fix}`,
    which carries the structured JSON envelope). The `_delegate`
    helper goes with them. `bin/quasi-audit` shim help block rewritten.
  - `skills/wrap-up/SKILL.md`: `--audit-first` flag + the
    `audit_state_clean()` pseudocode block stripped (Phase 0 was never
    real; the only real audit consumers are inside process-book /
    process-author skills which dispatch audit-agent directly).
  - Post-cleanup, audit's only disk side-effect is
    `.quasi/audit/typecheck-results.json` (the in-process round-trip
    artifact left behind by typecheck.py). audit-agent itself is now
    truly stateless — runs, returns JSON, done.

  **Tests**: no test changes — existing `test_douban_cn_en2zh.py` /
    `test_source_douban_cn.py` cover the data-source layer
    (HTML parsing, search, normalisation), not the agent writeback
    path or the translations.json schema, so they're untouched by
    this refactor.

- **0.28.0** (2026-05-18): **process-book/author reorchestration +
  new process-paper skill.** Rewires `process-book` Step 0 and
  `process-author` Phase 1/2 around the post-0.24.0 search-bin and
  post-0.25.0 agent contracts, and lifts YEAR_TRIAGE out of skill
  prose into a structured field in `download-agent`'s output protocol.
  - `agents/download-agent.md`: `DOWNLOAD_RESULT.per_item` for
    `kind=book` gains a `year_evidence` sub-object
    (`slug_year`, `source_years`, `pdf_signals`, `recommended_year`,
    `recommendation_reason`, `verdict`). Status enum grows
    `year_mismatch` and `year_ambiguous`; `tmp_path` exposed in those
    cases. Verdict computation rule codified in the agent prompt:
    `recommended_year` prefers `pdf.first_published` > multi-source
    mode > `pdf.copyright_year`; translation books exclude
    `original_year`; `MATCH` iff `slug_year == recommended_year` and
    ≥2 corroborating signals. Papers (`kind=paper`) explicitly do
    not carry `year_evidence` — DOIs are one-to-one, no version
    ambiguity.
  - `skills/process-book/SKILL.md`: Step 0 shrinks from ~80-line
    inline prompt (replicating search→download→finalize chain inside
    download-agent's prompt) to a thin caller — dispatch
    download-agent with `{kind: book, items: [1]}`, branch on
    `item.status`. `ok` → continue to EXTRACT;
    `year_mismatch`/`year_ambiguous` → report `year_evidence`
    verbatim to user (user changes slug or manually mv tmp);
    `download_failed` → fail. No more string-match parsing of agent
    reply prose. Preamble describing the inline chain rewritten to
    point at the agent contract.
  - `skills/process-author/SKILL.md`: Phase 1 replaces single
    narrative search-agent dispatch with two strict-contract
    dispatches (`kind=book` + `kind=paper`) writing
    `.quasi/authors/{slug}/{books,papers}.json`; skill merges into
    the canonical `manifest.json` shape Phase 2+ already expects.
    Phase 2 replaces single `mode=both` download-agent dispatch (no
    longer supported by agent contract since 0.24.0) with two
    structured dispatches (`kind=book` + `kind=paper`). Batch policy
    on book year mismatch: do NOT pause — skill overrides agent's
    "keep as tmp" signal, `mv`s tmp → final under slug-authoritative
    name, records `year_evidence` + a one-line `year_warning` for
    end-of-run report. Paper failures (fail-fast, no candidate
    retry) recorded with `failure_note`. Manifest status enum grows
    `year_mismatch` and `year_ambiguous`; resume-skip rules updated
    accordingly. Orchestration diagram updated to show
    `Phase 2: download-agent × 2`.
  - `skills/process-paper/SKILL.md` (new): single-paper end-to-end
    skill — `--doi` (preferred), `--slug` (PDF already in
    `sources/`), or `--title --author` (fallback). Opt-in
    `--translate` flag dispatches `translate-agent`. Reuses
    search-agent, download-agent, analyse-agent type=B, audit-agent,
    translate-agent with no new agent. No synthesis step;
    `analyse-agent type=B` already produces the full
    `vault/papers/{slug}.md` indistinguishable from
    `process-author` Phase 4 output. Trigger phrases: "处理这篇论文",
    "process paper", "跑这篇 paper", "summarize this paper".
  - Historical implementation plan docs were removed after completion; the
    active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
    the skill / agent files.
  - No bin changes, no Python changes, no user-disk migration.
    process-author manifests with `status: acquired` from earlier
    runs are consumed unchanged; new `status: year_mismatch` /
    `year_ambiguous` entries are treated as `acquired` by downstream
    Phase 3+ (file is on disk, just with a year warning attached).

- **0.27.0** (2026-05-18): **local-agent for cndouban backfill +
  douban_cn related-version probe.** Splits "find the Chinese
  translation of this book" out of the audit pipeline into its
  own narrow-scope agent, and gives the douban_cn source the
  capability to surface translations from a direct hit's other-versions
  block.
  - `agents/local-agent.md` (new): the only agent in quasi whose
    job is filling `cndouban: [...]` onto book frontmatter and
    maintaining `.quasi/audit/translations.json`. Reads
    `quasi-audit run --mode check --json`, filters
    `needs_backfill[]` to `type=book` + `missing=cndouban`, calls
    `quasi-search book --subject cndouban`, writes back. Idempotent
    on already-localised records (even `cndouban: []` is treated
    as "user already decided no Chinese edition exists" and
    skipped).
  - `scripts/search/sources/douban_cn.py`: new related-version
    probe path. When the caller passes `--subject
    zh/chinese/cn/translation/cndouban` **and** the direct search
    returns a hit, the source walks the subject page's `其他版本`
    / `同一作品` block and emits Chinese-like manifestations. Hint
    regex covers mainland presses (人民/三联/商务/译林/中信...)
    plus HK/TW patterns (聯經/時報/麥田/遠流/天下/印書館). Subject
    URL + works URL both normalised against `book.douban.com`.
    Pure addition — non-`zh` queries are unchanged; CJK-author
    fallback to works-page enumeration still triggers when direct
    returns empty.
  - `skills/process-book/SKILL.md`: new Step 6 LOCALISE, dispatched
    foreground after audit. Resume table documents the
    "frontmatter already has `cndouban` ⇒ skip" idempotency.
  - `skills/process-journal/SKILL.md`: Step 6 grows the same
    audit-escalation loop that `process-book` has had — items the
    audit escalates get one regeneration pass via `analyse-agent`
    (type B for journal papers), then re-audit; if still escalated,
    report and bail. Brings the two skills into structural parity.
  - `scripts/audit/audit.py` + `scripts/audit/sweep/README.md`:
    docstring/prose updates reflecting that online metadata
    backfill is its own workflow, not orchestrated by `audit-agent`.
    Sweep README's "Integration plan (future)" section is now
    just "Integration" — `quasi-audit backfill` is the actual
    dispatcher.
  - `agents/search-agent.md`: drop one redundant "不要在 prompt 里
    推该调哪个源" paragraph — the I/O contract already covers this.
  - `tests/test_douban_cn_en2zh.py` (new): end-to-end mock-driven
    test for the English-title → Chinese-translation pipeline.
    `test_source_douban_cn.py` grows a case proving the
    related-version probe fires when `--subject zh` and direct hits
    exist, and stays out of the way otherwise.
  - `docs/`: delete four stale design docs —
    `ADR-002-capability-layering.md`, `LAYERS.md`,
    `EXPERIENCE-vault-metadata-backfill.md`,
    `processing-schema.md`. The layered architecture they
    described was simplified away in 0.18.0; keeping them around
    misled both humans and Claude Code sessions opened in the
    source tree.

- **0.26.0** (2026-05-18): **artifact path discipline.** Sharpens the
  `processing/` vs `.quasi/` split on "would the user ever open this
  file?" Everything plumbing-shaped — manifests, indices, audit state,
  dispatch scratch, downloaded temp PDFs — moves into `.quasi/`.
  `processing/` ends minimal: `chapters/` (extracted text the user
  reads when PDFs are unclear) and `translations/` (translated PDFs).
  - Group B: `processing/proofread/{stem}/sections.json` →
    `.quasi/proofread/{stem}/`. Cleanup goes from optional to required.
  - Group C: `/tmp/{journal,topic,snowball}-pdfs/` →
    `.quasi/temp/{journal-pdfs/{name}, topic-pdfs/{name}, snowball-pdfs}/`.
    Brings temp PDFs into the project tree where they're inspectable
    and not subject to macOS /tmp/ reaping.
  - Group D: audit pipeline consolidates under `.quasi/audit/`.
    `scripts/typecheck/typecheck.py` `OUT_DIR` moves from `.quasi/`
    top-level to `.quasi/audit/`. `agents/audit-agent.md` doc paths
    fixed across multiple stale references (state.json,
    translations.json, typecheck-*). `scripts/schemas/book.py` description
    string + `docs/ARCHITECTURE.md` echo updated.
  - Group E: `processing/authors/{name}/manifest.json` →
    `.quasi/authors/{name}/manifest.json`. Driver file for the
    process-author phase state machine; user never opens.
  - Group A: residual cleanup. The bulk of the citation move was
    already merged in 0.22.x (`ct_dir = .quasi/citation/...`); this
    release finishes the trailing edges — citecheck-agent example,
    citation.py docstring, wrap-up 中间产物 tree. `render.py:741`
    has a stale reference too but render.py is deprecated per 0.22.0
    and skipped here.
  - User-disk migration: only `authors/{name}/manifest.json` carries
    a real caveat — any author run paused mid-flight loses its
    `--resume` state on upgrade. Finish or abandon before upgrading.
    Other stale dirs (`processing/citation/`, `processing/proofread/`,
    `processing/audit/`, top-level `.quasi/typecheck-*`) become
    harmless orphans the user can `rm -rf` at leisure.
  - Historical implementation plan docs were removed after completion; the
    active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
    the skill / agent files.

- **0.25.2** (2026-05-18): **rename citation-agent → citecheck-agent.**
  Naming consistency pass: most agents in quasi are verb-form
  (`search-agent` / `download-agent` / `extract-agent` / `proofread-agent` /
  `translate-agent` / `audit-agent` / `analyse-agent`); `citation-agent`
  was a noun-form outlier. Renamed to `citecheck-agent` (compare
  "spellcheck") to bring it into line.
  - `agents/citation-agent.md` → `agents/citecheck-agent.md` (`git mv` +
    frontmatter `name:` update).
  - Caller / cross-reference updates in `skills/wrap-up/SKILL.md`
    (Phase 2.2 dispatch + prose), `agents/proofread-agent.md` (cross-ref
    in 不动清单), `docs/ARCHITECTURE.md` (pattern table + DAG).
  - Historical references in `CLAUDE.md` Recent Changes entries
    (0.16 / 0.17 / 0.18 / 0.20 / 0.22 / 0.25.1) and in the committed
    spec / plan docs are **left intact** — they record what the agent
    was called at the time.
  - Caller-visible breaking change: any external invocation
    `Agent("quasi:citation-agent", ...)` must switch to
    `Agent("quasi:citecheck-agent", ...)`. All in-tree callers updated
    in the same commit.

- **0.25.1** (2026-05-18): **citation-agent vault-grounded judgment.**
  Phase 2.2 of `quasi:wrap-up` historically had `citation-agent` judge
  context-fit by reading `biblio.json` metadata fields
  (`title / journal / themes / publisher`) plus LLM prior knowledge.
  That meant judgments for obscure / non-English / idiosyncratically-read
  works degraded into hallucination. Re-grounded:
  - `agents/citation-agent.md` rewritten so each candidate is judged by
    reading the user's actual vault summary file (`vault/papers/{slug}.md`
    or `vault/books/{slug}/00-overview.md`) via `candidate.path` — already
    present in manifest since 0.17.0. New "严禁仅凭 title / publisher /
    LLM 先验知识判断" guard in the judgment guidance.
  - `biblio.json` dropped from the agent's input contract.
    `skills/wrap-up/SKILL.md` Phase 2.2 dispatch no longer passes
    `biblio:` to the agent. `biblio.json` is still produced upstream and
    consumed by `resolve.py` (for manifest building) and `emit_bib.py`
    (for the final .bib) — those uses are unchanged.
  - No Python script changes. `path` field on candidate was already
    propagated from `biblio.py:230` → `resolve.py:101` since the 0.17.0
    citation refactor; this release just starts using it.
  - Token cost: net byte volume to the agent goes **down** (drops a
    whole-vault frontmatter index, picks up a handful of scoped summary
    reads per batch). Main-process context unaffected — same prompt
    shape with one fewer path.
  - Historical implementation plan docs were removed after completion; the
    active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
    the skill / agent files.

- **0.25.0** (2026-05-18): **agent surface cleanup post-search-refactor.**
  Lands the long-lived `quasi-arch-refactor` branch into main and tidies
  the agent file naming after 0.24.0's atomic search-bin cutover.
  - `agents/new-discover-agent.md` → `agents/search-agent.md` (146 → 119
    lines). Frontmatter `name:` updated; content rewritten against the
    new bin: dropped the trust/priority table (bin does
    `match_and_priority` internally), dropped per-source fallback table
    (bin internal fallback handles douban_cn works-page / etc), fixed
    envelope shape to `{kind, query, results, diagnostics}`, corrected
    source counts (8 book + 3 paper), confidence heuristic now keyed on
    `sources_hit` + `conflicts`, output protocol renamed
    `DISCOVER_RESULT` → `SEARCH_RESULT`.
  - `agents/discover-agent.md` deleted — superseded by `search-agent`;
    all callers (process-author, wrap-up Phase 2.5, process-book Step 0)
    migrated on the refactor branch.
  - `process-author/SKILL.md` and `scripts/search/context.md` rename
    references updated.
  - No bin-layer change. Pure agent file rename + caller rewire.

- **0.24.0** (2026-05-17): **search bin complete refactor (BREAKING).**
  Historical implementation plan docs were removed after completion; the
  active contract is captured in `README.md`, `docs/ARCHITECTURE.md`, and
  the skill / agent files.
  - 2137-line `scripts/search/search.py` replaced by sectioned ~700-line
    `search.py` + 9 per-platform adapters in `sources/`.
  - CLI: only two verbs left — `quasi-search book` / `quasi-search paper`.
    `metadata` / `validate` / `scholar` / `backfill` / `cndouban` / `books` /
    `papers` removed entirely (no back-compat).
  - AA file-locate moved to `scripts/download/aa.py` (Python import only,
    no CLI verb). `download-agent` calls it directly.
  - Backfill dispatcher + sweep scripts moved to `scripts/audit/`.
    `quasi-audit backfill --strategy X` replaces `quasi-search backfill`.
  - Unpaywall / S2 / Wayback adapters dropped (enrich cascade non-goal).
  - Conflict surfacing: every fan-out call's diagnostics carries
    `conflicts[].evidence` for year / isbn_13 / publisher / page_count /
    authors — process-book Step 0 YEAR_TRIAGE now reads this rather than
    re-calling each source. Generalises 0.21.0's `year_signals` hack.
  - Callers migrated in same PR: `new-discover-agent.md` (delete routing
    table), `process-book` / `process-topic` / `process-author` /
    `wrap-up` (verb rename + remove validate/metadata batch calls),
    `download-agent.md` (AA via Python import), `discover-agent.md`
    (verb rename + delete validate/scholar).

- **0.22.0** (2026-05-17): **citation review pivots to TUI — HTML report
  + structured verdict enum deprecated.** Background: 0.20.0's tab-based
  HTML review still had a coarse fit between agent output shape and what
  the user actually had to do per cite — and earlier reflection on the
  Decisions Report json export (274 entries, ~10% had unstructured-note
  carryover that the buckets couldn't capture) showed the agent's
  structured verdict was both token-wasteful and less useful than a
  short context-fit note. User's diagnosis: "我们之前犯的错就是太结构化了".
  - **citation-agent rewritten** to output a minimal `{key, picked_slug,
    flag, note}` per cite. Drops the 4-way verdict enum (ok /
    context-mismatch / maybe-vault-typo / missing-from-vault) entirely.
    Agent only does two things now: pick the bib_source from candidates
    (single → the only one; multi → context-fittest), and flag ok or
    review for upper-layer triage. Note is free-form Chinese.
  - **wrap-up Phase 2 restructured** into 2.1 parse+resolve → 2.2
    citation-agent (single+multi only) → 2.3 discover-agent recover
    (miss only) → **2.4 TUI 审定** → 2.5 decisions.json + emit-bib.
    Phase 2.4 is a main-process AskUserQuestion loop, walking bins in
    dimension order (`review_single` / `review_multi` / `miss_recover` /
    `miss_orphan`) — `flag=ok` cites auto-accept with no user prompt.
    Each prompt shows mention snippet + agent's picked_slug + note;
    options vary by bin (accept / pick another candidate / mark
    draft-rewrite / vault-todo / skip).
  - **HTML review.html no longer driven by the skill.** `render.py` /
    `quasi-helpers citation render` is retained on disk but is now
    **stale** — it expects the old verdict enum (`ok` / `context-mismatch`
    / `maybe-vault-typo` / `missing-from-vault`) and will not render
    cleanly against the new `{key, picked_slug, flag, note}` batch
    format. Will be either rewritten against the new shape or deleted
    in a future minor; not blocking. The Phase 3 SUMMARY HTML is
    dropped — TUI prints a final stats block + paths inline.
  - **decisions.json schema preserved at the seams** — top level still
    `by_key: {key: {bib_source, decision, note}}` (what emit_bib.py
    consumes via `_pick_vault_slug`) plus `vault_todo[]` and
    `draft_rewrites[]` arrays for the user's follow-up work. emit_bib
    unchanged.
  - `--citation-only` flag now skips Phase 0/1/3 (cleanup), runs only
    Phase 2 (parse → agent → recover → TUI → emit). `--no-recover` still
    skips 2.3.

- **0.21.0** (2026-05-17): **year triage overhaul — N-source contract,
  structured PDF year signals, Google Books via dokobot.** Triggered by a
  failure case where Simondon's *Imagination and Invention* (UMN Press
  English translation, canonical year 2023) kept finalising as 2022.
  Root causes were 4 independent bugs stacked:
  - `_guess_year` in `scripts/download/download.py` returned the *first*
    `\b(?:19|20)\d{2}\b` regex hit in front matter — for translations this
    is almost always the original-language year ("Originally published in
    French as ... 1965"). Replaced with `_extract_year_signals` returning
    a structured dict `{first_published, copyright_year, original_year,
    other_years, best_guess, evidence_text}`. Anchors on
    "First published / First edition / Published" patterns, treats
    "Copyright YEAR" separately, and never lets "Originally published"
    or "Translated from" leak into best_guess. Includes a Q4-press
    heuristic: if `copyright == YEAR` and `YEAR+1` or `YEAR+2` also
    appears in front matter, prefer the later one (typical for press
    books copyrighted in Q4 and shipped the following year).
    `verify_book_file` returns `year_signals` alongside `year`;
    `finalize_book_identity` propagates it into the manifest entry.
    Back-compat shim `_guess_year` still exists, calling
    `_extract_year_signals(...)["best_guess"]`.
  - `process-book/SKILL.md` Step 0 prompt previously asked the agent
    for a slug / ol / pdf 3-way compare but named the discover-side year
    `ol_year` regardless of which source it came from — almost always
    Anna's Archive, since AA is the only source that yields an MD5.
    Rewritten as YEAR_TRIAGE: agent reports per-source years separately
    (`source_years: {google_books, openlibrary, openalex, anna_archive}`),
    per-pattern PDF signals (`pdf_signals: {first_published,
    copyright_year, original_year, other_years}`), a `recommended_year`
    with a one-line `recommendation_reason`, and a `verdict ∈ {MATCH,
    MISMATCH, AMBIGUOUS}`. Only `MATCH` finalises the file rename;
    other verdicts keep the `.tmp.{ext}` and surface the full triage
    block to the skill main process for user adjudication.
    `download-agent.md` finalize-doc updated to describe the new
    `year_signals` field and the N-source contract.
  - `search_google_books` was hitting the unauthenticated
    `googleapis.com/books/v1/volumes` endpoint, which returns HTTP 429
    with `RATE_LIMIT_EXCEEDED` (quota=0 on the default project) — i.e.
    the Google Books source was silently dead, cutting cross-verification
    from 3 sources to 2 without anyone noticing. Refactored into
    `_search_google_books_http` (existing path) + `_search_google_books_via_doko`
    (new, scrapes `google.com/search?tbm=bks` via `dokobot read --local`,
    falls back to remote mode if no bridge installed). Wrapper detects
    HTTP 429 / `RATE_LIMIT_EXCEEDED` and dispatches automatically.
    Returns parsed entries (title / authors / year via `AUTHOR · YEAR`
    pattern) plus a `raw_doko_text` field so agents can re-parse when
    the structured parse looks thin.
  - The agent-prompt heuristic "pdf_year = 出现的最大 published year,
    排除 reprint dates" couldn't distinguish copyright year from
    publication year — the new N-source contract makes the agent
    enumerate both `copyright_year` and `first_published` separately
    instead, so the skill main process sees the actual structure.

  Net: Simondon's book now triages as `pdf_signals.first_published=2023,
  pdf_signals.copyright_year=2022, pdf_signals.original_year=1965`,
  GB+OL=2023, AA=2022 — `recommended_year=2023` with reason "first_published
  beats copyright by 1 year (Q4 press lag)", and the slug `-2017` shows
  up as MISMATCH for user correction rather than auto-finalising to 2022.

- **0.20.0** (2026-05-17): **citation review UI — tabs by dimension,
  decisions grouped by side-effect.** Background: the previous review.html
  rendered a flat table with uniform `✓ ✗ ?` per row whose "✓ accept agent
  suggestion" semantics differed wildly across statuses (apply draft rewrite
  / run vault mv / pick candidate / nothing-to-apply for `ok`). User found
  the buttons misleading — particularly `ok` rows showing "accept" when
  there's nothing to accept, and a sea of `?` for rows agent didn't process.
  - render.py: replaced the 3-state filter (全部/需处理/已通过) with a
    7-tab nav by display_status: 全部 / 挑候选 / 修 draft / 修 vault /
    补 vault / 等 agent / ✓ 通过. Each tab shows count.
  - new `_action_widget()` renders per-dimension actions:
      ok                  → "✓ 通过" read-only badge
      pending             → "⏳ 等 agent" read-only badge
      context-mismatch    → [✓ 应用] [✗ 保留原引] (default 应用)
      maybe-vault-typo    → [✓ 执行 rename] [✗ 忽略] (default 忽略;
                            renames are destructive, opt-in)
      missing-from-vault  → [✓ 加待跑] [✗ 忽略] (default 加 if Phase 2.5
                            recovered with ≥medium confidence)
      multi-hit           → badge → "展开选 bib chooser radio"
  - JS exportDecisions now emits 4 grouped buckets:
      draft_rewrites     (context-mismatch + applied)
      vault_renames      (maybe-vault-typo + applied)
      vault_todo         (missing-from-vault + applied)
      multi_hit_picks    (multi-hit + bib chosen)
    plus a `skipped` group and a flat `by_key` for backward compat.
  - apply-bar at top of report instructs user to run
    `quasi-helpers citation apply <decisions.json>` (subcommand not yet
    implemented — coming in next minor version; for now decisions.json
    is enough to drive things manually).

- **0.19.1** (2026-05-17): wrap-up `--citation-only` flag.
  Skips Phase 0 (audit) + Phase 1 (proofread) + Phase 4 (cleanup), runs
  Phase 2 + 2.5 + 3 only. Use after补 vault'd a few books — re-emit bib
  in seconds without re-proofreading. Also documents `--no-recover` and
  `--audit-first` flags more explicitly in the call-shape section.

- **0.19.0** (2026-05-17): **wrap-up Phase 2.5 — online citation recovery.**
  When citation-agent flags an entry as `missing-from-vault`, the existing
  flow could only say "vault 缺,补完再重跑". This release adds an online
  step: discover-agent gains a new `mode=recover-citation` that takes the
  citation key + author + year_hint + mention_context + citation-agent's
  prior-knowledge guess, hits quasi-search (Crossref/OL/AA + scholar
  fallback), and emits an `online_recovery` record with title / author /
  year / ISBN / DOI / publisher / confidence / suggested_slug /
  process_book_cmd. wrap-up dispatches one discover-agent per missing
  entry in parallel (cap 4) after citation-agent finishes; render.py
  merges `verdicts/recovery-*.json` into the review UI so each
  missing row shows a "🔍 在线 recover" block with the recovered ID.
  This converts vault-todo from "list of names to look up" into "list of
  ready-to-paste `/quasi:process-book {slug}` commands". Opt-out with
  `/quasi:wrap-up <draft> --no-recover` to skip the online step.

- **0.18.1** (2026-05-17): process-book Step 0 hardening.
  - Self-dispatches download-agent when `sources/{slug}.{epub,pdf}` is
    absent — no longer bails out telling the user to "先用 process-author".
    The skill is orchestration; acquisition is part of orchestration.
  - download-agent prompt now replicates process-author's
    discover→download→finalize 3-stage chain (N=1 version): pre-download
    `quasi-search books` records `ol_year`, post-download Read PDF first
    3 pages records `pdf_year`, 3-way compare against `slug_year`. Any
    mismatch returns `YEAR_MISMATCH` report (skill main process decides
    whether to correct slug or accept) — file kept as `.tmp.{ext}` until
    resolution. Prevents the "user-supplied slug year propagating through"
    failure mode (e.g. user passes `simondon-...-2024` for a book whose
    canonical first English edition is 2023).

- **0.18.0** (2026-05-17): **Layer-cleanup refactor (BREAKING).** End-to-end
  rework of the bin / agent / skill split per `docs/LAYERS.md` and
  `docs/ARCHITECTURE.md`. Drives Pattern B (skill 直调 bin) out of the
  layer model by aggregating skill helpers into a single `quasi-helpers` bin.
  - **bins**: 13 → 6. Deletions: `quasi-typecheck`,
    `quasi-autofix-mechanical`, `quasi-proofread`, `quasi-citation`,
    `quasi-extract-{epub,ocr,split}`, `quasi-journal-{fetch,report}`,
    `quasi-synthesize-refs`. The last three are **deletion-as-forcing-
    function**: synthesis-agent's journal/topic mode will fail until the
    refs-extraction redesign (Q3) and journal stack rework land. New:
    `quasi-audit {check|fix|emit-bib}` (vault consistency dispatcher),
    `quasi-helpers {proofread|citation} <sub>` (skill orchestration aggregator).
    Subcommand restructure: `quasi-extract {epub|ocr|split}`,
    `quasi-download {paper|book|batch|finalize}` (was flag-based),
    `quasi-search` + `scholar` (dokobot Google Scholar) + `backfill`
    (vault metadata multi-source chain; ingests bts/scripts 8 sweep scripts
    documented in `docs/EXPERIENCE-vault-metadata-backfill.md`).
  - **agents**: `typecheck-agent` → `audit-agent` with new online
    metadata backfill responsibility. `analyze-agent` → `analyse-agent`
    (British spelling). `overview-agent` + `profile-agent` + 原 `synthesis-agent`
    → unified `synthesis-agent` with caller-passed `mode = book|author|
    journal|topic|kb-update`. `scan-agent` / `setup-agent` marked DEPRECATED
    (files retained, not dispatched by new code).
  - **skills**: `citation-snowball/` → `process-topic/` (rename only,
    internal redesign deferred). `wrap-up/SKILL.md` now calls `quasi-helpers
    {proofread,citation} *` and gains a Phase 0 audit-agent dispatch.
    `process-book` / `process-author` migrated to `synthesis-agent(mode=X)` +
    `audit-agent`.
  - **Deferred** (next round): entire journal stack
    (`quasi-journal-{fetch,report}` / `scan-agent` / `/quasi:process-journal`
    skill / `quasi-search journal` subcommand); `setup-agent` redesign;
    `process-topic` internal redesign; `quasi-synthesize-refs` disposition.

- **0.17.0** (2026-05-17): **Citation pipeline refactor — biblio.json as ground truth.**
  Driven by ADR-002 (see `docs/ADR-002-capability-layering.md`): citation
  flow now reads a pre-computed `biblio.json` instead of glob-walking the
  vault each call. New artefacts in `scripts/citation/`:
  - `biblio.py` scans vault frontmatter into `biblio.json` (multi-segment
    author-slug indexing so multi-word surnames like `agard-jones` /
    `fausto-sterling` resolve correctly)
  - `resolve.py` rewritten: input is `parse.json` + `biblio.json`,
    output is `manifest.json` with `{single-hit, multi-hit, miss}` status
    and 4-tier fuzzy fallback (strict → author-only → fuzzy author+year → miss)
  - `render.py` rewritten: single-decision review UI, bib chooser per row,
    top banner for missing-from-vault + maybe-vault-typo
  - `emit_bib.py` (new) renders BibTeX from `biblio.json` keyed by the draft's
    citation set; honours user-picked `bib_source` from decisions.json
  - `citation.py` subcommands: `biblio` / `parse` / `resolve` / `render` /
    `emit-bib` (removed `run` — orchestration belongs in the skill, not the CLI)
  `citation-agent` rewritten as **offline universal consistency judge**
  (no WebFetch / WebSearch): verdict ∈ `{ok, context-mismatch,
  maybe-vault-typo, missing-from-vault}`. Online cross-checking for vault
  metadata moves out of citation entirely (slated for `quasi-audit` in a
  future release). `skills/wrap-up/SKILL.md` is **not yet updated** for the
  new pipeline — TODO next.
- **0.16.0** (2026-05-15): **New `quasi:wrap-up` skill + two reusable agents**
  (`proofread-agent`, `citation-agent`). Drift finalisation in one shot —
  Phase 1 proofread (per-section parallel agents in-place edit typos /
  punctuation / spacing), Phase 2 citation (parse + vault lookup CLI →
  per-batch parallel agents do online cross-verification against Crossref /
  Anna's / Douban via dokobot), Phase 3 summary HTML linking both reports.
  Design rule: **skills only exist for composition; single-task work is
  done by dispatching agents directly** — so no standalone `citation` or
  `proofread` skills. New files: `skills/wrap-up/SKILL.md`,
  `agents/{proofread,citation}-agent.md`,
  `scripts/{proofread,citation}/*.py`,
  `bin/quasi-{proofread,citation}`. Citation parse-step ships a loose-scan
  validator (any paren-with-4-digit-year) to catch what the strict parser
  misses before downstream consumers see the data.
- **0.15.3** (2026-05-13): Doc/script rename — `$PWD` → `$CLAUDE_PROJECT_DIR`
  across all 11 agent prompts, `bin/quasi-typecheck`, and the two typecheck
  scripts' docstrings/help. Aligns with the official plugins-reference
  recommendation: `$CLAUDE_PROJECT_DIR` is set by Claude Code at session start
  and doesn't drift if anything `cd`s; `$PWD` is just the shell's transient
  cwd. `typecheck.py` / `autofix_mechanical.py` `PROJECT_ROOT` resolution now
  consults `CLAUDE_PROJECT_DIR` between the existing `QUA_PROJECT_ROOT`
  escape hatch and the `os.getcwd()` fallback — no behavior change when
  invoked from the project root (the common case), but stable under `cd`.
- **0.15.2** (2026-05-12): PreToolUse hook also propagates `CLAUDE_PLUGIN_ROOT`
  and `CLAUDE_PLUGIN_DATA` to bash subprocesses (in addition to the userConfig
  `QUASI_*` block). Before this, the shims fell back to `~/.cache/quasi/.venv`
  for the venv because `$CLAUDE_PLUGIN_DATA` was unset in Bash-tool env, even
  though the SessionStart hook had already materialised the venv at the
  official `$CLAUDE_PLUGIN_DATA/.venv` (= `~/.claude/plugins/data/<id>/.venv`).
  Now shims use the official path. Users with the old fallback venv can
  `rm -rf ~/.cache/quasi/.venv` to reclaim disk.
- **0.15.1** (2026-05-12): Trim `setup-agent.md` (166 → 122 lines). Drop the
  obsolete "credentials don't live here" callout and "调用方约定 (主 Claude 应
  AskUserQuestion 收集凭据)" section — neither makes sense after 0.15.0's hook
  bridge. No functional change.
- **0.15.0** (2026-05-12): **Breaking.** Final config resolution: PreToolUse hook
  bridge. The docs claim `CLAUDE_PLUGIN_OPTION_*` env vars reach "plugin
  subprocesses" but empirically Bash-tool subprocesses don't get them — only
  hooks/MCP/LSP/monitor do. Solution: a PreToolUse(Bash) hook
  (`scripts/hooks/inject-userconfig.py`) runs in a real plugin subprocess, reads
  its env, and prepends `export QUASI_<KEY>=...; ` to any `quasi-*` shell
  command before Claude Code executes it. Scripts read clean `QUASI_*` env
  vars. Sensitive userConfig fields stay in the macOS keychain — they only
  materialise in the hook+bash process env for one tool call at a time. Also
  renames all `bin/qua-*` shims to `bin/quasi-*`. Probe agent removed.
- **0.14.1–0.14.3** (2026-05-12): Diagnostic releases — probe agents and probe
  hooks to map out which subprocess types actually receive `CLAUDE_PLUGIN_OPTION_*`
  env injection. Results: only the 4 documented types (hook/MCP/LSP/monitor) do;
  Bash-tool subprocesses and Task-tool subagents do not. Drove the 0.15.0 design.
- **0.14.0** (2026-05-12): **Breaking.** Anna's Archive and Immersive Translate
  credentials follow CookieCloud into plugin `userConfig`. New userConfig fields:
  `anna_donator_key` (sensitive), `anna_mirrors` (multiple, defaults to 3 official
  mirrors), `immersive_auth_key` (sensitive). `download.py` / `search.py` /
  `immersive_translate.py` no longer read `config/anna-archive.json` or
  `config/immersive-translate.json` — fully env-var driven. `setup-agent` becomes
  purely permissions + system deps + dokobot indicator; the entire `$CLAUDE_PROJECT_DIR/config/`
  directory is now optional and quasi never writes there.
- **0.13.0** (2026-05-12): EZProxy creds moved to `userConfig` (CookieCloud).
  Removed `config/cookiecloud.json` and `config/ezproxy.json` reading.
- **0.12.1** (2026-05-12): Drop `setup-agent` Step 0 (plugin self-install bootstrap).
  Installation is now the canonical `/plugin marketplace add giraphant/quasi` +
  `/plugin install quasi@ramu-toolkit` flow; `setup-agent` is purely env + creds.
  README install section rewritten to match.
- **0.12.0** (2026-05-12): CookieCloud auto-refresh for EZProxy. Initial `config/
  cookiecloud.json` + `config/ezproxy.json` file-based flow — superseded by 0.13.0.
- **0.11.0** (2026-05-12): Python venv extracted from per-shim inline pip into a
  `SessionStart` hook + bootstrap script. Shims now ~half the size. Persistent venv
  lives in `$CLAUDE_PLUGIN_DATA` (or `~/.cache/quasi/`), never in plugin root.
- **0.10.0**: SPEC v0.2 schema + typecheck-agent + bin shims.
- **0.9.0**: Unified setup-agent (bootstrap + config).

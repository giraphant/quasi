# quasi maintainer guide

quasi is a Claude Code plugin for academic reading workflows: discovery, download, extraction, analysis, synthesis, translation, and schema checking.

## Important plugin-system facts

- Installed plugins load components from root-level `skills/`, `agents/`, `bin/`, `hooks/`, `monitors/`, `.mcp.json`, and `.lsp.json`.
- `.claude-plugin/plugin.json` is metadata only. Do not place components inside `.claude-plugin/`.
- This `CLAUDE.md` helps humans and Claude Code sessions opened inside the quasi source tree, but Claude Code does not load a plugin-root `CLAUDE.md` as context when quasi is installed as a plugin.

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

- **0.24.0** (2026-05-17): **search bin complete refactor (BREAKING).**
  Spec: `docs/superpowers/specs/2026-05-17-search-refactor-design.md`.
  Plan: `docs/superpowers/plans/2026-05-17-search-refactor.md`.
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

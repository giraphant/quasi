# process-book / process-author reorchestration + new process-paper — Design

Date: 2026-05-18
Affects:
`skills/process-book/SKILL.md`,
`skills/process-author/SKILL.md`,
`skills/process-paper/SKILL.md` (new),
`agents/download-agent.md`,
`agents/search-agent.md` (caller call-shape examples only),
`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (skill registration + version bump)
Version target: 0.28.0 (minor — skill orchestration rework + download-agent
output protocol extension + one new skill; no bin API change, no
user-disk migration)

## Background

quasi's `process-book` and `process-author` skills were written before the
0.24.0 search-bin refactor and the 0.25.0 agent surface cleanup. Both
skills predate:

- **search bin's strict envelope** — `quasi-search book|paper` now returns
  a `{results, diagnostics}` envelope where `diagnostics.conflicts[]`
  carries per-source evidence on year / isbn_13 / publisher / page_count
  / authors. Callers are expected to read this directly rather than
  re-call each source.
- **search-agent's strict 5-field input contract** — caller must pass
  `task / context / constraints / output_path / output_schema`. Free-form
  prompts no longer parse.
- **download-agent's `{kind, items[], output_dir}` contract** — the
  legacy `manifest + mode=both` shape is gone. Books and papers must be
  dispatched as separate calls.
- **Path discipline 0.26.0** — `.quasi/` for plumbing (manifests,
  indices, audit state), `processing/` for user-readable intermediates,
  `vault/` for final products.

Additionally, quasi has analyse-agent `type=B` for single-paper analysis
and translate-agent for per-paper translation, but **no user-facing skill
that orchestrates discover → download → analyse for a single paper**.
process-author does this in batch; process-topic does this in citation
snowballs; there is no granular single-paper entry point.

## Problems

### 1. process-book Step 0 has YEAR_TRIAGE inlined as agent-prompt addendum

The current `skills/process-book/SKILL.md` Step 0 dispatches
download-agent with a ~80-line prompt that bolts the YEAR_TRIAGE
protocol onto the agent's main responsibility. The agent must, in one
call:
- call `quasi-search book`
- pick a best-match candidate
- call `quasi-download book get --md5`
- read PDF front matter
- compute per-source year evidence
- compute per-pattern PDF year signals
- compute a `recommended_year`
- emit a free-form `YEAR_TRIAGE` block in plain text

The YEAR_TRIAGE block is **prose embedded in the agent's reply**, parsed
back out by the skill main process via string matching (`if result.contains("YEAR_TRIAGE") and (result.contains("MISMATCH") or result.contains("AMBIGUOUS")):`).
This is fragile, doesn't compose with other callers, and conflates
**evidence collection + verdict computation** (genuinely agent work)
with **decision presentation** (genuinely caller work).

### 2. process-author Phase 1 + Phase 2 do not match new contracts

- **Phase 1 DISCOVER** dispatches search-agent with a narrative prompt
  ("查找该学者的代表作 — 5 books, 10 papers, sorted by citations"). The
  agent's input contract since 0.25.0 requires `task / context.kind /
  constraints / output_path / output_schema` as structured fields. The
  narrative prompt either errors immediately or relies on the agent
  best-guessing the contract.
- **Phase 2 ACQUIRE** dispatches download-agent with `mode: both` against
  a single combined manifest. The agent's input contract since 0.24.0 is
  `{kind: "book"|"paper", items: [...], output_dir}`. There is no
  `mode: both`; books and papers must be two separate calls.

### 3. process-author silently ignores year discrepancies

process-author batch acquisition has no analog of process-book's
YEAR_TRIAGE. A book downloaded with `slug-year=2022` but whose front
matter says `first_published=2023` finalises silently into
`sources/{slug}-2022.pdf` and is analysed under the wrong year. The
user only catches this when reading the final author overview, by
which point a re-run is expensive.

### 4. No single-paper skill exists

Users who have one paper to process (a PDF a colleague sent, a single
citation found by hand) must currently either:
- run `quasi:process-topic` with a 1-paper seed (wrong semantics —
  snowball is for corpora);
- or invoke analyse-agent type=B manually with hand-built dispatch
  parameters and worry about sourcing the PDF themselves.

Neither is acceptable for a workflow tool whose other granularities
(book, author, topic, journal) all have dedicated skills.

## Principles (the rules we'll enforce going forward)

1. **Agents own evidence + verdict; callers own decision.** Anything
   computable from inputs by a deterministic rule belongs in the agent
   protocol as a structured return field. Anything requiring human
   judgment (or batch policy choice) belongs in the caller.
2. **Skill ↔ agent contracts are structured, not prose.** No string-match
   parsing of agent replies. If a skill needs a field, the agent
   protocol declares it.
3. **One skill per granularity.** Book / paper / author / topic / journal
   each get a dedicated skill with consistent shape: dispatch search →
   dispatch download → dispatch analysis → dispatch synthesis (if
   needed) → audit → localise.
4. **batch vs interactive policy is the caller's choice, not the agent's.**
   download-agent does not know whether its caller can pause for user
   input. It always returns the same structured envelope; callers
   decide whether `verdict=MISMATCH` triggers `AskUserQuestion`
   (process-book single-book) or just writes a warning to manifest
   (process-author batch).

## Design

### A. download-agent output protocol extension

`DOWNLOAD_RESULT.per_item` entries with `kind=book` gain a structured
`year_evidence` sub-object. The agent computes verdict by a fixed rule;
callers read it.

New per-item shape (book):

```yaml
- kind: book
  slug: simondon-imagination-and-invention-2017
  status: ok | year_mismatch | year_ambiguous | download_failed
  path: sources/{slug}.{ext}            # present iff status == ok
  tmp_path: sources/{slug}.tmp.{ext}    # present iff status in {year_mismatch, year_ambiguous}
  source: anna_archive | ...
  year_evidence:
    slug_year: 2017
    source_years:                       # mirrors search bin diagnostics.conflicts[field==year].evidence
      openlibrary: 2023                 # only sources that actually returned a year appear here;
      openalex:    2023                 # errored/empty sources are omitted (they're in
      google_books: 2023                # search bin's diagnostics.errors[], not propagated)
      anna_archive: 2022
    pdf_signals:                        # mirrors download bin metadata.year_signals
      first_published: 2023
      copyright_year:  2022
      original_year:   1965
      other_years:     []
    recommended_year: 2023
    recommendation_reason: "first_published beats copyright by 1y (Q4 press lag); 3/4 sources agree"
    verdict: MATCH | MISMATCH | AMBIGUOUS
```

Per-item shape (paper) is unchanged — papers have no version ambiguity
once DOI is fixed, so no `year_evidence` field.

`status` derivation:
- `verdict == MATCH` → `status: ok`, file `mv`'d from tmp to final,
  `path` set, `tmp_path` absent.
- `verdict == MISMATCH` → `status: year_mismatch`, file kept as tmp,
  `tmp_path` set, `path` absent.
- `verdict == AMBIGUOUS` → `status: year_ambiguous`, same as mismatch.
- download itself failed → `status: download_failed`, no path/tmp_path,
  no year_evidence.

Verdict computation rule (codified in `agents/download-agent.md`):

- `recommended_year` preference order: `pdf.first_published` > multi-source
  mode > `pdf.copyright_year`.
- Translation books explicitly exclude `pdf.original_year` from
  candidates (that is the original-language year, not this edition's).
- `MATCH` iff `slug_year == recommended_year` AND at least two
  sources/pdf-signals agree on `recommended_year`.
- `MISMATCH` iff `slug_year != recommended_year` AND evidence is
  unambiguous (one clear `recommended_year` candidate).
- `AMBIGUOUS` iff evidence is too scattered for a single
  `recommended_year` (e.g. three sources disagree, no PDF signal
  arbitrates).

### B. process-book Step 0 — thin caller

Step 0 becomes a thin dispatch + verdict branch. No more 80-line
prompt; the agent's protocol carries the structured output.

```
if not Glob(f"sources/{book_slug}.{epub,pdf}"):
    result = Agent("quasi:download-agent", foreground=True, prompt=f"""
      kind: book
      items: [{{ slug: {book_slug}, expected_author: ..., expected_title: ... }}]
      output_dir: sources/
    """)
    item = result.per_item[0]
    if item.status == "ok":
        pass  # continue to Step 1 EXTRACT
    elif item.status in ("year_mismatch", "year_ambiguous"):
        # emit year_evidence verbatim to user; do not auto-mv tmp.
        # user either: changes slug + re-runs, OR manually mv tmps + re-runs.
        report_year_triage_to_user(item.year_evidence, item.tmp_path)
        return
    else:  # download_failed
        report(f"download-agent failed to acquire {book_slug}")
        return
```

The `expected_author` and `expected_title` are parsed from the slug
inline in the skill: slugs are `{author}-{title}-{year}` with year as the
trailing 4-digit segment, author as the leading segment(s), title as
the middle. Skill main process splits and passes both fields as
agent input. (No shared helper today; if the same split logic
appears in process-author and process-paper too, it can be lifted to
`scripts/util/slug.py` in a follow-up — out of scope for this work.)

Steps 1-6 (EXTRACT, READ MANIFEST, PARALLEL ANALYSIS, BOOK OVERVIEW,
AUDIT, LOCALISE) are unchanged.

### C. process-author rewire

**Phase 1 DISCOVER** — two structured search-agent calls, one per kind.

```
# Books
search-agent dispatch:
  task: "find top 5 books by {full_name} on topic {topic}, sorted by citations"
  context:
    kind: book
    author: {full_name}
    topic: {topic}
  constraints:
    count: 5
    sort: citations
    write_policy: create
  output_path: .quasi/authors/{author_slug}/books.json
  output_schema: [{slug, title, year, isbn_13, authors, citation_count}]

# Papers
search-agent dispatch:
  task: "find top 10 papers by {full_name} on topic {topic}, sorted by citations"
  context:
    kind: paper
    author: {full_name}
    topic: {topic}
  constraints:
    count: 10
    sort: citations
    write_policy: create
  output_path: .quasi/authors/{author_slug}/papers.json
  output_schema: [{slug, title, year, doi, journal, authors, citation_count}]
```

The skill then merges both files into the existing manifest shape
`.quasi/authors/{author_slug}/manifest.json` with `books[]` and
`papers[]` arrays, each entry annotated `status: discovered`.

**Phase 2 ACQUIRE** — two structured download-agent calls, one per
kind.

```
# 2a. Books
download-agent dispatch:
  kind: book
  items: [
    {slug, expected_author, expected_title}
    for book in manifest.books
  ]
  output_dir: sources/

# Skill merges results back into manifest, per-book. Manifest status
# names mirror agent status with one rename (agent's "ok" →
# manifest's "acquired" — preserves existing manifest schema):
#   acquired             (agent: ok)
#   year_mismatch        (agent: year_mismatch)
#   year_ambiguous       (agent: year_ambiguous)
#   failed               (agent: download_failed)
# Additional fields populated by the skill when present in agent return:
#   year_evidence: {...}   (verbatim from agent's per_item[i].year_evidence)
#   year_warning: "..."    (skill-derived one-liner for the final report,
#                            iff status in {year_mismatch, year_ambiguous})

# 2b. Papers
download-agent dispatch:
  kind: paper
  items: [
    {slug, expected_author, expected_title, identifiers: {doi}}
    for paper in manifest.papers
  ]
  output_dir: sources/

# Papers have no year_evidence. Failed papers → status: failed, listed
# in the terminal report so the user can hand-fix DOIs.
```

**Policy difference from process-book**: `year_mismatch` /
`year_ambiguous` books **do not pause the batch**. The skill main
process knowingly overrides the agent's "keep as tmp" signal — it
`mv`'s `tmp_path` → `sources/{slug}.{ext}` (slug as the user wrote it
remains authoritative; the recommended year is recorded as a warning
but does not rename the file), records the full `year_evidence` block
in `manifest.books[i].year_warning`, and proceeds to extract / analyse
under the user-supplied slug. The terminal report at the end of process-author lists
"K books finalised with year-evidence warnings; review
`.quasi/authors/{slug}/manifest.json` and re-run individual books via
`/quasi:process-book` if needed."

Rationale: batch interrupt cost > deferred-review cost. process-author
users have already committed to a multi-hour run; pausing on each
ambiguous book defeats the workflow. The warning is preserved with
full evidence so the user can re-run targeted books cheaply.

Phases 3-7 (PROCESS BOOKS, PROCESS PAPERS, SYNTHESIS, AUDIT, LOCALISE)
are unchanged except for one path check: confirm all writes to
`.quasi/authors/...` rather than `processing/authors/...` (0.26.0
migration target).

### D. New `process-paper` skill

A minimal orchestrator for "I have one paper". Lives at
`skills/process-paper/SKILL.md`. Trigger phrases: "处理这篇论文",
"process paper", "跑这篇 paper", "summarize this paper".

Args (one of):
- `--doi {doi}` — preferred, deterministic
- `--slug {slug}` — if PDF already in `sources/{slug}.pdf`
- `--title {title} --author {author}` — fallback for hand-typed cases

Flow:

```
Step 0  ENSURE METADATA + SOURCED
  if --slug and Glob(sources/{slug}.pdf):
      # PDF already in sources/. Metadata sourcing, in order:
      #   1. if vault/papers/{slug}.md exists → read its frontmatter (title, authors, year, doi, journal)
      #   2. else → dispatch search-agent with write_policy=verify-only to get metadata
      #            without writing to vault (analyse-agent in Step 1 produces the vault file)
      # Either way, paper_metadata is fully populated before Step 1.
  else:
      # search-agent verify-only / create
      search-agent dispatch:
        task: "find paper {doi or title+author}"
        context: {kind: paper, doi?: ..., title?: ..., author?: ...}
        constraints: {count: 1, write_policy: create}
        output_path: .quasi/papers/{slug}.search.json
        output_schema: {slug, title, authors, year, doi, journal, ...}

      # download-agent kind=paper, single item
      download-agent dispatch:
        kind: paper
        items: [{slug, expected_author, expected_title, identifiers: {doi}}]
        output_dir: sources/

      if download_failed: report + return

Step 1  ANALYSE
  analyse-agent (type=B) dispatch:
    source_file: sources/{slug}.pdf
    output_path: vault/papers/{slug}.md
    metadata: paper_metadata
  → vault/papers/{slug}.md

Step 2  AUDIT (always-on, cheap)
  audit-agent dispatch:
    target: vault/papers/{slug}.md
  if escalated: re-dispatch analyse-agent overwrite=true; re-audit once.

Step 3  TRANSLATE (opt-in via --translate flag)
  if args.translate:
    translate-agent dispatch:
      slug: {slug}
    → processing/translations/{slug}-zh.pdf
```

No synthesis step — analyse-agent type=B already produces the full
vault file in one shot.

### E. Skill registration

`.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` add
`process-paper` to the skills list. Version bump to 0.28.0.

### F. Scope explicitly excluded

- **No bin changes.** search bin and download bin are stable post-0.24.0;
  this work is pure agent-protocol + skill-orchestration.
- **No search-agent rewrite.** The 5-field contract is already in place
  since 0.25.0; this work only updates *callers* to use it correctly.
- **No process-topic / process-journal changes.** Those skills have
  their own download/search call-sites that may need similar updates,
  but they're out of scope for QUA-29.
- **No batch year-triage UI.** process-author does not gain
  `AskUserQuestion` per book. The year_evidence is preserved in
  manifest for offline review.
- **No vault schema changes.** `vault/papers/{slug}.md` frontmatter
  shape is unchanged; process-paper produces files indistinguishable
  from those process-author and process-topic produce.

## Migration

User-disk:
- Existing `sources/`, `vault/papers/`, `vault/books/`, `vault/authors/`
  files are untouched.
- Existing in-flight `.quasi/authors/{name}/manifest.json` files remain
  consumable — Phase 2 acquire reads the same `manifest.books` /
  `manifest.papers` arrays, just writes them via different agent calls.
- Resume mid-run after this release: if the manifest already shows
  `status: acquired` for some books, those are skipped on re-run as
  before. New `status: year_mismatch | year_ambiguous` entries are
  treated as `acquired` for downstream phases (file is on disk, just
  with a year warning).

Caller code (in-tree only — no external callers):
- All in-tree dispatches of download-agent already pass `{kind, items[], output_dir}`
  shape after 0.24.0; this work tightens existing call-sites, doesn't
  introduce a new shape.
- Skill prompt strings change substantially; agent files change
  modestly (download-agent gains the `year_evidence` protocol section).

## Open questions

None remaining — design questions settled during brainstorming:
1. YEAR_TRIAGE belongs in the agent protocol (settled: yes, as
   `year_evidence`).
2. process-author should NOT pause on year mismatch (settled: batch
   policy is "log + continue").
3. process-paper supports `--translate` flag (settled: yes, low cost,
   keeps single-skill experience coherent).

## Success criteria

- `/quasi:process-book` runs end-to-end on a fresh slug, exercising the
  new download-agent year_evidence path. Both `verdict=MATCH` and
  `verdict=MISMATCH` cases work (test: re-run an existing book with a
  wrong year in the slug).
- `/quasi:process-author` runs end-to-end for a small author (2 books,
  3 papers), with at least one paper that DOI-fails (verifies the new
  fail-fast behavior reports cleanly in the manifest).
- `/quasi:process-paper --doi {doi}` produces `vault/papers/{slug}.md`
  identical in structure to what process-author Phase 4 produces.
- `/quasi:process-paper --doi {doi} --translate` additionally produces
  `processing/translations/{slug}-zh.pdf`.
- `agents/download-agent.md` documents the `year_evidence` protocol
  including the verdict computation rule.
- No regressions in process-topic, wrap-up, process-journal (verified
  by `grep -r 'quasi:download-agent\|quasi:search-agent' skills/`
  showing only the two updated callers + process-paper as new caller).

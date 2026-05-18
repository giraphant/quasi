# processing/ schema reference

Conventions for everything quasi writes under `$CLAUDE_PROJECT_DIR/processing/`
(intermediate artefacts, never authoritative; vault frontmatter is truth).

## audit/state.json — per-vault audit state

Single file (per-vault granularity, LAYERS.md §3 Q7a). Written by
`audit-agent` after each full run. No incremental tracking — agent
re-scans the whole vault each time and rewrites this file.

```json
{
  "version": 1,
  "last_audited_at": "2026-05-17T14:23:11Z",
  "vault_root": "/Users/.../bts",
  "clean": false,
  "checks": {
    "local": {
      "files_checked": 952,
      "files_with_violations": 18,
      "files_modified": 7,
      "remaining_violations": 11
    },
    "online": {
      "ran": false,
      "strategies": [],
      "publisher_filled": null,
      "isbn_filled": null,
      "doi_filled": null,
      "review_files": []
    }
  },
  "notes": "free-form summary string from audit-agent"
}
```

**Fields**:

- `clean` (bool) — `true` iff local check finished with 0 remaining_violations
  AND online check (if ran) produced 0 review-flagged entries.
  wrap-up skill's Phase 0 reads this flag to decide whether to re-run audit.
- `checks.local` — populated by `quasi-audit check` / `quasi-audit fix`.
- `checks.online` — populated only when audit-agent runs with `backfill: true`.
  `strategies` is the ordered list of `quasi-search backfill --strategy X`
  invocations performed in this run. `review_files` lists the paths of
  `*-mismatch.tsv` / `*-isbn-notfound.tsv` / `*-still-missing.tsv` left for
  the user.

## audit/translations.json — Chinese-edition cache (single file)

Written by `audit-agent` Step 4B. Single file, douban_id keyed, full-vault
中译本 metadata cache. Vault `cndouban: [int]` frontmatter field stores
just the IDs; full detail lives here.

```json
{
  "26689038": {
    "title": "赋身以性：性别政治和性的建构",
    "author": "安妮·福斯托-斯特林",
    "translator": "秦海花 / 秦文 / 叶红",
    "publisher": "江苏凤凰教育出版社",
    "year": 2015,
    "isbn": "9787549954025",
    "original_title": "Sexing the Body",
    "ratings_count": 30,
    "douban_url": "https://book.douban.com/subject/26689038/",
    "found_for_book": "fausto-sterling-sexing-the-body-2000",
    "first_seen": "2026-05-17",
    "last_seen": "2026-05-17"
  }
}
```

Merge semantics: same `douban_id` from another vault book run updates
non-null fields and bumps `last_seen`; `first_seen` is preserved.

Source-of-truth pairing: vault book frontmatter's `cndouban: [id, ...]`
field is the **authoritative** list per book (three-state: absent = not
yet queried; `[]` = queried, no translations; `[ids...]` = found).
`translations.json` is the **derived** detail cache;
regenerate-able from re-running `quasi-search cndouban` for any slug.

## biblio — derived view, NO standalone cache

biblio is **not** cached. Two callable derivations from vault frontmatter:

```
quasi-audit emit-bib            -o vault-biblio.json        # full vault
quasi-helpers citation emit-bib --biblio ... -o draft.bib   # per-draft subset
```

Both walk `vault/papers/*.md` + `vault/books/*/00-overview.md` frontmatter
on every call. Costs are modest (~1k files, sub-second).

## citation/{draft-stem}/ — per-draft scratch

```
processing/citation/{draft-stem}/
├── parse.json       # quasi-helpers citation parse
├── manifest.json    # quasi-helpers citation resolve
├── agents/
│   └── batch-NNN.json   # citation-agent verdicts (one per parallel batch)
├── report.html      # quasi-helpers citation render
└── references.bib   # quasi-helpers citation emit-bib (draft-level subset)
```

Survives wrap-up runs. Deleting is safe — next wrap-up re-creates everything
from current vault state.

## proofread/{draft-stem}/ — per-draft scratch

```
processing/proofread/{draft-stem}/
└── sections.json    # quasi-helpers proofread split
```

The proofread *record* lives inside the draft itself (between
`<!-- proofread:start --> ... <!-- proofread:end -->` markers), not in
this scratch dir. wrap-up Phase 4 cleanup removes the markers from the
draft; deleting this directory is independent.

## authors/{author-slug}/manifest.json — discover/download state

Author processing pipeline state machine (legacy, pre-0.18.0 shape).
Per-entry status transitions: `discovered → metadata_found → acquired →
processed`. Shape documented in `agents/discover-agent.md` and
`agents/download-agent.md`.

## chapters/{book-slug}/ — extract intermediates

```
processing/chapters/{book-slug}/
├── manifest.json    # chapter list with slot/title/start/end
└── *.txt            # raw chapter text from quasi-extract {epub|split}
```

Consumed by `analyse-agent` during book processing, then can be cleaned up.

## translations/{slug}-{lang}.pdf — translate output

quasi-translate output. Survives runs; user moves them out manually.

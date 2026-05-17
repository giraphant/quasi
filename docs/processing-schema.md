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

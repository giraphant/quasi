# sweep/ — vault metadata backfill scripts

Migrated from `~/Documents/Learn/bts/scripts/` (2026-05-17).

Each script is a **single-source, single-pass sweep** that walks
`vault/books/*/00-overview.md` (or `vault/papers/*.md`), queries one
metadata source, and writes back missing/empty fields. **Never
overwrites non-empty values** — fail-safe by design.

| script | what it does | source |
|---|---|---|
| `sweep-book-fm-clean.py` | Local-only: clean frontmatter (drop wikilinks, normalize titles) | — |
| `sweep-book-fm-meta.py` | Crossref `works?query.bibliographic=...` | Crossref |
| `sweep-book-fm-meta-aa.py` | Anna's Archive title search | AA |
| `sweep-book-fm-meta-aa-by-md5.py` | AA `/md5/<hash>` direct (0 误匹配) | AA |
| `sweep-book-fm-meta-aa-from-slug.py` | AA strict filter by slug (last resort) | AA |
| `sweep-book-fm-meta-oa.py` | OpenAlex → DOI → Crossref re-validate | OA + CR |
| `sweep-book-fm-meta-ol-fallback.py` | OpenLibrary search.json (fallback) | OL |
| `sweep-book-fm-ol-isbn-reverse.py` | OL `/isbn/{ISBN}.json` reverse + local regex cleanup | OL |

See `plugins/quasi/docs/EXPERIENCE-vault-metadata-backfill.md` for the
empirically-derived fallback chain (clean → CR → AA-title → AA-md5 →
OL-ISBN-reverse → manual). Hit rates, pitfalls, and source strengths
documented there.

## Entry points

These are dispatched by `quasi-search backfill --strategy <name>`. They
also run as standalone scripts for ad-hoc fixes:

```bash
python3 sweep-book-fm-meta.py --vault ~/path/to/vault [strategy-specific args]
```

## Integration plan (future)

These scripts currently each carry their own argparse + main(). The
target architecture (LAYERS.md) has `audit-agent` orchestrating the
chain — calling `quasi-search backfill --strategy X` for each source,
then doing local regex cleanup + writeback decisions in the agent.

For now: bin/quasi-search exposes `backfill` as a thin dispatcher to
the individual sweep scripts, preserving the standalone-runnable shape.

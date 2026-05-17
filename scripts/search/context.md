# Search Module Context

## Purpose
Two-verb academic search bin — `book` and `paper` — fanning out across per-platform adapters and merging into canonical record schemas. Search-only: enrich-writeback / validate / file-locate / backfill are caller's responsibility, not this bin's.

## Architecture
- `search.py` (~700 lines, 5 sections: SCHEMAS / MERGE / BOOK / PAPER / CLI)
- `sources/` — one file per platform (openalex / crossref / openlibrary / googlebooks / scholar / goodreads / storygraph / amazon / douban_cn). Each declares `SUPPORTS ∈ {book, paper, both}` and exports `search_book(BookQuery)` and/or `search_paper(PaperQuery)` returning `AdapterResult`.
- `tests/` — schema / merge / main + one per source

See `plugins/quasi/docs/superpowers/specs/2026-05-17-search-refactor-design.md` for design + `plugins/quasi/docs/superpowers/plans/2026-05-17-search-refactor.md` for migration history.

## Key Components
- `book_search(query, sources=None)`: parallel adapter fan-out, merge to BookRecord
- `paper_search(query, sources=None)`: same for PaperRecord
- `match_and_priority_merge_with_conflicts(by_source, kind)`: ISBN/DOI exact + fuzzy title+year clustering; per-field priority list picks chosen value; conflict-prone whitelist fields (`year` / `isbn_13` / `publisher` / `page_count` / `authors`) surface multi-source evidence in `diagnostics.conflicts`
- `BookRecord` / `PaperRecord`: fixed-key dataclass schemas with None/[]/"" filling missing fields
- `BookQuery` / `PaperQuery`: typed CLI inputs (isbn/doi/title/author/subject/query + filters)

## CLI Subcommands
- `book` — search books across all book-supporting adapters
- `paper` — search papers across all paper-supporting adapters

Removed since 0.24.0 (no back-compat): `books`, `papers`, `metadata`, `validate`, `scholar`, `backfill`, `cndouban`.

## Dependencies
- Internal: used by `new-discover-agent`, `discover-agent`, skill main processes of process-book / process-topic / process-author / wrap-up
- External APIs: OpenAlex, Crossref, OpenLibrary, Google Books (HTTP + dokobot fallback for 429), Google Scholar (HTML scrape with proxy support)
- Scrapers: Goodreads, StoryGraph (curl_cffi), Amazon, Douban CN (direct + dokobot for works-page)
- Python: requests, beautifulsoup4, curl_cffi (all in scripts/requirements.txt)

## API Notes
- **Crossref**: free, no auth, polite pool via `mailto` param. Best for humanities DOI coverage. Author search uses relevance sort + surname post-filter (citation-count sort buries niche authors).
- **OpenAlex**: free, no auth. `ids.isbn` filter is unreliable — fall back to `?search=ISBN` (the adapter does this transparently). Provides citation counts, OA status, abstracts (via inverted index).
- **Google Scholar**: HTML scrape, fragile. UA rotation + exponential backoff + CAPTCHA detection. Optional `QUASI_GOOGLE_SCHOLAR_PROXY_URL` env var. Both books and papers emitted via `[BOOK]` title-prefix discrimination.
- **Google Books**: HTTP path returns 429 frequently — adapter falls back to `dokobot read` on google.com/search?tbm=bks. DSL via `q=isbn:X` / `inauthor:Y` / `intitle:Z`.
- **Douban CN**: direct subject lookup (no dokobot) as primary; falls back to dokobot-driven works-page enumeration only when primary empty AND (CJK author OR subject=zh).

## Not in this bin (moved out in 0.24.0)
- **Anna's Archive file search** → `scripts/download/aa.py` (Python import only)
- **Vault backfill sweep dispatcher** → `quasi-audit backfill --strategy X`
- **Paper metadata enrich cascade (OA→CR→UP→S2→Wayback)** — dropped; OpenAlex covers most fields directly. Caller can chain via `paper --doi X` if more is needed.
- **DOI validate** — dropped; caller uses `curl -I https://doi.org/X` directly.

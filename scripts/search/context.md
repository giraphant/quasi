# Search Module Context

## Purpose
Unified academic search — books, papers, and metadata lookup across multiple APIs.

## Key Components
- `search_author_papers()`: Multi-source author paper search (OpenAlex + Crossref), merged and deduplicated
- `search_books()`: Multi-source book search (Google Books, OpenLibrary, OpenAlex)
- `search_aa()`: Anna's Archive HTML scraping for file search
- `search_paper_metadata()`: Multi-source metadata enrichment cascade (OpenAlex → Crossref → Unpaywall → S2 → Wayback)
- `validate_doi()`: HEAD request to doi.org, returns True if DOI resolves
- `validate_manifest_dois()`: Batch validate + Crossref recovery for all papers in manifest
- `query_crossref_title()`: Title-based DOI discovery via Crossref
- `search_crossref_author_papers()`: Author paper search via Crossref with surname filtering

## CLI Subcommands
- `books` — Search books across Google Books / OpenLibrary / OpenAlex / Anna's Archive
- `papers` — Search papers by author (default: OpenAlex + Crossref dual-source)
- `metadata` — Lookup/enrich paper metadata by DOI or title
- `validate` — Validate DOIs in manifest or single DOI check

## Recent Changes
- 2026-04-25: Added Crossref integration (author search, title search, DOI lookup)
- 2026-04-25: Added DOI validation (`validate_doi`, `validate` CLI subcommand)
- 2026-04-25: `search_author_papers()` upgraded to multi-source with merge/dedup
- 2026-04-25: `search_paper_metadata()` cascade now includes Crossref between OpenAlex and Unpaywall

## Dependencies
- Internal: used by discover-agent, download-agent (indirectly)
- External APIs: OpenAlex, Crossref, Unpaywall, Semantic Scholar, Wayback Machine, Google Books, OpenLibrary
- Optional: requests + beautifulsoup4 (for Anna's Archive only)

## API Notes
- Crossref: free, no auth, polite pool via `mailto` param. Best for humanities DOI coverage.
- OpenAlex: free, no auth. Best for citation counts and OA status.
- Crossref author search uses relevance sorting + surname post-filter (citation-count sorting buries niche authors).

"""sources/ — per-platform adapter modules.

Each module exports:
    SUPPORTS: list[str]           # ["book"] | ["paper"] | ["book", "paper"]
    SOURCE_ID: str                # canonical lowercase id (matches schemas.source_ids keys)

    def search_book(query: BookQuery) -> AdapterResult:  # if "book" in SUPPORTS
    def search_paper(query: PaperQuery) -> AdapterResult: # if "paper" in SUPPORTS

Adapters return raw entries (their private shape) + per-source diagnostics.
Main search functions (book_search / paper_search in search.py) handle
normalisation to BookRecord/PaperRecord and cross-source merging.

This package's __init__.py just lists available modules. Import them
explicitly by name in search.py (so missing/broken adapters fail
loudly at top of import).
"""

# Modules registered here as they land in Phase 4. The book_search /
# paper_search main functions iterate this registry by ID.

BOOK_ADAPTERS = [
    "openalex", "openlibrary", "googlebooks", "scholar",
    "goodreads", "storygraph", "amazon", "douban_cn",
]

PAPER_ADAPTERS = [
    "openalex", "crossref", "scholar",
]

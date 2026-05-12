"""Type registry: maps canonical type names to schema + body schema pairs.

Also tracks deprecated type aliases for autofix migration.
"""

from typing import Type
from pydantic import BaseModel

from .author import AuthorSchema
from .book import BookSchema
from .chapter import ChapterSchema
from .paper import PaperSchema
from .body import (
    BodySchema,
    AUTHOR_BODY,
    BOOK_BODY,
    CHAPTER_BODY,
    PAPER_BODY,
)


# ─── canonical type → (frontmatter schema, body schema) ────────

TYPE_REGISTRY: dict[str, tuple[Type[BaseModel], BodySchema]] = {
    "author":  (AuthorSchema,  AUTHOR_BODY),
    "book":    (BookSchema,    BOOK_BODY),
    "chapter": (ChapterSchema, CHAPTER_BODY),
    "paper":   (PaperSchema,   PAPER_BODY),
}


# ─── deprecated type aliases ──────────────────────────────────
# Old → canonical. Used by migration / typecheck to know what to rename.

TYPE_ALIASES: dict[str, str] = {
    "author-profile":             "author",
    "author":                     "author",  # identity for vault files using bare 'author'

    "book-overview":              "book",
    "book-analysis":              "book",
    "monograph":                  "book",
    "monograph-analysis":         "book",
    "overview":                   "book",
    "book":                       "book",  # identity for vault files using bare 'book'

    "chapter-summary":            "chapter",
    "chapter-analysis":           "chapter",
    "book-chapter":               "chapter",
    "book_chapter":               "chapter",
    "chapter":                    "chapter",

    "paper-analysis":             "paper",
    "paper-summary":              "paper",
    "article-analysis":           "paper",
    "journal-article":            "paper",
    "journal-article-analysis":   "paper",
    "paper":                      "paper",
}


def canonical_type(raw: str | None) -> str | None:
    """Return the canonical type name for a (possibly old) type string.

    Returns None for unknown types (including malformed values like 'A').
    """
    if not raw or raw == "A":
        return None
    return TYPE_ALIASES.get(raw)


def schema_for_type(raw: str | None) -> tuple[Type[BaseModel], BodySchema] | None:
    """Convenience: look up (frontmatter schema, body schema) by raw type string."""
    canon = canonical_type(raw)
    if not canon:
        return None
    return TYPE_REGISTRY.get(canon)

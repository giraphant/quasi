"""quasi-vault schema definitions (Pydantic V2 + dataclasses).

Frontmatter schemas (Pydantic):
    AuthorSchema · BookSchema · ChapterSchema · PaperSchema

Body schemas (dataclass):
    AUTHOR_BODY · BOOK_BODY · CHAPTER_BODY · PAPER_BODY

Registry:
    TYPE_REGISTRY    — canonical type → (frontmatter schema, body schema)
    TYPE_ALIASES     — old type names → canonical
    canonical_type() — string → canonical | None
    schema_for_type() — string → (schemas) | None

See SPEC.md for the spec; this module is its executable form.
"""

from .primitives import Name, Title, ShortString, Year, Rating, DOI
from .author import AuthorSchema
from .book import BookSchema
from .chapter import ChapterSchema
from .paper import PaperSchema
from .body import (
    BlockKind,
    BodySection,
    BodySchema,
    AUTHOR_BODY,
    BOOK_BODY,
    CHAPTER_BODY,
    PAPER_BODY,
)
from .registry import (
    TYPE_REGISTRY,
    TYPE_ALIASES,
    canonical_type,
    schema_for_type,
)

__all__ = [
    # primitives
    "Name", "Title", "ShortString", "Year", "Rating", "DOI",
    # frontmatter schemas
    "AuthorSchema", "BookSchema", "ChapterSchema", "PaperSchema",
    # body
    "BlockKind", "BodySection", "BodySchema",
    "AUTHOR_BODY", "BOOK_BODY", "CHAPTER_BODY", "PAPER_BODY",
    # registry
    "TYPE_REGISTRY", "TYPE_ALIASES",
    "canonical_type", "schema_for_type",
]

__version__ = "0.2.0"

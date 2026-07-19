"""quasi-vault schema definitions (Pydantic V2 + dataclasses).

See SPEC.md for the spec; this module is its executable form.
"""

from .primitives import Name, Title, ShortString, Year, Rating, DOI
from .author import AuthorSchema
from .book import BookSchema
from .chapter import ChapterSchema
from .image import ImageSchema
from .journal import JournalSchema
from .note import NoteSchema
from .paper import PaperSchema
from .talk import TalkSchema
from .topic import TopicSchema
from .transcript import TranscriptSchema
from .body import (
    BlockKind,
    BodySection,
    BodySchema,
    AUTHOR_BODY,
    BOOK_BODY,
    CHAPTER_BODY,
    IMAGE_BODY,
    JOURNAL_BODY,
    NOTE_BODY,
    PAPER_BODY,
    TALK_BODY,
    TOPIC_BODY,
    TRANSCRIPT_BODY,
)
from .registry import (
    TYPE_REGISTRY,
    TYPE_ALIASES,
    DEPRECATED_TYPE_ALIASES,
    canonical_type,
    deprecated_canonical_type,
    schema_for_type,
)

__all__ = [
    # primitives
    "Name", "Title", "ShortString", "Year", "Rating", "DOI",
    # frontmatter schemas
    "AuthorSchema", "BookSchema", "ChapterSchema",
    "ImageSchema", "JournalSchema", "NoteSchema", "PaperSchema",
    "TalkSchema", "TopicSchema", "TranscriptSchema",
    # body
    "BlockKind", "BodySection", "BodySchema",
    "AUTHOR_BODY", "BOOK_BODY", "CHAPTER_BODY",
    "IMAGE_BODY", "JOURNAL_BODY", "NOTE_BODY", "PAPER_BODY",
    "TALK_BODY", "TOPIC_BODY", "TRANSCRIPT_BODY",
    # registry
    "TYPE_REGISTRY", "TYPE_ALIASES", "DEPRECATED_TYPE_ALIASES",
    "canonical_type", "deprecated_canonical_type", "schema_for_type",
]

__version__ = "0.7.1"

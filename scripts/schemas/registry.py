"""Type registry: maps canonical type names to schema + body schema pairs."""

from __future__ import annotations

from typing import Type
from pydantic import BaseModel

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


TYPE_REGISTRY: dict[str, tuple[Type[BaseModel], BodySchema]] = {
    "author":     (AuthorSchema,     AUTHOR_BODY),
    "book":       (BookSchema,       BOOK_BODY),
    "chapter":    (ChapterSchema,    CHAPTER_BODY),
    "image":      (ImageSchema,      IMAGE_BODY),
    "journal":    (JournalSchema,    JOURNAL_BODY),
    "note":       (NoteSchema,       NOTE_BODY),
    "paper":      (PaperSchema,      PAPER_BODY),
    "talk":       (TalkSchema,       TALK_BODY),
    "topic":      (TopicSchema,      TOPIC_BODY),
    "transcript": (TranscriptSchema, TRANSCRIPT_BODY),
}


DEPRECATED_TYPE_ALIASES: dict[str, str] = {
    "author-profile": "author",
    "book-overview": "book",
    "book-analysis": "book",
    "monograph": "book",
    "monograph-analysis": "book",
    "overview": "book",
    "chapter-summary": "chapter",
    "chapter-analysis": "chapter",
    "book-chapter": "chapter",
    "book_chapter": "chapter",
    "paper-analysis": "paper",
    "paper-summary": "paper",
    "article-analysis": "paper",
    "journal-article": "paper",
    "journal-article-analysis": "paper",
    "journal-synthesis": "journal",
    "topic-synthesis": "topic",
    "snowball-synthesis": "topic",
    "citation-snowball-synthesis": "topic",
    "reading-list": "topic",
    "research-note": "topic",
    "concept-note": "topic",
}

TYPE_ALIASES = DEPRECATED_TYPE_ALIASES


def canonical_type(raw: str | None) -> str | None:
    """Return raw only when it is already a canonical type name."""
    if not raw or raw == "A":
        return None
    return raw if raw in TYPE_REGISTRY else None


def deprecated_canonical_type(raw: str | None) -> str | None:
    """Return the replacement for an old type alias, without accepting it."""
    if not raw or raw == "A":
        return None
    return DEPRECATED_TYPE_ALIASES.get(raw)


def schema_for_type(raw: str | None) -> tuple[Type[BaseModel], BodySchema] | None:
    """Look up (frontmatter schema, body schema) by canonical type string."""
    canon = canonical_type(raw)
    if not canon:
        return None
    return TYPE_REGISTRY.get(canon)

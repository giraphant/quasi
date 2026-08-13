"""Webpage schema: a captured HTTP(S) page and its analysed record."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .primitives import Name, Rating, ShortString, Title


WebURL = Annotated[
    str,
    StringConstraints(min_length=8, max_length=2048, strip_whitespace=True),
]


class WebpageSchema(BaseModel):
    """The semantic metadata for one captured webpage."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["webpage"]
    title: Title
    url: WebURL
    captured_at: datetime = Field(strict=False)
    authors: list[Name] = Field(default_factory=list)
    published: Optional[date] = Field(default=None, strict=False)
    site: Optional[ShortString] = None
    themes: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    rating: Optional[Rating] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("url must be a credential-free HTTP(S) URL")
        return value

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, value: datetime) -> datetime:
        if (
            value.tzinfo is None
            or value.utcoffset() != timedelta(0)
            or value.microsecond != 0
        ):
            raise ValueError("captured_at must be UTC at whole-second precision")
        return value

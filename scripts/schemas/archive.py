"""One archival material; originals and provenance are described by archive_manifest.py."""

from __future__ import annotations

from datetime import date as Date
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .primitives import Name, Rating, Title


class ArchiveSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["archive"]
    title: Title
    kind: Literal["patent", "thread", "post", "video", "image", "webpage", "document"]
    created: Date = Field(strict=False, description="本库建档日期，不是原文发布日期或快照时间")
    creator: list[Name] = Field(default_factory=list)
    date: Optional[Date] = Field(default=None, strict=False, description="已核实的原材料完整发布日期；更新日期或部分日期写正文，未知省略")
    source: Optional[str] = Field(default=None, description="来源平台、发布机构或转存出处")
    url: Optional[str] = Field(default=None, description="材料原始直接链接，与 manifest 共同出处对应")
    themes: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    rating: Optional[Rating] = None

    @field_validator("created", "date", mode="before")
    @classmethod
    def full_calendar_date(cls, value):
        # YAML supplies date objects; quoted dates must still be whole ISO days.
        # Do not coerce timestamps or partial dates into invented calendar dates.
        if value is None or type(value) is Date:
            return value
        if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return value
        raise ValueError("date must be a full YYYY-MM-DD calendar date")

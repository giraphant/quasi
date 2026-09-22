"""Reader-facing Archive inventory; never a workflow cursor or completion score."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ArchiveSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=8, max_length=4096, pattern=r"^https?://")
    title: Optional[str] = None


class ArchiveFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(pattern=r"^originals/[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+$")
    title: str = Field(min_length=1, description="可读原件标题，优先使用原网页或章节标题")
    description: str = Field(min_length=1, description="简述原件对象、内容或在材料中的作用；不推断未读媒体内容")
    media_type: str = Field(min_length=3)
    captured_at: datetime = Field(strict=False)
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Optional[ArchiveSource] = None
    # Original asset URL is technical provenance, distinct from its page/source.
    url: str = Field(min_length=8, max_length=4096, pattern=r"^https?://")

    @field_validator("title", "description")
    @classmethod
    def nonblank_display_text(cls, value):
        if not value.strip():
            raise ValueError("original title and description must be nonblank")
        return value.strip()

    @field_validator("captured_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("capture time must include a timezone")
        return value


class ArchiveManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["quasi.archive.manifest/0.2"] = "quasi.archive.manifest/0.2"
    source: ArchiveSource
    files: list[ArchiveFile] = Field(default_factory=list)
    coverage: str = ""

    @model_validator(mode="after")
    def unique_files(self):
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("duplicate original path")
        return self

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
    media_type: str = Field(min_length=3)
    captured_at: datetime = Field(strict=False)
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Optional[ArchiveSource] = None
    # Original asset URL is technical provenance, distinct from its page/source.
    url: str = Field(min_length=8, max_length=4096, pattern=r"^https?://")

    @field_validator("captured_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("capture time must include a timezone")
        return value


class ArchiveManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["quasi.archive.manifest/0.1"] = "quasi.archive.manifest/0.1"
    source: ArchiveSource
    files: list[ArchiveFile] = Field(default_factory=list)
    coverage: str = ""

    @model_validator(mode="after")
    def unique_files(self):
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("duplicate original path")
        return self

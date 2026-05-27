"""note schema: 自由笔记或批注。"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from .primitives import Title


class NoteSchema(BaseModel):
    """A lightweight freeform note or annotation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["note"]
    title: Title
    created: date = Field(strict=False)
    annotates: Optional[str] = Field(default=None)
    themes: list[str] = Field(default_factory=list)

"""transcript schema: talk 的带时间戳全文转写页。

文件位置: vault/talks/<slug>/transcript.md
SPEC: ../SPEC.md § 3.10

机器生成(多引擎集成转写),tracked。正文自由(带 `[hh:mm:ss]` 时间戳段落),
无固定 H2 结构 —— 与 note/image 一样是 lightweight body 类型。`talk` 字段
反向引用所属 talk 的 slug。
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .primitives import ShortString, Title


class TranscriptSchema(BaseModel):
    """A timestamped full transcript belonging to one talk."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["transcript"]
    title: Title
    talk: ShortString = Field(description="所属 talk 的 slug(反向引用)")

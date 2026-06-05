"""talk schema: 会议/讲座录制的结构化摘要页。

文件位置: vault/talks/<slug>/talk.md
SPEC: ../SPEC.md § 3.9

talk 是对一场录制(video/audio)的转写 + 结构化摘要。转写本体是同目录的
`transcript.md`(type: transcript);媒体本体 `recording.<ext>` 不入库(gitignore)。

frontmatter 极简 7 项,顺序固定: type / title / date / speaker / themes /
rating / media。`speaker` 用讲者姓名(可关联 vault/authors/);`themes` 复用
全库标准标签词表;静音/失败录制 speaker、themes 可空(省略)。
"""

from __future__ import annotations

from datetime import date as _Date
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from .primitives import Name, Title, ShortString, Rating


class TalkSchema(BaseModel):
    """A talk / lecture recording analysis."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["talk"]

    # ─── 必填 ─────────────────────────────────────────────
    title: Title
    date: _Date = Field(strict=False, description="录制日期(整日 ISO,如 2024-11-08)")

    # ─── 可选 ─────────────────────────────────────────────
    speaker: list[Name] = Field(
        default_factory=list,
        description="讲者姓名数组(可关联 vault/authors/);抽不到留空(省略整键)",
    )
    themes: list[str] = Field(
        default_factory=list,
        description="主题标签数组(复用全库 themes 词表);静音/失败录制可空",
    )
    rating: Optional[Rating] = Field(default=None)
    media: ShortString = Field(description="媒体文件名,如 recording.mov(gitignore)")

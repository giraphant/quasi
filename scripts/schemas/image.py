"""image schema: 本地图片对象 metadata。

文件位置: vault/images/<slug>/image.md
SPEC: ../SPEC.md § 3.8

图片文件本体是同目录的 `original.<ext>`,由路径约定派生,不写进 frontmatter。
描述性字段(creator/date/source/themes/rating)全部可选,人工或 agent 维护;
技术性字段(宽高/格式/文件大小)由阅读器索引时从 original.<ext> 现场派生,
**绝不**持久化进 frontmatter(QUA-175)。
"""

from __future__ import annotations

from datetime import date as _Date
from typing import Annotated, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .primitives import Name, Title, Rating

# 出处: URL 或自由文本(如 "维基百科" / 某书名)。URL 可能较长,上限放宽到 500。
SourceRef = Annotated[
    str,
    StringConstraints(min_length=2, max_length=500, strip_whitespace=True),
]


class ImageSchema(BaseModel):
    """A local image object with optional descriptive metadata."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["image"]

    # ─── 必填 ─────────────────────────────────────────────
    title: Title

    # ─── 可选 ─────────────────────────────────────────────
    creator: list[Name] = Field(
        default_factory=list,
        description="创作者姓名数组(摄影师/画家/制图者,可关联 vault/authors/);未知留空(省略整键)",
    )
    date: Optional[_Date] = Field(
        default=None, strict=False,
        description="创作/拍摄日期(整日 ISO,如 2024-11-08);未知省略",
    )
    source: Optional[SourceRef] = Field(
        default=None,
        description="出处: URL 或自由文本(保存时记录从哪来的)",
    )
    themes: list[str] = Field(
        default_factory=list,
        description="主题标签数组(复用全库 themes 词表)",
    )
    topics: list[str] = Field(
        default_factory=list,
        description="所属 topic 语料 slug 数组(同 paper/book/chapter/author)",
    )
    rating: Optional[Rating] = Field(default=None)

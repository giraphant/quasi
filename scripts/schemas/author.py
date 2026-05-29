"""author schema: 学者档案。

文件位置: vault/authors/<slug>.md
SPEC: ../SPEC.md § 3.1
"""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from .primitives import Name, Rating


class AuthorSchema(BaseModel):
    """Profile of a scholar. One file per author."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["author"] = Field(
        description="类型判别符,固定为字面量 'author'"
    )

    name: Name = Field(
        description="作者全名,作为该 entity 的展示名"
    )

    themes: list[str] = Field(
        default_factory=list,
        description="研究方向标签数组;允许空但 lint warn '0 themes 可能漏写'",
    )
    topics: list[str] = Field(
        default_factory=list,
        description="所属 topic 语料的 slug 数组;供前端按成员反查;允许空",
    )

    rating: Optional[Rating] = Field(
        default=None,
        description="整体学术评分(1..5,reader 渲染为 ★);可选",
    )

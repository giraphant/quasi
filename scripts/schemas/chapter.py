"""chapter schema: 一本书的一个章节分析。

文件位置: vault/books/<slug>/chXX-*.md
SPEC: ../SPEC.md § 3.3

与 paper 几乎完全镜像 —— 唯一字段差异是 `book` (slug) vs `journal`。
"""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from .primitives import Name, Title, ShortString, Year, Rating


class ChapterSchema(BaseModel):
    """A chapter analysis. Must live under vault/books/<slug>/."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["chapter"]

    # ─── 必填 ─────────────────────────────────────────────
    title: Title = Field(description="章节标题(含 '第N章 XXX' 前缀)")
    authors: list[Name] = Field(
        min_length=1,
        description="章作者;编纂本里可与父书 authors 不同(章节作者 != 书编者)",
    )
    year: Optional[Year] = Field(description="通常等于父书 year")
    book: ShortString = Field(
        description=(
            "父书 slug(从文件路径派生,如 'allison-nightwork-1994');"
            "vault-wide lint 校验该 slug 真的存在对应的 book 文件"
        )
    )

    # ─── 可选 ─────────────────────────────────────────────
    themes: list[str] = Field(
        default_factory=list,
        description="章节级主题;允许空(章节经常没有独立主题标签)",
    )
    topics: list[str] = Field(
        default_factory=list,
        description="所属 topic 语料的 slug 数组;供前端按成员反查;允许空",
    )
    rating: Optional[Rating] = Field(default=None)

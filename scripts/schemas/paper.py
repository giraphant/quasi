"""paper schema: 期刊论文分析。

文件位置: vault/papers/*.md (或 vault/journals/<slug>/<doi>.md)
SPEC: ../SPEC.md § 3.4

paper 严格指期刊文章。书的章节(包括论文集里的章节)归 chapter 类型,
放在 vault/books/<slug>/。

与 chapter 几乎完全镜像 —— 唯一字段差异是 `journal` vs `book`。
"""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from .primitives import Name, Title, ShortString, Year, Rating, DOI


class PaperSchema(BaseModel):
    """A journal article analysis."""

    model_config = ConfigDict(extra="allow", strict=True)

    type: Literal["paper"]

    # ─── 必填 ─────────────────────────────────────────────
    title: Title
    authors: list[Name] = Field(min_length=1, description="作者数组,永远 ≥1 元素")
    year: Optional[Year] = Field(description="发表年")
    journal: ShortString = Field(description="期刊名;paper = 期刊论文,必填")
    themes: list[str] = Field(
        min_length=1,
        description="主题标签数组;paper 必须有主题(不允许空 — 与 chapter 不同)",
    )

    # ─── 可选 ─────────────────────────────────────────────
    doi: Optional[DOI] = Field(default=None)
    rating: Optional[Rating] = Field(default=None)

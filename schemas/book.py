"""book schema: 一本书的整体分析。

文件位置: vault/books/<slug>/00-overview.md
SPEC: ../SPEC.md § 3.2

字段对齐 BibTeX `@book` / `@collection` 以便未来一键导出引文。
"""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .primitives import Name, Title, ShortString, Year, Rating


class BookSchema(BaseModel):
    """Analytical overview of a book. Aligns with BibTeX @book / @collection."""

    model_config = ConfigDict(extra="allow", strict=True)

    type: Literal["book"]

    # ─── BibTeX 核心(必填)──────────────────────────────────
    title: Title = Field(description="书名(含副标题)")
    authors: list[Name] = Field(
        min_length=1,
        description="作者或编者数组;角色由 category 区分;永远数组(单作者也包成 1 元素)",
    )
    year: Year | None = Field(description="出版年")
    publisher: ShortString = Field(
        description="出版社;Phase 1 lint warn,Phase 2 严格必填"
    )

    # ─── 唯一识别码 + 类别 ───────────────────────────────────
    isbn: str | None = Field(
        default=None,
        description="ISBN;schema 不强制格式,lint 单独检查",
    )
    category: Literal["monograph", "edited-volume", "handbook", "other"] = Field(
        default="monograph",
        description="书籍类别;BibTeX export 时驱动 @book vs @collection + author vs editor",
    )

    # 中译本索引不在 frontmatter,完全外挂在
    # $CLAUDE_PROJECT_DIR/.quasi/audit/translations.json 的 `by_book[slug]` 块,
    # 由 local-agent 维护。frontmatter 不写 `cndouban` 字段。

    # ─── 学术分析字段 ─────────────────────────────────────────
    themes: list[str] = Field(
        default_factory=list,
        description="主题标签数组",
    )
    rating: Rating | None = Field(default=None)

"""topic schema: 主题 overview/resources 页面。

frontmatter 需 type + kind + title(title 为人读主题标题,与 H1 一致);
文件夹 slug 仍是稳定身份键。
成员关系反向挂在实体的 `topics: [slug]` 上(见 paper/book/chapter/author)。
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .primitives import Title


class TopicSchema(BaseModel):
    """A lightweight topic overview or resources page."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["topic"]
    title: Title
    kind: Literal["overview", "resources"] = Field(
        description="页面类型: overview 为综合页,resources 为资源页"
    )

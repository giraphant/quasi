"""topic schema: 主题 overview/resources 页面。

身份由文件夹 slug + H1 确定;frontmatter 只需 type + kind。
成员关系反向挂在实体的 `topics: [slug]` 上(见 paper/book/chapter/author)。
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class TopicSchema(BaseModel):
    """A lightweight topic overview or resources page."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["topic"]
    kind: Literal["overview", "resources"] = Field(
        description="页面类型: overview 为综合页,resources 为资源页"
    )

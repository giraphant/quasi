"""topic schema: 主题 overview/resources 页面。"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .primitives import ShortString


class TopicSchema(BaseModel):
    """A lightweight topic overview or resources page."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["topic"]
    kind: Literal["overview", "resources"] = Field(
        description="页面类型: overview 为综合页,resources 为资源页"
    )
    topic: ShortString = Field(description="主题名")

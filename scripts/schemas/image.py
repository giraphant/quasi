"""image schema: 本地图片对象 metadata。"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict

from .primitives import Title


class ImageSchema(BaseModel):
    """A lightweight local image object."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["image"]
    title: Title

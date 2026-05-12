"""Shared constrained types used by author / book / chapter / paper schemas.

These are *value-level* reusable validators, not inherited base classes.
Each entity schema uses them à la carte.
"""

from typing import Annotated
from pydantic import Field, StringConstraints

# ─── 字符串原语 ─────────────────────────────────────────────

# 作者全名: 2..120 chars (人名通常较短)
Name = Annotated[
    str,
    StringConstraints(min_length=2, max_length=120, strip_whitespace=True),
]

# 实体标题(书 / 章节 / 论文): 2..280 chars (允许长副标题)
Title = Annotated[
    str,
    StringConstraints(min_length=2, max_length=280, strip_whitespace=True),
]

# 出版社 / 期刊 / 父书 slug 等通用短字符串
ShortString = Annotated[
    str,
    StringConstraints(min_length=2, max_length=200, strip_whitespace=True),
]

# ─── 数值原语 ─────────────────────────────────────────────

# 年份: 1500..2030 整数(允许 None 在 schema 字段处声明)
Year = Annotated[int, Field(ge=1500, le=2030)]

# 评分: 1..5 整数(前端渲染为 ★),允许 None 在 schema 字段处声明
Rating = Annotated[int, Field(ge=1, le=5)]

# ─── DOI ─────────────────────────────────────────────

# DOI: 必须以 10.<digits>/ 开头
DOI = Annotated[
    str,
    StringConstraints(pattern=r"^10\.\d+/.+", strip_whitespace=True),
]

# ─── 注意 ─────────────────────────────────────────────
#
# `Authors`(作者数组)和 `Themes`(主题数组)不在这里定义为类型别名,因为它们是
# `list[str]` 加上 `Field(min_length=N)` 约束 —— Pydantic V2 在类型别名上叠加
# 额外 Field 约束的写法不如直接在 schema 字段处写清晰。所以这两个直接在
# 各 schema 的字段定义里展开:
#
#     authors: list[Name] = Field(min_length=1, description='作者数组,≥1 元素')
#     themes:  list[str]  = Field(default_factory=list, description='主题标签')

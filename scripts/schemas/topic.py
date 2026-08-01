"""topic schema: 主题 overview/resources/outline/card 页面。

frontmatter 需 type + kind + title(title 为人读主题标题,与 H1 一致);
文件夹 slug 仍是稳定身份键。
成员关系反向挂在实体的 `topics: [slug]` 上(见 paper/book/chapter/author)。
outline 页(02-outline.md)是 steer-agent 维护的研究大纲状态,用户可手改;
card 页(cards/{card-slug}.md)是 webcard-agent 写的圈外证据卡。
设计见 docs/topic-steering-design.md。
"""

from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .primitives import CardSlug, Title


class SubqItem(BaseModel):
    """子问题的一个学术语料成员(持久在 outline frontmatter,跨轮跨重跑累计)。

    只收 vault 分析件(book/paper/talk)。圈外证据卡走 `Subquestion.cards`
    独立通道 —— 卡不是分析件,混进来会让 synth 按分析件路径去读一个不存在的产物。
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["book", "paper", "talk"]
    slug: str = Field(min_length=2, max_length=160)
    role: Optional[Literal["evidence", "theory", "method", "context"]] = None


class Subquestion(BaseModel):
    """研究大纲里的一个子问题(仅 kind: outline 页携带)。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    question: str = Field(min_length=4, max_length=280)
    coverage: Literal["gap", "thin", "covered", "saturated"]
    channel: Literal["academic", "web", "mixed"] = "academic"
    theory_used: int = 0
    items: Optional[List[SubqItem]] = None
    cards: List[CardSlug] = Field(
        default_factory=list,
        description="证据卡 slug 表(cards/{slug}.md),与 items 平行的圈外证据通道",
    )


class TopicSchema(BaseModel):
    """A topic overview, resources page, outline state, or evidence card."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["topic"]
    title: Title
    kind: Literal["overview", "resources", "outline", "card"] = Field(
        description="页面类型: overview 综合页 / resources 资源页 / outline 研究大纲 / "
                    "card 圈外证据卡"
    )
    subquestions: Optional[list[Subquestion]] = None
    history: Optional[list[str]] = None
    # 卡是从 note 迁过来的:手写卡带着 created/themes,迁移时不该为了迁移丢掉它们。
    # 只对 kind: card 开口,别的 kind 写了照样报错 —— 脊柱页没有"创建日期"这回事。
    created: Optional[date] = Field(default=None, strict=False)
    themes: Optional[list[str]] = Field(
        default=None, description="主题标签数组(复用全库 themes 词表);仅 kind: card"
    )

    @model_validator(mode="after")
    def _fields_stay_on_their_own_kind(self) -> "TopicSchema":
        if self.kind == "outline":
            if not self.subquestions:
                raise ValueError("outline 页必须携带非空 subquestions")
        elif self.subquestions is not None or self.history is not None:
            raise ValueError("subquestions/history 只允许出现在 kind: outline 页")
        if self.kind != "card" and (self.created is not None or self.themes is not None):
            raise ValueError("created/themes 只允许出现在 kind: card 页")
        return self

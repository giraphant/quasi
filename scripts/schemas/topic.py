"""topic schema: 主题 overview/resources/outline/dossier 页面。

frontmatter 需 type + kind + title(title 为人读主题标题,与 H1 一致);
文件夹 slug 仍是稳定身份键。
成员关系反向挂在实体的 `topics: [slug]` 上(见 paper/book/chapter/author)。
outline 页(02-outline.md)是 steer-agent 维护的研究大纲状态,用户可手改;
dossier 页(NN-{subq}.md)是毕业子问题的专章。设计见 docs/topic-steering-design.md。
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .primitives import Title


class SubqItem(BaseModel):
    """子问题的一个语料成员(持久在 outline frontmatter,跨轮跨重跑累计)。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["book", "paper", "talk"]
    slug: str = Field(min_length=2, max_length=160)


class Subquestion(BaseModel):
    """研究大纲里的一个子问题(仅 kind: outline 页携带)。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    question: str = Field(min_length=4, max_length=280)
    coverage: Literal["gap", "thin", "covered", "saturated"]
    channel: Literal["academic", "web", "mixed"] = "academic"
    dossier: bool = False
    page: Optional[str] = None
    theory_used: int = 0
    items: Optional[List[SubqItem]] = None


class TopicSchema(BaseModel):
    """A topic page: overview / resources spine, outline state, or dossier chapter."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["topic"]
    title: Title
    kind: Literal["overview", "resources", "outline", "dossier"] = Field(
        description="页面类型: overview 综合页 / resources 资源页 / outline 研究大纲 / dossier 子问题专章"
    )
    subquestions: Optional[list[Subquestion]] = None
    history: Optional[list[str]] = None

    @model_validator(mode="after")
    def _outline_fields_only_on_outline(self) -> "TopicSchema":
        if self.kind == "outline":
            if not self.subquestions:
                raise ValueError("outline 页必须携带非空 subquestions")
        elif self.subquestions is not None or self.history is not None:
            raise ValueError("subquestions/history 只允许出现在 kind: outline 页")
        return self

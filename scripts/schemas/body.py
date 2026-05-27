"""Body schemas: 正文 H2 章节结构定义。

每个 type 的正文由若干 H2 章节组成,每个 H2:
- 有一个 canonical 标题(4 字中文,跨 type 复用同名)
- 有一个 BlockKind(下方内容期望的形状)
- 有 required / optional 标记
- 有 aliases(LLM 漂移产生的同义异名)
- h3-* kinds 还有 child_kind(H3 之下的内容形状)

Lint 行为:
- 必填 H2 不存在 → fail
- block kind 不匹配 → fail
- 长尾非 schema H2 → 当前 Phase 1 当 warning,Phase 3 strict=True 后变 fail
- aliases 列表里的旧标题 → 由 autofix 改名为 canonical

SPEC: ../SPEC.md § 4
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Pattern, Union


BlockKind = Literal[
    "paragraph",          # 自由段落
    "bullet-list",        # `- item`
    "numbered-list",      # `1. item`
    "table",              # markdown table
    "blockquote-list",    # 多个 `> quote`
    "definition-list",    # **term**: description
    "h3-project-tabs",    # H2 下分 H3,H3 是 project 子节(reader 渲染为 tabs)
    "h3-sections",        # H2 下分 H3,H3 是原文小节(reader 渲染为流式 sub-headings)
    "mixed",              # 容忍混合,长期靠 autofix 收敛
]


@dataclass
class BodySection:
    """一个 H2 section 的 schema 描述。"""

    h2: str                                    # canonical 4-字 H2 标题
    kind: BlockKind                            # 期望的 block 形状
    required: bool = False                      # 是否必填
    child_kind: BlockKind | None = None         # h3-* kinds 下 H3 之下的形状
    aliases: list[Union[str, Pattern]] = field(default_factory=list)
    description: str = ""                       # 给 LLM prompt 用的语义说明


@dataclass
class BodySchema:
    """一个 type 的全部 body section 集合。"""

    type_name: str
    sections: list[BodySection]
    # Phase 1 = False(只 warn);Phase 3 = True(未知 H2 直接 fail)
    strict: bool = False

    def section_by_h2(self, h2: str) -> BodySection | None:
        """根据 H2 标题查 section,自动匹配 aliases。"""
        for s in self.sections:
            if s.h2 == h2:
                return s
            for alias in s.aliases:
                if isinstance(alias, str) and alias == h2:
                    return s
                if hasattr(alias, "match") and alias.match(h2):
                    return s
        return None


# ─── author body schema ──────────────────────────────────────

AUTHOR_BODY = BodySchema(
    type_name="author",
    sections=[
        BodySection(
            h2="思想肖像",
            kind="paragraph",
            required=True,
            description="2-3 句概括该学者的核心关切和贡献",
        ),
        BodySection(
            h2="代表著作",
            kind="paragraph",
            required=False,
            description="仅列专著;没有专著的作者跳过",
            aliases=["代表作概览"],
        ),
        BodySection(
            h2="学术轨迹",
            kind="paragraph",
            required=True,
            description="学者的研究历程",
        ),
        BodySection(
            h2="关键概念",
            kind="table",
            required=True,
            description="该学者提出/常用的核心概念表",
            aliases=["核心概念谱系", "概念谱系"],
        ),
        BodySection(
            h2="理论网络",
            kind="bullet-list",
            required=True,
            description="该学者对话过的思想家、理论传统",
        ),
        BodySection(
            h2="金句要点",
            kind="blockquote-list",
            required=True,
            description="可引用的代表性论点 / 原文金句",
            aliases=["可引用观点", "可引用要点"],
        ),
        BodySection(
            h2="项目关联",
            kind="h3-project-tabs",
            required=True,
            child_kind="paragraph",
            description="H3 per project — 项目名作为 H3 标签;reader 渲染为 tabs",
            aliases=[
                "与本项目主题的关联",
                "与项目主题的关联",
                re.compile(r"^与 .+ 的关联$"),
                re.compile(r"^与\".+\"的关联$"),
                re.compile(r"^与「.+」的关联$"),
                re.compile(r"^与 BTS .+ 的关联$"),
            ],
        ),
    ],
)


# ─── book body schema ────────────────────────────────────────

BOOK_BODY = BodySchema(
    type_name="book",
    sections=[
        BodySection(
            h2="核心论点",
            kind="paragraph",
            required=True,
            description="全书的中心主题和核心论证",
            aliases=["全书核心论点", "一、全书核心论点"],
        ),
        BodySection(
            h2="章节逻辑",
            kind="paragraph",
            required=True,
            description="各章如何构成整体论证;章节间递进/对话/互补关系",
            aliases=["章节间逻辑"],
        ),
        BodySection(
            h2="关键概念",
            kind="table",
            required=True,
            description="全书的核心概念表(同名 H2,book 用 table 形态)",
            aliases=["关键概念表", "核心概念表", "关键概念谱系", "三、核心概念表"],
        ),
        BodySection(
            h2="理论贡献",
            kind="paragraph",
            required=True,
            description="本书对学术领域的整体贡献",
            aliases=["核心理论贡献"],
        ),
        BodySection(
            h2="精读章节",
            kind="numbered-list",
            required=True,
            description="按优先级排序的推荐精读章节",
            aliases=["推荐精读章节"],
        ),
        BodySection(
            h2="项目关联",
            kind="h3-project-tabs",
            required=False,
            child_kind="paragraph",
            aliases=[
                re.compile(r"^与 .+ 的关联$"),
                re.compile(r"^与\".+\"的关联$"),
                re.compile(r"^与「.+」的关联$"),
            ],
        ),
    ],
)


# ─── chapter body schema ─────────────────────────────────────

CHAPTER_BODY = BodySchema(
    type_name="chapter",
    sections=[
        BodySection(
            h2="核心论点",
            kind="paragraph",
            required=True,
            description="章节的中心论点和论证逻辑",
        ),
        BodySection(
            h2="理论框架",
            kind="paragraph",
            required=True,
            description="理论传统、对话学者和思想资源",
        ),
        BodySection(
            h2="分节摘要",
            kind="h3-sections",
            required=True,
            child_kind="paragraph",
            description="按原文小节结构 — H3 是原文 sub-section 标题",
        ),
        BodySection(
            h2="关键概念",
            kind="table",
            required=True,
            description="章节中讨论的核心概念(同名 H2,chapter 用 table)",
        ),
        BodySection(
            h2="核心引用",
            kind="numbered-list",
            required=True,
            description="本章最重要的 5-15 个引用",
            aliases=["核心引用文献"],
        ),
        BodySection(
            h2="金句要点",
            kind="blockquote-list",
            required=False,
            description="可引用段落 / 原文金句",
            aliases=["可引用段落"],
        ),
        BodySection(
            h2="项目关联",
            kind="h3-project-tabs",
            required=False,
            child_kind="numbered-list",
            aliases=[
                re.compile(r"^与 .+ 的关联$"),
                re.compile(r"^与\".+\"的关联$"),
                re.compile(r"^★+ 与 .+ 的关联$"),
                re.compile(r"^与 BTS .+ 的关联$"),
            ],
        ),
    ],
)


# ─── paper body schema ───────────────────────────────────────

PAPER_BODY = BodySchema(
    type_name="paper",
    sections=[
        BodySection(
            h2="核心论点",
            kind="paragraph",
            required=True,
            description="论文的中心论点和论证逻辑",
        ),
        BodySection(
            h2="理论框架",
            kind="paragraph",
            required=True,
            description="理论传统、对话学者和思想资源",
        ),
        BodySection(
            h2="分节摘要",
            kind="h3-sections",
            required=True,
            child_kind="paragraph",
            description="按原文小节结构 — H3 是原文 sub-section 标题",
        ),
        BodySection(
            h2="关键概念",
            kind="table",
            required=True,
            description="论文中讨论的核心概念(同名 H2,paper 用 table)",
        ),
        BodySection(
            h2="核心引用",
            kind="numbered-list",
            required=True,
            description="本论文最重要的 5-15 个引用",
            aliases=["核心引用文献"],
        ),
        BodySection(
            h2="金句要点",
            kind="blockquote-list",
            required=False,
            description="可引用段落 / 原文金句",
            aliases=["可引用段落"],
        ),
        BodySection(
            h2="项目关联",
            kind="h3-project-tabs",
            required=False,
            child_kind="numbered-list",
            aliases=[
                re.compile(r"^与 .+ 的关联$"),
                re.compile(r"^与\".+\"的关联$"),
                re.compile(r"^★+ 与 .+"),
            ],
        ),
    ],
)


TOPIC_BODY = BodySchema(type_name="topic", sections=[])
JOURNAL_BODY = BodySchema(type_name="journal", sections=[])
NOTE_BODY = BodySchema(type_name="note", sections=[])
IMAGE_BODY = BodySchema(type_name="image", sections=[])

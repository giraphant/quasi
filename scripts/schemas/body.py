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
    columns: list[str] = field(default_factory=list)
    recommended_items: tuple[int, int] | None = None
    condition: str = ""


@dataclass
class BodySchema:
    """一个 type 的全部 body section 集合。"""

    type_name: str
    sections: list[BodySection]
    artifact_schema_version: str = ""
    path_pattern: str = ""
    identity_fields: list[str] = field(default_factory=list)
    h1: str = ""
    metadata_lines: list[str] = field(default_factory=list)
    evidence_rules: list[str] = field(default_factory=list)
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
    artifact_schema_version="quasi.artifact.author/0.1",
    path_pattern="vault/authors/{slug}.md",
    identity_fields=["name"],
    h1="使用 frontmatter.name",
    evidence_rules=[
        "只使用 caller 提供并验证的 canonical Book/Paper corpus",
        "每份成员作品首次出现时使用由其 exact canonical path 推导的 wikilink",
        "保持原材料的证据类型，不虚构时间顺序、引文或作品关系",
        "rating 只能由 caller 提供的证据支持；没有证据时省略",
    ],
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
    artifact_schema_version="quasi.artifact.book/0.1",
    path_pattern="vault/books/{slug}/00-overview.md",
    identity_fields=[
        "title",
        "authors",
        "year",
        "publisher",
        "isbn",
        "category",
    ],
    h1="使用 frontmatter.title；不添加模板式或项目式后缀",
    sections=[
        BodySection(
            h2="核心论点",
            kind="paragraph",
            required=True,
            description="综合全部 supplied chapter analyses，说明全书的中心主题、核心论证和证据关系",
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
            columns=["概念", "英文", "提出者", "定义"],
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
            condition="只推荐 supplied chapter analyses 中实际存在的章节",
            aliases=["推荐精读章节"],
        ),
        BodySection(
            h2="项目关联",
            kind="h3-project-tabs",
            required=False,
            child_kind="paragraph",
            condition="只有 caller identity 明确提供项目语境时才生成",
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
    artifact_schema_version="quasi.artifact.chapter/0.1",
    path_pattern="vault/books/{book_slug}/ch{slot}-{chapter_slug}.md",
    identity_fields=[
        "title",
        "authors",
        "year",
        "book",
    ],
    h1="忠实呈现 caller identity 中的 chapter label 与 chapter title，不添加装饰性后缀",
    metadata_lines=[
        "可写原文标题、作者和关键词；每一项必须由 input 或 caller identity 支持",
    ],
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
            columns=["概念", "英文", "提出者", "定义"],
            recommended_items=(3, 5),
        ),
        BodySection(
            h2="核心引用",
            kind="numbered-list",
            required=True,
            description="本章实质使用的著作及其在论证中的作用；不补写 input 无法支持的书目信息",
            recommended_items=(5, 15),
            aliases=["核心引用文献"],
        ),
        BodySection(
            h2="金句要点",
            kind="blockquote-list",
            required=False,
            description="可引用段落 / 原文金句",
            condition="只有 input 中存在可定位的准确引文时才生成",
            aliases=["可引用段落"],
        ),
        BodySection(
            h2="项目关联",
            kind="h3-project-tabs",
            required=False,
            child_kind="numbered-list",
            condition="只有 caller identity 明确提供项目语境时才生成",
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
    artifact_schema_version="quasi.artifact.paper/0.1",
    path_pattern="vault/papers/{slug}.md",
    identity_fields=[
        "title",
        "authors",
        "year",
        "journal",
        "doi",
    ],
    h1="忠实概括论文标题；不添加装饰性或项目式后缀",
    metadata_lines=[
        "英文原标题",
        "作者",
        "期刊来源",
        "仅在 identity 提供 DOI 时写 DOI",
    ],
    sections=[
        BodySection(
            h2="核心论点",
            kind="paragraph",
            required=True,
            description="说明研究问题、中心论点、证据、推理、贡献，以及正文实际提出的限制",
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
            columns=["概念", "英文", "提出者", "定义"],
            recommended_items=(3, 5),
        ),
        BodySection(
            h2="核心引用",
            kind="numbered-list",
            required=True,
            description="论文实质使用的著作及其在论证中的作用；不补写 input 无法支持的书目信息",
            recommended_items=(5, 15),
            aliases=["核心引用文献"],
        ),
        BodySection(
            h2="金句要点",
            kind="blockquote-list",
            required=False,
            description="可引用段落 / 原文金句",
            condition="只有 input 中存在可定位的准确引文时才生成",
            aliases=["可引用段落"],
        ),
        BodySection(
            h2="项目关联",
            kind="h3-project-tabs",
            required=False,
            child_kind="numbered-list",
            condition="只有 caller identity 明确提供项目语境时才生成",
            aliases=[
                re.compile(r"^与 .+ 的关联$"),
                re.compile(r"^与\".+\"的关联$"),
                re.compile(r"^★+ 与 .+"),
            ],
        ),
    ],
)


# ─── talk body schema ────────────────────────────────────────
#
# 6 个固定四字 H2,顺序与字样不得变动,缺内容时保留标题写「（…)」(silent/short
# 模板亦遵守 —— 见 scripts/transcribe/silent.py)。前五节与 paper 平行(`文献人物`
# 列表对应 paper 的 `核心引用`,问答并入 `分节摘要` 不单列);`时间脉络`(视频时间轴
# 导航)是 talk 专属,放最后当导航附录。

TALK_BODY = BodySchema(
    type_name="talk",
    artifact_schema_version="quasi.artifact.talk/0.1",
    path_pattern="vault/talks/{slug}/talk.md",
    identity_fields=["title", "date", "media"],
    h1="使用 frontmatter.title",
    metadata_lines=[
        "讲者",
        "日期",
        "场合",
        "时长",
        "transcript 未说明的非必填展示项标为（未说明）",
    ],
    sections=[
        BodySection(
            h2="核心论点",
            kind="paragraph",
            required=True,
            description="这场讲座的中心主张、问题意识、贡献(2-4 段)",
        ),
        BodySection(
            h2="分节摘要",
            kind="h3-sections",
            required=True,
            child_kind="paragraph",
            description="按内容实质分节(H3 小标题);摘要主体;问答并入此处",
        ),
        BodySection(
            h2="关键概念",
            kind="table",
            required=True,
            description="讲座提出/反复使用的核心概念表;无则保留表头写一行",
            columns=["概念", "英文", "定义"],
        ),
        BodySection(
            h2="项目关联",
            kind="bullet-list",
            required=True,
            description="与 vault/authors、BTS 综述议题、同系列讲座的关联;无则写「（暂无)」",
        ),
        BodySection(
            h2="文献人物",
            kind="bullet-list",
            required=True,
            description="讲座点到的学者、著作、概念来源(列表);无则写一行说明",
        ),
        BodySection(
            h2="时间脉络",
            kind="bullet-list",
            required=True,
            description="视频时间轴导航(talk 专属,置末);每行一段,带起始 `[mm:ss]`(取自 transcript)",
        ),
    ],
)


TOPIC_BODY = BodySchema(type_name="topic", sections=[])
JOURNAL_BODY = BodySchema(type_name="journal", sections=[])
NOTE_BODY = BodySchema(type_name="note", sections=[])
IMAGE_BODY = BodySchema(type_name="image", sections=[])
TRANSCRIPT_BODY = BodySchema(type_name="transcript", sections=[])

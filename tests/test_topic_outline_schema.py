from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from schemas.topic import TopicSchema  # noqa: E402

SQ = {
    "id": "sq-form-history",
    "question": "2000 年以来非主流形态的量产史是什么?",
    "coverage": "gap",
    "channel": "mixed",
    "dossier": False,
    "page": None,
    "theory_used": 0,
    "items": [{"kind": "paper", "slug": "gomes-morephone-2013", "role": "evidence"}],
    "cards": ["gaming-phone-cards-2003-2019"],
}


def test_outline_kind_carries_subquestions() -> None:
    doc = TopicSchema(
        type="topic", title="非常规手机形态", kind="outline",
        subquestions=[SQ], history=["2026-07-26 r0: 初拟 4 个子问题"],
    )
    assert doc.subquestions[0].coverage == "gap"
    assert doc.subquestions[0].page is None
    assert doc.subquestions[0].items[0].slug == "gomes-morephone-2013"
    assert doc.subquestions[0].items[0].role == "evidence"
    assert doc.subquestions[0].cards == ["gaming-phone-cards-2003-2019"]


def test_cards_are_a_channel_of_their_own_not_corpus_items() -> None:
    """卡不是 vault 分析件。混进 items 会让 synth 按 vault/papers/{slug}.md 去读一个
    不存在的产物 —— 静默死链,而不是报错。所以 items 的 kind 枚举必须挡住它。"""
    with pytest.raises(ValidationError):
        TopicSchema(
            type="topic", title="非常规手机形态", kind="outline",
            subquestions=[{**SQ, "items": [{"kind": "card", "slug": "gaming-phone-cards-2003-2019"}]}],
        )


def test_outline_requires_subquestions() -> None:
    with pytest.raises(ValidationError):
        TopicSchema(type="topic", title="非常规手机形态", kind="outline")


def test_non_outline_kinds_reject_outline_fields() -> None:
    with pytest.raises(ValidationError):
        TopicSchema(type="topic", title="非常规手机形态", kind="dossier", subquestions=[SQ])
    with pytest.raises(ValidationError):
        TopicSchema(type="topic", title="非常规手机形态", kind="overview", history=["r0"])
    # 卡页是 webcard-agent 的产物,不承载掌舵状态 —— outline 只能有一份,多份就没有唯一权威。
    with pytest.raises(ValidationError):
        TopicSchema(type="topic", title="游戏手机量产史", kind="card", subquestions=[SQ])
    with pytest.raises(ValidationError):
        TopicSchema(type="topic", title="游戏手机量产史", kind="card", history=["r0"])


def test_dossier_kind_is_valid_and_lean() -> None:
    doc = TopicSchema(type="topic", title="紧固件谱系", kind="dossier")
    assert doc.kind == "dossier"


def test_card_kind_is_valid_and_lean() -> None:
    """按品类汇总的机型卡(一张卡多个对象)与单对象卡是同一个 kind,frontmatter 同样只有三字段。"""
    doc = TopicSchema(type="topic", title="游戏手机量产史——6 款机型材料卡", kind="card")
    assert doc.kind == "card"

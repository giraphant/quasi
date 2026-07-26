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
}


def test_outline_kind_carries_subquestions() -> None:
    doc = TopicSchema(
        type="topic", title="非常规手机形态", kind="outline",
        subquestions=[SQ], history=["2026-07-26 r0: 初拟 4 个子问题"],
    )
    assert doc.subquestions[0].coverage == "gap"
    assert doc.subquestions[0].page is None


def test_outline_requires_subquestions() -> None:
    with pytest.raises(ValidationError):
        TopicSchema(type="topic", title="非常规手机形态", kind="outline")


def test_non_outline_kinds_reject_outline_fields() -> None:
    with pytest.raises(ValidationError):
        TopicSchema(type="topic", title="非常规手机形态", kind="dossier", subquestions=[SQ])
    with pytest.raises(ValidationError):
        TopicSchema(type="topic", title="非常规手机形态", kind="overview", history=["r0"])


def test_dossier_kind_is_valid_and_lean() -> None:
    doc = TopicSchema(type="topic", title="紧固件谱系", kind="dossier")
    assert doc.kind == "dossier"

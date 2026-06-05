from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from schemas import registry  # noqa: E402
from scripts.typecheck.typecheck import check_file  # noqa: E402


def test_registry_uses_only_short_canonical_types() -> None:
    assert set(registry.TYPE_REGISTRY) == {
        "author",
        "book",
        "chapter",
        "paper",
        "topic",
        "journal",
        "note",
        "image",
        "talk",
        "transcript",
    }
    for type_name in registry.TYPE_REGISTRY:
        assert registry.canonical_type(type_name) == type_name
        assert registry.schema_for_type(type_name) is not None


def test_deprecated_long_types_are_diagnostics_not_canonical_types() -> None:
    assert registry.DEPRECATED_TYPE_ALIASES["paper-analysis"] == "paper"
    assert registry.DEPRECATED_TYPE_ALIASES["book-overview"] == "book"
    assert registry.DEPRECATED_TYPE_ALIASES["chapter-summary"] == "chapter"
    assert registry.DEPRECATED_TYPE_ALIASES["author-profile"] == "author"
    assert registry.canonical_type("paper-analysis") is None
    assert registry.schema_for_type("paper-analysis") is None


def test_topic_and_journal_validate_lightweight_frontmatter() -> None:
    topic_schema, topic_body = registry.schema_for_type("topic")
    journal_schema, journal_body = registry.schema_for_type("journal")

    topic_schema.model_validate({
        "type": "topic",
        "title": "社会建构论",
        "kind": "overview",
    })
    topic_schema.model_validate({
        "type": "topic",
        "title": "社会建构论",
        "kind": "resources",
    })
    journal_schema.model_validate({
        "type": "journal",
        "title": "British Journal of Sociology",
        "kind": "overview",
        "journal": "British Journal of Sociology",
    })
    journal_schema.model_validate({
        "type": "journal",
        "title": "British Journal of Sociology",
        "kind": "resources",
        "journal": "British Journal of Sociology",
    })

    assert topic_body.type_name == "topic"
    assert topic_body.sections == []
    assert journal_body.type_name == "journal"
    assert journal_body.sections == []


def test_topic_and_journal_reject_extra_fields_and_old_kind_values() -> None:
    topic_schema, _ = registry.schema_for_type("topic")
    journal_schema, _ = registry.schema_for_type("journal")

    with pytest.raises(ValidationError):
        topic_schema.model_validate({
            "type": "topic",
            "title": "密码学的社会建构",
            "kind": "reading-list",
        })
    with pytest.raises(ValidationError):
        topic_schema.model_validate({
            "type": "topic",
            "title": "密码学的社会建构",
            "kind": "overview",
            "topic": "密码学的社会建构",
        })
    # title 现在必填:缺 title 应被拒
    with pytest.raises(ValidationError):
        topic_schema.model_validate({
            "type": "topic",
            "kind": "overview",
        })
    # 其它额外字段仍被 .strict() 拒绝
    with pytest.raises(ValidationError):
        journal_schema.model_validate({
            "type": "journal",
            "title": "British Journal of Sociology",
            "kind": "overview",
            "journal": "British Journal of Sociology",
            "issn": "0007-1315",
        })


def test_typecheck_allows_freeform_topic_and_journal_bodies(tmp_path: Path) -> None:
    topic_fp = tmp_path / "topic.md"
    topic_fp.write_text(
        "---\n"
        "type: topic\n"
        "title: 密码学的社会建构\n"
        "kind: overview\n"
        "---\n"
        "\n"
        "# 密码学的社会建构\n"
        "\n"
        "## 主题概览\n"
        "正文。\n"
        "\n"
        "## 核心文献图谱\n"
        "- Rogaway 2009\n",
        encoding="utf-8",
    )
    journal_fp = tmp_path / "journal.md"
    journal_fp.write_text(
        "---\n"
        "type: journal\n"
        "title: British Journal of Sociology\n"
        "kind: resources\n"
        "journal: British Journal of Sociology\n"
        "---\n"
        "\n"
        "# British Journal of Sociology Resources\n"
        "\n"
        "## British Journal of Sociology — 10-Year Scan\n"
        "正文。\n",
        encoding="utf-8",
    )

    topic_result = check_file(topic_fp)
    journal_result = check_file(journal_fp)

    assert topic_result["frontmatter_errors"] == []
    assert topic_result["body_violations"] == []
    assert journal_result["frontmatter_errors"] == []
    assert journal_result["body_violations"] == []


def test_note_and_image_validate_lightweight_frontmatter() -> None:
    note_schema, note_body = registry.schema_for_type("note")
    image_schema, image_body = registry.schema_for_type("image")

    note_schema.model_validate({
        "type": "note",
        "title": "对《English and American Tool Builders》的批注",
        "created": "2026-05-27",
        "annotates": "vault/books/roe-english-american-tool-builders-1916/00-overview.md",
        "themes": ["machine-tools"],
    })
    note_schema.model_validate({
        "type": "note",
        "title": "Sociology of Gap",
        "created": "2026-05-23",
    })
    image_schema.model_validate({
        "type": "image",
        "title": "Micrometer",
    })

    assert note_body.type_name == "note"
    assert note_body.sections == []
    assert image_body.type_name == "image"
    assert image_body.sections == []


def test_note_and_image_reject_extra_fields() -> None:
    note_schema, _ = registry.schema_for_type("note")
    image_schema, _ = registry.schema_for_type("image")

    with pytest.raises(ValidationError):
        note_schema.model_validate({
            "type": "note",
            "title": "Sociology of Gap",
            "created": "2026-05-23",
            "rating": 3,
        })
    with pytest.raises(ValidationError):
        image_schema.model_validate({
            "type": "image",
            "title": "Micrometer",
            "source": "catalog",
        })


def test_all_registered_frontmatter_schemas_forbid_extra_fields() -> None:
    for type_name in registry.TYPE_REGISTRY:
        schema, _ = registry.schema_for_type(type_name)
        assert schema.model_config.get("extra") == "forbid"


def test_analysis_schemas_reject_extra_fields_and_chapter_doi() -> None:
    author_schema, _ = registry.schema_for_type("author")
    book_schema, _ = registry.schema_for_type("book")
    chapter_schema, _ = registry.schema_for_type("chapter")
    paper_schema, _ = registry.schema_for_type("paper")

    author_schema.model_validate({"type": "author", "name": "Aryn Martin"})
    book_schema.model_validate({
        "type": "book",
        "title": "Test Book",
        "authors": ["Aryn Martin"],
        "year": 2020,
        "publisher": "Test Press",
        "doi": "10.1000/test",
    })
    chapter_schema.model_validate({
        "type": "chapter",
        "title": "Test Chapter",
        "authors": ["Aryn Martin"],
        "year": 2020,
        "book": "test-book-2020",
    })
    paper_schema.model_validate({
        "type": "paper",
        "title": "Test Paper",
        "authors": ["Aryn Martin"],
        "year": 2020,
        "journal": "Test Journal",
        "themes": ["test"],
    })

    with pytest.raises(ValidationError):
        author_schema.model_validate({
            "type": "author",
            "name": "Aryn Martin",
            "orcid": "0000-0000-0000-0000",
        })
    with pytest.raises(ValidationError):
        book_schema.model_validate({
            "type": "book",
            "title": "Test Book",
            "authors": ["Aryn Martin"],
            "year": 2020,
            "publisher": "Test Press",
            "cndouban": "1234567",
        })
    with pytest.raises(ValidationError):
        chapter_schema.model_validate({
            "type": "chapter",
            "title": "Test Chapter",
            "authors": ["Aryn Martin"],
            "year": 2020,
            "book": "test-book-2020",
            "doi": "10.1000/test",
        })
    with pytest.raises(ValidationError):
        paper_schema.model_validate({
            "type": "paper",
            "title": "Test Paper",
            "authors": ["Aryn Martin"],
            "year": 2020,
            "journal": "Test Journal",
            "themes": ["test"],
            "book": "test-book-2020",
        })


def test_entities_accept_topics_membership_field() -> None:
    author_schema, _ = registry.schema_for_type("author")
    book_schema, _ = registry.schema_for_type("book")
    chapter_schema, _ = registry.schema_for_type("chapter")
    paper_schema, _ = registry.schema_for_type("paper")

    author = author_schema.model_validate({
        "type": "author",
        "name": "Aryn Martin",
        "topics": ["social-construction-cryptography"],
    })
    assert author.topics == ["social-construction-cryptography"]

    book = book_schema.model_validate({
        "type": "book",
        "title": "Test Book",
        "authors": ["Aryn Martin"],
        "year": 2020,
        "publisher": "Test Press",
        "topics": ["smartphone-repair", "iphone-proprietary-screws"],
    })
    assert book.topics == ["smartphone-repair", "iphone-proprietary-screws"]

    chapter = chapter_schema.model_validate({
        "type": "chapter",
        "title": "Test Chapter",
        "authors": ["Aryn Martin"],
        "year": 2020,
        "book": "test-book-2020",
        "topics": ["smartphone-repair"],
    })
    assert chapter.topics == ["smartphone-repair"]

    paper = paper_schema.model_validate({
        "type": "paper",
        "title": "Test Paper",
        "authors": ["Aryn Martin"],
        "year": 2020,
        "journal": "Test Journal",
        "themes": ["test"],
        "topics": ["smartphone-repair"],
    })
    assert paper.topics == ["smartphone-repair"]

    # topics is optional: omitting it yields an empty list, never an error.
    bare = paper_schema.model_validate({
        "type": "paper",
        "title": "Test Paper",
        "authors": ["Aryn Martin"],
        "year": 2020,
        "journal": "Test Journal",
        "themes": ["test"],
    })
    assert bare.topics == []


def test_typecheck_allows_freeform_note_and_image_bodies(tmp_path: Path) -> None:
    note_fp = tmp_path / "note.md"
    note_fp.write_text(
        "---\n"
        "type: note\n"
        "title: Sociology of Gap\n"
        "created: 2026-05-23\n"
        "---\n"
        "\n"
        "# Sociology of Gap\n"
        "\n"
        "## 想法\n"
        "正文。\n",
        encoding="utf-8",
    )
    image_fp = tmp_path / "image.md"
    image_fp.write_text(
        "---\n"
        "type: image\n"
        "title: Micrometer\n"
        "---\n"
        "\n"
        "# Micrometer\n"
        "\n"
        "## Caption\n"
        "正文。\n",
        encoding="utf-8",
    )

    note_result = check_file(note_fp)
    image_result = check_file(image_fp)

    assert note_result["frontmatter_errors"] == []
    assert note_result["body_violations"] == []
    assert image_result["frontmatter_errors"] == []
    assert image_result["body_violations"] == []


def test_typecheck_reports_deprecated_type_instead_of_renaming(tmp_path: Path) -> None:
    fp = tmp_path / "old-paper.md"
    fp.write_text(
        "---\n"
        "type: paper-analysis\n"
        "title: Happy Objects\n"
        "authors:\n"
        "  - Sara Ahmed\n"
        "year: 2010\n"
        "journal: The Affect Theory Reader\n"
        "themes:\n"
        "  - affect-theory\n"
        "---\n"
        "\n"
        "## 核心论点\n"
        "body.\n",
        encoding="utf-8",
    )

    result = check_file(fp)

    assert result["type"] is None
    assert result.get("type_rename") is None
    assert result["frontmatter_errors"] == [
        {"type": "deprecated_type", "raw_type": "paper-analysis", "canonical_type": "paper"}
    ]


def test_talk_and_transcript_validate_frontmatter() -> None:
    talk_schema, talk_body = registry.schema_for_type("talk")
    transcript_schema, transcript_body = registry.schema_for_type("transcript")

    # full talk
    talk_schema.model_validate({
        "type": "talk",
        "title": "Lajilao",
        "date": "2024-11-08",
        "speaker": ["Zhou Pengan"],
        "themes": ["e-waste", "repair"],
        "rating": 4,
        "media": "recording.mp4",
    })
    # silent / minimal talk: speaker + themes omitted (empty defaults)
    talk_schema.model_validate({
        "type": "talk",
        "title": "Luxun and Lianhuanhua",
        "date": "2024-10-09",
        "media": "recording.mp4",
    })
    transcript_schema.model_validate({
        "type": "transcript",
        "title": "Lajilao — 转写",
        "talk": "lajilao-20241108",
    })

    # talk body enforces the six fixed four-char H2; transcript body is freeform
    assert talk_body.type_name == "talk"
    assert [s.h2 for s in talk_body.sections] == [
        "核心论点", "分节摘要", "关键概念", "项目关联", "文献人物", "时间脉络",
    ]
    assert all(len(s.h2) == 4 for s in talk_body.sections)
    assert transcript_body.sections == []


def test_talk_and_transcript_reject_extra_and_missing_fields() -> None:
    talk_schema, _ = registry.schema_for_type("talk")
    transcript_schema, _ = registry.schema_for_type("transcript")

    # extra field rejected (strict + forbid)
    with pytest.raises(ValidationError):
        talk_schema.model_validate({
            "type": "talk", "title": "X", "date": "2024-11-08",
            "media": "recording.mp4", "speakers": ["typo-key"],
        })
    # media is required
    with pytest.raises(ValidationError):
        talk_schema.model_validate({"type": "talk", "title": "X", "date": "2024-11-08"})
    # date is required
    with pytest.raises(ValidationError):
        talk_schema.model_validate({"type": "talk", "title": "X", "media": "recording.mp4"})
    # transcript needs talk + title
    with pytest.raises(ValidationError):
        transcript_schema.model_validate({"type": "transcript", "title": "X — 转写"})


def test_typecheck_passes_full_and_silent_talk_bodies(tmp_path: Path) -> None:
    full = tmp_path / "full.md"
    full.write_text(
        "---\n"
        "type: talk\n"
        "title: Lajilao\n"
        "date: 2024-11-08\n"
        "speaker:\n  - Zhou Pengan\n"
        "themes:\n  - e-waste\n"
        "media: recording.mp4\n"
        "---\n\n# 垃圾佬\n\n"
        "## 核心论点\n正文论点。\n\n"
        "## 分节摘要\n### 研究起点\n展开。\n\n### 三阶段框架\n展开。\n\n"
        "## 关键概念\n| 概念 | 英文 | 定义 |\n|------|------|------|\n| 垃圾佬 | Lajilao | 定义 |\n\n"
        "## 项目关联\n- 与 [[network-society-20241108]] 同场异源\n\n"
        "## 文献人物\n- Zhou Pengan — 讲者\n\n"
        "## 时间脉络\n- `[00:00]` 开场 — 引入\n- `[03:09]` 三阶段框架 — 概述\n",
        encoding="utf-8",
    )
    # silent template MUST conform to the body schema (h3 stub + bullets)
    silent = tmp_path / "silent.md"
    silent.write_text(
        "---\n"
        "type: talk\n"
        "title: Luxun and Lianhuanhua\n"
        "date: 2024-10-09\n"
        "media: recording.mp4\n"
        "---\n\n# Luxun and Lianhuanhua\n\n"
        "## 核心论点\n（录制无有效音频,无法摘要)\n\n"
        "## 分节摘要\n### （无）\n（录制无有效音频,无法摘要)\n\n"
        "## 关键概念\n| 概念 | 英文 | 定义 |\n|------|------|------|\n| （无） |  |  |\n\n"
        "## 项目关联\n- （暂无;待有效音源)\n\n"
        "## 文献人物\n- （录制无有效音频,无法摘要)\n\n"
        "## 时间脉络\n- `[00:00]` （静音,无可标注内容)\n",
        encoding="utf-8",
    )

    full_result = check_file(full)
    silent_result = check_file(silent)

    assert full_result["frontmatter_errors"] == []
    assert full_result["body_violations"] == []
    assert silent_result["frontmatter_errors"] == []
    assert silent_result["body_violations"] == []


def test_typecheck_allows_freeform_transcript_body(tmp_path: Path) -> None:
    fp = tmp_path / "transcript.md"
    fp.write_text(
        "---\n"
        "type: transcript\n"
        "title: Lajilao — 转写\n"
        "talk: lajilao-20241108\n"
        "---\n\n# 垃圾佬 — 转写\n\n"
        "> whisper/soniox 自动转写,未校对。\n\n"
        "`[00:00]` 开场介绍 ...\n\n`[00:45]` 研究起点 ...\n",
        encoding="utf-8",
    )
    result = check_file(fp)
    assert result["frontmatter_errors"] == []
    assert result["body_violations"] == []

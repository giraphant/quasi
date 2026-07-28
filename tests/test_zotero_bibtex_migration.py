from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "migrations" / "zotero_bibtex.py"


def load_module():
    spec = importlib.util.spec_from_file_location("zotero_bibtex", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_and_normalise_zotero_entries(tmp_path: Path) -> None:
    bib = tmp_path / "library.bib"
    bib.write_text(
        r'''@article{doe_example_2024,
  title = {An {Example}: Test},
  author = {Doe, Jane and Roe, Richard},
  year = {2024},
  journal = {Test Journal},
  doi = {https://doi.org/10.1000/ABC},
  abstract = {R\&D, 100\%, item\_1, item\#2},
  copyright = {⭐⭐⭐⭐},
  annote = {A personal note},
  file = {Full Text PDF:/tmp/example.pdf:application/pdf;\;snap},
}

@book{society_handbook_2017,
  title = {The Handbook of Things},
  editor = {{Research and Development Society}},
  year = {2017},
  publisher = {Test Press},
  isbn = {978-0-00-000000-2 978-0-00-000001-9},
}
''',
        encoding="utf-8",
    )

    migration = load_module()
    entries = migration.parse_bibtex(bib)

    assert [entry["entry_key"] for entry in entries] == [
        "doe_example_2024",
        "society_handbook_2017",
    ]
    assert entries[0]["bibtex_type"] == "article"
    assert entries[0]["title"] == "An Example: Test"
    assert entries[0]["authors"] == ["Jane Doe", "Richard Roe"]
    assert entries[0]["doi"] == "10.1000/abc"
    assert entries[0]["has_annote"] is True
    assert entries[0]["abstract"] == "R&D, 100%, item_1, item#2"
    assert entries[0]["parse_error"] is None
    assert entries[1]["authors"] == []
    assert entries[1]["editors"] == ["Research and Development Society"]
    assert entries[1]["isbn"] == "9780000000002"
    assert entries[1]["isbns"] == ["9780000000002", "9780000000019"]
    assert migration.display_person("van Dijck, José") == "José van Dijck"
    assert migration.display_person("{Research and Development Society}") == "Research and Development Society"
    assert migration.display_person("Smith, Jr, John") == "John Smith Jr"


def test_one_parse_failure_does_not_block_other_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bib = tmp_path / "partly-broken.bib"
    bib.write_text(
        "@article{good_one, title={One}}\n"
        "@article{broken, title={Broken}}\n"
        "@book{good_two, title={Two}}\n",
        encoding="utf-8",
    )
    migration = load_module()
    original = migration._parse_bibtex_block

    def fail_one(block: str, directives: list[str]):
        if "@article{broken," in block:
            raise ValueError("synthetic parser failure")
        return original(block, directives)

    monkeypatch.setattr(migration, "_parse_bibtex_block", fail_one)
    entries = migration.parse_bibtex(bib)

    assert [entry["entry_key"] for entry in entries] == [
        "broken",
        "good_one",
        "good_two",
    ]
    assert entries[0]["bibtex_type"] == "article"
    assert entries[0]["parse_error"] == "ValueError: synthetic parser failure"
    assert entries[1]["parse_error"] is None
    assert entries[2]["parse_error"] is None


def test_duplicate_entry_keys_are_rejected(tmp_path: Path) -> None:
    bib = tmp_path / "duplicates.bib"
    bib.write_text(
        "@book{same, title={One}}\n@book{same, title={Two}}\n",
        encoding="utf-8",
    )
    migration = load_module()
    with pytest.raises(ValueError, match="duplicate BibTeX entry key: same"):
        migration.parse_bibtex(bib)


def test_rating_mapping_is_exact() -> None:
    migration = load_module()
    assert migration.map_rating("⭐") == 1
    assert migration.map_rating("⭐⭐") == 2
    assert migration.map_rating("⭐⭐⭐") == 3
    assert migration.map_rating("⭐⭐⭐⭐") == 4
    assert migration.map_rating("⭐⭐⭐⭐⭐") == 5
    assert migration.map_rating("💖") == 5
    assert migration.map_rating("Copyright 2024") is None
    assert migration.map_rating("⭐⭐⭐⭐⭐ extra") is None


def test_attachment_parser_and_pdf_choice(tmp_path: Path) -> None:
    original = tmp_path / "Original.pdf"
    translated = tmp_path / "Original_zh-CN_translation.pdf"
    original.write_bytes(b"%PDF-1.7\n" + b"x" * 2048)
    translated.write_bytes(b"%PDF-1.7\n" + b"y" * 2048)
    raw = (
        f"Original:{original}:application/pdf;"
        f"Translation:{translated}:application/pdf;"
        "Snapshot:/missing/page.html:text/html;"
        "Relative:attachments/file.pdf:application/pdf"
    )
    migration = load_module()
    refs = migration.parse_file_refs(raw)
    path, reason = migration.choose_local_pdf(refs)
    assert path == str(original)
    assert reason == "single-original-pdf"
    assert refs[2]["exists"] is False
    assert refs[3]["path"] is None
    assert refs[3]["raw"] == "Relative:attachments/file.pdf:application/pdf"


def test_multiple_original_pdfs_require_review(tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    first.write_bytes(b"%PDF-1.7\n" + b"a" * 2048)
    second.write_bytes(b"%PDF-1.7\n" + b"b" * 2048)
    migration = load_module()
    refs = migration.parse_file_refs(
        f"A:{first}:application/pdf;B:{second}:application/pdf"
    )
    assert migration.choose_local_pdf(refs) == (None, "multiple-local-pdfs")


def test_work_slug_and_stubs_pass_body_schema() -> None:
    migration = load_module()
    slug = migration.make_work_slug(
        "Code Ethnography and the Materiality of Power",
        ["Fernanda R. Rosa"],
        2022,
    )
    assert slug == "rosa-code-ethnography-and-the-materiality-of-power-2022"
    assert migration.make_work_slug("A Study", ["John Smith Jr"], 2024) == "smith-a-study-2024"
    assert migration.check_body(migration.render_stub("book", "A Book"), migration.BOOK_BODY) == []
    assert migration.check_body(migration.render_stub("paper", "A Paper"), migration.PAPER_BODY) == []


def test_theme_catalog_scans_all_canonical_books_and_papers(tmp_path: Path) -> None:
    migration = load_module()
    journal_paper = tmp_path / "vault" / "journals" / "journal" / "paper.md"
    chapter = tmp_path / "vault" / "books" / "book" / "ch01.md"
    journal_paper.parent.mkdir(parents=True)
    chapter.parent.mkdir(parents=True)
    journal_paper.write_text(
        "---\ntype: paper\ntitle: Journal Paper\nthemes:\n  - scoring\n---\n",
        encoding="utf-8",
    )
    chapter.write_text(
        "---\ntype: chapter\ntitle: Chapter\nthemes:\n  - chapter-only\n---\n",
        encoding="utf-8",
    )

    catalog = migration.collect_theme_catalog(tmp_path)

    assert catalog["scoring"]["examples"] == [{
        "path": "vault/journals/journal/paper.md",
        "title": "Journal Paper",
    }]
    assert "chapter-only" not in catalog


def test_theme_decision_must_use_existing_vocabulary() -> None:
    migration = load_module()
    catalog = {
        "infrastructure-studies": {
            "count": 4,
            "examples": [{"path": "vault/papers/a.md", "title": "A"}],
        },
        "materiality": {
            "count": 8,
            "examples": [{"path": "vault/books/b/00-overview.md", "title": "B"}],
        },
    }
    valid = {
        "entry_key": "x",
        "themes": ["infrastructure-studies", "materiality"],
        "confidence": "high",
        "rationale": "Both are explicit in the abstract.",
    }
    assert migration.validate_theme_decision(valid, catalog) == (
        ["infrastructure-studies", "materiality"],
        None,
    )
    invalid = {**valid, "themes": ["infrastructure-studies", "invented-theme"]}
    assert migration.validate_theme_decision(invalid, catalog)[1] == "unknown-theme"
    catalog["unclassified"] = {"count": 1, "examples": []}
    forbidden = {**valid, "themes": ["materiality", "unclassified"]}
    assert migration.validate_theme_decision(forbidden, catalog)[1] == "forbidden-theme"

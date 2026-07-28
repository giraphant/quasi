from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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


def write_existing_paper(
    project: Path,
    slug: str,
    *,
    doi: str,
    rating: int | None = None,
) -> Path:
    migration = load_module()
    path = project / "vault" / "papers" / f"{slug}.md"
    fm = {
        "type": "paper",
        "title": "Existing Paper",
        "authors": ["Jane Doe"],
        "year": 2024,
        "journal": "Test Journal",
        "themes": ["materiality", "infrastructure-studies"],
        "doi": doi,
    }
    if rating is not None:
        fm["rating"] = rating
    migration.write_frontmatter(
        path,
        fm,
        migration.render_stub("paper", "Existing Paper"),
    )
    return path


def test_journal_paper_is_included_in_vault_index(tmp_path: Path) -> None:
    migration = load_module()
    path = tmp_path / "vault" / "journals" / "journal" / "10_1000_x.md"
    migration.write_frontmatter(
        path,
        {
            "type": "paper",
            "title": "Existing Paper",
            "authors": ["Jane Doe"],
            "year": 2024,
            "journal": "Test Journal",
            "themes": ["scoring"],
            "doi": "10.1000/x",
        },
        migration.render_stub("paper", "Existing Paper"),
    )

    index = migration.build_vault_index(tmp_path)

    assert index["by_doi"]["10.1000/x"][0]["path"] == (
        "vault/journals/journal/10_1000_x.md"
    )


def test_duplicate_identifier_is_review(tmp_path: Path) -> None:
    write_existing_paper(tmp_path, "first-2024", doi="10.1000/x")
    write_existing_paper(tmp_path, "second-2024", doi="10.1000/x")
    migration = load_module()
    entry = {
        "entry_key": "x",
        "bibtex_type": "article",
        "title": "Existing Paper",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": "10.1000/x",
        "isbn": None,
        "publisher": None,
        "rating": None,
        "abstract": "Material infrastructure.",
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {"materiality": {"count": 1, "examples": []}},
    )
    assert assessed["status"] == "review"
    assert assessed["reason"] == "identifier-matches-multiple-objects"
    assert assessed["match_basis"] == "doi"


def test_new_paper_with_local_pdf_routes_to_process(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    migration = load_module()
    entry = {
        "entry_key": "new",
        "bibtex_type": "article",
        "title": "A New Paper",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": "10.1000/new",
        "isbn": None,
        "publisher": None,
        "rating": 5,
        "abstract": "An abstract.",
        "file_refs": [
            {"path": str(pdf), "mime": "application/pdf", "exists": True}
        ],
        "has_annote": True,
        "has_note": False,
        "has_keywords": True,
    }
    catalog = {
        "materiality": {"count": 2, "examples": []},
        "infrastructure-studies": {"count": 2, "examples": []},
    }
    decisions = {
        "new": {
            "entry_key": "new",
            "themes": ["materiality", "infrastructure-studies"],
            "confidence": "high",
            "rationale": "Explicit in title and abstract.",
        }
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        decisions,
        catalog,
    )
    assert assessed["status"] == "safe-create"
    assert assessed["route"] == "process-local-pdf"
    assert assessed["preferred_pdf"] == str(pdf)
    assert assessed["canonical"]["themes"] == [
        "materiality",
        "infrastructure-studies",
    ]


def test_deferred_type_still_records_preferred_local_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "chapter.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    migration = load_module()
    entry = {
        "entry_key": "chapter",
        "bibtex_type": "incollection",
        "file_refs": [
            {"path": str(pdf), "mime": "application/pdf", "exists": True},
            {
                "raw": "Relative:file.pdf:application/pdf",
                "path": None,
                "mime": "application/pdf",
                "exists": False,
            },
        ],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "deferred-type"
    assert assessed["preferred_pdf"] == str(pdf)
    assert assessed["preferred_pdf_reason"] == "single-local-pdf"
    assert assessed["attachment_review"] == [
        {
            "raw": "Relative:file.pdf:application/pdf",
            "reason": "unparsed-attachment-path",
        }
    ]


def test_new_paper_without_pdf_needs_valid_theme_decision(tmp_path: Path) -> None:
    migration = load_module()
    entry = {
        "entry_key": "new",
        "bibtex_type": "article",
        "title": "A New Paper",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": "10.1000/new",
        "isbn": None,
        "publisher": None,
        "rating": None,
        "abstract": "Material infrastructure.",
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": True,
    }
    catalog = {
        "materiality": {"count": 2, "examples": []},
        "infrastructure-studies": {"count": 2, "examples": []},
    }
    pending = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        catalog,
    )
    assert pending["status"] == "review"
    assert pending["reason"] == "theme-decision-missing"
    decided = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {
            "new": {
                "entry_key": "new",
                "themes": ["materiality", "infrastructure-studies"],
                "confidence": "high",
                "rationale": "Explicit in abstract.",
            }
        },
        catalog,
    )
    assert decided["status"] == "safe-create"
    assert decided["route"] == "metadata-only"


def test_safe_enrich_never_routes_to_process_local_pdf(tmp_path: Path) -> None:
    path = write_existing_paper(tmp_path, "existing-2024", doi="10.1000/x")
    migration = load_module()
    fm = migration.read_frontmatter(path).frontmatter
    assert fm is not None
    fm.pop("rating", None)
    migration.write_frontmatter(path, fm, migration.read_frontmatter(path).body)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    entry = {
        "entry_key": "x",
        "bibtex_type": "article",
        "title": "Existing Paper",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": "10.1000/x",
        "isbn": None,
        "publisher": None,
        "rating": 5,
        "abstract": None,
        "file_refs": [
            {"path": str(pdf), "mime": "application/pdf", "exists": True}
        ],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "safe-enrich"
    assert assessed["route"] == "metadata-only"
    assert assessed["preferred_pdf"] == str(pdf)
    assert assessed["preferred_pdf_reason"] == "single-local-pdf"


def test_different_subtitles_do_not_match_on_two_short_title_keys(
    tmp_path: Path,
) -> None:
    path = write_existing_paper(
        tmp_path,
        "volume-eros-2024",
        doi="10.1000/existing",
    )
    migration = load_module()
    doc = migration.read_frontmatter(path)
    assert doc.frontmatter is not None
    doc.frontmatter["title"] = "Volume One: Eros"
    migration.write_frontmatter(path, doc.frontmatter, doc.body)
    entry = {
        "entry_key": "aphrodite",
        "bibtex_type": "article",
        "title": "Volume One: Aphrodite",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Journal",
        "doi": None,
        "isbn": None,
        "publisher": None,
        "rating": None,
        "abstract": "Material infrastructure.",
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    catalog = {
        "materiality": {"count": 1, "examples": []},
        "infrastructure-studies": {"count": 1, "examples": []},
    }
    decisions = {
        "aphrodite": {
            "entry_key": "aphrodite",
            "themes": ["materiality", "infrastructure-studies"],
            "confidence": "high",
            "rationale": "Explicit in abstract.",
        }
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        decisions,
        catalog,
    )
    assert assessed["status"] == "safe-create"
    assert assessed["match"] is None
    assert assessed["match_basis"] is None


def test_title_author_match_with_different_given_name_is_review(
    tmp_path: Path,
) -> None:
    write_existing_paper(tmp_path, "existing-2024", doi="10.1000/existing")
    migration = load_module()
    entry = {
        "entry_key": "other-doe",
        "bibtex_type": "article",
        "title": "Existing Paper",
        "authors": ["John Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": None,
        "isbn": None,
        "isbns": [],
        "publisher": None,
        "rating": None,
        "abstract": None,
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "review"
    assert assessed["match_basis"] == "title-author"
    assert assessed["conflicts"] == ["authors"]


def test_identifier_match_with_different_subtitle_is_review(
    tmp_path: Path,
) -> None:
    path = write_existing_paper(
        tmp_path,
        "volume-eros-2024",
        doi="10.1000/same",
    )
    migration = load_module()
    doc = migration.read_frontmatter(path)
    assert doc.frontmatter is not None
    doc.frontmatter["title"] = "Volume One: Eros"
    migration.write_frontmatter(path, doc.frontmatter, doc.body)
    entry = {
        "entry_key": "aphrodite",
        "bibtex_type": "article",
        "title": "Volume One: Aphrodite",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": "10.1000/same",
        "isbn": None,
        "isbns": [],
        "publisher": None,
        "rating": None,
        "abstract": None,
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "review"
    assert assessed["reason"] == "field-conflict"
    assert assessed["conflicts"] == ["title"]


def test_book_matches_any_source_isbn_without_false_conflict(
    tmp_path: Path,
) -> None:
    migration = load_module()
    path = tmp_path / "vault" / "books" / "doe-book-2024" / "00-overview.md"
    migration.write_frontmatter(
        path,
        {
            "type": "book",
            "title": "Book",
            "authors": ["Jane Doe"],
            "year": 2024,
            "publisher": "Press",
            "isbn": "9780000000019",
            "category": "monograph",
            "themes": [],
        },
        migration.render_stub("book", "Book"),
    )
    entry = {
        "entry_key": "book",
        "bibtex_type": "book",
        "title": "Book",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "publisher": "Press",
        "isbn": "9780000000002",
        "isbns": ["9780000000002", "9780000000019"],
        "doi": None,
        "journal": None,
        "rating": None,
        "abstract": None,
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "exact-existing"
    assert assessed["match_basis"] == "isbn"
    assert assessed.get("conflicts") is None


def test_missing_required_metadata_is_invalid_source(tmp_path: Path) -> None:
    migration = load_module()
    entry = {
        "entry_key": "broken",
        "bibtex_type": "article",
        "title": "Broken",
        "authors": [],
        "editors": [],
        "year": 2024,
        "journal": None,
        "doi": None,
        "isbn": None,
        "publisher": None,
        "rating": None,
        "abstract": None,
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "invalid-source"
    assert assessed["reason"] == "missing-paper-authors-or-journal"


def test_parse_error_is_invalid_source(tmp_path: Path) -> None:
    migration = load_module()
    entry = migration._invalid_parse_entry(
        "@article{broken, title={Broken}}",
        1,
        ValueError("bad entry"),
    )
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "invalid-source"
    assert assessed["reason"] == "bibtex-parse-error"
    assert assessed["parse_error"] == "ValueError: bad entry"


def test_book_authors_take_precedence_over_editors() -> None:
    migration = load_module()
    kind, candidate, error = migration.map_candidate(
        {
            "entry_key": "book",
            "bibtex_type": "book",
            "title": "A Book",
            "authors": ["Jane Doe"],
            "editors": ["Richard Roe"],
            "year": 2024,
            "publisher": "Press",
            "isbn": None,
            "doi": None,
            "rating": None,
        },
        None,
    )
    assert error is None
    assert kind == "book"
    assert candidate["authors"] == ["Jane Doe"]
    assert candidate["category"] == "other"


def test_batch_one_contains_25_articles_and_25_books() -> None:
    migration = load_module()
    rows = [
        {"entry_key": f"a-{i:02d}", "bibtex_type": "article"}
        for i in range(30)
    ] + [
        {"entry_key": f"b-{i:02d}", "bibtex_type": "book"}
        for i in range(30)
    ]
    assigned = migration.assign_batches(rows)
    pilot = [row for row in assigned if row["batch"] == 1]
    assert sum(row["bibtex_type"] == "article" for row in pilot) == 25
    assert sum(row["bibtex_type"] == "book" for row in pilot) == 25


def test_source_entries_with_same_identifier_are_both_review() -> None:
    migration = load_module()
    rows = [
        {
            "entry_key": key,
            "bibtex_type": "article",
            "status": "safe-create",
            "route": "metadata-only",
            "target_path": f"vault/papers/{key}.md",
            "source_fields": {
                "doi": "10.1000/same",
                "isbn": None,
                "isbns": [],
            },
        }
        for key in ("first", "second")
    ]
    collided = migration.mark_source_collisions(rows)
    assert [row["status"] for row in collided] == ["review", "review"]
    assert all(row["reason"] == "source-entry-collision" for row in collided)
    assert all(row["collision_basis"] == ["doi"] for row in collided)


def test_schema_validation_error_is_invalid_source(tmp_path: Path) -> None:
    migration = load_module()
    entry = {
        "entry_key": "invalid-schema",
        "bibtex_type": "book",
        "title": "X",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "publisher": "Press",
        "isbn": None,
        "isbns": [],
        "doi": None,
        "journal": None,
        "rating": None,
        "abstract": None,
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }

    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )

    assert assessed["status"] == "invalid-source"
    assert assessed["reason"] == "schema-validation-error"


def test_conflicting_safe_enrichments_for_same_target_are_review() -> None:
    migration = load_module()
    rows = [
        {
            "entry_key": key,
            "bibtex_type": "article",
            "status": "safe-enrich",
            "route": "metadata-only",
            "target_path": "vault/papers/existing.md",
            "source_fields": {"doi": None, "isbn": None, "isbns": []},
            "enrich_fields": {"rating": rating},
        }
        for key, rating in (("first", 4), ("second", 5))
    ]

    collided = migration.mark_source_collisions(rows)

    assert [row["status"] for row in collided] == ["review", "review"]
    assert all(row["reason"] == "source-entry-collision" for row in collided)
    assert all(row["collision_basis"] == ["target"] for row in collided)


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_inventory_is_read_only_and_writes_stable_artifacts(tmp_path: Path) -> None:
    migration = load_module()
    (tmp_path / "vault" / "papers").mkdir(parents=True)
    source = tmp_path / "library.bib"
    source.write_text(
        "@article{x, title={New Paper}, author={Doe, Jane}, year={2024}, "
        "journal={Journal}, abstract={Material infrastructure.}}\n",
        encoding="utf-8",
    )
    output = tmp_path / "processing" / "imports" / "zotero-test"
    before = sorted(path.relative_to(tmp_path) for path in (tmp_path / "vault").rglob("*"))
    proc = run_cli(
        "inventory",
        "--source", str(source),
        "--project-root", str(tmp_path),
        "--output-dir", str(output),
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    after = sorted(path.relative_to(tmp_path) for path in (tmp_path / "vault").rglob("*"))
    assert after == before
    assert (output / "source.bib").read_bytes() == source.read_bytes()
    rows = [json.loads(line) for line in (output / "entries.jsonl").read_text().splitlines()]
    assert rows[0]["status"] == "review"
    assert rows[0]["reason"] == "theme-decision-missing"
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["counts"]["entries"] == 1
    assert manifest["schema_version"] == migration.SCHEMA_VERSION


def test_inventory_is_idempotent_and_rejects_source_replacement(tmp_path: Path) -> None:
    (tmp_path / "vault" / "papers").mkdir(parents=True)
    source = tmp_path / "library.bib"
    source.write_text(
        "@book{x, title={Book}, author={Doe, Jane}, year={2024}, publisher={Press}}\n",
        encoding="utf-8",
    )
    output = tmp_path / "processing" / "imports" / "zotero-test"
    args = (
        "inventory", "--source", str(source), "--project-root", str(tmp_path),
        "--output-dir", str(output),
    )
    first = run_cli(*args, cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    before = {name: (output / name).read_bytes() for name in ("source.bib", "manifest.json", "entries.jsonl")}
    second = run_cli(*args, cwd=tmp_path)
    assert second.returncode == 0, second.stderr
    after = {name: (output / name).read_bytes() for name in before}
    assert after == before

    replacement = tmp_path / "replacement.bib"
    replacement.write_text(
        "@book{y, title={Other}, author={Roe, Jane}, year={2023}, publisher={Press}}\n",
        encoding="utf-8",
    )
    rejected = run_cli(
        "inventory", "--source", str(replacement), "--project-root", str(tmp_path),
        "--output-dir", str(output), cwd=tmp_path,
    )
    assert rejected.returncode == 2
    assert "source.bib hash mismatch" in rejected.stderr


def test_failed_first_run_does_not_block_corrected_retry(tmp_path: Path) -> None:
    (tmp_path / "vault" / "papers").mkdir(parents=True)
    source = tmp_path / "library.bib"
    source.write_text(
        "@article{dup, title={One}, author={Doe, Jane}, year={2024}, journal={J}}\n"
        "@article{dup, title={Two}, author={Doe, Jane}, year={2024}, journal={J}}\n",
        encoding="utf-8",
    )
    output = tmp_path / "processing" / "imports" / "zotero-test"
    args = (
        "inventory", "--source", str(source), "--project-root", str(tmp_path),
        "--output-dir", str(output),
    )
    failed = run_cli(*args, cwd=tmp_path)
    assert failed.returncode == 2, failed.stderr
    assert "duplicate BibTeX entry key: dup" in failed.stderr
    assert not (output / "source.bib").exists()

    source.write_text(
        "@article{x, title={Fixed}, author={Doe, Jane}, year={2024}, "
        "journal={Journal}, abstract={Material infrastructure.}}\n",
        encoding="utf-8",
    )
    fixed = run_cli(*args, cwd=tmp_path)
    assert fixed.returncode == 0, fixed.stderr
    assert (output / "source.bib").read_bytes() == source.read_bytes()


def test_apply_metadata_only_preserves_body_and_rerun_preserves_verification(tmp_path: Path) -> None:
    migration = load_module()
    existing = write_existing_paper(tmp_path, "existing-2024", doi="10.1000/x")
    doc = migration.read_frontmatter(existing)
    assert doc.frontmatter is not None
    doc.frontmatter.pop("rating", None)
    body_before = doc.body
    migration.write_frontmatter(existing, doc.frontmatter, body_before)

    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-enrich",
        "route": "metadata-only", "batch": 1,
        "target_path": str(existing.relative_to(tmp_path)),
        "canonical": {**doc.frontmatter, "rating": 5},
        "enrich_fields": {"rating": 5}, "preferred_pdf": None,
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    output = tmp_path / "processing"
    first = migration.apply_batch(tmp_path, inventory, 1, approved, output)
    changes = output / "batch-001-changes.json"
    migration.verify_changes(tmp_path, changes)
    second = migration.apply_batch(tmp_path, inventory, 1, approved, output)

    final_doc = migration.read_frontmatter(existing)
    assert final_doc.body == body_before
    assert final_doc.frontmatter["rating"] == 5
    assert first["entries"][0]["action"] == "enriched"
    assert second["entries"][0]["action"] == "enriched"
    assert second["entries"][0]["reapply_action"] == "no-op"
    assert second["entries"][0]["verified"] is True

    drifted = migration.read_frontmatter(existing)
    assert drifted.frontmatter is not None
    drifted.frontmatter["journal"] = "Changed after apply"
    migration.write_frontmatter(existing, drifted.frontmatter, drifted.body)
    checked = migration.verify_changes(tmp_path, changes)
    assert checked["entries"][0]["verified"] is False
    assert checked["entries"][0]["verification"]["error"] == "frontmatter-changed"
    with pytest.raises(ValueError, match="reapply is not a no-op"):
        migration.apply_batch(tmp_path, inventory, 1, approved, output)


def test_apply_enrich_rejects_post_inventory_conflict(tmp_path: Path) -> None:
    migration = load_module()
    existing = write_existing_paper(tmp_path, "existing-2024", doi="10.1000/x")
    doc = migration.read_frontmatter(existing)
    assert doc.frontmatter is not None
    doc.frontmatter["rating"] = 1
    migration.write_frontmatter(existing, doc.frontmatter, doc.body)
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-enrich",
        "route": "metadata-only", "batch": 1,
        "target_path": str(existing.relative_to(tmp_path)),
        "canonical": {**doc.frontmatter, "rating": 5},
        "enrich_fields": {"rating": 5}, "preferred_pdf": None,
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")

    with pytest.raises(ValueError, match="enrichment conflict"):
        migration.apply_batch(tmp_path, inventory, 1, approved, tmp_path / "out")

    current = migration.read_frontmatter(existing)
    assert current.frontmatter["rating"] == 1
    assert current.body == doc.body


def test_apply_local_pdf_stages_source_without_writing_vault(tmp_path: Path) -> None:
    migration = load_module()
    pdf = tmp_path / "zotero.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "process-local-pdf", "batch": 1,
        "target_path": "vault/papers/doe-paper-2024.md",
        "canonical": {
            "type": "paper", "title": "Paper", "authors": ["Jane Doe"],
            "year": 2024, "journal": "Journal",
            "themes": ["materiality", "infrastructure-studies"], "rating": 5,
        },
        "preferred_pdf": str(pdf),
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    result = migration.apply_batch(tmp_path, inventory, 1, approved, tmp_path / "out")
    assert (tmp_path / "sources" / "doe-paper-2024.pdf").read_bytes() == pdf.read_bytes()
    assert not (tmp_path / "vault" / "papers" / "doe-paper-2024.md").exists()
    assert result["entries"][0]["action"] == "staged-local-pdf"
    assert result["entries"][0]["artifact_paths"] == []


def test_reapply_rejects_missing_staged_pdf_without_recreating_it(tmp_path: Path) -> None:
    migration = load_module()
    pdf = tmp_path / "zotero.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "process-local-pdf", "batch": 1,
        "target_path": "vault/papers/doe-paper-2024.md",
        "canonical": {"type": "paper", "title": "Paper", "authors": ["Jane Doe"],
                      "year": 2024, "journal": "Journal",
                      "themes": ["materiality", "infrastructure-studies"]},
        "preferred_pdf": str(pdf),
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    output = tmp_path / "out"
    migration.apply_batch(tmp_path, inventory, 1, approved, output)
    staged = tmp_path / "sources" / "doe-paper-2024.pdf"
    staged.unlink()

    with pytest.raises(ValueError, match="reapply is not a no-op"):
        migration.apply_batch(tmp_path, inventory, 1, approved, output)
    assert not staged.exists()


def test_apply_rejects_unsafe_key_and_staged_pdf_conflict(tmp_path: Path) -> None:
    migration = load_module()
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "review", "bibtex_type": "article", "status": "review",
        "route": "manual-review", "batch": 1, "target_path": None,
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["review"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="approved key is not safe"):
        migration.apply_batch(tmp_path, inventory, 1, approved, tmp_path / "out")

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\n" + b"s" * 2048)
    staged = tmp_path / "sources" / "doe-paper-2024.pdf"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"%PDF-1.7\n" + b"x" * 2048)
    migration.write_jsonl(inventory, [{
        "entry_key": "pdf", "bibtex_type": "article", "status": "safe-create",
        "route": "process-local-pdf", "batch": 1,
        "target_path": "vault/papers/doe-paper-2024.md",
        "canonical": {"type": "paper", "title": "Paper", "authors": ["Jane Doe"],
                      "year": 2024, "journal": "Journal",
                      "themes": ["materiality", "infrastructure-studies"]},
        "preferred_pdf": str(source),
    }])
    approved.write_text('["pdf"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="staged PDF conflict"):
        migration.apply_batch(tmp_path, inventory, 1, approved, tmp_path / "out")


def test_metadata_only_create_passes_schema_and_body_check(tmp_path: Path) -> None:
    migration = load_module()
    inventory = tmp_path / "entries.jsonl"
    canonical = {
        "type": "paper", "title": "Paper", "authors": ["Jane Doe"],
        "year": 2024, "journal": "Journal",
        "themes": ["materiality", "infrastructure-studies"],
    }
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "metadata-only", "batch": 1,
        "target_path": "vault/papers/doe-paper-2024.md",
        "canonical": canonical, "preferred_pdf": None,
        "attachment_review": [{
            "raw": "Relative:file.pdf:application/pdf",
            "reason": "unparsed-attachment-path",
        }],
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    result = migration.apply_batch(tmp_path, inventory, 1, approved, tmp_path / "out")
    target = tmp_path / "vault" / "papers" / "doe-paper-2024.md"
    checked = migration.check_file(target)
    assert checked["frontmatter_errors"] == []
    assert checked["body_violations"] == []
    assert "待分析（由 Zotero 迁移创建）。" in target.read_text(encoding="utf-8")
    assert result["entries"][0]["artifact_paths"] == ["vault/papers/doe-paper-2024.md"]
    review_rows = json.loads(
        (tmp_path / "out" / "batch-001-review.json").read_text(encoding="utf-8")
    )["entries"]
    assert review_rows[0]["entry_key"] == "x"
    assert review_rows[0]["attachment_review"][0]["reason"] == "unparsed-attachment-path"


def test_finalize_process_product_preserves_body_and_records_artifacts(tmp_path: Path) -> None:
    migration = load_module()
    pdf = tmp_path / "zotero.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    inventory = tmp_path / "entries.jsonl"
    canonical = {
        "type": "paper", "title": "Paper", "authors": ["Jane Doe"],
        "year": 2024, "journal": "Journal", "doi": "10.1000/x",
        "themes": ["materiality", "infrastructure-studies"], "rating": 5,
    }
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "process-local-pdf", "batch": 1,
        "target_path": "vault/papers/doe-paper-2024.md",
        "canonical": canonical, "preferred_pdf": str(pdf),
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    output = tmp_path / "out"
    migration.apply_batch(tmp_path, inventory, 1, approved, output)
    target = tmp_path / "vault" / "papers" / "doe-paper-2024.md"
    produced = {key: value for key, value in canonical.items() if key not in {"rating", "themes"}}
    produced["themes"] = ["agent-invented-theme"]
    body = migration.render_stub("paper", "Paper")
    migration.write_frontmatter(target, produced, body)

    changes = output / "batch-001-changes.json"
    migration.finalize_entry(tmp_path, inventory, changes, "x")
    final_doc = migration.read_frontmatter(target)
    payload = json.loads(changes.read_text(encoding="utf-8"))
    assert final_doc.body == body
    assert final_doc.frontmatter["rating"] == 5
    assert final_doc.frontmatter["themes"] == ["materiality", "infrastructure-studies"]
    assert payload["entries"][0]["action"] == "processed-local-pdf"
    assert payload["entries"][0]["artifact_paths"] == ["vault/papers/doe-paper-2024.md"]

    migration.verify_changes(tmp_path, changes)
    migration.write_frontmatter(target, final_doc.frontmatter, body + "\nDrift.\n")
    with pytest.raises(ValueError, match="reapply is not a no-op"):
        migration.apply_batch(tmp_path, inventory, 1, approved, output)


def test_finalize_book_records_overview_chapters_and_extraction_artifacts(tmp_path: Path) -> None:
    migration = load_module()
    slug = "doe-book-2024"
    overview = tmp_path / "vault" / "books" / slug / "00-overview.md"
    chapter = overview.parent / "ch01-opening.md"
    extracted = tmp_path / "processing" / "chapters" / slug / "ch01.txt"
    migration.write_frontmatter(overview, {
        "type": "book", "title": "Book", "authors": ["Jane Doe"],
        "year": 2024, "publisher": "Press", "category": "monograph",
        "themes": [],
    }, migration.render_stub("book", "Book"))
    chapter.write_text("# Chapter\n", encoding="utf-8")
    extracted.parent.mkdir(parents=True)
    extracted.write_text("chapter text\n", encoding="utf-8")
    row = {"target_path": f"vault/books/{slug}/00-overview.md"}
    assert migration.collect_process_artifacts(tmp_path, row) == [
        f"processing/chapters/{slug}/ch01.txt",
        f"vault/books/{slug}/00-overview.md",
        f"vault/books/{slug}/ch01-opening.md",
    ]


def test_finalize_book_enforces_conservative_canonical_category(tmp_path: Path) -> None:
    migration = load_module()
    slug = "doe-book-2024"
    pdf = tmp_path / "zotero.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    inventory = tmp_path / "entries.jsonl"
    canonical = {
        "type": "book", "title": "Book", "authors": ["Jane Doe"],
        "year": 2024, "publisher": "Press", "category": "other",
    }
    migration.write_jsonl(inventory, [{
        "entry_key": "book", "bibtex_type": "book", "status": "safe-create",
        "route": "process-local-pdf", "batch": 1,
        "target_path": f"vault/books/{slug}/00-overview.md",
        "canonical": canonical, "preferred_pdf": str(pdf),
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["book"]\n', encoding="utf-8")
    output = tmp_path / "out"
    migration.apply_batch(tmp_path, inventory, 1, approved, output)
    overview = tmp_path / "vault" / "books" / slug / "00-overview.md"
    produced = {**canonical, "category": "monograph"}
    migration.write_frontmatter(
        overview, produced, migration.render_stub("book", "Book")
    )

    migration.finalize_entry(
        tmp_path, inventory, output / "batch-001-changes.json", "book"
    )

    assert migration.read_frontmatter(overview).frontmatter["category"] == "other"


def test_verify_and_record_failure_keep_failed_items_unverified(tmp_path: Path) -> None:
    migration = load_module()
    pdf = tmp_path / "zotero.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [
        {"entry_key": "ok", "bibtex_type": "article", "status": "safe-create",
         "route": "metadata-only", "batch": 1, "target_path": "vault/papers/ok.md",
         "canonical": {"type": "paper", "title": "OK", "authors": ["Jane Doe"],
                       "year": 2024, "journal": "Journal",
                       "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": None},
        {"entry_key": "audit", "bibtex_type": "article", "status": "safe-create",
         "route": "metadata-only", "batch": 1, "target_path": "vault/papers/audit.md",
         "canonical": {"type": "paper", "title": "Audit", "authors": ["Jane Doe"],
                       "year": 2024, "journal": "Journal",
                       "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": None},
        {"entry_key": "bad", "bibtex_type": "article", "status": "safe-create",
         "route": "process-local-pdf", "batch": 1, "target_path": "vault/papers/missing.md",
         "canonical": {"type": "paper", "title": "Partial", "authors": ["Jane Doe"],
                       "year": 2024, "journal": "Journal",
                       "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": str(pdf)},
    ])
    approved = tmp_path / "approved.json"
    approved.write_text('["ok", "audit", "bad"]\n', encoding="utf-8")
    output = tmp_path / "out"
    migration.apply_batch(tmp_path, inventory, 1, approved, output)
    # simulate a partial process product so record_failure captures it as a partial artifact
    migration.write_frontmatter(
        tmp_path / "vault" / "papers" / "missing.md",
        {"type": "paper", "title": "Partial", "authors": ["Jane Doe"],
         "year": 2024, "journal": "Journal",
         "themes": ["materiality", "infrastructure-studies"]},
        migration.render_stub("paper", "Partial"),
    )
    changes = output / "batch-001-changes.json"
    review = output / "batch-001-review.json"
    failed = migration.record_failure(
        tmp_path, inventory, changes, review, "bad", "workflow returned audit_escalated",
    )
    audit_failed = migration.record_failure(
        tmp_path, inventory, changes, review, "audit", "targeted audit returned partial",
    )
    verified = migration.verify_changes(tmp_path, changes)
    by_key = {entry["entry_key"]: entry for entry in verified["entries"]}
    assert by_key["ok"]["verified"] is True
    assert by_key["audit"]["verified"] is False
    assert by_key["bad"]["verified"] is False
    assert by_key["bad"]["failure_reason"] == "workflow returned audit_escalated"
    assert failed["partial_artifact_paths"] == ["vault/papers/missing.md"]
    assert audit_failed["partial_artifact_paths"] == ["vault/papers/audit.md"]
    review_rows = {
        row["entry_key"]: row
        for row in json.loads(review.read_text(encoding="utf-8"))["entries"]
    }
    assert review_rows["bad"]["execution_failure"] == "workflow returned audit_escalated"
    assert review_rows["audit"]["execution_failure"] == "targeted audit returned partial"


def test_progress_and_report_accept_completion_at_or_above_target(tmp_path: Path) -> None:
    migration = load_module()
    pdf = tmp_path / "zotero.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    book_pdf = tmp_path / "book.pdf"
    book_pdf.write_bytes(b"%PDF-1.7\n" + b"b" * 2048)
    inventory = tmp_path / "entries.jsonl"
    rows = [
        {"entry_key": f"exact-{index:03d}", "status": "exact-existing",
         "route": "exact-existing", "bibtex_type": "book"}
        for index in range(523)
    ]
    rows += [
        {"entry_key": "metadata", "bibtex_type": "article", "status": "safe-create",
         "route": "metadata-only", "batch": 1, "target_path": "vault/papers/metadata.md",
         "canonical": {"type": "paper", "title": "Metadata", "authors": ["Jane Doe"],
                       "year": 2024, "journal": "Journal",
                       "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": None},
        {"entry_key": "pdf", "bibtex_type": "article", "status": "safe-create",
         "route": "process-local-pdf", "batch": 1, "target_path": "vault/papers/pdf.md",
         "canonical": {"type": "paper", "title": "PDF", "authors": ["Jane Doe"],
                       "year": 2024, "journal": "Journal", "rating": 5,
                       "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": str(pdf)},
        {"entry_key": "review", "bibtex_type": "article", "status": "review",
         "route": "manual-review"},
        {"entry_key": "failed", "bibtex_type": "book", "status": "safe-create",
         "route": "process-local-pdf", "batch": 1,
         "target_path": "vault/books/failed/00-overview.md",
         "canonical": {"type": "book", "title": "Failed", "authors": ["Jane Doe"],
                       "year": 2024, "publisher": "Press", "category": "monograph"},
         "preferred_pdf": str(book_pdf)},
    ]
    migration.write_jsonl(inventory, rows)
    approved = tmp_path / "approved.json"
    approved.write_text('["metadata", "pdf", "failed"]\n', encoding="utf-8")
    output = tmp_path / "out"
    migration.apply_batch(tmp_path, inventory, 1, approved, output)
    # simulate quasi:process-material producing the pdf paper, then finalize + record the failure
    migration.write_frontmatter(
        tmp_path / "vault" / "papers" / "pdf.md",
        {"type": "paper", "title": "PDF", "authors": ["Jane Doe"], "year": 2024,
         "journal": "Journal", "themes": ["agent-invented-theme"]},
        migration.render_stub("paper", "PDF"),
    )
    changes = output / "batch-001-changes.json"
    migration.finalize_entry(tmp_path, inventory, changes, "pdf")
    migration.record_failure(
        tmp_path, inventory, changes, output / "batch-001-review.json",
        "failed", "process returned partial",
    )
    migration.verify_changes(tmp_path, changes)
    changes_dir = output
    progress = migration.progress_summary(inventory, changes_dir)
    assert progress == {
        "denominator": 2100, "target": 525, "completed": 525,
        "remaining_to_target": 0, "milestone_reached": True,
    }
    report_output = tmp_path / "milestone.json"
    report = migration.milestone_report(inventory, changes_dir, report_output)
    assert report["completed"] == 525
    assert report["exact_existing"] == 523
    assert report["metadata_only_verified"] == 1
    assert report["process_local_pdf_verified"] == 1
    assert report["attachment_review_fragments"] == 0
    assert report["failed_not_counted"] == 1
    assert report["milestone_reached"] is True
    assert json.loads(report_output.read_text(encoding="utf-8")) == report

    migration.write_jsonl(inventory, rows + [{
        "entry_key": "extra", "status": "exact-existing",
        "route": "exact-existing", "bibtex_type": "book",
    }])
    assert migration.progress_summary(inventory, changes_dir)["completed"] == 526

    tampered = json.loads(changes.read_text())
    tampered["entries"][0]["target_path"] = "vault/papers/wrong.md"
    migration.write_json(changes, tampered)
    with pytest.raises(ValueError, match="changes entry does not match inventory"):
        migration.progress_summary(inventory, changes_dir)


def test_report_cli_writes_output(tmp_path: Path) -> None:
    migration = load_module()
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [
        {"entry_key": f"exact-{index:03d}", "status": "exact-existing",
         "route": "exact-existing", "bibtex_type": "book"}
        for index in range(525)
    ])
    output = tmp_path / "milestone.json"
    proc = run_cli(
        "report", "--inventory", str(inventory),
        "--changes-dir", str(tmp_path), "--output", str(output),
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["completed"] == 525


def test_hand_stripped_apply_result_is_rejected_by_verify_and_progress(tmp_path: Path) -> None:
    # Critical 1a: a hand-edited changes entry missing the apply-result payload
    # (after/body_sha256) is rejected by every downstream consumer.
    migration = load_module()
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "metadata-only", "batch": 1, "target_path": "vault/papers/doe-paper-2024.md",
        "canonical": {"type": "paper", "title": "Paper", "authors": ["Jane Doe"],
                      "year": 2024, "journal": "Journal",
                      "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": None,
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    output = tmp_path / "out"
    migration.apply_batch(tmp_path, inventory, 1, approved, output)
    changes = output / "batch-001-changes.json"

    payload = json.loads(changes.read_text(encoding="utf-8"))
    payload["entries"][0].pop("after", None)
    payload["entries"][0].pop("body_sha256", None)
    migration.write_json(changes, payload)

    with pytest.raises(ValueError, match="invalid changes shape"):
        migration.verify_changes(tmp_path, changes)
    with pytest.raises(ValueError, match="invalid changes shape"):
        migration.progress_summary(inventory, output)


def test_verified_entry_without_passing_verification_record_is_rejected(tmp_path: Path) -> None:
    # Critical 1b: verified=True without a passing check_file verification record
    # cannot be counted by progress or baked into a milestone report.
    migration = load_module()
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "metadata-only", "batch": 1, "target_path": "vault/papers/doe-paper-2024.md",
        "canonical": {"type": "paper", "title": "Paper", "authors": ["Jane Doe"],
                      "year": 2024, "journal": "Journal",
                      "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": None,
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    output = tmp_path / "out"
    migration.apply_batch(tmp_path, inventory, 1, approved, output)
    changes = output / "batch-001-changes.json"
    migration.verify_changes(tmp_path, changes)

    payload = json.loads(changes.read_text(encoding="utf-8"))
    payload["entries"][0].pop("verification", None)
    migration.write_json(changes, payload)

    with pytest.raises(ValueError, match="verified entry lacks passing verification"):
        migration.progress_summary(inventory, output)
    with pytest.raises(ValueError, match="verified entry lacks passing verification"):
        migration.milestone_report(inventory, output, tmp_path / "milestone.json")


def test_forged_action_without_restamped_provenance_is_rejected(tmp_path: Path) -> None:
    # Critical 1c: the deterministic provenance fingerprint binds the apply-result
    # action; silently swapping it to another legal action is rejected at finalize.
    migration = load_module()
    pdf = tmp_path / "zotero.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "process-local-pdf", "batch": 1, "target_path": "vault/papers/doe-paper-2024.md",
        "canonical": {"type": "paper", "title": "Paper", "authors": ["Jane Doe"],
                      "year": 2024, "journal": "Journal",
                      "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": str(pdf),
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    output = tmp_path / "out"
    migration.apply_batch(tmp_path, inventory, 1, approved, output)
    changes = output / "batch-001-changes.json"

    payload = json.loads(changes.read_text(encoding="utf-8"))
    entry = payload["entries"][0]
    assert entry["action"] == "staged-local-pdf"
    entry["action"] = "no-op"  # legal process action, but provenance still names staged-local-pdf
    migration.write_json(changes, payload)

    with pytest.raises(ValueError, match="unprovenanced changes entry"):
        migration.finalize_entry(tmp_path, inventory, changes, "x")


def test_apply_rejects_absolute_target_path(tmp_path: Path) -> None:
    # Critical 2: absolute target paths cannot escape the vault chokepoint.
    migration = load_module()
    evil = tmp_path / "evil.md"
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "metadata-only", "batch": 1, "target_path": str(evil),
        "canonical": {"type": "paper", "title": "Paper", "authors": ["Jane Doe"],
                      "year": 2024, "journal": "Journal",
                      "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": None,
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe target path"):
        migration.apply_batch(tmp_path, inventory, 1, approved, tmp_path / "out")
    assert not evil.exists()


def test_apply_rejects_parent_traversal_target_path(tmp_path: Path) -> None:
    # Critical 2: parent-traversal segments cannot escape the vault chokepoint.
    migration = load_module()
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "metadata-only", "batch": 1, "target_path": "vault/papers/../../evil.md",
        "canonical": {"type": "paper", "title": "Paper", "authors": ["Jane Doe"],
                      "year": 2024, "journal": "Journal",
                      "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": None,
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe target path"):
        migration.apply_batch(tmp_path, inventory, 1, approved, tmp_path / "out")
    assert not (tmp_path / "evil.md").exists()


def test_apply_rejects_sources_symlink_escape(tmp_path: Path) -> None:
    # Critical 2: a sources/ symlink pointing outside the project root cannot
    # stage a PDF beyond the root.
    migration = load_module()
    outside = tmp_path.parent / "quasi-pdf-escape"
    outside.mkdir(exist_ok=True)
    sources = tmp_path / "sources"
    pdf = tmp_path / "zotero.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "process-local-pdf", "batch": 1, "target_path": "vault/papers/doe-paper-2024.md",
        "canonical": {"type": "paper", "title": "Paper", "authors": ["Jane Doe"],
                      "year": 2024, "journal": "Journal",
                      "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": str(pdf),
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    try:
        sources.symlink_to(outside)
        with pytest.raises(ValueError, match="staged PDF escapes project root"):
            migration.apply_batch(tmp_path, inventory, 1, approved, tmp_path / "out")
        assert not (outside / "doe-paper-2024.pdf").exists()
    finally:
        if sources.is_symlink():
            sources.unlink()
        if outside.exists():
            outside.rmdir()


def test_finalize_drift_after_body_tamper_is_rejected_and_keeps_unverified(tmp_path: Path) -> None:
    # Critical 3: after a clean finalize + verify, tampering with the body must be
    # rejected on re-finalize (drift), clear the verified flag, and keep the item
    # out of completion counts.
    migration = load_module()
    pdf = tmp_path / "zotero.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    inventory = tmp_path / "entries.jsonl"
    canonical = {
        "type": "paper", "title": "Paper", "authors": ["Jane Doe"],
        "year": 2024, "journal": "Journal", "doi": "10.1000/x", "rating": 5,
        "themes": ["materiality", "infrastructure-studies"],
    }
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "process-local-pdf", "batch": 1, "target_path": "vault/papers/doe-paper-2024.md",
        "canonical": canonical, "preferred_pdf": str(pdf),
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    output = tmp_path / "out"
    migration.apply_batch(tmp_path, inventory, 1, approved, output)
    target = tmp_path / "vault" / "papers" / "doe-paper-2024.md"
    produced = {key: value for key, value in canonical.items() if key not in {"rating", "themes"}}
    produced["themes"] = ["agent-invented-theme"]
    body = migration.render_stub("paper", "Paper")
    migration.write_frontmatter(target, produced, body)
    changes = output / "batch-001-changes.json"
    migration.finalize_entry(tmp_path, inventory, changes, "x")
    migration.verify_changes(tmp_path, changes)

    tampered = migration.read_frontmatter(target)
    migration.write_frontmatter(target, tampered.frontmatter, tampered.body + "\nDrift.\n")
    with pytest.raises(ValueError, match="finalize drift"):
        migration.finalize_entry(tmp_path, inventory, changes, "x")

    verified = migration.verify_changes(tmp_path, changes)
    assert verified["entries"][0]["verified"] is False
    progress = migration.progress_summary(inventory, output)
    assert progress["completed"] == 0


def test_record_failure_corrupt_review_leaves_changes_untouched_and_retries(tmp_path: Path) -> None:
    # Important 1: a corrupt review file fails before any write, so changes are
    # not half-marked-failed; fixing the review lets the same-reason retry converge.
    migration = load_module()
    pdf = tmp_path / "zotero.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "bad", "bibtex_type": "article", "status": "safe-create",
        "route": "process-local-pdf", "batch": 1, "target_path": "vault/papers/missing.md",
        "canonical": {"type": "paper", "title": "Partial", "authors": ["Jane Doe"],
                      "year": 2024, "journal": "Journal",
                      "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": str(pdf),
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["bad"]\n', encoding="utf-8")
    output = tmp_path / "out"
    migration.apply_batch(tmp_path, inventory, 1, approved, output)
    migration.write_frontmatter(
        tmp_path / "vault" / "papers" / "missing.md",
        {"type": "paper", "title": "Partial", "authors": ["Jane Doe"], "year": 2024,
         "journal": "Journal", "themes": ["materiality", "infrastructure-studies"]},
        migration.render_stub("paper", "Partial"),
    )
    changes = output / "batch-001-changes.json"
    review = output / "batch-001-review.json"
    snapshot = changes.read_text(encoding="utf-8")
    review.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        migration.record_failure(tmp_path, inventory, changes, review, "bad", "workflow failed")
    assert changes.read_text(encoding="utf-8") == snapshot
    assert not json.loads(snapshot)["entries"][0].get("failed")

    migration.write_json(review, {"version": 1, "batch": 1, "entries": []})
    result = migration.record_failure(tmp_path, inventory, changes, review, "bad", "workflow failed")
    assert result["failed"] is True
    assert json.loads(changes.read_text(encoding="utf-8"))["entries"][0]["failed"] is True


def test_apply_restores_missing_review_on_rerun(tmp_path: Path) -> None:
    # Important 2: if the review cannot be written, the changes commit marker is
    # not created; once unblocked, a rerun produces a complete review + changes.
    migration = load_module()
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [{
        "entry_key": "x", "bibtex_type": "article", "status": "safe-create",
        "route": "metadata-only", "batch": 1, "target_path": "vault/papers/doe-paper-2024.md",
        "canonical": {"type": "paper", "title": "Paper", "authors": ["Jane Doe"],
                      "year": 2024, "journal": "Journal",
                      "themes": ["materiality", "infrastructure-studies"]}, "preferred_pdf": None,
    }])
    approved = tmp_path / "approved.json"
    approved.write_text('["x"]\n', encoding="utf-8")
    output = tmp_path / "out"
    output.mkdir(parents=True, exist_ok=True)
    review_blocker = output / "batch-001-review.json"
    review_blocker.mkdir()
    (review_blocker / "blocker").write_text("x", encoding="utf-8")

    with pytest.raises(OSError):
        migration.apply_batch(tmp_path, inventory, 1, approved, output)
    assert not (output / "batch-001-changes.json").exists()

    (review_blocker / "blocker").unlink()
    review_blocker.rmdir()
    migration.apply_batch(tmp_path, inventory, 1, approved, output)
    review = output / "batch-001-review.json"
    assert review.is_file()
    assert isinstance(json.loads(review.read_text(encoding="utf-8"))["entries"], list)
    assert (output / "batch-001-changes.json").is_file()


def test_milestone_report_invalidates_stale_reached_artifact(tmp_path: Path) -> None:
    # Important 3: a stale milestone_reached=true artifact cannot survive a later
    # below-target run; the report reflects false on disk before the CLI exits 2.
    migration = load_module()
    inventory = tmp_path / "entries.jsonl"
    migration.write_jsonl(inventory, [
        {"entry_key": f"exact-{index:03d}", "status": "exact-existing",
         "route": "exact-existing", "bibtex_type": "book"}
        for index in range(525)
    ])
    out = tmp_path / "milestone.json"
    report = migration.milestone_report(inventory, tmp_path, out)
    assert report["milestone_reached"] is True
    assert json.loads(out.read_text(encoding="utf-8"))["milestone_reached"] is True

    migration.write_jsonl(inventory, [
        {"entry_key": f"exact-{index:03d}", "status": "exact-existing",
         "route": "exact-existing", "bibtex_type": "book"}
        for index in range(100)
    ])
    with pytest.raises(ValueError, match="milestone incomplete"):
        migration.milestone_report(inventory, tmp_path, out)
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk["milestone_reached"] is False
    assert on_disk["completed"] == 100

    proc = run_cli(
        "report", "--inventory", str(inventory),
        "--changes-dir", str(tmp_path), "--output", str(out), cwd=tmp_path,
    )
    assert proc.returncode == 2
    assert json.loads(out.read_text(encoding="utf-8"))["milestone_reached"] is False

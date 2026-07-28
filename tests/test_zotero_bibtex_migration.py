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

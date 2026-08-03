from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.status import status as status_module


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
STATUS = PLUGIN_ROOT / "scripts" / "status" / "status.py"


def run_status(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    return subprocess.run(
        [sys.executable, str(STATUS), *args],
        cwd=PLUGIN_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )


def write(path: Path, content: str | bytes = "content") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def frontmatter(kind: str) -> str:
    return f"---\ntype: {kind}\n---\n\n# Canonical artifact\n"


def complete_map(payload: dict) -> dict[str, bool | None]:
    return {item["stage"]: item["complete"] for item in payload["stages"]}


def test_status_reports_material_layouts(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    paper = "paper-status"
    write(project / "sources" / f"{paper}.pdf", b"%PDF-paper")
    write(project / "processing" / "papers" / paper / "source.txt", "paper source")
    write(project / "vault" / "papers" / f"{paper}.md", frontmatter("paper"))

    book = "book-status"
    write(project / "sources" / f"{book}.epub", b"EPUB-book")
    chapter_root = project / "processing" / "chapters" / book
    chapters = [
        {
            "slot": "01",
            "slug": "opening",
            "filename": "01_Opening.txt",
        },
        {
            "slot": "02",
            "slug": "closing",
            "filename": "02_Closing.txt",
        },
    ]
    write(chapter_root / "manifest.json", json.dumps({"chapters": chapters}))
    for chapter in chapters:
        write(chapter_root / chapter["filename"], "normalized chapter")
        write(
            project
            / "vault"
            / "books"
            / book
            / f"ch{chapter['slot']}-{chapter['slug']}.md",
            frontmatter("chapter"),
        )
    write(project / "vault" / "books" / book / "00-overview.md", frontmatter("book"))

    talk = "talk-status"
    write(project / "sources" / f"{talk}.mp3", b"talk-audio")
    write(
        project / "processing" / "talks" / talk / "transcript.whisper.srt",
        "1\n00:00:00,000 --> 00:00:01,000\nTranscript\n",
    )
    write(project / "vault" / "talks" / talk / "talk.md", frontmatter("talk"))

    paper_result = run_status(project, "--kind", "paper", "--slug", paper, "--json")
    book_result = run_status(project, "--kind", "book", "--slug", book, "--json")
    talk_result = run_status(project, "--kind", "talk", "--slug", talk, "--json")

    assert paper_result.returncode == book_result.returncode == talk_result.returncode == 0
    paper_payload = json.loads(paper_result.stdout)
    book_payload = json.loads(book_result.stdout)
    talk_payload = json.loads(talk_result.stdout)
    assert complete_map(paper_payload) == {
        "acquire": True,
        "prepare": True,
        "analyse": True,
    }
    assert complete_map(book_payload) == {
        "acquire": True,
        "prepare": True,
        "analyse": True,
        "synthesise": True,
    }
    assert complete_map(talk_payload) == {
        "prepare": True,
        "analyse": True,
    }
    assert paper_payload["next_stage"] is None
    assert book_payload["next_stage"] is None
    assert talk_payload["next_stage"] is None
    # This mirrors book.mts::chapterOutputPath exactly.
    assert book_payload["stages"][2]["evidence"] == [
        f"vault/books/{book}/ch01-opening.md",
        f"vault/books/{book}/ch02-closing.md",
    ]


def test_translation_status_reports_all_existing_derivatives_as_observations(
    tmp_path: Path,
):
    project = tmp_path / "project"
    slug = "multi-translation"
    write(project / "sources" / f"{slug}.pdf", b"%PDF-source")
    for tag in ("zh-cn", "fr-fr"):
        write(
            project / "processing" / "translations" / f"{slug}-{tag}.pdf",
            b"%PDF-translation",
        )
        write(
            project
            / "processing"
            / "translations"
            / f"{slug}-{tag}.manifest.json",
            "{}",
        )

    result = run_status(
        project,
        "--kind",
        "translation",
        "--slug",
        slug,
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["next_stage"] is None
    assert complete_map(payload) == {"acquire": True, "prepare": True}
    assert payload["stages"][1]["evidence"] == [
        f"processing/translations/{slug}-fr-fr.pdf",
        f"processing/translations/{slug}-zh-cn.pdf",
    ]
    assert payload["refs"]["derivatives"] == [
        f"processing/translations/{slug}-fr-fr.pdf",
        f"processing/translations/{slug}-zh-cn.pdf",
    ]


def test_translation_status_keeps_precondition_as_evidence_not_next_stage(
    tmp_path: Path,
):
    project = tmp_path / "project"
    project.mkdir()

    result = run_status(
        project,
        "--kind",
        "translation",
        "--slug",
        "missing-source",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert complete_map(payload) == {"acquire": False, "prepare": False}
    assert payload["next_stage"] == "acquire"
    assert payload["refs"] == {
        "source": "sources/missing-source.pdf",
        "derivatives": [],
    }


def test_status_marks_a_corrupt_book_manifest_incomplete(tmp_path: Path):
    project = tmp_path / "project"
    book = "corrupt-book"
    write(project / "sources" / f"{book}.pdf", b"%PDF-book")
    manifest = write(
        project / "processing" / "chapters" / book / "manifest.json", "{not json",
    )

    result = run_status(project, "--kind", "book", "--slug", book, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert complete_map(payload)["prepare"] is False
    assert payload["next_stage"] == "prepare"
    assert payload["stages"][1]["evidence"] == [
        "processing/chapters/corrupt-book/manifest.json"
    ]
    assert manifest.read_text(encoding="utf-8") == "{not json"


def test_status_empty_project_reports_first_missing_stage_and_exact_refs(tmp_path: Path):
    project = tmp_path / "empty"
    project.mkdir()

    result = run_status(project, "--kind", "paper", "--slug", "missing-paper", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "schema_version": "quasi.status/0.1",
        "kind": "paper",
        "slug": "missing-paper",
        "stages": [
            {"stage": "acquire", "complete": False, "evidence": []},
            {"stage": "prepare", "complete": False, "evidence": []},
            {"stage": "analyse", "complete": False, "evidence": []},
        ],
        "next_stage": "acquire",
        "refs": {"outputs": ["sources/missing-paper.pdf"]},
    }


def test_paper_status_uses_live_pipeline_artifact_template(
    tmp_path: Path, monkeypatch,
):
    project = tmp_path / "project"
    slug = "manifest-paper"
    source = write(project / "alternate-sources" / f"{slug}.pdf", b"%PDF")
    acquire = next(
        item
        for item in status_module.PIPELINE["paper"]["stages"]
        if item["stage"] == "acquire"
    )
    monkeypatch.setitem(
        acquire["artifacts"], "output", "alternate-sources/{slug}.pdf"
    )

    payload = status_module.paper_status(project, slug)

    assert payload["stages"][0]["evidence"] == [
        f"alternate-sources/{slug}.pdf"
    ]
    assert payload["refs"]["input"] == source.relative_to(project).as_posix()


def test_status_scan_discovers_and_deduplicates_kind_specific_layouts(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    write(project / "sources" / "paper-scan.pdf", b"%PDF")
    write(project / "processing" / "papers" / "paper-scan" / "source.txt", "text")
    write(project / "sources" / "book-scan.epub", b"EPUB")
    write(project / "sources" / "talk-scan.wav", b"WAV")

    result = run_status(project, "--scan", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schema_version": "quasi.status-scan/0.1",
        "items": [
            {"kind": "book", "slug": "book-scan", "next_stage": "prepare"},
            {"kind": "paper", "slug": "paper-scan", "next_stage": "analyse"},
            {"kind": "talk", "slug": "talk-scan", "next_stage": "prepare"},
        ],
    }


def test_status_invalid_invocation_returns_json_error(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    result = run_status(project, "--kind", "paper", "--json")

    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_invocation"


def test_status_identity_reads_only_canonical_frontmatter(tmp_path: Path):
    project = tmp_path / "project"
    paper = "identity-paper"
    write(project / "sources" / f"{paper}.pdf", b"%PDF")
    write(project / "processing" / "papers" / paper / "source.txt", "text")
    write(
        project / "vault" / "papers" / f"{paper}.md",
        "---\n"
        "type: paper\n"
        "title: Disk Identity\n"
        "authors:\n"
        "  - Ada Example\n"
        "year: 2024\n"
        "journal: Exact Joins\n"
        "themes:\n"
        "  - admission\n"
        "---\n\n# Disk Identity\n",
    )

    result = run_status(
        project,
        "--kind",
        "paper",
        "--slug",
        paper,
        "--json",
        "--identity",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["identity"] == {
        "title": "Disk Identity",
        "authors": ["Ada Example"],
        "year": 2024,
    }
    without_identity = run_status(
        project, "--kind", "paper", "--slug", paper, "--json"
    )
    assert "identity" not in json.loads(without_identity.stdout)


def test_status_identity_is_null_until_canonical_frontmatter_is_parseable(
    tmp_path: Path,
):
    project = tmp_path / "project"
    paper = "broken-identity"
    write(project / "sources" / f"{paper}.pdf", b"%PDF")
    write(project / "processing" / "papers" / paper / "source.txt", "text")
    write(project / "vault" / "papers" / f"{paper}.md", "not frontmatter")

    result = run_status(
        project,
        "--kind",
        "paper",
        "--slug",
        paper,
        "--json",
        "--identity",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["identity"] is None
    assert complete_map(payload)["analyse"] is False

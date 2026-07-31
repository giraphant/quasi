from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


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


def test_status_reports_all_three_material_layouts(tmp_path: Path):
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
        "audit": None,
    }
    assert complete_map(book_payload) == {
        "acquire": True,
        "prepare": True,
        "analyse": True,
        "synthesise": True,
        "audit": None,
    }
    assert complete_map(talk_payload) == {
        "acquire": True,
        "prepare": True,
        "analyse": True,
        "synthesise": True,
        "audit": None,
    }
    assert paper_payload["next_stage"] is None
    assert book_payload["next_stage"] is None
    assert talk_payload["next_stage"] is None
    # This mirrors book.mjs::chapterOutputPath exactly.
    assert book_payload["stages"][2]["evidence"] == [
        f"vault/books/{book}/ch01-opening.md",
        f"vault/books/{book}/ch02-closing.md",
    ]


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
            {"stage": "audit", "complete": None, "evidence": []},
        ],
        "next_stage": "acquire",
        "refs": {"outputs": ["sources/missing-paper.pdf"]},
    }


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

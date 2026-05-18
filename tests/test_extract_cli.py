from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXTRACT = PLUGIN_ROOT / "scripts" / "extract" / "extract.py"
EXTRACT_DIR = PLUGIN_ROOT / "scripts" / "extract"
sys.path.insert(0, str(EXTRACT_DIR))

import split_chapters  # noqa: E402


def run_extract(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EXTRACT), *args],
        cwd=PLUGIN_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_extract_help_exposes_agent_contract():
    result = run_extract("--help")

    assert result.returncode == 0
    assert "quasi-extract epub" in result.stdout
    assert "quasi-extract ocr" in result.stdout
    assert "quasi-extract split" in result.stdout


def test_extract_rejects_unknown_subcommand():
    result = run_extract("inspect")

    assert result.returncode == 2
    assert "unknown subcommand" in result.stderr


def test_pdf_split_manifest_uses_common_chapter_fields(tmp_path: Path):
    chapters = [
        {
            "slot": "01",
            "title": "Chapter 1",
            "start_page": 1,
            "content": ["one two three"],
        }
    ]

    split_chapters.create_manifest(
        chapters=chapters,
        skipped=[],
        output_dir=tmp_path,
        pdf_name="book.pdf",
        method="manual",
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    chapter = manifest["chapters"][0]
    assert chapter["filename"] == "01_Chapter_1.txt"
    assert chapter["word_count"] == 3
    assert "file" not in chapter
    assert manifest["extracted_count"] == 1

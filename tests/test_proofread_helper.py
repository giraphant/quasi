from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PROOFREAD = PLUGIN_ROOT / "scripts" / "proofread" / "proofread.py"


def run_proofread(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROOFREAD), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_prepare_writes_sections_and_records_block(tmp_path: Path):
    draft = tmp_path / "draft.md"
    sections = tmp_path / ".quasi" / "proofread" / "draft" / "sections.json"
    draft.write_text(
        "# Draft\n\nIntro.\n\n## One\n\nText.\n\n### Two\n\nMore.\n",
        encoding="utf-8",
    )

    result = run_proofread("prepare", str(draft), "-o", str(sections))

    assert result.returncode == 0, result.stderr
    data = json.loads(sections.read_text(encoding="utf-8"))
    assert data["draft"] == str(draft.resolve())
    assert [section["heading"] for section in data["sections"]] == [
        "Draft",
        "One",
        "Two",
    ]
    text = draft.read_text(encoding="utf-8")
    assert "<!-- proofread:start -->" in text
    assert "<!-- proofread:end -->" in text


def test_prepare_is_idempotent_for_records_block(tmp_path: Path):
    draft = tmp_path / "draft.md"
    sections = tmp_path / "sections.json"
    draft.write_text("## One\n\nText.\n", encoding="utf-8")

    first = run_proofread("prepare", str(draft), "-o", str(sections))
    second = run_proofread("prepare", str(draft), "-o", str(sections))

    assert first.returncode == 0
    assert second.returncode == 0
    text = draft.read_text(encoding="utf-8")
    assert text.count("<!-- proofread:start -->") == 1
    assert text.count("<!-- proofread:end -->") == 1
    assert "records_block: existing" in second.stdout


def test_old_split_and_init_are_not_public_commands(tmp_path: Path):
    draft = tmp_path / "draft.md"
    draft.write_text("## One\n\nText.\n", encoding="utf-8")

    split = run_proofread("split", str(draft), "-o", str(tmp_path / "sections.json"))
    init = run_proofread("init", str(draft))

    assert split.returncode == 2
    assert init.returncode == 2

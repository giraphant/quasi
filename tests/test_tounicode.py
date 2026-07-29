"""Unit tests for the BabelDOC ToUnicode repair.

The interesting part is the guard: rebuilding a CMap from the original font is
only valid while the subset keeps original glyph numbering, so a rebuild that
contradicts what BabelDOC already wrote must abort rather than corrupt the file.
"""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from translate import tounicode  # noqa: E402


def test_self_check():
    tounicode.demo()


def test_guard_rejects_renumbered_subset():
    existing = [(0, 0xFFFF), (0x2248, 0x4E00)]
    # Same numbering: safe to extend.
    assert tounicode.disagreements(existing, {0x2248: 0x4E00, 0x264B: 0x5206}) == 0
    # Subset renumbered its glyphs — writing this map would produce new mojibake.
    assert tounicode.disagreements(existing, {0x2248: 0x5206}) == 1


def test_shared_stream_keeps_only_agreed_glyphs(monkeypatch):
    # Bold and Regular share one ToUnicode stream but not one glyph order; an entry
    # they disagree on would mis-decode whichever font did not win.
    maps = {
        Path("bold.ttf"): {1: 0x4E00, 2: 0x5206, 3: 0x5408},
        Path("regular.ttf"): {1: 0x4E00, 2: 0x540C},
    }
    monkeypatch.setattr(tounicode, "build_gid_map", lambda path, max_gid: maps[path])
    assert tounicode.agreed_map([Path("bold.ttf")]) == maps[Path("bold.ttf")]
    assert tounicode.agreed_map([Path("bold.ttf"), Path("regular.ttf")]) == {1: 0x4E00}


def test_find_font_file_matches_versioned_names(tmp_path):
    for name in ("SourceHanSerifCN-Regular.ttf", "LXGWWenKaiGB-Regular.1.520.ttf"):
        (tmp_path / name).touch()
    assert tounicode.find_font_file("/Source Han Serif CN Regular", tmp_path).name.startswith(
        "SourceHanSerifCN",
    )
    # LXGW ships with a version suffix; the PDF BaseFont carries none.
    assert tounicode.find_font_file("/LXGW WenKai GB Regular", tmp_path).name.startswith("LXGW")
    assert tounicode.find_font_file("/Nonexistent Font", tmp_path) is None

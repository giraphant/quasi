#!/usr/bin/env python3
"""Rebuild broken /ToUnicode CMaps in BabelDOC-produced bilingual PDFs.

BabelDOC subsets its CJK fonts as Identity-H CID fonts, where the CID *is* the
original font's glyph id. On runs above a handful of translated pages it emits a
ToUnicode CMap with only a couple of dozen entries instead of one per glyph, so
the pages render perfectly but copy/paste and in-PDF search return mojibake —
the reader falls back to reading the raw CID as a codepoint.

Both quasi translate backends hit this: Immersive Translate's PDF pipeline uses
the same BabelDOC font stack.

Because the subset keeps original glyph ids, the map is recoverable from the
cached original TTF: scan its cmap for glyph id -> codepoint and write the full
CMap back. Every rebuild is cross-checked against the entries BabelDOC did get
right, and a font that disagrees is left untouched rather than corrupted.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pymupdf

# BabelDOC's own font cache; both backends download into it.
FONT_DIR = Path(
    os.environ.get("QUASI_BABELDOC_FONT_DIR", Path.home() / ".cache" / "babeldoc" / "fonts"),
)

# Priority order: a glyph shared by several codepoints (一 U+4E00 and the Kangxi
# radical ⼀ U+2F00 are one glyph) must resolve to the one a reader expects.
CODEPOINT_RANGES = (
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x0020, 0x024F),  # Latin
    (0x2000, 0x206F),  # General punctuation
    (0x3000, 0x303F),  # CJK punctuation
    (0xFF00, 0xFFEF),  # Fullwidth forms
    (0xF900, 0xFAFF),  # CJK compatibility ideographs
)

_CMAP_HEAD = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
"""
_CMAP_TAIL = b"""endcmap
CMapName currentdict /CMap defineresource pop
end
end
"""


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find_font_file(base_font: str, font_dir: Path = FONT_DIR) -> Path | None:
    """Match a PDF BaseFont ("Source Han Serif CN Regular") to a cached TTF."""
    # Subset prefixes look like "ABCDEF+Name"; BabelDOC does not add one, but a
    # re-saved PDF might.
    wanted = _normalise(base_font.lstrip("/").split("+")[-1])
    if not wanted or not font_dir.is_dir():
        return None
    for path in sorted(font_dir.glob("*.[to]tf")):
        stem = _normalise(path.stem)
        # LXGW ships as "LXGWWenKaiGB-Regular.1.520.ttf" — version suffix, same font.
        if stem == wanted or stem.startswith(wanted):
            return path
    return None


def build_gid_map(font_file: Path, max_gid: int) -> dict[int, int]:
    font = pymupdf.Font(fontfile=str(font_file))
    gid_to_cp: dict[int, int] = {}
    for low, high in CODEPOINT_RANGES:
        for codepoint in range(low, high + 1):
            gid = font.has_glyph(codepoint)
            if gid and gid <= max_gid:
                gid_to_cp.setdefault(gid, codepoint)
    return gid_to_cp


def build_cmap(gid_to_cp: dict[int, int]) -> bytes:
    """Serialise a glyph-id -> codepoint map as a ToUnicode CMap stream."""
    entries = sorted(gid_to_cp.items())
    chunks = [_CMAP_HEAD]
    # bfchar blocks are capped at 100 entries by the PDF spec.
    for start in range(0, len(entries), 100):
        block = entries[start : start + 100]
        chunks.append(b"%d beginbfchar\n" % len(block))
        for gid, codepoint in block:
            # Astral codepoints would need a surrogate pair; none of our ranges reach there.
            chunks.append(b"<%04X> <%04X>\n" % (gid, codepoint))
        chunks.append(b"endbfchar\n")
    chunks.append(_CMAP_TAIL)
    return b"".join(chunks)


def _existing_entries(doc: pymupdf.Document, tounicode_xref: int) -> list[tuple[int, int]]:
    try:
        raw = doc.xref_stream(tounicode_xref).decode("latin-1")
    except Exception:
        return []
    return [
        (int(gid, 16), int(cp, 16))
        for gid, cp in re.findall(r"<([0-9a-fA-F]{4})>\s*<([0-9a-fA-F]{4})>", raw)
    ]


def disagreements(existing: list[tuple[int, int]], gid_to_cp: dict[int, int]) -> int:
    """Count entries BabelDOC wrote that our rebuild contradicts."""
    return sum(
        1
        for gid, codepoint in existing
        # gid 0 is .notdef (mapped to U+FFFF); absent gids are additions, not conflicts.
        if gid and gid in gid_to_cp and gid_to_cp[gid] != codepoint
    )


def agreed_map(font_files: list[Path]) -> dict[int, int]:
    """Glyph-id map valid for every font sharing one CMap: agreeing entries only.

    BabelDOC points Bold and Regular at a single ToUnicode stream, and their glyph
    orders are not identical, so one font's map would mis-decode the other's text.
    """
    maps = [build_gid_map(path, max_gid=0xFFFF) for path in font_files]
    first, rest = maps[0], maps[1:]
    if not rest:
        return first
    return {
        gid: codepoint
        for gid, codepoint in first.items()
        if all(other.get(gid) == codepoint for other in rest)
    }


def repair_pdf(pdf_path: Path, *, font_dir: Path = FONT_DIR) -> dict[str, int]:
    """Rewrite every recoverable ToUnicode CMap in place. Returns font -> entries."""
    doc = pymupdf.open(str(pdf_path))
    repaired: dict[str, int] = {}
    try:
        # Group first: a shared stream must satisfy every font that points at it.
        streams: dict[int, dict[str, Path]] = {}
        for xref in range(1, doc.xref_length()):
            if doc.xref_get_key(xref, "Subtype")[1] != "/Type0":
                continue
            kind, value = doc.xref_get_key(xref, "ToUnicode")
            if kind != "xref":
                continue
            base_font = doc.xref_get_key(xref, "BaseFont")[1]
            font_file = find_font_file(base_font, font_dir)
            if font_file is not None:
                streams.setdefault(int(value.split()[0]), {})[base_font.lstrip("/")] = font_file

        for tounicode_xref, fonts in streams.items():
            gid_to_cp = agreed_map(sorted(set(fonts.values())))
            existing = _existing_entries(doc, tounicode_xref)
            if disagreements(existing, gid_to_cp):
                # Subset renumbered its glyphs (ocrmypdf does this): leave it alone.
                print(
                    f"tounicode: skipping {', '.join(fonts)} — rebuild contradicts existing entries",
                    file=sys.stderr,
                )
                continue
            if len(gid_to_cp) <= len(existing):
                continue
            doc.update_stream(tounicode_xref, build_cmap(gid_to_cp))
            for name in fonts:
                repaired[name] = len(gid_to_cp)
        if repaired:
            doc.saveIncr()
    finally:
        doc.close()
    return repaired


def demo() -> None:
    """Self-check: the CMap round-trips and the guard catches bad numbering."""
    cmap = build_cmap({0x2248: 0x4E00, 0x264B: 0x5206})
    assert b"2 beginbfchar" in cmap
    assert b"<2248> <4E00>" in cmap
    assert cmap.startswith(b"/CIDInit") and cmap.rstrip().endswith(b"end")
    assert build_cmap({i: 0x4E00 + i for i in range(1, 151)}).count(b"beginbfchar") == 2

    good = [(0, 0xFFFF), (0x2248, 0x4E00), (0x264B, 0x5206)]
    assert disagreements(good, {0x2248: 0x4E00, 0x264B: 0x5206}) == 0
    assert disagreements(good, {0x2248: 0x4E8C}) == 1
    assert disagreements(good, {}) == 0  # nothing to contradict
    assert _normalise("/Source Han Serif CN Regular") == "sourcehanserifcnregular"
    print("ok")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv == ["--self-check"]:
        demo()
        raise SystemExit(0)
    if not argv:
        print("usage: tounicode.py FILE.pdf [FILE.pdf ...] | --self-check", file=sys.stderr)
        raise SystemExit(2)
    for target in argv:
        result = repair_pdf(Path(target))
        summary = ", ".join(f"{name}={count}" for name, count in result.items()) or "nothing to fix"
        print(f"{target}: {summary}")

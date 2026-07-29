from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXTRACT = PLUGIN_ROOT / "scripts" / "extract" / "extract.py"
EXTRACT_DIR = PLUGIN_ROOT / "scripts" / "extract"
sys.path.insert(0, str(EXTRACT_DIR))

import ocr_dsocr2  # noqa: E402
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
    # OCR engine switch is part of the documented surface.
    assert "--engine dsocr2|tesseract" in result.stdout


def test_ocr_help_exposes_engine_flag():
    result = run_extract("ocr", "--help")

    assert result.returncode == 0
    assert "--engine" in result.stdout
    assert "dsocr2" in result.stdout


def test_dsocr2_runner_does_not_trust_remote_code():
    """The repo's remote code imports LlamaFlashAttention2, gone from transformers.

    mlx-vlm swallows that ImportError and reports "Unrecognized processing class",
    so passing trust_remote_code sends every run silently to the tesseract fallback.
    """
    runner = (EXTRACT_DIR / "ocr_dsocr2.py").read_text()

    assert "trust_remote_code=True" not in runner
    assert "HF_HUB_TRUST_REMOTE_CODE" not in runner


def test_parse_grounding_maps_boxes_onto_the_page():
    raw = (
        "<|ref|>Culture and agency<|/ref|><|det|>[[217, 62, 395, 83]]<|/det|>\n"
        "<|ref|>now-familiar reliance<|/ref|><|det|>[[135, 91, 866, 112]]<|/det|>\n"
        "<|ref|>  <|/ref|><|det|>[[100, 100, 200, 200]]<|/det|>\n"  # blank line
        "<|ref|>flat<|/ref|><|det|>[[10, 10, 500, 10]]<|/det|>\n"  # zero-height box
        "<|ref|>truncated<|/ref|><|det|>[[10, 10]]<|/det|>\n"
    )
    lines = ocr_dsocr2.parse_grounding(raw, 432.0, 648.0)

    assert [text for text, _ in lines] == ["Culture and agency", "now-familiar reliance"]
    rect = lines[0][1]
    # 0-999 space scaled onto the page box.
    assert rect.x0 == pytest.approx(217 / 999 * 432, abs=0.1)
    assert rect.y1 == pytest.approx(83 / 999 * 648, abs=0.1)


def test_pick_font_avoids_embedding_for_latin_text():
    """PyMuPDF cannot subset without fontTools, so an embedded font costs ~16MB."""
    assert ocr_dsocr2.pick_font(["plain ascii"], "/some/Arial Unicode.ttf") == (
        "helv",
        None,
        ["plain ascii"],
    )
    assert ocr_dsocr2.pick_font(["文化与能动性"], "/some/Arial Unicode.ttf") == (
        "cjk",
        "/some/Arial Unicode.ttf",
        ["文化与能动性"],
    )
    # No Unicode font on this machine: base-14 is all there is.
    assert ocr_dsocr2.pick_font(["文化"], None)[0] == "helv"


def test_pick_font_straightens_quotes_instead_of_embedding():
    """insert_text() encodes base-14 as Latin-1 and turns anything else into `·`.

    Font.has_glyph says otherwise, so it cannot be the test — every English book
    has curly quotes, and trusting it silently corrupted the whole text layer.
    """
    name, fontfile, texts = ocr_dsocr2.pick_font(['we mean “the same” — really'], "/x.ttf")

    assert (name, fontfile) == ("helv", None)
    assert texts == ['we mean "the same" - really']
    texts[0].encode("latin-1")  # what insert_text will actually do


def test_layout_leaves_born_digital_pages_alone(tmp_path):
    """Stripping a page whose text is the only content blanks it — silently.

    --layout draws its replacement text invisibly over the scan, so on a source
    with no scan behind the text the output looks like an empty book.
    """
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "born digital body text", fontsize=11)
    page = doc[0]
    raw = "<|ref|>born digital body text<|/ref|><|det|>[[100, 100, 800, 130]]<|/det|>"

    assert ocr_dsocr2.relayer_page(page, raw, "helv", None) == -1
    assert "born digital body text" in page.get_text()
    doc.close()


def test_strip_reaches_a_text_layer_hidden_in_a_form_xobject():
    """ABBYY-style scans keep their OCR text in a Form XObject, not the page stream.

    Stripping only page.get_contents() left that layer under ours, so BabelDOC got
    two stacked text layers and silently dropped body text.
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    inner = fitz.open()
    inner.new_page().insert_text((72, 72), "old scanner text layer", fontsize=11)
    page.show_pdf_page(page.rect, inner, 0)          # lands in a Form XObject
    assert "old scanner text layer" in page.get_text()

    ocr_dsocr2.strip_text(page)

    assert "old scanner text layer" not in doc.reload_page(page).get_text()
    doc.close()
    inner.close()


def test_layout_snaps_grid_jitter_to_one_body_size():
    """Box height drives the font size, and it tracks ink, not type size.

    Identically-set body lines therefore compute sizes -9%/+4% apart, and BabelDOC
    copies the source size onto its translation: 25 distinct sizes over a 10-page
    slice whose own text layer used 2. Only something far outside that band keeps
    its own size — which real headings are not, hence SNAP's documented ceiling.
    """
    import fitz

    ruler = fitz.Font("helv")
    body = [
        ("the same body line here", fitz.Rect(72, y, 400, y + h))
        for y, h in [(100, 13.0), (120, 13.4), (140, 12.7), (160, 13.2), (180, 12.9)]
    ]
    heading = ("A Chapter Heading", fitz.Rect(72, 60, 400, 86))
    lines = [heading, *body]

    snap = ocr_dsocr2.dominant_size([lines], ruler)
    doc = fitz.open()
    page = doc.new_page()
    ocr_dsocr2.draw_layout_page(page, lines, "helv", None, snap)
    sizes = sorted(
        {
            round(span["size"], 2)
            for block in page.get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
        }
    )
    doc.close()

    assert len(sizes) == 2, sizes
    assert sizes[1] > sizes[0] * 1.5  # the heading kept its own size


def test_layout_flows_a_block_as_one_paragraph():
    """The whole point of the MinerU pass: one text object per paragraph.

    Handed a LINE box, BabelDOC must fit that line's Chinese into that line's width
    and parks the tail in the margin, so the translation arrives cut into pieces.
    A paragraph box rewraps internally instead. Without blocks it must still draw
    per-line, because that is the fallback when MinerU cannot run.
    """
    import fitz

    lines = [
        ("the same body line here", fitz.Rect(72, y, 400, y + 13.0))
        for y in (100, 116, 132, 148, 164)
    ]
    blocks = [{"c": "text", "b": [0.1, 0.11, 0.7, 0.30]}]

    def drawn(blocks):
        # a fresh doc per page: new_page() invalidates page objects already held
        doc = fitz.open()
        page = doc.new_page()
        count = ocr_dsocr2.draw_layout_page(page, lines, "helv", None, 0.0, blocks)
        out = count, page.get_text()
        doc.close()
        return out

    count, text = drawn(blocks)
    per_line, _ = drawn(None)

    assert (count, per_line) == (1, len(lines))
    # one flowed object holding the block's lines joined, not five separate strings
    assert text.split() == " ".join(t for t, _ in lines).split()


def test_layout_survives_a_block_whose_lines_come_back_out_of_order():
    """DS OCR2 returns reading order, and on a page with figures that is not top-down.

    Taking the box from lines[0]/lines[-1] built an inverted rect and PyMuPDF raised
    "text box must be finite and not empty" — a hard crash on a real book (stewart).
    """
    import fitz

    lines = [
        ("second visually but first in reading order", fitz.Rect(72, 200, 400, 213)),
        ("the line that sits higher on the page", fitz.Rect(72, 100, 400, 113)),
    ]
    page = fitz.open().new_page()

    assert ocr_dsocr2.draw_layout_page(
        page, lines, "helv", None, 0.0, [{"c": "text", "b": [0.1, 0.1, 0.7, 0.4]}]
    ) == 1


def test_layout_join_undoes_line_break_hyphens_only():
    """A hyphen at a line end is a break; one inside a word is the author's."""
    assert ocr_dsocr2.join_lines(["the rep-", "resentation"]) == "the representation"
    assert ocr_dsocr2.join_lines(["a pre-logical", "mind"]) == "a pre-logical mind"
    # suspended hyphen: ends a line, but the next word is not its other half
    assert ocr_dsocr2.join_lines(["a table-", "or room-sized"]) == "a table- or room-sized"


def test_layout_blocks_keep_geometry_before_the_flow_filter():
    """Filter order is load-bearing, and getting it wrong wrecked a real book.

    Drop non-flowable blocks first and a `list` of footnotes looks childless once
    its `ref_text` children are gone, so six numbered notes flow as one blob; and a
    body block above a figure grows through it and swallows the caption.
    """
    import fitz

    page = fitz.open().new_page(width=200, height=300)
    boxes = ocr_dsocr2.flow_boxes(page, [
        {"c": "text", "b": [0.1, 0.1, 0.9, 0.4]},
        {"c": "image", "b": [0.1, 0.5, 0.9, 0.8]},
        {"c": "list", "b": [0.1, 0.85, 0.9, 0.95]},
        {"c": "ref_text", "b": [0.12, 0.86, 0.88, 0.90]},
    ])

    # the note flows on its own; its `list` parent is dropped for holding a child,
    # so six numbered notes cannot come out as one blob
    assert len(boxes) == 2
    assert boxes[0].y1 < 0.5 * page.rect.height   # and text stopped above the image
    assert boxes[1].y0 > 0.8 * page.rect.height   # the survivor is the note, not the list


def test_ocr_rejects_unknown_engine():
    result = run_extract("ocr", "x.pdf", "y.pdf", "--engine", "nope")

    assert result.returncode == 2
    assert "unknown engine" in result.stderr


def test_ocr_engine_requires_value():
    result = run_extract("ocr", "x.pdf", "--engine")

    assert result.returncode == 2
    assert "--engine requires a value" in result.stderr


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
        },
        {
            "slot": "02",
            "title": "Chapter 2: Networks and Power",
            "start_page": 4,
            "content": ["a b"],
        },
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
    # deterministic bare slug (no ch/slot prefix); chapter-number-only title falls back to full
    assert chapter["slug"] == "chapter-1"
    # "Chapter 2:" prefix stripped, rest slugified
    assert manifest["chapters"][1]["slug"] == "networks-and-power"
    assert manifest["extracted_count"] == 2

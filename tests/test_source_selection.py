"""User-visible selection invariants for reconstructed source text layers."""
from __future__ import annotations

import json
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf as fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from translate import source_selection as selection  # noqa: E402

layout_evidence = selection.layout_evidence
ocr_mineru = selection.ocr_mineru


def test_import_works_when_extract_cli_has_already_claimed_its_top_level_name(tmp_path):
    """A full-suite import order used to make `extract` a module, not a package."""
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    code = (
        "import sys, types; "
        "sys.modules['extract'] = types.ModuleType('extract'); "
        "sys.path.insert(0, sys.argv[1]); "
        "from translate import source_selection; "
        "assert callable(source_selection.read_bound_recognition); "
        "assert sys.modules['extract'].__name__ == 'extract'"
    )
    result = subprocess.run([sys.executable, "-c", code, str(scripts)], cwd=tmp_path,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_imports_use_extract_modules_from_their_own_checkout(tmp_path):
    """Two installed quasi copies must not reuse one another's OCR module."""
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    modules = []
    for label in ("first", "second"):
        root = tmp_path / label / "scripts"
        (root / "translate").mkdir(parents=True)
        (root / "extract").mkdir()
        shutil.copy2(scripts / "translate" / "source_selection.py", root / "translate")
        for name in ("ocr_mineru.py", "ocr_quality.py", "layout_evidence.py"):
            shutil.copy2(scripts / "extract" / name, root / "extract")
        path = root / "translate" / "source_selection.py"
        spec = importlib.util.spec_from_file_location(f"selection_probe_{label}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert Path(module.ocr_mineru.__file__).resolve() == (root / "extract" / "ocr_mineru.py").resolve()
        modules.append(module)
    assert modules[0].ocr_mineru is not modules[1].ocr_mineru
    assert modules[0].layout_evidence is not modules[1].layout_evidence


def test_alignment_keeps_vlm_corrections_and_physical_line_breaks():
    """An OCR typo is not authoritative, and a real hyphen is not a line wrap."""
    source = "We use inorganic cells and 5,000 cycles in pre-existing systems."
    lines = [
        {"text": "We use inor-", "bbox": [.1, .1, .8, .15]},
        {"text": "ganic cells and 5,ooo cycles", "bbox": [.1, .16, .8, .21]},
        {"text": "in pre-existing systems.", "bbox": [.1, .22, .8, .27]},
    ]
    placed = selection.align_lines(source, lines)
    assert placed == [
        "We use inor-",
        "ganic cells and 5,000 cycles",
        "in pre-existing systems.",
    ]


@pytest.mark.parametrize("lines", [
    [],
    [{"text": "Completely different material without any matching sentence.",
      "bbox": [.1, .1, .9, .15]}],
])
def test_alignment_refuses_missing_or_unrelated_line_evidence(lines):
    with pytest.raises(selection.SelectionAlignmentError):
        selection.align_lines("A precise paragraph must not lose any of its words.", lines)


def _scan_fixture(path: Path):
    """An actual raster of text lets us test position against independently set ink."""
    width, height = 400, 300
    with fitz.open() as original:
        image_page = original.new_page(width=width, height=height)
        image_page.insert_text((40, 70), "Selection should follow the", fontname="tiro", fontsize=13)
        image_page.insert_text((40, 88), "printed text across the page.", fontname="tiro", fontsize=13)
        spans = [line["spans"][0] for block in image_page.get_text("dict")["blocks"]
                 if "lines" in block for line in block["lines"]]
        pixmap = image_page.get_pixmap(alpha=False)
        expected_word = image_page.search_for("printed")[0]
        line_rows = [
            {"text": span["text"], "bbox": [span["bbox"][0] / width, span["bbox"][1] / height,
                                             span["bbox"][2] / width, span["bbox"][3] / height]}
            for span in spans
        ]
        full = fitz.Rect(spans[0]["bbox"]) | fitz.Rect(spans[-1]["bbox"])
        block = {"type": "text", "content": "Selection should follow the printed text across the page.",
                 "bbox": [full.x0 / width, full.y0 / height, full.x1 / width, full.y1 / height], "angle": 0}
        with fitz.open() as scan:
            page = scan.new_page(width=width, height=height)
            page.insert_image(page.rect, pixmap=pixmap)
            page.insert_text((40, 70), "Stale scanner garbage", fontsize=10, render_mode=3)
            page.add_highlight_annot(fitz.Rect(40, 55, 110, 73))
            second = scan.new_page(width=width, height=height)
            second.insert_text((40, 70), "Native page stays untouched.", fontsize=13)
            scan.set_toc([[1, "Original chapter", 1], [2, "Native page", 2]])
            scan.save(path)
    return block, line_rows, expected_word


def test_selection_layer_preserves_scan_native_page_annotations_and_toc(tmp_path):
    """The positioned layer should change text, not the visible page or its neighbors."""
    source = tmp_path / "source.pdf"
    output = tmp_path / "selection.pdf"
    block, rows, expected_word = _scan_fixture(source)
    selection.build_selection_source(source, output, [[block], []], [[[rows[0], rows[1]]], []])
    with fitz.open(source) as before, fitz.open(output) as after:
        assert len(after) == 2
        assert after.get_toc() == before.get_toc()
        assert [len(list(page.annots() or [])) for page in after] == [1, 0]
        for index in range(2):
            assert after[index].get_pixmap(alpha=False).samples == before[index].get_pixmap(alpha=False).samples
        assert after[1].get_text() == before[1].get_text()
        actual = after[0].get_text()
        assert "Stale scanner garbage" not in actual
        assert " ".join(actual.split()) == block["content"]
        printed = after[0].search_for("printed")
        assert len(printed) == 1
        # Check ink-relative placement; a paragraph that reflows this word onto
        # the first line cannot pass even if its text round trip is perfect.
        assert abs(printed[0].y0 - expected_word.y0) < 4
        assert abs(printed[0].x0 - expected_word.x0) < 8


def test_selection_text_keeps_curly_quotes_and_em_dash(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "selection.pdf"
    block, rows, _ = _scan_fixture(source)
    block["content"] = "“Selection” should follow the printed text—across the page."
    rows[0]["text"] = "Selection should follow the"
    rows[1]["text"] = "printed text across the page."
    selection.build_selection_source(source, output, [[block], []], [[rows], []])
    with fitz.open(output) as doc:
        assert " ".join(doc[0].get_text().split()) == block["content"]
        assert doc[0].search_for("Selection")


def test_unordered_detector_results_are_sorted_to_the_visible_lines(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "selection.pdf"
    block, rows, expected_word = _scan_fixture(source)
    # Some real MinerU detector results arrive as lines 1, 4, 5, 2, 3.
    # Geometry, not list order, must determine physical reading order.
    selection.build_selection_source(source, output, [[block], []], [[list(reversed(rows))], []])
    with fitz.open(output) as doc:
        assert " ".join(doc[0].get_text().split()) == block["content"]
        assert abs(doc[0].search_for("printed")[0].y0 - expected_word.y0) < 4


def test_selection_rejects_incomplete_page_inventory_without_output(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "selection.pdf"
    block, rows, _ = _scan_fixture(source)
    with pytest.raises(selection.SelectionAlignmentError):
        selection.build_selection_source(source, output, [[block]], [[[rows[0], rows[1]]]])
    assert not output.exists()


def test_saved_text_loss_is_detected_and_partial_output_removed(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    output = tmp_path / "selection.pdf"
    block, rows, _ = _scan_fixture(source)
    before = source.read_bytes()
    # Simulate a writer/font failure that silently omits all placed text.
    monkeypatch.setattr(selection, "_line_object", lambda *args, **kwargs: None)
    with pytest.raises(selection.SelectionAlignmentError, match="saved selection text differs"):
        selection.build_selection_source(source, output, [[block], []], [[rows], []])
    assert source.read_bytes() == before
    assert not output.exists()


def test_lost_word_boundaries_are_detected_before_selection_is_published(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    output = tmp_path / "selection.pdf"
    block, rows, _ = _scan_fixture(source)
    original = selection._line_object

    def remove_spaces(page, texts, *args, **kwargs):
        original(page, [text.replace(" ", "") for text in texts], *args, **kwargs)

    monkeypatch.setattr(selection, "_line_object", remove_spaces)
    with pytest.raises(selection.SelectionAlignmentError, match="saved selection text differs"):
        selection.build_selection_source(source, output, [[block], []], [[rows], []])
    assert not output.exists()


def test_changed_unicode_punctuation_is_detected_before_publication(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    output = tmp_path / "selection.pdf"
    block, rows, _ = _scan_fixture(source)
    block["content"] = "“Selection” should follow the printed text across the page."
    original = selection._line_object

    def change_punctuation(page, texts, *args, **kwargs):
        altered = [text.replace("“", '"').replace("”", '"') for text in texts]
        original(page, altered, *args, **kwargs)

    monkeypatch.setattr(selection, "_line_object", change_punctuation)
    with pytest.raises(selection.SelectionAlignmentError, match="saved selection text differs"):
        selection.build_selection_source(source, output, [[block], []], [[rows], []])
    assert not output.exists()


@pytest.mark.parametrize("angle", [90, 180, 270])
def test_rotated_caption_follows_scan_ink_without_changing_image(tmp_path, angle):
    source = tmp_path / f"source-{angle}.pdf"
    output = tmp_path / f"selection-{angle}.pdf"
    width, height = 400, 300
    with fitz.open() as visible:
        page = visible.new_page(width=width, height=height)
        page.insert_text((200, 150), "Rotated caption", fontsize=13, rotate=(-angle) % 360)
        expected = page.search_for("Rotated")[0]
        span = page.get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
        box = [span["bbox"][0] / width, span["bbox"][1] / height,
               span["bbox"][2] / width, span["bbox"][3] / height]
        pixmap = page.get_pixmap(alpha=False)
        with fitz.open() as scan:
            image_page = scan.new_page(width=width, height=height)
            image_page.insert_image(image_page.rect, pixmap=pixmap)
            scan.save(source)
    block = {"type": "text", "content": "Rotated caption", "bbox": box, "angle": angle}
    row = {"text": "Rotated caption", "bbox": box}
    selection.build_selection_source(source, output, [[block]], [[[row]]])
    with fitz.open(source) as before, fitz.open(output) as after:
        assert before[0].get_pixmap(alpha=False).samples == after[0].get_pixmap(alpha=False).samples
        assert "Rotated caption" in after[0].get_text()
        found = after[0].search_for("Rotated")
        assert len(found) == 1
        assert abs(found[0].x0 - expected.x0) < 5
        assert abs(found[0].y0 - expected.y0) < 5


def test_non_right_angle_block_is_rejected_without_output(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "selection.pdf"
    block, rows, _ = _scan_fixture(source)
    block["angle"] = 45
    with pytest.raises(ValueError):
        selection.build_selection_source(source, output, [[block], []], [[rows], []])
    assert not output.exists()


def test_recognition_must_match_embedded_original_source_hash(tmp_path):
    source = tmp_path / "source.pdf"
    prepared = tmp_path / "layout.pdf"
    recognition = tmp_path / "recognition.json"
    block, _, _ = _scan_fixture(source)
    rows = [[block], []]
    ocr_mineru.write_output(source, prepared, rows, layout=True, model=ocr_mineru.MODEL)
    source_sha = layout_evidence.file_sha256(source)
    ocr_mineru.save_recognition(recognition, source_sha, rows)
    assert selection.read_bound_recognition(prepared, recognition) == rows
    payload = json.loads(recognition.read_text())
    payload["source_sha256"] = "0" * 64
    recognition.write_text(json.dumps(payload))
    with pytest.raises(selection.SelectionAlignmentError, match="recognition"):
        selection.read_bound_recognition(prepared, recognition)


def test_recognition_geometry_cannot_drift_while_text_and_hash_match(tmp_path):
    source = tmp_path / "source.pdf"
    prepared = tmp_path / "layout.pdf"
    recognition = tmp_path / "recognition.json"
    block, _, _ = _scan_fixture(source)
    rows = [[block], []]
    ocr_mineru.write_output(source, prepared, rows, layout=True, model=ocr_mineru.MODEL)
    ocr_mineru.save_recognition(recognition, layout_evidence.file_sha256(source), rows)
    payload = json.loads(recognition.read_text())
    # Preserve all text and the authentic source hash, but move the crop away
    # from the layout layer.  Text/hash-only comparison would accept it.
    payload["pages"][0][0]["bbox"] = [.6, .6, .9, .9]
    recognition.write_text(json.dumps(payload))
    with pytest.raises(selection.SelectionAlignmentError, match="geometry"):
        selection.read_bound_recognition(prepared, recognition)


@pytest.mark.parametrize(("before", "after"), [
    ("Selection", "Ｓelection"),  # NFKC maps fullwidth S to ASCII S.
    ("fix", "ﬁx"),  # NFKC expands the fi ligature.
])
def test_source_binding_does_not_accept_unicode_compatibility_substitution(tmp_path, before, after):
    source = tmp_path / "source.pdf"
    prepared = tmp_path / "layout.pdf"
    recognition = tmp_path / "recognition.json"
    block, _, _ = _scan_fixture(source)
    block["content"] = block["content"].replace("follow", "fix")
    rows = [[block], []]
    ocr_mineru.write_output(source, prepared, rows, layout=True, model=ocr_mineru.MODEL)
    ocr_mineru.save_recognition(recognition, layout_evidence.file_sha256(source), rows)
    assert selection.read_bound_recognition(prepared, recognition) == rows
    payload = json.loads(recognition.read_text())
    payload["pages"][0][0]["content"] = payload["pages"][0][0]["content"].replace(before, after)
    recognition.write_text(json.dumps(payload, ensure_ascii=False))
    with pytest.raises(selection.SelectionAlignmentError, match="recognition"):
        selection.read_bound_recognition(prepared, recognition)


def test_source_binding_rejects_changed_word_boundaries(tmp_path):
    source = tmp_path / "source.pdf"
    prepared = tmp_path / "layout.pdf"
    recognition = tmp_path / "recognition.json"
    block, _, _ = _scan_fixture(source)
    rows = [[block], []]
    ocr_mineru.write_output(source, prepared, rows, layout=True, model=ocr_mineru.MODEL)
    ocr_mineru.save_recognition(recognition, layout_evidence.file_sha256(source), rows)
    payload = json.loads(recognition.read_text())
    payload["pages"][0][0]["content"] = block["content"].replace("Selection should", "Selectionshould")
    recognition.write_text(json.dumps(payload))
    with pytest.raises(selection.SelectionAlignmentError, match="recognition"):
        selection.read_bound_recognition(prepared, recognition)


def test_embedded_review_replaces_raw_recognition_without_changing_the_sidecar(tmp_path):
    source = tmp_path / "source.pdf"
    prepared = tmp_path / "layout.pdf"
    recognition = tmp_path / "recognition.json"
    block, _, _ = _scan_fixture(source)
    rows = [[block], []]
    source_sha = layout_evidence.file_sha256(source)
    review_block = {**block, "content": block["content"].replace("Selection", "Correction")}
    review = {"source_sha256": source_sha, "pages": [{"page": 1, "reason": "verified", "blocks": [review_block]}]}
    ocr_mineru.write_output(source, prepared, rows, layout=True, model=ocr_mineru.MODEL, review=review)
    ocr_mineru.save_recognition(recognition, source_sha, rows)
    original_sidecar = recognition.read_bytes()
    resolved = selection.read_bound_recognition(prepared, recognition)
    assert resolved == [[review_block], []]
    assert recognition.read_bytes() == original_sidecar


def test_dual_source_replacement_preserves_translations_toc_and_annotations(tmp_path):
    source = tmp_path / "source.pdf"
    aligned = tmp_path / "aligned.pdf"
    dual = tmp_path / "dual.pdf"
    block, rows, expected_word = _scan_fixture(source)
    selection.build_selection_source(source, aligned, [[block], []], [[rows], []])
    with fitz.open(source) as raw, fitz.open() as doc:
        for index in range(2):
            doc.insert_pdf(raw, from_page=index, to_page=index, annots=True)
            page = doc.new_page(width=400, height=300)
            page.insert_text((40, 70), f"Translated page {index + 1}", fontsize=13)
            page.add_highlight_annot(fitz.Rect(40, 55, 110, 73))
        doc.set_toc([[1, "First chapter", 1], [2, "Second chapter", 3]])
        doc.save(dual)
    with fitz.open(dual) as doc:
        original_toc = doc.get_toc()
        original_text = [page.get_text() for page in doc]
        original_pixels = [page.get_pixmap(alpha=False).samples for page in doc]
        original_annotations = [len(list(page.annots() or [])) for page in doc]
    selection.apply_selection_source(dual, aligned)
    with fitz.open(dual) as doc:
        assert len(doc) == 4 and doc.get_toc() == original_toc
        assert [len(list(page.annots() or [])) for page in doc] == original_annotations
        for index, page in enumerate(doc):
            assert page.get_pixmap(alpha=False).samples == original_pixels[index]
            if index:
                assert page.get_text() == original_text[index]
        assert " ".join(doc[0].get_text().split()) == block["content"]
        assert abs(doc[0].search_for("printed")[0].y0 - expected_word.y0) < 4


def test_native_pdf_needs_no_ocr_recognition_or_staging(tmp_path, monkeypatch):
    source = tmp_path / "digital.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((50, 50), "Born digital text.")
        doc.save(source)
    monkeypatch.setattr(selection, "detect_lines", lambda *_: pytest.fail("no OCR for native text"))
    work = tmp_path / "selection"
    assert selection.prepare_selection(source, tmp_path / "missing-recognition.json", work) is None
    assert not work.exists()


def test_shared_scan_form_pages_are_retained_without_modifying_other_pages(tmp_path):
    """Stripping shared Form XObjects could otherwise change another page."""
    source = tmp_path / "shared.pdf"
    output = tmp_path / "selection.pdf"
    with fitz.open() as imported:
        content = imported.new_page(width=400, height=300)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 3, 3), False)
        pix.clear_with(240)
        content.insert_image(content.rect, pixmap=pix)
        content.insert_text((40, 70), "Shared old words", render_mode=3)
        with fitz.open() as doc:
            for _ in range(2):
                page = doc.new_page(width=400, height=300)
                page.show_pdf_page(page.rect, imported, 0)
            doc.save(source)
    with fitz.open(source) as doc:
        assert all(page.get_images() for page in doc)
        forms0 = {entry[0] for entry in doc[0].get_xobjects()}
        forms1 = {entry[0] for entry in doc[1].get_xobjects()}
        assert forms0 & forms1
    block = {"type": "text", "content": "Shared words", "bbox": [.1, .1, .9, .4], "angle": 0}
    row = {"text": "Shared words", "bbox": [.1, .2, .5, .25]}
    result = selection.build_selection_source(source, output, [[block], [block]], [[[row]], [[row]]])
    assert [item["page"] for item in result["skipped_pages"]] == [1, 2]
    assert all("shared" in item["reason"] for item in result["skipped_pages"])
    with fitz.open(source) as before, fitz.open(output) as after:
        for index in range(2):
            assert before[index].get_pixmap(alpha=False).samples == after[index].get_pixmap(alpha=False).samples
            assert before[index].get_text() == after[index].get_text()


def test_complex_block_falls_back_without_changing_other_content(tmp_path):
    source, aligned, dual = (tmp_path / name for name in ("source.pdf", "aligned.pdf", "dual.pdf"))
    with fitz.open() as visible:
        page = visible.new_page(width=400, height=300)
        lines = [("Complex paragraph follows", 60), ("with all words retained.", 78),
                 ("Second paragraph is", 150), ("correctly aligned.", 168)]
        for text, y in lines:
            page.insert_text((40, y), text, fontsize=12)
        spans = [line["spans"][0] for block in page.get_text("dict")["blocks"]
                 if "lines" in block for line in block["lines"]]
        pix = page.get_pixmap(alpha=False)
        with fitz.open() as scan:
            page = scan.new_page(width=400, height=300)
            page.insert_image(page.rect, pixmap=pix)
            page.add_text_annot((20, 20), "keep annotation")
            page = scan.new_page(width=400, height=300)
            page.insert_text((20, 50), "Existing native text.")
            scan.set_toc([[1, "Contents", 1]])
            scan.save(source)
    def box(rect):
        return [rect[0] / 400, rect[1] / 300, rect[2] / 400, rect[3] / 300]
    raw_blocks, all_rows = [], []
    for first in (0, 2):
        pair = spans[first:first + 2]
        rect = fitz.Rect(pair[0]["bbox"]) | fitz.Rect(pair[1]["bbox"])
        raw_blocks.append({"type": "text", "content": " ".join(s["text"] for s in pair),
                           "bbox": box(rect), "angle": 0})
        all_rows.append([{"text": s["text"], "bbox": box(s["bbox"])} for s in pair])
    all_rows[0] = [{"error": "native OCR block failed: synthetic"}]
    result = selection.build_selection_source(source, aligned, [raw_blocks, []], [all_rows, []])
    assert len(result["fallback_blocks"]) == 1
    assert result["fallback_blocks"][0]["page"] == result["fallback_blocks"][0]["block"] == 1
    assert "native OCR block failed" in result["fallback_blocks"][0]["reason"]
    stats = result["page_stats"][0]
    assert (stats["page"], stats["blocks"], stats["aligned"], stats["fallback"]) == (1, 2, 1, 1)
    with fitz.open(source) as before, fitz.open(aligned) as after:
        assert before[0].get_pixmap(alpha=False).samples == after[0].get_pixmap(alpha=False).samples
        assert before[1].get_text() == after[1].get_text()
        assert before.get_toc() == after.get_toc()
        assert len(list(after[0].annots())) == 1
        assert " ".join(after[0].get_text().split()) == " ".join(b["content"] for b in raw_blocks)
        expected_y = spans[2]["bbox"][1]
        assert abs(after[0].search_for("Second")[0].y0 - expected_y) < 4
    with fitz.open(source) as raw, fitz.open() as doc:
        for index in range(2):
            doc.insert_pdf(raw, from_page=index, to_page=index, annots=True)
            page = doc.new_page(width=400, height=300)
            page.insert_text((20, 50), f"Translated page {index + 1}")
        doc.save(dual)
    with fitz.open(dual) as before:
        translated = [before[i].get_text() for i in (1, 3)]
    selection.apply_selection_source(dual, aligned)
    with fitz.open(dual) as doc:
        assert [doc[i].get_text() for i in (1, 3)] == translated
        assert " ".join(doc[0].get_text().split()) == " ".join(b["content"] for b in raw_blocks)
        kind, evidence = doc.xref_get_key(doc.pdf_catalog(), "QuasiSelection")
        assert kind == "string"
        assert json.loads(evidence)["fallback_blocks"] == result["fallback_blocks"]
        assert json.loads(evidence)["page_stats"][0]["applied"] is True


def test_changed_provider_page_is_retained_and_reported(tmp_path):
    source, aligned, dual = (tmp_path / name for name in ("source.pdf", "aligned.pdf", "dual.pdf"))
    block, rows, _ = _scan_fixture(source)
    selection.build_selection_source(source, aligned, [[block], []], [[rows], []])
    with fitz.open(source) as raw, fitz.open() as doc:
        for index in range(2):
            doc.insert_pdf(raw, from_page=index, to_page=index)
            doc.new_page(width=400, height=300)
        doc[0].insert_text((40, 120), "Changed pixels", fontsize=13)
        doc.save(dual)
    with fitz.open(dual) as doc:
        pixels = [page.get_pixmap(alpha=False).samples for page in doc]
        text = [page.get_text() for page in doc]
    selection.apply_selection_source(dual, aligned)
    with fitz.open(dual) as doc:
        assert [page.get_pixmap(alpha=False).samples for page in doc] == pixels
        assert [page.get_text() for page in doc] == text
        _, evidence = doc.xref_get_key(doc.pdf_catalog(), "QuasiSelection")
        skipped = json.loads(evidence)["skipped_pages"]
        assert len(skipped) == 1 and skipped[0]["page"] == 1 and skipped[0]["reason"]
        assert json.loads(evidence)["page_stats"][0]["applied"] is False


def test_rotated_scan_page_is_retained_with_source_bound_recognition(tmp_path):
    original, layout, rotated, recognition, aligned = (tmp_path / name for name in
        ("original.pdf", "layout.pdf", "rotated.pdf", "recognition.json", "aligned.pdf"))
    block, _, _ = _scan_fixture(original)
    rows = [[block], []]
    ocr_mineru.write_output(original, layout, rows, layout=True, model=ocr_mineru.MODEL)
    ocr_mineru.save_recognition(recognition, layout_evidence.file_sha256(original), rows)
    with fitz.open(layout) as doc:
        doc[0].set_rotation(90)
        doc.save(rotated)
    bound = selection.read_bound_recognition(rotated, recognition)
    assert bound == rows
    result = selection.build_selection_source(rotated, aligned, bound, [None, []])
    assert result["skipped_pages"][0]["page"] == 1
    assert "rotated" in result["skipped_pages"][0]["reason"]
    with fitz.open(rotated) as before, fitz.open(aligned) as after:
        assert after[0].rotation == before[0].rotation == 90
        assert after[0].get_pixmap(alpha=False).samples == before[0].get_pixmap(alpha=False).samples
        assert after[0].get_text() == before[0].get_text()
    payload = json.loads(recognition.read_text())
    payload["source_sha256"] = "0" * 64
    recognition.write_text(json.dumps(payload))
    with pytest.raises(selection.SelectionAlignmentError, match="recognition"):
        selection.read_bound_recognition(rotated, recognition)


def test_page_graft_exception_retains_provider_page_and_reports_it(tmp_path, monkeypatch):
    source, aligned, dual = (tmp_path / name for name in ("source.pdf", "aligned.pdf", "dual.pdf"))
    block, rows, _ = _scan_fixture(source)
    selection.build_selection_source(source, aligned, [[block], []], [[rows], []])
    with fitz.open(source) as raw, fitz.open() as doc:
        for index in range(2):
            doc.insert_pdf(raw, from_page=index, to_page=index)
            doc.new_page(width=400, height=300)
        doc.save(dual)
    with fitz.open(dual) as doc:
        pixels = [page.get_pixmap(alpha=False).samples for page in doc]
        texts = [page.get_text() for page in doc]
    def fail_trial(*_args, **_kwargs):
        raise RuntimeError("synthetic graft failure")
    monkeypatch.setattr(fitz.Document, "insert_pdf", fail_trial)
    selection.apply_selection_source(dual, aligned)
    with fitz.open(dual) as doc:
        assert [page.get_pixmap(alpha=False).samples for page in doc] == pixels
        assert [page.get_text() for page in doc] == texts
        _, evidence = doc.xref_get_key(doc.pdf_catalog(), "QuasiSelection")
        skipped = json.loads(evidence)["skipped_pages"]
        assert len(skipped) == 1 and skipped[0]["page"] == 1
        assert "synthetic graft failure" in skipped[0]["reason"]


def test_missing_roundtrip_font_retains_source_page_and_reports_it(tmp_path, monkeypatch):
    source, output = tmp_path / "source.pdf", tmp_path / "selection.pdf"
    block, rows, _ = _scan_fixture(source)
    def no_font(_texts):
        raise selection.SelectionAlignmentError("no roundtrip font")
    monkeypatch.setattr(selection, "_selection_font", no_font)
    result = selection.build_selection_source(source, output, [[block], []], [[rows], []])
    assert result["skipped_pages"][0]["page"] == 1
    assert "no roundtrip font" in result["skipped_pages"][0]["reason"]
    with fitz.open(source) as before, fitz.open(output) as after:
        assert before[0].get_pixmap(alpha=False).samples == after[0].get_pixmap(alpha=False).samples
        assert before[0].get_text() == after[0].get_text()
        assert before[1].get_text() == after[1].get_text()

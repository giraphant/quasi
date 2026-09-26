"""MinerU block recognition, layout and disagreement evidence; no model calls."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pymupdf as fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "extract"))
import layout_evidence
import ocr_mineru as engine
import ocr_quality


def block(text="A complete paragraph with its original words.", kind="text", bbox=None, angle=0):
    return {"type": kind, "content": text, "bbox": bbox or [.1, .1, .9, .4], "angle": angle}


def source_pdf(path, *, digital=False):
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=600)
        if not digital:
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 3, 3), False)
            pix.clear_with(240)
            page.insert_image(page.rect, pixmap=pix)
        page.insert_textbox(fitz.Rect(40, 40, 360, 550), "Existing scanner words and old text. " * 20,
                            fontsize=10, render_mode=3 if not digital else 0)
        doc.save(path)
    return path


def test_fixed_dependencies_and_one_two_step_client(monkeypatch, tmp_path):
    requirements = engine._MINERU_CMD
    assert "mlx-vlm==0.7.3" in requirements
    assert "mlx==0.32.2" in requirements and "mineru-vl-utils==2.0.5" in requirements
    # Execute the real subprocess wrapper with a fake client: one load, N pages,
    # object/dict rows, and propagated inference exceptions rather than [] pages.
    from types import SimpleNamespace
    calls = []
    class Client:
        def __init__(self, **kwargs): calls.append("load")
        def two_step_extract(self, image):
            calls.append("page")
            return [SimpleNamespace(**block()), block("Another paragraph")]
    class FakeImage:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=SimpleNamespace(open=lambda _: FakeImage())))
    png = tmp_path / "p.png"
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), False)
    pix.clear_with(255); pix.save(png)
    listing, result = tmp_path / "pages.json", tmp_path / "results.json"
    listing.write_text(json.dumps([str(png)] * 2))
    monkeypatch.setitem(sys.modules, "mineru_vl_utils", SimpleNamespace(MinerUClient=Client))
    for key, value in {"MINERU_MODEL": "test", "MINERU_PNG_LIST": str(listing), "MINERU_RESULTS": str(result)}.items():
        monkeypatch.setenv(key, value)
    exec(compile(engine._RUNNER, "mineru-runner", "exec"), {})
    assert calls == ["load", "page", "page"]
    assert len(json.loads(result.read_text())) == 2
    def fail(*args): raise RuntimeError("inference died")
    monkeypatch.setattr(Client, "two_step_extract", fail)
    with pytest.raises(RuntimeError, match="inference died"):
        exec(compile(engine._RUNNER, "mineru-runner", "exec"), {})


@pytest.mark.parametrize(("raw", "expected"), [
    (r"A \( ^{7} \) note <sup>①</sup>", "A 7 note ①"),
    (r"The bound is \(\infty\), with \(\sigma\).", "The bound is ∞, with σ."),
    (r"R&D rose 20% to \$20.5 billion", "R&D rose 20% to $20.5 billion"),
    ("a pre-logical mind", "a pre-logical mind"),
    (r"\[x+y \tag {3}\]", "x+y (3)"),
])
def test_markup_becomes_plain_text_without_damaging_prose(raw, expected):
    assert engine.clean(raw) == expected


def test_unknown_markup_or_block_never_silently_discards_text():
    with pytest.raises(ValueError, match="unsupported"):
        engine.clean(r"\(\unknownsecret{meaning}\)")
    for invalid in [block(kind="unrecognized"), block(bbox=[0, 0, float("nan"), 1]), block(text=""), block(angle=45)]:
        with pytest.raises(ValueError): engine.normalize_blocks([invalid])


def test_unicode_font_absence_fails_instead_of_losing_chinese(monkeypatch):
    monkeypatch.setattr(engine, "_FONT_FILES", [])
    with pytest.raises(ValueError, match="Unicode font"):
        engine.pick_font(["文化"])


def test_layout_preserves_images_uses_one_box_and_keeps_footnotes(tmp_path):
    source = source_pdf(tmp_path / "source.pdf")
    out = tmp_path / "layout.pdf"
    rows = [block("Body words " * 30), block("1. First note", "ref_text", [.1,.6,.9,.66]),
            block("2. Second note", "page_footnote", [.1,.7,.9,.76]),
            block("3. Table note", "table_footnote", [.1,.8,.9,.86]),
            block("", "list", [.08,.59,.92,.9]), block("<table><tr><td>Table cell</td></tr></table>", "table", [.1,.42,.9,.55])]
    engine.write_output(source, out, [rows], layout=True, model=engine.MODEL)
    with fitz.open(source) as src, fitz.open(out) as doc:
        text = doc[0].get_text()
        assert "Existing scanner" not in text and "Table cell" not in text
        assert all(part in text for part in ["First note", "Second note", "Table note"])
        assert " ".join(text.split()).count("Body words") == 30
        assert src.xref_stream(src[0].get_images()[0][0]) == doc.xref_stream(doc[0].get_images()[0][0])
        # Every placed paragraph is one BT/ET object drawn after the image.
        streams = [doc.xref_stream(x) for x in doc[0].get_contents()]
        assert sum(len(re.findall(rb"\bBT\b", data)) for data in streams) == 4
        assert all(trace['type'] == 3 for trace in doc[0].get_texttrace())
        assert ocr_quality.read(doc)["quality"]["reference_blocks"] == 3
    assert layout_evidence.inspect(out, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())["prepared"]


def test_text_output_keeps_table_formula_and_notes_but_drops_running_heads(tmp_path):
    source = source_pdf(tmp_path / "source.pdf")
    out = tmp_path / "text.pdf"
    rows = [block("Running head", "header"), block("body sentence"),
            block("<table><tr><td>A</td><td>42</td></tr></table>", "table"),
            block(r"\[x + y = 3\]", "equation"), block("1. A separate note", "ref_text")]
    engine.write_output(source, out, [rows], layout=False, model=engine.MODEL)
    with fitz.open(out) as doc:
        text = doc[0].get_text()
        assert "Running head" not in text
        assert "A | 42" in text and "x + y = 3" in text and "A separate note" in text
        assert "<table>" not in text and "\\[" not in text


def test_layout_digital_pages_are_unchanged_without_inference(tmp_path, monkeypatch):
    source = source_pdf(tmp_path / "digital.pdf", digital=True)
    out = tmp_path / "out.pdf"
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: pytest.fail("digital must not call model"))
    monkeypatch.setattr(sys, "argv", ["ocr_mineru.py", str(source), str(out), "--layout"])
    assert engine.main() == 0
    with fitz.open(source) as src, fitz.open(out) as doc:
        assert src[0].get_text() == doc[0].get_text()
        assert src[0].get_pixmap().samples == doc[0].get_pixmap().samples


@pytest.mark.parametrize("rows", [[], [block("", "image")], [block(text="")]])
def test_layout_empty_or_nontext_model_results_cannot_claim_success(tmp_path, rows):
    source = source_pdf(tmp_path / "source.pdf")
    output = tmp_path / "out.pdf"
    with pytest.raises(ValueError):
        engine.write_output(source, output, [rows], layout=True, model=engine.MODEL)
    assert not output.exists()


def test_main_uses_one_model_process_and_rejects_partial_page_list(tmp_path, monkeypatch):
    source = source_pdf(tmp_path / "source.pdf")
    out = tmp_path / "out.pdf"
    calls = []
    def run(command, *, env, **kwargs):
        calls.append(command)
        Path(env["MINERU_RESULTS"]).write_text("[]")
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(engine.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(engine.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(engine.shutil, "which", lambda _: "/test/uvx")
    monkeypatch.setattr(engine.subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", ["ocr_mineru.py", str(source), str(out), "--layout"])
    assert engine.main() != 0 and len(calls) == 1 and not out.exists()


def test_agreement_is_a_warning_not_automatic_old_text_substitution(tmp_path):
    source = source_pdf(tmp_path / "source.pdf")
    out = tmp_path / "out.pdf"
    text = "A wholly different paragraph introduces many novel phrases absent from the previous scanner result."
    quality = engine.write_output(source, out, [[block(text)]], layout=True, model=engine.MODEL)
    assert quality["checked_blocks"] == 1 and len(quality["suspects"]) == 1
    assert quality["suspects"][0]["new_excerpt"] == text
    with fitz.open(out) as doc: assert "novel phrases" in doc[0].get_text()


def test_absent_baseline_is_recorded_and_reference_blocks_are_exempt(tmp_path):
    with fitz.open() as doc:
        page = doc.new_page()
        quality = ocr_quality.empty_quality()
        ocr_quality.check_page(page, [block()], 1, quality)
        assert quality["unavailable_pages"] == [1] and quality["checked_blocks"] == 0
        page.insert_textbox(page.rect, "Existing scanner text " * 30, fontsize=9)
        ocr_quality.check_page(page, [block(kind="ref_text"), block(kind="page_footnote")], 2, quality)
        assert quality["reference_blocks"] == 2 and not quality["suspects"]


def test_quality_evidence_rejects_text_changes_and_wrong_layout_profile(tmp_path):
    source = source_pdf(tmp_path / "source.pdf")
    out = tmp_path / "out.pdf"
    engine.write_output(source, out, [[block()]], layout=True, model=engine.MODEL)
    with fitz.open(out) as doc:
        kind, raw = doc.xref_get_key(doc.pdf_catalog(), layout_evidence.KEY)
        evidence = json.loads(raw); evidence["profile"] = "old-engine"
        doc.xref_set_key(doc.pdf_catalog(), layout_evidence.KEY, fitz.get_pdf_str(json.dumps(evidence)))
        doc[0].insert_text((20, 580), "tampered")
        doc.saveIncr()
    assert not layout_evidence.inspect(out)["prepared"]
    assert ocr_quality.inspect(out) is None


def test_quality_merge_offsets_pages_and_keeps_reference_exemptions():
    part = ocr_quality.empty_quality()
    part.update(checked_blocks=1, reference_blocks=3, unavailable_pages=[2], suspects=[{
        'page':1,'block':2,'type':'text','bbox':[.1,.1,.9,.9],'agreement':.6,
        'new_excerpt':'new','old_excerpt':'old'}])
    combined = ocr_quality.combine([(0,part),(16,part)])
    assert combined['unavailable_pages'] == [2,18]
    assert [row['page'] for row in combined['suspects']] == [1,17]
    assert combined['reference_blocks'] == 6
    assert ocr_quality.valid_quality(combined,18)


@pytest.mark.parametrize('angle', [90,180,270])
def test_rotated_paragraph_is_complete_and_inside_its_box(tmp_path, angle):
    source = source_pdf(tmp_path/'source.pdf');output=tmp_path/'rotated.pdf'
    text='Rotated text retains every word.'
    row=block(text,bbox=[.2,.2,.8,.8],angle=angle)
    engine.write_output(source,output,[[row]],layout=True,model=engine.MODEL)
    with fitz.open(output) as doc:
        rect=engine.rectangle(doc[0],row)
        assert ' '.join(doc[0].get_text(clip=rect).split()) == text
        # get_text('words') expands to font ascender/descender metrics;
        # texttrace reports the actual drawn spans.
        bounds = rect + (-.001, -.001, .001, .001)  # PDF float rounding
        assert all(bounds.contains(fitz.Rect(span['bbox'])) for span in doc[0].get_texttrace())


def test_empty_blank_page_with_short_old_noise_is_reported(tmp_path):
    source=source_pdf(tmp_path/'source.pdf')
    with fitz.open(source) as doc:
        # A blank scan can carry old OCR noise, as Barnes physical page 176 did.
        page=doc.new_page(width=400,height=600)
        pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,3,3),False);pix.clear_with(255)
        page.insert_image(page.rect,pixmap=pix)
        page.insert_text((40,40),'On fa a i ae 7 = --',render_mode=3)
        doc.saveIncr()
    output=tmp_path/'layout.pdf'
    quality=engine.write_output(source,output,[[block('Body words '*30)],[]],layout=True,model=engine.MODEL)
    assert quality['empty_pages'] == [2] and quality['unavailable_pages'] == [2]
    with fitz.open(source) as src,fitz.open(output) as doc:
        assert len(doc)==2 and doc[1].get_text()==''
        assert doc[1].get_pixmap().samples==src[1].get_pixmap().samples


def test_bare_latex_fraction_keeps_both_arguments():
    assert engine.clean(r'Use \frac{1}{2} of 20% of $40.') == 'Use 1/2 of 20% of $40.'


def test_agreement_normalizes_compound_and_linebreak_hyphens_without_changing_text():
    assert ocr_quality.words('a shall-implication is pre-logical') == ocr_quality.words('a shall-\nimplication is pre-\nlogical')
    assert engine.clean('a shall-implication') == 'a shall-implication'


def test_dense_reference_exemption_requires_source_and_model_heading_agreement():
    citations='Bell, collected works, 458-471. Steinbuch, selected papers, 300-303. Müller, medical history, 1318-1323. Bidder, physiological essays, 1-11.'
    with fitz.open() as doc:
        page=doc.new_page()
        page.insert_text((30,30),'NOTES')
        page.insert_textbox(fitz.Rect(30,100,550,700),'Old source words for the baseline. '*40)
        rows=[block('NOTES','header',[.1,.01,.3,.04]),block(citations)]
        quality=ocr_quality.empty_quality();ocr_quality.check_page(page,rows,1,quality)
        assert quality['reference_blocks']==1 and quality['suspects']==[]
        rows[0]['content']='Notes on Method'
        quality=ocr_quality.empty_quality();ocr_quality.check_page(page,rows,1,quality)
        assert quality['reference_blocks']==0 and len(quality['suspects'])==1


def test_font_selection_checks_all_glyphs_and_uses_complete_fallback(tmp_path, monkeypatch):
    from types import SimpleNamespace
    limited=tmp_path/'limited.ttf';complete=tmp_path/'complete.ttf'
    limited.touch();complete.touch()
    monkeypatch.setattr(engine,'_FONT_FILES',[str(limited),str(complete)])
    monkeypatch.setattr(engine,'_font_roundtrips',lambda *_:True)
    monkeypatch.setattr(engine,'_unicode_font',lambda path:SimpleNamespace(has_glyph=lambda code: path==str(complete) or code!=ord('ș')))
    name,file,text=engine.pick_font(['Ceaușescu'])
    assert file==str(complete) and text==['Ceaușescu'] and name.startswith('quasiunicode')
    with pytest.raises(ValueError,match='covering every'):
        engine.pick_font(['Ceaușescu'],str(limited))


def test_font_rejects_alias_mapping_even_with_available_glyphs(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path=tmp_path/'aliases.ttf';path.touch()
    monkeypatch.setattr(engine,'_unicode_font',lambda _:SimpleNamespace(has_glyph=lambda _:True))
    monkeypatch.setattr(engine,'_font_roundtrips',lambda *_:False)
    with pytest.raises(ValueError,match='faithful text extraction'):
        engine.pick_font(['Ceaușescu; a-name'],str(path))

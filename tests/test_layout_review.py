"""Reviewed OCR corrections resume real layout without another model invocation."""
import copy
import json
import os

import pytest

from test_ocr_mineru import engine, block, source_pdf
from test_extract_cli import run_extract


def fixture(tmp_path):
    page = source_pdf(tmp_path / "one.pdf")
    source = tmp_path / "source.pdf"
    with engine.fitz.open(page) as one, engine.fitz.open() as doc:
        doc.insert_pdf(one)
        doc.insert_pdf(one)
        doc.save(source)
    raw, review, output = [tmp_path / name for name in ("raw.json", "review.json", "layout.pdf")]
    source_sha = engine.layout_evidence.file_sha256(source)
    rows = [[block("invented " * 1000, bbox=[.1, .1, .12, .12])],
            [block("numbers " * 1000, "header", [.2, .02, .8, .04]),
             block("Keep all the real body words from this paragraph.", bbox=[.1, .2, .9, .5])]]
    engine.save_recognition(raw, source_sha, rows)
    corrected = copy.deepcopy(rows[1])
    corrected[0]["content"] = "CHAPTER HEADING"
    review.write_text(json.dumps({"source_sha256": source_sha, "pages": [
        {"page": 1, "reason": "Visible blank scan; old and new OCR are noise.", "blocks": []},
        {"page": 2, "reason": "Read the actual heading; retain the complete body.", "blocks": corrected},
    ]}))
    return source, raw, review, output


def command(source, raw, output, review=None):
    args = ["ocr", str(source), str(output), "--layout", "--recognition-json", str(raw),
            "--no-clobber", "--json"]
    if review is not None:
        args.extend(["--review-json", str(review)])
    # uvx is deliberately unavailable. Only saved recognition can advance.
    return run_extract(*args, env=dict(os.environ, PATH=""))


def test_review_resumes_failed_layout_preserves_raw_images_and_unedited_body(tmp_path):
    source, raw, review, output = fixture(tmp_path)
    saved = {p: p.read_bytes() for p in (source, raw, review)}
    failed = command(source, raw, output)
    assert failed.returncode == 3 and not output.exists()
    assert "page 1, block 1" in failed.stderr
    assert "page 2, block 1" in failed.stderr
    recovered = command(source, raw, output, review)
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout)["status"] == "ok"
    assert "reusing recognition" in recovered.stderr
    for path, original in saved.items():
        assert path.read_bytes() == original
    with engine.fitz.open(source) as src, engine.fitz.open(output) as doc:
        assert len(doc) == 2
        assert all(a.get_pixmap().samples == b.get_pixmap().samples for a, b in zip(src, doc))
        assert not doc[0].get_text().strip()
        assert " ".join(doc[1].get_text().split()) == (
            "CHAPTER HEADING Keep all the real body words from this paragraph.")
        evidence = json.loads(doc.xref_get_key(doc.pdf_catalog(), "QuasiLayout")[1])
        assert evidence["review"] == json.loads(saved[review])
        assert engine.ocr_quality.read(doc)["quality"]["empty_pages"] == [1]
    assert engine.layout_evidence.inspect(output)["prepared"]
    assert json.loads(command(source, raw, output, review).stdout)["status"] == "existing"
    prior = output.read_bytes()
    changed = json.loads(review.read_text())
    changed["pages"][1]["blocks"][0]["content"] = "A DIFFERENT HEADING"
    review.write_text(json.dumps(changed))
    mismatch = command(source, raw, output, review)
    assert mismatch.returncode != 0 and output.read_bytes() == prior


@pytest.mark.parametrize("case", ["wrong-source", "outside-page", "missing-raw", "native-page", "unplaceable-review"])
def test_invalid_review_never_reinfers_or_publishes(tmp_path, case):
    source, raw, review, output = fixture(tmp_path)
    record = json.loads(review.read_text())
    if case == "wrong-source":
        record["source_sha256"] = "0" * 64
    elif case == "outside-page":
        record["pages"][0]["page"] = 3
    elif case == "missing-raw":
        raw.unlink()
    elif case == "unplaceable-review":
        record["pages"][1]["blocks"][1]["bbox"] = [.1, .2, .101, .201]
    else:
        source = source_pdf(tmp_path / "native.pdf", digital=True)
        record["source_sha256"] = engine.layout_evidence.file_sha256(source)
        record["pages"] = record["pages"][:1]
    review.write_text(json.dumps(record))
    before = review.read_bytes()
    result = command(source, raw, output, review)
    assert result.returncode != 0 and not output.exists()
    assert "two_step_extract" not in result.stderr
    assert review.read_bytes() == before
    if case == "missing-raw":
        assert "no new inference started" in result.stderr and not raw.exists()
    if case == "unplaceable-review":
        assert "page 2, block 2" in result.stderr and "cannot fit" in result.stderr

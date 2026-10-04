"""Recovery reuses existing evidence without starting a second expensive writer."""
import json
import sys
from pathlib import Path

import pytest

from test_ocr_mineru import engine, block, source_pdf
from test_translate_cli import commit, source_fixture, run_kwargs, observe_kwargs, passing_runner


def test_layout_failure_retains_raw_recognition_for_placement_only_retry(tmp_path, monkeypatch):
    source = source_pdf(tmp_path / "source.pdf")
    output, recognition = tmp_path / "output.pdf", tmp_path / "recognition.json"
    calls = []
    rows = [[block("Preserved unfamiliar paragraph", "future_text")]]
    monkeypatch.setattr(engine, "recognize", lambda *a, **k: calls.append("inference") or rows)
    monkeypatch.setattr(sys, "argv", ["ocr_mineru.py", str(source), str(output), "--layout",
                                     "--recognition-json", str(recognition)])
    place = engine.write_output
    def fail(*args, **kwargs):
        raise ValueError("placement failed")
    monkeypatch.setattr(engine, "write_output", fail)
    assert engine.main() == 3
    saved = recognition.read_bytes()
    assert json.loads(saved)["pages"] == rows
    assert not output.exists()
    monkeypatch.setattr(engine, "write_output", place)
    assert engine.main() == 0
    assert calls == ["inference"]
    assert recognition.read_bytes() == saved
    assert engine.layout_evidence.inspect(output)["prepared"]


def test_recognition_from_changed_source_is_preserved_but_not_reused(tmp_path, monkeypatch):
    source = source_pdf(tmp_path / "source.pdf")
    output, recognition = tmp_path / "output.pdf", tmp_path / "recognition.json"
    engine.save_recognition(recognition, "0" * 64, [[block()]])
    saved = recognition.read_bytes()
    monkeypatch.setattr(engine, "recognize", lambda *a, **k: pytest.fail("must not overwrite another source's evidence"))
    monkeypatch.setattr(sys, "argv", ["ocr_mineru.py", str(source), str(output), "--layout",
                                     "--recognition-json", str(recognition)])
    assert engine.main() == 3
    assert not output.exists() and recognition.read_bytes() == saved


def test_placement_failure_identifies_exact_page_block_and_geometry(tmp_path):
    source = source_pdf(tmp_path / "source.pdf")
    output = tmp_path / "output.pdf"
    rows = [[block("First paragraph"), block("Too much text " * 100, "future_note", [.1,.6,.101,.601])]]
    with pytest.raises(ValueError, match=r"page 1, block 2 \(future_note\).*bbox=.*chars=.*cannot fit"):
        engine.write_output(source, output, rows, layout=True, model=engine.MODEL)
    assert not output.exists()


def test_observe_tracks_existing_lock_then_committed_output_without_stdout(tmp_path):
    source, source_sha = source_fixture(tmp_path)
    paths = commit.output_paths(project_root=tmp_path, slug="strict-translation", target_language="zh")
    # Absence of a lock remains a pure read; observe must not create one.
    assert commit.observe(**observe_kwargs(tmp_path, source=source, mode="final"))["signal"] == "missing"
    assert not paths["lock_path"].exists()
    with commit.output_lock(paths):
        pending = commit.observe(**observe_kwargs(tmp_path, source=source, mode="final"))
        assert pending["signal"] == "running" and pending["effect"] == "readonly"
        assert pending["output_sha256"] is None
        # Publication puts the PDF in place before its manifest. That window is
        # still an active writer, not an unproven-output terminal or completion.
        paths["output_path"].write_bytes(source.read_bytes())
        pending = commit.observe(**observe_kwargs(tmp_path, source=source, mode="final"))
        assert pending["signal"] == "running" and pending["coverage"] is None
        assert pending["output_sha256"] is None
        paths["output_path"].unlink()
    # A stale filename cannot keep an exited job looking alive.
    paths["lock_path"].touch()
    assert commit.observe(**observe_kwargs(tmp_path, source=source, mode="final"))["signal"] == "missing"
    calls = []
    committed = commit.run_transaction(**run_kwargs(tmp_path, source, source_sha, passing_runner(calls)))
    assert committed["status"] == "succeeded"
    # The external stdout receipt and stderr log need not exist or be readable.
    final = commit.observe(**observe_kwargs(tmp_path, source=source, mode="final"))
    assert final["signal"] == "reused" and final["failure"] is None
    assert final["output_sha256"] == committed["output_sha256"]
    assert len(calls) == 1

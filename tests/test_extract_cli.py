from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXTRACT = PLUGIN_ROOT / "scripts" / "extract" / "extract.py"
EXTRACT_DIR = PLUGIN_ROOT / "scripts" / "extract"
sys.path.insert(0, str(EXTRACT_DIR))

import ocr_dsocr2  # noqa: E402
import split_chapters  # noqa: E402
import extract as extract_cli  # noqa: E402
import chapter_commit  # noqa: E402


def run_extract(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EXTRACT), *args],
        cwd=PLUGIN_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        env=env,
    )


def test_extract_help_exposes_agent_contract():
    result = run_extract("--help")

    assert result.returncode == 0
    assert "quasi-extract epub" in result.stdout
    assert "quasi-extract text" in result.stdout
    assert "quasi-extract ocr" in result.stdout
    assert "quasi-extract split" in result.stdout
    # OCR engine switch is part of the documented surface.
    assert "--engine dsocr2|tesseract" in result.stdout


def test_ocr_help_exposes_engine_flag():
    result = run_extract("ocr", "--help")

    assert result.returncode == 0
    assert "--engine" in result.stdout
    assert "dsocr2" in result.stdout
    assert "--no-clobber" in result.stdout
    assert "--json" in result.stdout


def test_ocr_json_is_single_object_and_routes_progress_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    source = str(tmp_path / "paper.pdf")
    output = str(tmp_path / "caller-output.pdf")

    def fake_call(command, **kwargs):
        assert kwargs["stdout"] is sys.stderr
        assert kwargs["stderr"] is sys.stderr
        print("engine progress", file=kwargs["stdout"])
        Path(output).write_bytes(b"%PDF-complete")
        return 0

    monkeypatch.setattr(extract_cli.subprocess, "call", fake_call)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR, [source, output, "--engine", "tesseract", "--json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.out.count("\n") == 1
    assert "engine progress" not in captured.out
    assert "engine progress" in captured.err
    assert rc == 0
    assert payload == {
        "status": "ok",
        "input": source,
        "output": output,
        "exit": 0,
        "exists": True,
        "size": len(b"%PDF-complete"),
        "failure": None,
    }


def test_ocr_json_reports_final_fallback_rc_even_with_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    source = str(tmp_path / "paper.pdf")
    output = str(tmp_path / "partial.pdf")
    calls = []

    def fake_call(command, **kwargs):
        calls.append(command)
        Path(output).write_bytes(b"partial")
        return 3 if len(calls) == 1 else 7

    monkeypatch.setattr(extract_cli.subprocess, "call", fake_call)

    rc = extract_cli._run_ocr(EXTRACT_DIR, [source, output, "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert len(calls) == 2
    assert rc == 7
    assert payload["status"] == "failed"
    assert payload["exit"] == 7
    assert payload["exists"] is True
    assert payload["size"] == len(b"partial")
    assert payload["failure"]["code"] == "ocr_failed"
    assert "falling back to tesseract" in captured.err


def test_ocr_json_child_rc_is_not_replaced_by_output_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    source = str(tmp_path / "paper.pdf")
    output = str(tmp_path / "partial.pdf")

    def fake_call(command, **kwargs):
        Path(output).write_bytes(b"partial")
        return 9

    monkeypatch.setattr(extract_cli.subprocess, "call", fake_call)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR, [source, output, "--engine=tesseract", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 9
    assert payload["status"] == "failed"
    assert payload["exit"] == 9
    assert payload["exists"] is True


def test_ocr_json_zero_child_rc_with_missing_output_fails_without_faking_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    source = str(tmp_path / "paper.pdf")
    output = str(tmp_path / "missing.pdf")

    monkeypatch.setattr(extract_cli.subprocess, "call", lambda command, **kwargs: 0)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR, [source, output, "--engine=tesseract", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["status"] == "failed"
    assert payload["exit"] == 0
    assert payload["exists"] is False
    assert payload["size"] == 0
    assert payload["failure"]["code"] == "output_missing"


def test_ocr_no_clobber_existing_skips_every_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    source = str(tmp_path / "paper.pdf")
    output = tmp_path / "existing.pdf"
    output.write_bytes(b"complete")

    def forbidden_call(*args, **kwargs):
        raise AssertionError("no OCR engine may run")

    monkeypatch.setattr(extract_cli.subprocess, "call", forbidden_call)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR, [source, str(output), "--no-clobber", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload == {
        "status": "existing",
        "input": source,
        "output": str(output),
        "exit": 0,
        "exists": True,
        "size": len(b"complete"),
        "failure": None,
    }


def test_ocr_no_clobber_runs_engine_in_staging_then_atomically_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    source = str(tmp_path / "paper.pdf")
    output = tmp_path / "final.pdf"
    engine_outputs: list[Path] = []

    def fake_call(command, **kwargs):
        engine_output = Path(command[3])
        engine_outputs.append(engine_output)
        assert engine_output != output
        assert engine_output.parent.parent == output.parent
        engine_output.write_bytes(b"complete staged PDF")
        return 0

    monkeypatch.setattr(extract_cli.subprocess, "call", fake_call)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR,
        [source, str(output), "--engine=tesseract", "--no-clobber", "--json"],
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["output"] == str(output)
    assert output.read_bytes() == b"complete staged PDF"
    assert len(engine_outputs) == 1
    assert engine_outputs[0].exists() is False
    assert list(tmp_path.glob(".final.pdf.ocr-*")) == []


def test_ocr_no_clobber_engine_failure_never_pollutes_final_and_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    source = str(tmp_path / "paper.pdf")
    output = tmp_path / "final.pdf"

    def fake_call(command, **kwargs):
        Path(command[3]).write_bytes(b"partial staged PDF")
        return 7

    monkeypatch.setattr(extract_cli.subprocess, "call", fake_call)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR,
        [source, str(output), "--engine=tesseract", "--no-clobber", "--json"],
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 7
    assert payload["status"] == "failed"
    assert payload["exit"] == 7
    assert payload["exists"] is False
    assert payload["size"] == 0
    assert output.exists() is False
    assert list(tmp_path.glob(".final.pdf.ocr-*")) == []


def test_ocr_no_clobber_commit_race_loser_reports_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    source = str(tmp_path / "paper.pdf")
    output = tmp_path / "final.pdf"

    def fake_call(command, **kwargs):
        Path(command[3]).write_bytes(b"losing staged PDF")
        return 0

    def racing_link(source_path, output_path):
        assert Path(source_path) != output
        Path(output_path).write_bytes(b"winning PDF")
        raise FileExistsError

    monkeypatch.setattr(extract_cli.subprocess, "call", fake_call)
    monkeypatch.setattr(extract_cli.os, "link", racing_link)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR,
        [source, str(output), "--engine=tesseract", "--no-clobber", "--json"],
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload == {
        "status": "existing",
        "input": source,
        "output": str(output),
        "exit": 0,
        "exists": True,
        "size": len(b"winning PDF"),
        "failure": None,
    }
    assert output.read_bytes() == b"winning PDF"
    assert list(tmp_path.glob(".final.pdf.ocr-*")) == []


def test_ocr_no_clobber_commit_failure_keeps_engine_exit_and_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    source = str(tmp_path / "paper.pdf")
    output = tmp_path / "final.pdf"

    def fake_call(command, **kwargs):
        Path(command[3]).write_bytes(b"complete staged PDF")
        return 0

    def failed_link(source_path, output_path):
        raise OSError("hard links unavailable")

    monkeypatch.setattr(extract_cli.subprocess, "call", fake_call)
    monkeypatch.setattr(extract_cli.os, "link", failed_link)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR,
        [source, str(output), "--engine=tesseract", "--no-clobber", "--json"],
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["status"] == "failed"
    assert payload["exit"] == 0
    assert payload["exists"] is False
    assert payload["failure"]["code"] == "commit_failed"
    assert output.exists() is False
    assert list(tmp_path.glob(".final.pdf.ocr-*")) == []


def test_ocr_no_clobber_two_processes_create_once_without_overwrite(tmp_path: Path):
    wrapper = tmp_path / "ocr-race-worker.py"
    wrapper.write_text(
        """
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import extract

extract_dir = Path(sys.argv[1])
source = sys.argv[2]
output = sys.argv[3]
barrier = Path(sys.argv[4])

def fake_call(command, **kwargs):
    marker = barrier / f"ready-{os.getpid()}"
    marker.write_text("", encoding="utf-8")
    deadline = time.monotonic() + 5
    while len(list(barrier.glob("ready-*"))) < 2:
        if time.monotonic() > deadline:
            return 90
        time.sleep(0.01)
    Path(command[3]).write_bytes(f"winner-{os.getpid()}".encode())
    return 0

extract.subprocess.call = fake_call
raise SystemExit(extract._run_ocr(
    extract_dir,
    [source, output, "--engine=tesseract", "--no-clobber", "--json"],
))
""".lstrip(),
        encoding="utf-8",
    )
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    source = str(tmp_path / "paper.pdf")
    output = tmp_path / "final.pdf"
    command = [
        sys.executable,
        str(wrapper),
        str(EXTRACT_DIR),
        source,
        str(output),
        str(barrier),
    ]

    processes = [
        subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(2)
    ]
    results = [process.communicate(timeout=10) for process in processes]
    payloads = [json.loads(stdout) for stdout, _ in results]

    assert [process.returncode for process in processes] == [0, 0]
    assert sorted(payload["status"] for payload in payloads) == ["existing", "ok"]
    assert all(payload["exit"] == 0 for payload in payloads)
    assert output.read_bytes().startswith(b"winner-")
    assert list(tmp_path.glob(".final.pdf.ocr-*")) == []


@pytest.mark.parametrize("collision", ["empty", "directory"])
def test_ocr_no_clobber_bad_collision_fails_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    collision: str,
):
    source = str(tmp_path / "paper.pdf")
    output = tmp_path / "collision"
    if collision == "empty":
        output.touch()
    else:
        output.mkdir()

    def forbidden_call(*args, **kwargs):
        raise AssertionError("no OCR engine may run")

    monkeypatch.setattr(extract_cli.subprocess, "call", forbidden_call)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR, [source, str(output), "--no-clobber", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["status"] == "failed"
    assert payload["exit"] == 2
    assert payload["exists"] is True
    assert payload["failure"]["code"] == (
        "output_empty" if collision == "empty" else "output_not_regular"
    )
    assert output.exists()
    assert output.is_dir() if collision == "directory" else output.stat().st_size == 0


def test_ocr_default_mode_keeps_legacy_subprocess_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    source = str(tmp_path / "paper.pdf")
    output = str(tmp_path / "paper-ocr.pdf")
    calls = []

    def fake_call(command, **kwargs):
        calls.append((command, kwargs))
        return 0

    monkeypatch.setattr(extract_cli.subprocess, "call", fake_call)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR, [source, output, "--engine", "tesseract"]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert calls == [(
        ["bash", str(EXTRACT_DIR / "ocr_pdf.sh"), source, output],
        {},
    )]


def test_ocr_duplicate_engine_is_rejected_before_subprocess(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    def forbidden_call(*args, **kwargs):
        raise AssertionError("invalid args must not launch an engine")

    monkeypatch.setattr(extract_cli.subprocess, "call", forbidden_call)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR,
        [
            "in.pdf",
            "out.pdf",
            "--engine",
            "dsocr2",
            "--engine=tesseract",
            "--json",
        ],
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["status"] == "failed"
    assert payload["input"] == "in.pdf"
    assert payload["output"] == "out.pdf"
    assert payload["failure"]["code"] == "invalid_arguments"


@pytest.mark.parametrize(
    "duplicate",
    [
        ["--json", "--json"],
        ["--no-clobber", "--no-clobber", "--json"],
        ["--layout", "--layout", "--json"],
    ],
)
def test_ocr_duplicate_flags_are_rejected_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    duplicate: list[str],
):
    def forbidden_call(*args, **kwargs):
        raise AssertionError("invalid args must not launch an engine")

    monkeypatch.setattr(extract_cli.subprocess, "call", forbidden_call)

    rc = extract_cli._run_ocr(
        EXTRACT_DIR, ["in.pdf", "out.pdf", *duplicate]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["status"] == "failed"
    assert payload["input"] == "in.pdf"
    assert payload["output"] == "out.pdf"
    assert payload["failure"]["code"] == "invalid_arguments"


@pytest.mark.parametrize(
    "bad_args",
    [
        ["--unknown", "caller-in.pdf", "caller-out.pdf", "--json"],
        ["caller-in.pdf", "caller-out.pdf", "--engine", "--json"],
        [
            "--engine=tesseract",
            "caller-in.pdf",
            "caller-out.pdf",
            "--engine=tesseract",
            "--json",
        ],
    ],
)
def test_ocr_json_invalid_arguments_echo_parsed_caller_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bad_args: list[str],
):
    def forbidden_call(*args, **kwargs):
        raise AssertionError("invalid args must not launch an engine")

    monkeypatch.setattr(extract_cli.subprocess, "call", forbidden_call)

    rc = extract_cli._run_ocr(EXTRACT_DIR, bad_args)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.out.count("\n") == 1
    assert rc == 2
    assert payload["status"] == "failed"
    assert payload["input"] == "caller-in.pdf"
    assert payload["output"] == "caller-out.pdf"
    assert payload["failure"]["code"] == "invalid_arguments"


def test_ocr_json_help_combination_is_one_invalid_arguments_object():
    result = run_extract(
        "ocr", "caller-in.pdf", "caller-out.pdf", "--help", "--json"
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert result.stdout.count("\n") == 1
    assert "Usage:" not in result.stdout
    assert payload["status"] == "failed"
    assert payload["input"] == "caller-in.pdf"
    assert payload["output"] == "caller-out.pdf"
    assert payload["failure"]["code"] == "invalid_arguments"


def _write_pdf(path: Path, pages: list[str]) -> None:
    import fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=11)
    doc.save(path)
    doc.close()


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext unavailable")
def test_text_extract_writes_utf8_and_machine_signals(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    output = tmp_path / "nested" / "paper.txt"
    _write_pdf(source, ["Making sense of conduct", "Café, agency, and culture"])

    result = run_extract("text", str(source), str(output), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    text = output.read_text(encoding="utf-8")
    assert payload == {
        "status": "ok",
        "input": str(source),
        "output": str(output),
        "exists": True,
        "size": output.stat().st_size,
        "chars": len(text),
        "non_whitespace_chars": sum(not char.isspace() for char in text),
        "exit": 0,
        "failure": None,
        "pages": 2,
        "text_pages": 2,
    }
    assert "Making sense of conduct" in text
    assert "Café, agency, and culture" in text


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext unavailable")
def test_text_extract_empty_text_layer_is_success_with_low_signals(tmp_path: Path):
    source = tmp_path / "image-only.pdf"
    output = tmp_path / "image-only.txt"
    _write_pdf(source, ["", ""])

    result = run_extract("text", str(source), str(output), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["failure"] is None
    assert payload["chars"] >= 0
    assert payload["non_whitespace_chars"] == 0
    assert payload["text_pages"] == 0
    assert output.is_file()


def test_text_extract_missing_input_returns_json_failure(tmp_path: Path):
    source = tmp_path / "missing.pdf"
    output = tmp_path / "paper.txt"

    result = run_extract("text", str(source), str(output), "--json")

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["input"] == str(source)
    assert payload["output"] == str(output)
    assert payload["exists"] is False
    assert payload["size"] == 0
    assert payload["pages"] == 0
    assert payload["text_pages"] == 0
    assert payload["exit"] == 2
    assert payload["failure"]["code"] == "input_missing"


def test_text_extract_reports_missing_pdftotext(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    output = tmp_path / "paper.txt"
    source.write_bytes(b"%PDF-1.4\n")
    env = os.environ.copy()
    env["PATH"] = str(tmp_path / "empty-path")

    result = run_extract("text", str(source), str(output), "--json", env=env)

    assert result.returncode == 127
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["pages"] == 0
    assert payload["text_pages"] == 0
    assert payload["exit"] == 127
    assert payload["failure"]["code"] == "pdftotext_missing"
    assert output.exists() is False


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext unavailable")
def test_text_extract_tool_failure_preserves_existing_output(tmp_path: Path):
    source = tmp_path / "broken.pdf"
    output = tmp_path / "paper.txt"
    source.write_text("not a PDF", encoding="utf-8")
    output.write_text("previous complete output", encoding="utf-8")

    result = run_extract("text", str(source), str(output), "--json")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["failure"]["code"] == "pdftotext_failed"
    assert payload["exists"] is True
    assert payload["size"] == len("previous complete output")
    assert output.read_text(encoding="utf-8") == "previous complete output"
    assert list(tmp_path.glob(".paper.txt.*.tmp")) == []


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext unavailable")
def test_text_extract_atomic_overwrite_is_idempotent(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    output = tmp_path / "paper.txt"
    _write_pdf(source, ["Stable normalized body"])
    output.write_text("stale", encoding="utf-8")

    first = run_extract("text", str(source), str(output), "--json")
    first_text = output.read_bytes()
    second = run_extract("text", str(source), str(output), "--json")

    assert first.returncode == second.returncode == 0
    assert output.read_bytes() == first_text
    assert json.loads(first.stdout) == json.loads(second.stdout)
    assert b"Stable normalized body" in first_text
    assert list(tmp_path.glob(".paper.txt.*.tmp")) == []


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


CHAPTER_RECEIPT_FIELDS = {
    "schema_version",
    "status",
    "input_path",
    "output_dir",
    "mode",
    "disposition",
    "exit",
    "manifest_path",
    "manifest_exists",
    "request_fingerprint",
    "manifest_fingerprint",
    "chapter_count",
    "chapters",
    "skipped",
    "removed_files",
    "limit",
    "previous_manifest_preserved",
    "failure",
}


def _book_pdf(path: Path, pages: list[str], toc: list[list] | None = None) -> None:
    import fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(
            fitz.Rect(72, 72, 520, 760),
            text,
            fontsize=10,
        )
    if toc:
        doc.set_toc(toc)
    doc.save(path)
    doc.close()


def _manual_specs(count: int) -> str:
    return json.dumps([
        {
            "title": f"Chapter {index}",
            "start": index,
            "end": index,
        }
        for index in range(1, count + 1)
    ])


def _run_manual(pdf: Path, output: Path, count: int, *extra: str):
    return run_extract(
        "split",
        str(pdf),
        "--output-dir",
        str(output),
        "--chapters",
        _manual_specs(count),
        "--min-chapter-length",
        "0",
        "--json",
        *extra,
    )


def test_book_manual_json_is_one_flat_receipt_and_full_manifest(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["first body " * 20, "second body " * 20])

    result = _run_manual(pdf, output, 2)

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 1
    assert "Created:" not in result.stdout
    assert "Created:" in result.stderr
    receipt = json.loads(result.stdout)
    assert set(receipt) == CHAPTER_RECEIPT_FIELDS
    assert receipt["schema_version"] == "quasi.extract.chapters.receipt/0.1"
    assert receipt["status"] == "ok"
    assert receipt["mode"] == "manual"
    assert receipt["disposition"] == "created"
    assert receipt["chapter_count"] == 2
    assert receipt["chapters"] == json.loads(
        (output / "manifest.json").read_text(encoding="utf-8")
    )["chapters"]
    assert receipt["limit"] == {"max_chapters": 50, "exceeded": False}
    assert receipt["previous_manifest_preserved"] is False
    assert receipt["failure"] is None
    assert all(row["sha256"] for row in receipt["chapters"])
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        (output / "manifest.json").read_bytes()
    ).hexdigest()


@pytest.mark.parametrize("method", ["toc", "pattern"])
def test_book_exact_toc_and_pattern_json_modes(tmp_path: Path, method: str):
    pdf = tmp_path / f"{method}.pdf"
    output = tmp_path / f"{method}-chapters"
    if method == "toc":
        _book_pdf(
            pdf,
            ["first body " * 20, "second body " * 20],
            [[1, "Chapter 1: First", 1], [1, "Chapter 2: Second", 2]],
        )
        extra: list[str] = []
    else:
        _book_pdf(
            pdf,
            [
                "Chapter 1: First\n" + "first body " * 20,
                "Chapter 2: Second\n" + "second body " * 20,
            ],
        )
        extra = ["--patterns", r"^Chapter\s+\d+"]

    result = run_extract(
        "split",
        str(pdf),
        "--output-dir",
        str(output),
        "--method",
        method,
        "--min-chapter-length",
        "0",
        "--json",
        *extra,
    )

    receipt = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert receipt["mode"] == method
    assert receipt["chapter_count"] == 2
    assert receipt["limit"]["exceeded"] is False
    assert json.loads((output / "manifest.json").read_text())["split_method"] == method


def test_book_replacement_removes_only_previous_manifest_owned_stale_file(
    tmp_path: Path,
):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20, "two " * 20])
    first = _run_manual(pdf, output, 2)
    assert first.returncode == 0
    old_second = json.loads(first.stdout)["chapters"][1]["filename"]
    unrelated = output / "reader-notes.txt"
    unrelated.write_text("user owned", encoding="utf-8")

    second = _run_manual(pdf, output, 1)

    receipt = json.loads(second.stdout)
    assert second.returncode == 0, second.stderr
    assert receipt["disposition"] == "replaced"
    assert receipt["removed_files"] == [old_second]
    assert (output / old_second).exists() is False
    assert unrelated.read_text(encoding="utf-8") == "user owned"
    assert sorted(row["filename"] for row in receipt["chapters"]) == [
        path.name
        for path in output.iterdir()
        if path.suffix == ".txt" and path != unrelated
    ]


def test_book_failed_run_preserves_prior_manifest_and_chapters(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20])
    assert _run_manual(pdf, output, 1).returncode == 0
    manifest_before = (output / "manifest.json").read_bytes()
    chapter_before = next(
        path for path in output.glob("*.txt")
    ).read_bytes()

    result = run_extract(
        "split",
        str(pdf),
        "--output-dir",
        str(output),
        "--chapters",
        "{not-json",
        "--json",
    )

    receipt = json.loads(result.stdout)
    assert result.returncode == 2
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "invalid_chapters_json"
    assert receipt["failure"]["outcome"] == "known"
    assert receipt["failure"]["retryable"] is False
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        manifest_before
    ).hexdigest()
    assert receipt["previous_manifest_preserved"] is True
    assert (output / "manifest.json").read_bytes() == manifest_before
    assert next(path for path in output.glob("*.txt")).read_bytes() == chapter_before


def test_book_repair_updates_exact_slot_and_renames_owned_file(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20, "replacement " * 20])
    initial = json.loads(_run_manual(pdf, output, 2).stdout)
    old_row = initial["chapters"][0]
    untouched = initial["chapters"][1]
    untouched_bytes = (output / untouched["filename"]).read_bytes()

    result = run_extract(
        "split",
        str(pdf),
        "--output-dir",
        str(output),
        "--pages",
        "2-2",
        "--title",
        "Repaired title",
        "--slot",
        old_row["slot"],
        "--json",
    )

    receipt = json.loads(result.stdout)
    repaired = next(
        row for row in receipt["chapters"] if row["slot"] == old_row["slot"]
    )
    assert result.returncode == 0, result.stderr
    assert receipt["mode"] == "repair"
    assert receipt["disposition"] == "repaired"
    assert receipt["chapter_count"] == 2
    assert repaired["filename"] == f"{old_row['slot']}_Repaired_title.txt"
    assert repaired["start_page"] == repaired["end_page"] == 2
    assert old_row["filename"] in receipt["removed_files"]
    assert (output / old_row["filename"]).exists() is False
    assert "replacement" in (output / repaired["filename"]).read_text()
    assert (output / untouched["filename"]).read_bytes() == untouched_bytes


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (["--pages", "1-1", "--title", "X", "--slot", "missing"], "slot_not_found"),
        (["--pages", "2-1", "--title", "X", "--slot", "01"], "invalid_range"),
        (["--pages", "1-999", "--title", "X", "--slot", "01"], "invalid_range"),
    ],
)
def test_book_repair_rejects_unknown_slot_and_invalid_range(
    tmp_path: Path, arguments: list[str], code: str
):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20])
    assert _run_manual(pdf, output, 1).returncode == 0
    before = (output / "manifest.json").read_bytes()

    result = run_extract(
        "split",
        str(pdf),
        "--output-dir",
        str(output),
        *arguments,
        "--json",
    )

    receipt = json.loads(result.stdout)
    assert result.returncode == 2
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == code
    assert receipt["failure"]["outcome"] == "known"
    assert receipt["failure"]["retryable"] is False
    assert receipt["previous_manifest_preserved"] is True
    assert (output / "manifest.json").read_bytes() == before


def test_book_limit_is_signal_only_and_never_changes_manual_output(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20, "two " * 20])

    result = _run_manual(pdf, output, 2, "--max-chapters", "1")

    receipt = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert receipt["chapter_count"] == 2
    assert receipt["limit"] == {"max_chapters": 1, "exceeded": True}
    assert receipt["mode"] == "manual"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--chapters", "{", "--json"],
        ["--method", "auto", "--json"],
        ["--pages", "1-1", "--slot", "01", "--json"],
    ],
)
def test_book_invalid_json_arguments_emit_exactly_one_receipt(
    tmp_path: Path, arguments: list[str]
):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20])

    result = run_extract(
        "split",
        str(pdf),
        "--output-dir",
        str(output),
        *arguments,
    )

    receipt = json.loads(result.stdout)
    assert result.returncode == 2
    assert result.stdout.count("\n") == 1
    assert receipt["status"] == "failed"
    assert receipt["failure"]["outcome"] == "known"
    assert receipt["failure"]["retryable"] is False
    assert set(receipt) == CHAPTER_RECEIPT_FIELDS


def test_book_identical_rerun_reconciles_without_rewriting(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20])
    first = _run_manual(pdf, output, 1)
    manifest_mtime = (output / "manifest.json").stat().st_mtime_ns

    second = _run_manual(pdf, output, 1)

    receipt = json.loads(second.stdout)
    assert first.returncode == second.returncode == 0
    assert receipt["status"] == "existing"
    assert receipt["disposition"] == "reconciled"
    assert receipt["previous_manifest_preserved"] is True
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        (output / "manifest.json").read_bytes()
    ).hexdigest()
    assert (output / "manifest.json").stat().st_mtime_ns == manifest_mtime


def test_book_two_process_same_output_race_has_one_generation(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20, "two " * 20])
    command = [
        sys.executable,
        str(EXTRACT),
        "split",
        str(pdf),
        "--output-dir",
        str(output),
        "--chapters",
        _manual_specs(2),
        "--min-chapter-length",
        "0",
        "--json",
    ]
    processes = [
        subprocess.Popen(
            command,
            cwd=PLUGIN_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(2)
    ]
    results = [process.communicate(timeout=10) for process in processes]
    receipts = [json.loads(stdout) for stdout, _ in results]

    assert [process.returncode for process in processes] == [0, 0]
    assert sorted(receipt["status"] for receipt in receipts) == ["existing", "ok"]
    assert len({receipt["request_fingerprint"] for receipt in receipts}) == 1
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["chapters"] == receipts[0]["chapters"]
    assert {
        path.name for path in output.glob("*.txt")
    } == {row["filename"] for row in manifest["chapters"]}
    assert list(tmp_path.glob(".chapters.stage-*")) == []
    assert list(tmp_path.glob(".chapters.backup-*")) == []


def test_book_manifest_change_during_build_fails_closed(
    tmp_path: Path,
):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20])
    first = _run_manual(pdf, output, 1)
    assert first.returncode == 0
    expected_manifest_fingerprint = hashlib.sha256(
        (output / "manifest.json").read_bytes()
    ).hexdigest()
    winner_manifest = json.loads((output / "manifest.json").read_text())
    winner_manifest["external_writer"] = "won"

    def racing_builder(stage: Path, previous: dict | None) -> dict:
        assert previous is not None
        for row in previous["chapters"]:
            shutil.copy2(output / row["filename"], stage / row["filename"])
        (output / "manifest.json").write_text(
            json.dumps(winner_manifest),
            encoding="utf-8",
        )
        return previous

    rc, receipt = chapter_commit.commit_chapter_set(
        input_path=pdf,
        output_dir=output,
        mode="manual",
        options={"chapters": "different"},
        max_chapters=50,
        build_stage=racing_builder,
        expected_manifest_fingerprint=expected_manifest_fingerprint,
    )

    assert rc == 1
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "expected_manifest_mismatch"
    assert receipt["failure"]["outcome"] == "known"
    assert receipt["failure"]["retryable"] is False
    assert receipt["previous_manifest_preserved"] is False
    assert json.loads((output / "manifest.json").read_text())["external_writer"] == "won"


def test_book_publish_failure_rolls_back_files_and_preserves_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["old " * 20, "new " * 20])
    assert _run_manual(pdf, output, 1).returncode == 0
    manifest_before = (output / "manifest.json").read_bytes()
    row = json.loads(manifest_before)["chapters"][0]
    chapter_before = (output / row["filename"]).read_bytes()
    real_replace = chapter_commit.os.replace

    def fail_manifest_replace(source, target):
        if Path(target) == output / "manifest.json":
            raise OSError("simulated manifest commit failure")
        return real_replace(source, target)

    monkeypatch.setattr(chapter_commit.os, "replace", fail_manifest_replace)
    specs = [{"title": "Renamed", "start": 2, "end": 2}]

    def build(stage: Path, _previous: dict | None) -> dict:
        chapters = split_chapters.split_by_manual(str(pdf), specs)
        chapters, skipped = split_chapters.filter_and_assign(chapters)
        split_chapters.save_chapters(chapters, stage)
        return split_chapters.create_manifest(
            chapters,
            skipped,
            stage,
            pdf.name,
            "manual",
            include_end=True,
        )

    rc, receipt = chapter_commit.commit_chapter_set(
        input_path=pdf,
        output_dir=output,
        mode="manual",
        options={"chapters": specs},
        max_chapters=50,
        build_stage=build,
    )

    assert rc == 1
    assert receipt["status"] == "blocked"
    assert receipt["failure"]["code"] == "commit_failed"
    assert receipt["failure"]["outcome"] == "unknown"
    assert receipt["failure"]["retryable"] is False
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        manifest_before
    ).hexdigest()
    assert receipt["previous_manifest_preserved"] is True
    assert (output / "manifest.json").read_bytes() == manifest_before
    assert (output / row["filename"]).read_bytes() == chapter_before
    assert (output / "01_Renamed.txt").exists() is False


def test_book_malformed_stage_is_blocked_unknown_without_final_writes(
    tmp_path: Path,
):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20])

    rc, receipt = chapter_commit.commit_chapter_set(
        input_path=pdf,
        output_dir=output,
        mode="manual",
        options={"malformed": True},
        max_chapters=50,
        build_stage=lambda _stage, _previous: "not a manifest",
    )

    assert rc == 1
    assert receipt["status"] == "blocked"
    assert receipt["failure"]["code"] == "writer_receipt_invalid"
    assert receipt["failure"]["outcome"] == "unknown"
    assert receipt["failure"]["retryable"] is False
    assert receipt["manifest_exists"] is False
    assert receipt["manifest_fingerprint"] is None
    assert output.exists() is False


def test_book_output_symlink_is_rejected_without_touching_target(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    real_output = tmp_path / "real-output"
    output = tmp_path / "chapters"
    real_output.mkdir()
    (real_output / "reader-notes.txt").write_text("keep", encoding="utf-8")
    output.symlink_to(real_output, target_is_directory=True)
    _book_pdf(pdf, ["one " * 20])

    result = _run_manual(pdf, output, 1)

    receipt = json.loads(result.stdout)
    assert result.returncode == 1
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "output_not_directory"
    assert receipt["failure"]["outcome"] == "known"
    assert receipt["failure"]["retryable"] is False
    assert (real_output / "reader-notes.txt").read_text() == "keep"
    assert sorted(path.name for path in real_output.iterdir()) == ["reader-notes.txt"]


def test_book_different_fresh_concurrent_writer_cannot_overwrite_winner(
    tmp_path: Path,
):
    wrapper = tmp_path / "chapter-race-worker.py"
    wrapper.write_text(
        """
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import chapter_commit

source = Path(sys.argv[2])
output = Path(sys.argv[3])
barrier = Path(sys.argv[4])
label = sys.argv[5]
original_lock = chapter_commit._output_lock

@contextmanager
def barrier_lock(output_dir):
    (barrier / f"ready-{label}").write_text("", encoding="utf-8")
    deadline = time.monotonic() + 5
    while len(list(barrier.glob("ready-*"))) < 2:
        if time.monotonic() > deadline:
            raise RuntimeError("barrier timeout")
        time.sleep(0.01)
    with original_lock(output_dir):
        yield

chapter_commit._output_lock = barrier_lock

def build(stage, previous):
    filename = f"01_{label}.txt"
    (stage / filename).write_text(f"# {label}\\n\\n{label}", encoding="utf-8")
    return {
        "source_pdf": source.name,
        "split_method": "manual",
        "chapters": [{
            "slot": "01",
            "title": label,
            "filename": filename,
            "slug": label.lower(),
            "word_count": 1,
        }],
        "skipped": [],
    }

rc, receipt = chapter_commit.commit_chapter_set(
    input_path=source,
    output_dir=output,
    mode="manual",
    options={"label": label},
    max_chapters=50,
    build_stage=build,
)
chapter_commit.emit_receipt(receipt)
raise SystemExit(rc)
""".lstrip(),
        encoding="utf-8",
    )
    source = tmp_path / "book.pdf"
    source.write_bytes(b"stable source identity")
    output = tmp_path / "chapters"
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    commands = [
        [
            sys.executable,
            str(wrapper),
            str(EXTRACT_DIR),
            str(source),
            str(output),
            str(barrier),
            label,
        ]
        for label in ("Alpha", "Beta")
    ]
    processes = [
        subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for command in commands
    ]
    results = [process.communicate(timeout=10) for process in processes]
    receipts = [json.loads(stdout) for stdout, _ in results]

    assert sorted(process.returncode for process in processes) == [0, 1]
    assert sorted(receipt["status"] for receipt in receipts) == ["failed", "ok"]
    loser = next(receipt for receipt in receipts if receipt["status"] == "failed")
    assert loser["failure"]["code"] == "manifest_conflict"
    assert loser["failure"]["outcome"] == "known"
    assert loser["failure"]["retryable"] is False
    assert loser["previous_manifest_preserved"] is True
    manifest = json.loads((output / "manifest.json").read_text())
    assert len(manifest["chapters"]) == 1
    assert {path.name for path in output.glob("*.txt")} == {
        manifest["chapters"][0]["filename"]
    }


def test_book_expected_manifest_fingerprint_allows_exact_replacement(
    tmp_path: Path,
):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20, "two " * 20])
    first = json.loads(_run_manual(pdf, output, 1).stdout)
    expected = first["manifest_fingerprint"]

    result = _run_manual(
        pdf,
        output,
        2,
        "--expected-manifest-fingerprint",
        expected,
    )

    receipt = json.loads(result.stdout)
    manifest_bytes = (output / "manifest.json").read_bytes()
    assert result.returncode == 0, result.stderr
    assert receipt["status"] == "ok"
    assert receipt["disposition"] == "replaced"
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        manifest_bytes
    ).hexdigest()
    assert receipt["manifest_fingerprint"] != expected


def test_book_expected_manifest_mismatch_fails_before_extraction(
    tmp_path: Path,
):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20, "two " * 20])
    assert _run_manual(pdf, output, 1).returncode == 0
    manifest_before = (output / "manifest.json").read_bytes()

    result = _run_manual(
        pdf,
        output,
        2,
        "--expected-manifest-fingerprint",
        "0" * 64,
    )

    receipt = json.loads(result.stdout)
    assert result.returncode == 1
    assert "Created:" not in result.stderr
    assert receipt["status"] == "failed"
    assert receipt["failure"] == {
        "code": "expected_manifest_mismatch",
        "outcome": "known",
        "retryable": False,
        "message": "manifest fingerprint does not match the caller precondition",
    }
    assert receipt["request_fingerprint"] is None
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        manifest_before
    ).hexdigest()
    assert (output / "manifest.json").read_bytes() == manifest_before


@pytest.mark.parametrize(
    ("code", "status", "outcome"),
    [
        ("invalid_arguments", "failed", "known"),
        ("manifest_missing", "failed", "known"),
        ("writer_receipt_invalid", "blocked", "unknown"),
        ("commit_failed", "blocked", "unknown"),
    ],
)
def test_book_error_receipt_matrix_and_exact_flat_keys(
    tmp_path: Path,
    code: str,
    status: str,
    outcome: str,
):
    error = chapter_commit.ChapterFailure(
        code,
        f"representative {code}",
        status=status,
        outcome=outcome,
    )

    receipt = chapter_commit.failure_receipt(
        input_path=tmp_path / "book.pdf",
        output_dir=tmp_path / "chapters",
        mode="manual",
        max_chapters=50,
        error=error,
    )

    assert set(receipt) == CHAPTER_RECEIPT_FIELDS
    assert receipt["status"] == status
    assert receipt["failure"] == {
        "code": code,
        "outcome": outcome,
        "retryable": False,
        "message": f"representative {code}",
    }
    assert receipt["request_fingerprint"] is None
    assert receipt["manifest_fingerprint"] is None


@pytest.mark.parametrize(
    ("status", "outcome", "retryable"),
    [
        ("failed", "unknown", False),
        ("failed", "known", True),
        ("blocked", "known", False),
        ("blocked", "unknown", True),
    ],
)
def test_book_failure_constructor_rejects_open_matrix(
    status: str, outcome: str, retryable: bool
):
    with pytest.raises(ValueError, match="failure matrix"):
        chapter_commit.ChapterFailure(
            "bad_matrix",
            "invalid failure matrix",
            status=status,
            outcome=outcome,
            retryable=retryable,
        )


@pytest.mark.parametrize("with_previous", [False, True], ids=["fresh", "replacement"])
def test_book_post_manifest_fsync_failure_keeps_new_generation_coherent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_previous: bool,
):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["old " * 20, "new " * 20])
    if with_previous:
        assert _run_manual(pdf, output, 1).returncode == 0

    real_fsync = chapter_commit.os.fsync
    fsync_calls = 0

    def fail_post_manifest_fsync(fd):
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError("simulated post-manifest directory fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(chapter_commit.os, "fsync", fail_post_manifest_fsync)
    specs = [{"title": "New", "start": 2, "end": 2}]

    def build(stage: Path, _previous: dict | None) -> dict:
        chapters = split_chapters.split_by_manual(str(pdf), specs)
        chapters, skipped = split_chapters.filter_and_assign(chapters)
        split_chapters.save_chapters(chapters, stage)
        return split_chapters.create_manifest(
            chapters,
            skipped,
            stage,
            pdf.name,
            "manual",
            include_end=True,
        )

    rc, receipt = chapter_commit.commit_chapter_set(
        input_path=pdf,
        output_dir=output,
        mode="manual",
        options={"chapters": specs},
        max_chapters=50,
        build_stage=build,
    )

    manifest_bytes = (output / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    row = manifest["chapters"][0]
    assert rc == 1
    assert fsync_calls == 2
    assert receipt["status"] == "blocked"
    assert receipt["disposition"] is None
    assert receipt["failure"]["code"] == "commit_failed"
    assert receipt["failure"]["outcome"] == "unknown"
    assert receipt["failure"]["retryable"] is False
    assert receipt["previous_manifest_preserved"] is False
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        manifest_bytes
    ).hexdigest()
    assert receipt["chapters"] == manifest["chapters"]
    assert row["title"] == "New"
    assert "new" in (output / row["filename"]).read_text(encoding="utf-8")
    chapter_commit.validate_manifest(manifest, output)

    reconcile_rc, reconcile = chapter_commit.commit_chapter_set(
        input_path=pdf,
        output_dir=output,
        mode="manual",
        options={"chapters": specs},
        max_chapters=50,
        build_stage=build,
    )
    assert reconcile_rc == 0
    assert reconcile["status"] == "existing"
    assert reconcile["disposition"] == "reconciled"
    assert reconcile["manifest_fingerprint"] == receipt["manifest_fingerprint"]
    assert list(tmp_path.glob(".chapters.stage-*")) == []
    assert list(tmp_path.glob(".chapters.backup-*")) == []


def test_book_legacy_manual_renders_prose_over_transaction(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["legacy " * 20])

    result = run_extract(
        "split",
        str(pdf),
        "--output-dir",
        str(output),
        "--chapters",
        _manual_specs(1),
        "--min-chapter-length",
        "0",
    )

    manifest = json.loads((output / "manifest.json").read_text())
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Manual mode: 1 chapters specified")
    assert f"Created: {output / manifest['chapters'][0]['filename']}" in result.stdout
    assert f"Created manifest: {output / 'manifest.json'}" in result.stdout
    assert result.stdout.rstrip().endswith("Done!")
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    chapter_commit.validate_manifest(manifest, output)


def test_book_legacy_pages_uses_transaction_manifest(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["single range " * 20])

    result = run_extract(
        "split",
        str(pdf),
        "--output-dir",
        str(output),
        "--pages",
        "1-1",
        "--title",
        "Legacy title",
    )

    manifest = json.loads((output / "manifest.json").read_text())
    row = manifest["chapters"][0]
    assert result.returncode == 0, result.stderr
    assert row["filename"] == "Legacy_title.txt"
    assert result.stdout.strip() == (
        f"Extracted pages 1-1 → {output / row['filename']}"
    )
    chapter_commit.validate_manifest(manifest, output)


def test_book_legacy_pattern_uses_transaction_manifest(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(
        pdf,
        [
            "Chapter 1: First\n" + "first body " * 20,
            "Chapter 2: Second\n" + "second body " * 20,
        ],
    )

    result = run_extract(
        "split",
        str(pdf),
        "--output-dir",
        str(output),
        "--method",
        "pattern",
        "--patterns",
        r"^Chapter\s+\d+",
        "--min-chapter-length",
        "0",
    )

    manifest = json.loads((output / "manifest.json").read_text())
    assert result.returncode == 0, result.stderr
    assert manifest["split_method"] == "pattern"
    assert len(manifest["chapters"]) == 2
    assert result.stdout.rstrip().endswith(
        "Done! Chapter files are ready for processing."
    )
    chapter_commit.validate_manifest(manifest, output)


def test_book_json_and_legacy_writers_share_one_output_lock(
    tmp_path: Path,
):
    wrapper = tmp_path / "paused-json-split.py"
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    wrapper.write_text(
        """
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import chapter_commit

output = Path(sys.argv[3])
ready = Path(sys.argv[4])
release = Path(sys.argv[5])
real_replace = chapter_commit.os.replace

def paused_replace(source, target):
    if Path(target) == output / "manifest.json":
        ready.write_text("ready", encoding="utf-8")
        deadline = time.monotonic() + 10
        while not release.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("barrier timeout")
            time.sleep(0.01)
    return real_replace(source, target)

chapter_commit.os.replace = paused_replace
import split_chapters

sys.argv = [
    "split_chapters.py",
    sys.argv[2],
    "--output-dir",
    sys.argv[3],
    "--chapters",
    '[{"title":"Same","start":1,"end":1}]',
    "--min-chapter-length",
    "0",
    "--json",
]
raise SystemExit(split_chapters.main())
""".lstrip(),
        encoding="utf-8",
    )
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["json generation " * 20, "legacy generation " * 20])
    json_writer = subprocess.Popen(
        [
            sys.executable,
            str(wrapper),
            str(EXTRACT_DIR),
            str(pdf),
            str(output),
            str(ready),
            str(release),
        ],
        cwd=PLUGIN_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 10
    while not ready.exists():
        if json_writer.poll() is not None:
            pytest.fail(f"JSON writer exited early: {json_writer.communicate()}")
        if time.monotonic() > deadline:
            pytest.fail("JSON writer did not reach manifest replacement")
        time.sleep(0.01)

    legacy_writer = subprocess.Popen(
        [
            sys.executable,
            str(EXTRACT),
            "split",
            str(pdf),
            "--output-dir",
            str(output),
            "--chapters",
            '[{"title":"Same","start":2,"end":2}]',
            "--min-chapter-length",
            "0",
        ],
        cwd=PLUGIN_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    legacy_completed_while_locked = False
    try:
        legacy_writer.wait(timeout=0.2)
        legacy_completed_while_locked = True
    except subprocess.TimeoutExpired:
        pass
    finally:
        release.write_text("release", encoding="utf-8")
    json_stdout, json_stderr = json_writer.communicate(timeout=10)
    legacy_stdout, legacy_stderr = legacy_writer.communicate(timeout=10)

    receipt = json.loads(json_stdout)
    manifest_bytes = (output / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert legacy_completed_while_locked is False
    assert json_writer.returncode == 0, json_stderr
    assert receipt["status"] == "ok"
    assert legacy_writer.returncode == 1, (legacy_stdout, legacy_stderr)
    assert "competing chapter generation" in legacy_stdout
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        manifest_bytes
    ).hexdigest()
    assert receipt["chapters"] == manifest["chapters"]
    assert "json generation" in (
        output / manifest["chapters"][0]["filename"]
    ).read_text(encoding="utf-8")
    chapter_commit.validate_manifest(manifest, output)

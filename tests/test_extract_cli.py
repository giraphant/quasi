from __future__ import annotations

import ast
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

import ocr_mineru  # noqa: E402
import split_chapters  # noqa: E402
import extract as extract_cli  # noqa: E402
import chapter_commit  # noqa: E402
import ocr_generation  # noqa: E402


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
    assert "quasi-extract ocr-generation" in result.stdout
    assert "quasi-extract split" in result.stdout
    # OCR engine switch is part of the documented surface.
    assert "--engine mineru|tesseract" in result.stdout


def test_ocr_help_exposes_engine_flag():
    result = run_extract("ocr", "--help")

    assert result.returncode == 0
    assert "--engine" in result.stdout
    assert "mineru" in result.stdout
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
    assert payload["status"] == "ok"
    assert payload["input"] == source
    assert payload["output"] == output
    assert payload["exists"] is True


def test_ocr_json_reports_failure_without_fallback_even_with_partial_output(
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
    assert len(calls) == 1
    assert rc == 3
    assert payload["status"] == "failed"
    assert payload["exit"] == 3
    assert payload["exists"] is True
    assert payload["size"] == len(b"partial")
    assert "falling back" not in captured.err


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
    assert payload["status"] == "existing"
    assert payload["input"] == source
    assert payload["output"] == str(output)
    assert payload["exists"] is True


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
    assert payload["status"] == "existing"
    assert payload["input"] == source
    assert payload["output"] == str(output)
    assert payload["exists"] is True
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
    assert output.exists()
    assert output.is_dir() if collision == "directory" else output.stat().st_size == 0


@pytest.fixture
def forbid_engine_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_call(*args, **kwargs):
        raise AssertionError("invalid args must not launch an engine")

    monkeypatch.setattr(extract_cli.subprocess, "call", forbidden_call)


def test_ocr_duplicate_engine_is_rejected_before_subprocess(
    forbid_engine_launch, capsys: pytest.CaptureFixture[str]
):
    rc = extract_cli._run_ocr(
        EXTRACT_DIR,
        [
            "in.pdf",
            "out.pdf",
            "--engine",
            "mineru",
            "--engine=tesseract",
            "--json",
        ],
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["status"] == "failed"
    assert payload["input"] == "in.pdf"
    assert payload["output"] == "out.pdf"


@pytest.mark.parametrize(
    "duplicate",
    [
        ["--json", "--json"],
        ["--no-clobber", "--no-clobber", "--json"],
        ["--layout", "--layout", "--json"],
    ],
    ids=("json", "no-clobber", "layout"),
)
def test_ocr_duplicate_flags_are_rejected_before_subprocess(
    forbid_engine_launch,
    capsys: pytest.CaptureFixture[str],
    duplicate: list[str],
):
    rc = extract_cli._run_ocr(
        EXTRACT_DIR, ["in.pdf", "out.pdf", *duplicate]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["status"] == "failed"
    assert payload["input"] == "in.pdf"
    assert payload["output"] == "out.pdf"


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
    ids=("unknown-option", "missing-engine-value", "duplicate-engine-spelling"),
)
def test_ocr_json_invalid_arguments_echo_parsed_caller_paths(
    forbid_engine_launch,
    capsys: pytest.CaptureFixture[str],
    bad_args: list[str],
):
    rc = extract_cli._run_ocr(EXTRACT_DIR, bad_args)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.out.count("\n") == 1
    assert rc == 2
    assert payload["status"] == "failed"
    assert payload["input"] == "caller-in.pdf"
    assert payload["output"] == "caller-out.pdf"


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


def _write_pdf(path: Path, pages: list[str]) -> None:
    import fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=11)
    doc.save(path)
    doc.close()


def _load_ocr_resume():
    try:
        import ocr_resume
    except ImportError as exc:
        pytest.fail(f"resumable OCR capability is unavailable: {exc}")
    return ocr_resume


def _fake_range_ocr(calls: list[tuple[int, int]]):
    def run(source: Path, output: Path, engine: str, language: str | None) -> int:
        import fitz

        with fitz.open(source) as document:
            labels = [page.get_text().strip() for page in document]
            calls.append((int(labels[0]), int(labels[-1])))
            document.save(output)
        return 0

    return run


def test_ocr_resume_advances_one_range_per_invocation_and_merges(tmp_path: Path):
    capability = _load_ocr_resume()
    source = tmp_path / "source.pdf"
    output = tmp_path / "ocr.pdf"
    progress = tmp_path / "ocr.progress.json"
    _write_pdf(source, [str(page) for page in range(1, 6)])
    calls: list[tuple[int, int]] = []
    runner = _fake_range_ocr(calls)

    first = capability.run_ocr_step(
        source, output, progress, "tesseract", 2, None, runner=runner
    )
    second = capability.run_ocr_step(
        source, output, progress, "tesseract", 2, None, runner=runner
    )
    third = capability.run_ocr_step(
        source, output, progress, "tesseract", 2, None, runner=runner
    )

    assert first["status"] == "partial"
    assert first["progress"]["completed_pages"] == 2
    assert second["status"] == "partial"
    assert second["progress"]["completed_pages"] == 4
    assert third["status"] == "ok"
    assert third["progress"]["completed_pages"] == 5
    assert calls == [(1, 2), (3, 4), (5, 5)]
    import fitz

    with fitz.open(output) as document:
        assert document.page_count == 5
        assert [page.get_text().strip() for page in document] == [
            str(page) for page in range(1, 6)
        ]
    assert not progress.exists()
    assert not (tmp_path / ".ocr-parts").exists()


def test_ocr_resume_rejects_source_drift_without_running_engine(tmp_path: Path):
    capability = _load_ocr_resume()
    source = tmp_path / "source.pdf"
    output = tmp_path / "ocr.pdf"
    progress = tmp_path / "ocr.progress.json"
    _write_pdf(source, ["1", "2", "3"])
    capability.run_ocr_step(
        source, output, progress, "tesseract", 1, None,
        runner=_fake_range_ocr([]),
    )
    _write_pdf(source, ["replacement"])

    with pytest.raises(ValueError, match="source_sha256"):
        capability.run_ocr_step(
            source, output, progress, "tesseract", 1, None,
            runner=lambda *_args: pytest.fail("engine must not run after source drift"),
        )


def test_ocr_resume_rejects_corrupt_committed_part(tmp_path: Path):
    capability = _load_ocr_resume()
    source = tmp_path / "source.pdf"
    output = tmp_path / "ocr.pdf"
    progress = tmp_path / "ocr.progress.json"
    _write_pdf(source, ["1", "2", "3"])
    capability.run_ocr_step(
        source, output, progress, "tesseract", 1, None,
        runner=_fake_range_ocr([]),
    )
    next_part = tmp_path / ".ocr-parts" / "pages-000002-000002.pdf"
    next_part.write_bytes(b"not a pdf")

    with pytest.raises(ValueError, match="part"):
        capability.run_ocr_step(
            source, output, progress, "tesseract", 1, None,
            runner=lambda *_args: pytest.fail("corrupt committed part must not be replaced"),
        )


def test_ocr_resume_engine_death_leaves_progress_at_last_commit(tmp_path: Path):
    capability = _load_ocr_resume()
    source = tmp_path / "source.pdf"
    output = tmp_path / "ocr.pdf"
    progress = tmp_path / "ocr.progress.json"
    _write_pdf(source, ["1", "2"])

    with pytest.raises(RuntimeError, match="interrupted"):
        capability.run_ocr_step(
            source,
            output,
            progress,
            "tesseract",
            1,
            None,
            runner=lambda *_args: (_ for _ in ()).throw(RuntimeError("interrupted")),
        )

    assert json.loads(progress.read_text(encoding="utf-8"))["completed_pages"] == 0
    assert list((tmp_path / ".ocr-parts").glob("*.pdf")) == []


def test_ocr_resume_lock_contention_fails_closed(tmp_path: Path):
    capability = _load_ocr_resume()
    source = tmp_path / "source.pdf"
    output = tmp_path / "ocr.pdf"
    progress = tmp_path / "ocr.progress.json"
    _write_pdf(source, ["1"])
    import fcntl

    lock = progress.with_suffix(progress.suffix + ".lock")
    lock.touch()
    with lock.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="locked"):
            capability.run_ocr_step(
                source, output, progress, "tesseract", 1, None,
                runner=lambda *_args: pytest.fail("contended engine must not run"),
            )


def test_ocr_resume_cli_requires_closed_resume_arguments(
    capsys: pytest.CaptureFixture[str], forbid_engine_launch
):
    rc = extract_cli._run_ocr(
        EXTRACT_DIR,
        ["in.pdf", "out.pdf", "--resume", "--no-clobber", "--json"],
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["failure"]["code"] == "invalid_arguments"
    assert "--progress-file" in payload["failure"]["message"]


def _ocr_generation_runner(calls: list[tuple[int, tuple[str, ...]]]):
    def run(
        source: Path,
        output: Path,
        engines: tuple[str, ...],
        language: str,
        _validation_policy: str,
    ) -> ocr_generation.EngineResult:
        import fitz

        assert language == "chi_sim+eng"
        with fitz.open(source) as sliced:
            count = sliced.page_count
        calls.append((count, engines))
        _write_pdf(output, [f"recovered page {index}" for index in range(1, count + 1)])
        if engines[0] == "mineru":
            with fitz.open(output) as document:
                ocr_generation.ocr_quality.stamp(document, source_sha256=ocr_generation.sha256_file(source), quality=ocr_generation.ocr_quality.empty_quality(), model=ocr_generation.ocr_quality.MODEL)
                document.saveIncr()
        return ocr_generation.EngineResult(engine=engines[0], returncode=0)

    return run


@pytest.mark.parametrize(
    ("kind", "root"),
    [("paper", "processing/papers"), ("book", "processing/chapters")],
)
def test_ocr_generation_key_and_paths_are_material_safe(kind, root, tmp_path):
    kwargs = {
        "kind": kind,
        "slug": "exact-material",
        "source_path": "sources/exact-material.pdf",
        "source_sha256": "a" * 64,
        "profile_name": "mineru-text",
    }
    first = ocr_generation.generation_key(**kwargs)
    same = ocr_generation.generation_key(**kwargs)
    changed = ocr_generation.generation_key(
        **{**kwargs, "source_sha256": "b" * 64}
    )

    assert first == same
    assert len(first) == 64
    assert first != changed
    paths = ocr_generation.paths_for(
        project_root=tmp_path, kind=kind, slug="exact-material", generation=first
    )
    assert paths["generation_dir"].relative_to(tmp_path).as_posix() == (
        f"{root}/exact-material/ocr-generations/{first}"
    )


def test_ocr_generation_profiles_bind_engine_specific_range_sizes():
    assert ocr_generation.resolve_profile("paper", "mineru-text")["chunk_pages"] == 16
    assert ocr_generation.resolve_profile("book", "mineru-text")["chunk_pages"] == 16
    assert ocr_generation.resolve_profile("paper", "tesseract-text")["chunk_pages"] == 32
    assert ocr_generation.resolve_profile("book", "tesseract-text")["chunk_pages"] == 32


def test_ocr_generation_mineru_quality_failure_never_falls_back(tmp_path, monkeypatch):
    source, output = tmp_path / "slice.pdf", tmp_path / "candidate.pdf"
    _write_pdf(source, ["", ""])
    calls = []
    def fake_call(command, **kwargs):
        calls.append(command)
        _write_pdf(Path(command[3]), ["Only page one", ""])
        return 0
    monkeypatch.setattr(ocr_generation.subprocess, "call", fake_call)
    result = ocr_generation._engine_runner(EXTRACT_DIR)(source, output, ("mineru",), "chi_sim+eng", "paper-text-v1")
    assert result.returncode != 0 and len(calls) == 1
    assert calls[0][1].endswith("ocr_mineru.py")
    assert not output.exists()


@pytest.mark.parametrize(
    ("kind", "profile_name", "pages", "first_range"),
    [("paper", "mineru-text", 17, 16), ("book", "tesseract-text", 33, 32)],
)
def test_ocr_generation_advances_one_range_then_commits_manifest_last(
    tmp_path: Path, kind: str, profile_name: str, pages: int, first_range: int,
):
    slug = "example-paper-2024"
    source = tmp_path / "sources" / f"{slug}.pdf"
    source.parent.mkdir()
    _write_pdf(source, ["" for _ in range(pages)])
    source_sha = ocr_generation.sha256_file(source)
    generation = ocr_generation.generation_key(
        kind=kind, slug=slug, source_path=f"sources/{slug}.pdf",
        source_sha256=source_sha, profile_name=profile_name,
    )
    calls: list[tuple[int, tuple[str, ...]]] = []

    first = ocr_generation.run_transaction(
        project_root=tmp_path,
        kind=kind,
        slug=slug,
        source_file=source,
        expected_source_sha256=source_sha,
        expected_generation_key=generation,
        profile_name=profile_name,
        runner=_ocr_generation_runner(calls),
    )
    second = ocr_generation.run_transaction(
        project_root=tmp_path,
        kind=kind,
        slug=slug,
        source_file=source,
        expected_source_sha256=source_sha,
        expected_generation_key=generation,
        profile_name=profile_name,
        runner=_ocr_generation_runner(calls),
    )

    assert first["status"] == "succeeded"
    assert first["disposition"] == "partial"
    assert first["progress"] == {
        "completed_pages": first_range,
        "total_pages": pages,
        "next_page": first_range + 1,
        "ranges": first["progress"]["ranges"],
    }
    assert second["status"] == "succeeded"
    assert second["disposition"] == "created"
    assert second["state"] == "committed"
    assert second["progress"] is None
    expected_engines = ("mineru",) if profile_name == "mineru-text" else ("tesseract",)
    assert calls == [(first_range, expected_engines), (pages - first_range, expected_engines)]
    paths = ocr_generation.paths_for(
        project_root=tmp_path, kind=kind, slug=slug, generation=generation
    )
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["schema_version"] == (ocr_generation.MINERU_MANIFEST_SCHEMA if profile_name == "mineru-text" else ocr_generation.MANIFEST_SCHEMA)
    assert manifest["kind"] == kind
    assert manifest["source"]["pages"] == pages
    assert manifest["recovery_pdf"]["pages"] == pages
    assert [item["engine"] for item in manifest["ranges"]] == [expected_engines[0]] * 2
    observed = ocr_generation.observe_generation(
        project_root=tmp_path,
        kind=kind,
        slug=slug,
        source_sha256=source_sha,
        source_size=source.stat().st_size,
        source_pages=pages,
        generation=generation,
        profile_name=profile_name,
    )
    assert observed["state"] == "committed"


def test_ocr_generation_rejects_a_tampered_committed_range(tmp_path: Path):
    slug = "tampered-paper-2024"
    source = tmp_path / "sources" / f"{slug}.pdf"
    source.parent.mkdir()
    _write_pdf(source, ["" for _ in range(17)])
    source_sha = ocr_generation.sha256_file(source)
    generation = ocr_generation.generation_key(
        kind="paper",
        slug=slug,
        source_sha256=source_sha,
        profile_name="mineru-text",
    )
    partial = ocr_generation.run_transaction(
        project_root=tmp_path,
        kind="paper",
        slug=slug,
        source_file=source,
        expected_source_sha256=source_sha,
        expected_generation_key=generation,
        profile_name="mineru-text",
        runner=_ocr_generation_runner([]),
    )
    part = tmp_path / partial["progress"]["ranges"][0]["path"]
    part.write_bytes(b"tampered")

    observed = ocr_generation.observe_generation(
        project_root=tmp_path,
        kind="paper",
        slug=slug,
        source_sha256=source_sha,
        source_size=source.stat().st_size,
        source_pages=17,
        generation=generation,
        profile_name="mineru-text",
    )

    assert observed["state"] == "invalid"
    assert observed["failure"] == "ocr.generation_progress_invalid"


def test_ocr_generation_stops_on_unknown_private_part_inventory(tmp_path: Path):
    slug = "unknown-parts-paper-2024"
    source = tmp_path / "sources" / f"{slug}.pdf"
    source.parent.mkdir()
    _write_pdf(source, ["" for _ in range(17)])
    source_sha = ocr_generation.sha256_file(source)
    generation = ocr_generation.generation_key(
        kind="paper",
        slug=slug,
        source_sha256=source_sha,
        profile_name="mineru-text",
    )
    partial = ocr_generation.run_transaction(
        project_root=tmp_path,
        kind="paper",
        slug=slug,
        source_file=source,
        expected_source_sha256=source_sha,
        expected_generation_key=generation,
        profile_name="mineru-text",
        runner=_ocr_generation_runner([]),
    )
    parts = (tmp_path / partial["paths"]["work_dir"] / "parts")
    (parts / "unexpected.pdf").write_bytes(b"unknown")

    observed = ocr_generation.observe_generation(
        project_root=tmp_path,
        kind="paper",
        slug=slug,
        source_sha256=source_sha,
        source_size=source.stat().st_size,
        source_pages=17,
        generation=generation,
        profile_name="mineru-text",
    )

    assert observed["state"] == "unknown"
    assert observed["failure"] == "ocr.generation_part_inventory_unknown"


def test_ocr_generation_rejects_tampered_committed_manifest_ranges(tmp_path: Path):
    slug = "tampered-manifest-paper-2024"
    source = tmp_path / "sources" / f"{slug}.pdf"
    source.parent.mkdir()
    _write_pdf(source, [""])
    source_sha = ocr_generation.sha256_file(source)
    generation = ocr_generation.generation_key(
        kind="paper",
        slug=slug,
        source_sha256=source_sha,
        profile_name="mineru-text",
    )
    created = ocr_generation.run_transaction(
        project_root=tmp_path,
        kind="paper",
        slug=slug,
        source_file=source,
        expected_source_sha256=source_sha,
        expected_generation_key=generation,
        profile_name="mineru-text",
        runner=_ocr_generation_runner([]),
    )
    assert created["disposition"] == "created"
    paths = ocr_generation.paths_for(
        project_root=tmp_path, kind="paper", slug=slug, generation=generation
    )
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["ranges"][0]["path"] = "processing/papers/foreign/part.pdf"
    paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    observed = ocr_generation.observe_generation(
        project_root=tmp_path,
        kind="paper",
        slug=slug,
        source_sha256=source_sha,
        source_size=source.stat().st_size,
        source_pages=1,
        generation=generation,
        profile_name="mineru-text",
    )

    assert observed["state"] == "invalid"
    assert observed["failure"] == "ocr.generation_manifest_invalid"


def test_ocr_generation_reconciles_without_rewriting_or_touching_legacy(tmp_path: Path):
    slug = "legacy-paper-2020"
    source = tmp_path / "sources" / f"{slug}.pdf"
    source.parent.mkdir()
    _write_pdf(source, [""])
    paper_dir = tmp_path / "processing" / "papers" / slug
    paper_dir.mkdir(parents=True)
    legacy_pdf = paper_dir / "ocr.pdf"
    legacy_text = paper_dir / "ocr.txt"
    legacy_pdf.write_bytes(b"protected legacy PDF evidence")
    legacy_text.write_text("protected legacy text evidence", encoding="utf-8")
    legacy = (legacy_pdf.read_bytes(), legacy_text.read_bytes())
    source_sha = ocr_generation.sha256_file(source)
    generation = ocr_generation.generation_key(
        kind="paper", slug=slug, source_path=f"sources/{slug}.pdf",
        source_sha256=source_sha, profile_name="mineru-text",
    )

    created = ocr_generation.run_transaction(
        project_root=tmp_path,
        kind="paper",
        slug=slug,
        source_file=source,
        expected_source_sha256=source_sha,
        expected_generation_key=generation,
        profile_name="mineru-text",
        runner=_ocr_generation_runner([]),
    )
    paths = ocr_generation.paths_for(
        project_root=tmp_path, kind="paper", slug=slug, generation=generation
    )
    mtimes = {
        key: paths[key].stat().st_mtime_ns for key in ("pdf", "text", "manifest")
    }
    reconciled = ocr_generation.run_transaction(
        project_root=tmp_path,
        kind="paper",
        slug=slug,
        source_file=source,
        expected_source_sha256=source_sha,
        expected_generation_key=generation,
        profile_name="mineru-text",
        runner=lambda *_args: pytest.fail("committed generation must not rerun OCR"),
    )

    assert created["disposition"] == "created"
    assert reconciled["disposition"] == "reconciled"
    assert {
        key: paths[key].stat().st_mtime_ns for key in ("pdf", "text", "manifest")
    } == mtimes
    assert (legacy_pdf.read_bytes(), legacy_text.read_bytes()) == legacy


def test_ocr_generation_rejects_empty_text_page_without_publication(tmp_path: Path):
    slug = "empty-middle-page-2021"
    source = tmp_path / "sources" / f"{slug}.pdf"
    source.parent.mkdir()
    _write_pdf(source, ["", "", ""])
    source_sha = ocr_generation.sha256_file(source)
    generation = ocr_generation.generation_key(
        kind="paper", slug=slug, source_path=f"sources/{slug}.pdf",
        source_sha256=source_sha, profile_name="mineru-text",
    )

    def incomplete_runner(
        _source: Path, output: Path, _engines: tuple[str, ...],
        _language: str, _policy: str,
    ) -> ocr_generation.EngineResult:
        _write_pdf(output, ["page one", "", "page three"])
        return ocr_generation.EngineResult(engine="mineru", returncode=0)

    result = ocr_generation.run_transaction(
        project_root=tmp_path,
        kind="paper",
        slug=slug,
        source_file=source,
        expected_source_sha256=source_sha,
        expected_generation_key=generation,
        profile_name="mineru-text",
        runner=incomplete_runner,
    )
    paths = ocr_generation.paths_for(
        project_root=tmp_path, kind="paper", slug=slug, generation=generation
    )

    assert result["status"] == "failed"
    assert result["failure"]["code"] == "ocr.generation_empty_text_pages"
    assert paths["generation_dir"].exists() is False


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext unavailable")
def test_text_extract_writes_utf8_and_machine_signals(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    output = tmp_path / "nested" / "paper.txt"
    _write_pdf(source, ["Making sense of conduct", "Café, agency, and culture"])

    result = run_extract("text", str(source), str(output), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    text = output.read_text(encoding="utf-8")
    assert payload["status"] == "ok"
    assert payload["input"] == str(source)
    assert payload["output"] == str(output)
    assert payload["exists"] is True
    assert payload["chars"] == len(text)
    assert payload["text_pages"] == 2
    assert "Making sense of conduct" in text
    assert "Café, agency, and culture" in text


def test_text_extract_normalizes_utf8_text_input_without_pdftotext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    import extract_text

    source = tmp_path / "article.txt"
    output = tmp_path / "normalized" / "source.txt"
    source.write_bytes("Title\r\nAbstract\rBody".encode("utf-8"))
    monkeypatch.setattr(
        extract_text.shutil,
        "which",
        lambda _name: pytest.fail("text input must not invoke pdftotext"),
    )

    rc = extract_text.extract_text(str(source), str(output), as_json=True)

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert output.read_bytes() == "Title\nAbstract\nBody\n".encode("utf-8")
    assert payload["status"] == "ok"
    assert payload["chars"] == len("Title\nAbstract\nBody\n")


def test_text_extract_invalid_utf8_never_replaces_existing_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    import extract_text

    source = tmp_path / "article.txt"
    output = tmp_path / "source.txt"
    source.write_bytes(b"\xff\xfe")
    output.write_text("existing\n", encoding="utf-8")

    rc = extract_text.extract_text(str(source), str(output), as_json=True)

    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["failure"]["code"] == "output_write_failed"
    assert output.read_text(encoding="utf-8") == "existing\n"


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






@pytest.mark.parametrize('engine_rc', [0, 4])
def test_layout_never_falls_back_or_publishes_unproven_output(tmp_path, monkeypatch, capsys, engine_rc):
    source, output = tmp_path / 'source.pdf', tmp_path / 'reocr.pdf'
    _write_pdf(source, ['original source'])
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        _write_pdf(Path(command[3]), ['unproven per-line output'])
        return engine_rc

    monkeypatch.setattr(extract_cli.subprocess, 'call', run)
    rc = extract_cli._run_ocr(EXTRACT_DIR, [str(source), str(output), '--layout', '--no-clobber', '--json'])
    assert rc != 0 and len(calls) == 1
    assert not output.exists()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['failure']['code'] == ('layout_failed' if engine_rc else 'layout_unproven')


def test_layout_rejects_tesseract_without_starting_engine(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(extract_cli.subprocess, 'call', lambda *a, **k: pytest.fail('must not start'))
    rc = extract_cli._run_ocr(EXTRACT_DIR, ['source.pdf', 'out.pdf', '--layout', '--engine=tesseract', '--json'])
    assert rc != 0
    assert 'paragraph placement' in json.loads(capsys.readouterr().out)['failure']['message']


def test_layout_born_digital_output_is_preserved_and_reuse_is_source_bound(tmp_path):
    source = tmp_path / 'source.pdf'
    output = tmp_path / 'processing' / 'translations' / 'book-zh-reocr.pdf'
    _write_pdf(source, ['Born digital unchanged'])
    result = run_extract('ocr', str(source), str(output), '--layout', '--no-clobber', '--json')
    assert result.returncode == 0, result.stderr
    before = output.read_bytes()
    reused = run_extract('ocr', str(source), str(output), '--layout', '--no-clobber', '--json')
    assert json.loads(reused.stdout)['status'] == 'existing'
    with ocr_mineru.fitz.open(output) as doc:
        assert 'Born digital unchanged' in doc[0].get_text()
    _write_pdf(source, ['Different source'])
    stale = run_extract('ocr', str(source), str(output), '--layout', '--no-clobber', '--json')
    assert stale.returncode != 0 and output.read_bytes() == before
    assert json.loads(stale.stdout)['failure']['code'] == 'layout_unproven'








def test_pick_font_avoids_embedding_for_latin_text():
    # Latin text needs no external font, even when a candidate font is unavailable.
    assert ocr_mineru.pick_font(["plain ascii"], "/missing/font.ttf") == (
        "helv", None, ["plain ascii"],
    )
    with pytest.raises(ValueError, match="Unicode font"):
        ocr_mineru.pick_font(["文化与能动性"], "/missing/font.ttf")


def test_pick_font_straightens_quotes_instead_of_embedding():
    """insert_text() encodes base-14 as Latin-1 and turns anything else into `·`.

    Font.has_glyph says otherwise, so it cannot be the test — every English book
    has curly quotes, and trusting it silently corrupted the whole text layer.
    """
    name, fontfile, texts = ocr_mineru.pick_font(['we mean “the same” — really'], "/x.ttf")

    assert (name, fontfile) == ("helv", None)
    assert texts == ['we mean "the same" - really']
    texts[0].encode("latin-1")  # what insert_text will actually do




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

    ocr_mineru.strip_text(page)

    assert "old scanner text layer" not in doc.reload_page(page).get_text()
    doc.close()
    inner.close()












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


def test_book_manual_json_commits_full_manifest(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["first body " * 20, "second body " * 20])

    result = _run_manual(pdf, output, 2)

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 1
    assert "Created:" not in result.stdout
    assert "Created:" in result.stderr
    receipt = json.loads(result.stdout)
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
    "arguments",
    [
        ["--pages", "1-1", "--title", "X", "--slot", "missing"],
        ["--pages", "2-1", "--title", "X", "--slot", "01"],
        ["--pages", "1-999", "--title", "X", "--slot", "01"],
    ],
)
def test_book_repair_rejects_unknown_slot_and_invalid_range(
    tmp_path: Path, arguments: list[str]
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


def test_book_identical_rerun_rejects_unpaired_page_range(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20])
    first = _run_manual(pdf, output, 1)
    assert first.returncode == 0
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["chapters"][0]["end_page"] = None
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_before = manifest_path.read_bytes()
    chapter_path = next(output.glob("*.txt"))
    chapter_before = chapter_path.read_bytes()

    second = _run_manual(pdf, output, 1)

    receipt = json.loads(second.stdout)
    assert second.returncode == 1
    assert receipt["status"] == "blocked"
    assert receipt["failure"]["code"] == "manifest_page_range_invalid"
    assert receipt["previous_manifest_preserved"] is True
    assert manifest_path.read_bytes() == manifest_before
    assert chapter_path.read_bytes() == chapter_before


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
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        manifest_before
    ).hexdigest()
    assert receipt["previous_manifest_preserved"] is True
    assert (output / "manifest.json").read_bytes() == manifest_before
    assert (output / row["filename"]).read_bytes() == chapter_before
    assert (output / "01_Renamed.txt").exists() is False


def test_book_invalid_private_stage_is_failed_known_without_final_writes(
    tmp_path: Path,
):
    pdf = tmp_path / "book.pdf"
    output = tmp_path / "chapters"
    _book_pdf(pdf, ["one " * 20])

    def build(stage: Path, _previous: dict | None) -> dict:
        (stage / "09_Contents.txt").write_text("contents chapter", encoding="utf-8")
        (stage / "09_Body.txt").write_text("body chapter", encoding="utf-8")
        return {
            "chapters": [
                {
                    "slot": "09",
                    "title": "Chapter 9 (Contents)",
                    "filename": "09_Contents.txt",
                    "start_page": 1,
                    "end_page": 1,
                },
                {
                    "slot": "09",
                    "title": "Chapter 9",
                    "filename": "09_Body.txt",
                    "start_page": 1,
                    "end_page": 1,
                },
            ],
            "skipped": [],
        }

    rc, receipt = chapter_commit.commit_chapter_set(
        input_path=pdf,
        output_dir=output,
        mode="pattern",
        options={"pattern": "default"},
        max_chapters=50,
        build_stage=build,
    )

    assert rc == 1
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "manifest_invalid"
    assert receipt["failure"]["outcome"] == "known"
    assert receipt["manifest_exists"] is False
    assert receipt["manifest_fingerprint"] is None
    assert output.exists() is False
    assert list(tmp_path.glob(".chapters.stage-*")) == []


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
    assert receipt["request_fingerprint"] is None
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        manifest_before
    ).hexdigest()
    assert (output / "manifest.json").read_bytes() == manifest_before


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


def _migration_request(tmp_path, *, pages=1, profile='mineru-text'):
    slug = 'migration-book'
    source = tmp_path / 'sources' / f'{slug}.pdf'
    source.parent.mkdir(exist_ok=True)
    _write_pdf(source, ['source page' for _ in range(pages)])
    sha = ocr_generation.sha256_file(source)
    generation = ocr_generation.generation_key(kind='book', slug=slug, source_sha256=sha, profile_name=profile)
    return dict(project_root=tmp_path, kind='book', slug=slug, source_file=source,
                expected_source_sha256=sha, expected_generation_key=generation, profile_name=profile)


def test_retired_ds_generation_reconciles_but_never_starts_a_writer(tmp_path):
    args = _migration_request(tmp_path, profile='dsocr2-text')
    never = lambda *_: pytest.fail('retired DS OCR2 must never execute')
    result = ocr_generation.run_transaction(**args, runner=never)
    assert result['status'] == 'blocked'
    assert result['failure']['code'] == 'ocr.generation_profile_retired'
    paths = ocr_generation.paths_for(project_root=tmp_path, kind='book', slug=args['slug'], generation=args['expected_generation_key'])
    assert not paths['progress'].exists()
    # Construct the original schema-0.1 committed artifacts, without old execution.
    paths['work_dir'].mkdir(parents=True, exist_ok=True)
    _write_pdf(paths['work_pdf'], ['retained historical recognition'])
    signals = ocr_generation.text_signals(paths['work_pdf'])
    paths['work_text'].write_text(signals['text'])
    record = dict(start_page=1, end_page=1, engine='dsocr2', pages=1, sha256='b'*64,
                  path=ocr_generation.project_relative(paths['work_dir'] / 'parts/part-000001-000001.dsocr2.pdf', tmp_path))
    manifest = ocr_generation._build_manifest(paths=paths, kind='book', slug=args['slug'],
        generation=args['expected_generation_key'], profile=ocr_generation.resolve_profile('book','dsocr2-text'),
        ranges=[record], source_sha256=args['expected_source_sha256'], source_size=args['source_file'].stat().st_size,
        source_pages=1, signals=signals)
    assert manifest['schema_version'] == 'quasi.ocr.generation.manifest/0.1' and 'quality' not in manifest
    ocr_generation._publish(paths=paths, manifest=manifest)
    before = {key: paths[key].read_bytes() for key in ['pdf','text','manifest']}
    result = ocr_generation.run_transaction(**args, runner=never)
    assert result['disposition'] == 'reconciled'
    assert before == {key: paths[key].read_bytes() for key in before}


@pytest.mark.parametrize('wrong_source', [False, True])
def test_mineru_orphan_requires_exact_source_evidence_without_replay(tmp_path, wrong_source):
    args = _migration_request(tmp_path, pages=17)
    result = ocr_generation.run_transaction(**args, runner=_ocr_generation_runner([]))
    paths = ocr_generation.paths_for(project_root=tmp_path, kind='book', slug=args['slug'], generation=args['expected_generation_key'])
    progress = json.loads(paths['progress'].read_text())
    # Simulate publication of the next part followed by a crash before progress.
    sliced = tmp_path / 'slice.pdf'
    ocr_generation._slice_pdf(args['source_file'], sliced, 17, 17)
    if wrong_source:
        _write_pdf(sliced, ['unrelated source'])
    orphan = paths['work_dir'] / 'parts/part-000017-000017.mineru.pdf'
    _ocr_generation_runner([])(sliced, orphan, ('mineru',), 'chi_sim+eng', 'book-pdf-v1')
    result = ocr_generation.run_transaction(**args, runner=lambda *_: pytest.fail('never replay orphan writer'))
    if wrong_source:
        assert result['failure']['code'] == 'ocr.generation_orphan_invalid'
        assert json.loads(paths['progress'].read_text()) == progress
        assert not paths['manifest'].exists()
    else:
        assert result['disposition'] == 'created'
        assert json.loads(paths['manifest'].read_text())['quality']['suspects'] == []


@pytest.mark.parametrize('field,value', [('model','foreign-model'), ('profile','foreign-profile')])
def test_mineru_invalid_quality_stops_before_advancing_another_range(tmp_path, field, value):
    import fitz
    args = _migration_request(tmp_path, pages=17)
    result = ocr_generation.run_transaction(**args, runner=_ocr_generation_runner([]))
    part = tmp_path / result['progress']['ranges'][0]['path']
    with fitz.open(part) as doc:
        evidence = ocr_generation.ocr_quality.read(doc)
        evidence[field] = value
        doc.xref_set_key(doc.pdf_catalog(), 'QuasiOCR', fitz.get_pdf_str(json.dumps(evidence)))
        doc.saveIncr()
    paths = ocr_generation.paths_for(project_root=tmp_path, kind='book', slug=args['slug'], generation=args['expected_generation_key'])
    progress = json.loads(paths['progress'].read_text())
    progress['ranges'][0]['sha256'] = ocr_generation.sha256_file(part)
    paths['progress'].write_text(json.dumps(progress))
    result = ocr_generation.run_transaction(**args, runner=lambda *_: pytest.fail('invalid evidence must stop before model work'))
    assert result['failure']['code'] == 'ocr.generation_progress_invalid'


def test_resume_defaults_to_exact_saved_tesseract_engine(tmp_path, monkeypatch, capsys):
    source = tmp_path / 'source.pdf'; output = tmp_path / 'out.pdf'; progress = tmp_path / 'progress.json'
    _write_pdf(source, ['source'])
    # Full identity validation belongs to run_ocr_step; prove the CLI forwards the saved engine.
    progress.write_text(json.dumps({'engine':'tesseract'}))
    import ocr_resume
    def step(_source, _output, _progress, engine, *args, **kwargs):
        assert engine == 'tesseract'
        return {'status':'existing','input':str(source),'output':str(output),'progress':None}
    monkeypatch.setattr(ocr_resume, 'run_ocr_step', step)
    assert extract_cli._run_ocr(EXTRACT_DIR, [str(source),str(output),'--resume','--progress-file',str(progress),'--chunk-pages','8','--no-clobber','--json']) == 0

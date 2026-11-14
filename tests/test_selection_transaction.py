"""Selection postprocessing stays inside the guarded translation transaction."""
from pathlib import Path

import pymupdf
import pytest

from test_translate_cli import commit, coverage, make_pdf, run_kwargs, source_fixture


@pytest.mark.parametrize("backend", ["pdf2zh", "immersive"])
def test_selection_preflight_failure_never_starts_provider(tmp_path, backend):
    source, source_sha = source_fixture(tmp_path)
    calls = []

    def fail_preflight(source, recognition, staging):
        calls.append("selection")
        raise ValueError("source-bound line evidence missing")

    def provider(*args):
        calls.append("provider")
        raise AssertionError("paid provider must not start")

    kwargs = run_kwargs(tmp_path, source, source_sha, provider, backend=backend)
    kwargs.update(prepare_selection=fail_preflight,
                  apply_selection=lambda *_: pytest.fail("no candidate exists"))
    receipt = commit.run_transaction(**kwargs)
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "translation.selection_prepare_failed"
    assert calls == ["selection"]
    assert not (tmp_path / receipt["output_path"]).exists()
    assert not (tmp_path / receipt["manifest_path"]).exists()


@pytest.mark.parametrize("backend", ["pdf2zh", "immersive"])
def test_provider_receives_paragraph_source_then_graft_precedes_validation(tmp_path, backend):
    source, source_sha = source_fixture(tmp_path)
    events = []
    staged = tmp_path / "aligned-source.pdf"

    def prepare(input_pdf, recognition, staging):
        assert input_pdf == source
        assert recognition.name == "strict-translation-zh-recognition.json"
        events.append("prepare")
        return make_pdf(staged, 4)

    def provider(input_pdf, candidate, language, work_dir, on_state):
        assert input_pdf == source and input_pdf != staged
        events.append("provider")
        coverage.build_dual(candidate, ["行动的形状是什么样的 " * 12] * 4)
        return {"task_id": None}

    def apply(candidate, selection_source):
        assert selection_source == staged
        events.append("apply")
        with pymupdf.open(candidate) as doc:
            doc.set_metadata({**doc.metadata, "subject": "selection applied"})
            doc.saveIncr()

    def toc(**kwargs):
        events.append("toc")
        return 0

    def repair(candidate):
        events.append("repair")
        with pymupdf.open(candidate) as doc:
            assert doc.metadata["subject"] == "selection applied"
        return {}

    def check(candidate, *, target_language):
        events.append("coverage")
        with pymupdf.open(candidate) as doc:
            assert doc.metadata["subject"] == "selection applied"
        return coverage.check(candidate, target_language=target_language)

    kwargs = run_kwargs(tmp_path, source, source_sha, provider, backend=backend)
    kwargs.update(prepare_selection=prepare, apply_selection=apply, add_toc=toc,
                  repair_tounicode=repair, check_coverage=check)
    receipt = commit.run_transaction(**kwargs)
    assert receipt["status"] == "succeeded"
    assert receipt["canonical_committed"]
    assert events == ["prepare", "provider", "apply", "toc", "repair", "coverage"]
    assert (tmp_path / receipt["output_path"]).is_file()


def test_failed_selection_graft_never_publishes_candidate(tmp_path):
    source, source_sha = source_fixture(tmp_path)
    staged = make_pdf(tmp_path / "aligned-source.pdf", 4)
    calls = []

    def provider(input_pdf, candidate, language, work_dir, on_state):
        calls.append("provider")
        coverage.build_dual(candidate, ["行动的形状是什么样的 " * 12] * 4)
        return {"task_id": None}

    def fail_graft(candidate, selection_source):
        calls.append("apply")
        raise ValueError("original image or source text did not match")

    kwargs = run_kwargs(tmp_path, source, source_sha, provider)
    kwargs.update(prepare_selection=lambda *_: staged, apply_selection=fail_graft,
                  check_coverage=lambda *a, **k: pytest.fail("coverage must follow successful graft"))
    receipt = commit.run_transaction(**kwargs)
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "translation.postcondition_failed"
    assert calls == ["provider", "apply"]
    assert not (tmp_path / receipt["output_path"]).exists()
    assert not (tmp_path / receipt["manifest_path"]).exists()


def test_selection_source_mutation_during_provider_blocks_graft_and_publish(tmp_path):
    source, source_sha = source_fixture(tmp_path)
    staged = make_pdf(tmp_path / "aligned-source.pdf", 4)
    calls = []

    def provider(input_pdf, candidate, language, work_dir, on_state):
        calls.append("provider")
        coverage.build_dual(candidate, ["行动的形状是什么样的 " * 12] * 4)
        staged.write_bytes(b"changed while provider was running")
        return {"task_id": None}

    kwargs = run_kwargs(tmp_path, source, source_sha, provider)
    kwargs.update(prepare_selection=lambda *_: staged,
                  apply_selection=lambda *_: pytest.fail("changed selection must not be grafted"))
    receipt = commit.run_transaction(**kwargs)
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "translation.selection_source_changed"
    assert calls == ["provider"]
    assert not (tmp_path / receipt["output_path"]).exists()
    assert not (tmp_path / receipt["manifest_path"]).exists()


def test_native_source_skips_graft_without_changing_backend_input(tmp_path):
    source, source_sha = source_fixture(tmp_path)
    calls = []

    def provider(input_pdf, candidate, language, work_dir, on_state):
        assert input_pdf == source
        calls.append("provider")
        coverage.build_dual(candidate, ["行动的形状是什么样的 " * 12] * 4)
        return {"task_id": None}

    kwargs = run_kwargs(tmp_path, source, source_sha, provider)
    kwargs.update(prepare_selection=lambda *_: None,
                  apply_selection=lambda *_: pytest.fail("native PDF needs no graft"))
    receipt = commit.run_transaction(**kwargs)
    assert receipt["status"] == "succeeded"
    assert calls == ["provider"]


@pytest.mark.parametrize(("suffix", "expected_sidecar"), [
    ("-zh-reocr.pdf", "-zh-recognition.json"),
    ("-zh-selection-reocr.pdf", "-zh-selection-recognition.json"),
])
def test_recovery_roles_use_their_own_sidecars_without_overwriting_prior_data(
    tmp_path, suffix, expected_sidecar
):
    directory = tmp_path / "processing" / "translations"
    slug = "strict-translation"
    historical = make_pdf(directory / f"{slug}-zh-reocr.pdf", 4)
    fresh = make_pdf(directory / f"{slug}-zh-selection-reocr.pdf", 4)
    historical_sidecar = directory / f"{slug}-zh-recognition.json"
    historical_sidecar.write_text("preserve historical evidence")
    expected_bytes = {path: path.read_bytes() for path in (historical, fresh, historical_sidecar)}
    source = directory / f"{slug}{suffix}"
    seen = []

    def prepare(input_pdf, recognition, staging):
        seen.append((input_pdf, recognition))
        raise ValueError("invalid source-bound recognition")

    def provider(*args):
        pytest.fail("no provider may start without verified recognition")

    kwargs = run_kwargs(tmp_path, source, commit.sha256_file(source), provider)
    kwargs.update(prepare_selection=prepare, apply_selection=lambda *_: None)
    result = commit.run_transaction(**kwargs)
    assert result["failure"]["code"] == "translation.selection_prepare_failed"
    assert seen == [(source, directory / f"{slug}{expected_sidecar}")]
    if suffix == "-zh-reocr.pdf":
        assert f"{slug}-zh-selection-reocr.pdf" in result["failure"]["message"]
        assert f"{slug}-zh-selection-recognition.json" in result["failure"]["message"]
        assert "--no-clobber" in result["failure"]["message"]
    for path, content in expected_bytes.items():
        assert path.read_bytes() == content
    assert not (tmp_path / result["output_path"]).exists()


@pytest.mark.parametrize("name", [
    "strict-translation-zh-other-reocr.pdf",
    "different-translation-zh-selection-reocr.pdf",
    "strict-translation-en-selection-reocr.pdf",
])
def test_similar_but_wrong_recovery_paths_are_rejected(tmp_path, name):
    path = make_pdf(tmp_path / "processing" / "translations" / name, 1)
    with pytest.raises(commit.TranslateContractError, match="exact canonical or recovery role"):
        commit.validate_project_source(path, tmp_path, slug="strict-translation", target_language="zh")

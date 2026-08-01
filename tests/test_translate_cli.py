"""Strict translation CLI/transaction tests; no provider is contacted."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pymupdf
import pytest
import requests

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from translate import coverage, immersive_translate as immersive  # noqa: E402
from translate import translate as translate_cli  # noqa: E402
from translate import translate_commit as commit  # noqa: E402


FULL = "行动的形状是什么样的 " * 12
def make_pdf(path: Path, pages: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    for _ in range(pages):
        document.new_page()
    document.save(str(path))
    document.close()
    return path


def source_fixture(
    root: Path,
    *,
    slug: str = "strict-translation",
    pages: int = 4,
    recovery: bool = False,
) -> tuple[Path, str]:
    if recovery:
        source = root / "processing" / "translations" / f"{slug}-zh-cn-reocr.pdf"
    else:
        source = root / "sources" / f"{slug}.pdf"
    make_pdf(source, pages)
    return source, commit.sha256_file(source)


def passing_runner(calls: list[str], *, pages: int = 4):
    def run(source, candidate, language, work_dir, on_state):
        calls.append(str(candidate))
        on_state("backend_running", None)
        coverage.build_dual(candidate, [FULL] * pages)
        return {"task_id": None}

    return run


def run_kwargs(
    root: Path,
    source: Path,
    source_sha: str,
    backend_runner,
    *,
    backend: str = "pdf2zh",
    attempt: int = 1,
    config_fingerprint: str | None = None,
):
    return {
        "project_root": root,
        "slug": "strict-translation",
        "backend": backend,
        "target_language": "zh-CN",
        "source_file": source,
        "expected_source_sha256": source_sha,
        "toc_json": None,
        "toc_page_side": "original",
        "attempt": attempt,
        "config_fingerprint": config_fingerprint
        or commit.fingerprint({"backend": backend, "model": "test"}),
        "backend_runner": backend_runner,
        "add_toc": lambda **kwargs: 0,
        "repair_tounicode": lambda path: {},
        "check_coverage": coverage.check,
    }


def observe_kwargs(
    root: Path,
    *,
    source: Path | None,
    mode: str = "initial",
    configuration_missing: list[str] | None = None,
):
    return {
        "project_root": root,
        "slug": "strict-translation",
        "backend": "pdf2zh",
        "target_language": "zh-CN",
        "source_file": source,
        "toc_json": None,
        "toc_page_side": "original",
        "config_fingerprint": commit.fingerprint({"backend": "pdf2zh", "model": "test"}),
        "configuration_missing": configuration_missing or [],
        "mode": mode,
    }


def test_strict_observe_cli_emits_one_closed_relative_receipt(tmp_path):
    source, _ = source_fixture(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "QUASI_TRANSLATE_BACKEND": "immersive",
            "QUASI_IMMERSIVE_AUTH_KEY": "configured-not-used",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "scripts" / "translate" / "translate.py"),
            "observe",
            "strict-translation",
            "--source-file",
            str(source),
            "--target-language",
            "zh-CN",
            "--mode",
            "initial",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    assert receipt["status"] == "succeeded"
    assert receipt["signal"] == "missing"
    assert receipt["generation_attempt"] == 1
    assert receipt["source_path"] == "sources/strict-translation.pdf"
    assert receipt["output_path"] == "processing/translations/strict-translation-zh-cn.pdf"
    assert receipt["manifest_path"].endswith("-zh-cn.manifest.json")
    assert receipt["toc_json"] is None
    assert receipt["output_sha256"] is None
    assert receipt["manifest_sha256"] is None
    assert receipt["candidates_fingerprint"] is None
    assert '"null"' not in result.stdout
    assert all(not str(value).startswith("/") for value in (
        receipt["source_path"],
        receipt["output_path"],
        receipt["manifest_path"],
    ))


def test_strict_observe_cli_preserves_nullable_json_types_across_branches(tmp_path):
    configured_env = os.environ.copy()
    configured_env.update(
        {
            "QUASI_TRANSLATE_BACKEND": "immersive",
            "QUASI_IMMERSIVE_AUTH_KEY": "configured-not-used",
        }
    )

    def invoke(root: Path, *extra: str, env: dict[str, str] = configured_env):
        result = subprocess.run(
            [
                sys.executable,
                str(PLUGIN_ROOT / "scripts" / "translate" / "translate.py"),
                "observe",
                "strict-translation",
                "--target-language",
                "zh-CN",
                "--mode",
                "initial",
                "--json",
                *extra,
            ],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert len(result.stdout.strip().splitlines()) == 1
        assert result.stderr == ""
        assert '"null"' not in result.stdout
        receipt = json.loads(result.stdout)
        return result, receipt

    configuration_root = tmp_path / "configuration"
    configuration_source, _ = source_fixture(configuration_root)
    toc = configuration_root / ".quasi" / "toc.json"
    toc.parent.mkdir(parents=True)
    toc.write_text("[]", encoding="utf-8")
    missing_config_env = configured_env.copy()
    missing_config_env.pop("QUASI_IMMERSIVE_AUTH_KEY")
    configuration_result, configuration = invoke(
        configuration_root,
        "--source-file",
        str(configuration_source),
        "--toc-json",
        str(toc),
        env=missing_config_env,
    )
    assert configuration_result.returncode == 2
    assert configuration["status"] == "blocked"
    assert configuration["signal"] == "configuration_required"
    assert configuration["toc_json"] == ".quasi/toc.json"
    assert configuration["output_sha256"] is None
    assert configuration["manifest_sha256"] is None
    assert configuration["candidates_fingerprint"] is None

    selection_root = tmp_path / "selection"
    source_fixture(selection_root)
    make_pdf(
        selection_root
        / "processing"
        / "papers"
        / "strict-translation"
        / "ocr.pdf",
        4,
    )
    selection_result, selection = invoke(selection_root)
    assert selection_result.returncode == 2
    assert selection["status"] == "blocked"
    assert selection["signal"] == "source_selection"
    assert selection["toc_json"] is None
    assert selection["output_sha256"] is None
    assert selection["manifest_sha256"] is None
    assert isinstance(selection["candidates_fingerprint"], str)
    assert len(selection["candidates_fingerprint"]) == 64

    reused_root = tmp_path / "reused"
    reused_source, reused_source_sha = source_fixture(reused_root)
    config_fingerprint = translate_cli.backend_config_fingerprint(
        "immersive",
        "zh-CN",
    )
    committed = commit.run_transaction(
        **run_kwargs(
            reused_root,
            reused_source,
            reused_source_sha,
            passing_runner([]),
            backend="immersive",
            config_fingerprint=config_fingerprint,
        )
    )
    assert committed["status"] == "succeeded"
    reused_result, reused = invoke(
        reused_root,
        "--source-file",
        str(reused_source),
    )
    assert reused_result.returncode == 0
    assert reused["status"] == "succeeded"
    assert reused["signal"] == "reused"
    assert reused["toc_json"] is None
    assert isinstance(reused["output_sha256"], str)
    assert len(reused["output_sha256"]) == 64
    assert isinstance(reused["manifest_sha256"], str)
    assert len(reused["manifest_sha256"]) == 64
    assert reused["candidates_fingerprint"] is None


def test_configuration_gate_is_closed_and_starts_no_provider(tmp_path):
    source, _ = source_fixture(tmp_path)
    receipt = commit.observe(
        **observe_kwargs(
            tmp_path,
            source=source,
            configuration_missing=["translate_api_key", "translate_model"],
        )
    )
    assert receipt["status"] == "blocked"
    assert receipt["signal"] == "configuration_required"
    assert receipt["generation_attempt"] == 0
    assert receipt["gate"] == {
        "kind": "configuration_required",
        "missing_fields": ["translate_api_key", "translate_model"],
        "candidates": [],
        "candidates_fingerprint": None,
    }


def test_secret_bearing_pdf2zh_base_url_is_a_configuration_gate(monkeypatch):
    monkeypatch.setenv(
        "QUASI_TRANSLATE_BASE_URL",
        "https://user:pass@example.test/v1?token=secret",
    )
    monkeypatch.setenv("QUASI_TRANSLATE_API_KEY", "configured")
    monkeypatch.setenv("QUASI_TRANSLATE_MODEL", "configured")
    assert translate_cli.missing_configuration("pdf2zh") == [
        "translate_base_url"
    ]
    # Invalid URL content is neither returned nor fingerprinted.
    value = translate_cli.backend_config_fingerprint("pdf2zh", "zh-CN")
    assert len(value) == 64


def test_strict_surface_rejects_caller_backend_override_as_typed_json(tmp_path):
    source, _ = source_fixture(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "QUASI_TRANSLATE_BACKEND": "immersive",
            "QUASI_IMMERSIVE_AUTH_KEY": "configured-not-used",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "scripts" / "translate" / "translate.py"),
            "observe",
            "strict-translation",
            "--backend",
            "pdf2zh",
            "--source-file",
            str(source),
            "--target-language",
            "zh-CN",
            "--mode",
            "initial",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(result.stdout)
    assert result.returncode == 1
    assert receipt["status"] == "failed"


@pytest.mark.parametrize(
    ("slug", "language"),
    [
        ("../escape", "zh-CN"),
        ("x/../../../victim", "zh-CN"),
        ("good-slug", "../../zh"),
        ("good-slug", "zh_CN"),
    ],
)
def test_output_paths_reject_traversal_before_construction(tmp_path, slug, language):
    with pytest.raises(commit.TranslateContractError):
        commit.output_paths(
            project_root=tmp_path,
            slug=slug,
            target_language=language,
        )
    assert not (tmp_path / "victim").exists()


def test_full_language_tag_owns_distinct_canonical_outputs(tmp_path):
    cn = commit.output_paths(
        project_root=tmp_path,
        slug="strict-translation",
        target_language="zh-CN",
    )
    tw = commit.output_paths(
        project_root=tmp_path,
        slug="strict-translation",
        target_language="zh-TW",
    )
    assert cn["output_path"] != tw["output_path"]
    assert str(cn["output_path"]).endswith("-zh-cn.pdf")
    assert str(tw["output_path"]).endswith("-zh-tw.pdf")


def test_source_and_toc_must_be_project_local_regular_files(tmp_path):
    source, _ = source_fixture(tmp_path)
    symlink = tmp_path / "sources" / "linked.pdf"
    symlink.symlink_to(source)
    with pytest.raises(commit.TranslateContractError, match="regular non-symlink"):
        commit.validate_source(symlink)
    outside = make_pdf(tmp_path.parent / f"{tmp_path.name}-outside.pdf", 1)
    with pytest.raises(commit.TranslateContractError, match="inside the project"):
        commit.validate_project_source(outside, tmp_path)
    outside_toc = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside_toc.write_text("[]", encoding="utf-8")
    with pytest.raises(commit.TranslateContractError, match="inside the project"):
        commit.validate_project_toc(outside_toc, tmp_path)


def test_zero_source_is_a_known_closed_failure(tmp_path):
    receipt = commit.observe(**observe_kwargs(tmp_path, source=None))
    assert receipt["status"] == "failed"
    assert receipt["signal"] is None
    assert receipt["generation_attempt"] == 0
    assert receipt["source_path"] is None
    assert receipt["candidates"] == []
    assert receipt["candidates_fingerprint"] is None
    assert receipt["gate"] is None
    assert receipt["failure"]["outcome"] == "known"


def test_closed_source_selection_and_decision_revalidation(tmp_path):
    canonical, canonical_sha = source_fixture(tmp_path)
    recovery = make_pdf(
        tmp_path
        / "processing"
        / "papers"
        / "strict-translation"
        / "ocr.pdf",
        4,
    )
    gate = commit.observe(**observe_kwargs(tmp_path, source=None))
    assert gate["status"] == "blocked"
    assert gate["signal"] == "source_selection"
    assert gate["generation_attempt"] == 0
    assert gate["candidates"] == sorted(gate["candidates"], key=lambda row: row["path"])
    assert {row["path"] for row in gate["candidates"]} == {
        "sources/strict-translation.pdf",
        "processing/papers/strict-translation/ocr.pdf",
    }
    assert gate["gate"]["missing_fields"] == []
    assert gate["gate"]["candidates"] == gate["candidates"]

    selected = commit.observe(
        **observe_kwargs(tmp_path, source=canonical),
        decision_path=canonical,
        decision_sha256=canonical_sha,
        candidates_fingerprint=gate["candidates_fingerprint"],
    )
    assert selected["status"] == "succeeded"
    assert selected["signal"] == "missing"
    assert selected["candidates"] == []
    assert selected["candidates_fingerprint"] == gate["candidates_fingerprint"]

    make_pdf(recovery, 5)
    with pytest.raises(commit.TranslateContractError) as error:
        commit.observe(
            **observe_kwargs(tmp_path, source=canonical),
            decision_path=canonical,
            decision_sha256=canonical_sha,
            candidates_fingerprint=gate["candidates_fingerprint"],
        )


def test_run_publishes_manifest_last_and_reconcile_is_backend_free(tmp_path):
    source, source_sha = source_fixture(tmp_path)
    calls: list[str] = []
    kwargs = run_kwargs(tmp_path, source, source_sha, passing_runner(calls))
    first = commit.run_transaction(**kwargs)
    second = commit.run_transaction(**kwargs)
    final = commit.observe(**observe_kwargs(tmp_path, source=source, mode="final"))

    assert first["status"] == "succeeded"
    assert first["disposition"] == "created"
    assert first["canonical_committed"]
    assert first["coverage"]["signal"] == "pass"
    assert first["output_pages"] == 8
    assert second["status"] == "succeeded"
    assert second["disposition"] == "reconciled"
    assert final["signal"] == "reused"
    assert final["generation_attempt"] == 1
    assert final["request_fingerprint"] == first["request_fingerprint"]
    assert len(calls) == 1

    output = tmp_path / first["output_path"]
    manifest_path = tmp_path / first["manifest_path"]
    manifest = json.loads(manifest_path.read_text())
    assert manifest["output_path"] == first["output_path"]
    assert manifest["output_sha256"] == commit.sha256_file(output)
    assert first["manifest_sha256"] == commit.sha256_file(manifest_path)


def test_recovery_mode_uses_generation_attempt_two(tmp_path):
    source, _ = source_fixture(tmp_path, recovery=True)
    receipt = commit.observe(**observe_kwargs(tmp_path, source=source, mode="recovery"))
    assert receipt["attempt"] == 1
    assert receipt["generation_attempt"] == 2
    expected = commit.request_fingerprint(
        project_root=tmp_path,
        slug="strict-translation",
        backend="pdf2zh",
        target_language="zh-CN",
        input_path=source,
        input_sha256=receipt["source_sha256"],
        input_pages=receipt["source_pages"],
        toc_path=None,
        toc_sha256=None,
        toc_page_side="original",
        attempt=2,
        config_fingerprint=observe_kwargs(tmp_path, source=source)["config_fingerprint"],
    )
    assert receipt["request_fingerprint"] == expected


def test_unproven_existing_output_blocks_without_backend(tmp_path):
    source, source_sha = source_fixture(tmp_path)
    calls: list[str] = []
    paths = commit.output_paths(
        project_root=tmp_path,
        slug="strict-translation",
        target_language="zh-CN",
    )
    make_pdf(paths["output_path"], 8)
    receipt = commit.run_transaction(
        **run_kwargs(tmp_path, source, source_sha, passing_runner(calls))
    )
    assert receipt["status"] == "blocked"
    assert receipt["failure"]["outcome"] == "unknown"
    assert calls == []


def test_source_fingerprint_mismatch_is_known_and_starts_no_backend(tmp_path):
    source, source_sha = source_fixture(tmp_path)
    calls: list[str] = []
    receipt = commit.run_transaction(
        **run_kwargs(tmp_path, source, "0" * 64, passing_runner(calls))
    )
    assert source_sha != "0" * 64
    assert receipt["status"] == "failed"
    assert receipt["failure"]["outcome"] == "known"
    assert calls == []


def test_undertranslated_candidate_is_preserved_but_never_canonical(tmp_path):
    source, source_sha = source_fixture(tmp_path)

    def backend(source, candidate, language, work_dir, on_state):
        coverage.build_dual(candidate, [FULL, "", "", ""])
        return {"task_id": None}

    receipt = commit.run_transaction(
        **run_kwargs(tmp_path, source, source_sha, backend)
    )
    assert receipt["status"] == "failed"
    assert receipt["coverage"]["signal"] == "under_translated"
    assert receipt["output_sha256"] is None
    assert receipt["manifest_sha256"] is None
    assert not (tmp_path / receipt["output_path"]).exists()
    assert not (tmp_path / receipt["manifest_path"]).exists()
    candidates = list(
        (tmp_path / "processing" / "translations").glob(
            ".strict-translation-zh-cn.translate-*/candidate.pdf"
        )
    )
    assert len(candidates) == 1


def test_fenced_unknown_generation_never_starts_second_backend(tmp_path):
    source, source_sha = source_fixture(tmp_path)
    calls: list[str] = []

    def killed(source, candidate, language, work_dir, on_state):
        calls.append("start")
        on_state("creating_remote_task", None)
        raise KeyboardInterrupt()

    kwargs = run_kwargs(
        tmp_path,
        source,
        source_sha,
        killed,
        backend="immersive",
    )
    with pytest.raises(KeyboardInterrupt):
        commit.run_transaction(**kwargs)
    second = commit.run_transaction(**kwargs)
    assert second["status"] == "blocked"
    assert second["failure"]["outcome"] == "unknown"
    assert calls == ["start"]


def test_remote_task_creation_unknown_is_persisted_and_not_replayed(tmp_path):
    source, source_sha = source_fixture(tmp_path)
    calls: list[str] = []

    def lost_response(source, candidate, language, work_dir, on_state):
        calls.append("post")
        on_state("creating_remote_task", None)
        raise immersive.TranslationError("response lost")

    kwargs = run_kwargs(
        tmp_path,
        source,
        source_sha,
        lost_response,
        backend="immersive",
    )
    first = commit.run_transaction(**kwargs)
    second = commit.run_transaction(**kwargs)
    assert first["status"] == "blocked"
    assert first["failure"]["outcome"] == "unknown"
    assert second == first
    assert calls == ["post"]


def test_manifest_replace_failure_removes_uncommitted_output(tmp_path, monkeypatch):
    source, source_sha = source_fixture(tmp_path)
    paths = commit.output_paths(
        project_root=tmp_path,
        slug="strict-translation",
        target_language="zh-CN",
    )
    real_replace = commit.os.replace

    def fail_manifest(source_path, destination):
        if Path(destination) == paths["manifest_path"]:
            raise OSError("simulated manifest replace failure")
        return real_replace(source_path, destination)

    monkeypatch.setattr(commit.os, "replace", fail_manifest)
    receipt = commit.run_transaction(
        **run_kwargs(tmp_path, source, source_sha, passing_runner([]))
    )
    assert receipt["status"] == "failed"
    assert receipt["failure"]["outcome"] == "known"
    assert not Path(paths["output_path"]).exists()
    assert not Path(paths["manifest_path"]).exists()
    assert receipt["previous_manifest_preserved"]


def test_post_manifest_fsync_failure_keeps_one_coherent_generation(tmp_path, monkeypatch):
    source, source_sha = source_fixture(tmp_path)
    paths = commit.output_paths(
        project_root=tmp_path,
        slug="strict-translation",
        target_language="zh-CN",
    )
    real_fsync = commit._fsync_directory

    def fail_after_manifest(path):
        if Path(paths["manifest_path"]).exists() and Path(path) == Path(paths["output_dir"]):
            raise OSError("simulated post-manifest fsync failure")
        return real_fsync(path)

    monkeypatch.setattr(commit, "_fsync_directory", fail_after_manifest)
    kwargs = run_kwargs(tmp_path, source, source_sha, passing_runner([]))
    receipt = commit.run_transaction(**kwargs)
    assert receipt["status"] == "blocked"
    assert receipt["failure"]["outcome"] == "unknown"
    output = Path(paths["output_path"])
    manifest_path = Path(paths["manifest_path"])
    manifest = json.loads(manifest_path.read_text())
    assert manifest["output_sha256"] == commit.sha256_file(output)
    assert manifest["output_size"] == output.stat().st_size

    monkeypatch.setattr(commit, "_fsync_directory", real_fsync)
    reconciled = commit.run_transaction(**kwargs)
    assert reconciled["status"] == "succeeded"
    assert reconciled["disposition"] == "reconciled"


def test_immersive_non_idempotent_post_is_not_retried(monkeypatch):
    class Session:
        def __init__(self):
            self.calls = 0

        def request(self, **kwargs):
            self.calls += 1
            raise requests.Timeout("lost response")

    client = immersive.ImmersiveTranslateClient(
        {**immersive.DEFAULT_SETTINGS, "auth_key": "secret-auth"},
    )
    client.session = Session()
    monkeypatch.setattr(immersive.time, "sleep", lambda seconds: None)
    with pytest.raises(immersive.TranslationError, match="lost response"):
        client.create_translate_task("object", Path("source.pdf"))
    assert client.session.calls == 1


def test_request_errors_redact_query_userinfo_and_known_secret():
    raw = (
        "401 for https://user:pass@example.test/check?"
        "apiKey=secret-auth&token=signed"
    )
    redacted = commit.redact_text(raw, secrets=("secret-auth",))
    assert "secret-auth" not in redacted
    assert "user:pass" not in redacted
    assert "token=signed" not in redacted
    assert "?<redacted>" in redacted

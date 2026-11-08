"""Unit tests for the pdf2zh-next translation backend.

The uvx subprocess and the remote model are not exercised — only the pieces
that decide whether output is trustworthy: command construction, dual-PDF
discovery, and the 2x-page-count acceptance gate that catches a mangled run
(pdf2zh-next exits 0 even when its output is garbage).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from translate import pdf2zh_translate as p2z  # noqa: E402
from translate.immersive_translate import MissingAuthKeyError, TranslationError  # noqa: E402

CFG = {"base_url": "https://x/v1", "api_key": "k", "model": "m"}


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/v1"),
        ("https://api.deepseek.com/", "https://api.deepseek.com/v1"),
        ("https://api.deepseek.com/v1", "https://api.deepseek.com/v1"),
        ("https://open.bigmodel.cn/api/paas/v4", "https://open.bigmodel.cn/api/paas/v4"),
    ],
)
def test_base_url_defaults_only_a_root_url_to_v1(configured, expected):
    assert p2z.normalise_base_url(configured) == expected


def test_base_url_rejects_a_bare_hostname():
    with pytest.raises(TranslationError, match="http"):
        p2z.normalise_base_url("api.deepseek.com")


@pytest.mark.parametrize(
    "value",
    [
        "https://user:pass@api.example/v1",
        "https://api.example/v1?token=secret",
        "https://api.example/v1#secret",
    ],
)
def test_base_url_rejects_secret_bearing_url_components(value):
    with pytest.raises(TranslationError, match="userinfo|query"):
        p2z.normalise_base_url(value)


def _make_pdf(path: Path, pages: int) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


def test_build_command_uses_alternating_dual_and_keeps_secrets_out_of_argv():
    cmd = p2z.build_command(
        source_pdf=Path("/s/a.pdf"),
        work_dir=Path("/w"),
        target_language="zh-CN",
    )
    # Keep the validated CLI/engine pair in uvx's isolated environment.
    assert cmd[cmd.index("--from") + 1] == "pdf2zh-next==2.10.2"
    assert cmd[cmd.index("--with") + 1] == "BabelDOC==0.7.1"
    # Alternating dual is what makes the existing TOC page mapping correct.
    assert "--use-alternating-pages-dual" in cmd
    assert "--no-mono" in cmd
    # Without this BabelDOC refuses every scanned book — most of the vault.
    assert "--auto-enable-ocr-workaround" in cmd
    assert CFG["base_url"] not in cmd
    assert CFG["api_key"] not in cmd
    assert CFG["model"] not in cmd
    assert not any("openai-compatible-api-key" in item for item in cmd)
    assert "--only-include-translated-page" not in cmd


def test_run_pdf2zh_delivers_provider_config_only_through_env(tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, *, check, env, stdout):
        assert stdout is p2z.sys.stderr
        captured.update({"cmd": cmd, "check": check, "env": env})
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(p2z.shutil, "which", lambda name: "/usr/bin/uvx")
    monkeypatch.setattr(p2z.subprocess, "run", fake_run)
    monkeypatch.setenv("QUASI_TRANSLATE_BASE_URL", CFG["base_url"])
    monkeypatch.setenv("QUASI_TRANSLATE_API_KEY", "secret-provider-key")
    monkeypatch.setenv("QUASI_TRANSLATE_MODEL", CFG["model"])
    cmd = p2z.build_command(
        source_pdf=Path("/s/a.pdf"),
        work_dir=tmp_path,
        target_language="zh-CN",
    )

    p2z.run_pdf2zh(cmd, tmp_path)

    assert "secret-provider-key" not in captured["cmd"]
    assert captured["env"]["PDF2ZH_OPENAI_COMPATIBLE_API_KEY"] == "secret-provider-key"
    assert captured["env"]["PDF2ZH_OPENAI_COMPATIBLE_BASE_URL"] == CFG["base_url"]
    assert captured["env"]["PDF2ZH_OPENAI_COMPATIBLE_MODEL"] == CFG["model"]


def test_missing_config_names_the_missing_fields(monkeypatch):
    for var in ("QUASI_TRANSLATE_BASE_URL", "QUASI_TRANSLATE_API_KEY", "QUASI_TRANSLATE_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("QUASI_TRANSLATE_BASE_URL", "https://x/v1")
    with pytest.raises(MissingAuthKeyError) as exc:
        p2z.load_backend_config()
    assert "translate_api_key" in str(exc.value)
    assert "translate_model" in str(exc.value)
    assert "translate_base_url" not in str(exc.value)


def test_find_dual_pdf(tmp_path):
    # Upstream exits 0 with no output when every request fails; say so, don't just
    # report a missing file.
    with pytest.raises(TranslationError, match="exited successfully"):
        p2z.find_dual_pdf(tmp_path)

    # Real name once --watermark-output-mode is set; docs only show `{stem}-dual.pdf`.
    real = "a.no_watermark.zh-CN.dual.pdf"
    _make_pdf(tmp_path / "nested" / real, 2)
    assert p2z.find_dual_pdf(tmp_path).name == real

    _make_pdf(tmp_path / "b-dual.pdf", 2)
    with pytest.raises(TranslationError, match="found several"):
        p2z.find_dual_pdf(tmp_path)


def test_provider_stdout_does_not_pollute_receipt_stream(tmp_path, monkeypatch, capfd):
    monkeypatch.setattr(p2z.shutil, 'which', lambda _: '/test/uvx')
    monkeypatch.setattr(p2z, 'load_backend_config', lambda: {
        'base_url': 'https://example.invalid/v1', 'api_key': 'test-only', 'model': 'test',
    })
    p2z.run_pdf2zh([p2z.sys.executable, '-c', "print('provider progress')"], tmp_path)
    captured=capfd.readouterr()
    assert captured.out == ''
    assert 'provider progress' in captured.err

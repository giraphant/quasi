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

from translate import coverage, pdf2zh_translate as p2z  # noqa: E402
from translate.immersive_translate import MissingAuthKeyError, TranslationError  # noqa: E402

CFG = {"base_url": "https://x/v1", "api_key": "k", "model": "m"}


def _make_pdf(path: Path, pages: int) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


def test_build_command_uses_alternating_dual_and_forwards_extras():
    cmd = p2z.build_command(
        source_pdf=Path("/s/a.pdf"),
        work_dir=Path("/w"),
        target_language="zh-CN",
        cfg=CFG,
        extra_args=["--qps", "4"],
    )
    # Alternating dual is what makes the existing TOC page mapping correct.
    assert "--use-alternating-pages-dual" in cmd
    assert "--no-mono" in cmd
    # Without this BabelDOC refuses every scanned book — most of the vault.
    assert "--auto-enable-ocr-workaround" in cmd
    assert cmd[cmd.index("--openai-compatible-base-url") + 1] == "https://x/v1"
    assert cmd[cmd.index("--openai-compatible-model") + 1] == "m"
    assert cmd[-2:] == ["--qps", "4"]
    assert "--only-include-translated-page" not in cmd  # no --pages, nothing to trim


def test_pages_flag_trims_the_output():
    cmd = p2z.build_command(
        source_pdf=Path("/s/a.pdf"),
        work_dir=Path("/w"),
        target_language="zh-CN",
        cfg=CFG,
        extra_args=["--pages", "31-60"],
    )
    # Otherwise the output is the whole book with the translated range buried inside.
    assert "--only-include-translated-page" in cmd


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


@pytest.mark.parametrize(
    ("out_pages", "ok"),
    [(6, True), (3, False), (5, False)],
)
def test_page_count_gate(tmp_path, monkeypatch, out_pages, ok):
    """A mangled run exits 0 upstream; only the page count catches it."""
    _make_pdf(tmp_path / "sources" / "slug.pdf", 3)

    def fake_run(cmd, work_dir):
        _make_pdf(Path(work_dir) / "slug.no_watermark.zh-CN.dual.pdf", out_pages)

    monkeypatch.setattr(p2z, "run_pdf2zh", fake_run)
    monkeypatch.setenv("QUASI_TRANSLATE_BASE_URL", CFG["base_url"])
    monkeypatch.setenv("QUASI_TRANSLATE_API_KEY", CFG["api_key"])
    monkeypatch.setenv("QUASI_TRANSLATE_MODEL", CFG["model"])

    def call():
        return p2z.translate_slug("slug", project_root=tmp_path)

    # With --pages the strict 2x rule cannot apply; only even-and-nonzero is checked.
    if out_pages % 2 == 0:
        assert p2z.translate_slug("slug", project_root=tmp_path, extra_args=["--pages", "1-3"])
    else:
        with pytest.raises(TranslationError, match="non-zero even count"):
            p2z.translate_slug("slug", project_root=tmp_path, extra_args=["--pages=1-3"])

    if ok:
        result = call()
        assert result["final_pdf"] == tmp_path / "processing" / "translations" / "slug-zh.pdf"
        assert result["final_pdf"].exists()
    else:
        with pytest.raises(TranslationError, match="expected 6"):
            call()
        # Failed output stays inspectable.
        assert (tmp_path / "processing" / "translations" / ".pdf2zh-slug").exists()


def test_correct_page_count_is_not_enough(tmp_path, monkeypatch):
    """The dual PDF above is blank, so the coverage gate abstains; a real one must not.

    A run that skips most of the body still lands the exact expected page count, which
    is why the page gate alone shipped a book that was 43% translated.
    """
    _make_pdf(tmp_path / "sources" / "slug.pdf", 4)
    for var, value in CFG.items():
        monkeypatch.setenv(f"QUASI_TRANSLATE_{var.upper()}", value)

    full = "行动的形状是什么样的 " * 12
    monkeypatch.setattr(
        p2z,
        "run_pdf2zh",
        lambda cmd, work_dir: coverage.build_dual(
            Path(work_dir) / "slug.no_watermark.zh-CN.dual.pdf",
            [full] + [""] * 3,
        ),
    )
    with pytest.raises(TranslationError, match="Under-translated"):
        p2z.translate_slug("slug", project_root=tmp_path)

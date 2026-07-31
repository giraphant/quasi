from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXTRACT = PLUGIN_ROOT / "scripts" / "extract" / "extract.py"
EXTRACT_DIR = PLUGIN_ROOT / "scripts" / "extract"
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


def _write_epub(
    path: Path,
    chapter_count: int = 2,
    body_label: str = "chapter",
    *,
    extension: str = ".xhtml",
    include_ncx: bool = True,
    filename_template: str = "chapter-{index}",
    nav_title_template: str = "Chapter {index}: Title",
) -> None:
    navpoints = []
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(1, chapter_count + 1):
            filename = filename_template.format(index=index) + extension
            navpoints.append(
                f"""
                <navPoint id="chapter-{index}">
                  <navLabel><text>{nav_title_template.format(index=index)}</text></navLabel>
                  <content src="{filename}"/>
                </navPoint>
                """
            )
            archive.writestr(
                f"OEBPS/{filename}",
                (
                    "<html><body><h1>Chapter</h1><p>"
                    + (f"{body_label} {index} body " * 30)
                    + "</p></body></html>"
                ),
            )
        if include_ncx:
            archive.writestr(
                "OEBPS/toc.ncx",
                "<ncx><navMap>" + "".join(navpoints) + "</navMap></ncx>",
            )


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EXTRACT), *args],
        cwd=PLUGIN_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_epub_json_commits_full_manifest_and_one_stdout_object(tmp_path: Path):
    source = tmp_path / "book.epub"
    output = tmp_path / "chapters"
    _write_epub(source)

    result = _run("epub", str(source), str(output), "--json")

    receipt = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 1
    assert "处理 EPUB" not in result.stdout
    assert "处理 EPUB" in result.stderr
    assert receipt["schema_version"] == "quasi.extract.chapters.receipt/0.1"
    assert set(receipt) == CHAPTER_RECEIPT_FIELDS
    assert receipt["status"] == "ok"
    assert receipt["mode"] == "epub"
    assert receipt["disposition"] == "created"
    assert receipt["chapter_count"] == 2
    manifest = json.loads((output / "manifest.json").read_text())
    assert receipt["chapters"] == manifest["chapters"]
    assert manifest["source_epub"] == source.name
    assert manifest["split_method"] == "epub"
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        (output / "manifest.json").read_bytes()
    ).hexdigest()
    assert all((output / row["filename"]).is_file() for row in receipt["chapters"])


def test_epub_fallback_reads_htm_and_normalises_filename_slug(tmp_path: Path):
    source = tmp_path / "book.epub"
    output = tmp_path / "chapters"
    _write_epub(
        source,
        chapter_count=2,
        extension=".htm",
        include_ncx=False,
        filename_template="{index:02d}_chapter_title",
    )

    result = _run("epub", str(source), str(output), "--json")

    receipt = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert receipt["chapter_count"] == 2
    assert [row["title"] for row in receipt["chapters"]] == [
        "01_chapter_title",
        "02_chapter_title",
    ]
    assert [row["slug"] for row in receipt["chapters"]] == [
        "01-chapter-title",
        "02-chapter-title",
    ]


def test_epub_normalises_ncx_title_whitespace(tmp_path: Path):
    source = tmp_path / "book.epub"
    output = tmp_path / "chapters"
    _write_epub(
        source,
        chapter_count=1,
        nav_title_template="Chapter {index}:\tA   Stable Title",
    )

    result = _run("epub", str(source), str(output), "--json")

    receipt = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert receipt["chapters"][0]["title"] == "Chapter 1: A Stable Title"


def test_epub_non_ascii_title_uses_canonical_slot_fallback(tmp_path: Path):
    source = tmp_path / "book.epub"
    output = tmp_path / "chapters"
    _write_epub(
        source,
        chapter_count=1,
        extension=".htm",
        include_ncx=False,
        filename_template="第一章",
    )

    result = _run("epub", str(source), str(output), "--json")

    receipt = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert receipt["chapters"][0]["slug"] == "section-01"


def test_epub_replaces_pre_contract_manifest_with_canonical_slugs(tmp_path: Path):
    source = tmp_path / "book.epub"
    output = tmp_path / "chapters"
    _write_epub(
        source,
        chapter_count=1,
        extension=".htm",
        include_ncx=False,
        filename_template="01_chapter_title",
    )
    assert _run("epub", str(source), str(output), "--json").returncode == 0
    manifest_path = output / "manifest.json"
    old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    old_manifest["request_fingerprint"] = "0" * 64
    old_manifest["chapters"][0]["slug"] = "01_chapter_title"
    manifest_path.write_text(
        json.dumps(old_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = _run("epub", str(source), str(output), "--json")

    receipt = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert receipt["disposition"] == "replaced"
    assert receipt["chapters"][0]["slug"] == "01-chapter-title"


def test_epub_limit_is_signal_only(tmp_path: Path):
    source = tmp_path / "book.epub"
    output = tmp_path / "chapters"
    _write_epub(source)

    result = _run(
        "epub",
        str(source),
        str(output),
        "--max-chapters",
        "1",
        "--json",
    )

    receipt = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert receipt["chapter_count"] == 2
    assert receipt["limit"] == {"max_chapters": 1, "exceeded": True}


def test_epub_invalid_archive_preserves_previous_generation(tmp_path: Path):
    source = tmp_path / "book.epub"
    output = tmp_path / "chapters"
    _write_epub(source)
    assert _run("epub", str(source), str(output), "--json").returncode == 0
    manifest_before = (output / "manifest.json").read_bytes()
    source.write_text("not a zip", encoding="utf-8")

    result = _run("epub", str(source), str(output), "--json")

    receipt = json.loads(result.stdout)
    assert result.returncode == 2
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "invalid_epub"
    assert receipt["failure"]["outcome"] == "known"
    assert receipt["failure"]["retryable"] is False
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        manifest_before
    ).hexdigest()
    assert receipt["previous_manifest_preserved"] is True
    assert (output / "manifest.json").read_bytes() == manifest_before


def test_epub_legacy_renders_prose_over_transaction(tmp_path: Path):
    source = tmp_path / "book.epub"
    output = tmp_path / "chapters"
    _write_epub(source, chapter_count=1)

    result = _run("epub", str(source), str(output))

    manifest = json.loads((output / "manifest.json").read_text())
    row = manifest["chapters"][0]
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"处理 EPUB: {source}")
    assert f"输出目录: {output}" in result.stdout
    assert f"Manifest: {output / 'manifest.json'}" in result.stdout
    assert "完成！共提取 1 个章节" in result.stdout
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    assert hashlib.sha256((output / row["filename"]).read_bytes()).hexdigest() == (
        row["sha256"]
    )


def test_epub_json_and_legacy_writers_share_one_output_lock(
    tmp_path: Path,
):
    wrapper = tmp_path / "paused-json-epub.py"
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
import process_epub

sys.argv = [
    "process_epub.py",
    sys.argv[2],
    sys.argv[3],
    "--json",
]
raise SystemExit(process_epub.main())
""".lstrip(),
        encoding="utf-8",
    )
    source = tmp_path / "book.epub"
    output = tmp_path / "chapters"
    _write_epub(
        source,
        chapter_count=1,
        body_label="json generation",
    )
    json_writer = subprocess.Popen(
        [
            sys.executable,
            str(wrapper),
            str(EXTRACT_DIR),
            str(source),
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

    # Give the legacy writer a distinct source generation with the same title,
    # slot, and filename after the JSON writer completed its source recheck.
    _write_epub(
        source,
        chapter_count=1,
        body_label="legacy generation",
    )
    legacy_writer = subprocess.Popen(
        [
            sys.executable,
            str(EXTRACT),
            "epub",
            str(source),
            str(output),
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
    row = manifest["chapters"][0]
    chapter_path = output / row["filename"]
    assert legacy_completed_while_locked is False
    assert json_writer.returncode == 0, json_stderr
    assert receipt["status"] == "ok"
    assert legacy_writer.returncode == 1, (legacy_stdout, legacy_stderr)
    assert "competing chapter generation" in legacy_stderr
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        manifest_bytes
    ).hexdigest()
    assert receipt["chapters"] == manifest["chapters"]
    assert row["sha256"] == hashlib.sha256(chapter_path.read_bytes()).hexdigest()
    assert "json generation" in chapter_path.read_text(encoding="utf-8")

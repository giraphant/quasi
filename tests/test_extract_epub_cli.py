from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXTRACT = PLUGIN_ROOT / "scripts" / "extract" / "extract.py"
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
    assert receipt["manifest_fingerprint"] == hashlib.sha256(
        manifest_before
    ).hexdigest()
    assert receipt["previous_manifest_preserved"] is True
    assert (output / "manifest.json").read_bytes() == manifest_before


def test_epub_uses_opf_spine_order_and_keeps_unlisted_heading(tmp_path: Path):
    source = tmp_path / "book.epub"
    output = tmp_path / "chapters"
    body = "substantial body text " * 20
    members = {
        "aa_promo.htm": f"<html><body><h1>Promotion</h1><p>{body}</p></body></html>",
        "zz_preface.htm": f"<html><body><h1>Preface heading</h1><p>{body}</p></body></html>",
        "a_ch1.htm": f"<html><body><h1>Alpha heading</h1><p>{body}</p></body></html>",
        "b_ch2.htm": f"<html><body><h1>Beta heading</h1><p>{body}</p></body></html>",
        "m_notes.htm": f"<html><body><h2>Notes heading</h2><p>{body}</p></body></html>",
        "n_notes2.htm": f"<html><body><h3>Chapter 2 notes</h3><p>{body}</p></body></html>",
        "ab_junk.htm": f"<html><body><p>{body}</p></body></html>",
    }
    spine_order = [
        "promo", "preface", "ch1", "ch2", "notes", "notes2", "junk",
    ]
    filenames_by_id = dict(zip(spine_order, members))
    navpoints = [
        ("promo", "Other Books by This Author"),
        ("preface", "Preface"),
        ("ch1", "1 - Alpha"),
        ("ch2", "2 - Beta"),
        ("notes", "Notes"),
    ]

    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="pkg_opf_r1.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "pkg_opf_r1.opf",
            "<package><manifest>"
            + "".join(
                f'<item href="OEBPS/{filename}" id="{item_id}" media-type="application/xhtml+xml"/>'
                for item_id, filename in filenames_by_id.items()
            )
            + '<item href="pkg_ncx_r1.ncx" id="ncx" media-type="application/x-dtbncx+xml"/>'
            + "</manifest><spine toc=\"ncx\">"
            + "".join(f'<itemref idref="{item_id}" linear="yes"/>' for item_id in spine_order)
            + "</spine></package>",
        )
        archive.writestr(
            "pkg_ncx_r1.ncx",
            "<ncx><navMap>"
            + "".join(
                f'<navPoint id="{item_id}"><navLabel><text>{title}</text></navLabel>'
                f'<content src="OEBPS/{filenames_by_id[item_id]}"/></navPoint>'
                for item_id, title in navpoints
            )
            + "</navMap></ncx>",
        )
        for filename, html in members.items():
            archive.writestr(f"OEBPS/{filename}", html)

    result = _run("epub", str(source), str(output), "--json")

    receipt = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((output / "manifest.json").read_text())
    assert [row["title"] for row in receipt["chapters"]] == [
        "Preface", "1 - Alpha", "2 - Beta", "Notes", "Chapter 2 notes",
    ]
    assert [row["slot"] for row in receipt["chapters"]] == [
        "01", "02", "03", "04", "05",
    ]
    assert manifest["total_chapters_in_toc"] == 7
    assert "Other Books by This Author" not in [
        row["title"] for row in manifest["chapters"]
    ]
    assert "ab_junk" not in [row["title"] for row in manifest["chapters"]]
    assert any(row["reason"] == "furniture" for row in manifest["skipped"])

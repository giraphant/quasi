"""Atomic prepare-media CLI tests without invoking a real encoder."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from talk import compress_media  # noqa: E402


def _args(root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        project_dir=str(root),
        media="sources/input.mov",
        output="vault/talks/compress-talk/recording.mp4",
        crf="28",
        preset="veryfast",
        audio_bitrate="96k",
        force=False,
        json=True,
    )


def _stub_ffmpeg(monkeypatch, calls: list[list[str]]) -> None:
    monkeypatch.setattr(compress_media.shutil, "which", lambda _name: "/ffmpeg")

    def run(command, text):
        del text
        calls.append(command)
        Path(command[-1]).write_bytes(b"compressed-media")
        return argparse.Namespace(returncode=0)

    monkeypatch.setattr(compress_media.subprocess, "run", run)


def test_prepare_media_closed_receipt_and_reconcile_without_ffmpeg(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "sources/input.mov"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-media")
    calls: list[list[str]] = []
    _stub_ffmpeg(monkeypatch, calls)
    code, created = compress_media.run(_args(tmp_path))
    assert code == 0
    assert created["action"] == "create"
    assert len(calls) == 1
    calls.clear()
    code, reconciled = compress_media.run(_args(tmp_path))
    assert code == 0
    assert reconciled["action"] == "reconciled"
    assert reconciled["output_sha256"] == created["output_sha256"]
    assert calls == []


def test_prepare_media_echoes_absolute_source_path(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "sources/input.mov"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-media")
    calls: list[list[str]] = []
    _stub_ffmpeg(monkeypatch, calls)
    args = _args(tmp_path)
    args.media = str(source)
    code, receipt = compress_media.run(args)
    assert code == 0
    assert receipt["input_path"] == str(source)


@pytest.mark.skipif(
    not hasattr(os, "chflags") or not hasattr(stat, "UF_HIDDEN"),
    reason="macOS file flags are unavailable",
)
def test_prepare_media_clears_hidden_flag_carried_by_staging_inode(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "sources/input.mov"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-media")
    calls: list[list[str]] = []
    monkeypatch.setattr(compress_media.shutil, "which", lambda _name: "/ffmpeg")

    def run(command, text):
        del text
        calls.append(command)
        stage = Path(command[-1])
        stage.write_bytes(b"compressed-media")
        os.chflags(stage, stage.stat().st_flags | stat.UF_HIDDEN)
        return argparse.Namespace(returncode=0)

    monkeypatch.setattr(compress_media.subprocess, "run", run)

    code, receipt = compress_media.run(_args(tmp_path))

    output = tmp_path / "vault/talks/compress-talk/recording.mp4"
    assert code == 0
    assert receipt["action"] == "create"
    assert len(calls) == 1
    assert output.stat().st_flags & stat.UF_HIDDEN == 0


@pytest.mark.skipif(
    not hasattr(os, "chflags") or not hasattr(stat, "UF_HIDDEN"),
    reason="macOS file flags are unavailable",
)
def test_prepare_media_reconcile_repairs_hidden_existing_output(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "sources/input.mov"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-media")
    calls: list[list[str]] = []
    _stub_ffmpeg(monkeypatch, calls)
    assert compress_media.run(_args(tmp_path))[0] == 0
    output = tmp_path / "vault/talks/compress-talk/recording.mp4"
    os.chflags(output, output.stat().st_flags | stat.UF_HIDDEN)
    assert output.stat().st_flags & stat.UF_HIDDEN
    calls.clear()

    code, receipt = compress_media.run(_args(tmp_path))

    assert code == 0
    assert receipt["action"] == "reconciled"
    assert calls == []
    assert output.stat().st_flags & stat.UF_HIDDEN == 0


def test_prepare_media_hidden_flag_failure_rolls_back_before_manifest(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "sources/input.mov"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-media")
    calls: list[list[str]] = []
    _stub_ffmpeg(monkeypatch, calls)

    def fail(_path: Path) -> bool:
        raise OSError("cannot clear hidden flag")

    monkeypatch.setattr(compress_media, "_clear_macos_hidden", fail)

    code, receipt = compress_media.run(_args(tmp_path))

    output = tmp_path / "vault/talks/compress-talk/recording.mp4"
    manifest = output.parent / ".recording.mp4.quasi-compress.json"
    assert code != 0
    assert receipt["status"] == "blocked"
    assert not output.exists()
    assert not manifest.exists()


def test_prepare_media_rejects_unmanaged_and_symlink_targets(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "sources/input.mov"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-media")
    calls: list[list[str]] = []
    _stub_ffmpeg(monkeypatch, calls)
    output = tmp_path / "vault/talks/compress-talk/recording.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"unmanaged")
    code, receipt = compress_media.run(_args(tmp_path))
    assert code != 0
    assert receipt["status"] == "blocked"
    assert calls == []

    output.unlink()
    assert list(output.parent.iterdir()) == []
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "vault/talks/compress-talk").rmdir()
    (tmp_path / "vault/talks/compress-talk").symlink_to(
        outside, target_is_directory=True
    )
    code, receipt = compress_media.run(_args(tmp_path))
    assert code != 0
    assert receipt["status"] == "blocked"
    assert calls == []


def test_prepare_media_post_manifest_fsync_failure_keeps_new_pair(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "sources/input.mov"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-media")
    calls: list[list[str]] = []
    _stub_ffmpeg(monkeypatch, calls)
    original = compress_media._fsync_dir
    count = 0

    def fail_after_marker(path):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("post-marker fsync")
        return original(path)

    monkeypatch.setattr(compress_media, "_fsync_dir", fail_after_marker)
    code, receipt = compress_media.run(_args(tmp_path))
    assert code != 0
    assert receipt["status"] == "blocked"
    output = tmp_path / "vault/talks/compress-talk/recording.mp4"
    manifest = json.loads(
        (output.parent / ".recording.mp4.quasi-compress.json").read_text()
    )
    assert compress_media._sha(output) == manifest["output_sha256"]

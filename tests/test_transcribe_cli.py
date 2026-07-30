"""Strict Talk CLI transaction and receipt characterization."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
sys.path.insert(0, str(PLUGIN_ROOT))

from transcribe import talk_commit, transcribe  # noqa: E402
from talk import compress_media  # noqa: E402


TRANSCRIBE_KEYS = {
    "schema_version",
    "key",
    "effect",
    "status",
    "attempt",
    "material_key",
    "slug",
    "input_path",
    "output_dir",
    "talk_dir",
    "manifest_path",
    "manifest_exists",
    "manifest_fingerprint",
    "request_fingerprint",
    "source_sha256",
    "lang",
    "title",
    "engines",
    "primary_engine",
    "transcript_path",
    "subtitle_path",
    "per_engine",
    "artifacts",
    "disposition",
    "previous_manifest_preserved",
    "failure",
}


def test_talk_transaction_remains_python39_compatible():
    source = (PLUGIN_ROOT / "scripts" / "transcribe" / "talk_commit.py").read_text(
        encoding="utf-8"
    )
    assert "strict=True" not in source


def _media(root: Path) -> Path:
    path = root / "sources" / "talk.wav"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not-real-media-but-stubbed")
    return path


def _args(root: Path, slug: str = "strict-talk") -> list[str]:
    return [
        "--project-dir",
        str(root),
        "run",
        "--media",
        "sources/talk.wav",
        "--slug",
        slug,
        "--title",
        "Strict Talk",
        "--engines",
        "soniox,apple",
        "--lang",
        "en",
        "--json",
    ]


def _stub_audio(monkeypatch, calls: list[str]) -> None:
    monkeypatch.setattr(
        transcribe,
        "_extract_wav",
        lambda _media, dst: (dst.write_bytes(b"wav") or True),
    )

    def engine(name, _wav, _lang):
        calls.append(name)
        return [
            {
                "start": 0.0,
                "end": 4.0,
                "text": f"{name} produced enough useful spoken content " * 5,
            }
        ]

    monkeypatch.setattr(transcribe.eng, "run_engine", engine)


def test_run_json_is_closed_committed_and_reconciles_without_engines(
    tmp_path: Path, monkeypatch, capsys
):
    _media(tmp_path)
    calls: list[str] = []
    _stub_audio(monkeypatch, calls)
    assert transcribe.main(_args(tmp_path)) == 0
    first = json.loads(capsys.readouterr().out)
    assert set(first) == TRANSCRIBE_KEYS
    assert first["status"] == "succeeded"
    assert first["disposition"] == "created"
    assert calls == ["soniox", "apple"] or calls == ["apple", "soniox"]
    assert [row["name"] for row in first["per_engine"]] == ["soniox", "apple"]
    assert first["manifest_fingerprint"] == talk_commit.sha256_file(
        tmp_path / first["manifest_path"]
    )
    assert all(
        talk_commit.sha256_file(tmp_path / row["path"]) == row["sha256"]
        for row in first["artifacts"]
    )

    calls.clear()
    assert transcribe.main(_args(tmp_path)) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["disposition"] == "reconciled"
    assert second["previous_manifest_preserved"] is True
    assert calls == []


def test_strict_receipts_echo_an_absolute_source_path_byte_for_byte(
    tmp_path: Path, monkeypatch, capsys
):
    source = _media(tmp_path)
    calls: list[str] = []
    _stub_audio(monkeypatch, calls)
    run = _args(tmp_path)
    run[run.index("sources/talk.wav")] = str(source)
    assert transcribe.main(run) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["input_path"] == str(source)

    observe = [
        "--project-dir",
        str(tmp_path),
        "observe",
        "--media",
        str(source),
        "--slug",
        "strict-talk",
        "--title",
        "Strict Talk",
        "--date",
        "2026-07-30",
        "--engines",
        "soniox,apple",
        "--lang",
        "en",
        "--json",
    ]
    assert transcribe.main(observe) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["input_path"] == str(source)


def test_observe_without_manifest_has_no_committed_request_fingerprint(
    tmp_path: Path, capsys
):
    _media(tmp_path)
    observe = [
        "--project-dir",
        str(tmp_path),
        "observe",
        "--media",
        "sources/talk.wav",
        "--slug",
        "strict-talk",
        "--title",
        "Strict Talk",
        "--date",
        "2026-07-30",
        "--engines",
        "apple",
        "--lang",
        "en",
        "--json",
    ]
    assert transcribe.main(observe) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "succeeded"
    assert receipt["manifest_exists"] is False
    assert receipt["request_fingerprint"] is None
    assert receipt["transcript_path"] is None
    assert receipt["subtitle_path"] is None
    assert receipt["classification"] is None


@pytest.mark.parametrize(
    "slug",
    ["中文讲座", "Uppercase", "../escape", "a" * 81],
)
def test_strict_cli_rejects_noncanonical_ascii_slugs(
    tmp_path: Path, monkeypatch, capsys, slug: str
):
    _media(tmp_path)
    calls: list[str] = []
    _stub_audio(monkeypatch, calls)
    assert transcribe.main(_args(tmp_path, slug)) != 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "invalid_slug"
    assert calls == []


def test_changed_request_replaces_only_manifest_owned_outputs(
    tmp_path: Path, monkeypatch, capsys
):
    _media(tmp_path)
    calls: list[str] = []
    _stub_audio(monkeypatch, calls)
    assert transcribe.main(_args(tmp_path)) == 0
    capsys.readouterr()
    unmanaged = tmp_path / "processing" / "talks" / "strict-talk" / "notes.txt"
    unmanaged.write_text("keep", encoding="utf-8")
    changed = _args(tmp_path)
    changed[changed.index("Strict Talk")] = "Strict Talk Revised"
    assert transcribe.main(changed) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["disposition"] == "replaced"
    assert unmanaged.read_text(encoding="utf-8") == "keep"


def test_observe_and_classify_accept_only_the_committed_generation(
    tmp_path: Path, monkeypatch, capsys
):
    _media(tmp_path)
    calls: list[str] = []
    _stub_audio(monkeypatch, calls)
    assert transcribe.main(_args(tmp_path)) == 0
    capsys.readouterr()
    observe = [
        "--project-dir",
        str(tmp_path),
        "observe",
        "--media",
        "sources/talk.wav",
        "--slug",
        "strict-talk",
        "--title",
        "Strict Talk",
        "--date",
        "2026-07-30",
        "--engines",
        "soniox,apple",
        "--lang",
        "en",
        "--json",
    ]
    assert transcribe.main(observe) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "succeeded"
    assert receipt["classification"] == "live"
    assert receipt["manifest_exists"] is True
    assert len(receipt["artifacts"]) == 4

    classify = [
        "--project-dir",
        str(tmp_path),
        "classify",
        "--slug",
        "strict-talk",
        "--json",
    ]
    assert transcribe.main(classify) == 0
    classified = json.loads(capsys.readouterr().out)
    assert classified["signal"] == "live"
    assert classified["machine_signals"]["total"] == 1


def test_prepared_video_observe_uses_prepared_source_fingerprint(
    tmp_path: Path, monkeypatch, capsys
):
    original = tmp_path / "sources/input.mov"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"original-video")
    monkeypatch.setattr(compress_media.shutil, "which", lambda _name: "/ffmpeg")

    def compress(command, text):
        del text
        Path(command[-1]).write_bytes(b"prepared-video")
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(compress_media.subprocess, "run", compress)
    prepare_args = type(
        "Args",
        (),
        {
            "project_dir": str(tmp_path),
            "media": "sources/input.mov",
            "output": "vault/talks/video-talk/recording.mp4",
            "crf": "28",
            "preset": "veryfast",
            "audio_bitrate": "96k",
            "force": False,
            "json": True,
        },
    )()
    assert compress_media.run(prepare_args)[0] == 0

    calls: list[str] = []
    _stub_audio(monkeypatch, calls)
    run = _args(tmp_path, "video-talk")
    run[run.index("sources/talk.wav")] = (
        "vault/talks/video-talk/recording.mp4"
    )
    run[run.index("Strict Talk")] = "Video Talk"
    assert transcribe.main(run) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["disposition"] == "created"
    calls.clear()

    observe = [
        "--project-dir",
        str(tmp_path),
        "observe",
        "--media",
        "sources/input.mov",
        "--slug",
        "video-talk",
        "--title",
        "Video Talk",
        "--date",
        "2026-07-30",
        "--engines",
        "soniox,apple",
        "--lang",
        "en",
        "--json",
    ]
    assert transcribe.main(observe) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["request_fingerprint"] == first["request_fingerprint"]
    assert observed["prepared_path"] == "vault/talks/video-talk/recording.mp4"
    assert observed["classification"] == "live"
    assert calls == []

    assert transcribe.main(run) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["disposition"] == "reconciled"
    assert calls == []


def test_silent_json_safe_yaml_create_then_reconcile(
    tmp_path: Path, capsys
):
    transcript = tmp_path / "vault/talks/silent-talk/transcript.md"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("`[00:00]` [BLANK_AUDIO]\n", encoding="utf-8")
    argv = [
        "--project-dir",
        str(tmp_path),
        "silent",
        "--slug",
        "silent-talk",
        "--title",
        "O'Brien: \"quoted\"",
        "--date",
        "2026-07-30",
        "--media",
        "recording: one's.mov",
        "--classification-signal",
        "dead",
        "--json",
    ]
    assert transcribe.main(argv) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["action"] == "create"
    output = tmp_path / created["output_path"]
    text = output.read_text(encoding="utf-8")
    assert "title: \"O'Brien: \\\"quoted\\\"\"" in text
    assert "media: \"recording: one's.mov\"" in text
    assert transcribe.main(argv) == 0
    reconciled = json.loads(capsys.readouterr().out)
    assert reconciled["action"] == "reconciled"
    assert reconciled["output_sha256"] == created["output_sha256"]


def test_symlink_output_ancestor_blocks_before_engine(
    tmp_path: Path, monkeypatch, capsys
):
    _media(tmp_path)
    calls: list[str] = []
    _stub_audio(monkeypatch, calls)
    (tmp_path / "processing").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "processing" / "talks").symlink_to(outside, target_is_directory=True)
    assert transcribe.main(_args(tmp_path)) != 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "blocked"
    assert receipt["failure"]["outcome"] == "unknown"
    assert calls == []


def test_same_slug_concurrent_calls_run_each_engine_once(
    tmp_path: Path, monkeypatch
):
    _media(tmp_path)
    calls: list[str] = []
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        transcribe,
        "_extract_wav",
        lambda _media, dst: (dst.write_bytes(b"wav") or True),
    )

    def engine(name, _wav, _lang):
        calls.append(name)
        started.set()
        release.wait(5)
        return [{"start": 0.0, "end": 2.0, "text": f"content from {name} " * 30}]

    monkeypatch.setattr(transcribe.eng, "run_engine", engine)
    results: list[int] = []

    def invoke():
        # Avoid stdout races: exercise the transaction API through cmd_run while
        # replacing emit only for this test.
        class Args:
            project_dir = str(tmp_path)
            slug = "strict-talk"
            media = "sources/talk.wav"
            title = "Strict Talk"
            engines = "soniox,apple"
            lang = "en"
            json = True

        results.append(transcribe.cmd_run(Args()))

    monkeypatch.setattr(transcribe, "emit_json", lambda _value: None)
    one = threading.Thread(target=invoke)
    two = threading.Thread(target=invoke)
    one.start()
    assert started.wait(2)
    two.start()
    time.sleep(0.1)
    release.set()
    one.join(5)
    two.join(5)
    assert results == [0, 0]
    assert sorted(calls) == ["apple", "soniox"]


@pytest.mark.parametrize("after_manifest", [False, True])
def test_publish_fsync_failure_keeps_one_coherent_generation(
    tmp_path: Path, monkeypatch, capsys, after_manifest: bool
):
    _media(tmp_path)
    calls: list[str] = []
    _stub_audio(monkeypatch, calls)
    assert transcribe.main(_args(tmp_path)) == 0
    capsys.readouterr()
    changed = _args(tmp_path)
    changed[changed.index("Strict Talk")] = "Changed Talk"
    original = talk_commit.fsync_directory
    count = 0

    def fail(directory):
        nonlocal count
        count += 1
        # Two artifact dirs are synced before manifest replacement; the third
        # sync is the post-marker durability barrier.
        threshold = 3 if after_manifest else 1
        if count == threshold:
            raise OSError("injected fsync failure")
        return original(directory)

    monkeypatch.setattr(talk_commit, "fsync_directory", fail)
    assert transcribe.main(changed) != 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "blocked"
    assert [row["name"] for row in receipt["per_engine"]] == [
        "soniox",
        "apple",
    ]
    assert all(row["status"] == "failed" for row in receipt["per_engine"])
    manifest = json.loads(
        (tmp_path / "processing/talks/strict-talk/manifest.json").read_text()
    )
    for row in manifest["artifacts"]:
        assert talk_commit.sha256_file(tmp_path / row["path"]) == row["sha256"]

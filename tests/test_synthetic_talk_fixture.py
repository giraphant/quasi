from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import wave


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "make_synthetic_talk.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "make_synthetic_talk",
        FIXTURE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tone_fixture_is_byte_deterministic(tmp_path: Path) -> None:
    module = _load()
    assert len(module.SPEECH_TEXT) > 200
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"

    first_receipt = module.build(
        first,
        mode="tone",
        seconds=1.0,
        text=module.SPEECH_TEXT,
    )
    second_receipt = module.build(
        second,
        mode="tone",
        seconds=1.0,
        text=module.SPEECH_TEXT,
    )

    assert first.read_bytes() == second.read_bytes()
    assert first_receipt["sha256"] == second_receipt["sha256"]
    assert first_receipt["duration_seconds"] == 1.0
    assert first_receipt["sentinels"] == []
    with wave.open(str(first), "rb") as source:
        assert source.getframerate() == 16_000
        assert source.getnchannels() == 1


def test_silence_fixture_is_all_zero_and_closed(tmp_path: Path) -> None:
    module = _load()
    output = tmp_path / "silence.wav"

    receipt = module.build(
        output,
        mode="silence",
        seconds=0.25,
        text=module.SPEECH_TEXT,
    )

    with wave.open(str(output), "rb") as source:
        assert set(source.readframes(source.getnframes())) == {0}
    assert set(receipt) == {
        "schema_version",
        "mode",
        "path",
        "size",
        "sha256",
        "duration_seconds",
        "sentinels",
        "text",
    }
    assert receipt["sha256"] == _digest(output)


def test_fixture_refuses_to_overwrite(tmp_path: Path) -> None:
    module = _load()
    output = tmp_path / "existing.wav"
    output.write_bytes(b"user-owned")

    try:
        module.build(
            output,
            mode="tone",
            seconds=1.0,
            text=module.SPEECH_TEXT,
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("fixture overwrote an existing path")

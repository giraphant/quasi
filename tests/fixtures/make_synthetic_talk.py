#!/usr/bin/env python3
"""Build deterministic audio or a macOS speech fixture for Talk tests.

The repository never stores the generated media.  ``tone`` and ``silence`` use
only the Python standard library and are byte-for-byte deterministic.  The
``speech`` mode is intended for native macOS acceptance: it uses ``say`` and
``ffmpeg`` and reports the resulting hash rather than promising cross-version
binary identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import wave


SAMPLE_RATE = 16_000
DEFAULT_SECONDS = 3.0
SPEECH_TEXT = (
    "ALPHA says that stable inputs need explicit provenance. "
    "BETA says that parallel workers must join before synthesis. "
    "GAMMA says that audit repair must follow exact artifact ownership. "
    "Together these rules make the workflow reproducible. "
    "Stable evidence prevents unsupported claims. "
    "Explicit joins prevent incomplete summaries. "
    "Exact ownership prevents a repair from changing the wrong file."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_new_output(path: Path) -> None:
    if not path.parent.is_dir():
        raise FileNotFoundError(f"output parent does not exist: {path.parent}")
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output already exists: {path}")


def _write_pcm_wave(path: Path, *, mode: str, seconds: float) -> None:
    frame_count = round(SAMPLE_RATE * seconds)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for index in range(frame_count):
            if mode == "silence":
                sample = 0
            else:
                # Two fixed tones make accidental all-zero fixtures obvious.
                value = (
                    0.55 * math.sin(2 * math.pi * 440 * index / SAMPLE_RATE)
                    + 0.25 * math.sin(2 * math.pi * 660 * index / SAMPLE_RATE)
                )
                sample = round(12_000 * value)
            frames.extend(struct.pack("<h", sample))
        output.writeframes(bytes(frames))


def _run(command: list[str]) -> None:
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _write_speech(path: Path, *, text: str) -> None:
    say = shutil.which("say")
    ffmpeg = shutil.which("ffmpeg")
    if say is None:
        raise RuntimeError("speech mode requires macOS say")
    if ffmpeg is None:
        raise RuntimeError("speech mode requires ffmpeg")

    with tempfile.TemporaryDirectory(prefix="quasi-talk-fixture-") as temp_name:
        temp = Path(temp_name)
        aiff = temp / "speech.aiff"
        _run([say, "-v", "Samantha", "-r", "165", "-o", str(aiff), text])
        if path.suffix.lower() == ".mp4":
            _run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=640x360:r=25",
                    "-i",
                    str(aiff),
                    "-shortest",
                    "-map_metadata",
                    "-1",
                    "-metadata",
                    "creation_time=2026-01-01T00:00:00Z",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(path),
                ]
            )
        elif path.suffix.lower() == ".wav":
            _run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-i",
                    str(aiff),
                    "-ar",
                    str(SAMPLE_RATE),
                    "-ac",
                    "1",
                    "-map_metadata",
                    "-1",
                    str(path),
                ]
            )
        else:
            raise ValueError("speech output must end in .mp4 or .wav")


def _duration(path: Path, *, fallback: float | None) -> float | None:
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as source:
            return source.getnframes() / source.getframerate()
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return fallback
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def build(
    output: Path,
    *,
    mode: str,
    seconds: float,
    text: str,
) -> dict[str, object]:
    _require_new_output(output)
    if mode in {"tone", "silence"}:
        if output.suffix.lower() != ".wav":
            raise ValueError(f"{mode} output must end in .wav")
        _write_pcm_wave(output, mode=mode, seconds=seconds)
        fallback_duration: float | None = seconds
    else:
        _write_speech(output, text=text)
        fallback_duration = None
    return {
        "schema_version": "quasi.synthetic-talk.fixture/0.1",
        "mode": mode,
        "path": str(output),
        "size": output.stat().st_size,
        "sha256": _sha256(output),
        "duration_seconds": _duration(
            output,
            fallback=fallback_duration,
        ),
        "sentinels": ["ALPHA", "BETA", "GAMMA"] if mode == "speech" else [],
        "text": text if mode == "speech" else None,
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--mode",
        choices=("tone", "silence", "speech"),
        default="tone",
    )
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--text", default=SPEECH_TEXT)
    parser.add_argument("--metadata-json", type=Path)
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or args.seconds <= 0 or args.seconds > 60:
        parser.error("--seconds must be finite and in (0, 60]")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    payload = build(
        args.output,
        mode=args.mode,
        seconds=args.seconds,
        text=args.text,
    )
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if args.metadata_json is not None:
        _require_new_output(args.metadata_json)
        args.metadata_json.write_text(rendered + "\n", encoding="utf-8")
    sys.stdout.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Single-recording compression helper for process-talk."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="quasi-helpers talk compress-media")
    ap.add_argument("--media", required=True, help="source video/audio file")
    ap.add_argument("--output", required=True, help="compressed output path")
    ap.add_argument("--crf", default="28", help="x265 CRF; lower is larger/better")
    ap.add_argument("--preset", default="veryfast", help="x265 preset")
    ap.add_argument("--audio-bitrate", default="96k", help="AAC audio bitrate")
    ap.add_argument("--force", action="store_true", help="replace output if it exists")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if shutil.which("ffmpeg") is None:
        raise SystemExit("Missing required tool: ffmpeg")

    source = Path(args.media).expanduser().resolve()
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        output = Path.cwd() / output
    if not source.exists():
        raise SystemExit(f"media not found: {source}")
    if output.exists() and not args.force:
        print(f"skip: output exists: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f"{output.stem}.tmp{output.suffix}")
    if tmp.exists():
        tmp.unlink()

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0?",
        "-map",
        "0:a?",
        "-map_metadata",
        "0",
        "-c:v",
        "libx265",
        "-preset",
        args.preset,
        "-crf",
        str(args.crf),
        "-pix_fmt",
        "yuv420p",
        "-tag:v",
        "hvc1",
        "-x265-params",
        "log-level=error",
        "-c:a",
        "aac",
        "-b:a",
        args.audio_bitrate,
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        if tmp.exists():
            tmp.unlink()
        return result.returncode
    if output.exists():
        output.unlink()
    tmp.rename(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

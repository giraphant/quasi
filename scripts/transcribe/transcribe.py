#!/usr/bin/env python3
"""quasi-transcribe — deterministic transcription for process-talk.

Subcommands (JSON to stdout; the skill orchestrates, the agent summarises):

  run      ffmpeg→wav → run the engine ensemble (parallel) → write each engine's
           SRT under processing/talks/<slug>/ and assemble the primary
           vault/talks/<slug>/transcript.md. Names every output path it writes.
  classify read a transcript.md → live | dead verdict (text-only, no decode).
  silent   write the TALK_BODY-conforming silent talk.md for a DEAD recording.

The summary (talk.md) is NOT produced here — that is analyse-agent's job, which
reads the per-engine transcripts this command leaves behind and cross-references
them. This bin stays single-responsibility (cf. bin scope discipline).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/
from transcribe import engines as eng  # noqa: E402
from transcribe.classify import classify_file  # noqa: E402
from transcribe.silent import write_silent  # noqa: E402

# soniox first (best quality + word timestamps) → whisper → apple → parakeet
DEFAULT_ENGINES = ["soniox", "apple", "parakeet"]
PRIMARY_PREFERENCE = ["soniox", "whisper", "apple", "parakeet"]
PARAGRAPH_SECONDS = 45


def _project_root(arg: str | None) -> Path:
    return Path(arg or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def _fmt_ts(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _srt_ts(sec: float) -> str:
    ms = int((sec - int(sec)) * 1000)
    s = int(sec)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d},{ms:03d}"


def _segments_to_srt(segs: list[dict]) -> str:
    out = []
    for i, s in enumerate(segs, 1):
        out.append(f"{i}\n{_srt_ts(s['start'])} --> {_srt_ts(s['end'])}\n{s['text'].strip()}\n")
    return "\n".join(out)


def _extract_wav(media: Path, dst: Path) -> bool:
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(media),
           "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=3600)
        return dst.exists()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[transcribe] ffmpeg failed: {e}\n")
        return False


def _detect_lang(wav: Path) -> str:
    """Cheap language detect via whisper.cpp on a 60s head clip; default 'en'."""
    binary = shutil.which("whisper-cli")
    model = eng.WHISPER_MODELS / "ggml-large-v3-turbo.bin"
    if not binary or not model.exists():
        return "en"
    with tempfile.TemporaryDirectory() as td:
        head = Path(td) / "head.wav"
        try:
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-t", "60",
                            "-i", str(wav), "-ar", "16000", "-ac", "1", str(head)],
                           check=True, capture_output=True, timeout=120)
            p = subprocess.run([binary, "-m", str(model), "-dl", "-f", str(head)],
                               capture_output=True, text=True, timeout=300)
            m = re.search(r"auto-detected language:\s*(\w+)", p.stderr + p.stdout)
            return m.group(1) if m else "en"
        except Exception:  # noqa: BLE001
            return "en"


def _build_transcript_md(title: str, slug: str, segs: list[dict],
                         engines_used: list[str], primary: str) -> str:
    fm = ["---", "type: transcript", f'title: "{title} — 转写"', f"talk: {slug}", "---"]
    note = (f"> 多引擎集成转写({'、'.join(engines_used)};主转写 = {primary})。"
            "未校对,时间戳可用于在视频中定位。")
    lines = [f"# {title} — 转写", "", note, ""]
    para: list[str] = []
    start = None
    for s in segs:
        if start is None:
            start = s["start"]
        para.append(f"`[{_fmt_ts(s['start'])}]` {s['text'].strip()}")
        if s["end"] - start >= PARAGRAPH_SECONDS:
            lines.append("\n".join(para))
            lines.append("")
            para, start = [], None
    if para:
        lines.append("\n".join(para))
    return "\n".join(fm) + "\n\n" + "\n".join(lines) + "\n"


def cmd_run(args) -> int:
    root = _project_root(args.project_dir)
    slug = args.slug
    media = Path(args.media).resolve()
    if not media.exists():
        print(json.dumps({"ok": False, "error": f"media not found: {media}"}))
        return 1
    talk_dir = root / "vault" / "talks" / slug
    # per-engine transcripts are tracked, user-inspectable intermediates (cf.
    # processing/chapters) — kept long-term so the summary can be re-run without
    # re-transcribing (esp. re-paying Soniox). NOT .quasi/ (that is gitignored).
    proc_dir = root / "processing" / "talks" / slug
    talk_dir.mkdir(parents=True, exist_ok=True)
    proc_dir.mkdir(parents=True, exist_ok=True)
    engine_names = [e.strip() for e in (args.engines or ",".join(DEFAULT_ENGINES)).split(",") if e.strip()]

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"
        if not _extract_wav(media, wav):
            print(json.dumps({"ok": False, "error": "ffmpeg extraction failed"}))
            return 1
        lang = args.lang if args.lang != "auto" else _detect_lang(wav)

        results: dict[str, list[dict]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(engine_names)) as pool:
            futs = {pool.submit(eng.run_engine, name, wav, lang): name for name in engine_names}
            for fut in concurrent.futures.as_completed(futs):
                name = futs[fut]
                try:
                    results[name] = fut.result()
                except Exception as e:  # noqa: BLE001
                    sys.stderr.write(f"[transcribe] {name} crashed: {e}\n")
                    results[name] = []

    per_engine = {}
    for name, segs in results.items():
        if segs:
            p = proc_dir / f"transcript.{name}.srt"
            p.write_text(_segments_to_srt(segs), encoding="utf-8")
            per_engine[name] = {"segments": len(segs), "srt": str(p)}

    primary = next((n for n in PRIMARY_PREFERENCE if results.get(n)), None)
    transcript_path = subtitle_path = None
    if primary:
        title = args.title or slug
        md = _build_transcript_md(title, slug, results[primary], list(per_engine), primary)
        transcript_path = talk_dir / "transcript.md"
        transcript_path.write_text(md, encoding="utf-8")
        # also drop a tracked SRT named to match recording.<ext> so video players
        # (VLC / IINA …) auto-load it as subtitles when watching the recording.
        subtitle_path = talk_dir / "recording.srt"
        subtitle_path.write_text(_segments_to_srt(results[primary]), encoding="utf-8")

    print(json.dumps({
        "ok": bool(primary),
        "slug": slug,
        "lang": lang,
        "engines": {n: len(s) for n, s in results.items()},
        "primary_engine": primary,
        "transcript_path": str(transcript_path) if transcript_path else None,
        "subtitle_path": str(subtitle_path) if subtitle_path else None,
        "per_engine": per_engine,
        "error": None if primary else "all engines returned empty",
    }, ensure_ascii=False))
    return 0 if primary else 1


def cmd_classify(args) -> int:
    root = _project_root(args.project_dir)
    path = Path(args.transcript) if args.transcript else root / "vault" / "talks" / args.slug / "transcript.md"
    if not path.exists():
        print(json.dumps({"ok": False, "error": f"transcript not found: {path}"}))
        return 1
    v = classify_file(path)
    print(json.dumps({"ok": True, **v.as_dict()}, ensure_ascii=False))
    return 0


def cmd_silent(args) -> int:
    root = _project_root(args.project_dir)
    talk_dir = root / "vault" / "talks" / args.slug
    out = write_silent(talk_dir, args.title, args.date, args.media, minutes=args.minutes)
    print(json.dumps({"ok": True, "talk_path": str(out)}, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="quasi-transcribe")
    ap.add_argument("--project-dir")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="transcribe a recording with the engine ensemble")
    r.add_argument("--media", required=True)
    r.add_argument("--slug", required=True)
    r.add_argument("--title", default=None)
    r.add_argument("--engines", default=None, help="comma list (default soniox,apple,parakeet)")
    r.add_argument("--lang", default="auto")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("classify", help="live/dead verdict from a transcript")
    c.add_argument("--slug")
    c.add_argument("--transcript")
    c.set_defaults(func=cmd_classify)

    s = sub.add_parser("silent", help="write the silent talk.md template")
    s.add_argument("--slug", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--date", required=True)
    s.add_argument("--media", required=True)
    s.add_argument("--minutes", default="?")
    s.set_defaults(func=cmd_silent)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

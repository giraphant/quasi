"""Unit tests for the deterministic parts of the transcribe ensemble.

Engine subprocess/network calls (soniox/apple/parakeet/whisper) are not exercised
here — only the pure pieces: SRT parsing, Soniox word-boundary cue grouping,
liveness classification, the silent template, and transcript.md assembly.
"""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
sys.path.insert(0, str(PLUGIN_ROOT))

from transcribe import engines  # noqa: E402
from transcribe.classify import classify_text  # noqa: E402
from transcribe.silent import build_silent_talk_md  # noqa: E402
from transcribe.transcribe import _build_transcript_md, _fmt_ts  # noqa: E402
from scripts.typecheck.typecheck import check_file  # noqa: E402


def test_parse_srt_roundtrip():
    srt = "1\n00:00:00,000 --> 00:00:02,500\nHello world.\n\n2\n00:01:05,200 --> 00:01:07,000\nSecond cue.\n"
    segs = engines.parse_srt(srt)
    assert len(segs) == 2
    assert segs[0]["text"] == "Hello world."
    assert abs(segs[0]["end"] - 2.5) < 1e-6
    assert abs(segs[1]["start"] - 65.2) < 1e-6


def test_soniox_grouping_never_splits_midword():
    # "environmental" arrives as two sub-word tokens; a break must not land between them.
    tokens = [
        {"text": "much", "start_ms": 0, "end_ms": 400},
        {"text": " environ", "start_ms": 400, "end_ms": 9000},
        {"text": "mental", "start_ms": 9000, "end_ms": 9300},  # no leading space → same word
        {"text": " globally", "start_ms": 12000, "end_ms": 12500},  # big gap → new cue ok
    ]
    cues = engines._soniox_tokens_to_segments(tokens, gap_ms=700, max_ms=8000)
    joined = " | ".join(c["text"] for c in cues)
    assert "environmental" in joined
    assert "environ |" not in joined and "| mental" not in joined


def test_soniox_grouping_breaks_on_cjk_punctuation():
    tokens = [
        {"text": "第一", "start_ms": 0, "end_ms": 500},
        {"text": "句。", "start_ms": 500, "end_ms": 9000},
        {"text": "第二", "start_ms": 9000, "end_ms": 9500},  # after 。 + over max_ms → break here
    ]
    cues = engines._soniox_tokens_to_segments(tokens, gap_ms=700, max_ms=8000)
    assert len(cues) == 2
    assert cues[0]["text"].endswith("。")


def test_classify_live_vs_dead():
    live = "\n\n".join(f"`[00:{i:02d}]` This is real distinct content number {i} about something." for i in range(15))
    assert classify_text(live).state == "live"

    blank = "\n\n".join(f"`[00:{i:02d}]` [BLANK_AUDIO]" for i in range(12))
    assert classify_text(blank).state == "dead"

    spam = "\n\n".join(f"`[00:{i:02d}]` 请不吝点赞订阅转发打赏支持明镜与点点栏目" for i in range(12))
    assert classify_text(spam).state == "dead"

    assert classify_text("no segments here").state == "empty"


def test_silent_template_conforms_to_talk_body(tmp_path):
    md = build_silent_talk_md("Test Talk", "2024-10-09", "recording.mp4", minutes="52")
    fp = tmp_path / "talk.md"
    fp.write_text(md, encoding="utf-8")
    result = check_file(fp)
    assert result["frontmatter_errors"] == []
    assert result["body_violations"] == []


def test_build_transcript_md_is_valid_transcript(tmp_path):
    segs = [
        {"start": 0.0, "end": 5.0, "text": "Opening remarks."},
        {"start": 5.0, "end": 50.0, "text": "A long stretch that should force a new paragraph."},
        {"start": 50.0, "end": 55.0, "text": "Final point."},
    ]
    md = _build_transcript_md("My Talk", "my-talk-20240101", segs, ["soniox", "apple"], "soniox")
    fp = tmp_path / "transcript.md"
    fp.write_text(md, encoding="utf-8")
    result = check_file(fp)
    assert result["type"] == "transcript"
    assert result["frontmatter_errors"] == []
    assert "`[00:00]`" in md and "主转写 = soniox" in md


def test_fmt_ts_drops_zero_hour():
    assert _fmt_ts(65) == "01:05"
    assert _fmt_ts(3725) == "01:02:05"

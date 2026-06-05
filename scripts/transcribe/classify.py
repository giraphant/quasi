"""Liveness classification: decide a transcript is live vs DEAD (no usable audio).

Many screen recordings never captured the mic (volume ≈ −91 dB). whisper then
emits `[BLANK_AUDIO]` (EN) or subtitle-spam hallucinations (ZH, "请点赞订阅" …).
Judging from the transcript *text* is much faster than decoding the whole file
for a volume scan. DEAD talks get the silent template (silent.py), not a forced
summary.

Pure + text-only: no ffmpeg, no models, no network. Unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# whisper's known silence-garbage / subtitle-volunteer hallucinations
SPAM_PHRASES = (
    "[BLANK_AUDIO]",
    "请不吝点赞",
    "请点赞",
    "优优独播",
    "中文字幕志愿者",
    "明镜需要您的支持",
    "Thanks for watching",
    "字幕由",
    "MBC 뉴스",
    "字幕志愿者",
)

# a transcript paragraph that begins with a timestamp marker, e.g. `[00:00]` …
_SEG_RE = re.compile(r"^`?\[\d{1,2}:\d{2}")
_TS_RE = re.compile(r"`?\[\d{1,2}:\d{2}(?::\d{2})?\]`?")


@dataclass
class Verdict:
    state: str          # "live" | "dead" | "empty"
    total: int          # segment count
    uniq_ratio: float   # unique segment texts / total
    chars: int          # non-timestamp char count
    spam_hits: int      # total SPAM phrase occurrences
    blank_dominant: bool
    reason: str

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "total": self.total,
            "uniq_ratio": round(self.uniq_ratio, 3),
            "chars": self.chars,
            "spam_hits": self.spam_hits,
            "blank_dominant": self.blank_dominant,
            "reason": self.reason,
        }


def _segments(body: str) -> list[str]:
    """Return the timestamped segment paragraphs' *text* (timestamp stripped)."""
    out: list[str] = []
    for para in body.split("\n\n"):
        p = para.strip()
        if _SEG_RE.match(p):
            out.append(_TS_RE.sub("", p).strip())
    return out


def classify_text(body: str) -> Verdict:
    """Classify a transcript body (markdown after frontmatter)."""
    segs = _segments(body)
    total = len(segs)
    if total == 0:
        return Verdict("empty", 0, 0.0, 0, 0, False, "no timestamped segments")

    blank = sum(1 for s in segs if "[BLANK_AUDIO]" in s)
    spam_hits = sum(body.count(p) for p in SPAM_PHRASES)
    uniq = len({s for s in segs}) / total
    chars = sum(len(s) for s in segs)
    blank_dominant = blank >= max(3, total * 0.4)

    if blank_dominant:
        return Verdict("dead", total, uniq, chars, spam_hits, True,
                       f"[BLANK_AUDIO] dominates ({blank}/{total})")
    if spam_hits >= 8:
        return Verdict("dead", total, uniq, chars, spam_hits, False,
                       f"subtitle-spam hallucination (spam_hits={spam_hits})")
    if total >= 10 and uniq < 0.25:
        return Verdict("dead", total, uniq, chars, spam_hits, False,
                       f"repetition loop (uniq_ratio={uniq:.2f})")
    if chars < 200:
        return Verdict("dead", total, uniq, chars, spam_hits, False,
                       f"too little content (chars={chars})")
    return Verdict("live", total, uniq, chars, spam_hits, False, "usable audio")


def classify_file(path) -> Verdict:
    from pathlib import Path
    text = Path(path).read_text(encoding="utf-8")
    # strip YAML frontmatter if present
    if text.startswith("---"):
        parts = text.split("\n---", 1)
        if len(parts) == 2:
            text = parts[1]
    return classify_text(text)

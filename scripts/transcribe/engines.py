"""Pluggable STT engines for the process-talk ensemble.

Each engine is a function `wav_path -> list[Segment]` where
`Segment = {"start": float, "end": float, "text": str}` (seconds). Engines are
independent and fail soft: on any error they return `[]` and log to stderr so
the ensemble degrades gracefully (the LLM cross-references whatever survived).

Engines (benchmarked QUA-182):
- soniox   : cloud stt-async-v4, word timestamps, best ZH/accent. Needs key.
- apple    : on-device SpeechTranscriber (macOS 26), free, EN+ZH, fastest.
- parakeet : parakeet-tdt-0.6b-v3 via mlx, cleanest EN; EUROPEAN ONLY (no ZH).
- whisper  : whisper.cpp large-v3-turbo, native SRT; -mc0 anti-hallucination.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or (Path.home() / ".cache" / "quasi"))
WHISPER_MODELS = Path(os.environ.get("QUASI_WHISPER_MODELS") or (Path.home() / ".cache" / "whisper-models"))

# Parakeet v3 multilingual = 25 European languages; Chinese/Japanese/Korean etc. unsupported.
PARAKEET_LANGS = {
    "en", "fr", "de", "es", "it", "pt", "nl", "pl", "ru", "uk", "cs", "sk",
    "sl", "hr", "bg", "ro", "hu", "fi", "sv", "da", "no", "et", "lv", "lt", "el",
}


def _log(msg: str) -> None:
    sys.stderr.write(f"[engines] {msg}\n")


# ─── SRT helpers ──────────────────────────────────────────────

_SRT_TS = re.compile(r"(\d\d):(\d\d):(\d\d)[,.](\d{1,3})")


def _ts_to_s(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_srt(text: str) -> list[dict]:
    """Parse SRT text into segments [{start,end,text}]."""
    segs: list[dict] = []
    block: list[str] = []
    for line in text.splitlines() + [""]:
        if line.strip() == "":
            if block:
                ts_line = next((l for l in block if "-->" in l), None)
                if ts_line:
                    times = _SRT_TS.findall(ts_line)
                    if len(times) >= 2:
                        start = _ts_to_s(*times[0])
                        end = _ts_to_s(*times[1])
                        idx = block.index(ts_line)
                        txt = " ".join(l.strip() for l in block[idx + 1:] if l.strip())
                        if txt:
                            segs.append({"start": start, "end": end, "text": txt})
                block = []
        else:
            block.append(line)
    return segs


# ─── whisper.cpp ──────────────────────────────────────────────

def run_whisper(wav: Path, lang: str | None = None,
                model: str = "ggml-large-v3-turbo.bin") -> list[dict]:
    binary = shutil.which("whisper-cli")
    model_path = WHISPER_MODELS / model
    if not binary or not model_path.exists():
        _log(f"whisper unavailable (bin={bool(binary)}, model={model_path.exists()})")
        return []
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out"
        cmd = [binary, "-m", str(model_path), "-t", "8", "-mc", "0",
               "-f", str(wav), "-osrt", "-of", str(out)]
        if lang:
            cmd += ["-l", lang]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=7200)
        except Exception as e:  # noqa: BLE001
            _log(f"whisper failed: {e}")
            return []
        srt = out.with_suffix(".srt")
        return parse_srt(srt.read_text(encoding="utf-8")) if srt.exists() else []


# ─── parakeet-mlx ─────────────────────────────────────────────

def run_parakeet(wav: Path, model: str = "mlx-community/parakeet-tdt-0.6b-v3") -> list[dict]:
    if not shutil.which("uvx"):
        _log("parakeet unavailable (no uvx)")
        return []
    with tempfile.TemporaryDirectory() as td:
        cmd = ["uvx", "--from", "parakeet-mlx", "parakeet-mlx",
               "--model", model, "--output-format", "srt", "--output-dir", td, str(wav)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=7200)
        except Exception as e:  # noqa: BLE001
            _log(f"parakeet failed: {e}")
            return []
        srt = Path(td) / (Path(wav).stem + ".srt")
        return parse_srt(srt.read_text(encoding="utf-8")) if srt.exists() else []


# ─── Apple SpeechTranscriber (macOS 26) ───────────────────────

def _ensure_apple_binary() -> Path | None:
    if sys.platform != "darwin" or not shutil.which("swiftc"):
        return None
    src = Path(__file__).with_name("apple_stt.swift")
    binary = DATA_DIR / "bin" / "apple-stt"
    if binary.exists() and binary.stat().st_mtime >= src.stat().st_mtime:
        return binary
    binary.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["swiftc", "-O", "-parse-as-library", str(src), "-o", str(binary)],
                       check=True, capture_output=True, timeout=300)
    except Exception as e:  # noqa: BLE001
        _log(f"apple compile failed: {e}")
        return None
    return binary


def run_apple(wav: Path, locale: str = "en-US") -> list[dict]:
    binary = _ensure_apple_binary()
    if not binary:
        _log("apple unavailable (need macOS 26 + swiftc)")
        return []
    try:
        p = subprocess.run([str(binary), str(wav), locale],
                           check=True, capture_output=True, text=True, timeout=7200)
    except Exception as e:  # noqa: BLE001
        _log(f"apple failed: {e}")
        return []
    return parse_srt(p.stdout)


# ─── Soniox (cloud stt-async-v4) ──────────────────────────────

SONIOX_BASE = "https://api.soniox.com"
SONIOX_MODEL = "stt-async-v4"


def _soniox_req(method, path, key, *, body=None, headers=None):
    h = {"Authorization": f"Bearer {key}"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(SONIOX_BASE + path, data=body, method=method, headers=h)
    with urllib.request.urlopen(r, timeout=180) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def run_soniox(wav: Path, lang_hints: tuple[str, ...] = ("en", "zh"),
               key: str | None = None) -> list[dict]:
    key = key or os.environ.get("QUASI_SONIOX_API_KEY") or os.environ.get("SONIOX_API_KEY")
    if not key:
        _log("soniox unavailable (no QUASI_SONIOX_API_KEY)")
        return []
    fid = tid = None
    try:
        # 1) upload
        boundary = "----b" + uuid.uuid4().hex
        fname = Path(wav).name
        ctype = mimetypes.guess_type(fname)[0] or "audio/wav"
        data = Path(wav).read_bytes()
        mp = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'.encode(),
            f"Content-Type: {ctype}\r\n\r\n".encode(), data, b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        fid = _soniox_req("POST", "/v1/files", key, body=mp,
                          headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})["id"]
        # 2) create transcription
        cbody = {"model": SONIOX_MODEL, "file_id": fid}
        if lang_hints:
            cbody["language_hints"] = list(lang_hints)
        tid = _soniox_req("POST", "/v1/transcriptions", key,
                          body=json.dumps(cbody).encode(),
                          headers={"Content-Type": "application/json"})["id"]
        # 3) poll
        deadline = time.time() + 1800
        while time.time() < deadline:
            st = _soniox_req("GET", f"/v1/transcriptions/{tid}", key).get("status", "")
            if st == "completed":
                break
            if st == "error":
                _log("soniox transcription error")
                return []
            time.sleep(1.0)
        # 4) fetch transcript tokens → segments
        res = _soniox_req("GET", f"/v1/transcriptions/{tid}/transcript", key)
        return _soniox_tokens_to_segments(res.get("tokens") or [])
    except Exception as e:  # noqa: BLE001
        _log(f"soniox failed: {e}")
        return []
    finally:
        for p in ([f"/v1/transcriptions/{tid}"] if tid else []) + ([f"/v1/files/{fid}"] if fid else []):
            try:
                _soniox_req("DELETE", p, key)
            except Exception:  # noqa: BLE001
                pass


_CJK_BREAK = "，。！？、；：,.!?;:"


def _soniox_tokens_to_segments(tokens: list[dict], gap_ms=700, max_ms=8000) -> list[dict]:
    """Group Soniox word tokens into cues, breaking ONLY at word boundaries.

    Soniox tokens are sub-word: "environmental" arrives as "environ"+"mental",
    with the leading space carried on the first token of each word. Breaking a
    cue mid-word produces "environ / mental" splits, so we only allow a break
    before a token that *starts a new word* (leading whitespace, or — for CJK
    which has no spaces — a token right after sentence punctuation).
    """
    cues: list[dict] = []
    cur: list[str] = []
    start = last = None
    prev_text = ""
    for t in tokens:
        txt = t.get("text", "")
        if txt == "<end>" or t.get("translation_status") == "translation":
            continue
        s, e = t.get("start_ms"), t.get("end_ms")
        if s is None or e is None:
            continue
        word_start = (not cur) or txt[:1].isspace() or (prev_text[-1:] in _CJK_BREAK)
        if cur and word_start and last is not None and (s - last > gap_ms or e - start > max_ms):
            cues.append({"start": start / 1000, "end": last / 1000, "text": "".join(cur).strip()})
            cur, start = [], None
        if start is None:
            start = s
        cur.append(txt)
        last = e
        prev_text = txt
    if cur and start is not None and last is not None:
        cues.append({"start": start / 1000, "end": last / 1000, "text": "".join(cur).strip()})
    return cues


# ─── registry ─────────────────────────────────────────────────

def _locale_for(lang: str) -> str:
    return {"zh": "zh-CN", "en": "en-US"}.get(lang, f"{lang}-{lang.upper()}" if len(lang) == 2 else lang)


def run_engine(name: str, wav: Path, lang: str) -> list[dict]:
    """Dispatch one engine by name. `lang` is a 2-letter code or 'auto'."""
    if name == "soniox":
        hints = ("en", "zh") if lang == "auto" else (lang,)
        return run_soniox(wav, lang_hints=hints)
    if name == "apple":
        return run_apple(wav, locale=_locale_for("en" if lang == "auto" else lang))
    if name == "parakeet":
        if lang not in ("auto",) and lang not in PARAKEET_LANGS:
            _log(f"parakeet skipped (lang={lang} unsupported)")
            return []
        return run_parakeet(wav)
    if name == "whisper":
        return run_whisper(wav, lang=None if lang == "auto" else lang)
    _log(f"unknown engine: {name}")
    return []

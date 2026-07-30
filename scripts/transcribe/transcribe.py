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
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/
from transcribe import engines as eng  # noqa: E402
from transcribe.classify import classify_file  # noqa: E402
from transcribe.silent import build_silent_talk_md, write_silent_atomic  # noqa: E402
from transcribe.talk_commit import (  # noqa: E402
    MANIFEST_NAME,
    MANIFEST_SCHEMA,
    TalkFailure,
    artifact_row,
    commit_transcription,
    emit_json,
    inspect_source,
    load_manifest,
    project_relative,
    regular_file,
    request_fingerprint,
    safe_output,
    sha256_file,
    validate_date,
    validate_engines,
    validate_slug,
    validate_text,
)
from talk import compress_media  # noqa: E402

# soniox first (best quality + word timestamps) → whisper → apple → parakeet
DEFAULT_ENGINES = ["soniox", "apple", "parakeet"]
PRIMARY_PREFERENCE = ["soniox", "whisper", "apple", "parakeet"]
PARAGRAPH_SECONDS = 45
TRANSCRIBE_SCHEMA = "quasi.operation.talk.transcribe.receipt/0.1"
OBSERVE_SCHEMA = "quasi.operation.talk.observe.receipt/0.1"
CLASSIFY_SCHEMA = "quasi.operation.talk.classify.receipt/0.1"
SILENT_SCHEMA = "quasi.operation.talk.render-silent.receipt/0.1"
_LANG_RE = re.compile(r"(?:auto|[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)")


def _project_root(arg: str | None) -> Path:
    return Path(arg or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def _failure(
    code: str,
    message: str | None,
    operation_key: str,
    *,
    status: str = "failed",
    outcome: str = "known",
    exit_code: int = 1,
) -> TalkFailure:
    return TalkFailure(
        code,
        message,
        operation_key=operation_key,
        status=status,
        outcome=outcome,
        exit_code=exit_code,
    )


def _material_key(slug: str | None) -> str | None:
    return f"talk:{slug}" if slug else None


def _relative_input(source: dict | None, root: Path, operation_key: str) -> str | None:
    if source is None:
        return None
    return project_relative(Path(source["path"]), root, operation_key=operation_key)


def _receipt_input(source: dict | None, root: Path, operation_key: str) -> str | None:
    try:
        return _relative_input(source, root, operation_key)
    except TalkFailure:
        return None


def _parse_engine_names(raw: str | None, operation_key: str) -> list[str]:
    values = [
        item.strip()
        for item in (raw or ",".join(DEFAULT_ENGINES)).split(",")
        if item.strip()
    ]
    return validate_engines(values, operation_key=operation_key)


def _validate_lang(value: object, operation_key: str) -> str:
    if not isinstance(value, str) or _LANG_RE.fullmatch(value) is None:
        raise _failure(
            "invalid_lang",
            "lang must be auto or a bounded BCP-47-like language tag",
            operation_key,
            exit_code=2,
        )
    return value


def _manifest_failure(code: str, message: str) -> dict:
    return {
        "code": code,
        "operation_key": "talk.transcribe",
        "outcome": "known",
        "retryable": False,
        "message": message,
    }


def _artifact_from_stage(role: str, staged: Path, target: Path, root: Path) -> dict:
    return {
        "role": role,
        "path": target.relative_to(root).as_posix(),
        "sha256": sha256_file(staged),
        "size": staged.stat().st_size,
    }


def _strict_transcribe_receipt(
    *,
    root: Path,
    slug: str | None,
    requested_input_path: str | None,
    source: dict | None,
    title: str | None,
    lang: str | None,
    engines: list[str],
    fingerprint: str | None,
    manifest: dict | None,
    disposition: str | None,
    previous_manifest_preserved: bool,
    error: TalkFailure | None,
) -> dict:
    output_dir = root / "processing" / "talks" / (slug or "__invalid__")
    talk_dir = root / "vault" / "talks" / (slug or "__invalid__")
    manifest_path = output_dir / MANIFEST_NAME
    manifest_exists = regular_file(manifest_path) if error is None else False
    manifest_fingerprint = sha256_file(manifest_path) if manifest_exists else None
    rows = list((manifest or {}).get("per_engine", []))
    if not rows and engines:
        rows = [
            {
                "name": name,
                "status": "failed",
                "segments": 0,
                "path": None,
                "sha256": None,
            }
            for name in engines
        ]
    artifacts = list((manifest or {}).get("artifacts", []))
    primary = (manifest or {}).get("primary_engine")
    transcript = next(
        (row["path"] for row in artifacts if row["role"] == "transcript"),
        None,
    )
    subtitle = next(
        (row["path"] for row in artifacts if row["role"] == "subtitle"),
        None,
    )
    status = error.status if error is not None else (manifest or {}).get("status", "blocked")
    failure = error.as_dict() if error is not None else (manifest or {}).get("failure")
    if status != "succeeded":
        disposition = None
    return {
        "schema_version": TRANSCRIBE_SCHEMA,
        "key": "talk.transcribe",
        "effect": "writer",
        "status": status,
        "attempt": 1,
        "material_key": _material_key(slug),
        "slug": slug,
        "input_path": requested_input_path,
        "output_dir": (
            output_dir.relative_to(root).as_posix() if slug is not None else None
        ),
        "talk_dir": talk_dir.relative_to(root).as_posix() if slug is not None else None,
        "manifest_path": (
            manifest_path.relative_to(root).as_posix() if slug is not None else None
        ),
        "manifest_exists": manifest_exists,
        "manifest_fingerprint": manifest_fingerprint,
        "request_fingerprint": fingerprint,
        "source_sha256": source.get("sha256") if source else None,
        "lang": lang,
        "title": title,
        "engines": list(engines),
        "primary_engine": primary,
        "transcript_path": transcript,
        "subtitle_path": subtitle,
        "per_engine": rows,
        "artifacts": artifacts,
        "disposition": disposition,
        "previous_manifest_preserved": previous_manifest_preserved,
        "failure": failure,
    }


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
    fm = [
        "---",
        "type: transcript",
        f"title: {json.dumps(f'{title} — 转写', ensure_ascii=False)}",
        f"talk: {slug}",
        "---",
    ]
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
    slug: str | None = None
    source: dict | None = None
    title: str | None = None
    lang: str | None = None
    engine_names: list[str] = []
    fingerprint: str | None = None
    manifest: dict | None = None
    disposition: str | None = None
    preserved = False
    error: TalkFailure | None = None
    try:
        slug = validate_slug(args.slug, operation_key="talk.transcribe")
        title = validate_text(
            args.title or slug,
            "title",
            operation_key="talk.transcribe",
            max_length=280,
        )
        requested_lang = _validate_lang(args.lang, "talk.transcribe")
        engine_names = _parse_engine_names(args.engines, "talk.transcribe")
        media = Path(args.media)
        if not media.is_absolute():
            media = root / media
        source = inspect_source(media, operation_key="talk.transcribe")
        fingerprint = request_fingerprint(
            source, engine_names, requested_lang, title
        )

        def build(stage_proc: Path, stage_talk: Path) -> tuple[dict, dict[Path, Path]]:
            results: dict[str, list[dict]] = {}
            crashed: set[str] = set()
            with tempfile.TemporaryDirectory() as temp_dir:
                wav = Path(temp_dir) / "audio.wav"
                if not _extract_wav(Path(source["path"]), wav):
                    failure = _manifest_failure(
                        "ffmpeg_failed", "ffmpeg extraction failed"
                    )
                    failed_manifest = {
                        "schema_version": MANIFEST_SCHEMA,
                        "slug": slug,
                        "request_fingerprint": fingerprint,
                        "source": source,
                        "title": title,
                        "lang": requested_lang,
                        "engines": engine_names,
                        "status": "failed",
                        "primary_engine": None,
                        "per_engine": [
                            {
                                "name": name,
                                "status": "empty",
                                "segments": 0,
                                "path": None,
                                "sha256": None,
                            }
                            for name in engine_names
                        ],
                        "artifacts": [],
                        "failure": failure,
                    }
                    return failed_manifest, {}
                selected_lang = (
                    requested_lang
                    if requested_lang != "auto"
                    else _detect_lang(wav)
                )
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=len(engine_names)
                ) as pool:
                    futures = {
                        pool.submit(eng.run_engine, name, wav, selected_lang): name
                        for name in engine_names
                    }
                    for future in concurrent.futures.as_completed(futures):
                        name = futures[future]
                        try:
                            value = future.result()
                            results[name] = value if isinstance(value, list) else []
                        except Exception as exc:  # noqa: BLE001
                            sys.stderr.write(
                                f"[transcribe] {name} crashed: {exc}\n"
                            )
                            results[name] = []
                            crashed.add(name)

            final_proc = root / "processing" / "talks" / slug
            final_talk = root / "vault" / "talks" / slug
            staged_files: dict[Path, Path] = {}
            artifacts: list[dict] = []
            rows: list[dict] = []
            for name in engine_names:
                segments = results.get(name, [])
                path: str | None = None
                digest: str | None = None
                if segments:
                    staged = stage_proc / f"transcript.{name}.srt"
                    staged.write_text(
                        _segments_to_srt(segments), encoding="utf-8"
                    )
                    target = final_proc / staged.name
                    row = _artifact_from_stage(
                        "engine_transcript", staged, target, root
                    )
                    artifacts.append(row)
                    staged_files[target] = staged
                    path = row["path"]
                    digest = row["sha256"]
                rows.append(
                    {
                        "name": name,
                        "status": (
                            "succeeded"
                            if segments
                            else ("failed" if name in crashed else "empty")
                        ),
                        "segments": len(segments),
                        "path": path,
                        "sha256": digest,
                    }
                )

            primary = next(
                (name for name in PRIMARY_PREFERENCE if results.get(name)), None
            )
            failure = None
            status = "succeeded"
            if primary is None:
                status = "failed"
                failure = _manifest_failure(
                    "all_engines_empty", "all engines returned empty"
                )
                # A failed attempt has no product artifacts.  It is still
                # committed as a durable attempt receipt so the same request
                # cannot silently re-charge a remote engine.
                staged_files.clear()
                artifacts.clear()
                rows = [
                    {**row, "path": None, "sha256": None}
                    for row in rows
                ]
            else:
                transcript_stage = stage_talk / "transcript.md"
                transcript_stage.write_text(
                    _build_transcript_md(
                        title,
                        slug,
                        results[primary],
                        [row["name"] for row in rows if row["status"] == "succeeded"],
                        primary,
                    ),
                    encoding="utf-8",
                )
                transcript_target = final_talk / "transcript.md"
                artifacts.append(
                    _artifact_from_stage(
                        "transcript",
                        transcript_stage,
                        transcript_target,
                        root,
                    )
                )
                staged_files[transcript_target] = transcript_stage
                subtitle_stage = stage_talk / "recording.srt"
                subtitle_stage.write_text(
                    _segments_to_srt(results[primary]), encoding="utf-8"
                )
                subtitle_target = final_talk / "recording.srt"
                artifacts.append(
                    _artifact_from_stage(
                        "subtitle", subtitle_stage, subtitle_target, root
                    )
                )
                staged_files[subtitle_target] = subtitle_stage

            built_manifest = {
                "schema_version": MANIFEST_SCHEMA,
                "slug": slug,
                "request_fingerprint": fingerprint,
                "source": source,
                "title": title,
                "lang": requested_lang,
                "engines": engine_names,
                "status": status,
                "primary_engine": primary,
                "per_engine": rows,
                "artifacts": artifacts,
                "failure": failure,
            }
            return built_manifest, staged_files

        manifest, disposition, preserved = commit_transcription(
            root=root,
            slug=slug,
            source=source,
            title=title,
            lang=requested_lang,
            engines=engine_names,
            fingerprint=fingerprint,
            build=build,
        )
        lang = manifest["lang"]
    except TalkFailure as exc:
        error = exc
    except Exception as exc:  # fail closed: the writer may have committed
        error = _failure(
            "commit_failed",
            f"transcription transaction failed: {exc}",
            "talk.transcribe",
            status="blocked",
            outcome="unknown",
        )

    receipt = _strict_transcribe_receipt(
        root=root,
        slug=slug,
        requested_input_path=args.media,
        source=source,
        title=title,
        lang=lang or args.lang,
        engines=engine_names,
        fingerprint=fingerprint,
        manifest=manifest,
        disposition=disposition,
        previous_manifest_preserved=preserved,
        error=error,
    )
    if args.json:
        emit_json(receipt)
    else:
        per_engine = {
            row["name"]: {
                "segments": row["segments"],
                "srt": row["path"],
            }
            for row in receipt["per_engine"]
            if row["path"] is not None
        }
        print(
            json.dumps(
                {
                    "ok": receipt["status"] == "succeeded",
                    "slug": slug,
                    "lang": receipt["lang"],
                    "engines": {
                        row["name"]: row["segments"]
                        for row in receipt["per_engine"]
                    },
                    "primary_engine": receipt["primary_engine"],
                    "transcript_path": receipt["transcript_path"],
                    "subtitle_path": receipt["subtitle_path"],
                    "per_engine": per_engine,
                    "error": (
                        receipt["failure"]["message"]
                        if receipt["failure"] is not None
                        else None
                    ),
                },
                ensure_ascii=False,
            )
        )
    return 0 if receipt["status"] == "succeeded" else (error.exit_code if error else 1)


def _observe_receipt(
    *,
    root: Path,
    slug: str | None,
    requested_input_path: str | None,
    source: dict | None,
    fingerprint: str | None,
    manifest: dict | None,
    classification: str | None,
    prepared_identity: tuple[Path, str, int] | None,
    error: TalkFailure | None,
) -> dict:
    output_dir = root / "processing" / "talks" / (slug or "__invalid__")
    talk_dir = root / "vault" / "talks" / (slug or "__invalid__")
    manifest_path = output_dir / MANIFEST_NAME
    transcript_path = talk_dir / "transcript.md"
    subtitle_path = talk_dir / "recording.srt"
    talk_path = talk_dir / "talk.md"
    prepared = (
        prepared_identity[0]
        if prepared_identity is not None and error is None
        else None
    )
    talk_exists = regular_file(talk_path) if error is None else False
    manifest_exists = regular_file(manifest_path) if error is None else False
    visible_artifacts = (
        list((manifest or {}).get("artifacts", [])) if error is None else []
    )
    if prepared is not None:
        visible_artifacts.append(
            {
                "role": "prepared_media",
                "path": prepared.relative_to(root).as_posix(),
                "sha256": prepared_identity[1],
                "size": prepared_identity[2],
            }
        )
    if talk_exists and not (manifest_exists and fingerprint is None):
        visible_artifacts.append(artifact_row("canonical", talk_path, root))
    return {
        "schema_version": OBSERVE_SCHEMA,
        "key": "talk.observe",
        "effect": "readonly",
        "status": error.status if error is not None else "succeeded",
        "attempt": 1,
        "material_key": _material_key(slug),
        "slug": slug,
        "input_path": requested_input_path,
        "output_dir": (
            output_dir.relative_to(root).as_posix() if slug is not None else None
        ),
        "manifest_path": (
            manifest_path.relative_to(root).as_posix() if slug is not None else None
        ),
        "manifest_exists": manifest_exists,
        "request_fingerprint": fingerprint,
        "source_sha256": source.get("sha256") if source else None,
        "source_size": source.get("size") if source else 0,
        "prepared_path": (
            prepared.relative_to(root).as_posix() if prepared is not None else None
        ),
        "prepared_sha256": prepared_identity[1] if prepared_identity is not None else None,
        "transcript_path": (
            transcript_path.relative_to(root).as_posix()
            if slug is not None and manifest_exists
            else None
        ),
        "subtitle_path": (
            subtitle_path.relative_to(root).as_posix()
            if slug is not None and manifest_exists
            else None
        ),
        "talk_path": talk_path.relative_to(root).as_posix() if slug is not None else None,
        "talk_exists": talk_exists,
        "talk_sha256": sha256_file(talk_path) if talk_exists else None,
        "classification": classification,
        "artifacts": visible_artifacts,
        "failure": error.as_dict() if error is not None else None,
    }


def cmd_observe(args) -> int:
    root = _project_root(args.project_dir)
    slug: str | None = None
    source: dict | None = None
    fingerprint: str | None = None
    manifest: dict | None = None
    classification: str | None = None
    prepared_identity: tuple[Path, str, int] | None = None
    error: TalkFailure | None = None
    try:
        slug = validate_slug(args.slug, operation_key="talk.observe")
        title = validate_text(
            args.title,
            "title",
            operation_key="talk.observe",
            max_length=280,
        )
        validate_date(args.date, operation_key="talk.observe")
        lang = _validate_lang(args.lang, "talk.observe")
        engines = _parse_engine_names(args.engines, "talk.observe")
        media = Path(args.media)
        if not media.is_absolute():
            media = root / media
        source = inspect_source(media, operation_key="talk.observe")
        output_dir = safe_output(
            root / "processing" / "talks" / slug, root, operation_key="talk.observe"
        )
        talk_dir = safe_output(
            root / "vault" / "talks" / slug, root, operation_key="talk.observe"
        )
        manifest_path = safe_output(
            output_dir / MANIFEST_NAME, root, operation_key="talk.observe"
        )
        safe_output(talk_dir / "talk.md", root, operation_key="talk.observe")
        prepared_path = talk_dir / "recording.mp4"
        try:
            prepared_info = compress_media.inspect_prepared(
                prepared_path, source["sha256"]
            )
        except compress_media.PrepareFailure as exc:
            raise _failure(
                exc.code,
                exc.message,
                "talk.observe",
                status=exc.status,
                outcome=exc.outcome,
            ) from exc
        if prepared_info is not None:
            prepared_identity = (
                prepared_path,
                prepared_info[0],
                prepared_info[1],
            )
        transcription_source = (
            inspect_source(prepared_path, operation_key="talk.observe")
            if prepared_identity is not None
            else source
        )
        fingerprint = request_fingerprint(
            transcription_source, engines, lang, title
        )
        manifest = load_manifest(
            manifest_path, root, slug, operation_key="talk.observe"
        )
        managed_without_manifest = [
            talk_dir / "transcript.md",
            talk_dir / "recording.srt",
            talk_dir / "talk.md",
        ]
        if manifest is None:
            if any(path.exists() or path.is_symlink() for path in managed_without_manifest):
                raise _failure(
                    "uncommitted_artifacts",
                    "Talk products exist without a trusted transcription manifest",
                    "talk.observe",
                    status="blocked",
                    outcome="unknown",
                )
            # An observation reports the fingerprint of a committed
            # transcription generation, not a prediction for work that has
            # not happened yet.  Keep the missing state unambiguous for the
            # graph's reconcile contract.
            fingerprint = None
        else:
            if (
                manifest["request_fingerprint"] != fingerprint
                or manifest["source"].get("sha256")
                != transcription_source.get("sha256")
                or manifest["source"].get("size")
                != transcription_source.get("size")
            ):
                # The old generation is internally trustworthy but belongs to
                # a different explicit request.  Do not advertise its
                # transcript as reusable; transcribe may replace it under the
                # same transactional lock.
                manifest = None
                fingerprint = None
            else:
                transcript = talk_dir / "transcript.md"
                if manifest["status"] == "succeeded":
                    if not regular_file(transcript):
                        raise _failure(
                            "artifact_set_incomplete",
                            "committed transcript is missing",
                            "talk.observe",
                            status="blocked",
                            outcome="unknown",
                        )
                    classification = classify_file(transcript).state
                else:
                    raise _failure(
                        "prior_transcription_failed",
                        (
                            manifest["failure"]["message"]
                            or "the identical transcription request previously failed"
                        ),
                        "talk.observe",
                    )
        for candidate in (
            talk_dir / "recording.mp4",
            talk_dir / "recording.m4a",
            talk_dir / "recording.wav",
            talk_dir / "talk.md",
        ):
            if (candidate.exists() or candidate.is_symlink()) and not regular_file(
                candidate
            ):
                raise _failure(
                    "observed_path_not_regular",
                    f"observed Talk path is not a regular file: {candidate}",
                    "talk.observe",
                    status="blocked",
                    outcome="unknown",
                )
    except TalkFailure as exc:
        error = exc
    except Exception as exc:
        error = _failure(
            "observation_failed",
            f"cannot observe Talk state: {exc}",
            "talk.observe",
            status="blocked",
            outcome="unknown",
        )
    receipt = _observe_receipt(
        root=root,
        slug=slug,
        requested_input_path=args.media,
        source=source,
        fingerprint=fingerprint,
        manifest=manifest,
        classification=classification,
        prepared_identity=prepared_identity,
        error=error,
    )
    emit_json(receipt)
    return 0 if receipt["status"] == "succeeded" else (error.exit_code if error else 1)


def cmd_classify(args) -> int:
    root = _project_root(args.project_dir)
    slug: str | None = None
    source: dict | None = None
    verdict = None
    error: TalkFailure | None = None
    try:
        if args.slug:
            slug = validate_slug(args.slug, operation_key="talk.classify")
        path = (
            Path(args.transcript)
            if args.transcript
            else root / "vault" / "talks" / slug / "transcript.md"
        )
        if not path.is_absolute():
            path = root / path
        source = inspect_source(path, operation_key="talk.classify")
        if args.json:
            _relative_input(source, root, "talk.classify")
        if slug is None:
            parts = Path(_relative_input(source, root, "talk.classify")).parts
            if len(parts) >= 4 and parts[:2] == ("vault", "talks"):
                slug = validate_slug(parts[2], operation_key="talk.classify")
            else:
                raise _failure(
                    "invalid_transcript_path",
                    "strict classify input must be inside vault/talks/{slug}",
                    "talk.classify",
                    exit_code=2,
                )
        verdict = classify_file(Path(source["path"]))
    except TalkFailure as exc:
        error = exc
    except Exception as exc:
        error = _failure(
            "classification_failed",
            f"cannot classify transcript: {exc}",
            "talk.classify",
        )
    if args.json:
        receipt = {
            "schema_version": CLASSIFY_SCHEMA,
            "key": "talk.classify",
            "effect": "readonly",
            "status": error.status if error is not None else "succeeded",
            "attempt": 1,
            "material_key": _material_key(slug),
            "input_path": (
                _receipt_input(source, root, "talk.classify")
                if source is not None
                else None
            ),
            "input_sha256": source.get("sha256") if source else None,
            "signal": verdict.state if verdict is not None else None,
            "machine_signals": (
                {
                    "total": verdict.total,
                    "uniq_ratio": round(verdict.uniq_ratio, 3),
                    "chars": verdict.chars,
                    "spam_hits": verdict.spam_hits,
                    "blank_dominant": verdict.blank_dominant,
                    "reason": verdict.reason,
                }
                if verdict is not None
                else None
            ),
            "failure": error.as_dict() if error is not None else None,
        }
        emit_json(receipt)
    elif verdict is not None:
        print(json.dumps({"ok": True, **verdict.as_dict()}, ensure_ascii=False))
    else:
        print(
            json.dumps(
                {"ok": False, "error": error.message if error else "classification failed"},
                ensure_ascii=False,
            )
        )
    return 0 if error is None else error.exit_code


def cmd_silent(args) -> int:
    root = _project_root(args.project_dir)
    slug: str | None = None
    source: dict | None = None
    out: Path | None = None
    action: str | None = args.mode
    error: TalkFailure | None = None
    try:
        slug = validate_slug(args.slug, operation_key="talk.render-silent")
        title = validate_text(args.title, "title", operation_key="talk.render-silent")
        date = validate_date(args.date, operation_key="talk.render-silent")
        media = validate_text(
            args.media, "media", operation_key="talk.render-silent", max_length=1000
        )
        signal = args.classification_signal
        if signal not in {"dead", "empty"}:
            raise _failure(
                "invalid_classification_signal",
                "silent rendering requires classification dead or empty",
                "talk.render-silent",
                exit_code=2,
            )
        expected = root / "vault" / "talks" / slug / "talk.md"
        out = expected
        input_path = (
            Path(args.transcript)
            if args.transcript
            else root / "vault" / "talks" / slug / "transcript.md"
        )
        if not input_path.is_absolute():
            input_path = root / input_path
        source = inspect_source(input_path, operation_key="talk.render-silent")
        if args.json:
            _relative_input(source, root, "talk.render-silent")
        requested_output = Path(args.output) if args.output else expected
        if not requested_output.is_absolute():
            requested_output = root / requested_output
        requested_output = safe_output(
            requested_output, root, operation_key="talk.render-silent"
        )
        if requested_output != expected:
            raise _failure(
                "invalid_output_path",
                "silent output must be vault/talks/{slug}/talk.md",
                "talk.render-silent",
                exit_code=2,
            )
        talk_dir = expected.parent
        content = build_silent_talk_md(
            title, date, media, minutes=args.minutes
        )
        out, action = write_silent_atomic(
            root,
            talk_dir,
            content,
            slug=slug,
            mode=args.mode,
        )
    except TalkFailure as exc:
        error = exc
    except Exception as exc:
        error = _failure(
            "render_failed",
            f"cannot render silent Talk: {exc}",
            "talk.render-silent",
            status="blocked",
            outcome="unknown",
        )
    if args.json:
        exists = out is not None and regular_file(out) and error is None
        receipt = {
            "schema_version": SILENT_SCHEMA,
            "key": "talk.render-silent",
            "effect": "writer",
            "status": error.status if error is not None else "succeeded",
            "attempt": 1,
            "material_key": _material_key(slug),
            "input_path": (
                _receipt_input(source, root, "talk.render-silent")
                if source is not None
                else None
            ),
            "output_path": (
                out.relative_to(root).as_posix() if out is not None else None
            ),
            "artifact_roles": ["canonical"],
            "classification_signal": args.classification_signal,
            "action": action,
            "output_sha256": sha256_file(out) if exists else None,
            "size": out.stat().st_size if exists else 0,
            "failure": error.as_dict() if error is not None else None,
        }
        emit_json(receipt)
    elif out is not None:
        print(json.dumps({"ok": True, "talk_path": str(out)}, ensure_ascii=False))
    else:
        print(json.dumps({"ok": False, "error": error.message if error else "render failed"}))
    return 0 if error is None else error.exit_code


def cmd_prepare_media(args) -> int:
    code, receipt = compress_media.run(args)
    if args.json:
        emit_json(receipt)
    elif receipt["status"] == "succeeded":
        if receipt["action"] == "reconciled":
            print(f"skip: output exists: {receipt['output_path']}")
        else:
            print(receipt["output_path"])
    else:
        print(receipt["failure"]["message"], file=sys.stderr)
    return code


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
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("classify", help="live/dead verdict from a transcript")
    c.add_argument("--slug")
    c.add_argument("--transcript")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_classify)

    s = sub.add_parser("silent", help="write the silent talk.md template")
    s.add_argument("--slug", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--date", required=True)
    s.add_argument("--media", required=True)
    s.add_argument("--minutes", default="?")
    s.add_argument("--transcript")
    s.add_argument(
        "--state",
        "--classification-signal",
        dest="classification_signal",
        choices=("dead", "empty"),
        default="dead",
    )
    s.add_argument("--mode", choices=("create", "repair"), default="create")
    s.add_argument("--output")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_silent)

    o = sub.add_parser("observe", help="read-only reconciliation observation")
    o.add_argument("--media", required=True)
    o.add_argument("--slug", required=True)
    o.add_argument("--title", required=True)
    o.add_argument("--date", required=True)
    o.add_argument("--engines", default=None)
    o.add_argument("--lang", default="auto")
    o.add_argument("--json", action="store_true")
    o.set_defaults(func=cmd_observe)

    p = sub.add_parser("prepare-media", help="atomically compress one recording")
    p.add_argument("--media", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--crf", default="28")
    p.add_argument("--preset", default="veryfast")
    p.add_argument("--audio-bitrate", default="96k")
    p.add_argument("--force", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_prepare_media)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

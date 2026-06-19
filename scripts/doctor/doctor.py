#!/usr/bin/env python3
"""Runtime healthcheck for quasi dependencies and external tools.

The doctor is intentionally stdlib-only so it can run even when quasi's shared
venv is missing or broken. Runtime Python packages are checked by spawning the
venv interpreter, not by importing them in this process.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

VERSION = "quasi-doctor.v1"
EXIT_CORE_FAILURE = 1
EXIT_USAGE = 2
EXIT_STRICT_OPTIONAL_FAILURE = 3

CORE_PYTHON_DEPS = [
    {"name": "requests", "import": "requests"},
    {"name": "beautifulsoup4", "import": "bs4"},
    {"name": "curl_cffi", "import": "curl_cffi"},
    {"name": "pydantic", "import": "pydantic"},
    {"name": "pyyaml", "import": "yaml"},
    {"name": "pymupdf", "import": "fitz"},
]

EXTERNAL_PROFILES = {
    "search": [
        {
            "name": "kagi",
            "kind": "command",
            "required": False,
            "reason": "Kagi CLI for Douban Chinese-edition discovery and paper recovery",
        },
    ],
    "extract": [
        {
            "name": "ocrmypdf",
            "kind": "command",
            "required": False,
            "reason": "OCR pipeline for scanned PDFs",
        },
        {
            "name": "tesseract",
            "kind": "command",
            "required": False,
            "reason": "OCR engine used by ocrmypdf",
        },
        {
            "name": "tesseract-lang:eng",
            "kind": "tesseract_language",
            "language": "eng",
            "required": False,
            "reason": "English OCR language data",
        },
        {
            "name": "tesseract-lang:chi_sim",
            "kind": "tesseract_language",
            "language": "chi_sim",
            "required": False,
            "reason": "Simplified Chinese OCR language data",
        },
        {
            "name": "pdftotext",
            "kind": "command",
            "required": False,
            "reason": "PDF first-page text verification fallback",
        },
    ],
    "transcribe": [
        {
            "name": "ffmpeg",
            "kind": "command",
            "required": False,
            "reason": "Audio extraction and talk media compression",
        },
        {
            "name": "ffmpeg-libx265",
            "kind": "ffmpeg_encoder",
            "encoder": "libx265",
            "required": False,
            "reason": "HEVC encoder used by talk media compression",
        },
        {
            "name": "whisper-cli",
            "kind": "command",
            "required": False,
            "reason": "Optional whisper.cpp transcription and language detection",
        },
        {
            "name": "swiftc",
            "kind": "command",
            "required": False,
            "reason": "Optional Apple SpeechTranscriber engine compiler on macOS",
        },
        {
            "name": "uvx",
            "kind": "command",
            "required": False,
            "reason": "Optional Parakeet MLX transcription engine launcher",
        },
    ],
    "translate": [],
    "orchestration": [
        {
            "name": "superset",
            "kind": "command",
            "required": False,
            "reason": "process-topic delegated agent dispatch",
        },
    ],
}

PROFILE_CHOICES = ["all", "core", *EXTERNAL_PROFILES.keys()]


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PLUGIN_DATA") or (Path.home() / ".cache" / "quasi"))


def venv_paths(root: Path, data: Path) -> dict[str, Path]:
    return {
        "venv": data / ".venv",
        "python": data / ".venv" / "bin" / "python",
        "requirements_source": root / "scripts" / "requirements.txt",
        "requirements_mirror": data / "requirements.txt",
    }


def check_requirements_sync(source: Path, mirror: Path, python_exists: bool) -> str:
    if not python_exists:
        return "venv_missing"
    if not source.exists():
        return "source_missing"
    if not mirror.exists():
        return "mirror_missing"
    try:
        return "ok" if source.read_bytes() == mirror.read_bytes() else "stale"
    except OSError:
        return "unknown"


def run_sync(root: Path) -> dict[str, Any]:
    script = root / "scripts" / "bootstrap-venv.sh"
    result = {
        "attempted": True,
        "script": str(script),
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "ok": False,
    }
    try:
        proc = subprocess.run(
            [str(script)],
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
            env=os.environ.copy(),
        )
    except Exception as exc:  # noqa: BLE001 - doctor should report, not crash
        result["stderr"] = f"{type(exc).__name__}: {exc}"
        return result
    result.update({
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "ok": proc.returncode == 0,
    })
    return result


def check_python_dep(python: Path, dep: dict[str, str], python_exists: bool) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": dep["name"],
        "import": dep["import"],
        "required": True,
    }
    if not python_exists:
        item.update({"status": "missing", "reason": "venv python missing"})
        return item
    code = (
        "import importlib, json; "
        f"m=importlib.import_module({dep['import']!r}); "
        "print(getattr(m, '__version__', '') or getattr(m, 'version', '') or '')"
    )
    try:
        proc = subprocess.run(
            [str(python), "-c", code],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        item.update({"status": "error", "reason": f"{type(exc).__name__}: {exc}"})
        return item
    if proc.returncode == 0:
        item.update({"status": "ok", "version": proc.stdout.strip()})
        return item
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    item.update({
        "status": "missing",
        "reason": detail[-1] if detail else f"import failed with exit {proc.returncode}",
    })
    return item


def check_command(spec: dict[str, Any]) -> dict[str, Any]:
    name = spec["name"]
    path = shutil.which(name)
    item = dict(spec)
    item["status"] = "ok" if path else "missing"
    if path:
        item["path"] = path
    return item


def check_ffmpeg_encoder(spec: dict[str, Any]) -> dict[str, Any]:
    item = dict(spec)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        item.update({"status": "missing", "reason": "ffmpeg command missing"})
        return item
    item["ffmpeg"] = ffmpeg
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        item.update({"status": "unknown", "reason": f"{type(exc).__name__}: {exc}"})
        return item
    body = (proc.stdout or "") + (proc.stderr or "")
    if spec.get("encoder") in body:
        item["status"] = "ok"
    else:
        item.update({"status": "missing", "reason": f"encoder {spec.get('encoder')} not listed"})
    return item


def tesseract_languages() -> tuple[set[str], str | None]:
    binary = shutil.which("tesseract")
    if not binary:
        return set(), "tesseract command missing"
    try:
        proc = subprocess.run(
            [binary, "--list-langs"],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return set(), f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return set(), detail[-1] if detail else f"exit {proc.returncode}"
    langs = {
        line.strip()
        for line in (proc.stdout or "").splitlines()
        if line.strip() and not line.startswith("List of available languages")
    }
    return langs, None


def check_tesseract_language(spec: dict[str, Any], cache: dict[str, Any]) -> dict[str, Any]:
    if "tesseract_languages" not in cache:
        langs, error = tesseract_languages()
        cache["tesseract_languages"] = langs
        cache["tesseract_error"] = error
    langs = cache["tesseract_languages"]
    error = cache.get("tesseract_error")
    lang = spec["language"]
    item = dict(spec)
    if error:
        item.update({"status": "missing", "reason": error})
    elif lang in langs:
        item["status"] = "ok"
    else:
        item.update({"status": "missing", "reason": f"language {lang} not listed"})
    return item


def check_external_spec(spec: dict[str, Any], cache: dict[str, Any]) -> dict[str, Any]:
    kind = spec.get("kind")
    if kind == "command":
        return check_command(spec)
    if kind == "ffmpeg_encoder":
        return check_ffmpeg_encoder(spec)
    if kind == "tesseract_language":
        return check_tesseract_language(spec, cache)
    item = dict(spec)
    item.update({"status": "unknown", "reason": f"unknown check kind: {kind}"})
    return item


def selected_profiles(profile: str) -> list[str]:
    if profile == "all":
        return list(EXTERNAL_PROFILES.keys())
    if profile == "core":
        return []
    return [profile]


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    root = plugin_root()
    data = data_dir()
    sync_result = run_sync(root) if args.sync else {"attempted": False}
    paths = venv_paths(root, data)
    python_exists = paths["python"].exists() and os.access(paths["python"], os.X_OK)
    requirements_sync = check_requirements_sync(
        paths["requirements_source"], paths["requirements_mirror"], python_exists
    )

    python_core = [check_python_dep(paths["python"], dep, python_exists) for dep in CORE_PYTHON_DEPS]
    external: dict[str, list[dict[str, Any]]] = {}
    cache: dict[str, Any] = {}
    for profile_name in selected_profiles(args.profile):
        external[profile_name] = [
            check_external_spec(spec, cache) for spec in EXTERNAL_PROFILES[profile_name]
        ]

    core_missing = [item["name"] for item in python_core if item.get("status") != "ok"]
    if requirements_sync not in {"ok"}:
        core_missing.append(f"requirements:{requirements_sync}")
    if sync_result.get("attempted") and not sync_result.get("ok"):
        core_missing.append("sync_failed")

    optional_missing: list[str] = []
    for items in external.values():
        for item in items:
            if not item.get("required") and item.get("status") != "ok":
                optional_missing.append(item["name"])

    core_ok = not core_missing
    strict_optional_fail = bool(args.strict and optional_missing)
    status = "ok" if core_ok and not strict_optional_fail else "error"

    return {
        "version": VERSION,
        "status": status,
        "profile": args.profile,
        "strict": args.strict,
        "plugin_root": str(root),
        "data_dir": str(data),
        "sync": sync_result,
        "venv": {
            "path": str(paths["venv"]),
            "python": str(paths["python"]),
            "exists": paths["venv"].exists(),
            "python_executable": python_exists,
            "requirements_source": str(paths["requirements_source"]),
            "requirements_mirror": str(paths["requirements_mirror"]),
            "requirements_sync": requirements_sync,
        },
        "python": {
            "interpreter": str(paths["python"]),
            "core": python_core,
        },
        "external": external,
        "summary": {
            "core_ok": core_ok,
            "core_missing": core_missing,
            "optional_missing": optional_missing,
        },
    }


def status_prefix(status: str) -> str:
    return {
        "ok": "ok",
        "missing": "missing",
        "error": "error",
        "unknown": "unknown",
    }.get(status, status)


def print_text(report: dict[str, Any]) -> None:
    print("quasi doctor")
    if report.get("sync", {}).get("attempted"):
        sync = report["sync"]
        print("\nsync:")
        print(f"  status: {'ok' if sync.get('ok') else 'failed'}")
        print(f"  returncode: {sync.get('returncode')}")
        if sync.get("stderr"):
            for line in sync["stderr"].rstrip().splitlines():
                print(f"  stderr: {line}")
    venv = report["venv"]
    print("\nvenv:")
    print(f"  data_dir: {report['data_dir']}")
    print(f"  python: {venv['python']}")
    print(f"  exists: {'yes' if venv['exists'] else 'no'}")
    print(f"  requirements_sync: {venv['requirements_sync']}")

    print("\npython dependencies:")
    print("  core:")
    for item in report["python"]["core"]:
        suffix = f" ({item['reason']})" if item.get("reason") else ""
        version = f" {item['version']}" if item.get("version") else ""
        print(f"    {status_prefix(item['status'])} {item['name']} -> {item['import']}{version}{suffix}")

    if report["external"]:
        print("\nexternal tools:")
        for profile, items in report["external"].items():
            print(f"  {profile}:")
            if not items:
                print("    ok no system-tool checks")
            for item in items:
                path = f" ({item['path']})" if item.get("path") else ""
                reason = f" — {item['reason']}" if item.get("reason") else ""
                print(f"    {status_prefix(item['status'])} {item['name']}{path}{reason}")

    summary = report["summary"]
    print("\nsummary:")
    print(f"  status: {report['status']}")
    print(f"  core: {'ok' if summary['core_ok'] else 'needs attention'}")
    if summary["core_missing"]:
        print(f"  core_missing: {', '.join(summary['core_missing'])}")
    if summary["optional_missing"]:
        print(f"  optional_missing: {', '.join(summary['optional_missing'])}")
    else:
        print("  optional_missing: none")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="quasi-doctor",
        description="Check quasi venv sync, core Python dependencies, and optional external tools.",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--sync", action="store_true", help="run scripts/bootstrap-venv.sh before checking")
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default="all",
        help="limit optional external checks to one profile (default: all)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return nonzero for missing optional tools in the selected profile",
    )
    return parser.parse_args(argv)


def exit_code(report: dict[str, Any]) -> int:
    if not report["summary"]["core_ok"]:
        return EXIT_CORE_FAILURE
    if report["strict"] and report["summary"]["optional_missing"]:
        return EXIT_STRICT_OPTIONAL_FAILURE
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(args)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_text(report)
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())

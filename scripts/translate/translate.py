#!/usr/bin/env python3
"""Public strict/legacy entrypoint for one transactional PDF translation."""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
sys.path.insert(0, str(SCRIPT_ROOT))

# urllib3 v2 warns during import on the plugin's current macOS Python 3.9
# fallback.  The strict command surface must remain one JSON object, so suppress
# only that import-time compatibility warning (provider failures remain visible
# through typed receipts).
warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*",
)

from translate import coverage  # noqa: E402
from translate import immersive_translate as immersive  # noqa: E402
from translate import pdf2zh_translate as pdf2zh  # noqa: E402
from translate import tounicode  # noqa: E402
from translate.translate_commit import (  # noqa: E402
    TranslateContractError,
    contract_failure_receipt,
    fingerprint,
    observe,
    run_transaction,
    validate_language,
)


BACKENDS = {"immersive", "pdf2zh"}


def provider_target_language(target_language: str) -> str:
    canonical = validate_language(target_language)
    return "zh-CN" if canonical == "zh" else canonical


def _public_base_url(value: str) -> str:
    if not value:
        return ""
    normalised = pdf2zh.normalise_base_url(value)
    parts = urlsplit(normalised)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def backend_config_fingerprint(backend: str, target_language: str) -> str:
    provider_language = provider_target_language(target_language)
    if backend == "immersive":
        public = {
            key: value
            for key, value in immersive.DEFAULT_SETTINGS.items()
            if key != "auth_key"
        }
        public["target_language"] = provider_language
        return fingerprint({"backend": backend, "settings": public})
    if backend == "pdf2zh":
        configured_base = os.environ.get("QUASI_TRANSLATE_BASE_URL", "").strip()
        try:
            public_base = _public_base_url(configured_base)
        except immersive.TranslationError:
            public_base = "<invalid>"
        return fingerprint(
            {
                "backend": backend,
                "base_url": public_base,
                "model": os.environ.get("QUASI_TRANSLATE_MODEL", "").strip(),
                "package": pdf2zh.PDF2ZH_SPEC,
                "target_language": provider_language,
            }
        )
    raise TranslateContractError("translation.invalid_backend", f"unknown backend: {backend}")


def missing_configuration(backend: str) -> list[str]:
    if backend == "immersive":
        return (
            []
            if os.environ.get("QUASI_IMMERSIVE_AUTH_KEY", "").strip()
            else ["immersive_auth_key"]
        )
    if backend == "pdf2zh":
        fields = [
            ("QUASI_TRANSLATE_BASE_URL", "translate_base_url"),
            ("QUASI_TRANSLATE_API_KEY", "translate_api_key"),
            ("QUASI_TRANSLATE_MODEL", "translate_model"),
        ]
        missing = [
            public
            for environment, public in fields
            if not os.environ.get(environment, "").strip()
        ]
        configured_base = os.environ.get("QUASI_TRANSLATE_BASE_URL", "").strip()
        if configured_base:
            try:
                _public_base_url(configured_base)
            except immersive.TranslationError:
                missing.append("translate_base_url")
        return sorted(set(missing))
    return ["translate_backend"]


def backend_runner(backend: str):
    if backend == "immersive":

        def run(
            source: Path,
            candidate: Path,
            target_language: str,
            generation_dir: Path,
            on_state,
        ) -> dict[str, Any]:
            return immersive.translate_to_candidate(
                source_pdf=source,
                candidate_pdf=candidate,
                target_language=provider_target_language(target_language),
                work_dir=generation_dir,
                on_state=on_state,
            )

        return run
    if backend == "pdf2zh":

        def run(
            source: Path,
            candidate: Path,
            target_language: str,
            generation_dir: Path,
            on_state,
        ) -> dict[str, Any]:
            return pdf2zh.translate_to_candidate(
                source_pdf=source,
                candidate_pdf=candidate,
                target_language=provider_target_language(target_language),
                work_dir=generation_dir / "pdf2zh",
                on_state=on_state,
            )

        return run
    raise TranslateContractError("translation.invalid_backend", f"unknown backend: {backend}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Observe or run one fenced Quasi translation transaction.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("observe", "run"):
        child = subparsers.add_parser(command)
        child.add_argument("slug")
        # Parse only to return a typed failure.  Strict backend ownership stays
        # with QUASI_TRANSLATE_BACKEND.
        child.add_argument("--backend", dest="backend_override", help=argparse.SUPPRESS)
        child.add_argument("--source-file", type=Path, required=command == "run")
        child.add_argument("--target-language", required=True)
        child.add_argument("--toc-json", type=Path)
        child.add_argument(
            "--toc-page-side",
            choices=sorted(immersive.TOC_PAGE_SIDES),
            default="original",
        )
        child.add_argument("--json", action="store_true")
    observe_parser = subparsers.choices["observe"]
    observe_parser.add_argument("--mode", choices=("initial", "recovery", "final"), required=True)
    observe_parser.add_argument("--decision-path", type=Path)
    observe_parser.add_argument("--decision-sha256")
    observe_parser.add_argument("--candidates-fingerprint")
    run_parser = subparsers.choices["run"]
    run_parser.add_argument("--attempt", type=int, choices=(1, 2), required=True)
    run_parser.add_argument("--expected-source-sha256", required=True)

    legacy = subparsers.add_parser("legacy")
    legacy.add_argument("slug")
    legacy.add_argument("--source-file", type=Path)
    legacy.add_argument("--target-language", default="zh-CN")
    legacy.add_argument("--toc-json", type=Path)
    legacy.add_argument(
        "--toc-page-side",
        choices=sorted(immersive.TOC_PAGE_SIDES),
        default="original",
    )
    legacy.add_argument("--json", action="store_true")
    return parser


def _configured_backend() -> str:
    return os.environ.get("QUASI_TRANSLATE_BACKEND", "immersive").strip()


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "backend_override", None) is not None:
        raise TranslateContractError(
            "translation.backend_override_forbidden",
            "strict observe/run take backend only from plugin configuration",
        )
    target_language = validate_language(args.target_language)
    backend = args.backend
    config_fingerprint = backend_config_fingerprint(backend, target_language)
    common = {
        "project_root": Path.cwd(),
        "slug": args.slug,
        "backend": backend,
        "target_language": target_language,
        "source_file": args.source_file,
        "toc_json": args.toc_json,
        "toc_page_side": args.toc_page_side,
        "config_fingerprint": config_fingerprint,
        "configuration_missing": missing_configuration(backend),
    }
    if args.command == "observe":
        return observe(
            **common,
            mode=args.mode,
            decision_path=args.decision_path,
            decision_sha256=args.decision_sha256,
            candidates_fingerprint=args.candidates_fingerprint,
        )
    return run_transaction(
        **common,
        expected_source_sha256=args.expected_source_sha256,
        attempt=args.attempt,
        backend_runner=backend_runner(backend),
        add_toc=immersive.add_toc_to_split_pdf,
        repair_tounicode=tounicode.repair_pdf,
        check_coverage=coverage.check,
    )


def execute_legacy(args: argparse.Namespace) -> dict[str, Any]:
    """Compatibility adapter; publication still uses the strict transaction."""
    target_language = validate_language(args.target_language)
    backend = args.backend
    config_fingerprint = backend_config_fingerprint(backend, target_language)
    missing = missing_configuration(backend)
    observed = observe(
        project_root=Path.cwd(),
        slug=args.slug,
        backend=backend,
        target_language=target_language,
        source_file=args.source_file,
        toc_json=args.toc_json,
        toc_page_side=args.toc_page_side,
        config_fingerprint=config_fingerprint,
        configuration_missing=missing,
        mode="initial",
    )
    if observed["status"] != "succeeded" or observed["signal"] != "missing":
        return observed
    source_path = Path.cwd() / observed["source_path"]
    return run_transaction(
        project_root=Path.cwd(),
        slug=args.slug,
        backend=backend,
        target_language=target_language,
        source_file=source_path,
        expected_source_sha256=observed["source_sha256"],
        toc_json=args.toc_json,
        toc_page_side=args.toc_page_side,
        attempt=1,
        config_fingerprint=config_fingerprint,
        configuration_missing=missing,
        backend_runner=backend_runner(backend),
        add_toc=immersive.add_toc_to_split_pdf,
        repair_tounicode=tounicode.repair_pdf,
        check_coverage=coverage.check,
    )


def _failure(args: argparse.Namespace, code: str, message: object) -> dict[str, Any]:
    return contract_failure_receipt(
        command="observe" if args.command == "observe" else "run",
        project_root=Path.cwd(),
        backend=args.backend,
        slug=args.slug,
        target_language=args.target_language,
        attempt=getattr(args, "attempt", 1),
        mode=getattr(args, "mode", "initial"),
        toc_json=getattr(args, "toc_json", None),
        toc_page_side=getattr(args, "toc_page_side", "original"),
        source_file=getattr(args, "source_file", None),
        code=code,
        message=message,
    )


def _print_legacy(receipt: dict[str, Any]) -> None:
    if receipt["status"] != "succeeded":
        failure = receipt.get("failure") or {}
        print(failure.get("message") or failure.get("code") or "translation failed", file=sys.stderr)
        return
    print("TRANSLATE_RESULT:")
    print(f"- slug: {receipt['slug']}")
    source = receipt.get("input_path") or receipt.get("source_path")
    print(f"- source_pdf: {source}")
    print("- pdf_id: -")
    print(f"- final_pdf: {receipt['output_path']}")
    print(f"- toc_entries: {receipt['toc_entries']}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.backend = _configured_backend()
    if args.backend not in BACKENDS:
        receipt = _failure(
            args,
            "translation.invalid_backend",
            f"unknown configured backend: {args.backend}",
        )
    else:
        try:
            receipt = execute_legacy(args) if args.command == "legacy" else execute(args)
        except TranslateContractError as exc:
            receipt = _failure(args, exc.code, exc)
        except Exception as exc:
            receipt = _failure(args, "translation.internal_error", exc)
    if args.command == "legacy" and not args.json:
        _print_legacy(receipt)
    else:
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    if receipt["status"] == "succeeded":
        return 0
    return 2 if receipt["status"] == "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())

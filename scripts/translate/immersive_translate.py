#!/usr/bin/env python3
"""Translate a Quasi PDF through Immersive Translate's Zotero API.

This script intentionally mirrors the Zotero plugin's request flow:

1. Validate the project-local auth key.
2. Fetch a pre-signed PDF upload URL.
3. Upload the local PDF.
4. Create a translation task.
5. Poll the task until completion.
6. Download bilingual and translation-only PDFs into processing/.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from getpass import getpass
from pathlib import Path
from typing import Any

import pymupdf
import requests


PROJECT_ROOT = Path.cwd()  # caller's research project root
CONFIG_PATH = PROJECT_ROOT / "config" / "immersive-translate.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "processing" / "translations"

DEFAULT_SETTINGS = {
    "auth_key": "",
    "api_base_url": "https://api2.immersivetranslate.com/zotero",
    "target_language": "zh-CN",
    "translate_model": "kimi+qwen",
    "enhance_compatibility": False,
    "ocr_workaround": "auto",
    "auto_extract_glossary": False,
    "rich_text_translate": True,
    "primary_font_family": "none",
    "dual_mode": "lort",
    "custom_system_prompt": "",
    "layout_model": "version_3",
}


class TranslationError(RuntimeError):
    """Base error for translation flow failures."""


class MissingAuthKeyError(TranslationError):
    """Raised when config does not contain a usable auth key."""


class SourceNotFoundError(TranslationError):
    """Raised when the source PDF cannot be located."""


class AmbiguousSourceError(TranslationError):
    """Raised when more than one plausible source PDF is found."""

    def __init__(self, slug: str, candidates: list[Path]):
        self.slug = slug
        self.candidates = candidates
        joined = "\n".join(f"- {candidate}" for candidate in candidates)
        super().__init__(f"Multiple PDF candidates found for '{slug}':\n{joined}")


def load_settings(raw_config: dict[str, Any] | None) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    if raw_config:
        settings.update({key: value for key, value in raw_config.items() if value is not None})
    return settings


def read_config(config_path: Path = CONFIG_PATH) -> dict[str, Any] | None:
    if not config_path.exists():
        return None
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise TranslationError(f"Failed to read config from {config_path}: {exc}") from exc


def write_config(settings: dict[str, Any], config_path: Path = CONFIG_PATH) -> None:
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as handle:
            json.dump(settings, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError as exc:
        raise TranslationError(f"Failed to write config to {config_path}: {exc}") from exc


def load_settings_from_disk(
    config_path: Path = CONFIG_PATH,
    *,
    prompt_for_auth: bool = False,
) -> dict[str, Any]:
    settings = load_settings(read_config(config_path))
    auth_key = str(settings.get("auth_key", "")).strip()
    if auth_key:
        settings["auth_key"] = auth_key
        return settings

    if prompt_for_auth and sys.stdin.isatty():
        auth_key = getpass("Immersive Translate auth key: ").strip()
        if not auth_key:
            raise MissingAuthKeyError(
                f"No auth key provided. Populate {config_path} with an auth_key.",
            )
        settings["auth_key"] = auth_key
        write_config(settings, config_path)
        return settings

    raise MissingAuthKeyError(
        f"Missing auth_key in {config_path}. Create the file or let the agent write it before retrying.",
    )


def resolve_source_pdf(
    slug: str,
    *,
    project_root: Path = PROJECT_ROOT,
    explicit_source: Path | None = None,
) -> Path:
    if explicit_source is not None:
        source = explicit_source.expanduser().resolve()
        if not source.exists():
            raise SourceNotFoundError(f"Source file does not exist: {source}")
        if source.suffix.lower() != ".pdf":
            raise SourceNotFoundError(f"Source file is not a PDF: {source}")
        return source

    exact = project_root / "sources" / f"{slug}.pdf"
    if exact.exists():
        return exact

    epub_candidate = project_root / "sources" / f"{slug}.epub"
    if epub_candidate.exists():
        raise SourceNotFoundError(
            f"Found EPUB but no PDF for '{slug}'. Convert or supply a PDF path explicitly.",
        )

    candidates = sorted(
        {
            path.resolve()
            for path in project_root.glob(f"processing/**/{slug}.pdf")
            if path.is_file()
        },
    )
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise AmbiguousSourceError(slug, candidates)

    raise SourceNotFoundError(
        f"Could not locate a PDF for '{slug}'. Expected sources/{slug}.pdf or an explicit --source-file.",
    )


def build_output_paths(
    *,
    slug: str,
    target_language: str,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Path]:
    output_dir = project_root / "processing" / "translations" / slug
    return {
        "output_dir": output_dir,
        "dual_pdf": output_dir / f"{slug}_{target_language}_dual.pdf",
        "translation_pdf": output_dir / f"{slug}_{target_language}_translation.pdf",
        "split_pdf": output_dir / f"{slug}_{target_language}_split.pdf",
    }


def split_dual_pdf(
    src_path: Path,
    dst_path: Path,
    *,
    split_point: float | None = None,
) -> Path:
    """Split each page of a dual-language PDF at its horizontal midpoint.

    The Immersive Translate dual PDF places the original and translated pages
    side-by-side on a single wide page.  This function cuts each page in half
    so the output has 2× the pages: left-half then right-half for every
    original page.
    """
    src = pymupdf.open(str(src_path))
    dst = pymupdf.open()

    for page_num in range(len(src)):
        page = src[page_num]
        rect = page.rect
        mid_x = split_point if split_point is not None else (rect.width / 2)

        left_clip = pymupdf.Rect(0, 0, mid_x, rect.height)
        left_page = dst.new_page(width=mid_x, height=rect.height)
        left_page.show_pdf_page(left_page.rect, src, page_num, clip=left_clip)

        right_clip = pymupdf.Rect(mid_x, 0, rect.width, rect.height)
        right_page = dst.new_page(width=rect.width - mid_x, height=rect.height)
        right_page.show_pdf_page(right_page.rect, src, page_num, clip=right_clip)

    dst.save(str(dst_path))
    dst.close()
    src.close()
    return dst_path


class ImmersiveTranslateClient:
    def __init__(self, settings: dict[str, Any], *, timeout: int = 60):
        self.settings = settings
        self.timeout = timeout
        self.session = requests.Session()

    @property
    def api_base_url(self) -> str:
        return str(self.settings["api_base_url"]).rstrip("/")

    @property
    def auth_key(self) -> str:
        return str(self.settings["auth_key"])

    def _api_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth_key}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expect_json: bool = True,
        retries: int = 0,
    ) -> Any:
        attempt = 0
        final_url = url if url.startswith("http") else f"{self.api_base_url}{url}"
        request_headers = dict(headers or {})
        if not url.startswith("http"):
            request_headers = {**self._api_headers(), **request_headers}

        while True:
            try:
                response = self.session.request(
                    method=method,
                    url=final_url,
                    params=params,
                    json=json_body,
                    headers=request_headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                if not expect_json:
                    return response.content

                data = response.json()
                if isinstance(data, dict) and "code" in data:
                    if data["code"] != 0:
                        message = data.get("message") or data.get("error") or f"API code {data['code']}"
                        raise TranslationError(str(message))
                    return data.get("data", data)
                return data
            except (requests.RequestException, ValueError) as exc:
                # Match the official Zotero plugin: never retry 4xx client errors
                if isinstance(exc, requests.HTTPError) and exc.response is not None and 400 <= exc.response.status_code < 500:
                    raise TranslationError(str(exc)) from exc
                if attempt >= retries:
                    raise TranslationError(str(exc)) from exc
                attempt += 1
                time.sleep(1)

    def check_auth_key(self) -> bool:
        result = self._request(
            "GET",
            "/check-key",
            params={"apiKey": self.auth_key},
        )
        return bool(result)

    def get_pdf_upload_url(self) -> dict[str, Any]:
        return self._request("GET", "/pdf-upload-url", retries=3)

    def upload_pdf(self, upload_url: str, pdf_path: Path) -> None:
        try:
            with pdf_path.open("rb") as handle:
                data = handle.read()
            headers = {"Content-Type": "application/pdf"}
            response = self.session.put(upload_url, data=data, headers=headers, timeout=self.timeout)
            response.raise_for_status()
        except (OSError, requests.RequestException) as exc:
            raise TranslationError(f"Failed to upload PDF {pdf_path}: {exc}") from exc

    def create_translate_task(self, object_key: str, source_pdf: Path) -> str:
        ocr_mode = str(self.settings["ocr_workaround"]).lower()
        payload = {
            "objectKey": object_key,
            "pdfOptions": {"conversion_formats": {"html": True}},
            "fileName": source_pdf.name,
            "targetLanguage": self.settings["target_language"],
            "requestModel": self.settings["translate_model"],
            "enhance_compatibility": bool(self.settings["enhance_compatibility"]),
            "OCRWorkaround": ocr_mode == "true",
            "autoEnableOcrWorkAround": ocr_mode == "auto",
            "autoExtractGlossary": bool(self.settings["auto_extract_glossary"]),
            "disable_rich_text_translate": not bool(self.settings["rich_text_translate"]),
            "primaryFontFamily": self.settings["primary_font_family"],
            "dual_mode": self.settings["dual_mode"],
            "customSystemPrompt": self.settings["custom_system_prompt"] or None,
            "layout_model_id": self.settings["layout_model"],
        }
        return str(
            self._request(
                "POST",
                "/backend-babel-pdf",
                json_body=payload,
                retries=3,
            ),
        )

    def get_translate_status(self, pdf_id: str) -> dict[str, Any]:
        return self._request("GET", f"/pdf/{pdf_id}/process", retries=10)

    def get_translate_result(self, pdf_id: str) -> dict[str, Any]:
        return self._request("GET", f"/pdf/{pdf_id}/temp-url", retries=3)

    def download_binary(self, url: str) -> bytes:
        return bytes(self._request("GET", url, expect_json=False, retries=3))


def poll_until_complete(
    client: ImmersiveTranslateClient,
    pdf_id: str,
    *,
    interval_seconds: int = 10,
    max_polls: int = 180,
) -> dict[str, Any]:
    for _ in range(max_polls):
        status = client.get_translate_status(pdf_id)
        status_value = str(status.get("status") or "").lower()
        if status_value == "ok" and status.get("overall_progress") == 100:
            return status
        # Any non-empty, non-"ok" status is a terminal failure (matches the official Zotero plugin)
        if status_value and status_value != "ok":
            message = status.get("message") or status.get("status")
            raise TranslationError(f"Translation failed for {pdf_id}: {message}")
        time.sleep(interval_seconds)
    raise TranslationError(f"Timed out waiting for translation task {pdf_id}")


def download_outputs(
    client: ImmersiveTranslateClient,
    pdf_id: str,
    outputs: dict[str, Path],
) -> dict[str, Path]:
    result = client.get_translate_result(pdf_id)
    dual_url = result.get("translationDualPdfOssUrl")
    translation_url = result.get("translationOnlyPdfOssUrl")
    if not dual_url or not translation_url:
        raise TranslationError(f"Missing result URLs for translation task {pdf_id}")

    try:
        outputs["output_dir"].mkdir(parents=True, exist_ok=True)
        outputs["dual_pdf"].write_bytes(client.download_binary(dual_url))
        outputs["translation_pdf"].write_bytes(client.download_binary(translation_url))
    except OSError as exc:
        raise TranslationError(
            f"Failed to write translated PDFs into {outputs['output_dir']}: {exc}",
        ) from exc
    return outputs


def translate_slug(
    slug: str,
    *,
    source_file: Path | None = None,
    config_path: Path = CONFIG_PATH,
    target_language: str | None = None,
    project_root: Path = PROJECT_ROOT,
    prompt_for_auth: bool = False,
    poll_interval: int = 10,
    max_polls: int = 180,
    split_dual: bool = False,
) -> dict[str, Any]:
    settings = load_settings_from_disk(config_path, prompt_for_auth=prompt_for_auth)
    if target_language:
        settings["target_language"] = target_language

    source_pdf = resolve_source_pdf(slug, project_root=project_root, explicit_source=source_file)
    outputs = build_output_paths(
        slug=slug,
        target_language=str(settings["target_language"]),
        project_root=project_root,
    )

    client = ImmersiveTranslateClient(settings)
    if not client.check_auth_key():
        raise TranslationError("Immersive Translate auth key check failed")

    upload_info = client.get_pdf_upload_url()
    upload_result = upload_info.get("result") or {}
    upload_url = upload_result.get("preSignedURL")
    object_key = upload_result.get("objectKey")
    if not upload_url or not object_key:
        raise TranslationError("Upload URL response did not include preSignedURL/objectKey")

    client.upload_pdf(upload_url, source_pdf)
    pdf_id = client.create_translate_task(object_key, source_pdf)
    poll_until_complete(
        client,
        pdf_id,
        interval_seconds=poll_interval,
        max_polls=max_polls,
    )
    download_outputs(client, pdf_id, outputs)

    if split_dual:
        split_dual_pdf(outputs["dual_pdf"], outputs["split_pdf"])

    return {
        "slug": slug,
        "source_pdf": source_pdf,
        "pdf_id": pdf_id,
        **outputs,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Translate a Quasi PDF via Immersive Translate's Zotero API.",
    )
    parser.add_argument("slug", help="Quasi slug used to locate the source PDF")
    parser.add_argument(
        "--source-file",
        type=Path,
        help="Explicit PDF path when slug resolution is ambiguous or unavailable",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=CONFIG_PATH,
        help="Project-local Immersive Translate config path",
    )
    parser.add_argument(
        "--target-language",
        help="Override the target language from config/immersive-translate.json",
    )
    parser.add_argument(
        "--prompt-for-auth",
        action="store_true",
        help="Prompt in-terminal for a missing auth key and write config/immersive-translate.json",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=10,
        help="Polling interval in seconds",
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=180,
        help="Maximum polling attempts before timing out",
    )
    parser.add_argument(
        "--split-dual",
        action="store_true",
        help="Split the dual PDF into single-language pages after translation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = translate_slug(
            slug=args.slug,
            source_file=args.source_file,
            config_path=args.config_path,
            target_language=args.target_language,
            prompt_for_auth=args.prompt_for_auth,
            poll_interval=args.poll_interval,
            max_polls=args.max_polls,
            split_dual=args.split_dual,
        )
    except AmbiguousSourceError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except SourceNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except MissingAuthKeyError as exc:
        print(str(exc), file=sys.stderr)
        return 5
    except TranslationError as exc:
        print(str(exc), file=sys.stderr)
        return 6

    print("TRANSLATE_RESULT:")
    print(f"- slug: {result['slug']}")
    print(f"- source_pdf: {result['source_pdf']}")
    print(f"- pdf_id: {result['pdf_id']}")
    print(f"- dual_pdf: {result['dual_pdf']}")
    print(f"- translation_pdf: {result['translation_pdf']}")
    print(f"- split_pdf: {result['split_pdf']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
